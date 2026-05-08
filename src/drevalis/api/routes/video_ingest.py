"""Video-ingest routes.

Layering: this router calls ``VideoIngestService`` only. No repository
imports; multipart parsing + ffprobe stay here because they're FastAPI
runtime concerns (audit F-A-01).

Flow:

1. ``POST /api/v1/video-ingest`` — upload a raw video. The endpoint
   creates (or dedups to) an Asset, enqueues an ``analyze_video_ingest``
   worker job, and returns a ``VideoIngestJobResponse`` the UI polls.
2. ``GET  /api/v1/video-ingest/{job_id}`` — status + candidate clips
   once ``status=done``.
3. ``POST /api/v1/video-ingest/{job_id}/pick`` — operator commits to
   one of the candidates, optionally assigning the new episode to a
   series. Returns the freshly created ``episode_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession  # runtime import — FastAPI Depends

from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.services.video_ingest import VideoIngestService

if TYPE_CHECKING:
    from drevalis.core.config import Settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["video-ingest"])


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VideoIngestService:
    return VideoIngestService(db, settings.storage_base_path)


class CandidateClip(BaseModel):
    start_s: float
    end_s: float
    title: str
    reason: str
    score: float


class VideoIngestJobResponse(BaseModel):
    id: UUID
    asset_id: UUID
    status: str
    stage: str | None
    progress_pct: int
    candidate_clips: list[CandidateClip] | None
    selected_clip_index: int | None
    resulting_episode_id: UUID | None
    error_message: str | None


class PickRequest(BaseModel):
    clip_index: int
    series_id: UUID


@router.post(
    "/api/v1/video-ingest",
    response_model=VideoIngestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_video_ingest(
    file: UploadFile = File(...),
    description: str | None = Form(default=None),
    svc: VideoIngestService = Depends(_service),
) -> VideoIngestJobResponse:
    """Upload a video and kick off the analyze-and-pick pipeline."""
    from drevalis.api.routes.assets import _probe_media, _safe_filename

    if not (file.content_type or "").startswith("video/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file must be a video")

    contents = await file.read()
    filename = _safe_filename(file.filename or "video.mp4")
    try:
        job = await svc.upload_and_enqueue(
            contents=contents,
            filename=filename,
            mime_type=file.content_type,
            description=description,
            probe_media=_probe_media,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
    return VideoIngestJobResponse(
        id=job.id,
        asset_id=job.asset_id,
        status=job.status,
        stage=job.stage,
        progress_pct=job.progress_pct,
        candidate_clips=None,
        selected_clip_index=None,
        resulting_episode_id=None,
        error_message=None,
    )


@router.get(
    "/api/v1/video-ingest/{job_id}",
    response_model=VideoIngestJobResponse,
)
async def get_video_ingest_job(
    job_id: UUID,
    svc: VideoIngestService = Depends(_service),
) -> VideoIngestJobResponse:
    try:
        job = await svc.get_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ingest job not found") from exc
    return VideoIngestJobResponse(
        id=job.id,
        asset_id=job.asset_id,
        status=job.status,
        stage=job.stage,
        progress_pct=job.progress_pct,
        candidate_clips=[CandidateClip.model_validate(c) for c in (job.candidate_clips or [])],
        selected_clip_index=job.selected_clip_index,
        resulting_episode_id=job.resulting_episode_id,
        error_message=job.error_message,
    )


@router.post(
    "/api/v1/video-ingest/{job_id}/pick",
    status_code=status.HTTP_201_CREATED,
)
async def pick_video_ingest_clip(
    job_id: UUID,
    body: PickRequest,
    svc: VideoIngestService = Depends(_service),
) -> dict[str, str]:
    """Commit to a candidate clip — creates a draft Episode from it."""
    try:
        await svc.pick_clip(job_id, body.clip_index, body.series_id)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
    return {"status": "enqueued"}
