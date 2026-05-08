"""Tests for ``api/routes/jobs/_monolith.py``.

Pin the layered job-control surface the Activity Monitor depends on:

* ``cancel_job``: NotFoundError → 404, InvalidStatusError → 409 with
  the current status in the detail (so the UI can say "this job is
  already done, nothing to cancel").
* ``set_priority``: InvalidStatusError → 422 (mode is unknown).
* ``list_all`` joins episode + series and surfaces titles + names.
* ``cleanup`` / ``cancel-all`` / ``retry-all-failed`` / ``pause-all``
  / ``restart_worker`` return human-readable summaries the toast
  layer renders verbatim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.jobs._monolith import (
    _service,
    cancel_all_jobs,
    cancel_job,
    cleanup_stale_jobs,
    get_active_tasks,
    get_job,
    get_priority,
    get_queue_status,
    list_active_jobs,
    list_all_jobs,
    list_jobs,
    pause_all,
    restart_worker,
    retry_all_failed,
    set_priority,
    worker_health,
)
from drevalis.core.exceptions import InvalidStatusError, NotFoundError
from drevalis.services.jobs import JobsService


def _settings() -> Any:
    s = MagicMock()
    s.max_concurrent_generations = 4
    return s


def _make_job(**overrides: Any) -> Any:
    j = MagicMock()
    j.id = overrides.get("id", uuid4())
    j.episode_id = overrides.get("episode_id", uuid4())
    j.step = overrides.get("step", "script")
    j.status = overrides.get("status", "queued")
    j.progress_pct = overrides.get("progress_pct", 0)
    j.started_at = overrides.get("started_at")
    j.completed_at = overrides.get("completed_at")
    j.error_message = overrides.get("error_message")
    j.retry_count = overrides.get("retry_count", 0)
    j.worker_id = overrides.get("worker_id")
    j.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    j.updated_at = overrides.get("updated_at", datetime(2026, 1, 1))
    j.episode = overrides.get("episode")
    return j


def _make_episode(title: str = "Hook A", series_name: str | None = None) -> Any:
    ep = MagicMock()
    ep.title = title
    if series_name is not None:
        s = MagicMock()
        s.name = series_name
        ep.series = s
    else:
        ep.series = None
    return ep


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service(self) -> None:
        svc = _service(db=AsyncMock())
        assert isinstance(svc, JobsService)


# ── GET /active + /status + /tasks/active ──────────────────────────


class TestActive:
    async def test_list_active_jobs(self) -> None:
        svc = MagicMock()
        svc.list_active = AsyncMock(return_value=[_make_job()])
        out = await list_active_jobs(limit=25, svc=svc)
        assert len(out) == 1
        svc.list_active.assert_awaited_once_with(25)

    async def test_queue_status_passes_concurrency(self) -> None:
        svc = MagicMock()
        svc.queue_status = AsyncMock(return_value={"running": 2, "queued": 0})
        # Patch effective_max_concurrent_generations so the license tier
        # active in the test process cannot cap the value below the
        # settings-derived 4.
        with patch(
            "drevalis.core.concurrency.effective_max_concurrent_generations",
            side_effect=lambda v: v,
        ):
            out = await get_queue_status(svc=svc, settings=_settings())
        assert out["running"] == 2
        svc.queue_status.assert_awaited_once_with(4)

    async def test_active_tasks_wraps_service_payload(self) -> None:
        svc = MagicMock()
        svc.active_tasks = AsyncMock(return_value=[{"task_id": "abc", "kind": "episode"}])
        out = await get_active_tasks(svc=svc)
        assert "tasks" in out
        assert out["tasks"][0]["task_id"] == "abc"


# ── Cleanup / cancel-all / retry-all / pause-all / restart ─────────


class TestBatchOperations:
    async def test_cleanup_includes_counts_in_message(self) -> None:
        svc = MagicMock()
        svc.cleanup_stale = AsyncMock(return_value={"cleaned_jobs": 3, "reset_episodes": 2})
        out = await cleanup_stale_jobs(svc=svc)
        assert "3 orphaned" in out["message"]
        assert "2 stale" in out["message"]
        assert out["cleaned_jobs"] == 3

    async def test_cancel_all_returns_count_message(self) -> None:
        svc = MagicMock()
        svc.cancel_all = AsyncMock(return_value={"cancelled_episodes": 5, "cancelled_jobs": 9})
        out = await cancel_all_jobs(svc=svc)
        assert "5 episode" in out["message"]
        assert out["cancelled_episodes"] == 5

    async def test_retry_all_failed_includes_priority(self) -> None:
        svc = MagicMock()
        svc.retry_all_failed = AsyncMock(return_value={"retried": 4})
        out = await retry_all_failed(priority="longform_first", svc=svc)
        assert "4 failed" in out["message"]
        assert "longform_first" in out["message"]

    async def test_pause_all(self) -> None:
        svc = MagicMock()
        svc.pause_all = AsyncMock(return_value=2)
        out = await pause_all(svc=svc)
        assert out["paused"] == 2

    async def test_restart_worker(self) -> None:
        svc = MagicMock()
        svc.restart_worker = AsyncMock(return_value=3)
        out = await restart_worker(svc=svc)
        assert out["reset_episodes"] == 3
        assert out["restart_signal_set"] is True


# ── set-priority / get-priority ────────────────────────────────────


class TestPriority:
    async def test_set_priority_success(self) -> None:
        svc = MagicMock()
        svc.set_priority = AsyncMock()
        out = await set_priority(mode="shorts_first", svc=svc)
        assert out["mode"] == "shorts_first"

    async def test_set_priority_invalid_maps_to_422(self) -> None:
        svc = MagicMock()
        svc.set_priority = AsyncMock(
            side_effect=InvalidStatusError("priority_mode", "x", current="x", allowed=["fifo"])
        )
        with pytest.raises(HTTPException) as exc:
            await set_priority(mode="bogus", svc=svc)
        assert exc.value.status_code == 422

    async def test_get_priority(self) -> None:
        svc = MagicMock()
        svc.get_priority = AsyncMock(return_value="fifo")
        out = await get_priority(svc=svc)
        assert out["mode"] == "fifo"


# ── List endpoints ─────────────────────────────────────────────────


class TestListAllJobs:
    async def test_joins_episode_and_series_titles(self) -> None:
        svc = MagicMock()
        # Job with episode + series.
        with_series = _make_job(episode=_make_episode("Hook A", series_name="Mech"))
        # Job with episode but no series.
        with_episode = _make_job(episode=_make_episode("Hook B", series_name=None))
        # Job with no episode (rare — orphaned job).
        no_episode = _make_job(episode=None)
        svc.list_all_filtered = AsyncMock(return_value=[with_series, with_episode, no_episode])
        out = await list_all_jobs(
            status_filter="queued",
            episode_id=None,
            step=None,
            limit=10,
            offset=0,
            svc=svc,
        )
        assert out[0].episode_title == "Hook A"
        assert out[0].series_name == "Mech"
        assert out[1].episode_title == "Hook B"
        assert out[1].series_name is None
        assert out[2].episode_title is None
        assert out[2].series_name is None

    async def test_passes_filters_to_service(self) -> None:
        svc = MagicMock()
        svc.list_all_filtered = AsyncMock(return_value=[])
        eid = uuid4()
        await list_all_jobs(
            status_filter="failed",
            episode_id=eid,
            step="voice",
            limit=25,
            offset=10,
            svc=svc,
        )
        kwargs = svc.list_all_filtered.call_args.kwargs
        assert kwargs == {
            "status_filter": "failed",
            "episode_id": eid,
            "step": "voice",
            "offset": 10,
            "limit": 25,
        }


class TestListJobs:
    async def test_passes_filters(self) -> None:
        svc = MagicMock()
        svc.list_filtered = AsyncMock(return_value=[])
        eid = uuid4()
        await list_jobs(episode_id=eid, status_filter="queued", limit=50, svc=svc)
        svc.list_filtered.assert_awaited_once_with(episode_id=eid, status_filter="queued", limit=50)


# ── Worker health/restart ──────────────────────────────────────────


class TestWorkerHealth:
    async def test_returns_service_payload(self) -> None:
        svc = MagicMock()
        svc.worker_health = AsyncMock(
            return_value={"healthy": True, "last_heartbeat_age_seconds": 12}
        )
        out = await worker_health(svc=svc)
        assert out["healthy"] is True


# ── POST /{job_id}/cancel ──────────────────────────────────────────


class TestCancelJob:
    async def test_success_returns_episode_cancelled(self) -> None:
        svc = MagicMock()
        eid = uuid4()
        svc.cancel_job = AsyncMock(return_value=(eid, True))
        jid = uuid4()
        out = await cancel_job(jid, svc=svc)
        assert out["episode_id"] == str(eid)
        assert out["episode_cancelled"] is True
        assert out["job_id"] == str(jid)

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.cancel_job = AsyncMock(side_effect=NotFoundError("generation_job", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await cancel_job(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_invalid_status_maps_to_409_with_current_status(self) -> None:
        # Pin: 409 detail surfaces ``current`` so the UI can say
        # "this job is already done" instead of generic conflict.
        svc = MagicMock()
        svc.cancel_job = AsyncMock(
            side_effect=InvalidStatusError(
                "generation_job", uuid4(), current="completed", allowed=["queued", "running"]
            )
        )
        with pytest.raises(HTTPException) as exc:
            await cancel_job(uuid4(), svc=svc)
        assert exc.value.status_code == 409
        assert "completed" in exc.value.detail


# ── GET /{job_id} ──────────────────────────────────────────────────


class TestGetJob:
    async def test_success(self) -> None:
        svc = MagicMock()
        j = _make_job()
        svc.get_job = AsyncMock(return_value=j)
        out = await get_job(j.id, svc=svc)
        assert out.id == j.id

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get_job = AsyncMock(side_effect=NotFoundError("generation_job", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_job(uuid4(), svc=svc)
        assert exc.value.status_code == 404
