"""Auto-schedule distributor.

Spreads ready-but-unuploaded episodes across the calendar at a chosen
cadence, optionally honouring the target YouTube channel's
``upload_days`` (weekday allow-list) and ``upload_time`` ("HH:MM" of
day in the channel's local sense). The result is a list of
``scheduled_posts`` rows the caller can persist.

The service does NOT touch the DB itself — it returns a plan so the
route handler can wrap creation + commit in a single transaction.

Inputs
------
- A list of episodes (already filtered by the caller to the upload-
  ready statuses ``review`` / ``exported``).
- A start datetime (UTC) — earliest publish slot to consider.
- A cadence (``daily`` / ``every_n_days`` / ``weekly`` — the latter
  uses the channel's ``upload_days`` set).
- ``every_n``: integer for ``every_n_days``; ignored otherwise.
- The target channel's ``upload_days`` (list of ISO weekday names)
  and ``upload_time`` ("HH:MM"). Either may be ``None``; defaults
  apply.
- The channel's preferred privacy + the operator's overrides.

Output
------
``list[ScheduledSlot]``: each slot carries the planned
``scheduled_at`` (UTC), the source episode id, and the resolved
title/description/tags/privacy/channel_id payload ready for
``ScheduledPostRepository.create``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog

logger = structlog.get_logger(__name__)

Cadence = Literal["daily", "every_n_days", "weekly"]


# Map ISO weekday names → Python's Monday=0..Sunday=6.
_WEEKDAY_INDEX: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True)
class ScheduledSlot:
    """One planned ``scheduled_posts`` row, pre-resolution."""

    episode_id: UUID
    scheduled_at_utc: datetime
    title: str
    description: str
    tags: str
    privacy: str
    youtube_channel_id: UUID | None


def _parse_upload_time(upload_time: str | None) -> time:
    """Parse ``"HH:MM"`` → ``time``. Defaults to 09:00 on parse failure."""
    if not upload_time:
        return time(9, 0)
    try:
        hh, mm = upload_time.split(":", 1)
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        logger.warning("auto_schedule.bad_upload_time", value=upload_time)
        return time(9, 0)


def _normalise_upload_days(upload_days: Iterable[Any] | None) -> set[int]:
    """Return the channel's allowed weekday indices.

    ``None`` / empty → every day. Strings normalise to lowercase ISO
    weekday names; unknown names are dropped with a warning.
    """
    if not upload_days:
        return {0, 1, 2, 3, 4, 5, 6}
    out: set[int] = set()
    for name in upload_days:
        if not isinstance(name, str):
            continue
        idx = _WEEKDAY_INDEX.get(name.strip().lower())
        if idx is None:
            logger.warning("auto_schedule.unknown_upload_day", value=name)
            continue
        out.add(idx)
    return out or {0, 1, 2, 3, 4, 5, 6}


def _next_allowed_date(*, after: date, allowed_weekdays: set[int]) -> date:
    """First date ≥ *after* whose weekday ∈ *allowed_weekdays*."""
    cursor = after
    for _ in range(7):  # any allow-list has a hit within 7 days
        if cursor.weekday() in allowed_weekdays:
            return cursor
        cursor += timedelta(days=1)
    # Empty allow-list shouldn't reach here (normalised to all-days),
    # but fail safe.
    return after


def plan_auto_schedule(
    *,
    episodes: list[Any],
    start_at_utc: datetime,
    cadence: Cadence,
    every_n: int,
    upload_days: Iterable[Any] | None,
    upload_time: str | None,
    timezone: str,
    youtube_channel_id: UUID | None,
    privacy: str,
    description_template: str = "",
    tags_template: str = "",
) -> list[ScheduledSlot]:
    """Walk *episodes* and emit one slot per episode at the right cadence.

    *episodes* must each carry an ``id`` (UUID) and a ``title`` (str).
    They're consumed in iteration order; caller is responsible for the
    sort (typically ``created_at ASC`` for "oldest first" or
    ``created_at DESC`` for "newest first").

    The first slot lands on the first ``upload_days``-allowed date at
    or after ``start_at_utc``'s local date, at the channel's
    ``upload_time``. Subsequent slots step by ``cadence`` (skipping
    disallowed weekdays for ``daily`` / ``every_n_days``; ``weekly``
    just rotates through ``upload_days`` order).

    Empty *episodes* returns ``[]``; ``every_n < 1`` is clamped to 1.
    """
    if not episodes:
        return []
    every_n = max(1, every_n)

    tz = ZoneInfo(timezone)
    local_start = start_at_utc.astimezone(tz)
    upload_at = _parse_upload_time(upload_time)
    allowed = _normalise_upload_days(upload_days)

    slots: list[ScheduledSlot] = []
    cursor = _next_allowed_date(after=local_start.date(), allowed_weekdays=allowed)

    for ep in episodes:
        # If the requested moment-of-day is in the past on the FIRST
        # iteration AND we're already on ``local_start.date``, skip
        # forward one allowed day so the slot is genuinely in the
        # future.
        local_at = datetime.combine(cursor, upload_at, tzinfo=tz)
        if not slots and local_at <= local_start:
            cursor = _next_allowed_date(after=cursor + timedelta(days=1), allowed_weekdays=allowed)
            local_at = datetime.combine(cursor, upload_at, tzinfo=tz)

        slot_utc = local_at.astimezone(UTC)

        title = getattr(ep, "title", None) or f"Episode {getattr(ep, 'id', '')}"
        slots.append(
            ScheduledSlot(
                episode_id=ep.id,
                scheduled_at_utc=slot_utc,
                title=str(title)[:500],
                description=description_template,
                tags=tags_template,
                privacy=privacy,
                youtube_channel_id=youtube_channel_id,
            )
        )

        # Advance the cursor for the next episode.
        if cadence == "daily":
            cursor = _next_allowed_date(after=cursor + timedelta(days=1), allowed_weekdays=allowed)
        elif cadence == "every_n_days":
            cursor = _next_allowed_date(
                after=cursor + timedelta(days=every_n), allowed_weekdays=allowed
            )
        elif cadence == "weekly":
            # Step forward one day, then land on the next allowed
            # weekday in the allow-list. With a multi-day allow-list
            # this rotates through them; with a single-day allow-list
            # this is effectively "+7 days".
            cursor = _next_allowed_date(after=cursor + timedelta(days=1), allowed_weekdays=allowed)
        else:
            # Unknown cadence — caller should have validated, but
            # fall through with daily as the safe default.
            cursor = _next_allowed_date(after=cursor + timedelta(days=1), allowed_weekdays=allowed)

    return slots
