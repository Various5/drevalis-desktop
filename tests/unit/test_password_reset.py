"""Unit tests for the password-reset service and routes.

Tests
-----
Service layer (services/password_reset.py):
* test_request_reset_creates_token_and_sends_email
* test_request_reset_unknown_email_still_calls_send
* test_consume_reset_with_valid_token_sets_password_and_bumps_version
* test_consume_reset_with_used_token_returns_none
* test_consume_reset_with_expired_token_returns_none
* test_consume_reset_invalidates_sibling_tokens
* test_token_cap_3_per_user_oldest_rotated_out

Route layer (api/routes/auth.py):
* test_forgot_password_route_returns_same_response_for_known_and_unknown_emails
* test_forgot_password_rate_limited_per_ip
* test_reset_route_with_2fa_user_returns_totp_stage
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request, Response

from drevalis.models.password_reset_token import PasswordResetToken

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_user(**overrides: Any) -> Any:
    u = MagicMock()
    u.id = overrides.get("id", uuid4())
    u.email = overrides.get("email", "user@example.com")
    u.role = overrides.get("role", "owner")
    u.is_active = overrides.get("is_active", True)
    u.password_hash = overrides.get("password_hash", "hash")
    u.session_version = overrides.get("session_version", 0)
    u.totp_confirmed_at = overrides.get("totp_confirmed_at")
    return u


def _make_prt(
    user_id: Any,
    *,
    token_hash: str = "abc",
    used_at: datetime | None = None,
    expires_at: datetime | None = None,
    created_at: datetime | None = None,
) -> PasswordResetToken:
    now = datetime.now(tz=UTC)
    prt = PasswordResetToken()
    prt.id = uuid4()
    prt.user_id = user_id
    prt.token_hash = token_hash
    prt.created_at = created_at or now
    prt.expires_at = expires_at or (now + timedelta(hours=1))
    prt.used_at = used_at
    return prt


def _settings(**overrides: Any) -> Any:
    s = MagicMock()
    s.smtp_host = overrides.get("smtp_host", "smtp.example.com")
    s.smtp_port = overrides.get("smtp_port", 587)
    s.smtp_username = overrides.get("smtp_username", "from@example.com")
    s.smtp_password = overrides.get("smtp_password", "pw")
    s.smtp_use_tls = overrides.get("smtp_use_tls", True)
    s.smtp_from = overrides.get("smtp_from", "from@example.com")
    s.app_base_url = overrides.get("app_base_url", "https://drevalis.example.com")
    s.cookie_secure = False
    s.get_session_secret = MagicMock(return_value="secret")
    return s


def _request(ip: str = "10.0.0.1") -> Any:
    req = MagicMock(spec=Request)
    req.cookies = {}
    client = MagicMock()
    client.host = ip
    req.client = client
    req.headers = MagicMock()
    req.headers.get = MagicMock(return_value=None)
    return req


# ---------------------------------------------------------------------------
# Service: request_reset
# ---------------------------------------------------------------------------


class TestRequestReset:
    async def test_creates_token_and_sends_email(self) -> None:
        """Known, active user: token inserted + send_email called with real address."""
        from drevalis.services.password_reset import request_reset

        user = _make_user()
        db = AsyncMock()

        # Simulate no existing tokens (empty list).
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        execute_result.scalar_one_or_none.return_value = user
        db.execute = AsyncMock(return_value=execute_result)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        added: list[Any] = []
        db.add = MagicMock(side_effect=added.append)

        send_mock = AsyncMock(return_value=True)

        with (
            patch(
                "drevalis.services.password_reset._check_and_increment_rate",
                AsyncMock(return_value=True),
            ),
            patch("drevalis.services.password_reset.send_email", send_mock),
        ):
            await request_reset(db=db, email="user@example.com", settings=_settings())

        # A PasswordResetToken must have been added.
        assert any(isinstance(obj, PasswordResetToken) for obj in added)
        # send_email must have been called with the real (not discard) address.
        call_kwargs = send_mock.call_args.kwargs
        assert call_kwargs["to"] == "user@example.com"
        assert "reset-password?token=" in call_kwargs["html"]

    async def test_unknown_email_still_calls_send(self) -> None:
        """Unknown email: send_email still called (timing-uniform), discard address."""
        from drevalis.services.password_reset import request_reset

        db = AsyncMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None  # user not found
        db.execute = AsyncMock(return_value=execute_result)
        db.commit = AsyncMock()

        send_mock = AsyncMock(return_value=False)

        with (
            patch(
                "drevalis.services.password_reset._check_and_increment_rate",
                AsyncMock(return_value=True),
            ),
            patch("drevalis.services.password_reset.send_email", send_mock),
        ):
            await request_reset(db=db, email="ghost@example.com", settings=_settings())

        # send_email IS called — timing-uniform property.
        send_mock.assert_awaited_once()
        # Recipient is the discard address, not the queried email.
        call_kwargs = send_mock.call_args.kwargs
        assert "ghost@example.com" not in call_kwargs["to"]
        assert "discard" in call_kwargs["to"]

    async def test_rate_limited_email_silently_returns(self) -> None:
        """When rate limit exceeded, request_reset returns without calling send."""
        from drevalis.services.password_reset import request_reset

        db = AsyncMock()
        send_mock = AsyncMock()

        with (
            patch(
                "drevalis.services.password_reset._check_and_increment_rate",
                AsyncMock(return_value=False),
            ),
            patch("drevalis.services.password_reset.send_email", send_mock),
        ):
            await request_reset(db=db, email="user@example.com", settings=_settings())

        send_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Service: consume_reset
# ---------------------------------------------------------------------------


class TestConsumeReset:
    def _db_with_prt(self, prt: PasswordResetToken | None, user: Any) -> Any:
        """Build an AsyncMock DB that returns *prt* from a token lookup and *user* from db.get."""
        db = AsyncMock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = prt
        db.execute = AsyncMock(return_value=result_mock)
        db.get = AsyncMock(return_value=user)
        db.commit = AsyncMock()
        return db

    async def test_valid_token_sets_password_and_bumps_version(self) -> None:
        """Happy path: password changed, session_version incremented, user returned."""
        from drevalis.services.password_reset import _hash_token, consume_reset

        user = _make_user(session_version=2)
        raw = "validtokenABCDE12345678901234"
        prt = _make_prt(user.id, token_hash=_hash_token(raw))

        db = self._db_with_prt(prt, user)

        with patch("drevalis.services.password_reset.hash_password", return_value="newhash"):
            result = await consume_reset(
                db=db,
                raw_token=raw,
                new_password="newSecurePass",
                settings=_settings(),
            )

        assert result is user
        assert user.password_hash == "newhash"
        assert user.session_version == 3

    async def test_used_token_returns_none(self) -> None:
        """Token with used_at already set: consume_reset returns None."""
        from drevalis.services.password_reset import consume_reset

        db = AsyncMock()
        # scalar_one_or_none returns None because the query filters out used tokens.
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await consume_reset(
            db=db,
            raw_token="alreadyused",
            new_password="newSecurePass",
            settings=_settings(),
        )
        assert result is None

    async def test_expired_token_returns_none(self) -> None:
        """Expired token (expires_at in the past): consume_reset returns None."""
        from drevalis.services.password_reset import consume_reset

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await consume_reset(
            db=db,
            raw_token="expiredtoken",
            new_password="newSecurePass",
            settings=_settings(),
        )
        assert result is None

    async def test_marks_used_at_on_token(self) -> None:
        """Successful consume: used_at is set on the PasswordResetToken."""
        from drevalis.services.password_reset import _hash_token, consume_reset

        user = _make_user()
        raw = "markusedtoken12345678901234567"
        prt = _make_prt(user.id, token_hash=_hash_token(raw))

        db = self._db_with_prt(prt, user)

        with patch("drevalis.services.password_reset.hash_password", return_value="h"):
            await consume_reset(db=db, raw_token=raw, new_password="p4ssw0rd", settings=_settings())

        assert prt.used_at is not None

    async def test_invalidates_sibling_tokens(self) -> None:
        """Successful consume: UPDATE statement issued to invalidate siblings."""
        from drevalis.services.password_reset import _hash_token, consume_reset

        user = _make_user()
        raw = "siblingtoken12345678901234567"
        prt = _make_prt(user.id, token_hash=_hash_token(raw))

        db = self._db_with_prt(prt, user)

        update_calls: list[Any] = []
        original_execute = db.execute

        async def _capture_execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
            update_calls.append(stmt)
            return await original_execute(stmt, *args, **kwargs)

        db.execute = _capture_execute

        with patch("drevalis.services.password_reset.hash_password", return_value="h"):
            await consume_reset(db=db, raw_token=raw, new_password="p4ssw0rd", settings=_settings())

        # At least two DB calls: one SELECT (find prt) + one UPDATE (invalidate siblings).
        assert len(update_calls) >= 2


# ---------------------------------------------------------------------------
# Service: token cap
# ---------------------------------------------------------------------------


class TestTokenCap:
    async def test_token_cap_3_per_user_oldest_rotated_out(self) -> None:
        """When 3 active tokens exist, the oldest is deleted before inserting."""
        from drevalis.services.password_reset import request_reset

        user = _make_user()
        now = datetime.now(tz=UTC)

        old1 = _make_prt(user.id, token_hash="h1", created_at=now - timedelta(hours=2))
        old2 = _make_prt(user.id, token_hash="h2", created_at=now - timedelta(hours=1))
        old3 = _make_prt(user.id, token_hash="h3", created_at=now - timedelta(minutes=10))

        db = AsyncMock()
        # First execute call: user lookup → returns user.
        # Second execute call: existing tokens → returns [old1, old2, old3].
        execute_responses = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=user)),
            MagicMock(
                scalars=MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=[old1, old2, old3]))
                )
            ),
        ]
        db.execute = AsyncMock(side_effect=execute_responses)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        deleted: list[Any] = []
        db.delete = AsyncMock(side_effect=lambda obj: deleted.append(obj))
        added: list[Any] = []
        db.add = MagicMock(side_effect=added.append)

        with (
            patch(
                "drevalis.services.password_reset._check_and_increment_rate",
                AsyncMock(return_value=True),
            ),
            patch("drevalis.services.password_reset.send_email", AsyncMock(return_value=True)),
        ):
            await request_reset(db=db, email="user@example.com", settings=_settings())

        # The oldest token (old1) must have been deleted so the cap is not exceeded.
        assert old1 in deleted
        # A new PasswordResetToken was added.
        assert any(isinstance(obj, PasswordResetToken) for obj in added)


# ---------------------------------------------------------------------------
# Route: forgot_password
# ---------------------------------------------------------------------------


class TestForgotPasswordRoute:
    async def test_same_response_for_known_and_unknown_email(self) -> None:
        """Both known and unknown email paths return the same 200 body."""
        from drevalis.api.routes.auth import ForgotPasswordRequest, forgot_password

        settings = _settings()
        db = AsyncMock()
        rq = _request()
        request_reset_mock = AsyncMock()

        # The route imports request_reset inside the function body so we patch
        # it at the source module level — that is where the name is resolved.
        with (
            patch("drevalis.api.routes.auth._check_forgot_rate", AsyncMock(return_value=True)),
            patch("drevalis.services.password_reset.request_reset", request_reset_mock),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            result = await forgot_password(
                body=ForgotPasswordRequest(email="user@example.com"),
                request=rq,
                db=db,
                settings=settings,
            )

        assert result == {"message": "if your email is on file, a reset link has been sent"}

    async def test_rate_limited_ip_still_returns_200(self) -> None:
        """Per-IP rate-limit hit: same 200 generic response, no 429 to HTTP client."""
        from drevalis.api.routes.auth import ForgotPasswordRequest, forgot_password

        db = AsyncMock()
        rq = _request(ip="5.5.5.5")

        with (
            patch("drevalis.api.routes.auth._check_forgot_rate", AsyncMock(return_value=False)),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            result = await forgot_password(
                body=ForgotPasswordRequest(email="victim@example.com"),
                request=rq,
                db=db,
                settings=_settings(),
            )

        assert result == {"message": "if your email is on file, a reset link has been sent"}

    async def test_forgot_password_rate_limited_per_ip(self) -> None:
        """After rate limit is exceeded the route returns the same generic message.

        When the rate limit is hit the handler returns early, so request_reset
        (imported inside the handler) is never called.  We verify by patching
        it at the service module level and confirming it was not awaited.
        """
        from drevalis.api.routes.auth import ForgotPasswordRequest, forgot_password

        db = AsyncMock()
        request_reset_mock = AsyncMock()

        # Patch at service module so the in-function import sees the mock.
        with (
            patch("drevalis.api.routes.auth._check_forgot_rate", AsyncMock(return_value=False)),
            patch("drevalis.services.password_reset.request_reset", request_reset_mock),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            result = await forgot_password(
                body=ForgotPasswordRequest(email="flood@example.com"),
                request=_request(ip="1.2.3.4"),
                db=db,
                settings=_settings(),
            )

        # Rate-limited early-return: request_reset must NOT have been called.
        request_reset_mock.assert_not_awaited()
        # HTTP response is still the generic 200 body.
        assert "reset link" in result["message"]


# ---------------------------------------------------------------------------
# Route: reset_password
# ---------------------------------------------------------------------------


class TestResetPasswordRoute:
    async def test_invalid_token_returns_400(self) -> None:
        from drevalis.api.routes.auth import ResetPasswordRequest, reset_password

        db = AsyncMock()
        rq = _request()
        resp = Response()

        # consume_reset is imported inside the route handler body; patch at source.
        with (
            patch("drevalis.services.password_reset.consume_reset", AsyncMock(return_value=None)),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await reset_password(
                    body=ResetPasswordRequest(token="bad", new_password="newpass1"),
                    request=rq,
                    response=resp,
                    db=db,
                    settings=_settings(),
                )

        assert exc.value.status_code == 400
        assert exc.value.detail == "invalid_or_expired_token"

    async def test_success_no_2fa_returns_message(self) -> None:
        from drevalis.api.routes.auth import ResetPasswordRequest, reset_password

        user = _make_user(totp_confirmed_at=None)
        db = AsyncMock()
        rq = _request()
        resp = Response()

        with (
            patch("drevalis.services.password_reset.consume_reset", AsyncMock(return_value=user)),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            result = await reset_password(
                body=ResetPasswordRequest(token="goodtoken", new_password="newpass1"),
                request=rq,
                response=resp,
                db=db,
                settings=_settings(),
            )

        assert result == {"message": "password_reset_successful"}
        # Cookie must be cleared.
        cookie_header = resp.headers.get("set-cookie", "")
        assert "drevalis_session=" in cookie_header

    async def test_reset_route_with_2fa_user_returns_totp_stage(self) -> None:
        """User with active TOTP: reset-password returns totp_required challenge."""
        from datetime import datetime

        from drevalis.api.routes.auth import ResetPasswordRequest, reset_password

        user = _make_user(totp_confirmed_at=datetime(2026, 1, 1, tzinfo=UTC))
        db = AsyncMock()
        rq = _request()
        resp = Response()

        with (
            patch("drevalis.services.password_reset.consume_reset", AsyncMock(return_value=user)),
            patch(
                "drevalis.api.routes.auth._mint_totp_challenge",
                return_value="challenge_blob",
            ),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            result = await reset_password(
                body=ResetPasswordRequest(token="goodtoken", new_password="newpass1"),
                request=rq,
                response=resp,
                db=db,
                settings=_settings(),
            )

        assert result["stage"] == "totp_required"
        assert result["challenge"] == "challenge_blob"
