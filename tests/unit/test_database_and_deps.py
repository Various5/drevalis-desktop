"""Tests for ``core/database.py`` and ``core/deps.py``.

Both modules underpin every API call. Pin the contracts:

* ``init_db`` → ``get_session_factory`` round-trip
* ``get_session_factory`` raises a clear error before init
* ``get_db_session`` commits on clean yield, rollbacks on exception
* ``close_db`` is no-op when uninitialised, disposes engine when set
* ``is_demo_mode`` / ``require_not_demo`` honour the settings flag
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from drevalis.core import database as _db
from drevalis.core import deps as _deps
from drevalis.core.deps import is_demo_mode, require_not_demo


def _make_settings(*, demo_mode: bool = False) -> Any:
    s = MagicMock()
    s.database_url = "postgresql+asyncpg://x:y@localhost/test"
    s.db_pool_size = 5
    s.db_max_overflow = 10
    s.db_echo = False
    s.demo_mode = demo_mode
    return s


# ── core/database.py ────────────────────────────────────────────────


class TestGetSessionFactoryUninitialised:
    def setup_method(self) -> None:
        # Reset the module-level singletons so this test gets the
        # fresh "uninitialised" state even when other tests ran first.
        _db._engine = None  # noqa: SLF001
        _db._session_factory = None  # noqa: SLF001

    def test_raises_runtime_error_with_helpful_message(self) -> None:
        with pytest.raises(RuntimeError, match="not initialised"):
            _db.get_session_factory()


class TestInitDb:
    def setup_method(self) -> None:
        _db._engine = None  # noqa: SLF001
        _db._session_factory = None  # noqa: SLF001

    async def test_init_db_populates_engine_and_factory(self) -> None:
        # Don't actually connect to a database — just verify that
        # init_db wires up create_async_engine + async_sessionmaker
        # with the settings the caller passed.
        fake_engine = AsyncMock()
        fake_factory = MagicMock()
        with (
            patch(
                "drevalis.core.database.create_async_engine",
                return_value=fake_engine,
            ) as mock_engine,
            patch(
                "drevalis.core.database.async_sessionmaker",
                return_value=fake_factory,
            ),
        ):
            await _db.init_db(_make_settings())

        # Engine constructed with the settings values.
        kwargs = mock_engine.call_args.kwargs
        assert kwargs["pool_size"] == 5
        assert kwargs["max_overflow"] == 10
        assert kwargs["echo"] is False
        # Module-level singletons populated.
        assert _db._engine is fake_engine  # noqa: SLF001
        assert _db._session_factory is fake_factory  # noqa: SLF001
        # get_session_factory now returns the populated factory.
        assert _db.get_session_factory() is fake_factory


class TestCloseDb:
    async def test_close_when_uninitialised_is_noop(self) -> None:
        _db._engine = None  # noqa: SLF001
        _db._session_factory = None  # noqa: SLF001
        # Must not raise.
        await _db.close_db()

    async def test_close_disposes_engine_and_clears_factory(self) -> None:
        engine = AsyncMock()
        engine.dispose = AsyncMock()
        _db._engine = engine  # noqa: SLF001
        _db._session_factory = MagicMock()  # noqa: SLF001
        await _db.close_db()
        engine.dispose.assert_awaited_once()
        # Both singletons cleared so a second call is a clean no-op.
        assert _db._engine is None  # noqa: SLF001
        assert _db._session_factory is None  # noqa: SLF001


class TestGetDbSession:
    async def test_commits_on_clean_yield(self) -> None:
        # Successful request flow: dependency yields session, route
        # handler does its work, dependency commits and closes.
        session = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        class _Factory:
            def __call__(self) -> Any:
                return self

            async def __aenter__(self) -> Any:
                return session

            async def __aexit__(self, *_a: Any) -> None:
                return None

        factory = _Factory()
        with patch.object(_db, "_session_factory", factory):
            async for s in _db.get_db_session():
                # Simulate a route handler doing nothing exceptional.
                assert s is session

        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    async def test_rollbacks_and_re_raises_on_exception(self) -> None:
        # Route handler raised → dependency must rollback then
        # propagate the exception so the route returns 500 and the
        # transaction doesn't silently swallow the partial write.
        # Use ``athrow`` (the explicit async-generator protocol) since
        # raising inside an ``async for`` body doesn't propagate into
        # the generator's except block.
        session = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        class _Factory:
            def __call__(self) -> Any:
                return self

            async def __aenter__(self) -> Any:
                return session

            async def __aexit__(self, *_a: Any) -> None:
                return None

        factory = _Factory()
        with patch.object(_db, "_session_factory", factory):
            gen = _db.get_db_session()
            yielded = await gen.__anext__()
            assert yielded is session
            with pytest.raises(RuntimeError, match="boom"):
                await gen.athrow(RuntimeError("boom"))

        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()


# ── core/deps.py: get_db / get_redis async-generator delegators ─────


class TestGetSettings:
    def test_returns_settings_singleton(self) -> None:
        # ``get_settings`` is the FastAPI dep that hands every request
        # the cached app config. Pin it returns *the same* Settings on
        # repeat calls — accidental cache loss would re-read .env on
        # every request and crater latency.
        from drevalis.core.config import Settings as _Settings
        from drevalis.core.deps import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert isinstance(s1, _Settings)
        assert s1 is s2


class TestGetDbDelegator:
    async def test_yields_session_from_get_db_session(self) -> None:
        # ``deps.get_db`` is a thin async-generator wrapper around
        # ``database.get_db_session``. Pin the delegation so a future
        # rewrite (e.g. caching the session) doesn't silently swallow
        # commit/rollback semantics from the underlying factory.
        session = MagicMock(name="session")

        async def _fake_get_db_session() -> Any:
            yield session

        with patch(
            "drevalis.core.deps.get_db_session",
            side_effect=lambda: _fake_get_db_session(),
        ):
            gen = _deps.get_db()
            yielded = await gen.__anext__()
            assert yielded is session
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()


class TestGetRedisDelegator:
    async def test_yields_client_from_core_redis(self) -> None:
        client = MagicMock(name="redis_client")

        async def _fake_get_redis() -> Any:
            yield client

        with patch(
            "drevalis.core.deps._get_redis",
            side_effect=lambda: _fake_get_redis(),
        ):
            gen = _deps.get_redis()
            yielded = await gen.__anext__()
            assert yielded is client
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()


# ── core/deps.py: demo-mode helpers ─────────────────────────────────


class TestIsDemoMode:
    def test_returns_false_when_settings_demo_off(self) -> None:
        assert is_demo_mode(_make_settings(demo_mode=False)) is False

    def test_returns_true_when_settings_demo_on(self) -> None:
        assert is_demo_mode(_make_settings(demo_mode=True)) is True

    def test_coerces_truthy_demo_value(self) -> None:
        # Defensive: settings.demo_mode might be set from env var as
        # a non-bool truthy value (string "1"). The helper coerces
        # via ``bool(...)`` so callers always get a proper bool.
        s = MagicMock()
        s.demo_mode = "true"
        assert is_demo_mode(s) is True
        s2 = MagicMock()
        s2.demo_mode = ""
        assert is_demo_mode(s2) is False


class TestRequireNotDemo:
    def test_passes_when_demo_off(self) -> None:
        # Should not raise.
        require_not_demo(_make_settings(demo_mode=False))

    def test_raises_403_when_demo_on(self) -> None:
        with pytest.raises(HTTPException) as exc:
            require_not_demo(_make_settings(demo_mode=True))
        assert exc.value.status_code == 403
        # Detail string is machine-readable so the frontend can route
        # to the "this is a demo install" banner instead of just
        # showing a generic 403.
        assert exc.value.detail == "disabled_in_demo"
