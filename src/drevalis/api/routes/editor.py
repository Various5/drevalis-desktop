"""Video editor session routes.

Layering: this router calls ``EditorService`` only. No repository
imports, no FFmpeg subprocess invocation here (audit F-A-01).

One session row per episode. ``GET`` auto-creates a session seeded from
the episode's existing scenes/voice/music. ``PUT`` overwrites the
timeline. ``POST /render`` enqueues an FFmpeg render.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession  # runtime import — FastAPI

# needs to resolve ``AsyncSession = Depends(get_db)`` at wiring time.
from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.services.editor import EditorService, WaveformRenderError

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["editor"])


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EditorService:
    return EditorService(
        db,
        storage_base_path=settings.storage_base_path,
        ffmpeg_path=settings.ffmpeg_path,
    )


class EditSessionResponse(BaseModel):
    id: UUID
    episode_id: UUID
    version: int
    timeline: dict[str, Any]
    last_render_job_id: UUID | None
    last_rendered_at: datetime | None
    final_video_path: str | None = None


class TimelineUpdate(BaseModel):
    timeline: dict[str, Any]


class CaptionWord(BaseModel):
    word: str
    start_seconds: float
    end_seconds: float
    emphasis: bool = False
    color: str | None = None


class CaptionWordsPayload(BaseModel):
    words: list[CaptionWord]


@router.get(
    "/api/v1/episodes/{episode_id}/editor",
    response_model=EditSessionResponse,
)
async def get_editor_session(
    episode_id: UUID,
    svc: EditorService = Depends(_service),
) -> EditSessionResponse:
    """Return the edit session for this episode, auto-creating it from
    the current scene state if one doesn't yet exist.

    Wraps the lookup in targeted try/except so a 500 carries a real
    cause. The most common failure is migration 026 not being applied —
    we surface that specifically so users know to run alembic.
    """
    try:
        session, final_video_path = await svc.get_or_create(episode_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc
    except Exception as exc:
        logger.exception("editor_session_lookup_failed", episode_id=str(episode_id))
        msg = str(exc)
        if "video_edit_sessions" in msg and "does not exist" in msg:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                {
                    "error": "migration_missing",
                    "missing_table": "video_edit_sessions",
                    "hint": (
                        "Migration 026_video_edit_sessions hasn't been applied. "
                        "Run ``docker compose exec app alembic upgrade head`` "
                        "(or restart the app container — it runs migrations on startup)."
                    ),
                },
            ) from exc
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            {
                "error": "session_lookup_failed",
                "reason": f"{type(exc).__name__}: {msg[:200]}",
            },
        ) from exc

    return EditSessionResponse.model_validate(
        {
            "id": session.id,
            "episode_id": session.episode_id,
            "version": session.version,
            "timeline": session.timeline,
            "last_render_job_id": session.last_render_job_id,
            "last_rendered_at": session.last_rendered_at,
            "final_video_path": final_video_path,
        }
    )


@router.put(
    "/api/v1/episodes/{episode_id}/editor",
    response_model=EditSessionResponse,
)
async def save_editor_session(
    episode_id: UUID,
    body: TimelineUpdate,
    svc: EditorService = Depends(_service),
) -> EditSessionResponse:
    """Overwrite the timeline. The editor autosaves; callers should
    debounce so we aren't doing one commit per keystroke."""
    session, final_video_path = await svc.save(episode_id, body.timeline)
    return EditSessionResponse.model_validate(
        {
            "id": session.id,
            "episode_id": session.episode_id,
            "version": session.version,
            "timeline": session.timeline,
            "last_render_job_id": session.last_render_job_id,
            "last_rendered_at": session.last_rendered_at,
            "final_video_path": final_video_path,
        }
    )


@router.post(
    "/api/v1/episodes/{episode_id}/editor/render",
    status_code=status.HTTP_202_ACCEPTED,
)
async def render_editor_session(
    episode_id: UUID,
    svc: EditorService = Depends(_service),
) -> dict[str, str]:
    """Enqueue an FFmpeg render from the current timeline."""
    try:
        await svc.enqueue_render(episode_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no edit session") from exc
    return {"status": "enqueued"}


# ── Caption word editor ─────────────────────────────────────────────


@router.get(
    "/api/v1/episodes/{episode_id}/editor/captions",
    response_model=CaptionWordsPayload,
)
async def get_captions(
    episode_id: UUID,
    svc: EditorService = Depends(_service),
) -> CaptionWordsPayload:
    """Return the editable word-level caption list for the episode."""
    try:
        words = await svc.get_captions(episode_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc
    return CaptionWordsPayload(words=[CaptionWord.model_validate(w) for w in words])


@router.put(
    "/api/v1/episodes/{episode_id}/editor/captions",
    response_model=CaptionWordsPayload,
)
async def put_captions(
    episode_id: UUID,
    body: CaptionWordsPayload,
    svc: EditorService = Depends(_service),
) -> CaptionWordsPayload:
    """Overwrite the word-level caption list. The render worker reads
    this file (when present) to produce an edited ASS before burning
    captions over the final video."""
    try:
        await svc.put_captions(episode_id, [w.model_dump() for w in body.words])
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc
    return body


# ── Waveform generation ─────────────────────────────────────────────


@router.get(
    "/api/v1/episodes/{episode_id}/editor/waveform",
)
async def get_waveform(
    episode_id: UUID,
    track: str = "voice",
    svc: EditorService = Depends(_service),
) -> Any:
    """Render (or reuse) a waveform PNG for the voice or music track
    and stream it. Returns 404 if the track has no source asset."""
    try:
        out_path = await svc.render_waveform(episode_id, track)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no audio asset on this track") from exc
    except WaveformRenderError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "waveform render failed"
        ) from exc
    return FileResponse(str(out_path), media_type="image/png")


# ── Proxy preview ────────────────────────────────────────────────────


@router.post(
    "/api/v1/episodes/{episode_id}/editor/preview",
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_preview(
    episode_id: UUID,
    svc: EditorService = Depends(_service),
) -> dict[str, str]:
    """Enqueue a low-bitrate proxy render so scrubbing shows overlays
    + audio mixed without waiting for a full-quality export.

    Uses the same ``render_from_edit`` worker but hints proxy=true via
    an env-style sentinel in Redis. The worker reads it and outputs to
    ``output/proxy.mp4`` at 480p.
    """
    try:
        await svc.enqueue_preview(episode_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no edit session") from exc
    return {"status": "enqueued"}
