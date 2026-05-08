"""Content scheduling API routes.

Layering: this router calls ``ScheduleService`` only. No repository or
ORM imports here (audit F-A-01).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.schedule import (
    AutoScheduleRequest,
    AutoScheduleResponse,
    CalendarDay,
    DiagnosticsResponse,
    RetryFailedRequest,
    RetryFailedResponse,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
)
from drevalis.services.schedule import ScheduleService, to_response
from drevalis.services.schedule_slot import find_next_free_slot

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/schedule", tags=["schedule"])


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScheduleService:
    return ScheduleService(db, app_timezone=settings.app_timezone)


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a post for future publishing",
)
async def create_scheduled_post(
    payload: ScheduleCreate,
    svc: ScheduleService = Depends(_service),
) -> ScheduleResponse:
    post = await svc.create(payload)
    logger.info("post_scheduled", post_id=str(post.id), platform=payload.platform)
    return to_response(post)


@router.get(
    "",
    response_model=list[ScheduleResponse],
    status_code=status.HTTP_200_OK,
    summary="List scheduled posts",
)
async def list_scheduled_posts(
    status_filter: str | None = Query(default=None, alias="status"),
    platform: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    svc: ScheduleService = Depends(_service),
) -> list[ScheduleResponse]:
    posts = await svc.list_filtered(status_filter=status_filter, platform=platform, limit=limit)
    return [to_response(p) for p in posts]


@router.get(
    "/calendar",
    response_model=list[CalendarDay],
    status_code=status.HTTP_200_OK,
    summary="Get calendar view of scheduled posts",
)
async def get_calendar(
    start: str = Query(..., description="ISO date e.g. 2026-03-01"),
    end: str = Query(..., description="ISO date e.g. 2026-03-31"),
    svc: ScheduleService = Depends(_service),
) -> list[CalendarDay]:
    grouped = await svc.get_calendar(start, end)
    return [
        CalendarDay(date=d, posts=[to_response(p) for p in ps]) for d, ps in sorted(grouped.items())
    ]


@router.put(
    "/{post_id}",
    response_model=ScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a scheduled post",
)
async def update_scheduled_post(
    post_id: UUID,
    payload: ScheduleUpdate,
    svc: ScheduleService = Depends(_service),
) -> ScheduleResponse:
    try:
        updated = await svc.update(post_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scheduled post not found") from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.detail) from exc
    return to_response(updated)


@router.delete(
    "/{post_id}",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Delete a scheduled post",
)
async def delete_scheduled_post(
    post_id: UUID,
    svc: ScheduleService = Depends(_service),
) -> dict[str, Any]:
    try:
        await svc.delete(post_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scheduled post not found") from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.detail) from exc
    return {"message": "Scheduled post deleted", "post_id": str(post_id)}


# ── Auto-schedule (series-level batch scheduling) ─────────────────────────


@router.post(
    "/series/{series_id}/auto-schedule",
    response_model=AutoScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Distribute review-ready unuploaded episodes across the calendar",
)
async def auto_schedule_series(
    series_id: UUID,
    payload: AutoScheduleRequest,
    svc: ScheduleService = Depends(_service),
) -> AutoScheduleResponse:
    """Walk a series' unuploaded episodes and queue scheduled YouTube posts.

    The first slot lands on the channel's first ``upload_days``-allowed
    date at the channel's ``upload_time``. Subsequent slots step by
    ``cadence`` (daily / every_n_days / weekly).

    ``dry_run=true`` returns the plan without persisting so callers can
    preview before committing.
    """
    try:
        planned, skipped, persisted = await svc.auto_schedule_series(series_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.detail) from exc
    return AutoScheduleResponse(
        series_id=series_id,
        cadence=payload.cadence,
        planned=planned,
        persisted=persisted,
        skipped_already_scheduled=skipped,
    )


# ── Diagnostics + manual retry ────────────────────────────────────────────


@router.get(
    "/diagnostics",
    response_model=DiagnosticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Why are uploads failing? Aggregate health of channels + recent posts",
)
async def get_diagnostics(
    within_hours: int = Query(default=72, ge=1, le=720),
    svc: ScheduleService = Depends(_service),
) -> DiagnosticsResponse:
    """Aggregate the data needed to diagnose 'uploads not working'.

    Returns:
      * Per-channel health (token expiry + refreshability + upload rules)
      * The N most recent failed scheduled posts with their error messages
      * Overdue posts still in ``scheduled`` status (worker-not-running
        smoke signal)
      * Summary counters
    """
    channels, recent_failed, overdue, summary = await svc.diagnostics(within_hours)
    return DiagnosticsResponse(
        channels=channels,
        recent_failed_posts=recent_failed,
        overdue_scheduled_posts=overdue,
        summary=summary,
    )


@router.get(
    "/next-slot",
    status_code=status.HTTP_200_OK,
    summary="Find the next free posting slot for a platform",
)
async def next_slot(
    platform: str = Query(
        ...,
        pattern="^(youtube|tiktok|instagram|facebook|x)$",
        description="Target social platform.",
    ),
    channel_id: UUID | None = Query(
        default=None,
        description=(
            "YouTube channel id — required-ish for ``platform=youtube`` to "
            "honour that channel's ``upload_days`` / ``upload_time``. "
            "Other platforms ignore it."
        ),
    ),
    exclude_window_minutes: int = Query(
        default=60,
        ge=0,
        le=1440,
        description=(
            "Slots within this many minutes of an existing pending post on "
            "the same platform are skipped. 0 disables the de-conflict step."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Returns the next allowed, non-conflicting posting slot.

    Uses ``youtube_channels.upload_days`` + ``upload_time`` for YouTube
    and a sensible weekday-09:00-UTC default elsewhere. The frontend
    Calendar dialog calls this to populate "Next available slot"
    instead of asking the user to pick a date and hope it doesn't
    clash with an existing scheduled post.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    try:
        slot = await find_next_free_slot(
            platform=platform,
            channel_id=channel_id,
            after_utc=_datetime.now(tz=_UTC),
            exclude_window_minutes=exclude_window_minutes,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"platform": platform, "scheduled_at": slot.isoformat()}


@router.post(
    "/retry-failed",
    response_model=RetryFailedResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset failed scheduled posts so the next cron tick re-attempts them",
)
async def retry_failed(
    payload: RetryFailedRequest,
    svc: ScheduleService = Depends(_service),
) -> RetryFailedResponse:
    """Manual companion to the 48h auto-retry-on-startup behaviour.

    Resets ``status='failed'`` posts back to ``'scheduled'`` (clearing
    ``error_message``) so the next ``publish_scheduled_posts`` cron
    tick picks them up. ``post_ids`` filters to specific posts;
    omitted/null = every failed post within ``within_hours``.
    """
    requeued, skipped = await svc.retry_failed(payload)
    return RetryFailedResponse(requeued=requeued, skipped=skipped)
