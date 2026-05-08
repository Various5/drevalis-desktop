"""Tests for ``api/routes/social.py``.

Thin router over ``SocialService`` + the TikTok OAuth callback. Pin
the layered status mapping that drives the activation/connection UX:

* ``TikTokNotConfiguredError`` → 400
* ``TikTokInvalidStateError`` → 302 redirect with
  ``?tiktok_error=invalid_state`` (NOT a 400 — the user is in a
  browser flow and should be returned to settings, not shown a JSON)
* ``TikTokOAuthError`` → 400 with the upstream error code embedded
* OAuth ``error`` query parameter present → 302 redirect with the
  error code passed through (no token exchange attempted)
* ``ValidationError`` → 400, ``NotFoundError`` → 404 across CRUD
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from drevalis.api.routes.social import (
    _service,
    connect_platform,
    create_upload,
    disconnect_platform,
    get_stats,
    list_platforms,
    list_uploads,
    tiktok_auth_url,
    tiktok_callback,
    tiktok_status,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.social import (
    OverallStats,
    PlatformConnect,
    SocialUploadRequest,
)
from drevalis.services.social import (
    SocialService,
    TikTokInvalidStateError,
    TikTokNotConfiguredError,
    TikTokOAuthError,
)


def _make_platform(**overrides: Any) -> Any:
    p = MagicMock()
    p.id = overrides.get("id", uuid4())
    p.platform = overrides.get("platform", "tiktok")
    p.account_id = overrides.get("account_id", "tt-acc-1")
    p.account_name = overrides.get("account_name", "@drevalis")
    p.is_active = overrides.get("is_active", True)
    p.access_token_encrypted = overrides.get("access_token_encrypted", b"x")
    p.refresh_token_encrypted = overrides.get("refresh_token_encrypted", b"y")
    p.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    p.updated_at = overrides.get("updated_at", datetime(2026, 1, 2))
    return p


def _make_upload(**overrides: Any) -> Any:
    u = MagicMock()
    u.id = overrides.get("id", uuid4())
    u.platform_id = overrides.get("platform_id", uuid4())
    u.episode_id = overrides.get("episode_id", uuid4())
    u.content_type = overrides.get("content_type", "episode")
    u.platform_content_id = overrides.get("platform_content_id")
    u.platform_url = overrides.get("platform_url")
    u.title = overrides.get("title", "Hook A")
    u.description = overrides.get("description", "")
    u.hashtags = overrides.get("hashtags", "")
    u.upload_status = overrides.get("upload_status", "pending")
    u.error_message = overrides.get("error_message")
    u.views = overrides.get("views", 0)
    u.likes = overrides.get("likes", 0)
    u.comments = overrides.get("comments", 0)
    u.shares = overrides.get("shares", 0)
    u.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    u.updated_at = overrides.get("updated_at", datetime(2026, 1, 1))
    return u


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service(self) -> None:
        db = AsyncMock()
        settings = MagicMock()
        svc = _service(db=db, settings=settings)
        assert isinstance(svc, SocialService)


# ── GET /tiktok/auth-url ────────────────────────────────────────────


class TestTikTokAuthURL:
    async def test_returns_url_and_state(self) -> None:
        svc = MagicMock()
        svc.tiktok_auth_url = AsyncMock(
            return_value=("https://tiktok.test/oauth/auth?state=abc", "abc")
        )
        with patch("drevalis.api.routes.social.require_feature"):
            out = await tiktok_auth_url(svc=svc)
        assert out.auth_url.startswith("https://tiktok")
        assert out.state == "abc"

    async def test_not_configured_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.tiktok_auth_url = AsyncMock(side_effect=TikTokNotConfiguredError("client_key unset"))
        with patch("drevalis.api.routes.social.require_feature"):
            with pytest.raises(HTTPException) as exc:
                await tiktok_auth_url(svc=svc)
        assert exc.value.status_code == 400


# ── GET /tiktok/callback ───────────────────────────────────────────


class TestTikTokCallback:
    async def test_user_denied_redirects_with_error(self) -> None:
        # User denied on TikTok consent screen. We must NOT hit
        # tiktok_complete_oauth — just bounce back to settings carrying
        # the error code so the UI can render a "you cancelled" toast.
        svc = MagicMock()
        svc.tiktok_complete_oauth = AsyncMock()
        out = await tiktok_callback(
            code="ignored",
            state="x",
            error="access_denied",
            error_description="User cancelled",
            svc=svc,
        )
        assert isinstance(out, RedirectResponse)
        assert out.status_code == 302
        loc = out.headers["location"]
        assert "tiktok_error=access_denied" in loc
        svc.tiktok_complete_oauth.assert_not_awaited()

    async def test_success_redirects_to_settings(self) -> None:
        svc = MagicMock()
        svc.tiktok_complete_oauth = AsyncMock()
        out = await tiktok_callback(
            code="auth-code", state="csrf", error=None, error_description=None, svc=svc
        )
        assert isinstance(out, RedirectResponse)
        assert out.status_code == 302
        # No error param on success.
        assert "tiktok_error" not in out.headers["location"]
        svc.tiktok_complete_oauth.assert_awaited_once_with("auth-code", "csrf")

    async def test_invalid_state_redirects_with_invalid_state_error(self) -> None:
        # CSRF-bypass attempt or replayed state. Browser flow → redirect,
        # not 400, so the user lands somewhere they can recover from.
        svc = MagicMock()
        svc.tiktok_complete_oauth = AsyncMock(side_effect=TikTokInvalidStateError())
        out = await tiktok_callback(
            code="auth-code",
            state="bad",
            error=None,
            error_description=None,
            svc=svc,
        )
        assert isinstance(out, RedirectResponse)
        assert "tiktok_error=invalid_state" in out.headers["location"]

    async def test_not_configured_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.tiktok_complete_oauth = AsyncMock(
            side_effect=TikTokNotConfiguredError("client_secret unset")
        )
        with pytest.raises(HTTPException) as exc:
            await tiktok_callback(
                code="x",
                state="y",
                error=None,
                error_description=None,
                svc=svc,
            )
        assert exc.value.status_code == 400

    async def test_oauth_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.tiktok_complete_oauth = AsyncMock(side_effect=TikTokOAuthError("invalid_grant"))
        with pytest.raises(HTTPException) as exc:
            await tiktok_callback(
                code="x",
                state="y",
                error=None,
                error_description=None,
                svc=svc,
            )
        assert exc.value.status_code == 400
        # Detail surfaces the upstream error code so debugging is possible.
        assert "invalid_grant" in str(exc.value.detail)


# ── GET /tiktok/status ─────────────────────────────────────────────


class TestTikTokStatus:
    async def test_disconnected_when_no_active_connection(self) -> None:
        svc = MagicMock()
        svc.tiktok_active_connection = AsyncMock(return_value=None)
        out = await tiktok_status(svc=svc)
        assert out.connected is False
        assert out.account is None

    async def test_connected_includes_account(self) -> None:
        svc = MagicMock()
        svc.tiktok_active_connection = AsyncMock(return_value=_make_platform())
        out = await tiktok_status(svc=svc)
        assert out.connected is True
        assert out.account is not None
        assert out.account.platform == "tiktok"


# ── Platform CRUD ──────────────────────────────────────────────────


class TestPlatformCrud:
    async def test_list_platforms(self) -> None:
        svc = MagicMock()
        svc.list_platforms = AsyncMock(
            return_value=[_make_platform(), _make_platform(platform="instagram")]
        )
        out = await list_platforms(svc=svc)
        assert len(out) == 2
        assert {p.platform for p in out} == {"tiktok", "instagram"}

    async def test_connect_platform_success(self) -> None:
        svc = MagicMock()
        platform = _make_platform()
        svc.connect_platform = AsyncMock(return_value=platform)
        body = PlatformConnect(
            platform="tiktok",
            account_name="@drevalis",
            account_id="tt-acc-1",
            access_token="token",
        )
        with patch("drevalis.api.routes.social.require_feature"):
            out = await connect_platform(body, svc=svc)
        assert out.platform == "tiktok"

    async def test_connect_platform_validation_error(self) -> None:
        svc = MagicMock()
        svc.connect_platform = AsyncMock(side_effect=ValidationError("token already used"))
        body = PlatformConnect(platform="x", account_name="acc", access_token="tok")
        with patch("drevalis.api.routes.social.require_feature"):
            with pytest.raises(HTTPException) as exc:
                await connect_platform(body, svc=svc)
        assert exc.value.status_code == 400

    async def test_disconnect_platform_success(self) -> None:
        svc = MagicMock()
        svc.disconnect_platform = AsyncMock()
        await disconnect_platform(uuid4(), svc=svc)
        svc.disconnect_platform.assert_awaited_once()

    async def test_disconnect_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.disconnect_platform = AsyncMock(side_effect=NotFoundError("social_platform", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await disconnect_platform(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── Uploads ────────────────────────────────────────────────────────


class TestUploads:
    async def test_create_upload_success(self) -> None:
        svc = MagicMock()
        svc.get_platform = AsyncMock(return_value=_make_platform())
        svc.create_upload = AsyncMock(return_value=_make_upload())
        body = SocialUploadRequest(platform_id=uuid4(), title="Hook")
        with patch("drevalis.api.routes.social.require_feature"):
            out = await create_upload(body, svc=svc)
        assert out.title == "Hook A"

    async def test_create_upload_not_found(self) -> None:
        svc = MagicMock()
        svc.get_platform = AsyncMock(return_value=_make_platform())
        svc.create_upload = AsyncMock(side_effect=NotFoundError("social_platform", uuid4()))
        body = SocialUploadRequest(platform_id=uuid4(), title="Hook")
        with patch("drevalis.api.routes.social.require_feature"):
            with pytest.raises(HTTPException) as exc:
                await create_upload(body, svc=svc)
        assert exc.value.status_code == 404

    async def test_create_upload_validation(self) -> None:
        svc = MagicMock()
        svc.get_platform = AsyncMock(return_value=_make_platform())
        svc.create_upload = AsyncMock(side_effect=ValidationError("episode not exported"))
        body = SocialUploadRequest(platform_id=uuid4(), title="Hook")
        with patch("drevalis.api.routes.social.require_feature"):
            with pytest.raises(HTTPException) as exc:
                await create_upload(body, svc=svc)
        assert exc.value.status_code == 400

    async def test_list_uploads(self) -> None:
        svc = MagicMock()
        svc.list_uploads = AsyncMock(return_value=[_make_upload()])
        pid = uuid4()
        out = await list_uploads(platform_id=pid, limit=25, svc=svc)
        assert len(out) == 1
        svc.list_uploads.assert_awaited_once_with(platform_id=pid, limit=25)


# ── Stats ──────────────────────────────────────────────────────────


class TestStats:
    async def test_returns_overall_stats(self) -> None:
        svc = MagicMock()
        stats = OverallStats(
            platforms=[],
            total_platforms_connected=0,
            total_uploads=10,
            total_views=1000,
            total_likes=100,
        )
        svc.stats = AsyncMock(return_value=stats)
        out = await get_stats(svc=svc)
        assert out.total_uploads == 10
