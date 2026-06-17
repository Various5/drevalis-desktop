"""Unit tests for ``ScheduleService.publish_missed_now``.

The route test (``test_schedule_route.py``) pins the thin delegation;
these pin the service's actual behaviour: it counts missed posts,
enqueues the publish job to run *now*, and degrades gracefully when the
arq pool is unavailable (rows are left untouched for the next cron tick).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.services.schedule import ScheduleService


def _service_with_missed(posts: list) -> ScheduleService:
    """Build a ScheduleService whose ``db.execute(...).scalars().all()``
    yields *posts* (the missed-post query result)."""
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = posts
    db.execute = AsyncMock(return_value=exec_result)
    return ScheduleService(db, app_timezone="UTC")


def _post():
    p = MagicMock()
    p.id = uuid4()
    return p


class TestPublishMissedNow:
    async def test_enqueues_and_returns_count(self) -> None:
        posts = [_post(), _post(), _post()]
        svc = _service_with_missed(posts)

        arq = MagicMock()
        arq.enqueue_job = AsyncMock()
        with patch("drevalis.core.redis.get_arq_pool", return_value=arq):
            out = await svc.publish_missed_now(within_hours=720)

        assert out["queued"] == 3
        assert out["enqueued"] is True
        assert len(out["post_ids"]) == 3
        assert all(isinstance(pid, str) for pid in out["post_ids"])
        arq.enqueue_job.assert_awaited_once_with("publish_scheduled_posts")

    async def test_no_missed_does_not_enqueue(self) -> None:
        svc = _service_with_missed([])

        arq = MagicMock()
        arq.enqueue_job = AsyncMock()
        with patch("drevalis.core.redis.get_arq_pool", return_value=arq):
            out = await svc.publish_missed_now()

        assert out == {"queued": 0, "enqueued": False, "post_ids": []}
        arq.enqueue_job.assert_not_awaited()

    async def test_enqueue_failure_degrades_gracefully(self) -> None:
        # Redis/arq down: the rows are still found and reported, the call
        # does NOT raise, and ``enqueued`` is False so the UI can fall
        # back to "next cron tick" messaging.
        posts = [_post()]
        svc = _service_with_missed(posts)

        with patch(
            "drevalis.core.redis.get_arq_pool",
            side_effect=RuntimeError("arq pool not initialised"),
        ):
            out = await svc.publish_missed_now()

        assert out["queued"] == 1
        assert out["enqueued"] is False
