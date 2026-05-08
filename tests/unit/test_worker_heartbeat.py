"""Tests for the worker heartbeat job (workers/jobs/heartbeat.py).

The heartbeat is the sentinel for worker liveness — every minute it
writes ``worker:heartbeat`` to Redis with a 180s TTL. The TTL pad is
deliberate (one full beat margin over the API's 120s threshold) so a
single missed beat doesn't make the worker look dead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from drevalis.workers.jobs.heartbeat import worker_heartbeat

# ── Helpers ──────────────────────────────────────────────────────────


def _patched_redis_from_url(redis_mock: Any) -> Any:
    """Patch the ``Redis.from_url`` factory inside the heartbeat job."""
    return patch(
        "redis.asyncio.Redis.from_url",
        return_value=redis_mock,
    )


# ── worker_heartbeat ────────────────────────────────────────────────


class TestWorkerHeartbeat:
    async def test_writes_isoformat_timestamp_with_ttl(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.aclose = AsyncMock()

        with _patched_redis_from_url(redis):
            await worker_heartbeat({"redis_url": "redis://test:6379/0"})

        redis.set.assert_awaited_once()
        args, kwargs = redis.set.call_args
        # First arg is the key.
        assert args[0] == "worker:heartbeat"
        # Second arg is an ISO-8601 timestamp.
        ts = args[1]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is UTC
        # ex= TTL must exceed the API's 120s liveness threshold by one beat.
        assert kwargs["ex"] == 180

    async def test_uses_redis_url_from_ctx(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.aclose = AsyncMock()

        with patch("redis.asyncio.Redis.from_url", return_value=redis) as p:
            await worker_heartbeat({"redis_url": "redis://elsewhere:7000/3"})
        # The function honours the URL the arq context passes through —
        # operator-supplied REDIS_URL settings need to flow into the job.
        called_url = p.call_args.args[0]
        assert called_url == "redis://elsewhere:7000/3"

    async def test_falls_back_to_default_url_when_ctx_missing(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.aclose = AsyncMock()

        with patch("redis.asyncio.Redis.from_url", return_value=redis) as p:
            await worker_heartbeat({})  # no redis_url in ctx
        called_url = p.call_args.args[0]
        # Default mirrors the docker-compose service host; if this changes
        # the test should be updated together with the source.
        assert called_url == "redis://redis:6379/0"

    async def test_redis_connection_closed_after_set(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.aclose = AsyncMock()
        with _patched_redis_from_url(redis):
            await worker_heartbeat({})
        redis.aclose.assert_awaited_once()

    async def test_redis_closed_even_when_set_raises(self) -> None:
        # Defensive: a failure inside the try block must not leak the
        # connection. The finally clause guarantees aclose runs.
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=RuntimeError("redis hiccup"))
        redis.aclose = AsyncMock()

        with _patched_redis_from_url(redis):
            await worker_heartbeat({})
        redis.aclose.assert_awaited_once()

    async def test_outer_exception_swallowed(self, caplog: pytest.LogCaptureFixture) -> None:
        # When even ``Redis.from_url`` blows up, the heartbeat must NOT
        # propagate the exception — that would fail the arq job and mask
        # the actual cause. It logs a warning and returns.
        with patch("redis.asyncio.Redis.from_url", side_effect=ConnectionError("dns down")):
            await worker_heartbeat({})  # must not raise

    async def test_returns_none(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.aclose = AsyncMock()
        with _patched_redis_from_url(redis):
            result = await worker_heartbeat({})
        assert result is None
