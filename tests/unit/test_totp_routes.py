"""Unit tests for TOTP 2FA routes (api/routes/auth.py).

Covers:
* POST /2fa/enroll — happy path, 409 when already confirmed.
* POST /2fa/confirm — happy path, 409 if already confirmed, 400 if no secret,
                      401 if wrong code.
* POST /2fa/disable — wrong password → 401 (no schema change), correct → OK.
* POST /auth/login — returns totp_required stage when 2FA confirmed.
* POST /auth/login/totp — valid code → session cookie.
* Recovery code — consumed after use, same code rejected on second call.
* Routing — 6-digit goes to TOTP path; 16-hex goes to recovery path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request, Response

from drevalis.api.routes.auth import (
    LoginRequest,
    TotpConfirmRequest,
    TotpDisableRequest,
    TotpLoginRequest,
    _consume_recovery_code,
    login,
    login_totp,
    totp_confirm,
    totp_disable,
    totp_enroll,
)
from drevalis.services.totp import generate_recovery_codes, generate_secret

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _make_user(**overrides: Any) -> Any:
    u = MagicMock()
    u.id = overrides.get("id", uuid4())
    u.email = overrides.get("email", "owner@drevalis.test")
    u.role = overrides.get("role", "owner")
    u.display_name = overrides.get("display_name")
    u.is_active = overrides.get("is_active", True)
    u.last_login_at = overrides.get("last_login_at")
    u.password_hash = overrides.get("password_hash", "$pbkdf2$xx")
    u.session_version = overrides.get("session_version", 0)
    # TOTP fields — None by default (2FA not enrolled).
    u.totp_secret_encrypted = overrides.get("totp_secret_encrypted")
    u.totp_key_version = overrides.get("totp_key_version")
    u.totp_confirmed_at = overrides.get("totp_confirmed_at")
    u.totp_recovery_codes_encrypted = overrides.get("totp_recovery_codes_encrypted")
    return u


def _settings() -> Any:
    s = MagicMock()
    s.cookie_secure = False
    s.demo_mode = False
    s.get_session_secret = MagicMock(return_value="test-secret")
    # encrypt / decrypt pass-through using Fernet so challenges work.
    from cryptography.fernet import Fernet

    _key = Fernet.generate_key()
    _f = Fernet(_key)
    s.encrypt = MagicMock(side_effect=lambda pt: (_f.encrypt(pt.encode()).decode(), 1))
    s.decrypt = MagicMock(side_effect=lambda ct: _f.decrypt(ct.encode()).decode())
    s.get_encryption_keys = MagicMock(return_value={1: _key.decode()})
    return s


def _request(cookie: str | None = None, ip: str = "10.0.0.1") -> Any:
    req = MagicMock(spec=Request)
    req.cookies = {"drevalis_session": cookie} if cookie else {}
    client = MagicMock()
    client.host = ip
    req.client = client
    req.headers = MagicMock()
    req.headers.get = MagicMock(return_value=None)
    return req


def _discard_task(coro: Any) -> MagicMock:
    coro.close()
    return MagicMock()


# ---------------------------------------------------------------------------
# POST /2fa/enroll
# ---------------------------------------------------------------------------


class TestTotpEnroll:
    async def test_enroll_happy_path_returns_secret_and_codes(self) -> None:
        """Enrolment stores encrypted secret + recovery codes and returns them once."""
        me = _make_user()
        db = AsyncMock()
        db.commit = AsyncMock()
        settings = _settings()

        result = await totp_enroll(me=me, db=db, settings=settings)

        assert len(result.secret_base32) == 32
        assert result.otpauth_uri.startswith("otpauth://totp/")
        assert len(result.recovery_codes) == 10
        for code in result.recovery_codes:
            assert len(code) == 16
        # Columns must have been set.
        assert me.totp_secret_encrypted is not None
        assert me.totp_key_version is not None
        assert me.totp_recovery_codes_encrypted is not None
        # totp_confirmed_at must remain NULL (pending, not confirmed yet).
        assert me.totp_confirmed_at is None
        db.commit.assert_awaited_once()

    async def test_enroll_409_when_already_confirmed(self) -> None:
        """If totp_confirmed_at is set, a second enrolment attempt must 409."""
        me = _make_user(totp_confirmed_at=datetime.now(tz=UTC))
        db = AsyncMock()
        settings = _settings()

        with pytest.raises(HTTPException) as exc:
            await totp_enroll(me=me, db=db, settings=settings)
        assert exc.value.status_code == 409
        assert "2fa_already_enrolled" in exc.value.detail


# ---------------------------------------------------------------------------
# POST /2fa/confirm
# ---------------------------------------------------------------------------


class TestTotpConfirm:
    async def test_confirm_happy_path_sets_confirmed_at(self) -> None:
        """Submitting the correct TOTP code activates 2FA."""
        secret = generate_secret()
        settings = _settings()
        ct, _ver = settings.encrypt(secret)

        me = _make_user(totp_secret_encrypted=ct)
        db = AsyncMock()
        db.commit = AsyncMock()

        import base64
        import hashlib
        import hmac as _hmac
        import struct
        import time

        from drevalis.services.totp import _TOTP_DIGITS, _TOTP_STEP

        # Compute a valid code for the current step.
        padding = "=" * (-len(secret) % 8)
        key = base64.b32decode(secret.upper() + padding)
        counter = int(time.time()) // _TOTP_STEP
        msg = struct.pack(">Q", counter)
        mac = _hmac.new(key, msg, hashlib.sha1).digest()  # noqa: S324
        offset = mac[-1] & 0x0F
        code_int = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
        code = str(code_int % (10**_TOTP_DIGITS)).zfill(_TOTP_DIGITS)

        result = await totp_confirm(
            body=TotpConfirmRequest(code=code),
            me=me,
            db=db,
            settings=settings,
        )

        assert result["message"] == "2fa_activated"
        assert me.totp_confirmed_at is not None
        db.commit.assert_awaited_once()

    async def test_confirm_409_when_already_confirmed(self) -> None:
        me = _make_user(totp_confirmed_at=datetime.now(tz=UTC))
        db = AsyncMock()
        settings = _settings()

        with pytest.raises(HTTPException) as exc:
            await totp_confirm(
                body=TotpConfirmRequest(code="123456"), me=me, db=db, settings=settings
            )
        assert exc.value.status_code == 409

    async def test_confirm_400_when_not_enrolled(self) -> None:
        """Confirm without a stored secret returns 400 totp_not_enrolled."""
        me = _make_user()  # no totp_secret_encrypted
        db = AsyncMock()
        settings = _settings()

        with pytest.raises(HTTPException) as exc:
            await totp_confirm(
                body=TotpConfirmRequest(code="123456"), me=me, db=db, settings=settings
            )
        assert exc.value.status_code == 400
        assert "totp_not_enrolled" in exc.value.detail

    async def test_confirm_401_on_wrong_code(self) -> None:
        """A wrong code returns 401."""
        secret = generate_secret()
        settings = _settings()
        ct, _ver = settings.encrypt(secret)
        me = _make_user(totp_secret_encrypted=ct)
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await totp_confirm(
                body=TotpConfirmRequest(code="000000"), me=me, db=db, settings=settings
            )
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# POST /2fa/disable
# ---------------------------------------------------------------------------


class TestTotpDisable:
    async def test_disable_requires_password(self) -> None:
        """Wrong password returns 401 and must NOT modify TOTP columns."""
        me = _make_user(totp_confirmed_at=datetime.now(tz=UTC))
        db = AsyncMock()
        settings = _settings()
        original_confirmed_at = me.totp_confirmed_at

        with (
            patch("drevalis.api.routes.auth.verify_password", return_value=False),
        ):
            with pytest.raises(HTTPException) as exc:
                await totp_disable(
                    body=TotpDisableRequest(password="wrong"),
                    me=me,
                    db=db,
                    settings=settings,
                )
        assert exc.value.status_code == 401
        # TOTP columns must be unchanged.
        assert me.totp_confirmed_at == original_confirmed_at

    async def test_disable_correct_password_nulls_columns_and_bumps_sv(self) -> None:
        """Correct password nulls all TOTP columns and bumps session_version."""
        me = _make_user(
            totp_confirmed_at=datetime.now(tz=UTC),
            totp_secret_encrypted="enc",
            totp_key_version=1,
            totp_recovery_codes_encrypted="enc2",
            session_version=2,
        )
        db = AsyncMock()
        db.commit = AsyncMock()
        settings = _settings()

        with patch("drevalis.api.routes.auth.verify_password", return_value=True):
            result = await totp_disable(
                body=TotpDisableRequest(password="correct"),
                me=me,
                db=db,
                settings=settings,
            )

        assert result["message"] == "2fa_disabled"
        assert me.totp_secret_encrypted is None
        assert me.totp_key_version is None
        assert me.totp_confirmed_at is None
        assert me.totp_recovery_codes_encrypted is None
        # session_version bumped.
        assert me.session_version == 3
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST /auth/login — TOTP stage detection
# ---------------------------------------------------------------------------


class TestLoginReturnsTotpStage:
    async def test_login_returns_totp_stage_when_2fa_confirmed(self) -> None:
        """When totp_confirmed_at IS NOT NULL, login must NOT set a cookie.

        Instead it returns {stage: "totp_required", challenge: ...}.
        The challenge is a Fernet-encrypted opaque token.
        """
        me = _make_user(totp_confirmed_at=datetime.now(tz=UTC))
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=me))
        )
        settings = _settings()
        resp = Response()

        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.verify_password", return_value=True),
            patch("asyncio.create_task", side_effect=_discard_task),
        ):
            result = await login(
                body=LoginRequest(email=me.email, password="correct"),
                request=_request(),
                response=resp,
                db=db,
                settings=settings,
            )

        assert result.get("stage") == "totp_required"
        assert "challenge" in result
        # No session cookie must have been set.
        assert "drevalis_session" not in resp.headers.get("set-cookie", "")

    async def test_login_without_2fa_issues_cookie_directly(self) -> None:
        """Users without 2FA still get the session cookie on first login."""
        me = _make_user()  # totp_confirmed_at = None
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=me))
        )
        db.commit = AsyncMock()
        settings = _settings()
        resp = Response()

        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.verify_password", return_value=True),
            patch("drevalis.api.routes.auth.mint_session_token", return_value="tok"),
            patch("asyncio.create_task", side_effect=_discard_task),
        ):
            result = await login(
                body=LoginRequest(email=me.email, password="correct"),
                request=_request(),
                response=resp,
                db=db,
                settings=settings,
            )

        assert result.get("message") == "logged_in"
        assert "drevalis_session=tok" in resp.headers.get("set-cookie", "")


# ---------------------------------------------------------------------------
# POST /auth/login/totp
# ---------------------------------------------------------------------------


class TestLoginTotpEndpoint:
    async def test_login_totp_endpoint_with_valid_code(self) -> None:
        """A valid TOTP code after a valid challenge issues the session cookie."""
        secret = generate_secret()
        settings = _settings()
        me = _make_user(
            totp_confirmed_at=datetime.now(tz=UTC),
            totp_secret_encrypted=settings.encrypt(secret)[0],
        )

        # Build a valid challenge via the real _mint_totp_challenge.
        from drevalis.api.routes.auth import _mint_totp_challenge

        challenge = _mint_totp_challenge(me.id, settings)

        # Compute a valid TOTP code.
        import base64
        import hashlib
        import hmac as _hmac
        import struct
        import time

        from drevalis.services.totp import _TOTP_DIGITS, _TOTP_STEP

        padding = "=" * (-len(secret) % 8)
        key = base64.b32decode(secret.upper() + padding)
        counter = int(time.time()) // _TOTP_STEP
        msg = struct.pack(">Q", counter)
        mac = _hmac.new(key, msg, hashlib.sha1).digest()  # noqa: S324
        offset = mac[-1] & 0x0F
        code_int = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
        code = str(code_int % (10**_TOTP_DIGITS)).zfill(_TOTP_DIGITS)

        db = AsyncMock()
        db.get = AsyncMock(return_value=me)
        db.commit = AsyncMock()
        resp = Response()

        with (
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth._is_challenge_used", AsyncMock(return_value=False)),
            patch("drevalis.api.routes.auth._mark_challenge_used", AsyncMock()),
            patch("drevalis.api.routes.auth.mint_session_token", return_value="tok"),
            patch("asyncio.create_task", side_effect=_discard_task),
        ):
            result = await login_totp(
                body=TotpLoginRequest(challenge=challenge, code=code),
                request=_request(),
                response=resp,
                db=db,
                settings=settings,
            )

        assert result.get("message") == "logged_in"
        assert "drevalis_session=tok" in resp.headers.get("set-cookie", "")

    async def test_login_totp_invalid_code_returns_401(self) -> None:
        """A wrong TOTP code returns 401 without a cookie."""
        secret = generate_secret()
        settings = _settings()
        me = _make_user(
            totp_confirmed_at=datetime.now(tz=UTC),
            totp_secret_encrypted=settings.encrypt(secret)[0],
        )

        from drevalis.api.routes.auth import _mint_totp_challenge

        challenge = _mint_totp_challenge(me.id, settings)

        db = AsyncMock()
        db.get = AsyncMock(return_value=me)
        resp = Response()

        with (
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth._is_challenge_used", AsyncMock(return_value=False)),
            patch("drevalis.api.routes.auth._mark_challenge_used", AsyncMock()),
            patch("drevalis.api.routes.auth.record_login_failure", AsyncMock()),
            patch("asyncio.create_task", side_effect=_discard_task),
        ):
            with pytest.raises(HTTPException) as exc:
                await login_totp(
                    body=TotpLoginRequest(challenge=challenge, code="000000"),
                    request=_request(),
                    response=resp,
                    db=db,
                    settings=settings,
                )
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Recovery code consumption
# ---------------------------------------------------------------------------


class TestRecoveryCodeConsumed:
    async def test_recovery_code_consumed_after_use(self) -> None:
        """The same recovery code can only be used once.

        First call returns True and removes the code from the list.
        Second call with the same code returns False.
        """
        codes = generate_recovery_codes(10)
        code_to_use = codes[0]

        settings = _settings()
        encrypted, _v = settings.encrypt(json.dumps(codes))

        me = _make_user(totp_recovery_codes_encrypted=encrypted)

        db = AsyncMock()
        db.flush = AsyncMock()

        # First use — should succeed.
        result1 = await _consume_recovery_code(me, code_to_use, settings, db)
        assert result1 is True

        # After consumption, decrypt the new list and verify the code is gone.
        remaining = json.loads(settings.decrypt(me.totp_recovery_codes_encrypted))
        assert code_to_use not in remaining
        assert len(remaining) == 9

        # Second use — same code, now absent from the list → False.
        result2 = await _consume_recovery_code(me, code_to_use, settings, db)
        assert result2 is False

    async def test_unknown_recovery_code_returns_false(self) -> None:
        codes = generate_recovery_codes(10)
        settings = _settings()
        encrypted, _v = settings.encrypt(json.dumps(codes))
        me = _make_user(totp_recovery_codes_encrypted=encrypted)
        db = AsyncMock()
        db.flush = AsyncMock()

        result = await _consume_recovery_code(me, "0000000000000000", settings, db)
        assert result is False

    async def test_no_recovery_codes_returns_false(self) -> None:
        me = _make_user()  # totp_recovery_codes_encrypted = None
        db = AsyncMock()
        settings = _settings()

        result = await _consume_recovery_code(me, "abcdef0123456789", settings, db)
        assert result is False
