"""Tests for ``api/routes/youtube/_monolith.py`` (OAuth + channel CRUD).

YouTube has the most error-shape variety in the codebase. Pin:

* `build_youtube_service` translates `YouTubeNotConfiguredError` into:
  - 503 with the `youtube_key_decrypt_failed` hint when the DB has
    rows but they can't be decrypted (most common cause: backup
    restored onto a different ENCRYPTION_KEY).
  - 503 with the "set YOUTUBE_CLIENT_ID/SECRET in .env" hint when
    keys are absent entirely.
* `_ambiguous_channel_400` builds the `channel_id_required` 400 with
  the connected-channels list so the UI can render a picker.
* OAuth callback: missing state → 400, expired/forged state →
  400, redis store down → 503.
* `disconnect`: ambiguous channels → 400, missing → 404.
* `oauth_callback` routes `ChannelCapExceededError` → 402 Payment
  Required with tier + limit detail.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.youtube._monolith import (
    _ambiguous_channel_400,
    _service,
    build_youtube_service,
    connection_status,
    delete_channel,
    disconnect,
    get_auth_url,
    list_channels,
    oauth_callback,
    update_channel,
)
from drevalis.core.exceptions import NotFoundError
from drevalis.schemas.youtube import YouTubeChannelUpdate
from drevalis.services.youtube_admin import (
    ChannelCapExceededError,
    MultipleChannelsAmbiguousError,
    YouTubeAdminService,
    YouTubeNotConfiguredError,
)


def _settings() -> Any:
    s = MagicMock()
    s.demo_mode = False
    return s


def _make_channel(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "channel_id": "UC_test123",
        "channel_name": "Drevalis",
        "is_active": True,
        "upload_days": ["mon", "wed", "fri"],
        "upload_time": "10:00",
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 2),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── _service factory ───────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_admin_service(self) -> None:
        svc = _service(db=AsyncMock(), settings=_settings())
        assert isinstance(svc, YouTubeAdminService)


# ── build_youtube_service ──────────────────────────────────────────


class TestBuildYouTubeService:
    async def test_success_returns_service(self) -> None:
        fake_svc = MagicMock()
        with patch(
            "drevalis.api.routes.youtube._monolith._build_youtube_service",
            AsyncMock(return_value=fake_svc),
        ):
            out = await build_youtube_service(_settings(), AsyncMock())
        assert out is fake_svc

    async def test_decrypt_failed_503_with_hint(self) -> None:
        # DB rows present but ENCRYPTION_KEY rotated → decrypt fails.
        # Pin the structured 503 detail with id_stored / secret_stored
        # flags so the UI can render an actionable error banner.
        with patch(
            "drevalis.api.routes.youtube._monolith._build_youtube_service",
            AsyncMock(side_effect=YouTubeNotConfiguredError(has_id_row=True, has_secret_row=True)),
        ):
            with pytest.raises(HTTPException) as exc:
                await build_youtube_service(_settings(), AsyncMock())
        assert exc.value.status_code == 503
        assert exc.value.detail["error"] == "youtube_key_decrypt_failed"
        assert exc.value.detail["id_stored"] is True
        assert exc.value.detail["secret_stored"] is True

    async def test_partially_stored_still_routes_to_decrypt_hint(self) -> None:
        # Only ID row present (secret missing) — pin: still routes to
        # the decrypt hint because rows-exist-but-incomplete is also
        # a "rotate-the-key" footgun.
        with patch(
            "drevalis.api.routes.youtube._monolith._build_youtube_service",
            AsyncMock(side_effect=YouTubeNotConfiguredError(has_id_row=True, has_secret_row=False)),
        ):
            with pytest.raises(HTTPException) as exc:
                await build_youtube_service(_settings(), AsyncMock())
        assert exc.value.status_code == 503
        assert exc.value.detail["error"] == "youtube_key_decrypt_failed"

    async def test_no_rows_503_with_setup_hint(self) -> None:
        # Neither row present → "set YOUTUBE_CLIENT_ID/SECRET" hint.
        with patch(
            "drevalis.api.routes.youtube._monolith._build_youtube_service",
            AsyncMock(
                side_effect=YouTubeNotConfiguredError(has_id_row=False, has_secret_row=False)
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await build_youtube_service(_settings(), AsyncMock())
        assert exc.value.status_code == 503
        # Plain string detail (not the dict variant).
        assert "YOUTUBE_CLIENT_ID" in exc.value.detail


# ── _ambiguous_channel_400 ─────────────────────────────────────────


class TestAmbiguousChannel400:
    def test_includes_connected_channels(self) -> None:
        a = _make_channel(channel_id="UC_a", channel_name="A")
        b = _make_channel(channel_id="UC_b", channel_name="B")
        exc = _ambiguous_channel_400(MultipleChannelsAmbiguousError(channels=[a, b]))
        assert exc.status_code == 400
        assert exc.detail["error"] == "channel_id_required"
        names = {c["name"] for c in exc.detail["connected_channels"]}
        assert names == {"A", "B"}


# ── GET /auth-url ──────────────────────────────────────────────────


class TestGetAuthURL:
    async def test_persists_state_to_redis_with_ttl(self) -> None:
        yt = MagicMock()
        yt.get_auth_url = MagicMock(return_value=("https://google/x", "abc-state"))
        redis = AsyncMock()
        redis.setex = AsyncMock()
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await get_auth_url(settings=_settings(), redis=redis, db=AsyncMock())
        assert out.auth_url == "https://google/x"
        # 10-minute TTL on the CSRF state key.
        redis.setex.assert_awaited_once()
        args = redis.setex.await_args.args
        assert args[0] == "youtube_oauth_state:abc-state"
        assert args[1] == 600

    async def test_redis_failure_does_not_block_url_return(self) -> None:
        # Pin: a transient Redis failure on state persistence is
        # logged-and-swallowed — the user still gets the URL. The
        # callback will fail their state check downstream, which is
        # the correct security posture.
        yt = MagicMock()
        yt.get_auth_url = MagicMock(return_value=("https://google/x", "s"))
        redis = AsyncMock()
        redis.setex = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await get_auth_url(settings=_settings(), redis=redis, db=AsyncMock())
        assert out.auth_url == "https://google/x"


# ── GET /callback ──────────────────────────────────────────────────


class TestOAuthCallback:
    async def test_missing_state_400(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await oauth_callback(
                code="abc",
                state=None,
                db=AsyncMock(),
                settings=_settings(),
                redis=AsyncMock(),
                admin=MagicMock(),
            )
        assert exc.value.status_code == 400

    async def test_redis_lookup_failure_503(self) -> None:
        redis = AsyncMock()
        redis.getdel = AsyncMock(side_effect=ConnectionError("redis down"))
        with pytest.raises(HTTPException) as exc:
            await oauth_callback(
                code="abc",
                state="s",
                db=AsyncMock(),
                settings=_settings(),
                redis=redis,
                admin=MagicMock(),
            )
        assert exc.value.status_code == 503

    async def test_unknown_state_400(self) -> None:
        # State is missing from Redis (TTL expired or never persisted)
        # → 400. Pin: this is a CSRF guard, NOT a 404.
        redis = AsyncMock()
        redis.getdel = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await oauth_callback(
                code="abc",
                state="bogus",
                db=AsyncMock(),
                settings=_settings(),
                redis=redis,
                admin=MagicMock(),
            )
        assert exc.value.status_code == 400
        assert "Invalid or expired" in exc.value.detail

    async def test_callback_failure_400(self) -> None:
        redis = AsyncMock()
        redis.getdel = AsyncMock(return_value=b"1")
        yt = MagicMock()
        yt.handle_callback = AsyncMock(side_effect=ConnectionError("Google handshake failed"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await oauth_callback(
                    code="abc",
                    state="s",
                    db=AsyncMock(),
                    settings=_settings(),
                    redis=redis,
                    admin=MagicMock(),
                )
        assert exc.value.status_code == 400

    async def test_channel_cap_402(self) -> None:
        # Pin: hitting the tier's channel cap returns 402 Payment
        # Required with tier+limit so the UI can route to the
        # upgrade flow.
        redis = AsyncMock()
        redis.getdel = AsyncMock(return_value=b"1")
        yt = MagicMock()
        yt.handle_callback = AsyncMock(return_value={"channel_id": "UC_x"})
        admin = MagicMock()
        admin.upsert_oauth_channel = AsyncMock(
            side_effect=ChannelCapExceededError(tier="creator", limit=1)
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await oauth_callback(
                    code="abc",
                    state="s",
                    db=AsyncMock(),
                    settings=_settings(),
                    redis=redis,
                    admin=admin,
                )
        assert exc.value.status_code == 402
        assert exc.value.detail["tier"] == "creator"
        assert exc.value.detail["limit"] == 1

    async def test_success_returns_channel_response(self) -> None:
        redis = AsyncMock()
        redis.getdel = AsyncMock(return_value=b"1")
        yt = MagicMock()
        yt.handle_callback = AsyncMock(return_value={"channel_id": "UC_x"})
        admin = MagicMock()
        admin.upsert_oauth_channel = AsyncMock(return_value=_make_channel())
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await oauth_callback(
                code="abc",
                state="s",
                db=AsyncMock(),
                settings=_settings(),
                redis=redis,
                admin=admin,
            )
        assert out.channel_id == "UC_test123"


# ── GET /status ────────────────────────────────────────────────────


class TestConnectionStatus:
    async def test_disconnected_when_no_channels(self) -> None:
        admin = MagicMock()
        admin.connection_status = AsyncMock(return_value=([], None))
        out = await connection_status(admin=admin)
        assert out.connected is False
        assert out.channel is None
        assert out.channels == []

    async def test_connected_with_active(self) -> None:
        admin = MagicMock()
        a = _make_channel(channel_name="A")
        b = _make_channel(channel_name="B")
        admin.connection_status = AsyncMock(return_value=([a, b], a))
        out = await connection_status(admin=admin)
        assert out.connected is True
        assert out.channel is not None
        assert out.channel.channel_name == "A"
        assert len(out.channels) == 2

    async def test_falls_back_to_first_when_no_active(self) -> None:
        # Pin: when no channel is marked active, the response uses the
        # first channel as `primary` so the UI has something to show.
        admin = MagicMock()
        a = _make_channel(channel_name="First")
        b = _make_channel(channel_name="Second")
        admin.connection_status = AsyncMock(return_value=([a, b], None))
        out = await connection_status(admin=admin)
        assert out.connected is True
        assert out.channel is not None
        assert out.channel.channel_name == "First"


# ── POST /disconnect ───────────────────────────────────────────────


class TestDisconnect:
    async def test_success_returns_disconnect_message(self) -> None:
        admin = MagicMock()
        admin.disconnect = AsyncMock(return_value="Drevalis")
        out = await disconnect(channel_id=None, admin=admin)
        assert out["message"] == "Disconnected YouTube channel: Drevalis"

    async def test_ambiguous_400_with_channel_list(self) -> None:
        admin = MagicMock()
        a = _make_channel(channel_name="A")
        b = _make_channel(channel_name="B")
        admin.disconnect = AsyncMock(side_effect=MultipleChannelsAmbiguousError(channels=[a, b]))
        with pytest.raises(HTTPException) as exc:
            await disconnect(channel_id=None, admin=admin)
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "channel_id_required"
        # Disconnect's own list shape: id + name (no channel_id field).
        names = {c["name"] for c in exc.value.detail["connected_channels"]}
        assert names == {"A", "B"}

    async def test_not_found_404(self) -> None:
        admin = MagicMock()
        admin.disconnect = AsyncMock(side_effect=NotFoundError("youtube_channel", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await disconnect(channel_id=uuid4(), admin=admin)
        assert exc.value.status_code == 404


# ── GET /channels ──────────────────────────────────────────────────


class TestListChannels:
    async def test_active_only_by_default(self) -> None:
        admin = MagicMock()
        admin.list_channels = AsyncMock(return_value=[_make_channel()])
        await list_channels(include_inactive=False, admin=admin)
        admin.list_channels.assert_awaited_once_with(include_inactive=False)

    async def test_include_inactive_passes_through(self) -> None:
        admin = MagicMock()
        admin.list_channels = AsyncMock(return_value=[])
        await list_channels(include_inactive=True, admin=admin)
        admin.list_channels.assert_awaited_once_with(include_inactive=True)


# ── DELETE /channels/{id} ──────────────────────────────────────────


class TestDeleteChannel:
    async def test_success(self) -> None:
        admin = MagicMock()
        admin.delete_channel = AsyncMock(return_value="Drevalis")
        out = await delete_channel(uuid4(), admin=admin)
        assert "Drevalis" in out["message"]

    async def test_not_found_404(self) -> None:
        admin = MagicMock()
        admin.delete_channel = AsyncMock(side_effect=NotFoundError("youtube_channel", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_channel(uuid4(), admin=admin)
        assert exc.value.status_code == 404


# ── PUT /channels/{id} ─────────────────────────────────────────────


class TestUpdateChannel:
    async def test_success(self) -> None:
        admin = MagicMock()
        admin.update_channel = AsyncMock(return_value=_make_channel(upload_time="14:00"))
        out = await update_channel(
            uuid4(),
            YouTubeChannelUpdate(upload_time="14:00"),
            admin=admin,
        )
        assert out.upload_time == "14:00"
        kwargs = admin.update_channel.call_args.args[1]
        assert kwargs == {"upload_time": "14:00"}

    async def test_not_found_404(self) -> None:
        admin = MagicMock()
        admin.update_channel = AsyncMock(side_effect=NotFoundError("youtube_channel", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_channel(
                uuid4(),
                YouTubeChannelUpdate(upload_time="x"),
                admin=admin,
            )
        assert exc.value.status_code == 404
