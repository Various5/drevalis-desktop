"""Tests for the small remaining gaps:

* ``services/api_key_store.py``  — encrypted-credentials orchestration
* ``repositories/series.py``     — eager-loading + episode-count query
* ``core/license/quota.py`` last branch (redis.decr exception)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from drevalis.core.exceptions import NotFoundError
from drevalis.core.license import quota as _quota
from drevalis.core.license import state as _state
from drevalis.core.license.claims import LicenseClaims
from drevalis.core.license.state import LicenseState, LicenseStatus
from drevalis.repositories.series import SeriesRepository
from drevalis.services.api_key_store import ApiKeyStoreService

# ── api_key_store ─────────────────────────────────────────────────────


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode()


class TestApiKeyStoreService:
    async def test_list_delegates_to_repo(self, fernet_key: str) -> None:
        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[MagicMock(), MagicMock()])
        db = AsyncMock()
        with patch(
            "drevalis.services.api_key_store.ApiKeyStoreRepository",
            return_value=repo,
        ):
            svc = ApiKeyStoreService(db, fernet_key)
            out = await svc.list()
        assert len(out) == 2
        repo.get_all.assert_awaited_once()

    async def test_upsert_encrypts_value_with_key_version(self, fernet_key: str) -> None:
        repo = MagicMock()
        repo.upsert = AsyncMock()
        db = AsyncMock()
        db.commit = AsyncMock()
        with patch(
            "drevalis.services.api_key_store.ApiKeyStoreRepository",
            return_value=repo,
        ):
            svc = ApiKeyStoreService(db, fernet_key)
            await svc.upsert(key_name="elevenlabs", api_key="secret-xyz")

        repo.upsert.assert_awaited_once()
        kwargs = repo.upsert.call_args.kwargs
        assert kwargs["key_name"] == "elevenlabs"
        # Encrypted, never plaintext.
        assert kwargs["encrypted_value"] != "secret-xyz"
        assert kwargs["key_version"] is not None
        # Encryption is round-trippable with the same key.
        from drevalis.core.security import decrypt_value

        assert decrypt_value(kwargs["encrypted_value"], fernet_key) == "secret-xyz"
        # Commits after the upsert.
        db.commit.assert_awaited_once()

    async def test_upsert_with_rotated_keyring_tags_current_version(self, fernet_key: str) -> None:
        # Pin: when the service is constructed with a multi-version
        # keyring (operator has rotated), new writes get tagged with
        # the highest version, not the legacy ``1``. This is what lets
        # a background re-encryption sweep filter rows by
        # ``key_version < current_version`` to find stale rows.
        from cryptography.fernet import Fernet

        new_key = Fernet.generate_key().decode()
        repo = MagicMock()
        repo.upsert = AsyncMock()
        db = AsyncMock()
        db.commit = AsyncMock()

        with patch(
            "drevalis.services.api_key_store.ApiKeyStoreRepository",
            return_value=repo,
        ):
            svc = ApiKeyStoreService(
                db,
                new_key,  # the current ENCRYPTION_KEY post-rotation
                encryption_keys={1: fernet_key, 2: new_key},
            )
            await svc.upsert(key_name="elevenlabs", api_key="secret")

        kwargs = repo.upsert.call_args.kwargs
        assert kwargs["key_version"] == 2
        # Round-trip with the *current* key still works.
        from drevalis.core.security import decrypt_value

        assert decrypt_value(kwargs["encrypted_value"], new_key) == "secret"

    async def test_delete_when_present_commits(self, fernet_key: str) -> None:
        repo = MagicMock()
        repo.delete_by_key_name = AsyncMock(return_value=True)
        db = AsyncMock()
        db.commit = AsyncMock()
        with patch(
            "drevalis.services.api_key_store.ApiKeyStoreRepository",
            return_value=repo,
        ):
            svc = ApiKeyStoreService(db, fernet_key)
            await svc.delete("elevenlabs")
        repo.delete_by_key_name.assert_awaited_once_with("elevenlabs")
        db.commit.assert_awaited_once()

    async def test_delete_when_missing_raises_not_found(self, fernet_key: str) -> None:
        repo = MagicMock()
        repo.delete_by_key_name = AsyncMock(return_value=False)
        db = AsyncMock()
        db.commit = AsyncMock()
        with patch(
            "drevalis.services.api_key_store.ApiKeyStoreRepository",
            return_value=repo,
        ):
            svc = ApiKeyStoreService(db, fernet_key)
            with pytest.raises(NotFoundError):
                await svc.delete("ghost-key")
        # No commit when nothing to delete.
        db.commit.assert_not_awaited()

    async def test_list_stored_names_returns_set(self, fernet_key: str) -> None:
        e1 = MagicMock(key_name="elevenlabs")
        e2 = MagicMock(key_name="claude")
        # Duplicate to confirm set semantics.
        e3 = MagicMock(key_name="elevenlabs")
        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[e1, e2, e3])
        db = AsyncMock()
        with patch(
            "drevalis.services.api_key_store.ApiKeyStoreRepository",
            return_value=repo,
        ):
            svc = ApiKeyStoreService(db, fernet_key)
            out = await svc.list_stored_names()
        assert out == {"elevenlabs", "claude"}


# ── repositories/series.py ────────────────────────────────────────────


def _mock_session_returning(rows: list[Any]) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = rows
    result.scalars.return_value = scalars_proxy
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    result.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


def _last_compiled_sql(session: AsyncMock) -> str:
    stmt = session.execute.await_args.args[0]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


class TestSeriesRepository:
    async def test_get_with_relations_returns_row(self) -> None:
        row = MagicMock()
        session = _mock_session_returning([row])
        repo = SeriesRepository(session)
        sid = uuid4()
        out = await repo.get_with_relations(sid)
        assert out is row
        sql = _last_compiled_sql(session)
        assert (sid.hex in sql) or (str(sid) in sql)

    async def test_get_with_relations_none_when_missing(self) -> None:
        session = _mock_session_returning([])
        repo = SeriesRepository(session)
        assert await repo.get_with_relations(uuid4()) is None

    async def test_list_with_episode_counts_zips_into_tuples(self) -> None:
        # Each Row has positional access [0] = Series, [1] = count.
        s1 = MagicMock()
        s2 = MagicMock()
        # SQLAlchemy Row supports indexing.
        row1 = MagicMock()
        row1.__getitem__ = lambda _self, idx: (s1, 5)[idx]
        row2 = MagicMock()
        row2.__getitem__ = lambda _self, idx: (s2, 0)[idx]

        session = AsyncMock()
        result = MagicMock()
        result.all.return_value = [row1, row2]
        session.execute = AsyncMock(return_value=result)

        repo = SeriesRepository(session)
        out = await repo.list_with_episode_counts()
        assert out == [(s1, 5), (s2, 0)]

        sql = _last_compiled_sql(session)
        assert "GROUP BY" in sql
        assert "OUTER JOIN" in sql.upper() or "LEFT" in sql.upper()
        # Order by series name.
        order = sql.split("ORDER BY")[1].lower()
        assert "name" in order


# ── core/license/quota.py last branch ─────────────────────────────────


def _claims(tier: str = "creator") -> LicenseClaims:
    now = int(datetime.now(tz=UTC).timestamp())
    return LicenseClaims(
        iss="x",
        sub="x",
        jti="x",
        tier=tier,
        iat=now - 100,
        nbf=now - 100,
        exp=now + 86400,
        period_end=now + 86400,
    )


class TestQuotaDecrException:
    def setup_method(self) -> None:
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_claims()))

    async def test_decr_exception_swallowed_during_overshoot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # On overshoot, the rollback DECR is best-effort: a Redis blip
        # during DECR must NOT mask the 402 we're about to raise.
        monkeypatch.setattr(_quota, "TIER_DAILY_EPISODE_QUOTA", {"creator": 5})
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=6)  # over cap
        redis.decr = AsyncMock(side_effect=RuntimeError("redis hiccup"))
        with pytest.raises(HTTPException) as exc:
            await _quota.check_and_increment_episode_quota(redis)
        assert exc.value.status_code == 402
        # decr was attempted exactly once (best-effort cleanup).
        redis.decr.assert_awaited_once()
