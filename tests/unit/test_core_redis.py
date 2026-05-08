"""Tests for ``core/redis.py``.

Module-level singletons + DNS preflight + connection pool helpers.
Pin the contracts:

* ``_parse_redis_settings`` translates redis:// URLs to arq RedisSettings
* ``get_pool`` / ``get_arq_pool`` raise clear errors before init
* ``close_redis`` is no-op when uninitialised, closes both pools when set
* ``get_redis`` yields a client from the pool and closes it on cleanup
* DNS preflight retries until deadline; succeeds when host eventually reachable
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from drevalis.core import redis as _redis

# ── _parse_redis_settings ────────────────────────────────────────────


class TestParseRedisSettings:
    def test_full_url_parsed(self) -> None:
        s = _redis._parse_redis_settings("redis://:secret@redis-host:6380/3")
        assert s.host == "redis-host"
        assert s.port == 6380
        assert s.database == 3
        assert s.password == "secret"

    def test_minimal_url_uses_defaults(self) -> None:
        s = _redis._parse_redis_settings("redis://")
        assert s.host == "localhost"
        assert s.port == 6379
        assert s.database == 0
        assert s.password is None

    def test_database_path_normalised(self) -> None:
        # Bare ``redis://host`` (no /<db>) → database 0.
        s = _redis._parse_redis_settings("redis://h:6379")
        assert s.database == 0


# ── get_pool / get_arq_pool ─────────────────────────────────────────


class TestGetPool:
    def setup_method(self) -> None:
        _redis._pool = None  # noqa: SLF001
        _redis._arq_pool = None  # noqa: SLF001

    def test_get_pool_raises_when_uninitialised(self) -> None:
        with pytest.raises(RuntimeError, match="not initialised"):
            _redis.get_pool()

    def test_get_arq_pool_raises_when_uninitialised(self) -> None:
        with pytest.raises(RuntimeError, match="arq connection pool"):
            _redis.get_arq_pool()

    def test_get_pool_returns_set_singleton(self) -> None:
        fake = MagicMock()
        _redis._pool = fake  # noqa: SLF001
        try:
            assert _redis.get_pool() is fake
        finally:
            _redis._pool = None  # noqa: SLF001

    def test_get_arq_pool_returns_set_singleton(self) -> None:
        fake = MagicMock()
        _redis._arq_pool = fake  # noqa: SLF001
        try:
            assert _redis.get_arq_pool() is fake
        finally:
            _redis._arq_pool = None  # noqa: SLF001


# ── close_redis ─────────────────────────────────────────────────────


class TestCloseRedis:
    async def test_close_when_uninitialised_is_noop(self) -> None:
        _redis._pool = None  # noqa: SLF001
        _redis._arq_pool = None  # noqa: SLF001
        # Must not raise.
        await _redis.close_redis()

    async def test_close_disposes_both_pools_and_clears_singletons(
        self,
    ) -> None:
        pool = AsyncMock()
        pool.aclose = AsyncMock()
        arq = AsyncMock()
        arq.aclose = AsyncMock()
        _redis._pool = pool  # noqa: SLF001
        _redis._arq_pool = arq  # noqa: SLF001
        try:
            await _redis.close_redis()
        finally:
            _redis._pool = None  # noqa: SLF001
            _redis._arq_pool = None  # noqa: SLF001
        pool.aclose.assert_awaited_once()
        arq.aclose.assert_awaited_once()

    async def test_close_handles_arq_only(self) -> None:
        # Defensive: if init partially succeeded with only arq set,
        # close should still drop just that pool.
        arq = AsyncMock()
        arq.aclose = AsyncMock()
        _redis._pool = None  # noqa: SLF001
        _redis._arq_pool = arq  # noqa: SLF001
        try:
            await _redis.close_redis()
        finally:
            _redis._arq_pool = None  # noqa: SLF001
        arq.aclose.assert_awaited_once()


# ── get_redis (FastAPI dependency) ──────────────────────────────────


class TestGetRedis:
    async def test_yields_client_and_closes_on_cleanup(self) -> None:
        pool = MagicMock()
        client = AsyncMock()
        client.aclose = AsyncMock()
        _redis._pool = pool  # noqa: SLF001
        try:
            with patch("drevalis.core.redis.Redis", return_value=client):
                gen = _redis.get_redis()
                yielded = await gen.__anext__()
                assert yielded is client
                # Simulate normal cleanup (StopAsyncIteration).
                with pytest.raises(StopAsyncIteration):
                    await gen.__anext__()
            # aclose called in the finally block.
            client.aclose.assert_awaited_once()
        finally:
            _redis._pool = None  # noqa: SLF001


# ── _wait_for_redis_dns ─────────────────────────────────────────────


class TestWaitForRedisDns:
    async def test_succeeds_immediately_when_host_reachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Stub asyncio.open_connection to "succeed" — return mock
        # reader/writer pair. wait_for wraps it; we patch that too
        # so the timeout doesn't fire on the mock.
        async def _fake_open_connection(host: str, port: int) -> Any:
            reader = MagicMock()
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            return reader, writer

        async def _fake_wait_for(coro: Any, *, timeout: float) -> Any:
            return await coro

        monkeypatch.setattr(_redis.asyncio, "open_connection", _fake_open_connection)
        monkeypatch.setattr(_redis.asyncio, "wait_for", _fake_wait_for)

        # Must complete without raising.
        await _redis._wait_for_redis_dns("redis://localhost:6379/0")

    async def test_timeout_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Every connection attempt raises gaierror — preflight loops
        # until the deadline expires.
        import socket

        async def _always_fails(host: str, port: int) -> Any:
            raise socket.gaierror(-5, "DNS NX")

        async def _fake_wait_for(coro: Any, *, timeout: float) -> Any:
            return await coro

        # No-op asyncio.sleep so the test doesn't actually wait.
        async def _no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr(_redis.asyncio, "open_connection", _always_fails)
        monkeypatch.setattr(_redis.asyncio, "wait_for", _fake_wait_for)
        monkeypatch.setattr(_redis.asyncio, "sleep", _no_sleep)

        with pytest.raises(RuntimeError, match="not reachable"):
            await _redis._wait_for_redis_dns(
                "redis://nonexistent:6379/0",
                total_seconds=0.01,  # immediate deadline
                initial_delay=0.001,
                max_delay=0.001,
            )
