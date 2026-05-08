"""Tests for the singleton license-state repository
(repositories/license_state.py).

The stored JWT is end-user-facing — it's the literal license key.
This module owns:
  * Fernet at-rest encryption + key-version metadata
  * legacy-plaintext row compatibility (re-encrypted on next write)
  * upsert / clear / record_heartbeat singleton-row semantics

Misses ship as either licenses that fail to decrypt after a deploy,
or plaintext keys leaking into DB backups.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from drevalis.repositories.license_state import (
    LicenseStateRepository,
    _decrypt_stored_jwt,
)

# ── Helpers ──────────────────────────────────────────────────────────


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode()


def _row(
    *,
    jwt: str | None = None,
    jwt_key_version: int | None = None,
    machine_id: str | None = "m1",
    activated_at: datetime | None = None,
    updated_at: datetime | None = None,
    last_heartbeat_at: datetime | None = None,
    last_heartbeat_status: str | None = None,
) -> Any:
    """Build a stub LicenseStateRow whose attributes are mutable."""

    class _R:
        pass

    r = _R()
    r.jwt = jwt
    r.jwt_key_version = jwt_key_version
    r.machine_id = machine_id
    r.activated_at = activated_at
    r.updated_at = updated_at
    r.last_heartbeat_at = last_heartbeat_at
    r.last_heartbeat_status = last_heartbeat_status
    return r


def _session_with(row: Any | None) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


# ── _decrypt_stored_jwt ─────────────────────────────────────────────


class TestDecryptStoredJwt:
    def test_no_jwt_returns_none(self) -> None:
        assert _decrypt_stored_jwt(_row(jwt=None)) is None
        assert _decrypt_stored_jwt(_row(jwt="")) is None

    def test_legacy_plaintext_returned_as_is(self) -> None:
        # Pre-encryption rows have ``jwt_key_version=None`` — return the
        # value unchanged (the next write upgrades it).
        row = _row(jwt="raw.legacy.jwt", jwt_key_version=None)
        assert _decrypt_stored_jwt(row) == "raw.legacy.jwt"

    def test_encrypted_value_decrypted(self, fernet_key: str) -> None:
        from drevalis.core.security import encrypt_value

        ciphertext, version = encrypt_value("real.jwt.token", fernet_key)
        row = _row(jwt=ciphertext, jwt_key_version=version)

        with patch("drevalis.repositories.license_state.Settings") as settings_cls:
            from drevalis.core.security import decrypt_value as _decrypt

            settings_cls.return_value.encryption_key = fernet_key
            settings_cls.return_value.decrypt.side_effect = lambda ct: _decrypt(ct, fernet_key)
            assert _decrypt_stored_jwt(row) == "real.jwt.token"

    def test_undecryptable_raises_value_error(self, fernet_key: str) -> None:
        # Encrypted with key A, decryption attempted with key B → must
        # raise a clear ValueError pointing the operator at key rotation.
        from drevalis.core.security import encrypt_value

        wrong_key = Fernet.generate_key().decode()
        ciphertext, _ = encrypt_value("token", fernet_key)
        row = _row(jwt=ciphertext, jwt_key_version=1)

        with patch("drevalis.repositories.license_state.Settings") as settings_cls:
            from cryptography.fernet import InvalidToken

            settings_cls.return_value.encryption_key = wrong_key
            settings_cls.return_value.decrypt.side_effect = InvalidToken()
            with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
                _decrypt_stored_jwt(row)


# ── get_plaintext_jwt ────────────────────────────────────────────────


class TestGetPlaintextJwt:
    async def test_returns_none_when_row_missing(self) -> None:
        session = _session_with(None)
        repo = LicenseStateRepository(session)
        assert await repo.get_plaintext_jwt() is None

    async def test_returns_legacy_plaintext_unchanged(self) -> None:
        session = _session_with(_row(jwt="legacy.jwt", jwt_key_version=None))
        repo = LicenseStateRepository(session)
        assert await repo.get_plaintext_jwt() == "legacy.jwt"

    async def test_decrypts_encrypted_jwt(self, fernet_key: str) -> None:
        from drevalis.core.security import encrypt_value

        ciphertext, ver = encrypt_value("a.b.c", fernet_key)
        session = _session_with(_row(jwt=ciphertext, jwt_key_version=ver))
        repo = LicenseStateRepository(session)
        with patch("drevalis.repositories.license_state.Settings") as settings_cls:
            from drevalis.core.security import decrypt_value as _decrypt

            settings_cls.return_value.encryption_key = fernet_key
            settings_cls.return_value.decrypt.side_effect = lambda ct: _decrypt(ct, fernet_key)
            assert await repo.get_plaintext_jwt() == "a.b.c"


# ── upsert ──────────────────────────────────────────────────────────


class TestUpsert:
    async def test_creates_new_row_when_missing(self, fernet_key: str) -> None:
        session = _session_with(None)
        repo = LicenseStateRepository(session)

        with patch("drevalis.repositories.license_state.Settings") as settings_cls:
            from drevalis.core.security import encrypt_value as _enc

            settings_cls.return_value.encryption_key = fernet_key
            settings_cls.return_value.encrypt.side_effect = lambda p: _enc(p, fernet_key)
            row = await repo.upsert(jwt="new.jwt", machine_id="machine-x")

        # Singleton id pinned.
        assert row.id == 1
        # JWT encrypted at rest, never plaintext.
        assert row.jwt != "new.jwt"
        assert row.jwt_key_version is not None
        # machine_id + timestamps populated.
        assert row.machine_id == "machine-x"
        assert row.activated_at is not None
        assert row.updated_at is not None
        # Row added to session.
        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()

    async def test_updates_existing_row_in_place(self, fernet_key: str) -> None:
        old_activated = datetime.now(tz=UTC) - timedelta(days=10)
        existing = _row(
            jwt="old.cipher",
            jwt_key_version=1,
            machine_id="old-m",
            activated_at=old_activated,
        )
        session = _session_with(existing)
        repo = LicenseStateRepository(session)

        with patch("drevalis.repositories.license_state.Settings") as settings_cls:
            from drevalis.core.security import encrypt_value as _enc

            settings_cls.return_value.encryption_key = fernet_key
            settings_cls.return_value.encrypt.side_effect = lambda p: _enc(p, fernet_key)
            row = await repo.upsert(jwt="new.jwt", machine_id="new-m")

        # Same row mutated in place — no .add() call.
        assert row is existing
        session.add.assert_not_called()
        # JWT replaced with fresh ciphertext.
        assert row.jwt != "old.cipher"
        assert row.jwt != "new.jwt"  # encrypted
        assert row.machine_id == "new-m"
        # activated_at preserved (we only set it once, on first activation).
        assert row.activated_at == old_activated
        session.flush.assert_awaited_once()

    async def test_existing_row_with_null_activated_at_gets_set(self, fernet_key: str) -> None:
        # Defensive: rows from before activated_at was tracked have
        # ``None`` here; upsert should backfill it on next write.
        existing = _row(jwt="old", jwt_key_version=1, activated_at=None)
        session = _session_with(existing)
        repo = LicenseStateRepository(session)
        with patch("drevalis.repositories.license_state.Settings") as settings_cls:
            from drevalis.core.security import encrypt_value as _enc

            settings_cls.return_value.encryption_key = fernet_key
            settings_cls.return_value.encrypt.side_effect = lambda p: _enc(p, fernet_key)
            row = await repo.upsert(jwt="new", machine_id="m")
        assert row.activated_at is not None

    async def test_jwt_encrypted_round_trip_decryptable(self, fernet_key: str) -> None:
        # End-to-end: upsert encrypts → get_plaintext_jwt decrypts back
        # to the same plaintext.
        from drevalis.core.security import decrypt_value

        session = _session_with(None)
        repo = LicenseStateRepository(session)
        with patch("drevalis.repositories.license_state.Settings") as settings_cls:
            from drevalis.core.security import encrypt_value as _enc

            settings_cls.return_value.encryption_key = fernet_key
            settings_cls.return_value.encrypt.side_effect = lambda p: _enc(p, fernet_key)
            row = await repo.upsert(jwt="round.trip.token", machine_id="m")
        # Decrypt ciphertext directly — round-trip succeeds.
        assert decrypt_value(row.jwt, fernet_key) == "round.trip.token"


# ── clear ───────────────────────────────────────────────────────────


class TestClear:
    async def test_clear_when_no_row_is_noop(self) -> None:
        session = _session_with(None)
        repo = LicenseStateRepository(session)
        await repo.clear()
        # No flush happens when there's no row.
        session.flush.assert_not_awaited()

    async def test_clear_zeros_jwt_fields_only(self) -> None:
        existing = _row(
            jwt="cipher",
            jwt_key_version=1,
            machine_id="m1",
            activated_at=datetime.now(tz=UTC) - timedelta(days=5),
            last_heartbeat_at=datetime.now(tz=UTC),
        )
        session = _session_with(existing)
        repo = LicenseStateRepository(session)
        await repo.clear()

        # JWT + key version zeroed.
        assert existing.jwt is None
        assert existing.jwt_key_version is None
        # machine_id + history NOT cleared (audit trail).
        assert existing.machine_id == "m1"
        assert existing.activated_at is not None
        assert existing.last_heartbeat_at is not None
        # updated_at refreshed.
        assert existing.updated_at is not None
        session.flush.assert_awaited_once()


# ── record_heartbeat ────────────────────────────────────────────────


class TestRecordHeartbeat:
    async def test_no_row_is_noop(self) -> None:
        session = _session_with(None)
        repo = LicenseStateRepository(session)
        await repo.record_heartbeat("ok")
        session.flush.assert_not_awaited()

    async def test_records_status_and_timestamp(self) -> None:
        existing = _row(jwt="cipher", jwt_key_version=1)
        session = _session_with(existing)
        repo = LicenseStateRepository(session)
        await repo.record_heartbeat("ok")
        assert existing.last_heartbeat_status == "ok"
        assert existing.last_heartbeat_at is not None
        # updated_at refreshed.
        assert existing.updated_at is not None
        session.flush.assert_awaited_once()

    async def test_records_revoked_status(self) -> None:
        existing = _row(jwt=None, jwt_key_version=None)
        session = _session_with(existing)
        repo = LicenseStateRepository(session)
        await repo.record_heartbeat("revoked:license_revoked")
        assert existing.last_heartbeat_status == "revoked:license_revoked"

    async def test_overwrites_previous_status(self) -> None:
        old_ts = datetime.now(tz=UTC) - timedelta(hours=1)
        existing = _row(
            last_heartbeat_at=old_ts,
            last_heartbeat_status="network_error",
        )
        session = _session_with(existing)
        repo = LicenseStateRepository(session)
        await repo.record_heartbeat("ok")
        assert existing.last_heartbeat_status == "ok"
        # Timestamp moved forward.
        assert existing.last_heartbeat_at > old_ts


# ── get ──────────────────────────────────────────────────────────────


class TestGet:
    async def test_get_returns_singleton_row(self) -> None:
        existing = _row(jwt="x", jwt_key_version=1)
        session = _session_with(existing)
        repo = LicenseStateRepository(session)
        out = await repo.get()
        assert out is existing

    async def test_get_returns_none_when_empty(self) -> None:
        session = _session_with(None)
        repo = LicenseStateRepository(session)
        assert await repo.get() is None
