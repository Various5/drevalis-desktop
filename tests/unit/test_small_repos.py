"""Tests for the small custom-query repositories.

These repos each add a single ``get_by_<filter>`` method on top of
``BaseRepository``. The methods are 4-5 lines but they're the actual
filter the API surfaces — drift between the column name and the
filter would silently match nothing or everything. Pin the SQL shape
by inspecting the statement passed to ``session.execute``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from drevalis.repositories.audiobook import AudiobookRepository
from drevalis.repositories.comfyui import (
    ComfyUIServerRepository,
    ComfyUIWorkflowRepository,
)
from drevalis.repositories.prompt_template import PromptTemplateRepository
from drevalis.repositories.video_edit_session import VideoEditSessionRepository
from drevalis.repositories.voice_profile import VoiceProfileRepository


def _mock_session_returning(rows: list[Any]) -> AsyncMock:
    """Mock an AsyncSession.execute that returns a result wrapping ``rows``."""
    session = AsyncMock()
    result = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = rows
    result.scalars.return_value = scalars_proxy
    # scalar_one_or_none is used by the video-edit-session repo
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    session.execute = AsyncMock(return_value=result)
    return session


def _last_compiled_sql(session: AsyncMock) -> str:
    """Stringify the SQL passed to the most recent execute() call."""
    stmt = session.execute.await_args.args[0]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ── AudiobookRepository.get_by_status ────────────────────────────────


class TestAudiobookRepository:
    async def test_get_by_status_filters_and_orders(self) -> None:
        rows = [MagicMock(), MagicMock()]
        session = _mock_session_returning(rows)
        repo = AudiobookRepository(session)

        out = await repo.get_by_status("done")
        assert out == rows
        sql = _last_compiled_sql(session)
        assert "WHERE" in sql
        assert "status = 'done'" in sql
        assert "ORDER BY" in sql
        # Order by created_at DESC.
        assert "created_at DESC" in sql

    async def test_get_by_status_empty(self) -> None:
        session = _mock_session_returning([])
        repo = AudiobookRepository(session)
        assert await repo.get_by_status("done") == []


# ── VoiceProfileRepository.get_by_provider ───────────────────────────


class TestVoiceProfileRepository:
    async def test_get_by_provider_filters(self) -> None:
        rows = [MagicMock()]
        session = _mock_session_returning(rows)
        repo = VoiceProfileRepository(session)

        await repo.get_by_provider("piper")
        sql = _last_compiled_sql(session)
        assert "provider = 'piper'" in sql
        assert "ORDER BY" in sql
        # Sorted by name column (alphabetical for the dropdown).
        order_clause = sql.split("ORDER BY")[1]
        assert "name" in order_clause

    async def test_get_by_provider_returns_list(self) -> None:
        session = _mock_session_returning([])
        repo = VoiceProfileRepository(session)
        result = await repo.get_by_provider("elevenlabs")
        assert isinstance(result, list)
        assert result == []


# ── PromptTemplateRepository.get_by_type ─────────────────────────────


class TestPromptTemplateRepository:
    async def test_get_by_type_filters(self) -> None:
        session = _mock_session_returning([])
        repo = PromptTemplateRepository(session)

        await repo.get_by_type("script")
        sql = _last_compiled_sql(session)
        assert "template_type = 'script'" in sql

    @pytest.mark.parametrize("kind", ["script", "visual", "hook", "hashtag"])
    async def test_each_documented_type_query_works(self, kind: str) -> None:
        # Pin the parametrized type values mentioned in the docstring;
        # if a future rename drops one, this will fail loudly.
        session = _mock_session_returning([])
        repo = PromptTemplateRepository(session)
        await repo.get_by_type(kind)
        sql = _last_compiled_sql(session)
        assert f"template_type = '{kind}'" in sql


# ── ComfyUIServerRepository ──────────────────────────────────────────


class TestComfyUIServerRepository:
    async def test_get_active_servers_filters_is_active_true(self) -> None:
        session = _mock_session_returning([])
        repo = ComfyUIServerRepository(session)

        await repo.get_active_servers()
        sql = _last_compiled_sql(session)
        # ``is_active.is_(True)`` compiles to ``IS true`` or ``= 1``
        # depending on dialect; the column name has to be present.
        assert "is_active" in sql
        # Sorted by display name.
        assert "ORDER BY" in sql

    async def test_update_test_status_calls_update_with_kwargs(self) -> None:
        # update_test_status is a thin wrapper that delegates to
        # BaseRepository.update — pin the kwarg shape.
        session = _mock_session_returning([])
        repo = ComfyUIServerRepository(session)

        # Patch the inherited update method so we can observe calls.
        update_mock = AsyncMock(return_value=MagicMock())
        repo.update = update_mock  # type: ignore[method-assign]

        sid = uuid4()
        ts = datetime.now(tz=UTC)
        await repo.update_test_status(sid, "ok", ts)
        update_mock.assert_awaited_once_with(
            sid,
            last_test_status="ok",
            last_tested_at=ts,
        )


# ── ComfyUIWorkflowRepository ────────────────────────────────────────


class TestComfyUIWorkflowRepository:
    async def test_repo_is_constructable_with_session(self) -> None:
        # The class only inherits BaseRepository — no custom methods.
        # A constructor smoke test ensures the BaseRepository CRUD
        # surface remains reachable.
        session = AsyncMock()
        repo = ComfyUIWorkflowRepository(session)
        # Inherited create / update / get_by_id / delete must exist.
        assert hasattr(repo, "create")
        assert hasattr(repo, "update")
        assert hasattr(repo, "get_by_id")
        assert hasattr(repo, "delete")


# ── VideoEditSessionRepository.get_by_episode ────────────────────────


class TestVideoEditSessionRepository:
    async def test_get_by_episode_filters_episode_id(self) -> None:
        row = MagicMock()
        session = _mock_session_returning([row])
        repo = VideoEditSessionRepository(session)

        eid = uuid4()
        out = await repo.get_by_episode(eid)
        assert out is row
        sql = _last_compiled_sql(session)
        assert "episode_id" in sql
        # SQLAlchemy compiles UUID literals without dashes in the
        # default dialect; match on the hex form.
        assert eid.hex in sql or str(eid) in sql

    async def test_get_by_episode_returns_none_when_missing(self) -> None:
        session = _mock_session_returning([])
        repo = VideoEditSessionRepository(session)
        assert await repo.get_by_episode(uuid4()) is None
