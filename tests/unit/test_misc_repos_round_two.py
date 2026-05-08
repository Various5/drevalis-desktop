"""Tests for the remaining mid-coverage repos (round 2):

* ``repositories/api_key_store.py`` — get_by_key_name, upsert,
  delete_by_key_name
* ``repositories/video_template.py`` — get_default, increment_usage,
  clear_default_flag
* ``repositories/asset.py`` — get_by_hash, get_by_ids, list_filtered;
  VideoIngestJobRepository.get_by_asset_id
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from drevalis.repositories.api_key_store import ApiKeyStoreRepository
from drevalis.repositories.asset import (
    AssetRepository,
    VideoIngestJobRepository,
)
from drevalis.repositories.video_template import VideoTemplateRepository


def _mock_session(rows: list[Any] | None = None) -> AsyncMock:
    rows = rows or []
    session = AsyncMock()
    result = MagicMock()
    proxy = MagicMock()
    proxy.all.return_value = rows
    result.scalars.return_value = proxy
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    session.execute = AsyncMock(return_value=result)
    return session


def _last_sql(session: AsyncMock) -> str:
    stmt = session.execute.await_args.args[0]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ── ApiKeyStoreRepository ───────────────────────────────────────────


class TestApiKeyStoreRepoExtras:
    async def test_get_by_key_name_filters_correctly(self) -> None:
        session = _mock_session()
        repo = ApiKeyStoreRepository(session)
        await repo.get_by_key_name("elevenlabs")
        sql = _last_sql(session)
        assert "key_name = 'elevenlabs'" in sql

    async def test_upsert_creates_new_when_missing(self) -> None:
        session = _mock_session([])
        repo = ApiKeyStoreRepository(session)
        # Patch base CRUD so we observe the create branch.
        new_row = MagicMock(id=uuid4())
        repo.create = AsyncMock(return_value=new_row)  # type: ignore[method-assign]
        repo.update = AsyncMock()  # type: ignore[method-assign]
        out = await repo.upsert(
            key_name="elevenlabs",
            encrypted_value="cipher",
            key_version=1,
        )
        assert out is new_row
        repo.create.assert_awaited_once()
        repo.update.assert_not_awaited()

    async def test_upsert_updates_when_existing(self) -> None:
        existing = MagicMock(id=uuid4())
        session = _mock_session([existing])
        repo = ApiKeyStoreRepository(session)
        updated = MagicMock(id=existing.id)
        repo.update = AsyncMock(return_value=updated)  # type: ignore[method-assign]
        repo.create = AsyncMock()  # type: ignore[method-assign]
        out = await repo.upsert(
            key_name="elevenlabs",
            encrypted_value="new-cipher",
            key_version=2,
        )
        assert out is updated
        repo.update.assert_awaited_once()
        repo.create.assert_not_awaited()

    async def test_delete_by_key_name_returns_false_when_missing(self) -> None:
        session = _mock_session([])
        repo = ApiKeyStoreRepository(session)
        repo.delete = AsyncMock()  # type: ignore[method-assign]
        out = await repo.delete_by_key_name("ghost")
        assert out is False
        repo.delete.assert_not_awaited()

    async def test_delete_by_key_name_returns_true_on_delete(self) -> None:
        existing = MagicMock(id=uuid4())
        session = _mock_session([existing])
        repo = ApiKeyStoreRepository(session)
        repo.delete = AsyncMock(return_value=True)  # type: ignore[method-assign]
        out = await repo.delete_by_key_name("elevenlabs")
        assert out is True
        repo.delete.assert_awaited_once_with(existing.id)


# ── VideoTemplateRepository ─────────────────────────────────────────


class TestVideoTemplateRepoExtras:
    async def test_get_default_filters_is_default_true_recent_first(self) -> None:
        session = _mock_session([MagicMock()])
        repo = VideoTemplateRepository(session)
        await repo.get_default()
        sql = _last_sql(session)
        assert "is_default" in sql
        assert "created_at DESC" in sql
        assert "LIMIT 1" in sql

    async def test_get_default_returns_none_when_no_default_set(self) -> None:
        session = _mock_session([])
        repo = VideoTemplateRepository(session)
        out = await repo.get_default()
        assert out is None

    async def test_increment_usage_uses_server_side_increment(self) -> None:
        session = _mock_session([MagicMock()])
        repo = VideoTemplateRepository(session)
        await repo.increment_usage(uuid4())
        sql = _last_sql(session)
        # times_used = times_used + 1 — server-side atomic increment to
        # avoid races on concurrent updates.
        assert "times_used" in sql
        # SQLAlchemy compiles the +1 as ``times_used + 1`` literally.
        assert "+ 1" in sql or "+1" in sql

    async def test_increment_usage_returns_none_for_missing_template(self) -> None:
        session = _mock_session([])
        repo = VideoTemplateRepository(session)
        out = await repo.increment_usage(uuid4())
        assert out is None

    async def test_clear_default_flag_runs_update(self) -> None:
        session = _mock_session()
        repo = VideoTemplateRepository(session)
        await repo.clear_default_flag()
        sql = _last_sql(session)
        # UPDATE ... SET is_default = false WHERE is_default = true
        assert "UPDATE" in sql
        assert "is_default" in sql


# ── AssetRepository ─────────────────────────────────────────────────


class TestAssetRepo:
    async def test_get_by_hash_filters_sha256(self) -> None:
        session = _mock_session([MagicMock()])
        repo = AssetRepository(session)
        sha = "a" * 64
        await repo.get_by_hash(sha)
        sql = _last_sql(session)
        assert "hash_sha256" in sql
        assert sha in sql

    async def test_get_by_ids_empty_returns_empty_dict_no_query(self) -> None:
        session = _mock_session()
        repo = AssetRepository(session)
        out = await repo.get_by_ids([])
        assert out == {}
        session.execute.assert_not_awaited()

    async def test_get_by_ids_returns_dict_keyed_by_id(self) -> None:
        a = MagicMock()
        a.id = uuid4()
        b = MagicMock()
        b.id = uuid4()
        session = _mock_session([a, b])
        repo = AssetRepository(session)
        out = await repo.get_by_ids([a.id, b.id])
        assert out == {a.id: a, b.id: b}

    async def test_list_filtered_no_filters_orders_recent_first(self) -> None:
        session = _mock_session([])
        repo = AssetRepository(session)
        await repo.list_filtered()
        sql = _last_sql(session)
        assert "WHERE" not in sql
        assert "created_at DESC" in sql
        assert "LIMIT 100" in sql

    async def test_list_filtered_kind_only(self) -> None:
        session = _mock_session([])
        repo = AssetRepository(session)
        await repo.list_filtered(kind="video")
        sql = _last_sql(session)
        assert "kind = 'video'" in sql

    async def test_list_filtered_search_uses_ilike(self) -> None:
        session = _mock_session([])
        repo = AssetRepository(session)
        await repo.list_filtered(search="lake")
        sql = _last_sql(session).lower()
        # ilike compiles to LOWER(...) LIKE on the dialect default.
        assert "ilike" in sql or "lower(" in sql
        assert "lake" in sql

    async def test_list_filtered_offset_and_limit_propagate(self) -> None:
        session = _mock_session([])
        repo = AssetRepository(session)
        await repo.list_filtered(offset=20, limit=5)
        sql = _last_sql(session)
        assert "OFFSET 20" in sql
        assert "LIMIT 5" in sql


# ── VideoIngestJobRepository ────────────────────────────────────────


class TestVideoIngestJobRepo:
    async def test_get_by_asset_id_filters(self) -> None:
        session = _mock_session([MagicMock()])
        repo = VideoIngestJobRepository(session)
        aid = uuid4()
        await repo.get_by_asset_id(aid)
        sql = _last_sql(session)
        assert "asset_id" in sql
        assert (aid.hex in sql) or (str(aid) in sql)

    async def test_get_by_asset_id_returns_none_when_missing(self) -> None:
        session = _mock_session([])
        repo = VideoIngestJobRepository(session)
        assert await repo.get_by_asset_id(uuid4()) is None
