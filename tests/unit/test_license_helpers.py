"""Tests for the small license helper modules.

Targets:
  * ``core/license/machine.py``  — ``stable_machine_id`` derivation
  * ``core/license/keys.py``     — public-key loading + override
  * ``core/license/state.py``    — process-wide state holder
  * ``core/license/claims.py``   — grace-window + lifetime helpers
  * ``core/license/quota.py``    — Redis-backed daily quota counter

All modules are pure (or only need an AsyncMock Redis), so the tests
require no fixtures and no external services.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException

from drevalis.core.license import (
    keys as _keys,
)
from drevalis.core.license import (
    machine as _machine,
)
from drevalis.core.license import (
    quota as _quota,
)
from drevalis.core.license import (
    state as _state,
)
from drevalis.core.license.claims import LicenseClaims
from drevalis.core.license.state import LicenseState, LicenseStatus

# ── stable_machine_id ────────────────────────────────────────────────


class TestStableMachineId:
    def test_returns_16_hex_chars(self) -> None:
        mid = _machine.stable_machine_id()
        assert len(mid) == 16
        assert all(c in "0123456789abcdef" for c in mid)

    def test_stable_across_calls(self) -> None:
        # The hostname + MAC don't change between two consecutive calls
        # in the same process, so the digest must match.
        assert _machine.stable_machine_id() == _machine.stable_machine_id()

    def test_changes_when_hostname_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_machine.socket, "gethostname", lambda: "host-a")
        a = _machine.stable_machine_id()
        monkeypatch.setattr(_machine.socket, "gethostname", lambda: "host-b")
        b = _machine.stable_machine_id()
        assert a != b

    def test_handles_hostname_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> str:
            raise OSError("dns down")

        monkeypatch.setattr(_machine.socket, "gethostname", _boom)
        # Must not raise — machine_id is best-effort.
        mid = _machine.stable_machine_id()
        assert len(mid) == 16

    def test_handles_uuid_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> int:
            raise RuntimeError("no NIC")

        monkeypatch.setattr(_machine._uuid, "getnode", _boom)
        mid = _machine.stable_machine_id()
        assert len(mid) == 16


# ── get_public_keys ──────────────────────────────────────────────────


def _make_test_pem() -> str:
    """Generate a fresh Ed25519 keypair and return its public-key PEM."""
    priv = Ed25519PrivateKey.generate()
    return (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


class TestGetPublicKeys:
    def test_default_returns_embedded_key(self) -> None:
        keys = _keys.get_public_keys()
        assert len(keys) >= 1

    def test_override_returns_only_override(self) -> None:
        override_pem = _make_test_pem()
        keys = _keys.get_public_keys(override_pem=override_pem)
        assert len(keys) == 1

    def test_override_distinct_from_default(self) -> None:
        override_pem = _make_test_pem()
        default = _keys.get_public_keys()[0]
        override = _keys.get_public_keys(override_pem=override_pem)[0]
        # Different PEMs → different verifier keys.
        assert default.public_bytes_raw() != override.public_bytes_raw()

    def test_invalid_override_raises(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — cryptography raises ValueError or TypeError
            _keys.get_public_keys(override_pem="not a pem")

    def test_non_ed25519_pem_raises(self) -> None:
        # An RSA key should be rejected by the type check inside _load_pem.
        from cryptography.hazmat.primitives.asymmetric import rsa

        rsa_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pub_pem = (
            rsa_priv.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        with pytest.raises(TypeError, match="Ed25519"):
            _keys.get_public_keys(override_pem=rsa_pub_pem)


# ── LicenseState ─────────────────────────────────────────────────────


def _make_claims(**overrides: Any) -> LicenseClaims:
    now = int(datetime.now(tz=UTC).timestamp())
    base: dict[str, Any] = {
        "iss": "drevalis-license",
        "sub": "user@example.com",
        "jti": "test-jti",
        "tier": "creator",
        "iat": now - 86400,
        "nbf": now - 86400,
        "exp": now + 86400 * 30,
        "period_end": now + 86400 * 23,
    }
    base.update(overrides)
    return LicenseClaims(**base)


class TestLicenseState:
    def setup_method(self) -> None:
        # Reset to default before each test so we don't leak state across tests.
        _state.set_state(LicenseState(status=LicenseStatus.UNACTIVATED))

    def test_default_status_is_unactivated(self) -> None:
        # set_state in setup writes UNACTIVATED.
        s = _state.get_state()
        assert s.status == LicenseStatus.UNACTIVATED
        assert s.claims is None

    def test_active_state_is_usable(self) -> None:
        active = LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims())
        assert active.is_usable is True

    def test_grace_state_is_usable(self) -> None:
        grace = LicenseState(status=LicenseStatus.GRACE, claims=_make_claims())
        assert grace.is_usable is True

    def test_expired_state_not_usable(self) -> None:
        expired = LicenseState(status=LicenseStatus.EXPIRED)
        assert expired.is_usable is False

    def test_invalid_state_not_usable(self) -> None:
        invalid = LicenseState(status=LicenseStatus.INVALID, error="bad sig")
        assert invalid.is_usable is False

    def test_set_state_marks_bootstrapped(self) -> None:
        # Reset bootstrapped flag — done implicitly here by fresh module
        # state in test isolation; we just confirm set_state flips it.
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims()))
        assert _state.is_bootstrapped() is True

    def test_local_version_round_trip(self) -> None:
        _state.set_local_version(7)
        assert _state.get_local_version() == 7


# ── LicenseClaims helpers ────────────────────────────────────────────


class TestLicenseClaimsHelpers:
    def test_is_lifetime_default_false(self) -> None:
        c = _make_claims()
        assert c.is_lifetime is False

    def test_is_lifetime_when_license_type_set(self) -> None:
        c = _make_claims(license_type="lifetime_pro")
        assert c.is_lifetime is True

    def test_exp_datetime_returns_utc(self) -> None:
        c = _make_claims()
        dt = c.exp_datetime()
        assert dt.tzinfo is UTC
        # Round-trip back through epoch.
        assert int(dt.timestamp()) == c.exp

    def test_period_end_datetime_returns_utc(self) -> None:
        c = _make_claims()
        dt = c.period_end_datetime()
        assert dt.tzinfo is UTC

    def test_is_in_grace_true_between_period_end_and_exp(self) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        c = _make_claims(period_end=now - 100, exp=now + 100)
        assert c.is_in_grace(now) is True

    def test_is_in_grace_false_before_period_end(self) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        c = _make_claims(period_end=now + 100, exp=now + 200)
        assert c.is_in_grace(now) is False

    def test_is_in_grace_false_after_exp(self) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        c = _make_claims(period_end=now - 200, exp=now - 100)
        assert c.is_in_grace(now) is False

    def test_extra_fields_ignored(self) -> None:
        # ConfigDict(extra="ignore") — server may add new claim fields and
        # we must not crash on them.
        now = int(datetime.now(tz=UTC).timestamp())
        c = LicenseClaims(
            iss="x",
            sub="x",
            jti="x",
            tier="creator",
            iat=now,
            nbf=now,
            exp=now + 100,
            period_end=now + 50,
            future_field="ignored",  # type: ignore[call-arg]
        )
        assert c.tier == "creator"


# ── quota.check_and_increment_episode_quota ──────────────────────────


class TestQuotaCheck:
    def setup_method(self) -> None:
        _state.set_state(LicenseState(status=LicenseStatus.UNACTIVATED))

    async def test_unactivated_raises_402(self) -> None:
        redis = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await _quota.check_and_increment_episode_quota(redis)
        assert exc.value.status_code == 402

    async def test_unlimited_tier_short_circuits_redis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Monkey-patch the cap table so creator tier reads as None (unlimited)
        # — works without depending on whatever the production map currently has.
        monkeypatch.setattr(
            _quota,
            "TIER_DAILY_EPISODE_QUOTA",
            {"creator": None},
        )
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims()))
        redis = AsyncMock()
        await _quota.check_and_increment_episode_quota(redis)
        # Unlimited tier never increments the Redis counter.
        redis.incr.assert_not_called()

    async def test_under_cap_increments_and_returns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_quota, "TIER_DAILY_EPISODE_QUOTA", {"creator": 10})
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims()))
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=3)
        await _quota.check_and_increment_episode_quota(redis)
        redis.incr.assert_awaited_once()

    async def test_first_increment_sets_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_quota, "TIER_DAILY_EPISODE_QUOTA", {"creator": 10})
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims()))
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=1)  # first ever bump → set TTL
        await _quota.check_and_increment_episode_quota(redis)
        redis.expire.assert_awaited_once()

    async def test_subsequent_increments_skip_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_quota, "TIER_DAILY_EPISODE_QUOTA", {"creator": 10})
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims()))
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=5)
        await _quota.check_and_increment_episode_quota(redis)
        redis.expire.assert_not_called()

    async def test_redis_error_fails_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Losing a quota check is preferable to blocking legitimate users
        # if Redis hiccups — the contract is fail-open.
        monkeypatch.setattr(_quota, "TIER_DAILY_EPISODE_QUOTA", {"creator": 10})
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims()))
        redis = AsyncMock()
        redis.incr = AsyncMock(side_effect=RuntimeError("redis down"))
        # Must not raise.
        await _quota.check_and_increment_episode_quota(redis)

    async def test_over_cap_raises_402_and_decrements(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_quota, "TIER_DAILY_EPISODE_QUOTA", {"creator": 5})
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims()))
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=6)  # over cap
        redis.decr = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await _quota.check_and_increment_episode_quota(redis)
        assert exc.value.status_code == 402
        # Rollback so repeated failing calls don't accumulate.
        redis.decr.assert_awaited_once()


class TestQuotaUsage:
    def setup_method(self) -> None:
        _state.set_state(LicenseState(status=LicenseStatus.UNACTIVATED))

    async def test_unusable_state_returns_zeros(self) -> None:
        redis = AsyncMock()
        result = await _quota.get_daily_episode_usage(redis)
        assert result == {"used": 0, "limit": 0}

    async def test_active_state_returns_used_and_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_quota, "TIER_DAILY_EPISODE_QUOTA", {"creator": 25})
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims()))
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"7")
        result = await _quota.get_daily_episode_usage(redis)
        assert result == {"used": 7, "limit": 25}

    async def test_redis_error_returns_zero_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_quota, "TIER_DAILY_EPISODE_QUOTA", {"creator": 25})
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_make_claims()))
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=RuntimeError("offline"))
        result = await _quota.get_daily_episode_usage(redis)
        assert result["used"] == 0


# Silence ``asyncio`` unused-import check when this file's pytest config
# already runs in asyncio mode.
_ = asyncio, timedelta
