"""Tests for ``api/routes/ab_tests.py``.

Thin router over ``ABTestService``. Pin layering + serialisation:

* ``ValidationError`` → 400, ``NotFoundError`` → 404 on create
* ``NotFoundError`` → 404 on detail-fetch
* Detail endpoint composes per-episode stats + falls back to
  ``_missing_stats`` placeholder when an episode row was deleted out
  from under the pair (rare but possible since the pair only soft-
  references episodes by FK).
* ``_serialise`` formats datetimes as ISO-8601 (or ``""`` for
  ``created_at`` when the row was somehow created without a default).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.ab_tests import (
    ABTestCreate,
    _missing_stats,
    _serialise,
    _service,
    create_ab_test,
    delete_ab_test,
    get_ab_test,
    list_ab_tests,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.services.ab_test import ABTestService


def _make_test(**overrides: Any) -> Any:
    t = MagicMock()
    t.id = overrides.get("id", uuid4())
    t.series_id = overrides.get("series_id", uuid4())
    t.episode_a_id = overrides.get("episode_a_id", uuid4())
    t.episode_b_id = overrides.get("episode_b_id", uuid4())
    t.variant_label = overrides.get("variant_label", "title-A")
    t.notes = overrides.get("notes")
    t.winner_episode_id = overrides.get("winner_episode_id")
    t.comparison_at = overrides.get("comparison_at")
    t.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    return t


def _stats_payload(episode_id: Any) -> dict[str, Any]:
    return {
        "episode_id": episode_id,
        "title": "Hook A",
        "status": "exported",
        "youtube_video_id": "abc123",
        "youtube_url": "https://youtu.be/abc123",
        "youtube_views": 4500,
        "youtube_likes": 120,
        "youtube_comments": 10,
    }


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service_bound_to_session(self) -> None:
        db = AsyncMock()
        svc = _service(db=db)
        assert isinstance(svc, ABTestService)


# ── _serialise ──────────────────────────────────────────────────────


class TestSerialise:
    def test_iso_format_for_dates(self) -> None:
        t = _make_test(comparison_at=datetime(2026, 5, 1, 12, 30))
        out = _serialise(t)
        assert out.created_at == "2026-01-01T00:00:00"
        assert out.comparison_at == "2026-05-01T12:30:00"

    def test_none_dates_handled(self) -> None:
        # comparison_at is None until the worker settles the test;
        # serialiser must not crash on the absent timestamp.
        t = _make_test(comparison_at=None)
        out = _serialise(t)
        assert out.comparison_at is None

    def test_missing_created_at_becomes_empty_string(self) -> None:
        # Defensive: created_at should be set by SQLAlchemy default but
        # if a unit test passes a partially-mocked row, the serialiser
        # falls back to "" rather than crashing on .isoformat() of None.
        t = _make_test(created_at=None)
        out = _serialise(t)
        assert out.created_at == ""


# ── _missing_stats placeholder ──────────────────────────────────────


class TestMissingStats:
    def test_placeholder_marks_status_deleted(self) -> None:
        eid = uuid4()
        s = _missing_stats(eid)
        assert s.episode_id == eid
        assert s.status == "deleted"
        assert s.youtube_views is None


# ── POST / ──────────────────────────────────────────────────────────


class TestCreateAbTest:
    async def test_success_returns_serialised(self) -> None:
        svc = MagicMock()
        t = _make_test()
        svc.create = AsyncMock(return_value=t)

        body = ABTestCreate(
            series_id=t.series_id,
            episode_a_id=t.episode_a_id,
            episode_b_id=t.episode_b_id,
            variant_label="A vs B",
        )
        out = await create_ab_test(body, svc=svc)

        assert out.id == t.id
        assert out.variant_label == "title-A"

    async def test_validation_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=ValidationError("same episode twice"))
        body = ABTestCreate(
            series_id=uuid4(),
            episode_a_id=uuid4(),
            episode_b_id=uuid4(),
            variant_label="x",
        )
        with pytest.raises(HTTPException) as exc:
            await create_ab_test(body, svc=svc)
        assert exc.value.status_code == 400

    async def test_not_found_error_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=NotFoundError("episode", uuid4()))
        body = ABTestCreate(
            series_id=uuid4(),
            episode_a_id=uuid4(),
            episode_b_id=uuid4(),
            variant_label="x",
        )
        with pytest.raises(HTTPException) as exc:
            await create_ab_test(body, svc=svc)
        assert exc.value.status_code == 404


# ── GET / ───────────────────────────────────────────────────────────


class TestListAbTests:
    async def test_lists_all_when_no_filter(self) -> None:
        svc = MagicMock()
        svc.list_all = AsyncMock(return_value=[_make_test(), _make_test()])
        out = await list_ab_tests(series_id=None, svc=svc)
        assert len(out) == 2
        svc.list_all.assert_awaited_once_with(None)

    async def test_filters_by_series(self) -> None:
        svc = MagicMock()
        svc.list_all = AsyncMock(return_value=[])
        sid = uuid4()
        await list_ab_tests(series_id=sid, svc=svc)
        svc.list_all.assert_awaited_once_with(sid)


# ── GET /{test_id} ──────────────────────────────────────────────────


class TestGetAbTest:
    async def test_detail_includes_both_episode_stats(self) -> None:
        svc = MagicMock()
        t = _make_test()
        svc.get = AsyncMock(return_value=t)
        svc.stats_for_pair = AsyncMock(
            return_value={
                t.episode_a_id: _stats_payload(t.episode_a_id),
                t.episode_b_id: _stats_payload(t.episode_b_id),
            }
        )
        out = await get_ab_test(t.id, svc=svc)
        assert out.episode_a_stats.youtube_views == 4500
        assert out.episode_b_stats.youtube_views == 4500

    async def test_missing_episode_falls_back_to_placeholder(self) -> None:
        # Episode A row was deleted (DB cascade left A out of the
        # stats map). Placeholder must surface so the UI can render
        # a "(missing episode)" tile rather than throw 500.
        svc = MagicMock()
        t = _make_test()
        svc.get = AsyncMock(return_value=t)
        svc.stats_for_pair = AsyncMock(
            return_value={t.episode_b_id: _stats_payload(t.episode_b_id)}
        )
        out = await get_ab_test(t.id, svc=svc)
        assert out.episode_a_stats.status == "deleted"
        assert out.episode_b_stats.status == "exported"

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("ab_test", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_ab_test(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── DELETE /{test_id} ───────────────────────────────────────────────


class TestDeleteAbTest:
    async def test_delegates_to_service(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        tid = uuid4()
        await delete_ab_test(tid, svc=svc)
        svc.delete.assert_awaited_once_with(tid)
