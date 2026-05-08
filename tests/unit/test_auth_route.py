"""Tests for ``api/routes/auth.py``.

Login + session cookies + owner-only user CRUD. This is the only
surface guarding multi-user installs — pin every branch that decides
who can do what:

* `_current_user`: missing / bad / no-uid / invalid-uid / inactive-user
  cookies all yield None (anonymous).
* `require_user` → 401, `require_owner` → 403 when not owner.
* Login: rate-limit → 429, invalid creds record a failure (so future
  attempts hit the rate limiter), success sets the cookie + bumps
  `last_login_at`.
* `update_user`: an owner demoting themselves when they are the **only
  active owner** must be blocked (409 `cannot_remove_last_owner`) —
  otherwise the install is unrecoverable.
* `delete_user`: self-delete refused (409 `cannot_delete_self`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request, Response

from drevalis.api.routes.auth import (
    LoginRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
    _current_user,
    auth_mode,
    create_user,
    delete_user,
    list_users,
    login,
    logout,
    require_owner,
    require_user,
    update_user,
    whoami,
)
from drevalis.core.auth import LoginRateLimitedError


def _make_user(**overrides: Any) -> Any:
    u = MagicMock()
    u.id = overrides.get("id", uuid4())
    u.email = overrides.get("email", "owner@drevalis.test")
    u.role = overrides.get("role", "owner")
    u.display_name = overrides.get("display_name")
    u.is_active = overrides.get("is_active", True)
    u.last_login_at = overrides.get("last_login_at")
    u.password_hash = overrides.get("password_hash", "$pbkdf2$xx")
    u.created_at = overrides.get("created_at", datetime(2026, 1, 1, tzinfo=UTC))
    # A.3 — session version: default to 0 so _current_user sv check passes.
    u.session_version = overrides.get("session_version", 0)
    # TOTP 2FA: default to None (not enrolled) so the login TOTP branch is
    # not triggered in tests that don't exercise 2FA.
    u.totp_confirmed_at = overrides.get("totp_confirmed_at")
    return u


def _settings() -> Any:
    s = MagicMock()
    s.cookie_secure = False
    s.demo_mode = False
    s.get_session_secret = MagicMock(return_value="secret")
    return s


def _request(cookie: str | None = None, ip: str = "10.0.0.1") -> Any:
    req = MagicMock(spec=Request)
    req.cookies = {"drevalis_session": cookie} if cookie else {}
    client = MagicMock()
    client.host = ip
    req.client = client
    return req


# ── _current_user ──────────────────────────────────────────────────


class TestCurrentUser:
    async def test_no_cookie_returns_none(self) -> None:
        out = await _current_user(request=_request(), db=AsyncMock(), settings=_settings())
        assert out is None

    async def test_unparseable_token_returns_none(self) -> None:
        with patch("drevalis.api.routes.auth.parse_session_token", return_value=None):
            out = await _current_user(
                request=_request(cookie="garbage"),
                db=AsyncMock(),
                settings=_settings(),
            )
        assert out is None

    async def test_missing_uid_in_payload_returns_none(self) -> None:
        with patch(
            "drevalis.api.routes.auth.parse_session_token",
            return_value={"role": "owner"},  # no uid
        ):
            out = await _current_user(
                request=_request(cookie="x"),
                db=AsyncMock(),
                settings=_settings(),
            )
        assert out is None

    async def test_invalid_uuid_in_payload_returns_none(self) -> None:
        with patch(
            "drevalis.api.routes.auth.parse_session_token",
            return_value={"uid": "not-a-uuid"},
        ):
            out = await _current_user(
                request=_request(cookie="x"),
                db=AsyncMock(),
                settings=_settings(),
            )
        assert out is None

    async def test_user_missing_returns_none(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        with patch(
            "drevalis.api.routes.auth.parse_session_token",
            return_value={"uid": str(uuid4())},
        ):
            out = await _current_user(request=_request(cookie="x"), db=db, settings=_settings())
        assert out is None

    async def test_inactive_user_returns_none(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=_make_user(is_active=False))
        with patch(
            "drevalis.api.routes.auth.parse_session_token",
            return_value={"uid": str(uuid4())},
        ):
            out = await _current_user(request=_request(cookie="x"), db=db, settings=_settings())
        assert out is None

    async def test_active_user_returned(self) -> None:
        u = _make_user()
        db = AsyncMock()
        db.get = AsyncMock(return_value=u)
        with patch(
            "drevalis.api.routes.auth.parse_session_token",
            # A.3: sv claim must match user.session_version (both 0 here).
            return_value={"uid": str(u.id), "sv": 0},
        ):
            out = await _current_user(request=_request(cookie="x"), db=db, settings=_settings())
        assert out is u


# ── require_user / require_owner ───────────────────────────────────


class TestRequireGuards:
    async def test_require_user_unauthenticated_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await require_user(user=None)
        assert exc.value.status_code == 401

    async def test_require_user_authenticated_returns_user(self) -> None:
        u = _make_user()
        out = await require_user(user=u)
        assert out is u

    async def test_require_owner_non_owner_raises_403(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await require_owner(user=_make_user(role="editor"))
        assert exc.value.status_code == 403

    async def test_require_owner_owner_returns_user(self) -> None:
        u = _make_user(role="owner")
        out = await require_owner(user=u)
        assert out is u


# ── POST /auth/login ───────────────────────────────────────────────


class TestLogin:
    async def test_rate_limit_maps_to_429(self) -> None:
        db = AsyncMock()
        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch(
                "drevalis.api.routes.auth.check_login_rate_limit",
                AsyncMock(side_effect=LoginRateLimitedError("too many tries")),
            ),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await login(
                    body=LoginRequest(email="a@b.co", password="x"),
                    request=_request(),
                    response=Response(),
                    db=db,
                    settings=_settings(),
                )
        assert exc.value.status_code == 429

    async def test_invalid_credentials_record_failure_and_401(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        record = AsyncMock()
        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.record_login_failure", record),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await login(
                    body=LoginRequest(email="a@b.co", password="x"),
                    request=_request(),
                    response=Response(),
                    db=db,
                    settings=_settings(),
                )
        assert exc.value.status_code == 401
        # F-S-09 invariant: failed attempts MUST be recorded so the
        # rate limiter has a signal to act on next time.
        record.assert_awaited_once()

    async def test_inactive_user_treated_as_invalid_credentials(self) -> None:
        # Pin: an inactive user with a matching password still gets 401
        # — auth must not leak the existence of disabled accounts.
        u = _make_user(is_active=False)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=u)))
        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.verify_password", return_value=True),
            patch("drevalis.api.routes.auth.record_login_failure", AsyncMock()),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await login(
                    body=LoginRequest(email="a@b.co", password="x"),
                    request=_request(),
                    response=Response(),
                    db=db,
                    settings=_settings(),
                )
        assert exc.value.status_code == 401

    async def test_success_sets_cookie_and_bumps_last_login(self) -> None:
        u = _make_user()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=u)))
        db.commit = AsyncMock()
        resp = Response()
        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.verify_password", return_value=True),
            patch("drevalis.api.routes.auth.mint_session_token", return_value="tok"),
            patch("asyncio.create_task", side_effect=lambda c: c.close() or MagicMock()),
        ):
            out = await login(
                body=LoginRequest(email="a@b.co", password="x"),
                request=_request(),
                response=resp,
                db=db,
                settings=_settings(),
            )
        assert out["message"] == "logged_in"
        assert out["role"] == "owner"
        assert u.last_login_at is not None
        # Cookie is set on the response.
        cookie_header = resp.headers.get("set-cookie", "")
        assert "drevalis_session=tok" in cookie_header
        assert "HttpOnly" in cookie_header
        assert "SameSite=lax" in cookie_header.lower() or "samesite=lax" in cookie_header.lower()


# ── POST /auth/logout ──────────────────────────────────────────────


class TestLogout:
    async def test_clears_cookie(self) -> None:
        resp = Response()
        out = await logout(response=resp)
        assert out["message"] == "logged_out"
        # delete_cookie is implemented as set with empty value + Max-Age=0.
        cookie_header = resp.headers.get("set-cookie", "")
        assert "drevalis_session=" in cookie_header


# ── GET /auth/me ───────────────────────────────────────────────────


class TestWhoami:
    async def test_returns_none_when_anonymous(self) -> None:
        out = await whoami(user=None)
        assert out is None

    async def test_returns_user_when_authenticated(self) -> None:
        u = _make_user(email="me@drevalis.test")
        out = await whoami(user=u)
        assert isinstance(out, UserResponse)
        assert out.email == "me@drevalis.test"


# ── GET /auth/mode ─────────────────────────────────────────────────


class TestAuthMode:
    async def test_team_mode_when_users_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OWNER_EMAIL", raising=False)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=1)))
        out = await auth_mode(db=db, settings=_settings())
        assert out["team_mode"] is True
        assert out["demo_mode"] is False

    async def test_team_mode_when_owner_env_set_even_with_no_users(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OWNER_EMAIL", "owner@drevalis.test")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=0)))
        out = await auth_mode(db=db, settings=_settings())
        assert out["team_mode"] is True

    async def test_solo_mode_when_neither_users_nor_owner_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OWNER_EMAIL", raising=False)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=0)))
        out = await auth_mode(db=db, settings=_settings())
        assert out["team_mode"] is False


# ── GET /users ─────────────────────────────────────────────────────


class TestListUsers:
    async def test_returns_all_users(self) -> None:
        db = AsyncMock()
        u1, u2 = _make_user(), _make_user(email="b@b.co")
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[u1, u2])
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=result)
        out = await list_users(_=_make_user(role="owner"), db=db)
        assert len(out) == 2


# ── POST /users ────────────────────────────────────────────────────


class TestCreateUser:
    async def test_duplicate_email_raises_409(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=_make_user()))
        )
        with pytest.raises(HTTPException) as exc:
            await create_user(
                body=UserCreate(email="dupe@b.co", password="passwordpw"),
                _=_make_user(role="owner"),
                db=db,
            )
        assert exc.value.status_code == 409

    async def test_success_creates_user(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        added: list[Any] = []

        def _add(u: Any) -> None:
            added.append(u)

        db.add = MagicMock(side_effect=_add)
        db.commit = AsyncMock()

        # Real DB.refresh would populate server-default fields (id +
        # is_active); fake it here so UserResponse.from_orm doesn't trip
        # on None values.
        async def _refresh(u: Any) -> None:
            if u.id is None:
                u.id = uuid4()
            if u.is_active is None:
                u.is_active = True

        db.refresh = AsyncMock(side_effect=_refresh)

        with patch("drevalis.api.routes.auth.hash_password", return_value="hashed"):
            out = await create_user(
                body=UserCreate(email="new@b.co", password="passwordpw", role="editor"),
                _=_make_user(role="owner"),
                db=db,
            )
        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        assert out.email == "new@b.co"
        # Password was hashed before storage, never persisted plaintext.
        assert added[0].password_hash == "hashed"


# ── PUT /users/{id} ────────────────────────────────────────────────


class TestUpdateUser:
    async def test_user_not_found_maps_to_404(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await update_user(
                user_id=uuid4(),
                body=UserUpdate(role="editor"),
                me=_make_user(role="owner"),
                db=db,
            )
        assert exc.value.status_code == 404

    async def test_last_owner_demotion_blocked(self) -> None:
        # Owner is editing their own row, demoting to editor — but they
        # are the only active owner. Must 409 to prevent lockout.
        me = _make_user(role="owner")
        db = AsyncMock()
        db.get = AsyncMock(return_value=me)
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[me])  # only this owner
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=result)
        with pytest.raises(HTTPException) as exc:
            await update_user(
                user_id=me.id,
                body=UserUpdate(role="editor"),
                me=me,
                db=db,
            )
        assert exc.value.status_code == 409
        assert "cannot_remove_last_owner" in exc.value.detail

    async def test_demotion_allowed_when_other_owners_exist(self) -> None:
        me = _make_user(role="owner")
        other_owner = _make_user(role="owner")
        db = AsyncMock()
        db.get = AsyncMock(return_value=me)
        scalars = MagicMock()
        # Two owners — me + another. Demoting me leaves the other.
        scalars.all = MagicMock(return_value=[me, other_owner])
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        out = await update_user(
            user_id=me.id,
            body=UserUpdate(role="editor"),
            me=me,
            db=db,
        )
        assert out.role == "editor"

    async def test_password_change_rehashed(self) -> None:
        u = _make_user(role="editor")
        db = AsyncMock()
        db.get = AsyncMock(return_value=u)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        with patch("drevalis.api.routes.auth.hash_password", return_value="new-hash"):
            await update_user(
                user_id=u.id,
                body=UserUpdate(password="newsecret123"),
                me=_make_user(role="owner"),
                db=db,
            )
        assert u.password_hash == "new-hash"

    async def test_partial_field_updates(self) -> None:
        u = _make_user(role="editor", display_name=None, is_active=True)
        db = AsyncMock()
        db.get = AsyncMock(return_value=u)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await update_user(
            user_id=u.id,
            body=UserUpdate(display_name="Sara", is_active=False),
            me=_make_user(role="owner"),
            db=db,
        )
        assert u.display_name == "Sara"
        assert u.is_active is False


# ── DELETE /users/{id} ─────────────────────────────────────────────


class TestDeleteUser:
    async def test_self_delete_blocked_with_409(self) -> None:
        me = _make_user(role="owner")
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await delete_user(user_id=me.id, me=me, db=db)
        assert exc.value.status_code == 409
        assert "cannot_delete_self" in exc.value.detail

    async def test_missing_user_silent_success(self) -> None:
        # 404 leaks user existence; the route deliberately returns 204
        # for both "deleted" and "didn't exist". Pin the 204 path.
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        out = await delete_user(user_id=uuid4(), me=_make_user(role="owner"), db=db)
        assert out is None
        db.delete.assert_not_called()

    async def test_success_deletes(self) -> None:
        target = _make_user(email="gone@b.co")
        db = AsyncMock()
        db.get = AsyncMock(return_value=target)
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        await delete_user(user_id=target.id, me=_make_user(role="owner"), db=db)
        db.delete.assert_awaited_once_with(target)
        db.commit.assert_awaited_once()
