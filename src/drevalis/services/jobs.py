"""JobsService — generation jobs, queue, worker health, bulk ops.

Layering: keeps the jobs route file free of repository imports + the
``redis.asyncio.Redis`` client lifecycle (audit F-A-01).

Five repositories collaborate (Episode, GenerationJob, Audiobook +
ApiKeyStore via the unified-tasks aggregator's lazy import) so the
service owns them in one place. Each method either returns a plain
dict / list of dicts (response shape stays in the route) or raises
``NotFoundError`` / ``ValidationError``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from sqlalchemy import select

from drevalis.core.exceptions import InvalidStatusError, NotFoundError
from drevalis.repositories.episode import EpisodeRepository
from drevalis.repositories.generation_job import GenerationJobRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.models.generation_job import GenerationJob

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


VALID_PRIORITY_MODES = ("shorts_first", "longform_first", "fifo")


class JobsService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._jobs = GenerationJobRepository(db)
        self._episodes = EpisodeRepository(db)

    # ── Listing / detail ─────────────────────────────────────────────────

    async def list_active(self, limit: int) -> list[GenerationJob]:
        return list(await self._jobs.get_active_jobs(limit=limit))

    async def list_filtered(
        self,
        *,
        episode_id: UUID | None,
        status_filter: str | None,
        limit: int,
    ) -> list[GenerationJob]:
        if episode_id is not None:
            jobs = await self._jobs.get_by_episode(episode_id)
            if status_filter is not None:
                jobs = [j for j in jobs if j.status == status_filter]
            return list(jobs[:limit])
        if status_filter == "failed":
            return list(await self._jobs.get_failed_jobs(limit=limit))
        if status_filter in ("queued", "running"):
            jobs = await self._jobs.get_active_jobs(limit=limit)
            return [j for j in jobs if j.status == status_filter]
        return list(await self._jobs.get_all(limit=limit))

    async def list_all_filtered(
        self,
        *,
        status_filter: str | None,
        episode_id: UUID | None,
        step: str | None,
        offset: int,
        limit: int,
    ) -> list[GenerationJob]:
        return list(
            await self._jobs.get_all_filtered(
                status_filter=status_filter,
                episode_id=episode_id,
                step=step,
                offset=offset,
                limit=limit,
            )
        )

    async def get_job(self, job_id: UUID) -> GenerationJob:
        job = await self._jobs.get_by_id(job_id)
        if job is None:
            raise NotFoundError("GenerationJob", job_id)
        return job

    # ── Queue status / unified tasks ─────────────────────────────────────

    async def queue_status(self, max_concurrent: int) -> dict[str, Any]:
        active_jobs = await self._jobs.get_active_jobs(limit=500)
        running_jobs = [j for j in active_jobs if j.status == "running"]
        queued_jobs = [j for j in active_jobs if j.status == "queued"]
        generating_count = await self._episodes.count_by_status("generating")
        failed_count = await self._episodes.count_by_status("failed")
        return {
            "active": len(running_jobs),
            "queued": len(queued_jobs),
            "max_concurrent": max_concurrent,
            "slots_available": max(0, max_concurrent - generating_count),
            "generating_episodes": generating_count,
            "total_generating_episodes": generating_count,
            "total_failed_episodes": failed_count,
        }

    async def active_tasks(self) -> list[dict[str, Any]]:
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool
        from drevalis.models.episode import Episode

        tasks: list[dict[str, Any]] = []

        # 1. Episode generation jobs
        active_jobs = await self._jobs.get_active_jobs(limit=200)
        by_episode: dict[UUID, Any] = {}
        for job in active_jobs:
            existing = by_episode.get(job.episode_id)
            if existing is None or job.status == "running":
                by_episode[job.episode_id] = job

        ep_titles: dict[UUID, str] = {}
        if by_episode:
            result = await self._db.execute(
                select(Episode.id, Episode.title).where(Episode.id.in_(list(by_episode.keys())))
            )
            for ep_id, ep_title in result.all():
                ep_titles[ep_id] = ep_title

        for ep_id, job in by_episode.items():
            tasks.append(
                {
                    "type": "episode_generation",
                    "id": str(ep_id),
                    "title": ep_titles.get(ep_id, f"Episode {str(ep_id)[:8]}"),
                    "step": job.step,
                    "status": job.status,
                    "progress": job.progress_pct,
                    "url": f"/episodes/{ep_id}",
                }
            )

        # 2. Audiobook generation
        try:
            from drevalis.repositories.audiobook import AudiobookRepository

            ab_repo = AudiobookRepository(self._db)
            generating_abs = await ab_repo.get_by_status("generating")
            for ab in generating_abs:
                tasks.append(
                    {
                        "type": "audiobook_generation",
                        "id": str(ab.id),
                        "title": ab.title,
                        "step": "tts",
                        "status": "running",
                        "progress": -1,
                        "url": f"/audiobooks/{ab.id}",
                    }
                )
        except Exception:
            logger.debug("tasks_audiobook_query_failed", exc_info=True)

        # 3. LLM script/series jobs (Redis)
        rc: Redis = Redis(connection_pool=get_pool())
        try:
            all_status_keys: list[str] = []
            cursor: int = 0
            while True:
                cursor, keys = await rc.scan(cursor, match="script_job:*:status", count=50)
                for k in keys:
                    all_status_keys.append(k if isinstance(k, str) else k.decode())
                if cursor == 0:
                    break

            if all_status_keys:
                status_values = await rc.mget(all_status_keys)
                generating_jids: list[str] = []
                for key_str, raw_val in zip(all_status_keys, status_values, strict=False):
                    if not raw_val:
                        continue
                    val = raw_val if isinstance(raw_val, str) else raw_val.decode()
                    if val != "generating":
                        continue
                    parts = key_str.split(":")
                    if len(parts) >= 3:
                        generating_jids.append(parts[1])

                input_values: list[Any] = []
                if generating_jids:
                    input_keys = [f"script_job:{jid}:input" for jid in generating_jids]
                    input_values = await rc.mget(input_keys)

                for jid, input_raw in zip(generating_jids, input_values, strict=False):
                    title = "AI Script"
                    if input_raw:
                        try:
                            raw_input = (
                                input_raw if isinstance(input_raw, str) else input_raw.decode()
                            )
                            data = json.loads(raw_input)
                            if data.get("type") == "series":
                                idea = data.get("idea", "")
                                title = f"AI Series: {idea[:30]}" if idea else "AI Series"
                            else:
                                concept = data.get("concept", data.get("idea", ""))
                                title = f"AI Script: {concept[:30]}" if concept else "AI Script"
                        except Exception:
                            pass

                    url = "/series" if "Series" in title else "/audiobooks"
                    tasks.append(
                        {
                            "type": "script_generation",
                            "id": jid,
                            "title": title,
                            "step": "llm",
                            "status": "running",
                            "progress": -1,
                            "url": url,
                        }
                    )
        except Exception:
            logger.debug("tasks_redis_scan_failed", exc_info=True)
        finally:
            await rc.aclose()

        return tasks

    # ── Bulk operations ──────────────────────────────────────────────────

    async def cleanup_stale(self) -> dict[str, int]:
        active_jobs = await self._jobs.get_active_jobs(limit=1000)
        episode_ids = list({job.episode_id for job in active_jobs})
        eps_by_id = await self._episodes.get_by_ids(episode_ids)
        cleaned_jobs = 0
        for job in active_jobs:
            ep = eps_by_id.get(job.episode_id)
            if ep is None or ep.status != "generating":
                await self._jobs.update_status(
                    job.id, "failed", error_message="Cleaned up: orphaned job"
                )
                cleaned_jobs += 1

        generating_eps = await self._episodes.get_by_status("generating", limit=500)
        reset_episodes = 0
        for ep in generating_eps:
            jobs = await self._jobs.get_by_episode(ep.id)
            has_active = any(j.status in ("queued", "running") for j in jobs)
            if not has_active:
                await self._episodes.update_status(ep.id, "draft")
                reset_episodes += 1

        await self._db.commit()
        logger.info("cleanup_complete", cleaned_jobs=cleaned_jobs, reset_episodes=reset_episodes)
        return {"cleaned_jobs": cleaned_jobs, "reset_episodes": reset_episodes}

    async def cancel_all(self) -> dict[str, int]:
        from drevalis.core.redis import get_arq_pool
        from drevalis.schemas.progress import ProgressMessage

        redis = get_arq_pool()
        generating_episodes = await self._episodes.get_by_status("generating", limit=500)

        cancelled_episodes = 0
        cancelled_jobs = 0
        for episode in generating_episodes:
            await redis.set(f"cancel:{episode.id}", "1", ex=3600)
            jobs = await self._jobs.get_by_episode(episode.id)
            for job in jobs:
                if job.status in ("running", "queued"):
                    await self._jobs.update_status(
                        job.id, "failed", error_message="Cancelled by emergency stop"
                    )
                    cancelled_jobs += 1
            await self._episodes.update_status(episode.id, "failed")
            cancelled_episodes += 1

            cancel_msg = ProgressMessage(
                episode_id=str(episode.id),
                job_id="",
                step="script",
                status="failed",
                progress_pct=0,
                message="Generation cancelled by emergency stop",
                error="Emergency stop: all jobs cancelled",
            )
            try:
                await redis.publish(f"progress:{episode.id}", cancel_msg.model_dump_json())
            except Exception:
                logger.debug(
                    "cancel_all_broadcast_failed", episode_id=str(episode.id), exc_info=True
                )

        await self._db.commit()
        logger.info(
            "all_jobs_cancelled",
            cancelled_episodes=cancelled_episodes,
            cancelled_jobs=cancelled_jobs,
        )
        return {
            "cancelled_episodes": cancelled_episodes,
            "cancelled_jobs": cancelled_jobs,
        }

    async def retry_all_failed(self, priority: str) -> dict[str, int | str]:
        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        failed_episodes = list(await self._episodes.get_by_status("failed", limit=500))

        if priority == "shorts_first":
            failed_episodes.sort(
                key=lambda e: 0 if getattr(e, "content_format", "shorts") == "shorts" else 1
            )
        elif priority == "longform_first":
            failed_episodes.sort(
                key=lambda e: 0 if getattr(e, "content_format", "shorts") == "longform" else 1
            )

        retried = 0
        for episode in failed_episodes:
            try:
                await arq.enqueue_job("retry_episode_step", str(episode.id), None)
                await self._episodes.update_status(episode.id, "generating")
                retried += 1
            except Exception:
                logger.debug("retry_all_enqueue_failed", episode_id=str(episode.id))

        await self._db.commit()
        logger.info(
            "retry_all_failed_done",
            retried=retried,
            total=len(failed_episodes),
            priority=priority,
        )
        return {"retried": retried, "total_failed": len(failed_episodes), "priority": priority}

    async def pause_all(self) -> int:
        from drevalis.core.redis import get_arq_pool

        redis = get_arq_pool()
        generating = await self._episodes.get_by_status("generating", limit=500)
        paused = 0
        for episode in generating:
            await redis.set(f"cancel:{episode.id}", "1", ex=3600)
            jobs = await self._jobs.get_by_episode(episode.id)
            for job in jobs:
                if job.status in ("running", "queued"):
                    await self._jobs.update_status(job.id, "failed", error_message="Paused by user")
            await self._episodes.update_status(episode.id, "failed")
            paused += 1
        await self._db.commit()
        logger.info("pause_all_done", paused=paused)
        return paused

    # ── Priority mode (Redis only) ───────────────────────────────────────

    async def set_priority(self, mode: str) -> None:
        if mode not in VALID_PRIORITY_MODES:
            raise InvalidStatusError("PriorityMode", mode, mode, list(VALID_PRIORITY_MODES))
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool

        rc: Redis = Redis(connection_pool=get_pool())
        try:
            await rc.set("job:priority_mode", mode, ex=86400 * 30)
        finally:
            await rc.aclose()

    async def get_priority(self) -> str:
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool

        rc: Redis = Redis(connection_pool=get_pool())
        try:
            raw = await rc.get("job:priority_mode")
        finally:
            await rc.aclose()
        if isinstance(raw, bytes):
            return raw.decode()
        return raw or "fifo"

    # ── Worker health + restart ──────────────────────────────────────────

    async def worker_health(self) -> dict[str, Any]:
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool

        rc: Redis = Redis(connection_pool=get_pool())
        try:
            raw = await rc.get("worker:heartbeat")
        finally:
            await rc.aclose()

        now = datetime.now(UTC)
        if raw is None:
            return {
                "alive": False,
                "last_heartbeat": None,
                "age_seconds": None,
                "message": "Worker heartbeat key not found. Worker may be down or not yet started.",
            }

        heartbeat_str = raw if isinstance(raw, str) else raw.decode()
        try:
            last_beat = datetime.fromisoformat(heartbeat_str)
            if last_beat.tzinfo is None:
                last_beat = last_beat.replace(tzinfo=UTC)
            age_seconds = (now - last_beat).total_seconds()
        except ValueError:
            return {
                "alive": False,
                "last_heartbeat": heartbeat_str,
                "age_seconds": None,
                "message": "Worker heartbeat value could not be parsed.",
            }

        generating_count = await self._episodes.count_by_status("generating")
        return {
            "alive": age_seconds < 120,
            "last_heartbeat": heartbeat_str,
            "age_seconds": round(age_seconds, 1),
            "generating_episodes": generating_count,
            "message": "Worker is alive." if age_seconds < 120 else "Worker heartbeat is stale.",
        }

    async def restart_worker(self) -> int:
        from drevalis.core.redis import get_arq_pool

        redis = get_arq_pool()
        await redis.set("worker:restart_signal", "1", ex=300)

        generating_episodes = await self._episodes.get_by_status("generating", limit=500)
        reset_count = 0
        for episode in generating_episodes:
            jobs = await self._jobs.get_by_episode(episode.id)
            for job in jobs:
                if job.status in ("running", "queued"):
                    await self._jobs.update_status(
                        job.id, "failed", error_message="Reset by worker restart signal"
                    )
            await self._episodes.update_status(episode.id, "failed")
            reset_count += 1

        await self._db.commit()
        logger.info("worker_restart_signalled", reset_episodes=reset_count)
        return reset_count

    # ── Single-job cancel ────────────────────────────────────────────────

    async def cancel_job(self, job_id: UUID) -> tuple[UUID, bool]:
        """Cancel a single job. Returns ``(episode_id, episode_cancelled)``.

        Raises ``NotFoundError`` when the job is missing and
        ``InvalidStatusError`` when the job is not running/queued.
        """
        from drevalis.core.redis import get_arq_pool
        from drevalis.schemas.progress import ProgressMessage

        redis = get_arq_pool()

        job = await self._jobs.get_by_id(job_id)
        if job is None:
            raise NotFoundError("GenerationJob", job_id)
        if job.status not in ("running", "queued"):
            raise InvalidStatusError("GenerationJob", job_id, job.status, ["running", "queued"])

        await self._jobs.update_status(job.id, "failed", error_message="Cancelled by user")

        episode_jobs = await self._jobs.get_by_episode(job.episode_id)
        remaining_active = [
            j for j in episode_jobs if j.id != job.id and j.status in ("running", "queued")
        ]

        episode_cancelled = False
        if not remaining_active:
            await redis.set(f"cancel:{job.episode_id}", "1", ex=3600)
            episode = await self._episodes.get_by_id(job.episode_id)
            if episode is not None and episode.status == "generating":
                await self._episodes.update_status(job.episode_id, "failed")
                episode_cancelled = True

            cancel_msg = ProgressMessage(
                episode_id=str(job.episode_id),
                job_id=str(job.id),
                step=job.step,
                status="failed",
                progress_pct=0,
                message="Job cancelled by user",
                error="Cancelled by user",
            )
            try:
                await redis.publish(f"progress:{job.episode_id}", cancel_msg.model_dump_json())
            except Exception:
                logger.debug("cancel_job_broadcast_failed", job_id=str(job_id), exc_info=True)

        await self._db.commit()
        logger.info(
            "job_cancelled",
            job_id=str(job_id),
            episode_id=str(job.episode_id),
            episode_cancelled=episode_cancelled,
        )
        return job.episode_id, episode_cancelled


__all__ = ["JobsService", "VALID_PRIORITY_MODES"]
