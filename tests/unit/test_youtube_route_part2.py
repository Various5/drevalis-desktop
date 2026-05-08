"""Tests for ``api/routes/youtube/_monolith.py`` — second half:
playlists, analytics, video deletion.

Pin:

* `delete_video`: TokenRefreshError → 401 with structured detail
  + reconnect hint; NotFoundError on channel → 404.
* `create_playlist`: NoChannelConnectedError → 400, NotFound → 404,
  Ambiguous → 400 (channel_id_required), TokenRefresh → 401,
  upstream failure → 502.
* `add_video_to_playlist` / `delete_playlist`: NotFound → 404,
  TokenRefresh → 401, upstream failure → 502.
* `get_video_analytics`: empty `video_ids` → 422; >50 → 422; demo
  mode returns deterministic fake stats; upstream failure → 502
  with the structured `youtube_analytics_failed` detail and
  reconnect/quota hint.
* `upload_episode` demo-mode short-circuit returns the synthetic
  `demo_<uuid_prefix>` video_id without invoking the YouTube
  service.
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
    add_video_to_playlist,
    create_playlist,
    delete_playlist,
    delete_video,
    get_video_analytics,
    list_playlists,
    list_uploads,
    upload_episode,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.youtube import (
    PlaylistAddVideo,
    PlaylistCreate,
    YouTubeUploadRequest,
)
from drevalis.services.youtube_admin import (
    MultipleChannelsAmbiguousError,
    NoChannelConnectedError,
    TokenRefreshError,
)


def _settings(demo: bool = False) -> Any:
    s = MagicMock()
    s.demo_mode = demo
    return s


def _make_channel(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "channel_id": "UC_test123",
        "channel_name": "Drevalis",
        "is_active": True,
        "upload_days": None,
        "upload_time": None,
        "access_token_encrypted": "enc-access",
        "refresh_token_encrypted": "enc-refresh",
        "token_expiry": datetime(2030, 1, 1),
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_playlist(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "channel_id": uuid4(),
        "youtube_playlist_id": "PL_yt_abc",
        "title": "My Playlist",
        "description": None,
        "privacy_status": "public",
        "item_count": 0,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_upload(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "episode_id": uuid4(),
        "channel_id": uuid4(),
        "youtube_video_id": None,
        "youtube_url": None,
        "title": "Hook A",
        "description": "",
        "privacy_status": "private",
        "upload_status": "pending",
        "error_message": None,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── DELETE /videos/{youtube_video_id} ──────────────────────────────


class TestDeleteVideo:
    async def test_success(self) -> None:
        admin = MagicMock()
        ch = _make_channel()
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock()

        yt = MagicMock()
        yt.delete_video = AsyncMock()
        db = AsyncMock()
        db.commit = AsyncMock()
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await delete_video(
                youtube_video_id="abc123",
                channel_id=uuid4(),
                db=db,
                settings=_settings(),
                admin=admin,
            )
        assert "abc123" in out["message"]
        db.commit.assert_awaited_once()

    async def test_channel_not_found_404(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NotFoundError("youtube_channel", uuid4()))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await delete_video(
                    youtube_video_id="abc",
                    channel_id=uuid4(),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 404

    async def test_token_refresh_401_with_reconnect_hint(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(return_value=_make_channel())
        admin.refresh_and_persist_tokens = AsyncMock(
            side_effect=TokenRefreshError("refresh failed: invalid_grant")
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await delete_video(
                    youtube_video_id="abc",
                    channel_id=uuid4(),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 401
        assert exc.value.detail["error"] == "youtube_token_expired"
        assert "Reconnect" in exc.value.detail["hint"]


# ── POST /playlists ────────────────────────────────────────────────


class TestCreatePlaylist:
    async def test_success(self) -> None:
        admin = MagicMock()
        ch = _make_channel()
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock()
        admin.create_playlist_row = AsyncMock(return_value=_make_playlist())

        yt = MagicMock()
        yt.create_playlist = AsyncMock(
            return_value={
                "playlist_id": "PL_yt_abc",
                "title": "My Playlist",
                "description": None,
                "privacy_status": "public",
                "item_count": 0,
            }
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await create_playlist(
                payload=PlaylistCreate(title="My Playlist"),
                channel_id=None,
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        assert out.title == "My Playlist"

    async def test_no_channel_400(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NoChannelConnectedError())
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_playlist(
                    payload=PlaylistCreate(title="X"),
                    channel_id=None,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 400

    async def test_channel_not_found_404(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NotFoundError("youtube_channel", uuid4()))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_playlist(
                    payload=PlaylistCreate(title="X"),
                    channel_id=uuid4(),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 404

    async def test_ambiguous_400(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(
            side_effect=MultipleChannelsAmbiguousError(channels=[_make_channel(), _make_channel()])
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_playlist(
                    payload=PlaylistCreate(title="X"),
                    channel_id=None,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "channel_id_required"

    async def test_token_refresh_401(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(return_value=_make_channel())
        admin.refresh_and_persist_tokens = AsyncMock(side_effect=TokenRefreshError("expired"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_playlist(
                    payload=PlaylistCreate(title="X"),
                    channel_id=None,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 401

    async def test_upstream_failure_502(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(return_value=_make_channel())
        admin.refresh_and_persist_tokens = AsyncMock()
        yt = MagicMock()
        yt.create_playlist = AsyncMock(side_effect=ConnectionError("api down"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_playlist(
                    payload=PlaylistCreate(title="X"),
                    channel_id=None,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 502


# ── GET /playlists ─────────────────────────────────────────────────


class TestListPlaylists:
    async def test_success(self) -> None:
        admin = MagicMock()
        ch = _make_channel()
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.list_playlists_for_channel = AsyncMock(
            return_value=[_make_playlist(), _make_playlist()]
        )
        out = await list_playlists(channel_id=None, admin=admin)
        assert len(out) == 2

    async def test_no_channel_400(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NoChannelConnectedError())
        with pytest.raises(HTTPException) as exc:
            await list_playlists(channel_id=None, admin=admin)
        assert exc.value.status_code == 400

    async def test_channel_not_found_404(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NotFoundError("youtube_channel", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await list_playlists(channel_id=uuid4(), admin=admin)
        assert exc.value.status_code == 404

    async def test_ambiguous_400(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(
            side_effect=MultipleChannelsAmbiguousError(channels=[_make_channel()])
        )
        with pytest.raises(HTTPException) as exc:
            await list_playlists(channel_id=None, admin=admin)
        assert exc.value.status_code == 400


# ── POST /playlists/{id}/add ───────────────────────────────────────


class TestAddVideoToPlaylist:
    async def test_success_increments_count(self) -> None:
        admin = MagicMock()
        pl = _make_playlist()
        ch = _make_channel()
        admin.get_playlist_with_channel = AsyncMock(return_value=(pl, ch))
        admin.refresh_and_persist_tokens = AsyncMock()
        admin.increment_playlist_item_count = AsyncMock()
        yt = MagicMock()
        yt.add_to_playlist = AsyncMock(return_value={"id": "item-1"})
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await add_video_to_playlist(
                playlist_id=pl.id,
                payload=PlaylistAddVideo(video_id="vid-1"),
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        assert out["playlist_item_id"] == "item-1"
        admin.increment_playlist_item_count.assert_awaited_once()

    async def test_playlist_not_found_404(self) -> None:
        admin = MagicMock()
        admin.get_playlist_with_channel = AsyncMock(side_effect=NotFoundError("playlist", uuid4()))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await add_video_to_playlist(
                    playlist_id=uuid4(),
                    payload=PlaylistAddVideo(video_id="x"),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 404

    async def test_token_refresh_401(self) -> None:
        admin = MagicMock()
        admin.get_playlist_with_channel = AsyncMock(
            return_value=(_make_playlist(), _make_channel())
        )
        admin.refresh_and_persist_tokens = AsyncMock(side_effect=TokenRefreshError("expired"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await add_video_to_playlist(
                    playlist_id=uuid4(),
                    payload=PlaylistAddVideo(video_id="x"),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 401

    async def test_upstream_failure_502(self) -> None:
        admin = MagicMock()
        admin.get_playlist_with_channel = AsyncMock(
            return_value=(_make_playlist(), _make_channel())
        )
        admin.refresh_and_persist_tokens = AsyncMock()
        yt = MagicMock()
        yt.add_to_playlist = AsyncMock(side_effect=ConnectionError("down"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await add_video_to_playlist(
                    playlist_id=uuid4(),
                    payload=PlaylistAddVideo(video_id="x"),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 502


# ── DELETE /playlists/{id} ─────────────────────────────────────────


class TestDeletePlaylist:
    async def test_success_removes_local_row(self) -> None:
        admin = MagicMock()
        pl = _make_playlist(title="Old Show")
        ch = _make_channel()
        admin.get_playlist_with_channel = AsyncMock(return_value=(pl, ch))
        admin.refresh_and_persist_tokens = AsyncMock()
        admin.delete_playlist_row = AsyncMock()
        yt = MagicMock()
        yt.delete_playlist = AsyncMock()
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await delete_playlist(
                playlist_id=pl.id,
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        assert "Old Show" in out["message"]
        admin.delete_playlist_row.assert_awaited_once_with(pl.id)

    async def test_not_found_404(self) -> None:
        admin = MagicMock()
        admin.get_playlist_with_channel = AsyncMock(side_effect=NotFoundError("playlist", uuid4()))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await delete_playlist(
                    playlist_id=uuid4(),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 404

    async def test_token_refresh_401(self) -> None:
        admin = MagicMock()
        admin.get_playlist_with_channel = AsyncMock(
            return_value=(_make_playlist(), _make_channel())
        )
        admin.refresh_and_persist_tokens = AsyncMock(side_effect=TokenRefreshError("expired"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await delete_playlist(
                    playlist_id=uuid4(),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 401

    async def test_upstream_failure_502(self) -> None:
        admin = MagicMock()
        admin.get_playlist_with_channel = AsyncMock(
            return_value=(_make_playlist(), _make_channel())
        )
        admin.refresh_and_persist_tokens = AsyncMock()
        yt = MagicMock()
        yt.delete_playlist = AsyncMock(side_effect=ConnectionError("down"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await delete_playlist(
                    playlist_id=uuid4(),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 502


# ── GET /uploads ───────────────────────────────────────────────────


class TestListUploads:
    async def test_returns_responses(self) -> None:
        admin = MagicMock()
        admin.list_uploads = AsyncMock(return_value=[_make_upload()])
        out = await list_uploads(limit=50, admin=admin)
        assert len(out) == 1


# ── GET /analytics ─────────────────────────────────────────────────


class TestVideoAnalytics:
    async def test_demo_mode_returns_synthetic_stats(self) -> None:
        admin = MagicMock()
        out = await get_video_analytics(
            video_ids="abc,def",
            channel_id=None,
            db=AsyncMock(),
            settings=_settings(demo=True),
            admin=admin,
        )
        assert len(out) == 2
        assert out[0].video_id == "abc"
        assert out[0].views > 0  # randint(1200, 58000)

    async def test_demo_mode_caps_at_50(self) -> None:
        # Pin: even in demo mode, the cap is enforced.
        ids = ",".join(f"v{i}" for i in range(60))
        out = await get_video_analytics(
            video_ids=ids,
            channel_id=None,
            db=AsyncMock(),
            settings=_settings(demo=True),
            admin=MagicMock(),
        )
        assert len(out) == 50

    async def test_no_channel_400(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NoChannelConnectedError())
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_video_analytics(
                    video_ids="abc",
                    channel_id=None,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 400

    async def test_channel_not_found_404(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NotFoundError("youtube_channel", uuid4()))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_video_analytics(
                    video_ids="abc",
                    channel_id=uuid4(),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 404

    async def test_ambiguous_400(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(
            side_effect=MultipleChannelsAmbiguousError(channels=[_make_channel()])
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_video_analytics(
                    video_ids="abc",
                    channel_id=None,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 400

    async def test_empty_ids_422(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(return_value=_make_channel())
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_video_analytics(
                    video_ids="",
                    channel_id=None,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 422

    async def test_too_many_ids_422(self) -> None:
        # The route now chunks internally and accepts up to 5000 IDs.
        # A request with > 5000 IDs must still be rejected with 422.
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(return_value=_make_channel())
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_video_analytics(
                    video_ids=",".join(f"v{i}" for i in range(5001)),
                    channel_id=None,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 422

    async def test_upstream_failure_returns_structured_502(self) -> None:
        # Pin: the 502 detail includes the structured fields the UI
        # uses to decide whether to surface "reconnect" vs "wait for
        # quota reset" hints.
        admin = MagicMock()
        ch = _make_channel()
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock()
        yt = MagicMock()
        yt.get_video_stats = AsyncMock(side_effect=ConnectionError("down"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_video_analytics(
                    video_ids="abc,def",
                    channel_id=None,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 502
        assert exc.value.detail["error"] == "youtube_analytics_failed"
        assert exc.value.detail["channel_id"] == str(ch.id)
        # The hint mentions both reconnect AND quota — UI picks based
        # on the upstream `reason` text.
        assert "reconnect" in exc.value.detail["hint"].lower()
        assert "quota" in exc.value.detail["hint"].lower()

    async def test_success_passes_ids_and_returns_response_models(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(return_value=_make_channel())
        admin.refresh_and_persist_tokens = AsyncMock()
        yt = MagicMock()
        yt.get_video_stats = AsyncMock(
            return_value=[
                {
                    "video_id": "abc",
                    "title": "Hook A",
                    "views": 100,
                    "likes": 10,
                    "comments": 1,
                    "published_at": None,
                }
            ]
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await get_video_analytics(
                video_ids="abc,, def ",  # commas + whitespace handled
                channel_id=None,
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        assert len(out) == 1
        # Pin: stripped + empty-dropped → both abc and def reach the
        # service, even though the input has empty / whitespace tokens.
        called_ids = yt.get_video_stats.call_args.kwargs["video_ids"]
        assert called_ids == ["abc", "def"]


# ── POST /upload/{episode_id} (demo-mode short-circuit only) ───────


class TestUploadEpisodeDemoMode:
    async def test_demo_mode_short_circuits_yt_service(self) -> None:
        # Pin: in demo mode, the upload route does NOT invoke the
        # YouTube service or the admin orchestrator — it returns a
        # deterministic synthetic response so the UI's "upload"
        # button works in the public demo install.
        admin = MagicMock()
        # Asserting via attribute access: any call would be a MagicMock
        # call, but admin should never be touched at all.
        admin.resolve_episode_upload_target = AsyncMock(
            side_effect=AssertionError("admin must not be touched in demo mode")
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(side_effect=AssertionError("yt service must not be built")),
        ):
            ep_id = uuid4()
            out = await upload_episode(
                episode_id=ep_id,
                payload=YouTubeUploadRequest(title="My Demo"),
                db=AsyncMock(),
                settings=_settings(demo=True),
                admin=admin,
            )
        assert out.youtube_video_id is not None
        assert out.youtube_video_id.startswith("demo_")
        assert ep_id.hex[:11] in out.youtube_video_id
        assert out.upload_status == "done"

    async def test_real_upload_404_when_episode_missing(self) -> None:
        # Pin: NOT in demo mode → resolve_episode_upload_target's
        # NotFoundError → 404.
        admin = MagicMock()
        admin.resolve_episode_upload_target = AsyncMock(
            side_effect=NotFoundError("episode", uuid4())
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await upload_episode(
                    episode_id=uuid4(),
                    payload=YouTubeUploadRequest(title="X"),
                    db=AsyncMock(),
                    settings=_settings(demo=False),
                    admin=admin,
                )
        assert exc.value.status_code == 404

    async def test_real_upload_validation_400(self) -> None:
        admin = MagicMock()
        admin.resolve_episode_upload_target = AsyncMock(
            side_effect=ValidationError("episode not exported yet")
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await upload_episode(
                    episode_id=uuid4(),
                    payload=YouTubeUploadRequest(title="X"),
                    db=AsyncMock(),
                    settings=_settings(demo=False),
                    admin=admin,
                )
        assert exc.value.status_code == 400
