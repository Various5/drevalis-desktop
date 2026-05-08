"""Tests for auth hardening additions (A.1 / A.2 / A.3).

A.1 — Constant-time login: verify_password is called the same number of
      times regardless of whether the email exists.
A.2 — Login audit: login_events row inserted on every success/failure path.
A.3 — Session version: minting embeds sv; mismatched sv in _current_user
      rejects the token; logout-everywhere increments version + clears cookie.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request, Response

from drevalis.api.routes.auth import (
    LoginRequest,
    _current_user,
    login,
    logout_everywhere,
    my_login_history,
)
from drevalis.services.team import (
    mint_session_token,
    parse_session_token,
)

# ---------------------------------------------------------------------------
# Shared helpers (duplicated from test_auth_route.py to keep this file
# self-contained — the helper functions are trivial).
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
    # TOTP 2FA: default None (not enrolled) — keeps existing tests on the
    # password-only login path.
    u.totp_confirmed_at = overrides.get("totp_confirmed_at")
    return u


def _settings() -> Any:
    s = MagicMock()
    s.cookie_secure = False
    s.demo_mode = False
    s.get_session_secret = MagicMock(return_value="test-secret")
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


# ---------------------------------------------------------------------------
# A.1 — Constant-time login
# ---------------------------------------------------------------------------


class TestLoginConstantTime:
    """verify_password is called exactly once whether or not the email exists.

    We count *calls*, not wall-clock time — timing-based tests are flaky
    in CI.  What we care about is that the code path never *skips*
    verify_password for the missing-user or inactive-user cases.
    """

    async def test_unknown_email_still_calls_verify_password(self) -> None:
        """When no user row is found, verify_password must still be called
        (against the dummy hash) to burn the same ~150ms as a real attempt.
        """
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.record_login_failure", AsyncMock()),
            patch("asyncio.create_task", side_effect=_discard_task),
            patch("drevalis.api.routes.auth.verify_password", return_value=False) as mock_vp,
        ):
            with pytest.raises(HTTPException) as exc:
                await login(
                    body=LoginRequest(email="nobody@drevalis.test", password="guess"),
                    request=_request(),
                    response=Response(),
                    db=db,
                    settings=_settings(),
                )
        assert exc.value.status_code == 401
        # Must have been called at least once (against the dummy hash).
        assert mock_vp.call_count >= 1

    async def test_existing_email_calls_verify_password(self) -> None:
        """Baseline: for a real user, verify_password is called against
        the stored hash.  Call count must equal the unknown-email case.
        """
        u = _make_user()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=u)))

        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.record_login_failure", AsyncMock()),
            patch("asyncio.create_task", side_effect=_discard_task),
            patch("drevalis.api.routes.auth.verify_password", return_value=False) as mock_vp,
        ):
            with pytest.raises(HTTPException) as exc:
                await login(
                    body=LoginRequest(email=u.email, password="wrong"),
                    request=_request(),
                    response=Response(),
                    db=db,
                    settings=_settings(),
                )
        assert exc.value.status_code == 401
        # Called exactly once against the real stored hash.
        assert mock_vp.call_count == 1

    async def test_inactive_user_calls_verify_password(self) -> None:
        """Inactive-user branch also must call verify_password (not short-circuit)."""
        u = _make_user(is_active=False)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=u)))

        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.record_login_failure", AsyncMock()),
            patch("asyncio.create_task", side_effect=_discard_task),
            patch("drevalis.api.routes.auth.verify_password", return_value=False) as mock_vp,
        ):
            with pytest.raises(HTTPException) as exc:
                await login(
                    body=LoginRequest(email=u.email, password="whatever"),
                    request=_request(),
                    response=Response(),
                    db=db,
                    settings=_settings(),
                )
        assert exc.value.status_code == 401
        assert mock_vp.call_count >= 1


# ---------------------------------------------------------------------------
# A.2 — Login audit log
# ---------------------------------------------------------------------------


def _discard_task(coro: Any) -> MagicMock:
    """Side-effect for patching asyncio.create_task in tests that don't need
    to inspect the event row.  Closes the coroutine immediately so Python
    doesn't emit a 'coroutine was never awaited' RuntimeWarning.
    """
    coro.close()
    return MagicMock()


def _collect_tasks() -> tuple[list[Any], Any]:
    """Return (task_list, side_effect_fn) for patching asyncio.create_task.

    The side_effect captures the coroutine so tests can await it after the
    call under test completes, without leaving dangling unawaited coroutines.
    """
    tasks: list[Any] = []

    def _side_effect(coro: Any) -> MagicMock:
        tasks.append(coro)
        return MagicMock()

    return tasks, _side_effect


class TestLoginEventRecordedOnSuccess:
    async def test_success_row_has_user_id_and_no_failure_reason(self) -> None:
        u = _make_user()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=u)))
        db.commit = AsyncMock()

        captured: list[dict[str, Any]] = []

        async def _fake_record(
            session: Any,
            *,
            user_id: Any,
            email_attempted: Any,
            ip: str,
            user_agent: Any,
            success: bool,
            failure_reason: Any,
        ) -> None:
            captured.append(
                {
                    "user_id": user_id,
                    "email_attempted": email_attempted,
                    "success": success,
                    "failure_reason": failure_reason,
                }
            )

        tasks, task_side_effect = _collect_tasks()
        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.verify_password", return_value=True),
            patch("drevalis.api.routes.auth.mint_session_token", return_value="tok"),
            patch("drevalis.api.routes.auth._record_login_event", _fake_record),
            patch("asyncio.create_task", side_effect=task_side_effect),
        ):
            await login(
                body=LoginRequest(email=u.email, password="correct"),
                request=_request(),
                response=Response(),
                db=db,
                settings=_settings(),
            )
        # Drain captured coroutines so _fake_record actually runs.
        for coro in tasks:
            await coro

        success_rows = [r for r in captured if r["success"]]
        assert len(success_rows) >= 1
        row = success_rows[-1]
        assert row["user_id"] == u.id
        assert row["failure_reason"] is None
        assert row["email_attempted"] is None


class TestLoginEventRecordedOnUnknownEmail:
    async def test_unknown_email_row_has_no_user_id(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        captured: list[dict[str, Any]] = []

        async def _fake_record(session: Any, **kwargs: Any) -> None:
            captured.append(kwargs)

        tasks, task_side_effect = _collect_tasks()
        with (
            patch("drevalis.api.routes.auth.ensure_owner_from_env", AsyncMock()),
            patch("drevalis.api.routes.auth.check_login_rate_limit", AsyncMock()),
            patch("drevalis.api.routes.auth.record_login_failure", AsyncMock()),
            patch("drevalis.api.routes.auth.verify_password", return_value=False),
            patch("drevalis.api.routes.auth._record_login_event", _fake_record),
            patch("asyncio.create_task", side_effect=task_side_effect),
        ):
            with pytest.raises(HTTPException):
                await login(
                    body=LoginRequest(email="ghost@drevalis.test", password="x"),
                    request=_request(),
                    response=Response(),
                    db=db,
                    settings=_settings(),
                )
        for coro in tasks:
            await coro

        failure_rows = [r for r in captured if not r["success"]]
        assert len(failure_rows) >= 1
        row = failure_rows[0]
        assert row["user_id"] is None
        assert row["failure_reason"] == "unknown_email"
        assert row["email_attempted"] == "ghost@drevalis.test"


# ---------------------------------------------------------------------------
# A.3 — Session version
# ---------------------------------------------------------------------------


class TestSessionVersionInToken:
    def test_mint_embeds_sv_claim(self) -> None:
        uid = uuid4()
        token = mint_session_token(user_id=uid, role="owner", secret="s", session_version=7)
        payload = parse_session_token(token, secret="s")
        assert payload is not None
        assert int(payload["sv"]) == 7

    def test_default_sv_is_zero(self) -> None:
        uid = uuid4()
        token = mint_session_token(user_id=uid, role="owner", secret="s")
        payload = parse_session_token(token, secret="s")
        assert payload is not None
        assert int(payload["sv"]) == 0


class TestSessionVersionInvalidatesOldToken:
    """_current_user must reject a token whose sv doesn't match user.session_version."""

    async def test_stale_sv_returns_none(self) -> None:
        uid = uuid4()
        # Mint token at version 0.
        token = mint_session_token(
            user_id=uid, role="owner", secret="test-secret", session_version=0
        )

        # Simulate user having been bumped to version 1.
        u = _make_user(id=uid, session_version=1)
        db = AsyncMock()
        db.get = AsyncMock(return_value=u)

        result = await _current_user(
            request=_request(cookie=token),
            db=db,
            settings=_settings(),
        )
        assert result is None

    async def test_matching_sv_returns_user(self) -> None:
        uid = uuid4()
        token = mint_session_token(
            user_id=uid, role="owner", secret="test-secret", session_version=3
        )

        u = _make_user(id=uid, session_version=3)
        db = AsyncMock()
        db.get = AsyncMock(return_value=u)

        result = await _current_user(
            request=_request(cookie=token),
            db=db,
            settings=_settings(),
        )
        assert result is u


class TestLogoutEverywhere:
    async def test_increments_session_version_and_clears_cookie(self) -> None:
        u = _make_user(session_version=2)
        db = AsyncMock()
        db.commit = AsyncMock()
        resp = Response()

        out = await logout_everywhere(response=resp, me=u, db=db)

        assert out["message"] == "logged_out_everywhere"
        # session_version bumped by 1.
        assert u.session_version == 3
        db.commit.assert_awaited_once()
        # Cookie cleared.
        cookie_header = resp.headers.get("set-cookie", "")
        assert "drevalis_session=" in cookie_header

    async def test_unauthenticated_user_blocked(self) -> None:
        """require_user dependency raises 401 for unauthenticated callers."""
        from drevalis.api.routes.auth import require_user

        with pytest.raises(HTTPException) as exc:
            await require_user(user=None)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# A.2 — login-history endpoint privacy
# ---------------------------------------------------------------------------


class TestLoginHistoryEndpointOwnerSelfOnly:
    """GET /auth/login-history returns only the current user's rows.

    The route already enforces this by filtering on ``me.id`` — there is no
    ``user_id`` path parameter that could be substituted.  This test pins
    that the DB query is always scoped to the authenticated user's ID.
    """

    async def test_query_is_scoped_to_current_user(self) -> None:
        uid = uuid4()
        me = _make_user(id=uid)
        db = AsyncMock()

        # Simulate an empty result set (we only care about the filter, not
        # the rows returned).
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        db.execute = AsyncMock(return_value=result)

        rows = await my_login_history(me=me, db=db, limit=20)
        assert rows == []

        # The WHERE clause must reference me.id — inspect the compiled query.
        executed_stmt = db.execute.call_args[0][0]
        # SQLAlchemy Select: walk whereclause to find the bound user_id value.

        compiled = executed_stmt.compile()
        params_str = str(compiled.params)
        assert str(uid) in params_str
