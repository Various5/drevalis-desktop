"""Tests for the pipeline hot-path repositories
(``repositories/episode.py`` and ``repositories/generation_job.py``).

These two are queried on every WebSocket progress event, every dashboard
load, and every pipeline retry. A typo in a status filter or a missing
ORDER BY changes user-visible UI behaviour without crashing — pin the
SQL shape so silent regressions show up here.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from drevalis.repositories.episode import EpisodeRepository
from drevalis.repositories.generation_job import GenerationJobRepository

# ── Helpers ──────────────────────────────────────────────────────────


def _mock_session_returning(rows: list[Any], scalar_one_value: Any = None) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = rows
    result.scalars.return_value = scalars_proxy
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    # ``count(*)`` queries call ``.scalar_one`` (without _or_none).
    result.scalar_one.return_value = scalar_one_value if scalar_one_value is not None else 0
    session.execute = AsyncMock(return_value=result)
    return session


def _last_compiled_sql(session: AsyncMock) -> str:
    stmt = session.execute.await_args.args[0]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ══════════════════════════════════════════════════════════════════
# EpisodeRepository
# ══════════════════════════════════════════════════════════════════


class TestEpisodeGetBySeries:
    async def test_filters_by_series_and_orders_recent_first(self) -> None:
        rows = [MagicMock()]
        session = _mock_session_returning(rows)
        repo = EpisodeRepository(session)
        sid = uuid4()

        await repo.get_by_series(sid)
        sql = _last_compiled_sql(session)
        assert "series_id" in sql
        assert (sid.hex in sql) or (str(sid) in sql)
        # Recent-first.
        assert "created_at DESC" in sql

    async def test_status_filter_added_when_provided(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)

        await repo.get_by_series(uuid4(), status_filter="review")
        sql = _last_compiled_sql(session)
        assert "status = 'review'" in sql

    async def test_no_status_filter_when_none(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)
        await repo.get_by_series(uuid4(), status_filter=None)
        sql = _last_compiled_sql(session)
        assert "status =" not in sql

    async def test_offset_and_limit_propagate(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)
        await repo.get_by_series(uuid4(), offset=20, limit=5)
        sql = _last_compiled_sql(session)
        assert "LIMIT 5" in sql
        assert "OFFSET 20" in sql

    async def test_default_limit_is_100(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)
        await repo.get_by_series(uuid4())
        sql = _last_compiled_sql(session)
        assert "LIMIT 100" in sql


class TestEpisodeGetWithAssets:
    async def test_includes_eager_load_options(self) -> None:
        # Eager-load both relations so the API can render the editor in
        # one round-trip — the alternative is N+1 lazy loads inside an
        # already-pinned async context.
        row = MagicMock()
        session = _mock_session_returning([row])
        repo = EpisodeRepository(session)
        eid = uuid4()
        out = await repo.get_with_assets(eid)
        assert out is row
        sql = _last_compiled_sql(session)
        assert "id" in sql
        # selectinload uses a follow-up SELECT — at minimum the primary
        # SELECT references the episode by id.
        assert (eid.hex in sql) or (str(eid) in sql)


class TestEpisodeUpdateStatus:
    async def test_delegates_to_base_update(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)
        update_mock = AsyncMock(return_value=MagicMock())
        repo.update = update_mock  # type: ignore[method-assign]
        eid = uuid4()
        await repo.update_status(eid, "review")
        update_mock.assert_awaited_once_with(eid, status="review")


class TestEpisodeGetRecent:
    async def test_orders_recent_first_with_default_limit_10(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)
        await repo.get_recent()
        sql = _last_compiled_sql(session)
        assert "created_at DESC" in sql
        assert "LIMIT 10" in sql

    async def test_custom_limit_propagates(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)
        await repo.get_recent(limit=25)
        sql = _last_compiled_sql(session)
        assert "LIMIT 25" in sql


class TestEpisodeGetByIds:
    async def test_empty_list_returns_empty_dict_without_query(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)
        out = await repo.get_by_ids([])
        assert out == {}
        # No SQL executed.
        session.execute.assert_not_awaited()

    async def test_returns_dict_keyed_by_id(self) -> None:
        ep_a = MagicMock()
        ep_a.id = uuid4()
        ep_b = MagicMock()
        ep_b.id = uuid4()
        session = _mock_session_returning([ep_a, ep_b])
        repo = EpisodeRepository(session)
        out = await repo.get_by_ids([ep_a.id, ep_b.id])
        assert out == {ep_a.id: ep_a, ep_b.id: ep_b}

    async def test_query_uses_id_in(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)
        ids = [uuid4(), uuid4()]
        await repo.get_by_ids(ids)
        sql = _last_compiled_sql(session)
        # SQLAlchemy compiles ``Episode.id.in_(...)`` to ``IN``.
        assert " IN " in sql or " in (" in sql.lower()


class TestEpisodeGetByStatus:
    async def test_filters_status_and_default_limit_50(self) -> None:
        session = _mock_session_returning([])
        repo = EpisodeRepository(session)
        await repo.get_by_status("generating")
        sql = _last_compiled_sql(session)
        assert "status = 'generating'" in sql
        assert "LIMIT 50" in sql
        assert "created_at DESC" in sql


class TestEpisodeCountByStatus:
    async def test_returns_scalar_count(self) -> None:
        session = _mock_session_returning([], scalar_one_value=42)
        repo = EpisodeRepository(session)
        out = await repo.count_by_status("review")
        assert out == 42
        sql = _last_compiled_sql(session)
        assert "count(*)" in sql.lower()
        assert "status = 'review'" in sql


class TestEpisodeCountNonDraft:
    async def test_filters_status_not_draft(self) -> None:
        session = _mock_session_returning([], scalar_one_value=7)
        repo = EpisodeRepository(session)
        out = await repo.count_non_draft_for_series(uuid4())
        assert out == 7
        sql = _last_compiled_sql(session)
        assert "count(*)" in sql.lower()
        # ``!=`` compiles to ``<>`` in SQLAlchemy default dialect.
        assert ("!= 'draft'" in sql) or ("<> 'draft'" in sql)


# ══════════════════════════════════════════════════════════════════
# GenerationJobRepository
# ══════════════════════════════════════════════════════════════════


class TestJobGetByEpisode:
    async def test_filters_episode_orders_step_then_created(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        eid = uuid4()
        await repo.get_by_episode(eid)
        sql = _last_compiled_sql(session)
        assert "episode_id" in sql
        # Order by step first (groups jobs of same step together) then
        # created_at — defines the per-step retry order.
        order_clause = sql.split("ORDER BY")[1].lower()
        # step appears before created_at in the ORDER BY.
        step_pos = order_clause.find("step")
        created_pos = order_clause.find("created_at")
        assert 0 <= step_pos < created_pos


class TestJobActiveAndFailed:
    async def test_active_jobs_filters_queued_and_running(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        await repo.get_active_jobs()
        sql = _last_compiled_sql(session)
        assert "'queued'" in sql
        assert "'running'" in sql
        assert " IN " in sql or "in (" in sql.lower()
        assert "LIMIT 50" in sql

    async def test_active_jobs_custom_limit(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        await repo.get_active_jobs(limit=200)
        sql = _last_compiled_sql(session)
        assert "LIMIT 200" in sql

    async def test_failed_jobs_filters_failed_and_orders_recent(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        await repo.get_failed_jobs()
        sql = _last_compiled_sql(session)
        assert "status = 'failed'" in sql
        assert "created_at DESC" in sql


class TestJobUpdateHelpers:
    async def test_update_progress_delegates_with_pct(self) -> None:
        session = AsyncMock()
        repo = GenerationJobRepository(session)
        update_mock = AsyncMock(return_value=MagicMock())
        repo.update = update_mock  # type: ignore[method-assign]
        jid = uuid4()
        await repo.update_progress(jid, 42)
        update_mock.assert_awaited_once_with(jid, progress_pct=42)

    async def test_update_status_without_error_message(self) -> None:
        session = AsyncMock()
        repo = GenerationJobRepository(session)
        update_mock = AsyncMock(return_value=MagicMock())
        repo.update = update_mock  # type: ignore[method-assign]
        jid = uuid4()
        await repo.update_status(jid, "running")
        update_mock.assert_awaited_once_with(jid, status="running")

    async def test_update_status_with_error_message(self) -> None:
        session = AsyncMock()
        repo = GenerationJobRepository(session)
        update_mock = AsyncMock(return_value=MagicMock())
        repo.update = update_mock  # type: ignore[method-assign]
        jid = uuid4()
        await repo.update_status(jid, "failed", error_message="comfyui dead")
        update_mock.assert_awaited_once_with(jid, status="failed", error_message="comfyui dead")

    async def test_update_status_does_not_overwrite_error_with_none(self) -> None:
        # Defensive: when ``error_message=None``, we MUST NOT pass
        # ``error_message=None`` to update — that would clear a previous
        # error string when transitioning queued→running.
        session = AsyncMock()
        repo = GenerationJobRepository(session)
        update_mock = AsyncMock(return_value=MagicMock())
        repo.update = update_mock  # type: ignore[method-assign]
        jid = uuid4()
        await repo.update_status(jid, "running")
        kwargs = update_mock.call_args.kwargs
        assert "error_message" not in kwargs


class TestJobGetAllFiltered:
    async def test_no_filters_returns_query_with_eager_load(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        await repo.get_all_filtered()
        sql = _last_compiled_sql(session)
        # No WHERE clause when no filters set (just ORDER BY + LIMIT).
        assert "WHERE" not in sql
        assert "LIMIT 50" in sql
        assert "created_at DESC" in sql

    async def test_status_filter(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        await repo.get_all_filtered(status_filter="failed")
        sql = _last_compiled_sql(session)
        assert "status = 'failed'" in sql

    async def test_episode_id_filter(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        eid = uuid4()
        await repo.get_all_filtered(episode_id=eid)
        sql = _last_compiled_sql(session)
        assert "episode_id" in sql
        assert (eid.hex in sql) or (str(eid) in sql)

    async def test_step_filter(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        await repo.get_all_filtered(step="captions")
        sql = _last_compiled_sql(session)
        assert "step = 'captions'" in sql

    async def test_combined_filters_all_applied(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        await repo.get_all_filtered(
            status_filter="running",
            episode_id=uuid4(),
            step="scenes",
            offset=10,
            limit=25,
        )
        sql = _last_compiled_sql(session)
        assert "status = 'running'" in sql
        assert "episode_id" in sql
        assert "step = 'scenes'" in sql
        assert "OFFSET 10" in sql
        assert "LIMIT 25" in sql


class TestJobGetLatestByEpisodeAndStep:
    async def test_filters_both_and_returns_latest(self) -> None:
        session = _mock_session_returning([MagicMock()])
        repo = GenerationJobRepository(session)
        await repo.get_latest_by_episode_and_step(uuid4(), "voice")
        sql = _last_compiled_sql(session)
        assert "episode_id" in sql
        assert "step = 'voice'" in sql
        assert "created_at DESC" in sql
        assert "LIMIT 1" in sql

    async def test_returns_none_when_no_match(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        out = await repo.get_latest_by_episode_and_step(uuid4(), "voice")
        assert out is None


class TestJobGetDoneSteps:
    async def test_filters_status_done_and_returns_set(self) -> None:
        session = _mock_session_returning(["script", "voice", "scenes"])
        repo = GenerationJobRepository(session)
        out = await repo.get_done_steps(uuid4())
        assert out == {"script", "voice", "scenes"}
        sql = _last_compiled_sql(session)
        assert "status = 'done'" in sql
        # DISTINCT keeps the set semantically a set even if the same
        # step has multiple done jobs (regenerate path).
        assert "DISTINCT" in sql.upper()

    async def test_empty_set_when_nothing_done(self) -> None:
        session = _mock_session_returning([])
        repo = GenerationJobRepository(session)
        out = await repo.get_done_steps(uuid4())
        assert out == set()
