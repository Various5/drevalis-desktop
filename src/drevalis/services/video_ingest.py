"""VideoIngestService — upload, dedup, analyze enqueue, clip pick.

Layering: keeps the route file free of repository imports + filesystem
writes (audit F-A-01). Multipart parsing + ffprobe stay on the route
side because they're FastAPI / runtime concerns; the service receives
already-decoded content.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.repositories.asset import AssetRepository, VideoIngestJobRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.models.asset import Asset, VideoIngestJob

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

ProbeMediaCallable = Callable[[Path], Awaitable[tuple[int | None, int | None, float | None]]]


class VideoIngestService:
    def __init__(self, db: AsyncSession, storage_base_path: Path) -> None:
        self._db = db
        self._storage = Path(storage_base_path)
        self._assets = AssetRepository(db)
        self._jobs = VideoIngestJobRepository(db)

    async def upload_and_enqueue(
        self,
        *,
        contents: bytes,
        filename: str,
        mime_type: str | None,
        description: str | None,
        probe_media: ProbeMediaCallable,
    ) -> VideoIngestJob:
        """Persist the upload (or reuse a hash-matched existing Asset),
        create a queued ingest job, and enqueue the analyze worker."""
        if not contents:
            raise ValidationError("empty file")

        sha = hashlib.sha256(contents).hexdigest()
        existing = await self._assets.get_by_hash(sha)
        if existing is not None:
            asset = existing
        else:
            asset = await self._persist_asset(
                contents=contents,
                sha=sha,
                filename=filename,
                mime_type=mime_type,
                description=description,
                probe_media=probe_media,
            )

        job = await self._jobs.create(
            asset_id=asset.id,
            status="queued",
            stage=None,
            progress_pct=0,
        )
        await self._db.commit()

        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        await arq.enqueue_job("analyze_video_ingest", str(job.id))
        logger.info("video_ingest_enqueued", job_id=str(job.id), asset_id=str(asset.id))
        return job

    async def _persist_asset(
        self,
        *,
        contents: bytes,
        sha: str,
        filename: str,
        mime_type: str | None,
        description: str | None,
        probe_media: ProbeMediaCallable,
    ) -> Asset:
        asset_id = uuid4()
        rel = Path("assets") / "videos" / str(asset_id) / filename
        abs_path = self._storage / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(contents)
        width, height, duration = await probe_media(abs_path)
        return await self._assets.create(
            id=asset_id,
            kind="video",
            filename=filename,
            file_path=rel.as_posix(),
            file_size_bytes=len(contents),
            mime_type=mime_type,
            hash_sha256=sha,
            width=width,
            height=height,
            duration_seconds=duration,
            tags=["ingest"],
            description=description,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )

    async def get_job(self, job_id: UUID) -> VideoIngestJob:
        job = await self._jobs.get_by_id(job_id)
        if job is None:
            raise NotFoundError("VideoIngestJob", job_id)
        return job

    async def pick_clip(self, job_id: UUID, clip_index: int, series_id: UUID) -> None:
        job = await self._jobs.get_by_id(job_id)
        if job is None or job.status != "done":
            raise ValidationError("job is not ready")
        if not 0 <= clip_index < len(job.candidate_clips or []):
            raise ValidationError("clip_index out of range")

        from drevalis.core.redis import get_arq_pool

        arq = get_arq_pool()
        await arq.enqueue_job(
            "commit_video_ingest_clip",
            str(job_id),
            int(clip_index),
            str(series_id),
        )


__all__ = ["VideoIngestService"]
