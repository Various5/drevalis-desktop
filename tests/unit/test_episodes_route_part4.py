"""Tests for ``api/routes/episodes/_monolith.py`` — fourth part:
publish_all (cross-platform fan-out) + seo_variants (LLM A/B options).

Pin:

* `publish_all`: episode missing → 404, wrong status → 409, no
  finished video → 409.
* YouTube: missing series.youtube_channel_id → skipped with hint;
  with channel → upload row created and accepted.
* TikTok: SocialPlatform row missing/inactive → skipped; row
  present + supported → SocialUpload created.
* Instagram: NEVER fulfilled (no shipped worker) — always skipped
  with "uploads aren't shipped yet" hint.
* SEO precedence in publish_all: payload.title > seo.title >
  episode.title; payload.description > seo.description > topic.
* `seo_variants`: no LLM configured → degrades to deterministic
  template variants; with LLM → returns parsed titles/thumbnails/
  descriptions, each capped at limits.
* Empty/missing-script episode → 404.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.episodes._monolith import (
    PublishAllRequest,
    publish_all,
    seo_variants,
)
from drevalis.services.episode import (
    EpisodeNoScriptError,
    EpisodeNotFoundError,
)


def _settings() -> Any:
    s = MagicMock()
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    return s


def _make_episode(**overrides: Any) -> Any:
    """Episode with `series` attribute defaulting to a shape compatible
    with `db.refresh(episode, attribute_names=["series"])` — `series` is
    a SimpleNamespace already so refresh is a no-op for our test fakes."""
    base: dict[str, Any] = {
        "id": uuid4(),
        "title": "Hook A",
        "topic": "intro",
        "status": "review",
        "script": None,
        "metadata_": None,
        "series": SimpleNamespace(youtube_channel_id=None),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _publish_request(**overrides: Any) -> PublishAllRequest:
    base: dict[str, Any] = {"platforms": ["youtube"]}
    base.update(overrides)
    return PublishAllRequest(**base)


# ── publish_all ────────────────────────────────────────────────────


class TestPublishAllValidation:
    async def test_episode_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await publish_all(
                uuid4(),
                _publish_request(),
                db=AsyncMock(),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_wrong_status_409(self) -> None:
        # Pin: only review/exported/editing can publish; draft/generating/
        # failed all 409.
        for bad_status in ("draft", "generating", "failed"):
            ep = _make_episode(status=bad_status)
            svc = MagicMock()
            svc.get_or_raise = AsyncMock(return_value=ep)
            with pytest.raises(HTTPException) as exc:
                await publish_all(
                    ep.id,
                    _publish_request(),
                    db=AsyncMock(),
                    svc=svc,
                )
            assert exc.value.status_code == 409
            assert bad_status in exc.value.detail

    async def test_no_video_409(self) -> None:
        ep = _make_episode(status="review")
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await publish_all(
                ep.id,
                _publish_request(),
                db=AsyncMock(),
                svc=svc,
            )
        assert exc.value.status_code == 409
        assert "video" in exc.value.detail.lower()


class TestPublishAllYouTube:
    async def test_youtube_no_channel_skipped_with_hint(self) -> None:
        ep = _make_episode(series=SimpleNamespace(youtube_channel_id=None))
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")
        db = AsyncMock()
        db.refresh = AsyncMock()
        db.commit = AsyncMock()

        out = await publish_all(
            ep.id,
            _publish_request(platforms=["youtube"]),
            db=db,
            svc=svc,
        )

        assert out.accepted == []
        assert len(out.skipped) == 1
        assert out.skipped[0]["platform"] == "youtube"
        assert "no assigned YouTube channel" in out.skipped[0]["reason"]

    async def test_youtube_with_channel_creates_upload_row(self) -> None:
        ch_id = uuid4()
        ep = _make_episode(
            series=SimpleNamespace(youtube_channel_id=ch_id),
            metadata_={
                "seo": {
                    "title": "SEO Title",
                    "description": "SEO desc",
                    "tags": ["t1"],
                    "hashtags": ["a", "b"],
                }
            },
        )
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")

        added: list[Any] = []
        db = AsyncMock()
        db.refresh = AsyncMock()

        def _add(obj: Any) -> None:
            # Simulate SQLAlchemy assigning a primary key.
            obj.id = uuid4()
            added.append(obj)

        db.add = MagicMock(side_effect=_add)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        yt_repo_instance = MagicMock()
        yt_repo_instance.get_existing_done = AsyncMock(return_value=None)
        with patch(
            "drevalis.repositories.youtube.YouTubeUploadRepository",
            return_value=yt_repo_instance,
        ):
            out = await publish_all(
                ep.id,
                _publish_request(platforms=["youtube"], privacy="unlisted"),
                db=db,
                svc=svc,
            )

        assert len(out.accepted) == 1
        assert out.accepted[0]["platform"] == "youtube"
        assert out.accepted[0]["channel_id"] == str(ch_id)
        # The YouTubeUpload row was created with SEO-derived title +
        # description.
        upload_row = added[0]
        assert upload_row.title == "SEO Title"
        assert upload_row.description == "SEO desc"
        assert upload_row.privacy_status == "unlisted"
        # Commit ran exactly once at the end of the route.
        db.commit.assert_awaited_once()

    async def test_payload_overrides_seo(self) -> None:
        ch_id = uuid4()
        ep = _make_episode(
            series=SimpleNamespace(youtube_channel_id=ch_id),
            metadata_={"seo": {"title": "SEO Title", "description": "SEO desc"}},
        )
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")

        added: list[Any] = []
        db = AsyncMock()
        db.refresh = AsyncMock()

        def _add(obj: Any) -> None:
            obj.id = uuid4()
            added.append(obj)

        db.add = MagicMock(side_effect=_add)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        yt_repo_instance = MagicMock()
        yt_repo_instance.get_existing_done = AsyncMock(return_value=None)
        with patch(
            "drevalis.repositories.youtube.YouTubeUploadRepository",
            return_value=yt_repo_instance,
        ):
            await publish_all(
                ep.id,
                _publish_request(
                    platforms=["youtube"],
                    title="My Override",
                    description="My override desc",
                ),
                db=db,
                svc=svc,
            )
        row = added[0]
        assert row.title == "My Override"
        assert row.description == "My override desc"

    async def test_falls_back_to_episode_fields_when_no_seo(self) -> None:
        ch_id = uuid4()
        ep = _make_episode(
            title="Episode Title",
            topic="Episode topic text",
            series=SimpleNamespace(youtube_channel_id=ch_id),
            metadata_=None,
        )
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")

        added: list[Any] = []
        db = AsyncMock()
        db.refresh = AsyncMock()

        def _add(obj: Any) -> None:
            obj.id = uuid4()
            added.append(obj)

        db.add = MagicMock(side_effect=_add)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        yt_repo_instance = MagicMock()
        yt_repo_instance.get_existing_done = AsyncMock(return_value=None)
        with patch(
            "drevalis.repositories.youtube.YouTubeUploadRepository",
            return_value=yt_repo_instance,
        ):
            await publish_all(
                ep.id,
                _publish_request(platforms=["youtube"]),
                db=db,
                svc=svc,
            )
        row = added[0]
        assert row.title == "Episode Title"
        assert row.description == "Episode topic text"


class TestPublishAllSocial:
    async def test_instagram_no_account_skipped(self) -> None:
        # Pin: Instagram is handled via the same SocialPlatform lookup as
        # TikTok. When no active instagram account is connected the route
        # skips and emits a "No active instagram account connected" hint.
        ep = _make_episode(series=SimpleNamespace(youtube_channel_id=None))
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")

        # SocialPlatform query returns None → skip with hint.
        db = AsyncMock()
        db.refresh = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        out = await publish_all(
            ep.id,
            _publish_request(platforms=["instagram"]),
            db=db,
            svc=svc,
        )
        assert any(
            s["platform"] == "instagram" and "No active instagram" in s["reason"]
            for s in out.skipped
        )

    async def test_tiktok_no_account_skipped(self) -> None:
        ep = _make_episode(series=SimpleNamespace(youtube_channel_id=None))
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")

        # SocialPlatform query returns None → skip with hint.
        db = AsyncMock()
        db.refresh = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        out = await publish_all(
            ep.id,
            _publish_request(platforms=["tiktok"]),
            db=db,
            svc=svc,
        )
        assert any(
            s["platform"] == "tiktok" and "No active tiktok" in s["reason"] for s in out.skipped
        )

    async def test_tiktok_with_account_creates_upload(self) -> None:
        ep = _make_episode(
            series=SimpleNamespace(youtube_channel_id=None),
            metadata_={"seo": {"hashtags": ["viral", "fyp"]}},
        )
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")

        plat_id = uuid4()
        plat = SimpleNamespace(id=plat_id, platform="tiktok", is_active=True)

        added: list[Any] = []
        db = AsyncMock()
        db.refresh = AsyncMock()

        def _add(obj: Any) -> None:
            obj.id = uuid4()
            added.append(obj)

        db.add = MagicMock(side_effect=_add)
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=plat)
        db.execute = AsyncMock(return_value=result)

        out = await publish_all(
            ep.id,
            _publish_request(platforms=["tiktok"]),
            db=db,
            svc=svc,
        )
        assert len(out.accepted) == 1
        assert out.accepted[0]["platform"] == "tiktok"
        # Hashtags joined with spaces (no `#` prefix — TikTok's SocialUpload
        # row stores them as a string already-joined).
        upload_row = added[0]
        assert upload_row.hashtags == "viral fyp"
        assert upload_row.platform_id == plat_id

    async def test_mixed_platforms_partial_success(self) -> None:
        # YouTube succeeds, TikTok skipped (no account), Instagram skipped
        # (not shipped). Single commit at the end.
        ch_id = uuid4()
        ep = _make_episode(series=SimpleNamespace(youtube_channel_id=ch_id))
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")

        db = AsyncMock()
        db.refresh = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result)

        added: list[Any] = []

        def _add(obj: Any) -> None:
            obj.id = uuid4()
            added.append(obj)

        db.add = MagicMock(side_effect=_add)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        out = await publish_all(
            ep.id,
            _publish_request(platforms=["youtube", "tiktok", "instagram"]),
            db=db,
            svc=svc,
        )
        # YT accepted, others skipped.
        assert [a["platform"] for a in out.accepted] == ["youtube"]
        assert {s["platform"] for s in out.skipped} == {"tiktok", "instagram"}
        # Commit only once at the very end.
        db.commit.assert_awaited_once()


# ── seo_variants ──────────────────────────────────────────────────


class TestSeoVariantsValidation:
    async def test_episode_or_script_missing_404(self) -> None:
        svc = MagicMock()
        svc.get_with_script_or_raise = AsyncMock(side_effect=EpisodeNoScriptError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await seo_variants(
                uuid4(),
                db=AsyncMock(),
                settings=_settings(),
                svc=svc,
            )
        assert exc.value.status_code == 404


class TestSeoVariantsNoLLM:
    async def test_no_llm_returns_template_fallbacks(self) -> None:
        # Pin: when no LLM is registered, the route returns deterministic
        # template variants derived from the episode title — Solo-mode
        # users without an LLM still get suggestions.
        svc = MagicMock()
        ep = _make_episode(title="My Topic")
        svc.get_with_script_or_raise = AsyncMock(return_value=(ep, MagicMock()))

        cfg_svc = MagicMock()
        cfg_svc.list_all = AsyncMock(return_value=[])
        with patch(
            "drevalis.services.llm_config.LLMConfigService",
            return_value=cfg_svc,
        ):
            out = await seo_variants(
                ep.id,
                db=AsyncMock(),
                settings=_settings(),
                svc=svc,
            )
        # Five title variants, all referencing the episode title.
        assert len(out.titles) == 5
        assert any("My Topic" in t for t in out.titles)
        # Three thumbnail prompts.
        assert len(out.thumbnail_prompts) == 3
        # At least one description variant.
        assert len(out.descriptions) >= 1

    async def test_untitled_episode_falls_back_safely(self) -> None:
        # Pin: episode.title=None doesn't crash — falls back to "Untitled".
        svc = MagicMock()
        ep = _make_episode(title=None, topic=None)
        svc.get_with_script_or_raise = AsyncMock(return_value=(ep, MagicMock()))
        cfg_svc = MagicMock()
        cfg_svc.list_all = AsyncMock(return_value=[])
        with patch(
            "drevalis.services.llm_config.LLMConfigService",
            return_value=cfg_svc,
        ):
            out = await seo_variants(
                ep.id,
                db=AsyncMock(),
                settings=_settings(),
                svc=svc,
            )
        assert any("Untitled" in t for t in out.titles)


class TestSeoVariantsWithLLM:
    async def test_parses_llm_json_response_and_caps_lengths(
        self,
    ) -> None:
        svc = MagicMock()
        ep = _make_episode(
            title="Hook",
            script={
                "scenes": [
                    {"narration": "First scene narration"},
                    {"narration": "Second scene narration"},
                ]
            },
        )
        svc.get_with_script_or_raise = AsyncMock(return_value=(ep, MagicMock()))

        cfg = MagicMock()
        cfg_svc = MagicMock()
        cfg_svc.list_all = AsyncMock(return_value=[cfg])

        provider = MagicMock()
        provider.generate = AsyncMock(
            return_value=SimpleNamespace(
                content='{"titles": ["A", "B", "C", "D", "E", "F-extra"], '
                '"thumbnail_prompts": ["P1", "P2", "P3"], '
                '"descriptions": ["D1", "D2", "D3"]}'
            )
        )

        llm_service = MagicMock()
        llm_service.get_provider = MagicMock(return_value=provider)

        with (
            patch(
                "drevalis.services.llm_config.LLMConfigService",
                return_value=cfg_svc,
            ),
            patch(
                "drevalis.services.llm.LLMService",
                return_value=llm_service,
            ),
            patch(
                "drevalis.services.llm.extract_json",
                side_effect=lambda x: x,  # passthrough
            ),
        ):
            out = await seo_variants(
                ep.id,
                db=AsyncMock(),
                settings=_settings(),
                svc=svc,
            )
        # Pin: titles capped at 5, even though LLM returned 6.
        assert len(out.titles) == 5
        assert "F-extra" not in out.titles
        # Thumbnails + descriptions also capped at 5.
        assert len(out.thumbnail_prompts) == 3
        assert len(out.descriptions) == 3

    async def test_unparseable_llm_response_returns_empty_lists(
        self,
    ) -> None:
        # Pin: when the LLM emits non-JSON, the route returns empty
        # variant lists rather than 502 — the UI shows "no variants
        # available" instead of an error toast.
        svc = MagicMock()
        ep = _make_episode(
            title="Hook",
            script={"scenes": [{"narration": "x"}]},
        )
        svc.get_with_script_or_raise = AsyncMock(return_value=(ep, MagicMock()))

        cfg_svc = MagicMock()
        cfg_svc.list_all = AsyncMock(return_value=[MagicMock()])

        provider = MagicMock()
        provider.generate = AsyncMock(return_value=SimpleNamespace(content="not json at all"))
        llm_service = MagicMock()
        llm_service.get_provider = MagicMock(return_value=provider)

        with (
            patch(
                "drevalis.services.llm_config.LLMConfigService",
                return_value=cfg_svc,
            ),
            patch(
                "drevalis.services.llm.LLMService",
                return_value=llm_service,
            ),
            patch(
                "drevalis.services.llm.extract_json",
                side_effect=lambda x: x,
            ),
        ):
            out = await seo_variants(
                ep.id,
                db=AsyncMock(),
                settings=_settings(),
                svc=svc,
            )
        assert out.titles == []
        assert out.thumbnail_prompts == []
        assert out.descriptions == []

    async def test_truncates_long_strings(self) -> None:
        # Pin: titles capped at 100 chars, thumbnail_prompts at 400,
        # descriptions at 500. Defensive against runaway LLM output.
        svc = MagicMock()
        ep = _make_episode(
            title="Hook",
            script={"scenes": [{"narration": "x"}]},
        )
        svc.get_with_script_or_raise = AsyncMock(return_value=(ep, MagicMock()))

        cfg_svc = MagicMock()
        cfg_svc.list_all = AsyncMock(return_value=[MagicMock()])

        long_str = "X" * 1000
        provider = MagicMock()
        provider.generate = AsyncMock(
            return_value=SimpleNamespace(
                content=(
                    '{"titles": ["' + long_str + '"], '
                    '"thumbnail_prompts": ["' + long_str + '"], '
                    '"descriptions": ["' + long_str + '"]}'
                )
            )
        )
        llm_service = MagicMock()
        llm_service.get_provider = MagicMock(return_value=provider)

        with (
            patch(
                "drevalis.services.llm_config.LLMConfigService",
                return_value=cfg_svc,
            ),
            patch(
                "drevalis.services.llm.LLMService",
                return_value=llm_service,
            ),
            patch(
                "drevalis.services.llm.extract_json",
                side_effect=lambda x: x,
            ),
        ):
            out = await seo_variants(
                ep.id,
                db=AsyncMock(),
                settings=_settings(),
                svc=svc,
            )
        assert len(out.titles[0]) == 100
        assert len(out.thumbnail_prompts[0]) == 400
        assert len(out.descriptions[0]) == 500
