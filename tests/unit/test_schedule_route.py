"""Tests for ``api/routes/schedule.py``.

Thin router over ``ScheduleService``. Pin the layering contract:
``NotFoundError`` → 404 across update/delete/auto-schedule;
``ValidationError`` → 409 on update/delete (publishing-state conflict);
``ValidationError`` → 422 on auto-schedule (invalid plan).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.schedule import (
    _service,
    auto_schedule_series,
    create_scheduled_post,
    delete_scheduled_post,
    get_calendar,
    get_diagnostics,
    list_scheduled_posts,
    retry_failed,
    update_scheduled_post,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.schedule import (
    AutoScheduleRequest,
    PlannedSlot,
    RetryFailedRequest,
    ScheduleCreate,
    ScheduleUpdate,
)
from drevalis.services.schedule import ScheduleService


def _make_post(**overrides: Any) -> Any:
    p = MagicMock()
    p.id = overrides.get("id", uuid4())
    p.content_type = overrides.get("content_type", "episode")
    p.content_id = overrides.get("content_id", uuid4())
    p.platform = overrides.get("platform", "youtube")
    p.scheduled_at = overrides.get("scheduled_at", datetime(2026, 5, 15, 12))
    p.title = overrides.get("title", "Hook A")
    p.description = overrides.get("description", "")
    p.tags = overrides.get("tags", "")
    p.privacy = overrides.get("privacy", "private")
    p.status = overrides.get("status", "scheduled")
    p.error_message = overrides.get("error_message")
    p.published_at = overrides.get("published_at")
    p.remote_id = overrides.get("remote_id")
    p.remote_url = overrides.get("remote_url")
    p.youtube_channel_id = overrides.get("youtube_channel_id")
    p.created_at = overrides.get("created_at", datetime(2026, 5, 1))
    return p


def _make_create() -> ScheduleCreate:
    return ScheduleCreate(
        content_type="episode",
        content_id=uuid4(),
        platform="youtube",
        scheduled_at=datetime(2026, 5, 15, 12, tzinfo=UTC),
        title="Hook",
    )


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service_with_app_timezone(self) -> None:
        db = AsyncMock()
        settings = MagicMock()
        settings.app_timezone = "Europe/Amsterdam"
        svc = _service(db=db, settings=settings)
        assert isinstance(svc, ScheduleService)


# ── POST / ──────────────────────────────────────────────────────────


class TestCreateScheduledPost:
    async def test_returns_response(self) -> None:
        svc = MagicMock()
        post = _make_post()
        svc.create = AsyncMock(return_value=post)
        out = await create_scheduled_post(_make_create(), svc=svc)
        assert out.id == post.id


# ── GET / ───────────────────────────────────────────────────────────


class TestListScheduledPosts:
    async def test_passes_filters_through(self) -> None:
        svc = MagicMock()
        svc.list_filtered = AsyncMock(return_value=[_make_post()])
        out = await list_scheduled_posts(
            status_filter="scheduled",
            platform="youtube",
            limit=25,
            svc=svc,
        )
        assert len(out) == 1
        svc.list_filtered.assert_awaited_once_with(
            status_filter="scheduled",
            platform="youtube",
            limit=25,
        )


# ── GET /calendar ───────────────────────────────────────────────────


class TestGetCalendar:
    async def test_groups_posts_by_date(self) -> None:
        svc = MagicMock()
        post1 = _make_post()
        post2 = _make_post()
        # Service returns a dict[date_str, list[post]]; router sorts.
        svc.get_calendar = AsyncMock(
            return_value={
                "2026-05-16": [post2],
                "2026-05-15": [post1],
            }
        )
        out = await get_calendar(start="2026-05-01", end="2026-05-31", svc=svc)
        # Sorted ascending by date.
        assert [d.date for d in out] == ["2026-05-15", "2026-05-16"]
        assert len(out[0].posts) == 1


# ── PUT /{id} ───────────────────────────────────────────────────────


class TestUpdateScheduledPost:
    async def test_success(self) -> None:
        svc = MagicMock()
        post = _make_post()
        svc.update = AsyncMock(return_value=post)
        out = await update_scheduled_post(post.id, ScheduleUpdate(title="renamed"), svc=svc)
        assert out.id == post.id

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=NotFoundError("scheduled_post", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_scheduled_post(uuid4(), ScheduleUpdate(), svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_error_maps_to_409(self) -> None:
        # Conflict: trying to edit a post that's already been published.
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ValidationError("already published"))
        with pytest.raises(HTTPException) as exc:
            await update_scheduled_post(uuid4(), ScheduleUpdate(), svc=svc)
        assert exc.value.status_code == 409


# ── DELETE /{id} ────────────────────────────────────────────────────


class TestDeleteScheduledPost:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        pid = uuid4()
        out = await delete_scheduled_post(pid, svc=svc)
        assert out["post_id"] == str(pid)
        assert out["message"]

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("scheduled_post", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_scheduled_post(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_error_maps_to_409(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=ValidationError("post is publishing"))
        with pytest.raises(HTTPException) as exc:
            await delete_scheduled_post(uuid4(), svc=svc)
        assert exc.value.status_code == 409


# ── POST /series/{id}/auto-schedule ─────────────────────────────────


class TestAutoSchedule:
    async def test_success_returns_plan(self) -> None:
        svc = MagicMock()
        sid = uuid4()
        slot = PlannedSlot(
            episode_id=uuid4(),
            episode_title="Ep1",
            scheduled_at=datetime(2026, 5, 16, 12, tzinfo=UTC),
            privacy="public",
            youtube_channel_id=None,
        )
        svc.auto_schedule_series = AsyncMock(return_value=([slot], [], True))
        body = AutoScheduleRequest(
            cadence="daily",
            start_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        out = await auto_schedule_series(sid, body, svc=svc)
        assert out.series_id == sid
        assert out.persisted is True
        assert out.planned[0].episode_title == "Ep1"

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.auto_schedule_series = AsyncMock(side_effect=NotFoundError("series", uuid4()))
        body = AutoScheduleRequest(start_at=datetime(2026, 5, 1, tzinfo=UTC))
        with pytest.raises(HTTPException) as exc:
            await auto_schedule_series(uuid4(), body, svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_error_maps_to_422(self) -> None:
        svc = MagicMock()
        svc.auto_schedule_series = AsyncMock(
            side_effect=ValidationError("no upload_days configured")
        )
        body = AutoScheduleRequest(start_at=datetime(2026, 5, 1, tzinfo=UTC))
        with pytest.raises(HTTPException) as exc:
            await auto_schedule_series(uuid4(), body, svc=svc)
        assert exc.value.status_code == 422


# ── GET /diagnostics + POST /retry-failed ──────────────────────────


class TestDiagnostics:
    async def test_aggregates_response(self) -> None:
        svc = MagicMock()
        svc.diagnostics = AsyncMock(return_value=([], [], [], {"failed": 0}))
        out = await get_diagnostics(within_hours=72, svc=svc)
        assert out.summary == {"failed": 0}
        svc.diagnostics.assert_awaited_once_with(72)


class TestRetryFailed:
    async def test_returns_requeued_and_skipped(self) -> None:
        svc = MagicMock()
        a, b = uuid4(), uuid4()
        svc.retry_failed = AsyncMock(return_value=([a], [b]))
        out = await retry_failed(RetryFailedRequest(within_hours=48), svc=svc)
        assert out.requeued == [a]
        assert out.skipped == [b]
