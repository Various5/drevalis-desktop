"""AudiobookAdminService — CRUD, AI script enqueue, regen flows.

Layering: keeps the audiobooks route file free of repository imports +
direct Redis / arq client lifecycles (audit F-A-01).

The heavy generation logic lives in ``services/audiobook.py`` (the
``AudiobookService`` class). This file is the *route-orchestration*
layer that owns AudiobookRepository / VoiceProfileRepository /
YouTube*Repository plus the script-job Redis bookkeeping. The two
collaborate but stay separate so the worker keeps importing the heavy
service without dragging in HTTP-side concerns.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.repositories.audiobook import AudiobookRepository
from drevalis.repositories.voice_profile import VoiceProfileRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.models.audiobook import Audiobook
    from drevalis.models.voice_profile import VoiceProfile

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


_VALID_OUTPUT_FORMATS = ("audio_only", "audio_image", "audio_video")


class NoChannelSelectedError(Exception):
    """Raised when an audiobook upload can't unambiguously pick a YouTube channel."""


class AudiobookAdminService:
    def __init__(self, db: AsyncSession, storage_base_path: Path) -> None:
        self._db = db
        self._storage = Path(storage_base_path)
        self._repo = AudiobookRepository(db)
        self._voices = VoiceProfileRepository(db)

    # ── Script-job (Redis-backed async LLM) ──────────────────────────────

    async def enqueue_script_job(self, payload_dict: dict[str, Any]) -> str:
        from redis.asyncio import Redis

        from drevalis.core.redis import get_arq_pool, get_pool

        job_id = str(uuid4())
        rc: Redis = Redis(connection_pool=get_pool())
        try:
            await rc.set(f"script_job:{job_id}:status", "generating", ex=3600)
            await rc.set(f"script_job:{job_id}:input", json.dumps(payload_dict), ex=3600)
            arq = get_arq_pool()
            await arq.enqueue_job("generate_script_async", job_id, payload_dict)
        finally:
            await rc.aclose()
        return job_id

    async def get_script_job(self, job_id: str) -> dict[str, Any]:
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool

        rc: Redis = Redis(connection_pool=get_pool())
        try:
            raw_status = await rc.get(f"script_job:{job_id}:status")
            if not raw_status:
                raise NotFoundError("ScriptJob", job_id)

            job_status = raw_status if isinstance(raw_status, str) else raw_status.decode()
            result_dict: dict[str, Any] | None = None
            error: str | None = None
            if job_status == "done":
                result_json = await rc.get(f"script_job:{job_id}:result")
                if result_json:
                    raw = result_json if isinstance(result_json, str) else result_json.decode()
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        result_dict = parsed
            elif job_status == "failed":
                raw_error = await rc.get(f"script_job:{job_id}:error")
                if raw_error:
                    error = raw_error if isinstance(raw_error, str) else raw_error.decode()
            return {"status": job_status, "result": result_dict, "error": error}
        finally:
            await rc.aclose()

    async def cancel_script_job(self, job_id: str) -> None:
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool

        rc: Redis = Redis(connection_pool=get_pool())
        try:
            existing = await rc.get(f"script_job:{job_id}:status")
            if not existing:
                raise NotFoundError("ScriptJob", job_id)
            await rc.set(f"script_job:{job_id}:status", "cancelled", ex=3600)
        finally:
            await rc.aclose()
        log.info("audiobook.script.job_cancelled", job_id=job_id)

    # ── Create AI audiobook (LLM script + TTS in one job) ────────────────

    async def create_ai(self, payload: Any) -> Audiobook:
        """Build voice casting from the characters list + create the row.

        ``payload`` is the route's ``AudiobookAICreateRequest`` Pydantic
        model. Kept loose-typed here so the service file doesn't have
        to import the route module.
        """
        if payload.output_format not in _VALID_OUTPUT_FORMATS:
            raise ValidationError(f"output_format must be one of {_VALID_OUTPUT_FORMATS}")

        title = payload.concept.strip()[:50].rstrip(".") + "..."

        all_voices = await self._voices.get_all()
        male_voices = [v for v in all_voices if getattr(v, "gender", None) == "male"]
        female_voices = [v for v in all_voices if getattr(v, "gender", None) == "female"]

        voice_casting, default_voice_id = self._auto_assign_voices(
            characters=payload.characters,
            male_voices=male_voices,
            female_voices=female_voices,
        )

        if not default_voice_id:
            raise ValidationError("No voice profiles available. Create voice profiles first.")

        voice_profile = await self._voices.get_by_id(UUID(default_voice_id))
        if voice_profile is None:
            raise NotFoundError("VoiceProfile", default_voice_id)

        audiobook = await self._repo.create(
            title=title,
            text="",
            voice_profile_id=UUID(default_voice_id),
            status="generating",
            output_format=payload.output_format,
            voice_casting=voice_casting if voice_casting else None,
            music_enabled=payload.music_enabled,
            music_mood=payload.music_mood,
            music_volume_db=payload.music_volume_db,
            speed=payload.speed,
            pitch=payload.pitch,
            image_generation_enabled=payload.image_generation_enabled,
        )
        await self._db.commit()

        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        await arq.enqueue_job("generate_ai_audiobook", str(audiobook.id), payload.model_dump())
        log.info(
            "audiobook.ai_create.enqueued",
            audiobook_id=str(audiobook.id),
            concept_length=len(payload.concept),
            character_count=len(payload.characters),
            target_minutes=payload.target_minutes,
        )
        return audiobook

    @staticmethod
    def _auto_assign_voices(
        *,
        characters: list[dict[str, Any]],
        male_voices: list[VoiceProfile],
        female_voices: list[VoiceProfile],
    ) -> tuple[dict[str, str], str | None]:
        """Round-robin voice assignment by gender; explicit ids win."""
        voice_casting: dict[str, str] = {}
        default_voice_id: str | None = None
        gender_counters: dict[str, int] = {"male": 0, "female": 0}

        for char in characters:
            vp_id = char.get("voice_profile_id")
            if vp_id:
                voice_casting[char["name"]] = vp_id
                if not default_voice_id:
                    default_voice_id = vp_id
                continue

            gender = char.get("gender", "male")
            pool = female_voices if gender == "female" else male_voices
            if not pool:
                continue
            used_ids = set(voice_casting.values())
            available = [v for v in pool if str(v.id) not in used_ids]
            if available:
                chosen = available[0]
            else:
                idx = gender_counters[gender] % len(pool)
                chosen = pool[idx]
            gender_counters[gender] += 1
            voice_casting[char["name"]] = str(chosen.id)
            if not default_voice_id:
                default_voice_id = str(chosen.id)
        return voice_casting, default_voice_id

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def list_filtered(
        self, *, status_filter: str | None, offset: int, limit: int
    ) -> list[Audiobook]:
        if status_filter is not None:
            return list(await self._repo.get_by_status(status_filter))
        return list(await self._repo.get_all(offset=offset, limit=limit))

    async def get(self, audiobook_id: UUID) -> Audiobook:
        ab = await self._repo.get_by_id(audiobook_id)
        if ab is None:
            raise NotFoundError("Audiobook", audiobook_id)
        return ab

    async def create(self, payload: Any, settings_blob: dict[str, Any] | None) -> Audiobook:
        """Validate references + persist the row + enqueue. ``payload``
        is the route's ``AudiobookCreate``."""
        if payload.output_format not in _VALID_OUTPUT_FORMATS:
            raise ValidationError(f"output_format must be one of {_VALID_OUTPUT_FORMATS}")

        voice_profile = await self._voices.get_by_id(payload.voice_profile_id)
        if voice_profile is None:
            raise NotFoundError("VoiceProfile", payload.voice_profile_id)

        if payload.voice_casting:
            for speaker, vp_id in payload.voice_casting.items():
                try:
                    cast_uuid = UUID(vp_id)
                except ValueError as exc:
                    raise ValidationError(
                        f"Invalid UUID '{vp_id}' for speaker '{speaker}'"
                    ) from exc
                cast_vp = await self._voices.get_by_id(cast_uuid)
                if cast_vp is None:
                    raise NotFoundError(f"VoiceProfile (speaker={speaker})", vp_id)

        audiobook = await self._repo.create(
            title=payload.title,
            text=payload.text,
            voice_profile_id=payload.voice_profile_id,
            status="generating",
            background_image_path=payload.background_image_path,
            output_format=payload.output_format,
            cover_image_path=payload.cover_image_path,
            voice_casting=payload.voice_casting,
            music_enabled=payload.music_enabled,
            music_mood=payload.music_mood,
            music_volume_db=payload.music_volume_db,
            speed=payload.speed,
            pitch=payload.pitch,
            video_orientation=payload.video_orientation,
            caption_style_preset=payload.caption_style_preset,
            image_generation_enabled=payload.image_generation_enabled,
            settings_json=settings_blob,
        )
        await self._db.commit()
        await self._db.refresh(audiobook)

        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        await arq.enqueue_job("generate_audiobook", str(audiobook.id), payload.generate_video)
        log.info(
            "audiobook.created",
            audiobook_id=str(audiobook.id),
            text_length=len(payload.text),
            output_format=payload.output_format,
            generate_video=payload.generate_video,
            music_enabled=payload.music_enabled,
            has_voice_casting=payload.voice_casting is not None,
        )
        return audiobook

    async def update_metadata(self, audiobook_id: UUID, update_data: dict[str, Any]) -> Audiobook:
        if not update_data:
            raise ValidationError("No fields to update")
        audiobook = await self._repo.update(audiobook_id, **update_data)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)
        await self._db.commit()
        await self._db.refresh(audiobook)
        return audiobook

    async def update_text(self, audiobook_id: UUID, text: str) -> Audiobook:
        existing = await self._repo.get_by_id(audiobook_id)
        if existing is None:
            raise NotFoundError("Audiobook", audiobook_id)
        audiobook = await self._repo.update(audiobook_id, text=text)
        await self._db.commit()
        assert audiobook is not None
        await self._db.refresh(audiobook)
        log.info("audiobook.text_updated", audiobook_id=str(audiobook_id), text_length=len(text))
        return audiobook

    # ── Chapter regen / image regen ──────────────────────────────────────

    async def regenerate_chapter(
        self, audiobook_id: UUID, chapter_index: int, new_text: str | None
    ) -> None:
        audiobook = await self._repo.get_by_id(audiobook_id)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)

        if audiobook.chapters and (chapter_index < 0 or chapter_index >= len(audiobook.chapters)):
            raise ValidationError(
                f"chapter_index {chapter_index} is out of range (0..{len(audiobook.chapters) - 1})"
            )

        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        await arq.enqueue_job(
            "regenerate_audiobook_chapter", str(audiobook_id), chapter_index, new_text
        )
        log.info(
            "audiobook.regenerate_chapter.enqueued",
            audiobook_id=str(audiobook_id),
            chapter_index=chapter_index,
            has_new_text=new_text is not None,
        )

    async def regenerate_chapter_image(
        self, audiobook_id: UUID, chapter_index: int, prompt_override: str | None
    ) -> None:
        audiobook = await self._repo.get_by_id(audiobook_id)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)
        if not audiobook.chapters:
            raise ValidationError("Audiobook has no chapters yet")
        if chapter_index < 0 or chapter_index >= len(audiobook.chapters):
            raise ValidationError(
                f"chapter_index {chapter_index} is out of range (0..{len(audiobook.chapters) - 1})"
            )

        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        await arq.enqueue_job(
            "regenerate_audiobook_chapter_image",
            str(audiobook_id),
            chapter_index,
            prompt_override,
        )
        log.info(
            "audiobook.regenerate_chapter_image.enqueued",
            audiobook_id=str(audiobook_id),
            chapter_index=chapter_index,
            has_prompt_override=prompt_override is not None,
        )

    # ── Voices update / cancel / regenerate / remix ──────────────────────

    async def update_voices(
        self,
        audiobook_id: UUID,
        voice_casting: dict[str, str] | None,
        default_voice_id: str | None,
        regenerate: bool,
    ) -> bool:
        """Returns True when a regeneration job was enqueued."""
        audiobook = await self._repo.get_by_id(audiobook_id)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)

        updates: dict[str, Any] = {}
        if voice_casting:
            updates["voice_casting"] = voice_casting
        if default_voice_id:
            updates["voice_profile_id"] = UUID(default_voice_id)
        if updates:
            await self._repo.update(audiobook_id, **updates)
            await self._db.commit()

        if regenerate:
            await self._repo.update(audiobook_id, status="generating", error_message=None)
            await self._db.commit()
            from drevalis.core.redis import get_arq_pool

            arq = get_arq_pool()
            await arq.enqueue_job("generate_audiobook", str(audiobook_id))
            return True
        return False

    async def cancel(self, audiobook_id: UUID) -> str:
        """Returns the new status string ("cancel-signalled" / actual status)."""
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool

        audiobook = await self._repo.get_by_id(audiobook_id)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)
        if audiobook.status != "generating":
            return audiobook.status

        rc: Redis = Redis(connection_pool=get_pool())
        try:
            await rc.set(f"cancel:audiobook:{audiobook_id}", "1", ex=3600)
        finally:
            await rc.aclose()
        log.info("audiobook.cancel.signalled", audiobook_id=str(audiobook_id))
        return "cancel-signalled"

    async def regenerate(self, audiobook_id: UUID) -> None:
        audiobook = await self._repo.get_by_id(audiobook_id)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)
        await self._repo.update(audiobook_id, status="generating", error_message=None)
        await self._db.commit()

        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        await arq.enqueue_job("generate_audiobook", str(audiobook_id), False)
        log.info("audiobook.regenerate.enqueued", audiobook_id=str(audiobook_id))

    async def remix(self, audiobook_id: UUID, delta: dict[str, Any]) -> dict[str, Any]:
        audiobook = await self._repo.get_by_id(audiobook_id)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)

        current_mix: dict[str, Any] = dict(audiobook.track_mix or {})
        current_mix.update(delta)

        await self._repo.update(
            audiobook_id,
            status="generating",
            error_message=None,
            track_mix=current_mix,
        )
        await self._db.commit()

        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        await arq.enqueue_job("generate_audiobook", str(audiobook_id), False)
        log.info(
            "audiobook.remix.enqueued",
            audiobook_id=str(audiobook_id),
            applied=list(delta.keys()),
        )
        return current_mix

    # ── YouTube upload (channel resolution + tracking row) ───────────────

    async def prepare_youtube_upload(self, audiobook_id: UUID) -> tuple[Audiobook, Any, Path]:
        """Resolve channel + validate video file. Returns
        ``(audiobook, channel, absolute_video_path)`` or raises.

        Channel resolution: per-audiobook ``youtube_channel_id`` first,
        then implicit single-channel fallback. Anything else raises
        ``NoChannelSelectedError``.
        """
        from drevalis.repositories.youtube import YouTubeChannelRepository

        audiobook = await self._repo.get_by_id(audiobook_id)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)

        channel_repo = YouTubeChannelRepository(self._db)
        channel = None
        ab_channel_id = getattr(audiobook, "youtube_channel_id", None)
        if ab_channel_id:
            channel = await channel_repo.get_by_id(ab_channel_id)
        if channel is None:
            all_channels = await channel_repo.get_all_channels()
            if len(all_channels) == 1:
                channel = all_channels[0]
        if channel is None:
            raise NoChannelSelectedError()

        if not audiobook.video_path:
            raise ValidationError(
                "No video file found for this audiobook. "
                "Generate with output_format 'audio_image' or 'audio_video' first."
            )
        video_path = self._storage / audiobook.video_path
        if not video_path.exists():
            raise ValidationError("Video file not found on disk")
        return audiobook, channel, video_path

    async def create_youtube_upload_row(
        self,
        *,
        audiobook_id: UUID,
        channel_id: UUID,
        title: str,
        privacy_status: str,
    ) -> Any:
        from drevalis.repositories.youtube import YouTubeAudiobookUploadRepository

        upload_repo = YouTubeAudiobookUploadRepository(self._db)
        upload = await upload_repo.create(
            audiobook_id=audiobook_id,
            channel_id=channel_id,
            title=title,
            privacy_status=privacy_status,
            upload_status="uploading",
        )
        await self._db.commit()
        await self._db.refresh(upload)
        return upload

    async def record_youtube_upload_success(self, upload: Any, *, video_id: str, url: str) -> None:
        upload.youtube_video_id = video_id
        upload.youtube_url = url
        upload.upload_status = "done"
        await self._db.commit()

    async def record_youtube_upload_failure(self, upload: Any, error: str) -> None:
        upload.upload_status = "failed"
        upload.error_message = error[:1000]
        await self._db.commit()

    async def list_youtube_uploads(self, audiobook_id: UUID) -> list[Any]:
        from drevalis.repositories.youtube import YouTubeAudiobookUploadRepository

        audiobook = await self._repo.get_by_id(audiobook_id)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)

        upload_repo = YouTubeAudiobookUploadRepository(self._db)
        return list(await upload_repo.get_by_audiobook(audiobook_id))

    # ── Delete ───────────────────────────────────────────────────────────

    async def delete(self, audiobook_id: UUID) -> None:
        audiobook = await self._repo.get_by_id(audiobook_id)
        if audiobook is None:
            raise NotFoundError("Audiobook", audiobook_id)

        audiobook_dir = self._storage / "audiobooks" / str(audiobook_id)
        if audiobook_dir.exists():
            shutil.rmtree(audiobook_dir, ignore_errors=True)
            log.info(
                "audiobook.files_deleted",
                audiobook_id=str(audiobook_id),
                path=str(audiobook_dir),
            )

        await self._repo.delete(audiobook_id)
        await self._db.commit()


__all__ = ["AudiobookAdminService", "NoChannelSelectedError"]
