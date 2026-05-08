"""Tests for ``api/routes/youtube/_monolith.py`` — third part:
upload_episode happy path, channel analytics, channel scopes.

Pin:

* `upload_episode` happy path: SEO + script-fallback merging,
  thumbnail path lookup, refresh-tokens, upload, success recording,
  auto-add to series playlist all wired in the right order.
* SEO precedence: payload.title > seo.title > episode.title;
  payload.description > seo.description > script-derived;
  hashtags from seo merged into description (skipped if already
  present); script fallback fires only when SEO + payload empty.
* `upload_episode` failure path: upload_video raises → upload row
  marked failed + 502 raised + auto_add_to_series_playlist NOT
  called.
* `get_channel_analytics`: demo mode returns deterministic synthetic
  data with daily breakdown matching the requested window;
  AnalyticsNotAuthorized → 403 with structured
  `analytics_scope_missing` hint pointing the user at reconnect;
  upstream failure → 502.
* `get_channel_scopes`: missing access_token_encrypted → returns
  scope-introspection-failed payload (no decrypt attempted);
  decrypt failure also surfaces introspection-failed; success
  flags `has_analytics_scope` / `has_upload_scope` and emits
  reconnect hint when analytics scope is missing but token works.
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
    get_channel_analytics,
    get_channel_scopes,
    upload_episode,
)
from drevalis.core.exceptions import NotFoundError
from drevalis.schemas.youtube import YouTubeUploadRequest
from drevalis.services.youtube import AnalyticsNotAuthorized, YouTubeService
from drevalis.services.youtube_admin import (
    MultipleChannelsAmbiguousError,
    NoChannelConnectedError,
    TokenRefreshError,
)


def _settings(demo: bool = False) -> Any:
    s = MagicMock()
    s.demo_mode = demo
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    return s


def _make_channel(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "channel_id": "UC_test123",
        "channel_name": "Drevalis",
        "is_active": True,
        "access_token_encrypted": "enc-access",
        "refresh_token_encrypted": "enc-refresh",
        "token_expiry": datetime(2030, 1, 1),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_episode(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "title": "Hook A",
        "topic": "intro",
        "script": None,
        "metadata_": None,
        "content_format": "shorts",
        "series_id": uuid4(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_upload_row(**overrides: Any) -> Any:
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


# ── upload_episode happy + failure paths ───────────────────────────


class TestUploadEpisodeHappyPath:
    async def test_seo_data_fills_description_and_tags_when_payload_empty(
        self,
    ) -> None:
        # Pin SEO precedence on description + tags (title is min_length=1
        # so always truthy and wins over SEO). Hashtags merged in with
        # `#` prefix.
        ep = _make_episode()
        ch = _make_channel()
        admin = MagicMock()
        admin.resolve_episode_upload_target = AsyncMock(return_value=(ep, ch, "/path/to/video.mp4"))
        admin.get_or_generate_seo = AsyncMock(
            return_value={
                "title": "SEO Title",
                "description": "SEO description",
                "tags": ["seo-tag-1", "seo-tag-2"],
                "hashtags": ["foo", "bar"],
            }
        )
        admin.get_thumbnail_path = AsyncMock(return_value=None)
        admin.refresh_and_persist_tokens = AsyncMock()
        admin.create_upload_row = AsyncMock(return_value=_make_upload_row())
        admin.record_upload_success = AsyncMock()
        admin.auto_add_to_series_playlist = AsyncMock()

        yt = MagicMock()
        yt.upload_video = AsyncMock(return_value={"video_id": "yt-x", "url": "https://y/x"})

        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            await upload_episode(
                episode_id=ep.id,
                # Title required (min_length=1) so user supplies a
                # placeholder; description + tags omitted → SEO fills.
                payload=YouTubeUploadRequest(title="Custom Title"),
                db=AsyncMock(),
                settings=_settings(demo=False),
                admin=admin,
            )

        kwargs = yt.upload_video.call_args.kwargs
        # Title from payload wins (truthy non-empty).
        assert kwargs["title"] == "Custom Title"
        # Description from SEO + hashtags merged.
        assert "SEO description" in kwargs["description"]
        assert "#foo" in kwargs["description"]
        assert "#bar" in kwargs["description"]
        # Tags from SEO.
        assert kwargs["tags"] == ["seo-tag-1", "seo-tag-2"]
        # Auto-playlist add fires after success recording.
        admin.auto_add_to_series_playlist.assert_awaited_once()

    async def test_payload_overrides_seo(self) -> None:
        # Pin: when the user provides explicit title/description/tags,
        # those win over SEO data.
        ep = _make_episode()
        ch = _make_channel()
        admin = MagicMock()
        admin.resolve_episode_upload_target = AsyncMock(return_value=(ep, ch, "/v.mp4"))
        admin.get_or_generate_seo = AsyncMock(
            return_value={
                "title": "SEO",
                "description": "SEO desc",
                "tags": ["seo"],
                "hashtags": [],
            }
        )
        admin.get_thumbnail_path = AsyncMock(return_value=None)
        admin.refresh_and_persist_tokens = AsyncMock()
        admin.create_upload_row = AsyncMock(return_value=_make_upload_row())
        admin.record_upload_success = AsyncMock()
        admin.auto_add_to_series_playlist = AsyncMock()
        yt = MagicMock()
        yt.upload_video = AsyncMock(return_value={"video_id": "x", "url": "https://y/x"})

        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            await upload_episode(
                episode_id=ep.id,
                payload=YouTubeUploadRequest(
                    title="My Title",
                    description="My desc",
                    tags=["mine-1", "mine-2"],
                ),
                db=AsyncMock(),
                settings=_settings(demo=False),
                admin=admin,
            )
        kwargs = yt.upload_video.call_args.kwargs
        assert kwargs["title"] == "My Title"
        assert "My desc" in kwargs["description"]
        assert kwargs["tags"] == ["mine-1", "mine-2"]

    async def test_hashtags_skipped_when_already_in_description(
        self,
    ) -> None:
        # Pin: if the user-provided description already contains the
        # hashtag string, don't append it again.
        ep = _make_episode()
        ch = _make_channel()
        admin = MagicMock()
        admin.resolve_episode_upload_target = AsyncMock(return_value=(ep, ch, "/v.mp4"))
        admin.get_or_generate_seo = AsyncMock(return_value={"hashtags": ["foo", "bar"]})
        admin.get_thumbnail_path = AsyncMock(return_value=None)
        admin.refresh_and_persist_tokens = AsyncMock()
        admin.create_upload_row = AsyncMock(return_value=_make_upload_row())
        admin.record_upload_success = AsyncMock()
        admin.auto_add_to_series_playlist = AsyncMock()
        yt = MagicMock()
        yt.upload_video = AsyncMock(return_value={"video_id": "x", "url": "https://y/x"})

        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            await upload_episode(
                episode_id=ep.id,
                payload=YouTubeUploadRequest(
                    title="My",
                    description="My desc — see #foo #bar already here",
                ),
                db=AsyncMock(),
                settings=_settings(demo=False),
                admin=admin,
            )
        kwargs = yt.upload_video.call_args.kwargs
        # No double-append: only ONE occurrence of "#foo #bar".
        assert kwargs["description"].count("#foo #bar") == 1

    async def test_script_fallback_fills_description_when_seo_empty(
        self,
    ) -> None:
        # Pin (post-Phase-2.3 resolution chain): SEO empty + payload
        # description empty → script.description wins on its own
        # (clean copy is the primary deliverable now), with hashtags
        # appended on a trailing line. The pre-overhaul chain joined
        # script.title + description + hashtags; we no longer do that
        # because the script's description is already a vetted
        # standalone blurb.
        ep = _make_episode(
            script={
                "title": "Script Title",
                "description": "Script desc",
                "hashtags": ["a", "b"],
            }
        )
        ch = _make_channel()
        admin = MagicMock()
        admin.resolve_episode_upload_target = AsyncMock(return_value=(ep, ch, "/v.mp4"))
        admin.get_or_generate_seo = AsyncMock(return_value={})
        admin.get_thumbnail_path = AsyncMock(return_value=None)
        admin.refresh_and_persist_tokens = AsyncMock()
        admin.create_upload_row = AsyncMock(return_value=_make_upload_row())
        admin.record_upload_success = AsyncMock()
        admin.auto_add_to_series_playlist = AsyncMock()
        yt = MagicMock()
        yt.upload_video = AsyncMock(return_value={"video_id": "x", "url": "https://y/x"})
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            await upload_episode(
                episode_id=ep.id,
                payload=YouTubeUploadRequest(title="Placeholder"),
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        kwargs = yt.upload_video.call_args.kwargs
        # script.description wins; hashtags get appended on a blank line.
        assert "Script desc" in kwargs["description"]
        assert "#a" in kwargs["description"]
        assert "#b" in kwargs["description"]
        # Tags also derived from script hashtags (with '#' stripped).
        assert kwargs["tags"] == ["a", "b"]

    async def test_token_refresh_401(self) -> None:
        ep = _make_episode()
        ch = _make_channel()
        admin = MagicMock()
        admin.resolve_episode_upload_target = AsyncMock(return_value=(ep, ch, "/v.mp4"))
        admin.get_or_generate_seo = AsyncMock(return_value={})
        admin.get_thumbnail_path = AsyncMock(return_value=None)
        admin.refresh_and_persist_tokens = AsyncMock(side_effect=TokenRefreshError("expired"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await upload_episode(
                    episode_id=ep.id,
                    payload=YouTubeUploadRequest(title="x"),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 401
        assert exc.value.detail["error"] == "youtube_token_expired"

    async def test_upload_failure_marks_row_failed_and_skips_playlist(
        self,
    ) -> None:
        # Critical pin: when yt.upload_video raises, the route MUST:
        # 1. Mark the upload row failed (record_upload_failure).
        # 2. Raise 502.
        # 3. NOT call auto_add_to_series_playlist (no video to add).
        ep = _make_episode()
        ch = _make_channel()
        admin = MagicMock()
        admin.resolve_episode_upload_target = AsyncMock(return_value=(ep, ch, "/v.mp4"))
        admin.get_or_generate_seo = AsyncMock(return_value={})
        admin.get_thumbnail_path = AsyncMock(return_value=None)
        admin.refresh_and_persist_tokens = AsyncMock()
        admin.create_upload_row = AsyncMock(return_value=_make_upload_row())
        admin.record_upload_failure = AsyncMock()
        admin.auto_add_to_series_playlist = AsyncMock()
        admin.record_upload_success = AsyncMock()

        yt = MagicMock()
        yt.upload_video = AsyncMock(side_effect=ConnectionError("yt down"))

        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await upload_episode(
                    episode_id=ep.id,
                    payload=YouTubeUploadRequest(title="x"),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 502
        admin.record_upload_failure.assert_awaited_once()
        admin.record_upload_success.assert_not_awaited()
        admin.auto_add_to_series_playlist.assert_not_awaited()


# ── GET /analytics/channel ─────────────────────────────────────────


class TestChannelAnalytics:
    async def test_demo_mode_returns_synthetic_window(self) -> None:
        admin = MagicMock()
        out = await get_channel_analytics(
            channel_id=None,
            days=14,
            db=AsyncMock(),
            settings=_settings(demo=True),
            admin=admin,
        )
        assert out["window_days"] == 14
        assert len(out["daily"]) == 14
        # totals.views == sum of daily views.
        assert out["totals"]["views"] == sum(d["views"] for d in out["daily"])
        # All required totals fields populated.
        for key in ("views", "minutes_watched", "subscribers_gained", "likes"):
            assert key in out["totals"]

    async def test_no_channel_400(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NoChannelConnectedError())
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_channel_analytics(
                    channel_id=None,
                    days=28,
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
                await get_channel_analytics(
                    channel_id=uuid4(),
                    days=28,
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
                await get_channel_analytics(
                    channel_id=None,
                    days=28,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 400

    async def test_token_refresh_401(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(return_value=_make_channel())
        admin.refresh_and_persist_tokens = AsyncMock(side_effect=TokenRefreshError("expired"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_channel_analytics(
                    channel_id=None,
                    days=28,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 401

    async def test_analytics_not_authorized_403_with_hint(self) -> None:
        # Pin: AnalyticsNotAuthorized → 403 with structured hint
        # pointing the user at scope reconnect.
        admin = MagicMock()
        ch = _make_channel()
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock()
        yt = MagicMock()
        yt.get_channel_analytics = AsyncMock(side_effect=AnalyticsNotAuthorized("scope missing"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_channel_analytics(
                    channel_id=None,
                    days=28,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 403
        assert exc.value.detail["error"] == "analytics_scope_missing"
        assert exc.value.detail["channel_id"] == str(ch.id)

    async def test_upstream_failure_502(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(return_value=_make_channel())
        admin.refresh_and_persist_tokens = AsyncMock()
        yt = MagicMock()
        yt.get_channel_analytics = AsyncMock(side_effect=ConnectionError("down"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_channel_analytics(
                    channel_id=None,
                    days=28,
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 502

    async def test_success_attaches_channel_id_to_response(self) -> None:
        admin = MagicMock()
        ch = _make_channel()
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock()
        yt = MagicMock()
        yt.get_channel_analytics = AsyncMock(
            return_value={"window_days": 28, "totals": {"views": 1000}}
        )
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await get_channel_analytics(
                channel_id=None,
                days=28,
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        assert out["channel_id"] == str(ch.id)
        assert out["totals"] == {"views": 1000}


# ── GET /channels/{id}/scopes ──────────────────────────────────────


class TestChannelScopes:
    async def test_no_channel_400(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NoChannelConnectedError())
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_channel_scopes(
                    channel_id=uuid4(),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 400

    async def test_not_found_404(self) -> None:
        admin = MagicMock()
        admin.resolve_channel = AsyncMock(side_effect=NotFoundError("youtube_channel", uuid4()))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_channel_scopes(
                    channel_id=uuid4(),
                    db=AsyncMock(),
                    settings=_settings(),
                    admin=admin,
                )
        assert exc.value.status_code == 404

    async def test_token_refresh_failure_swallowed_then_no_token(self) -> None:
        # Pin: TokenRefreshError is logged-and-swallowed; flow falls
        # through to "no access token" branch returning the
        # introspection-failed payload.
        admin = MagicMock()
        ch = _make_channel(access_token_encrypted=None)
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock(side_effect=TokenRefreshError("expired"))
        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            out = await get_channel_scopes(
                channel_id=ch.id,
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        assert out["token_introspection_failed"] is True
        assert out["scopes"] == []
        assert out["has_analytics_scope"] is False
        assert "reconnected" in out["hint"]

    async def test_decrypt_failure_returns_introspection_failed(self) -> None:
        admin = MagicMock()
        ch = _make_channel(access_token_encrypted="enc-bad")
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock()

        # Route calls ``settings.decrypt(ct)`` (multi-version aware).
        # Configure it to raise so the introspection-failed branch fires.
        s = _settings()
        s.decrypt = MagicMock(side_effect=ValueError("decrypt failed"))

        with patch(
            "drevalis.api.routes.youtube._monolith.build_youtube_service",
            AsyncMock(return_value=MagicMock()),
        ):
            out = await get_channel_scopes(
                channel_id=ch.id,
                db=AsyncMock(),
                settings=s,
                admin=admin,
            )
        assert out["token_introspection_failed"] is True
        assert "couldn't be decrypted" in out["hint"]

    async def test_success_with_full_scopes(self) -> None:
        # Pin: when both expected scopes are present, hint is None
        # and both flags are True.
        admin = MagicMock()
        ch = _make_channel()
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock()
        full_scopes = [
            "https://www.googleapis.com/auth/yt-analytics.readonly",
            "https://www.googleapis.com/auth/youtube.upload",
        ]
        with (
            patch(
                "drevalis.api.routes.youtube._monolith.build_youtube_service",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "drevalis.core.security.decrypt_value",
                return_value="decrypted-token",
            ),
            patch(
                "drevalis.api.routes.youtube._monolith.fetch_token_scopes",
                AsyncMock(return_value=full_scopes),
            ),
        ):
            out = await get_channel_scopes(
                channel_id=ch.id,
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        assert out["has_analytics_scope"] is True
        assert out["has_upload_scope"] is True
        assert out["hint"] is None
        assert out["token_introspection_failed"] is False
        assert out["expected_scopes"] == YouTubeService.SCOPES

    async def test_success_with_missing_analytics_scope_emits_hint(
        self,
    ) -> None:
        admin = MagicMock()
        ch = _make_channel()
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock()
        upload_only = ["https://www.googleapis.com/auth/youtube.upload"]
        with (
            patch(
                "drevalis.api.routes.youtube._monolith.build_youtube_service",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "drevalis.core.security.decrypt_value",
                return_value="decrypted",
            ),
            patch(
                "drevalis.api.routes.youtube._monolith.fetch_token_scopes",
                AsyncMock(return_value=upload_only),
            ),
        ):
            out = await get_channel_scopes(
                channel_id=ch.id,
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        assert out["has_analytics_scope"] is False
        assert out["has_upload_scope"] is True
        assert out["hint"] is not None
        assert "Reconnect" in out["hint"]

    async def test_empty_scopes_introspection_failed_flag(self) -> None:
        # Pin: when fetch_token_scopes returns [] (Google rejected the
        # token), token_introspection_failed flag is True.
        admin = MagicMock()
        ch = _make_channel()
        admin.resolve_channel = AsyncMock(return_value=ch)
        admin.refresh_and_persist_tokens = AsyncMock()
        with (
            patch(
                "drevalis.api.routes.youtube._monolith.build_youtube_service",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "drevalis.core.security.decrypt_value",
                return_value="decrypted",
            ),
            patch(
                "drevalis.api.routes.youtube._monolith.fetch_token_scopes",
                AsyncMock(return_value=[]),
            ),
        ):
            out = await get_channel_scopes(
                channel_id=ch.id,
                db=AsyncMock(),
                settings=_settings(),
                admin=admin,
            )
        assert out["token_introspection_failed"] is True
        # Hint stays None (we don't know whether scopes are missing or
        # token is dead — the flag tells us it's introspection failure).
        assert out["hint"] is None
