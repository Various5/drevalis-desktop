"""Episode service — business logic extracted from route handlers.

Owns Episode + GenerationJob + MediaAsset repositories plus the arq
enqueue / Redis cancel-flag bookkeeping for the episode lifecycle.

Layering: keeps the episodes route file free of repository imports
(audit F-A-01).
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.episode import Episode
from drevalis.models.generation_job import GenerationJob
from drevalis.repositories.episode import EpisodeRepository
from drevalis.repositories.generation_job import GenerationJobRepository
from drevalis.repositories.media_asset import MediaAssetRepository
from drevalis.schemas.script import EpisodeScript

log = structlog.get_logger(__name__)


# Pipeline steps in execution order (kept in sync with PipelineOrchestrator).
PIPELINE_STEPS: list[str] = [
    "script",
    "voice",
    "scenes",
    "captions",
    "assembly",
    "thumbnail",
]


# ── Domain exceptions ────────────────────────────────────────────────────


class EpisodeNotFoundError(Exception):
    def __init__(self, episode_id: UUID) -> None:
        self.episode_id = episode_id
        super().__init__(f"Episode {episode_id} not found")


class EpisodeNoScriptError(Exception):
    def __init__(self, episode_id: UUID) -> None:
        self.episode_id = episode_id
        super().__init__(f"Episode {episode_id} has no script")


class EpisodeInvalidStatusError(Exception):
    def __init__(self, episode_id: UUID, current_status: str, allowed: list[str]) -> None:
        self.episode_id = episode_id
        self.current_status = current_status
        self.allowed = allowed
        super().__init__(
            f"Episode {episode_id} has status '{current_status}', expected one of {allowed}"
        )


class ConcurrencyCapReachedError(Exception):
    def __init__(self, max_slots: int) -> None:
        self.max_slots = max_slots
        super().__init__(
            f"Maximum concurrent generations ({max_slots}) reached. "
            "Please wait for existing jobs to complete."
        )


class SceneNotFoundError(Exception):
    def __init__(self, scene_number: int) -> None:
        self.scene_number = scene_number
        super().__init__(f"Scene {scene_number} not found")


class ScriptValidationError(Exception):
    """Wraps an underlying validator error so the route can return 422."""


class NoFailedJobError(Exception):
    """Raised by retry() when there's no failed job to re-enqueue."""


# ── Concurrency-slot cache (process-local, 60s TTL) ──────────────────────


_slot_cache: dict[str, Any] = {"value": None, "expires": 0.0}


# ── Service ──────────────────────────────────────────────────────────────


class EpisodeService:
    """Episode lifecycle + script editing + generation orchestration.

    Does NOT import FastAPI. Raises domain exceptions; routes map them
    to HTTP status codes.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._ep_repo = EpisodeRepository(db)
        self._job_repo = GenerationJobRepository(db)
        self._asset_repo = MediaAssetRepository(db)

    # ── Fetch helpers ───────────────────────────────────────────────

    async def get_or_raise(self, episode_id: UUID) -> Episode:
        episode = await self._ep_repo.get_by_id(episode_id)
        if episode is None:
            raise EpisodeNotFoundError(episode_id)
        return episode

    async def get_with_assets_or_raise(self, episode_id: UUID) -> Episode:
        episode = await self._ep_repo.get_with_assets(episode_id)
        if episode is None:
            raise EpisodeNotFoundError(episode_id)
        return episode

    async def get_with_script_or_raise(self, episode_id: UUID) -> tuple[Episode, EpisodeScript]:
        episode = await self.get_or_raise(episode_id)
        if not episode.script:
            raise EpisodeNoScriptError(episode_id)
        script = EpisodeScript.model_validate(episode.script)
        return episode, script

    # ── Generic CRUD ────────────────────────────────────────────────

    async def list_recent(self, limit: int) -> list[Episode]:
        return list(await self._ep_repo.get_recent(limit=limit))

    async def list_filtered(
        self,
        *,
        series_id: UUID | None,
        status_filter: str | None,
        offset: int,
        limit: int,
    ) -> list[Episode]:
        if series_id is not None:
            return list(
                await self._ep_repo.get_by_series(
                    series_id=series_id,
                    status_filter=status_filter,
                    offset=offset,
                    limit=limit,
                )
            )
        if status_filter is not None:
            return list(await self._ep_repo.get_by_status(status=status_filter, limit=limit))
        return list(await self._ep_repo.get_all(offset=offset, limit=limit))

    async def create(
        self,
        *,
        series_id: UUID,
        title: str,
        topic: str | None,
    ) -> Episode:
        episode = await self._ep_repo.create(
            series_id=series_id,
            title=title,
            topic=topic,
            status="draft",
        )
        await self._db.commit()
        await self._db.refresh(episode)
        full = await self._ep_repo.get_with_assets(episode.id)
        assert full is not None
        return full

    async def update(self, episode_id: UUID, update_data: dict[str, Any]) -> Episode:
        if not update_data:
            raise ScriptValidationError("No fields to update")

        if "script" in update_data and update_data["script"] is not None:
            try:
                EpisodeScript.model_validate(update_data["script"])
            except Exception as exc:
                raise ScriptValidationError(f"Invalid script format: {exc}") from exc

        episode = await self._ep_repo.update(episode_id, **update_data)
        if episode is None:
            raise EpisodeNotFoundError(episode_id)
        await self._db.commit()
        full = await self._ep_repo.get_with_assets(episode.id)
        assert full is not None
        return full

    async def delete(self, episode_id: UUID, *, storage_delete_dir: Any | None = None) -> None:
        episode = await self._ep_repo.get_by_id(episode_id)
        if episode is None:
            raise EpisodeNotFoundError(episode_id)
        if storage_delete_dir is not None:
            await storage_delete_dir(episode_id)
        await self._ep_repo.delete(episode_id)
        await self._db.commit()

    async def duplicate(self, episode_id: UUID) -> Episode:
        episode = await self.get_or_raise(episode_id)
        new_episode = await self._ep_repo.create(
            series_id=episode.series_id,
            title=f"{episode.title} (copy)",
            topic=episode.topic,
            status="draft",
            script=episode.script,
            override_voice_profile_id=episode.override_voice_profile_id,
            override_llm_config_id=episode.override_llm_config_id,
        )
        await self._db.commit()
        await self._db.refresh(new_episode)
        full = await self._ep_repo.get_with_assets(new_episode.id)
        assert full is not None
        log.info(
            "episode_duplicated",
            source_episode_id=str(episode_id),
            new_episode_id=str(new_episode.id),
        )
        return full

    async def reset_to_draft(self, episode_id: UUID) -> int:
        episode = await self._ep_repo.get_by_id(episode_id)
        if episode is None:
            raise EpisodeNotFoundError(episode_id)

        count_result = await self._db.execute(
            sa_select(sa_func.count())
            .select_from(GenerationJob)
            .where(GenerationJob.episode_id == episode_id)
        )
        deleted_jobs = count_result.scalar() or 0
        await self._db.execute(
            sa_delete(GenerationJob).where(GenerationJob.episode_id == episode_id)
        )
        await self._ep_repo.update_status(episode_id, "draft")
        await self._db.commit()

        log.info("episode_reset", episode_id=str(episode_id), jobs_deleted=deleted_jobs)
        return deleted_jobs

    # ── Concurrency gate ────────────────────────────────────────────

    async def get_dynamic_max_slots(self, base_max: int) -> int:
        if _slot_cache["value"] is not None and time.time() < _slot_cache["expires"]:
            return int(_slot_cache["value"])
        result = base_max
        try:
            from drevalis.repositories.comfyui import ComfyUIServerRepository

            servers = await ComfyUIServerRepository(self._db).get_active_servers()
            if len(servers) > 1:
                result = base_max + (len(servers) - 1) * 2
        except Exception:
            pass
        _slot_cache["value"] = result
        _slot_cache["expires"] = time.time() + 60
        return result

    async def check_generation_slots(self, base_max: int) -> int:
        max_slots = await self.get_dynamic_max_slots(base_max)
        generating_count = await self._ep_repo.count_by_status("generating")
        if generating_count >= max_slots:
            raise ConcurrencyCapReachedError(max_slots)
        return generating_count

    # ── Generation lifecycle ────────────────────────────────────────

    async def bulk_generate(
        self, episode_ids: list[UUID], base_max: int
    ) -> tuple[list[UUID], list[UUID]]:
        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        queued_ids: list[UUID] = []
        skipped_ids: list[UUID] = []

        result = await self._db.execute(sa_select(Episode).where(Episode.id.in_(episode_ids)))
        episodes_by_id = {ep.id: ep for ep in result.scalars().all()}

        for episode_id in episode_ids:
            episode = episodes_by_id.get(episode_id)
            if episode is None or episode.status not in ("draft", "failed"):
                skipped_ids.append(episode_id)
                continue
            generating_count = await self._ep_repo.count_by_status("generating")
            if generating_count >= base_max:
                skipped_ids.append(episode_id)
                continue

            for step in PIPELINE_STEPS:
                await self._job_repo.create(episode_id=episode_id, step=step, status="queued")
            await self._ep_repo.update_status(episode_id, "generating")
            await arq.delete(f"cancel:{episode_id}")
            await arq.enqueue_job("generate_episode", str(episode_id))
            queued_ids.append(episode_id)
            log.info("bulk_generate_enqueued", episode_id=str(episode_id))

        await self._db.commit()
        return queued_ids, skipped_ids

    async def generate(
        self, episode_id: UUID, requested_steps: list[str] | None, base_max: int
    ) -> list[UUID]:
        from drevalis.core.redis import get_arq_pool

        episode = await self.get_or_raise(episode_id)
        if episode.status not in ("draft", "failed"):
            raise EpisodeInvalidStatusError(episode_id, episode.status, ["draft", "failed"])
        await self.check_generation_slots(base_max)

        steps = PIPELINE_STEPS
        if requested_steps:
            steps = [s for s in PIPELINE_STEPS if s in requested_steps]

        done_steps = await self._job_repo.get_done_steps(episode_id)
        job_ids: list[UUID] = []
        for step in steps:
            if step in done_steps:
                continue
            job = await self._job_repo.create(episode_id=episode_id, step=step, status="queued")
            job_ids.append(job.id)

        await self._ep_repo.update_status(episode_id, "generating")
        await self._db.commit()

        arq = get_arq_pool()
        await arq.delete(f"cancel:{episode_id}")
        await arq.enqueue_job("generate_episode", str(episode_id))
        return job_ids

    async def retry_first_failed(self, episode_id: UUID, base_max: int) -> tuple[UUID, str]:
        from drevalis.core.redis import get_arq_pool

        await self.get_or_raise(episode_id)
        await self.check_generation_slots(base_max)

        jobs = await self._job_repo.get_by_episode(episode_id)
        failed_job = next((j for j in jobs if j.status == "failed"), None)
        if failed_job is None:
            raise NoFailedJobError("No failed jobs found for this episode")

        await self._job_repo.update_status(failed_job.id, "queued")
        failed_job.retry_count += 1
        await self._db.flush()
        await self._ep_repo.update_status(episode_id, "generating")
        await self._db.commit()

        arq = get_arq_pool()
        await arq.delete(f"cancel:{episode_id}")
        await arq.enqueue_job("retry_episode_step", str(episode_id), failed_job.step)
        return failed_job.id, failed_job.step

    async def retry_step(self, episode_id: UUID, step: str, base_max: int) -> UUID:
        from drevalis.core.redis import get_arq_pool

        await self.get_or_raise(episode_id)
        await self.check_generation_slots(base_max)

        existing = await self._job_repo.get_latest_by_episode_and_step(episode_id, step)
        if existing is not None:
            await self._job_repo.update_status(existing.id, "queued")
            existing.retry_count += 1
            await self._db.flush()
            job_id = existing.id
        else:
            job = await self._job_repo.create(episode_id=episode_id, step=step, status="queued")
            job_id = job.id

        await self._ep_repo.update_status(episode_id, "generating")
        await self._db.commit()

        arq = get_arq_pool()
        await arq.delete(f"cancel:{episode_id}")
        await arq.enqueue_job("retry_episode_step", str(episode_id), step)
        return job_id

    async def cancel(self, episode_id: UUID) -> int:
        from drevalis.core.redis import get_arq_pool
        from drevalis.schemas.progress import ProgressMessage

        episode = await self.get_or_raise(episode_id)
        if episode.status != "generating":
            raise EpisodeInvalidStatusError(episode_id, episode.status, ["generating"])

        redis = get_arq_pool()
        await redis.set(f"cancel:{episode_id}", "1", ex=3600)

        jobs = await self._job_repo.get_by_episode(episode_id)
        cancelled_jobs = 0
        for job in jobs:
            if job.status in ("running", "queued"):
                await self._job_repo.update_status(
                    job.id, "failed", error_message="Cancelled by user"
                )
                cancelled_jobs += 1

        await self._ep_repo.update_status(episode_id, "failed")
        await self._db.commit()

        cancel_msg = ProgressMessage(
            episode_id=str(episode_id),
            job_id="",
            step="script",
            status="failed",
            progress_pct=0,
            message="Generation cancelled by user",
            error="Cancelled by user",
        )
        try:
            await redis.publish(f"progress:{episode_id}", cancel_msg.model_dump_json())
        except Exception:
            log.debug("cancel_broadcast_failed", episode_id=str(episode_id), exc_info=True)

        log.info(
            "episode_cancelled",
            episode_id=str(episode_id),
            cancelled_jobs=cancelled_jobs,
        )
        return cancelled_jobs

    # ── Script edits ────────────────────────────────────────────────

    async def get_script(self, episode_id: UUID) -> dict[str, Any] | None:
        episode = await self.get_or_raise(episode_id)
        return episode.script

    async def update_script(self, episode_id: UUID, script: dict[str, Any]) -> dict[str, Any]:
        try:
            EpisodeScript.model_validate(script)
        except Exception as exc:
            raise ScriptValidationError(f"Invalid script format: {exc}") from exc

        episode = await self._ep_repo.update(episode_id, script=script)
        if episode is None:
            raise EpisodeNotFoundError(episode_id)
        await self._db.commit()
        return dict(episode.script or {})

    async def update_scene(
        self, episode_id: UUID, scene_number: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        episode, script = await self.get_with_script_or_raise(episode_id)

        scene_idx = next(
            (i for i, s in enumerate(script.scenes) if s.scene_number == scene_number),
            None,
        )
        if scene_idx is None:
            raise SceneNotFoundError(scene_number)

        scene = script.scenes[scene_idx]
        if "narration" in payload:
            scene.narration = payload["narration"]
        if "visual_prompt" in payload:
            scene.visual_prompt = payload["visual_prompt"]
        if "duration_seconds" in payload:
            scene.duration_seconds = payload["duration_seconds"]
        if "keywords" in payload:
            scene.keywords = payload["keywords"]

        script.total_duration_seconds = sum(s.duration_seconds for s in script.scenes)
        episode.script = script.model_dump()
        await self._db.commit()

        log.info(
            "scene_updated",
            episode_id=str(episode_id),
            scene_number=scene_number,
            updated_fields=[
                k
                for k in payload
                if k in ("narration", "visual_prompt", "duration_seconds", "keywords")
            ],
        )
        return scene.model_dump()

    async def delete_scene(self, episode_id: UUID, scene_number: int) -> tuple[int, int]:
        """Returns ``(remaining_scenes, deleted_assets)``. Raises
        ``ScriptValidationError`` if attempting to remove the last scene."""
        episode, script = await self.get_with_script_or_raise(episode_id)

        scene_idx = next(
            (i for i, s in enumerate(script.scenes) if s.scene_number == scene_number),
            None,
        )
        if scene_idx is None:
            raise SceneNotFoundError(scene_number)
        if len(script.scenes) <= 1:
            raise ScriptValidationError("Cannot delete the last remaining scene")

        script.scenes.pop(scene_idx)
        for i, scene in enumerate(script.scenes):
            scene.scene_number = i + 1
        script.total_duration_seconds = sum(s.duration_seconds for s in script.scenes)
        episode.script = script.model_dump()

        deleted_count = await self._asset_repo.delete_by_episode_and_scene(episode_id, scene_number)
        await self._db.commit()

        log.info(
            "scene_deleted",
            episode_id=str(episode_id),
            scene_number=scene_number,
            media_assets_deleted=deleted_count,
        )
        return len(script.scenes), deleted_count

    async def reorder_scenes(self, episode_id: UUID, order: list[int]) -> list[int]:
        episode, script = await self.get_with_script_or_raise(episode_id)

        current_numbers = {s.scene_number for s in script.scenes}
        if set(order) != current_numbers or len(order) != len(script.scenes):
            raise ScriptValidationError(
                f"Order must contain exactly the current scene numbers "
                f"{sorted(current_numbers)}, got {order}"
            )
        scene_map = {s.scene_number: s for s in script.scenes}
        reordered = [scene_map[num] for num in order]
        for i, scene in enumerate(reordered):
            scene.scene_number = i + 1
        script.scenes = reordered
        episode.script = script.model_dump()
        await self._db.commit()
        log.info("scenes_reordered", episode_id=str(episode_id), new_order=order)
        return [s.scene_number for s in script.scenes]

    async def split_scene(
        self, episode_id: UUID, scene_number: int, char_offset: int | None
    ) -> int:
        episode, script = await self.get_with_script_or_raise(episode_id)

        idx = next(
            (i for i, s in enumerate(script.scenes) if s.scene_number == scene_number),
            None,
        )
        if idx is None:
            raise SceneNotFoundError(scene_number)

        scene = script.scenes[idx]
        narration = scene.narration or ""
        offset = char_offset if char_offset is not None else len(narration) // 2
        if offset <= 0 or offset >= len(narration):
            raise ScriptValidationError(
                "char_offset must be a positive index strictly inside the narration"
            )

        left = narration[:offset]
        right = narration[offset:]
        last_space = left.rfind(" ")
        if last_space > len(left) * 0.5:
            left = left[:last_space]
            right = narration[last_space + 1 :]

        left_scene = scene.model_copy(update={"narration": left.rstrip()})
        right_scene = scene.model_copy(update={"narration": right.lstrip()})

        new_scenes = [
            *script.scenes[:idx],
            left_scene,
            right_scene,
            *script.scenes[idx + 1 :],
        ]
        for i, s in enumerate(new_scenes):
            s.scene_number = i + 1
        script.scenes = new_scenes
        episode.script = script.model_dump()
        await self._db.commit()
        log.info("scene_split", episode_id=str(episode_id), scene_number=scene_number)
        return len(script.scenes)

    async def merge_scenes(self, episode_id: UUID, target: int) -> int:
        episode, script = await self.get_with_script_or_raise(episode_id)

        idx = next(
            (i for i, s in enumerate(script.scenes) if s.scene_number == target),
            None,
        )
        if idx is None or idx + 1 >= len(script.scenes):
            raise ScriptValidationError(
                "scene_number must refer to a scene that has a successor to merge with"
            )

        a, b = script.scenes[idx], script.scenes[idx + 1]
        merged = a.model_copy(
            update={
                "narration": (
                    f"{(a.narration or '').rstrip()} {(b.narration or '').lstrip()}"
                ).strip(),
                "keywords": sorted(set((a.keywords or []) + (b.keywords or []))),
            }
        )
        new_scenes = [*script.scenes[:idx], merged, *script.scenes[idx + 2 :]]
        for i, s in enumerate(new_scenes):
            s.scene_number = i + 1
        script.scenes = new_scenes
        episode.script = script.model_dump()
        await self._db.commit()
        log.info(
            "scenes_merged",
            episode_id=str(episode_id),
            kept=target,
            removed=target + 1,
        )
        return len(script.scenes)

    # ── Regenerate scene / voice / reassemble / regenerate captions ──

    async def regenerate_scene(
        self,
        episode_id: UUID,
        scene_number: int,
        visual_prompt_override: str | None,
        base_max: int,
    ) -> list[UUID]:
        from drevalis.core.redis import get_arq_pool

        await self.check_generation_slots(base_max)
        episode, script = await self.get_with_script_or_raise(episode_id)

        scene_idx = next(
            (i for i, s in enumerate(script.scenes) if s.scene_number == scene_number),
            None,
        )
        if scene_idx is None:
            raise SceneNotFoundError(scene_number)

        if visual_prompt_override is not None:
            script.scenes[scene_idx].visual_prompt = visual_prompt_override
            episode.script = script.model_dump()
            await self._db.commit()

        scene_job = await self._job_repo.create(
            episode_id=episode_id, step="scenes", status="queued"
        )
        assembly_job = await self._job_repo.create(
            episode_id=episode_id, step="assembly", status="queued"
        )
        await self._ep_repo.update_status(episode_id, "generating")
        await self._db.commit()

        arq = get_arq_pool()
        await arq.enqueue_job(
            "regenerate_scene",
            str(episode_id),
            scene_number,
            visual_prompt_override,
        )
        log.info(
            "regenerate_scene_enqueued",
            episode_id=str(episode_id),
            scene_number=scene_number,
        )
        return [scene_job.id, assembly_job.id]

    async def regenerate_voice(
        self,
        episode_id: UUID,
        *,
        voice_profile_id: UUID | None,
        speed: float | None,
        pitch: float | None,
        base_max: int,
    ) -> list[UUID]:
        from drevalis.core.redis import get_arq_pool

        await self.check_generation_slots(base_max)
        episode, _script = await self.get_with_script_or_raise(episode_id)

        if voice_profile_id is not None:
            await self._ep_repo.update(episode_id, override_voice_profile_id=voice_profile_id)

        if speed is not None or pitch is not None:
            current_meta: dict[str, Any] = dict(episode.metadata_) if episode.metadata_ else {}
            tts_overrides: dict[str, Any] = dict(current_meta.get("tts_overrides", {}))
            if speed is not None:
                tts_overrides["speed"] = speed
            if pitch is not None:
                tts_overrides["pitch"] = pitch
            current_meta["tts_overrides"] = tts_overrides
            await self._ep_repo.update(episode_id, metadata_=current_meta)

        job_ids: list[UUID] = []
        for step in ("voice", "captions", "assembly", "thumbnail"):
            job = await self._job_repo.create(episode_id=episode_id, step=step, status="queued")
            job_ids.append(job.id)

        await self._ep_repo.update_status(episode_id, "generating")
        await self._db.commit()

        arq = get_arq_pool()
        await arq.enqueue_job("regenerate_voice", str(episode_id))
        log.info("regenerate_voice_enqueued", episode_id=str(episode_id))
        return job_ids

    async def reassemble(self, episode_id: UUID, base_max: int) -> list[UUID]:
        from drevalis.core.redis import get_arq_pool

        await self.check_generation_slots(base_max)
        await self.get_with_script_or_raise(episode_id)

        job_ids: list[UUID] = []
        for step in ("captions", "assembly", "thumbnail"):
            job = await self._job_repo.create(episode_id=episode_id, step=step, status="queued")
            job_ids.append(job.id)
        await self._ep_repo.update_status(episode_id, "generating")
        await self._db.commit()

        arq = get_arq_pool()
        await arq.enqueue_job("reassemble_episode", str(episode_id))
        log.info("reassemble_enqueued", episode_id=str(episode_id))
        return job_ids

    async def regenerate_captions(
        self, episode_id: UUID, caption_style: str, base_max: int
    ) -> list[UUID]:
        from drevalis.core.redis import get_arq_pool

        await self.check_generation_slots(base_max)
        await self.get_with_script_or_raise(episode_id)

        await self._ep_repo.update(episode_id, override_caption_style=caption_style)

        job_ids: list[UUID] = []
        for step in ("captions", "assembly", "thumbnail"):
            job = await self._job_repo.create(episode_id=episode_id, step=step, status="queued")
            job_ids.append(job.id)
        await self._ep_repo.update_status(episode_id, "generating")
        await self._db.commit()

        arq = get_arq_pool()
        await arq.enqueue_job("reassemble_episode", str(episode_id))
        log.info(
            "regenerate_captions_enqueued",
            episode_id=str(episode_id),
            caption_style=caption_style,
        )
        return job_ids

    # ── Cost estimation ─────────────────────────────────────────────

    async def estimate_cost(self, episode_id: UUID) -> dict[str, Any]:
        from drevalis.repositories.series import SeriesRepository
        from drevalis.repositories.voice_profile import VoiceProfileRepository

        episode = await self.get_or_raise(episode_id)
        series = await SeriesRepository(self._db).get_by_id(episode.series_id)
        content_format = getattr(episode, "content_format", "shorts")
        script = episode.script or {}
        scenes = script.get("scenes", [])

        total_chars = sum(len(s.get("narration", "")) for s in scenes)
        estimated_minutes = round(total_chars / 900, 1)

        voice_profile_id = series.voice_profile_id if series else None
        provider = "unknown"
        if voice_profile_id:
            vp = await VoiceProfileRepository(self._db).get_by_id(voice_profile_id)
            if vp:
                provider = vp.provider

        cost_per_1k = 0.15 if "elevenlabs" in provider else 0.0
        estimated_cost = round(total_chars / 1000 * cost_per_1k, 2)

        return {
            "content_format": content_format,
            "scene_count": len(scenes),
            "total_characters": total_chars,
            "estimated_duration_minutes": estimated_minutes,
            "estimated_tts_cost_usd": estimated_cost,
            "provider": provider,
        }

    # ── Music tab ──────────────────────────────────────────────────

    async def list_music_tracks(
        self,
        episode_id: UUID,
        storage_base_path: Any,
        ffprobe_duration: Any,
        audio_extensions: tuple[str, ...],
    ) -> dict[str, Any]:
        """Scan episode-specific + shared library music dirs. Returns
        the assembled response payload directly."""
        from pathlib import Path

        episode = await self.get_or_raise(episode_id)
        base = Path(storage_base_path)
        tracks: list[dict[str, Any]] = []

        episode_music_dir = base / "episodes" / str(episode_id) / "music"
        if episode_music_dir.exists():
            for audio_file in sorted(episode_music_dir.iterdir()):
                if audio_file.suffix.lower() in audio_extensions:
                    relative = f"episodes/{episode_id}/music/{audio_file.name}"
                    duration = await ffprobe_duration(audio_file)
                    mood_guess = audio_file.stem.split("_")[0] if "_" in audio_file.stem else ""
                    tracks.append(
                        {
                            "filename": audio_file.name,
                            "path": relative,
                            "mood": mood_guess,
                            "duration": duration,
                            "source": "episode",
                        }
                    )

        generated_dir = base / "music" / "generated"
        if generated_dir.exists():
            for mood_dir in sorted(generated_dir.iterdir()):
                if not mood_dir.is_dir():
                    continue
                mood_name = mood_dir.name
                for audio_file in sorted(mood_dir.iterdir()):
                    if audio_file.suffix.lower() in audio_extensions:
                        relative = f"music/generated/{mood_name}/{audio_file.name}"
                        duration = await ffprobe_duration(audio_file)
                        tracks.append(
                            {
                                "filename": audio_file.name,
                                "path": relative,
                                "mood": mood_name,
                                "duration": duration,
                                "source": "library",
                            }
                        )

        selected_path: str | None = (
            episode.metadata_.get("selected_music_path") if episode.metadata_ else None
        )
        return {
            "episode_id": str(episode_id),
            "tracks": tracks,
            "selected_path": selected_path,
        }

    async def select_music(self, episode_id: UUID, music_path: str | None) -> str | None:
        """Persist ``selected_music_path`` in episode.metadata_."""
        episode = await self.get_or_raise(episode_id)

        current_meta: dict[str, Any] = dict(episode.metadata_) if episode.metadata_ else {}
        if music_path is None:
            current_meta.pop("selected_music_path", None)
        else:
            current_meta["selected_music_path"] = music_path

        await self._ep_repo.update(episode_id, metadata_=current_meta)
        await self._db.commit()
        log.info(
            "music_selected",
            episode_id=str(episode_id),
            selected_music_path=music_path,
        )
        return music_path

    async def set_music(
        self,
        episode_id: UUID,
        *,
        music_enabled: bool,
        music_mood: str | None,
        music_volume_db: float | None,
        reassemble: bool,
        base_max: int,
    ) -> dict[str, Any]:
        """Persist music_settings on episode.metadata_; optionally
        enqueue a reassembly job. Returns the response payload."""
        from drevalis.core.redis import get_arq_pool

        episode = await self.get_or_raise(episode_id)

        music_settings: dict[str, Any] = {"music_enabled": music_enabled}
        if music_mood is not None:
            music_settings["music_mood"] = music_mood
        if music_volume_db is not None:
            music_settings["music_volume_db"] = music_volume_db

        current_meta: dict[str, Any] = dict(episode.metadata_) if episode.metadata_ else {}
        current_meta["music_settings"] = music_settings

        await self._ep_repo.update(episode_id, metadata_=current_meta)
        await self._db.commit()
        log.info(
            "music_settings_updated",
            episode_id=str(episode_id),
            music_settings=music_settings,
        )

        response: dict[str, Any] = {
            "episode_id": str(episode_id),
            "music_settings": music_settings,
            "message": "Music settings saved",
        }
        if not reassemble:
            return response

        await self.check_generation_slots(base_max)

        if not episode.script:
            response["message"] = "Music settings saved; reassembly skipped (episode has no script)"
            return response

        job_ids: list[UUID] = []
        for step in ("captions", "assembly", "thumbnail"):
            job = await self._job_repo.create(episode_id=episode_id, step=step, status="queued")
            job_ids.append(job.id)

        await self._ep_repo.update_status(episode_id, "generating")
        await self._db.commit()

        arq = get_arq_pool()
        await arq.enqueue_job("reassemble_episode", str(episode_id))
        log.info("set_music_reassemble_enqueued", episode_id=str(episode_id))
        response["message"] = "Music settings saved; reassembly enqueued"
        response["job_ids"] = [str(j) for j in job_ids]
        return response

    # ── Export helpers ─────────────────────────────────────────────

    async def get_with_series_or_raise(self, episode_id: UUID) -> Episode:
        """Load an episode with its series eagerly loaded."""
        from sqlalchemy.orm import selectinload

        stmt = (
            sa_select(Episode).where(Episode.id == episode_id).options(selectinload(Episode.series))
        )
        result = await self._db.execute(stmt)
        episode = result.scalar_one_or_none()
        if episode is None:
            raise EpisodeNotFoundError(episode_id)
        return episode

    async def get_video_asset_path(self, episode_id: UUID) -> str | None:
        """Return the relative path of the latest video asset, or None."""
        video_assets = await self._asset_repo.get_by_episode_and_type(episode_id, "video")
        return video_assets[-1].file_path if video_assets else None

    async def get_thumbnail_asset_path(self, episode_id: UUID) -> str | None:
        thumb_assets = await self._asset_repo.get_by_episode_and_type(episode_id, "thumbnail")
        return thumb_assets[-1].file_path if thumb_assets else None

    async def get_caption_asset_path(self, episode_id: UUID) -> str | None:
        caption_assets = await self._asset_repo.get_by_episode_and_type(episode_id, "caption")
        return caption_assets[-1].file_path if caption_assets else None

    async def get_all_assets(self, episode_id: UUID) -> list[Any]:
        return list(await self._asset_repo.get_by_episode(episode_id))

    async def get_latest_video_asset(self, episode_id: UUID) -> Any | None:
        """Return the most recent ``video`` MediaAsset row, or None."""
        video_assets = await self._asset_repo.get_by_episode_and_type(episode_id, "video")
        return video_assets[-1] if video_assets else None

    async def get_latest_thumbnail_asset(self, episode_id: UUID) -> Any | None:
        thumbs = await self._asset_repo.get_by_episode_and_type(episode_id, "thumbnail")
        return thumbs[-1] if thumbs else None

    async def update_asset_metadata(
        self,
        asset_id: UUID,
        *,
        file_size_bytes: int | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if file_size_bytes is not None:
            kwargs["file_size_bytes"] = file_size_bytes
        if duration_seconds is not None:
            kwargs["duration_seconds"] = duration_seconds
        if kwargs:
            await self._asset_repo.update(asset_id, **kwargs)
            await self._db.commit()

    # ── Custom thumbnail upload ────────────────────────────────────

    async def replace_thumbnail_asset(
        self,
        episode_id: UUID,
        *,
        rel_path: str,
        file_size: int,
    ) -> Any:
        """Delete any existing thumbnail MediaAsset rows + create a new
        one + update episode.metadata_['thumbnail_path']. Returns the
        new asset row."""
        existing = await self._asset_repo.get_by_episode_and_type(episode_id, "thumbnail")
        for a in existing:
            await self._asset_repo.delete(a.id)

        new_asset = await self._asset_repo.create(
            episode_id=episode_id,
            asset_type="thumbnail",
            file_path=rel_path,
            file_size_bytes=file_size,
        )

        episode = await self._ep_repo.get_by_id(episode_id)
        if episode is None:
            raise EpisodeNotFoundError(episode_id)
        current_metadata = dict(episode.metadata_ or {}) if episode.metadata_ else {}
        current_metadata["thumbnail_path"] = rel_path
        await self._ep_repo.update(episode_id, metadata_=current_metadata)
        await self._db.commit()
        return new_asset

    # ── Job creation helpers (kept from original v1 for compatibility) ──

    async def create_reassembly_jobs(
        self,
        episode_id: UUID,
        steps: list[str] | None = None,
    ) -> list[Any]:
        if steps is None:
            steps = ["captions", "assembly", "thumbnail"]
        jobs = []
        for step in steps:
            job = await self._job_repo.create(episode_id=episode_id, step=step, status="queued")
            jobs.append(job)
        return jobs

    def require_status(self, episode: Episode, allowed: list[str]) -> None:
        if episode.status not in allowed:
            raise EpisodeInvalidStatusError(episode.id, episode.status, allowed)


__all__ = [
    "ConcurrencyCapReachedError",
    "EpisodeInvalidStatusError",
    "EpisodeNoScriptError",
    "EpisodeNotFoundError",
    "EpisodeService",
    "NoFailedJobError",
    "PIPELINE_STEPS",
    "SceneNotFoundError",
    "ScriptValidationError",
]
