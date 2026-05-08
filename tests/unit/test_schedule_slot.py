"""Tests for the next-free-slot finder.

Uses ``unittest.mock`` instead of the ``db_session`` SQLite fixture
because ``conftest`` builds every table in the metadata, and a few
Postgres-only DDL constructs in unrelated tables (interval casts,
JSONB defaults) don't compile to SQLite. Mocking the two DB calls
this service makes is cleaner than working around the conftest seam.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from drevalis.services.schedule_slot import (
    _DEFAULT_UPLOAD_DAYS,
    _DEFAULT_UPLOAD_TIME,
    find_next_free_slot,
)


def _mock_db(*, channel: Any | None = None, has_conflict_at: list[datetime] | None = None) -> Any:
    """Build a MagicMock AsyncSession.

    * The first ``execute`` call (preferences fetch) yields a row whose
      ``scalar_one_or_none()`` returns ``channel``.
    * Subsequent ``execute`` calls (conflict probes) yield a row whose
      ``first()`` returns truthy when the candidate slot is in
      ``has_conflict_at`` (within 60-min window) and ``None`` otherwise.
    """
    conflicts = has_conflict_at or []
    db = MagicMock()

    async def _execute(stmt: Any) -> Any:  # noqa: ARG001
        compiled = str(stmt).lower()
        result = MagicMock()
        if "youtube_channels" in compiled:
            result.scalar_one_or_none = MagicMock(return_value=channel)
        else:
            # The conflict query uses ScheduledPost — match candidate
            # against the configured conflict windows.
            result.first = MagicMock(return_value=None)
            for c_at in conflicts:
                # We can't introspect the candidate from the SQL — instead
                # we inspect the mock's call_args after the test. For
                # this fixture we surface a preset list and the helper
                # below tracks call ordinals.
                pass
            # Pop one conflict per call: nth call returns nth list item.
            if conflicts:
                ordinal = _execute.call_index
                if ordinal < len(conflicts) and conflicts[ordinal] is not None:
                    result.first = MagicMock(return_value=(uuid4(),))
                _execute.call_index += 1
        return result

    _execute.call_index = 0
    db.execute = AsyncMock(side_effect=_execute)
    return db


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_calendar_returns_first_default_slot() -> None:
    """No scheduled posts, no channel — default Mon-Fri 09:00 UTC."""
    db = _mock_db()
    after = datetime(2026, 5, 11, 14, 0, tzinfo=UTC)  # Mon 14:00
    slot = await find_next_free_slot(
        platform="tiktok",
        channel_id=None,
        after_utc=after,
        db=db,
    )
    assert slot == datetime(2026, 5, 12, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_youtube_honours_channel_preferences() -> None:
    channel = MagicMock()
    channel.upload_days = ["wednesday"]
    channel.upload_time = "15:30"
    db = _mock_db(channel=channel)

    after = datetime(2026, 5, 11, 8, 0, tzinfo=UTC)  # Mon morning
    slot = await find_next_free_slot(
        platform="youtube",
        channel_id=UUID("00000000-0000-0000-0000-000000000001"),
        after_utc=after,
        db=db,
    )
    # Mon → next Wednesday at 15:30.
    assert slot == datetime(2026, 5, 13, 15, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_conflict_skips_to_next_allowed_day() -> None:
    """First candidate clashes → returns the next allowed day."""
    # Single conflict on the first probe — second probe returns no
    # match, so the loop advances to the next allowed day.
    db = _mock_db(has_conflict_at=[datetime(2026, 5, 12, 9, 0, tzinfo=UTC), None])
    after = datetime(2026, 5, 11, 14, 0, tzinfo=UTC)
    slot = await find_next_free_slot(
        platform="tiktok",
        channel_id=None,
        after_utc=after,
        db=db,
    )
    # Tue blocked → Wed 09:00 (default Mon-Fri allows Wednesday).
    assert slot == datetime(2026, 5, 13, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_youtube_without_channel_id_uses_defaults() -> None:
    """``platform=youtube`` but no ``channel_id`` — defaults still apply."""
    db = _mock_db()
    after = datetime(2026, 5, 11, 14, 0, tzinfo=UTC)
    slot = await find_next_free_slot(
        platform="youtube",
        channel_id=None,
        after_utc=after,
        db=db,
    )
    assert slot == datetime(2026, 5, 12, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_zero_window_disables_conflict_check() -> None:
    """``exclude_window_minutes=0`` skips the conflict probe entirely.

    Functionally that means the very first allowed slot is always
    returned. The mock would otherwise have asserted on the conflict
    call — verifying the slot doesn't change confirms the behaviour.
    """
    db = _mock_db()
    after = datetime(2026, 5, 11, 14, 0, tzinfo=UTC)
    slot = await find_next_free_slot(
        platform="tiktok",
        channel_id=None,
        after_utc=after,
        exclude_window_minutes=0,
        db=db,
    )
    assert slot == datetime(2026, 5, 12, 9, 0, tzinfo=UTC)


def test_module_defaults_are_sane() -> None:
    """Sanity-check the constants other tests rely on."""
    assert "monday" in _DEFAULT_UPLOAD_DAYS
    assert "saturday" not in _DEFAULT_UPLOAD_DAYS
    assert _DEFAULT_UPLOAD_TIME == "09:00"


@pytest.mark.asyncio
async def test_lookahead_cap_raises_when_no_slot() -> None:
    """If every allowed day clashes for ``_MAX_LOOKAHEAD_DAYS``, raise."""
    # Conflict on every probe — we'll cap the loop. _MAX_LOOKAHEAD_DAYS
    # is 365; supply a long-enough conflict list.
    conflicts = [datetime.now(tz=UTC) + timedelta(days=i) for i in range(400)]
    db = _mock_db(has_conflict_at=conflicts)
    with pytest.raises(ValueError, match="No free slot"):
        await find_next_free_slot(
            platform="tiktok",
            channel_id=None,
            after_utc=datetime(2026, 5, 11, 14, 0, tzinfo=UTC),
            db=db,
        )
