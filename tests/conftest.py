"""Shared pytest fixtures for the Drevalis test suite."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── SQLite compatibility for PostgreSQL-specific types ────────────────────────
# Register compile-time adapters so that JSONB and UUID columns render as
# plain JSON / CHAR(32) when targeting SQLite.
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import JSON

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_redis, get_settings
from drevalis.main import create_app


@compiles(JSONB, "sqlite")
def _jsonb_to_json(element, compiler, **kw):
    return compiler.visit_JSON(JSON(), **kw)


@compiles(UUID, "sqlite")
def _uuid_to_char(element, compiler, **kw):
    return "TEXT"


@compiles(ARRAY, "sqlite")
def _array_to_json(element, compiler, **kw):
    # SQLite has no ARRAY; serialize as JSON for round-trip in tests.
    return compiler.visit_JSON(JSON(), **kw)


# Override UUID type processing for SQLite so that string <-> uuid.UUID
# round-trips work correctly.  PostgreSQL UUID returns a native UUID;
# SQLite returns a plain string from gen_random_uuid().
import uuid as _uuid_mod

_original_uuid_result_processor = UUID.result_processor


def _patched_uuid_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":

        def process(value):
            if value is None:
                return None
            if isinstance(value, _uuid_mod.UUID):
                return value
            return _uuid_mod.UUID(str(value))

        return process
    return _original_uuid_result_processor(self, dialect, coltype)


UUID.result_processor = _patched_uuid_result_processor

_original_uuid_bind_processor = UUID.bind_processor


def _patched_uuid_bind_processor(self, dialect):
    if dialect.name == "sqlite":

        def process(value):
            if value is None:
                return None
            if isinstance(value, _uuid_mod.UUID):
                return str(value)
            return str(value)

        return process
    return _original_uuid_bind_processor(self, dialect)


UUID.bind_processor = _patched_uuid_bind_processor
from drevalis.schemas.comfyui import NodeInput, WorkflowInputMapping
from drevalis.schemas.script import EpisodeScript, SceneScript
from drevalis.services.ffmpeg import FFmpegService
from drevalis.services.storage import LocalStorage

# ── Test Fernet key (deterministic, never used in production) ─────────────────
_TEST_FERNET_KEY: str = Fernet.generate_key().decode()


# ── Settings ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Return a Settings instance configured for testing.

    Uses an in-process SQLite database (async via aiosqlite) so tests
    do not require a running PostgreSQL instance.  Override this fixture
    if you want integration tests against a real database.
    """
    return Settings(
        debug=True,
        database_url="sqlite+aiosqlite:///./test.db",
        redis_url="redis://localhost:6379/1",
        encryption_key=_TEST_FERNET_KEY,
        storage_base_path="./test_storage",
    )


# ── Database ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def db_session(test_settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session backed by a temporary test database."""
    import datetime
    import uuid as _uuid

    engine = create_async_engine(test_settings.database_url, echo=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _register_sqlite_functions(dbapi_conn, connection_record):
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(datetime.UTC).isoformat()
        )
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))

    # Import Base so that ``metadata.create_all`` picks up all models
    from drevalis.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# ── Redis (mocked by default) ────────────────────────────────────────────────


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Return a mock Redis client for unit tests that don't need a real Redis."""
    mock = AsyncMock()
    mock.get.return_value = None
    mock.set.return_value = True
    mock.delete.return_value = 1
    mock.ping.return_value = True
    mock.publish.return_value = 1
    return mock


# ── HTTP Client ───────────────────────────────────────────────────────────────


@pytest.fixture
async def client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    """Yield an ``httpx.AsyncClient`` wired to the test FastAPI app.

    The app's settings dependency is overridden with ``test_settings`` so that
    no external services are required.
    """
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: test_settings

    # Create a single engine + session factory for the lifetime of this fixture.
    engine = create_async_engine(test_settings.database_url, echo=False)

    # Register PostgreSQL-compatible functions for SQLite.
    import datetime
    import uuid as _uuid

    @event.listens_for(engine.sync_engine, "connect")
    def _register_sqlite_functions(dbapi_conn, connection_record):
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(datetime.UTC).isoformat()
        )
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(_uuid.uuid4()))

    from drevalis.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # Override the get_db dependency (used by all API routes)
    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_db] = _override_db

    # Override the get_redis dependency with a mock
    mock_redis_client = AsyncMock()
    mock_redis_client.publish.return_value = 1
    mock_redis_client.enqueue_job = AsyncMock(return_value=None)

    async def _override_redis():
        yield mock_redis_client

    application.dependency_overrides[get_redis] = _override_redis

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Storage fixture ───────────────────────────────────────────────────────────


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    """Return a LocalStorage backed by a temporary directory."""
    return LocalStorage(base_path=tmp_path)


# ── FFmpeg service fixture ────────────────────────────────────────────────────


@pytest.fixture
def ffmpeg_service() -> FFmpegService:
    """Return an FFmpegService with default paths."""
    return FFmpegService()


# ── Mock LLM provider fixture ────────────────────────────────────────────────


@pytest.fixture
def mock_llm_provider() -> AsyncMock:
    """Return an AsyncMock satisfying the LLMProvider protocol."""
    provider = AsyncMock()
    provider.generate = AsyncMock()
    return provider


# ── Mock ComfyUI client fixture ──────────────────────────────────────────────


@pytest.fixture
def mock_comfyui_client() -> AsyncMock:
    """Return an AsyncMock satisfying the ComfyUIClient interface."""
    client = AsyncMock()
    client.base_url = "http://localhost:8188"
    client.queue_prompt = AsyncMock(return_value="test-prompt-id")
    client.get_history = AsyncMock(
        return_value={
            "outputs": {
                "9": {"images": [{"filename": "output.png", "subfolder": "", "type": "output"}]}
            }
        }
    )
    client.download_image = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    client.test_connection = AsyncMock(return_value=True)
    client.close = AsyncMock()
    return client


# ── Sample EpisodeScript fixture ──────────────────────────────────────────────


@pytest.fixture
def sample_episode_script() -> EpisodeScript:
    """Return a valid EpisodeScript instance for testing."""
    return EpisodeScript(
        title="Why Cats Ignore You",
        hook="Did you know your cat is secretly judging you?",
        scenes=[
            SceneScript(
                scene_number=1,
                narration="Every morning, your cat stares at you from across the room.",
                visual_prompt="close-up of a tabby cat staring intensely, cinematic lighting",
                duration_seconds=5.0,
            ),
            SceneScript(
                scene_number=2,
                narration="Scientists discovered that cats can recognize their owner's voice.",
                visual_prompt="cat sitting next to a scientist in a lab, dramatic atmosphere",
                duration_seconds=6.0,
            ),
            SceneScript(
                scene_number=3,
                narration="But they just choose not to respond. Classic cat behaviour.",
                visual_prompt="cat walking away from owner, comedic wide shot",
                duration_seconds=5.0,
            ),
        ],
        outro="Follow for more cat facts!",
        total_duration_seconds=16.0,
        language="en-US",
    )


# ── Sample WorkflowInputMapping fixture ───────────────────────────────────────


@pytest.fixture
def sample_workflow_mapping() -> WorkflowInputMapping:
    """Return a valid WorkflowInputMapping for testing."""
    return WorkflowInputMapping(
        mappings=[
            NodeInput(
                sf_field="visual_prompt",
                node_id="3",
                field_name="text",
                description="Positive prompt",
            ),
            NodeInput(
                sf_field="negative_prompt",
                node_id="7",
                field_name="text",
                description="Negative prompt",
            ),
            NodeInput(
                sf_field="seed",
                node_id="3",
                field_name="seed",
                description="Random seed",
            ),
            NodeInput(
                sf_field="width",
                node_id="5",
                field_name="width",
                description="Width",
            ),
            NodeInput(
                sf_field="height",
                node_id="5",
                field_name="height",
                description="Height",
            ),
        ],
        output_node_id="9",
        output_field_name="images",
    )


# ── Stale-test quarantine ───────────────────────────────────────────────
#
# These test cases were written against an earlier version of the codebase
# (pre-refactor to `_monolith.py` packages, pre-license-subsystem changes,
# etc.) and their mocks/imports no longer match the current structure.
#
# Rather than delete them — they still encode useful intent — we mark them
# as expected-failures so CI stays green while they're in quarantine.
# Each entry is tracked in TECHDEBT.md; fixing them one-by-one is a separate
# workstream.
#
# To un-quarantine a test: fix its body, then remove it from this list. If
# an xfailed test suddenly starts passing, pytest reports XPASS (loud
# enough to notice but non-blocking because strict=False).

_STALE_TESTS: frozenset[str] = frozenset(
    {
        # (Un-quarantined: replaced with test_pool_round_robin_selection
        # which exercises the actual selector + total_capacity helper.)
        # (Un-quarantined: tests now build an AudioMixConfig matching the
        # current _build_assembly_command signature instead of the legacy
        # music_volume_db float kwarg.)
        # (Un-quarantined: tests now pass after F-T-08 dropped the
        # storage param and tests were updated to patch decrypt_value
        # explicitly so the encrypted-vs-plain api_key flow is tested.)
        # (Un-quarantined: tests now patch metrics.record_* and pin
        # redis.get to None so the pipeline executes through the
        # _execute_step dispatcher to the patched _step_<name> handlers.)
        # (Un-quarantined: tests now patch repo imports at the source
        # module path that workers/jobs/* re-imports via in-function
        # imports, plus stub Settings to avoid ENCRYPTION_KEY env need.)
    }
)


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ARG001
    """Mark stale tests as xfail so CI stays honest without blocking."""
    marker = pytest.mark.xfail(
        reason="Quarantined — see tests/conftest.py _STALE_TESTS + TECHDEBT.md",
        strict=False,
    )
    for item in items:
        # ``item.nodeid`` uses '/' on POSIX and '\\' on Windows — normalize.
        normalized = item.nodeid.replace("\\", "/")
        if normalized in _STALE_TESTS:
            item.add_marker(marker)
