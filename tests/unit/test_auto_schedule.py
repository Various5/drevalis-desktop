"""Tests for the auto-schedule distributor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from drevalis.services.auto_schedule import (
    ScheduledSlot,
    _next_allowed_date,
    _normalise_upload_days,
    _parse_upload_time,
    plan_auto_schedule,
)


@dataclass
class _FakeEpisode:
    id: UUID
    title: str
    created_at: datetime


def _ep(title: str, n: int) -> _FakeEpisode:
    return _FakeEpisode(
        id=uuid4(),
        title=title,
        created_at=datetime(2026, 4, 1, 12, 0, n, tzinfo=UTC),
    )


# ── Helpers ─────────────────────────────────────────────────────────────


class TestNormaliseUploadDays:
    def test_none_returns_all_days(self) -> None:
        assert _normalise_upload_days(None) == {0, 1, 2, 3, 4, 5, 6}

    def test_empty_list_returns_all_days(self) -> None:
        assert _normalise_upload_days([]) == {0, 1, 2, 3, 4, 5, 6}

    def test_named_days_resolve_to_indices(self) -> None:
        result = _normalise_upload_days(["Monday", "wednesday", "FRIDAY"])
        assert result == {0, 2, 4}

    def test_unknown_names_dropped(self) -> None:
        result = _normalise_upload_days(["monday", "blursday", "tuesday"])
        assert result == {0, 1}

    def test_all_unknown_falls_back_to_all_days(self) -> None:
        result = _normalise_upload_days(["blursday"])
        assert result == {0, 1, 2, 3, 4, 5, 6}


class TestParseUploadTime:
    def test_valid_hh_mm(self) -> None:
        t = _parse_upload_time("14:30")
        assert t.hour == 14
        assert t.minute == 30

    def test_none_defaults_to_9am(self) -> None:
        t = _parse_upload_time(None)
        assert t.hour == 9
        assert t.minute == 0

    def test_invalid_format_defaults_to_9am(self) -> None:
        t = _parse_upload_time("not-a-time")
        assert t.hour == 9


class TestNextAllowedDate:
    def test_already_allowed_returns_unchanged(self) -> None:
        from datetime import date as _date

        # Wednesday 2026-04-01 has weekday == 2.
        result = _next_allowed_date(after=_date(2026, 4, 1), allowed_weekdays={2})
        assert result == _date(2026, 4, 1)

    def test_skips_to_next_allowed(self) -> None:
        from datetime import date as _date

        # Wed (weekday 2). Allow only Saturday (5). Should jump 3 days.
        result = _next_allowed_date(after=_date(2026, 4, 1), allowed_weekdays={5})
        assert result == _date(2026, 4, 4)


# ── plan_auto_schedule ──────────────────────────────────────────────────


class TestPlanAutoSchedule:
    def test_empty_episodes_returns_empty(self) -> None:
        slots = plan_auto_schedule(
            episodes=[],
            start_at_utc=datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
            cadence="daily",
            every_n=1,
            upload_days=None,
            upload_time="09:00",
            timezone="UTC",
            youtube_channel_id=None,
            privacy="private",
        )
        assert slots == []

    def test_daily_cadence_consecutive_days(self) -> None:
        eps = [_ep(f"Ep {i}", i) for i in range(3)]
        slots = plan_auto_schedule(
            episodes=eps,
            start_at_utc=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),  # Friday
            cadence="daily",
            every_n=1,
            upload_days=None,
            upload_time="09:00",
            timezone="UTC",
            youtube_channel_id=None,
            privacy="private",
        )
        assert len(slots) == 3
        assert slots[0].scheduled_at_utc == datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
        assert slots[1].scheduled_at_utc == datetime(2026, 5, 2, 9, 0, tzinfo=UTC)
        assert slots[2].scheduled_at_utc == datetime(2026, 5, 3, 9, 0, tzinfo=UTC)

    def test_every_n_days_cadence(self) -> None:
        eps = [_ep(f"Ep {i}", i) for i in range(3)]
        slots = plan_auto_schedule(
            episodes=eps,
            start_at_utc=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            cadence="every_n_days",
            every_n=3,
            upload_days=None,
            upload_time="09:00",
            timezone="UTC",
            youtube_channel_id=None,
            privacy="private",
        )
        assert len(slots) == 3
        assert slots[0].scheduled_at_utc.day == 1
        assert slots[1].scheduled_at_utc.day == 4
        assert slots[2].scheduled_at_utc.day == 7

    def test_weekly_cadence_honours_upload_days(self) -> None:
        # Three episodes, allow Monday + Thursday (two upload days).
        # Should cycle: Mon → Thu → Mon.
        eps = [_ep(f"Ep {i}", i) for i in range(3)]
        slots = plan_auto_schedule(
            episodes=eps,
            start_at_utc=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),  # Monday
            cadence="weekly",
            every_n=1,
            upload_days=["Monday", "Thursday"],
            upload_time="09:00",
            timezone="UTC",
            youtube_channel_id=None,
            privacy="private",
        )
        assert len(slots) == 3
        # Mon May 4 → Thu May 7 → Mon May 11.
        assert slots[0].scheduled_at_utc.weekday() == 0
        assert slots[1].scheduled_at_utc.weekday() == 3
        assert slots[2].scheduled_at_utc.weekday() == 0
        assert (slots[1].scheduled_at_utc - slots[0].scheduled_at_utc).days == 3
        assert (slots[2].scheduled_at_utc - slots[1].scheduled_at_utc).days == 4

    def test_first_slot_in_past_skips_to_next_day(self) -> None:
        # Start at 14:00 UTC but upload_time is 09:00 — first slot
        # would be 09:00 today (in the past), so push to tomorrow.
        eps = [_ep("Ep", 0)]
        slots = plan_auto_schedule(
            episodes=eps,
            start_at_utc=datetime(2026, 5, 1, 14, 0, tzinfo=UTC),
            cadence="daily",
            every_n=1,
            upload_days=None,
            upload_time="09:00",
            timezone="UTC",
            youtube_channel_id=None,
            privacy="private",
        )
        assert len(slots) == 1
        assert slots[0].scheduled_at_utc > datetime(2026, 5, 1, 14, 0, tzinfo=UTC)

    def test_upload_days_filter_applied(self) -> None:
        # Allow only Saturday. 5 episodes → 5 consecutive Saturdays.
        eps = [_ep(f"Ep {i}", i) for i in range(5)]
        slots = plan_auto_schedule(
            episodes=eps,
            start_at_utc=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),  # Friday
            cadence="daily",  # daily but only Saturdays allowed
            every_n=1,
            upload_days=["Saturday"],
            upload_time="09:00",
            timezone="UTC",
            youtube_channel_id=None,
            privacy="private",
        )
        assert len(slots) == 5
        for slot in slots:
            assert slot.scheduled_at_utc.weekday() == 5
        # Each 7 days apart.
        for i in range(1, 5):
            delta = (slots[i].scheduled_at_utc - slots[i - 1].scheduled_at_utc).days
            assert delta == 7

    def test_titles_and_channel_propagate(self) -> None:
        ch = uuid4()
        eps = [_ep("Hello World", 0)]
        slots = plan_auto_schedule(
            episodes=eps,
            start_at_utc=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            cadence="daily",
            every_n=1,
            upload_days=None,
            upload_time="09:00",
            timezone="UTC",
            youtube_channel_id=ch,
            privacy="public",
            description_template="Subscribe!",
            tags_template="ai,shorts",
        )
        assert slots[0].title == "Hello World"
        assert slots[0].youtube_channel_id == ch
        assert slots[0].privacy == "public"
        assert slots[0].description == "Subscribe!"
        assert slots[0].tags == "ai,shorts"

    def test_every_n_clamped_to_minimum_one(self) -> None:
        eps = [_ep("a", 0), _ep("b", 1)]
        slots = plan_auto_schedule(
            episodes=eps,
            start_at_utc=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            cadence="every_n_days",
            every_n=0,  # invalid → clamped
            upload_days=None,
            upload_time="09:00",
            timezone="UTC",
            youtube_channel_id=None,
            privacy="private",
        )
        # ``0 → 1`` means consecutive days.
        assert (slots[1].scheduled_at_utc - slots[0].scheduled_at_utc).days == 1

    def test_long_title_truncated(self) -> None:
        eps = [_FakeEpisode(id=uuid4(), title="x" * 1000, created_at=datetime.now(UTC))]
        slots = plan_auto_schedule(
            episodes=eps,
            start_at_utc=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            cadence="daily",
            every_n=1,
            upload_days=None,
            upload_time="09:00",
            timezone="UTC",
            youtube_channel_id=None,
            privacy="private",
        )
        assert len(slots[0].title) <= 500


# ── ScheduledSlot dataclass ─────────────────────────────────────────────


class TestScheduledSlot:
    def test_is_immutable(self) -> None:
        slot = ScheduledSlot(
            episode_id=uuid4(),
            scheduled_at_utc=datetime.now(UTC),
            title="x",
            description="",
            tags="",
            privacy="private",
            youtube_channel_id=None,
        )
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            slot.title = "y"  # type: ignore[misc]
