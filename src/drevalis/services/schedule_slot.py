"""Find the next free posting slot for a single platform.

Companion to ``services/auto_schedule.py`` which plans many slots at
once. This module answers a different question: "if I want to schedule
ONE more episode on ``platform``, when's the next sensible time?"

Reused by:

* ``GET /api/v1/schedule/next-slot`` — frontend Calendar dialog button.
* (future) Episode detail page — quick "schedule" action.

Rules:

* Slot must be at or after ``after_utc`` (caller passes ``now`` for the
  typical case; allows future-dated planning too).
* Slot must match the platform's ``upload_days`` / ``upload_time``
  preferences when available. YouTube preferences live on
  ``youtube_channels``; for other platforms we use a sensible default
  (every day, 09:00 UTC) until per-platform schedule prefs land.
* Slot must NOT be within ``exclude_window_minutes`` of any other
  ``scheduled_posts`` row for the same platform (and same YouTube
  channel, for ``platform=youtube``). The default 60-minute buffer
  matches the YouTube algorithm's "don't post twice in the same hour"
  guidance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.scheduled_post import ScheduledPost
from drevalis.models.youtube_channel import YouTubeChannel
from drevalis.services.auto_schedule import (
    _next_allowed_date,
    _normalise_upload_days,
    _parse_upload_time,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Defaults applied when the platform has no upload-day/time preferences.
# Daily 09:00 UTC matches YouTube Studio's typical "best-time" default.
_DEFAULT_UPLOAD_DAYS: list[str] = ["monday", "tuesday", "wednesday", "thursday", "friday"]
_DEFAULT_UPLOAD_TIME = "09:00"
_DEFAULT_TIMEZONE = "UTC"
# Look at most this far into the future before giving up. 365 days
# means even a "post once a year" cadence resolves; in practice the
# loop short-circuits within a handful of iterations.
_MAX_LOOKAHEAD_DAYS = 365


async def _platform_preferences(
    *,
    platform: str,
    channel_id: UUID | None,
    db: AsyncSession,
) -> tuple[list[Any] | None, str | None, str]:
    """Return ``(upload_days, upload_time, timezone)`` for *platform*.

    YouTube reads from the ``youtube_channels`` row when ``channel_id``
    is supplied; falls back to defaults otherwise. Other platforms
    don't have a stored preference yet — the defaults apply.
    """
    if platform == "youtube" and channel_id is not None:
        row = await db.execute(select(YouTubeChannel).where(YouTubeChannel.id == channel_id))
        channel = row.scalar_one_or_none()
        if channel is not None:
            return (channel.upload_days, channel.upload_time, _DEFAULT_TIMEZONE)
    return (_DEFAULT_UPLOAD_DAYS, _DEFAULT_UPLOAD_TIME, _DEFAULT_TIMEZONE)


async def _conflicts(
    *,
    platform: str,
    channel_id: UUID | None,
    candidate_utc: datetime,
    window: timedelta,
    db: AsyncSession,
) -> bool:
    """True if any pending / queued ``scheduled_posts`` row falls within
    ``window`` of ``candidate_utc`` on the same platform (+ same
    YouTube channel when applicable).

    ``done`` and ``failed`` rows are ignored — we only care about
    upcoming traffic, not historical rows.
    """
    lower = candidate_utc - window
    upper = candidate_utc + window
    where = [
        ScheduledPost.platform == platform,
        ScheduledPost.scheduled_at >= lower,
        ScheduledPost.scheduled_at <= upper,
        ScheduledPost.status.in_(["pending", "queued"]),
    ]
    if platform == "youtube" and channel_id is not None:
        where.append(ScheduledPost.youtube_channel_id == channel_id)
    row = await db.execute(select(ScheduledPost.id).where(and_(*where)).limit(1))
    return row.first() is not None


async def find_next_free_slot(
    *,
    platform: str,
    channel_id: UUID | None,
    after_utc: datetime,
    exclude_window_minutes: int = 60,
    db: AsyncSession,
) -> datetime:
    """Return the next allowed, non-conflicting posting slot.

    Always returns a UTC ``datetime``. Raises ``ValueError`` if no slot
    can be found within ``_MAX_LOOKAHEAD_DAYS`` (effectively never under
    sane preferences).
    """
    upload_days, upload_time, tz_name = await _platform_preferences(
        platform=platform, channel_id=channel_id, db=db
    )
    tz = ZoneInfo(tz_name)
    upload_at = _parse_upload_time(upload_time)
    allowed = _normalise_upload_days(upload_days)
    window = timedelta(minutes=exclude_window_minutes)

    local_after = after_utc.astimezone(tz)
    cursor = _next_allowed_date(after=local_after.date(), allowed_weekdays=allowed)

    for _ in range(_MAX_LOOKAHEAD_DAYS):
        local_at = datetime.combine(cursor, upload_at, tzinfo=tz)
        if local_at <= local_after:
            cursor = _next_allowed_date(after=cursor + timedelta(days=1), allowed_weekdays=allowed)
            continue

        candidate_utc = local_at.astimezone(UTC)
        clash = await _conflicts(
            platform=platform,
            channel_id=channel_id,
            candidate_utc=candidate_utc,
            window=window,
            db=db,
        )
        if not clash:
            logger.info(
                "schedule.next_slot",
                platform=platform,
                slot=candidate_utc.isoformat(),
                channel_id=str(channel_id) if channel_id else None,
            )
            return candidate_utc

        cursor = _next_allowed_date(after=cursor + timedelta(days=1), allowed_weekdays=allowed)

    msg = (
        f"No free slot found within {_MAX_LOOKAHEAD_DAYS} days "
        f"for platform={platform} channel={channel_id}"
    )
    raise ValueError(msg)


# Re-exports for testability — the helpers above are intentionally
# private but a couple are convenient to assert against in tests.
__all__ = [
    "_DEFAULT_TIMEZONE",
    "_DEFAULT_UPLOAD_DAYS",
    "_DEFAULT_UPLOAD_TIME",
    "find_next_free_slot",
]
