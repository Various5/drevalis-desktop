"""Tests for license JWT verification + bootstrap (core/license/verifier.py).

This module decides every "is the license valid right now" question:
signature, audience pin (F-S-11 hotfix), legacy-tolerance for tokens
without ``aud``, key rotation across multiple public keys, and the
lifecycle classifier (UNACTIVATED → ACTIVE → GRACE → EXPIRED).
Misses ship as either silently-bypassed paywalls or false 402s.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from drevalis.core.license import verifier as _verifier
from drevalis.core.license.claims import LicenseClaims
from drevalis.core.license.state import LicenseStatus
from drevalis.core.license.verifier import (
    LicenseVerificationError,
    _classify,
    bump_state_version,
    get_remote_version,
    verify_jwt,
)

# ── Test keys + token forge helpers ─────────────────────────────────


def _make_keypair() -> tuple[Ed25519PrivateKey, str]:
    priv = Ed25519PrivateKey.generate()
    pub_pem = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return priv, pub_pem


def _priv_to_pem(priv: Ed25519PrivateKey) -> bytes:
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _make_token(
    priv: Ed25519PrivateKey,
    *,
    iss: str = "drevalis-license-server",
    aud: str | None = "drevalis-creator-studio",
    tier: str = "creator",
    now: datetime | None = None,
    period_offset_days: int = 23,
    exp_offset_days: int = 30,
    nbf_offset_seconds: int = -3600,
    extra: dict[str, Any] | None = None,
) -> str:
    n = now or datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "iss": iss,
        "sub": "user@example.com",
        "jti": "jti-test",
        "tier": tier,
        "iat": int(n.timestamp()) - 100,
        "nbf": int(n.timestamp()) + nbf_offset_seconds,
        "exp": int((n + timedelta(days=exp_offset_days)).timestamp()),
        "period_end": int((n + timedelta(days=period_offset_days)).timestamp()),
        "features": [],
    }
    if aud is not None:
        payload["aud"] = aud
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _priv_to_pem(priv), algorithm="EdDSA")


# ── verify_jwt ───────────────────────────────────────────────────────


class TestVerifyJwt:
    def test_valid_token_with_aud_decodes(self) -> None:
        priv, pub_pem = _make_keypair()
        token = _make_token(priv)
        claims = verify_jwt(token, public_key_override_pem=pub_pem)
        assert isinstance(claims, LicenseClaims)
        assert claims.tier == "creator"

    def test_legacy_token_without_aud_still_accepted(self) -> None:
        # F-S-11 hotfix: tokens minted before the audience pin must keep
        # working. Decoding skips audience check when ``aud`` is absent.
        priv, pub_pem = _make_keypair()
        token = _make_token(priv, aud=None)
        claims = verify_jwt(token, public_key_override_pem=pub_pem)
        assert claims.tier == "creator"

    def test_wrong_audience_rejected(self) -> None:
        priv, pub_pem = _make_keypair()
        token = _make_token(priv, aud="some-other-product")
        with pytest.raises(LicenseVerificationError):
            verify_jwt(token, public_key_override_pem=pub_pem)

    def test_wrong_issuer_rejected(self) -> None:
        priv, pub_pem = _make_keypair()
        token = _make_token(priv, iss="evil.example.com")
        with pytest.raises(LicenseVerificationError):
            verify_jwt(token, public_key_override_pem=pub_pem)

    def test_signature_with_wrong_key_rejected(self) -> None:
        priv_real, _ = _make_keypair()
        _, pub_pem_other = _make_keypair()
        token = _make_token(priv_real)
        with pytest.raises(LicenseVerificationError, match="signature"):
            verify_jwt(token, public_key_override_pem=pub_pem_other)

    def test_malformed_token_rejected(self) -> None:
        with pytest.raises(LicenseVerificationError, match="malformed"):
            verify_jwt("definitely-not-a-jwt", public_key_override_pem=None)

    def test_missing_required_claim_rejected(self) -> None:
        priv, pub_pem = _make_keypair()
        # Forge a token missing ``jti`` — the require list demands it.
        n = datetime.now(tz=UTC)
        payload = {
            "iss": "drevalis-license-server",
            "sub": "x",
            "tier": "creator",
            "iat": int(n.timestamp()) - 100,
            "nbf": int(n.timestamp()) - 100,
            "exp": int((n + timedelta(days=10)).timestamp()),
            "period_end": int((n + timedelta(days=5)).timestamp()),
            "aud": "drevalis-creator-studio",
        }
        token = jwt.encode(payload, _priv_to_pem(priv), algorithm="EdDSA")
        with pytest.raises(LicenseVerificationError):
            verify_jwt(token, public_key_override_pem=pub_pem)

    def test_expired_token_rejected_at_decode(self) -> None:
        priv, pub_pem = _make_keypair()
        # exp 1 hour in the past.
        token = _make_token(priv, exp_offset_days=-1, period_offset_days=-2)
        with pytest.raises(LicenseVerificationError):
            verify_jwt(token, public_key_override_pem=pub_pem)


# ── _classify ────────────────────────────────────────────────────────


def _claims_for_classify(
    *,
    nbf_offset: int = -100,
    period_offset: int = 86400,
    exp_offset: int = 86400 * 30,
    license_type: str = "subscription",
) -> LicenseClaims:
    now = int(datetime.now(tz=UTC).timestamp())
    return LicenseClaims(
        iss="x",
        sub="x",
        jti="x",
        tier="creator",
        iat=now - 100,
        nbf=now + nbf_offset,
        exp=now + exp_offset,
        period_end=now + period_offset,
        license_type=license_type,
    )


class TestClassify:
    def test_active_when_inside_paid_window(self) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        c = _claims_for_classify(period_offset=86400, exp_offset=86400 * 8)
        assert _classify(c, now_unix=now) == LicenseStatus.ACTIVE

    def test_grace_when_past_period_end_but_before_exp(self) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        c = _claims_for_classify(period_offset=-100, exp_offset=86400 * 7)
        assert _classify(c, now_unix=now) == LicenseStatus.GRACE

    def test_expired_when_past_exp(self) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        c = _claims_for_classify(period_offset=-86400 * 8, exp_offset=-100)
        assert _classify(c, now_unix=now) == LicenseStatus.EXPIRED

    def test_invalid_when_before_nbf(self) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        c = _claims_for_classify(nbf_offset=3600)  # nbf 1h in the future
        assert _classify(c, now_unix=now) == LicenseStatus.INVALID

    def test_lifetime_skips_period_end_check(self) -> None:
        # A lifetime license is ACTIVE even if ``period_end`` already
        # passed — there's no "paid through" date for lifetime tokens.
        now = int(datetime.now(tz=UTC).timestamp())
        c = _claims_for_classify(
            period_offset=-86400 * 365,
            exp_offset=86400 * 365 * 50,
            license_type="lifetime_pro",
        )
        assert _classify(c, now_unix=now) == LicenseStatus.ACTIVE

    def test_lifetime_still_invalid_before_nbf(self) -> None:
        # Defensive: nbf is still respected for lifetime licenses.
        now = int(datetime.now(tz=UTC).timestamp())
        c = _claims_for_classify(nbf_offset=3600, license_type="lifetime_pro")
        assert _classify(c, now_unix=now) == LicenseStatus.INVALID


# ── bump_state_version / get_remote_version ─────────────────────────


class TestStateVersionRedis:
    async def test_bump_returns_new_value(self) -> None:
        redis = AsyncMock()
        redis.incr = AsyncMock(return_value=42)
        result = await bump_state_version(redis)
        assert result == 42
        redis.incr.assert_awaited_once_with(_verifier.REDIS_STATE_VERSION_KEY)

    async def test_bump_on_redis_error_returns_zero(self) -> None:
        redis = AsyncMock()
        redis.incr = AsyncMock(side_effect=RuntimeError("redis offline"))
        # Fail-safe: must not raise. Returning 0 keeps the in-process
        # version comparison sensible.
        assert await bump_state_version(redis) == 0

    async def test_get_remote_returns_int(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"7")
        assert await get_remote_version(redis) == 7

    async def test_get_remote_handles_string_response(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value="9")
        assert await get_remote_version(redis) == 9

    async def test_get_remote_returns_zero_on_missing_key(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        assert await get_remote_version(redis) == 0

    async def test_get_remote_returns_zero_on_redis_error(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=RuntimeError("offline"))
        assert await get_remote_version(redis) == 0


# ── refresh_if_stale ─────────────────────────────────────────────────


class TestRefreshIfStale:
    async def test_no_refresh_when_local_at_or_above_remote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from drevalis.core.license import state as _state

        _state.set_local_version(5)

        called = False

        async def _spy(*args: Any, **kwargs: Any) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(_verifier, "bootstrap_license_state", _spy)

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"3")  # remote behind local
        await _verifier.refresh_if_stale(AsyncMock(), redis)
        assert called is False

    async def test_refresh_when_remote_ahead(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from drevalis.core.license import state as _state

        _state.set_local_version(2)

        called_with: list[Any] = []

        async def _spy(session_factory: Any, **kwargs: Any) -> None:
            called_with.append((session_factory, kwargs))

        monkeypatch.setattr(_verifier, "bootstrap_license_state", _spy)

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"9")
        await _verifier.refresh_if_stale(AsyncMock(), redis)
        assert len(called_with) == 1
        # Local version updated to remote value after successful refresh.
        assert _state.get_local_version() == 9

    async def test_refresh_swallows_bootstrap_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from drevalis.core.license import state as _state

        _state.set_local_version(0)

        async def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("DB lost")

        monkeypatch.setattr(_verifier, "bootstrap_license_state", _boom)

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")
        # Must not raise — the gate middleware must keep serving traffic
        # even when the license-state refresh path is broken.
        await _verifier.refresh_if_stale(AsyncMock(), redis)
        # And local version is NOT bumped on failure (so we'll retry next request).
        assert _state.get_local_version() == 0
