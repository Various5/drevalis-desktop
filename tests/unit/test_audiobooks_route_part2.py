"""Tests for ``api/routes/audiobooks/_monolith.py`` — second half:
sync script gen, music_preview, list_clips, YouTube upload, list
uploads.

Pin:

* `generate_audiobook_script_sync` parses the LLM output for title,
  chapter headers, character tags, word count; LLM failure → 502.
* `music_preview`: 404 when audiobook missing; 503 when MusicService
  returns no track.
* `list_clips`: 404 when audiobook missing; payload includes
  `overrides` from the `track_mix` field.
* YouTube upload: NotFoundError → 404, ValidationError → 404 (the
  domain error means "no video to upload"), NoChannelSelectedError
  → 400 with structured `no_channel_selected` detail; upstream
  failure → 502; success records video_id + URL.
* `list_audiobook_uploads`: 404 when audiobook missing; serialises
  datetimes via `.isoformat()`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.audiobooks._monolith import (
    AudiobookScriptRequest,
    AudiobookYouTubeUploadRequest,
    generate_audiobook_script_sync,
    list_audiobook_uploads,
    list_clips,
    music_preview,
    upload_audiobook_to_youtube,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.services.audiobook_admin import NoChannelSelectedError


def _settings(tmp_path: Path | None = None) -> Any:
    s = MagicMock()
    s.lm_studio_base_url = "http://localhost:1234/v1"
    s.lm_studio_default_model = "local-model"
    s.storage_base_path = tmp_path or Path("/tmp")
    return s


def _script_request() -> AudiobookScriptRequest:
    return AudiobookScriptRequest(
        concept="A dragon adventure tale of fire and ice",
        target_minutes=5,
        mood="epic",
    )


def _llm_result(text: str) -> Any:
    r = MagicMock()
    r.content = text
    return r


# ── POST /generate-script-sync ─────────────────────────────────────


class TestGenerateScriptSync:
    async def test_success_extracts_title_chapters_characters(self) -> None:
        # Realistic-ish LLM output. Pin: route extracts title from the
        # first line, chapters from `## ` headers, and characters from
        # `[Tag]` lines (sfx tags filtered out).
        script_text = """The Last Dragon

## Chapter 1: Awakening

[Narrator] The cave was silent.

[Bram] Hello?

[SFX: rumble] (filtered)

## Chapter 2: Flight

[Narrator] He spread his wings.
"""
        provider = MagicMock()
        provider.generate = AsyncMock(return_value=_llm_result(script_text))

        with patch(
            "drevalis.services.llm.OpenAICompatibleProvider",
            return_value=provider,
        ):
            out = await generate_audiobook_script_sync(_script_request(), settings=_settings())

        assert out.title == "The Last Dragon"
        assert out.chapters == ["Chapter 1: Awakening", "Chapter 2: Flight"]
        # `[SFX: rumble]` filtered (case-insensitive prefix `sfx`).
        assert "Narrator" in out.characters
        assert "Bram" in out.characters
        assert all(not c.lower().startswith("sfx") for c in out.characters)
        # Word count + estimated minutes derived from text.
        assert out.word_count > 0
        assert out.estimated_minutes == round(out.word_count / 150, 1)

    async def test_strips_leading_hash_from_title(self) -> None:
        provider = MagicMock()
        provider.generate = AsyncMock(
            return_value=_llm_result("# Untitled Story\n\n[Narrator] body")
        )
        with patch(
            "drevalis.services.llm.OpenAICompatibleProvider",
            return_value=provider,
        ):
            out = await generate_audiobook_script_sync(_script_request(), settings=_settings())
        assert out.title == "Untitled Story"

    async def test_empty_response_falls_back_to_untitled(self) -> None:
        provider = MagicMock()
        provider.generate = AsyncMock(return_value=_llm_result(""))
        with patch(
            "drevalis.services.llm.OpenAICompatibleProvider",
            return_value=provider,
        ):
            out = await generate_audiobook_script_sync(_script_request(), settings=_settings())
        # Empty content → empty title (route splits, takes first line
        # which is "" after strip).
        assert out.title in ("", "Untitled")

    async def test_llm_failure_502(self) -> None:
        provider = MagicMock()
        provider.generate = AsyncMock(side_effect=ConnectionError("LM Studio down"))
        with patch(
            "drevalis.services.llm.OpenAICompatibleProvider",
            return_value=provider,
        ):
            with pytest.raises(HTTPException) as exc:
                await generate_audiobook_script_sync(_script_request(), settings=_settings())
        assert exc.value.status_code == 502


# ── POST /{id}/music-preview ───────────────────────────────────────


class TestMusicPreview:
    async def test_audiobook_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await music_preview(
                uuid4(),
                mood="epic",
                seconds=30.0,
                volume_db=-14.0,
                db=AsyncMock(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_returns_503_when_no_track_rendered(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get = AsyncMock()

        # AudiobookService.render_music_preview returns a path that
        # does NOT exist on disk → 503 "no track resolved".
        ab_svc = MagicMock()
        ab_svc.render_music_preview = AsyncMock(return_value=tmp_path / "missing.wav")

        pool = MagicMock()
        pool.sync_from_db = AsyncMock()
        # Empty `_servers` dict so ComfyUIService construction is None.
        pool._servers = {}

        redis = MagicMock()
        redis.aclose = AsyncMock()

        with (
            patch("drevalis.services.comfyui.ComfyUIPool", return_value=pool),
            patch("drevalis.services.audiobook.AudiobookService", return_value=ab_svc),
            patch("drevalis.services.ffmpeg.FFmpegService", return_value=MagicMock()),
            patch("drevalis.services.storage.LocalStorage", return_value=MagicMock()),
            patch(
                "redis.asyncio.Redis",
                return_value=redis,
            ),
            patch("drevalis.core.redis.get_pool", return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await music_preview(
                    uuid4(),
                    mood="epic",
                    seconds=30.0,
                    volume_db=-14.0,
                    db=AsyncMock(),
                    settings=_settings(tmp_path),
                    svc=svc,
                )
        assert exc.value.status_code == 503
        # Pin: redis cleanup runs even when 503 fires.
        redis.aclose.assert_awaited_once()

    async def test_success_returns_url(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get = AsyncMock()

        ab_id = uuid4()
        # Stage a real preview file at the path the route expects.
        out_path = tmp_path / "audiobooks" / str(ab_id) / "music_preview.wav"
        out_path.parent.mkdir(parents=True)
        out_path.write_bytes(b"fake-audio")

        ab_svc = MagicMock()
        ab_svc.render_music_preview = AsyncMock(return_value=out_path)
        pool = MagicMock()
        pool.sync_from_db = AsyncMock()
        pool._servers = {}
        redis = MagicMock()
        redis.aclose = AsyncMock()

        with (
            patch("drevalis.services.comfyui.ComfyUIPool", return_value=pool),
            patch("drevalis.services.audiobook.AudiobookService", return_value=ab_svc),
            patch("drevalis.services.ffmpeg.FFmpegService", return_value=MagicMock()),
            patch("drevalis.services.storage.LocalStorage", return_value=MagicMock()),
            patch(
                "redis.asyncio.Redis",
                return_value=redis,
            ),
            patch("drevalis.core.redis.get_pool", return_value=MagicMock()),
        ):
            out = await music_preview(
                ab_id,
                mood="epic",
                seconds=30.0,
                volume_db=-14.0,
                db=AsyncMock(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert out["mood"] == "epic"
        assert out["url"].endswith("music_preview.wav")
        redis.aclose.assert_awaited_once()


# ── GET /{id}/clips ────────────────────────────────────────────────


class TestListClips:
    async def test_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await list_clips(
                uuid4(),
                db=AsyncMock(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_includes_overrides_from_track_mix(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ab = SimpleNamespace(
            track_mix={
                "voice_db": -2.0,
                "clips": {"voice:1": {"db_offset": -3}},
            }
        )
        svc.get = AsyncMock(return_value=ab)

        ab_svc = MagicMock()
        ab_svc.list_clips = AsyncMock(return_value={"voice": [{"id": "1"}], "music": []})

        with (
            patch("drevalis.services.audiobook.AudiobookService", return_value=ab_svc),
            patch("drevalis.services.ffmpeg.FFmpegService", return_value=MagicMock()),
            patch("drevalis.services.storage.LocalStorage", return_value=MagicMock()),
        ):
            out = await list_clips(
                uuid4(),
                db=AsyncMock(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert "voice" in out
        assert out["overrides"] == {"voice:1": {"db_offset": -3}}

    async def test_no_track_mix_yields_empty_overrides(self, tmp_path: Path) -> None:
        # Pin: when the audiobook has no track_mix yet (fresh), the
        # route still returns `overrides: {}` rather than None / KeyError.
        svc = MagicMock()
        ab = SimpleNamespace(track_mix=None)
        svc.get = AsyncMock(return_value=ab)
        ab_svc = MagicMock()
        ab_svc.list_clips = AsyncMock(return_value={"voice": []})
        with (
            patch("drevalis.services.audiobook.AudiobookService", return_value=ab_svc),
            patch("drevalis.services.ffmpeg.FFmpegService", return_value=MagicMock()),
            patch("drevalis.services.storage.LocalStorage", return_value=MagicMock()),
        ):
            out = await list_clips(
                uuid4(),
                db=AsyncMock(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert out["overrides"] == {}


# ── POST /{id}/upload-youtube ──────────────────────────────────────


def _make_channel(**overrides: Any) -> Any:
    base = {
        "id": uuid4(),
        "channel_id": "UC_x",
        "channel_name": "Drevalis",
        "is_active": True,
        "access_token_encrypted": "enc",
        "refresh_token_encrypted": "ref",
        "token_expiry": datetime(2030, 1, 1),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _upload_request() -> AudiobookYouTubeUploadRequest:
    return AudiobookYouTubeUploadRequest(title="My Audiobook")


class TestYouTubeUpload:
    async def test_audiobook_missing_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.prepare_youtube_upload = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        yt = MagicMock()
        yt.refresh_tokens_if_needed = AsyncMock(return_value=None)
        with patch(
            "drevalis.api.routes.youtube.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await upload_audiobook_to_youtube(
                    uuid4(),
                    _upload_request(),
                    db=AsyncMock(),
                    settings=_settings(tmp_path),
                    svc=svc,
                )
        assert exc.value.status_code == 404

    async def test_validation_error_maps_to_404(self, tmp_path: Path) -> None:
        # Pin: ValidationError on prepare means "no video to upload"
        # — the UI should show "generate a video first" so 404 is the
        # right semantic, NOT 422.
        svc = MagicMock()
        svc.prepare_youtube_upload = AsyncMock(side_effect=ValidationError("no video file"))
        yt = MagicMock()
        with patch(
            "drevalis.api.routes.youtube.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await upload_audiobook_to_youtube(
                    uuid4(),
                    _upload_request(),
                    db=AsyncMock(),
                    settings=_settings(tmp_path),
                    svc=svc,
                )
        assert exc.value.status_code == 404

    async def test_no_channel_selected_400_with_hint(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.prepare_youtube_upload = AsyncMock(side_effect=NoChannelSelectedError())
        yt = MagicMock()
        with patch(
            "drevalis.api.routes.youtube.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await upload_audiobook_to_youtube(
                    uuid4(),
                    _upload_request(),
                    db=AsyncMock(),
                    settings=_settings(tmp_path),
                    svc=svc,
                )
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "no_channel_selected"
        assert "youtube_channel_id" in exc.value.detail["hint"]

    async def test_success_records_video_and_url(self, tmp_path: Path) -> None:
        ab = SimpleNamespace(id=uuid4())
        ch = _make_channel()
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"\x00")

        svc = MagicMock()
        svc.prepare_youtube_upload = AsyncMock(return_value=(ab, ch, video_path))
        upload_row = SimpleNamespace(id=uuid4())
        svc.create_youtube_upload_row = AsyncMock(return_value=upload_row)
        svc.record_youtube_upload_success = AsyncMock()

        yt = MagicMock()
        yt.refresh_tokens_if_needed = AsyncMock(return_value=None)
        yt.upload_video = AsyncMock(
            return_value={
                "video_id": "yt-abc",
                "url": "https://youtu.be/yt-abc",
            }
        )

        with patch(
            "drevalis.api.routes.youtube.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            out = await upload_audiobook_to_youtube(
                ab.id,
                _upload_request(),
                db=AsyncMock(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert out["youtube_video_id"] == "yt-abc"
        assert out["youtube_url"] == "https://youtu.be/yt-abc"
        assert out["status"] == "done"
        svc.record_youtube_upload_success.assert_awaited_once()

    async def test_token_refresh_persists_updates(self, tmp_path: Path) -> None:
        # Pin: when refresh_tokens_if_needed returns updated tokens,
        # they're written back onto the channel + db.flush() runs.
        ab = SimpleNamespace(id=uuid4())
        ch = _make_channel()
        video_path = tmp_path / "v.mp4"
        video_path.write_bytes(b"\x00")

        svc = MagicMock()
        svc.prepare_youtube_upload = AsyncMock(return_value=(ab, ch, video_path))
        svc.create_youtube_upload_row = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        svc.record_youtube_upload_success = AsyncMock()

        yt = MagicMock()
        yt.refresh_tokens_if_needed = AsyncMock(return_value={"access_token_encrypted": "new-enc"})
        yt.upload_video = AsyncMock(return_value={"video_id": "x", "url": "https://y/x"})

        db = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "drevalis.api.routes.youtube.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            await upload_audiobook_to_youtube(
                ab.id,
                _upload_request(),
                db=db,
                settings=_settings(tmp_path),
                svc=svc,
            )
        # Updated token written onto the channel object.
        assert ch.access_token_encrypted == "new-enc"
        db.flush.assert_awaited_once()

    async def test_upstream_failure_502_records_failure(self, tmp_path: Path) -> None:
        ab = SimpleNamespace(id=uuid4())
        ch = _make_channel()
        video_path = tmp_path / "v.mp4"
        video_path.write_bytes(b"\x00")

        svc = MagicMock()
        svc.prepare_youtube_upload = AsyncMock(return_value=(ab, ch, video_path))
        svc.create_youtube_upload_row = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        svc.record_youtube_upload_failure = AsyncMock()

        yt = MagicMock()
        yt.refresh_tokens_if_needed = AsyncMock(return_value=None)
        yt.upload_video = AsyncMock(side_effect=ConnectionError("yt down"))

        with patch(
            "drevalis.api.routes.youtube.build_youtube_service",
            AsyncMock(return_value=yt),
        ):
            with pytest.raises(HTTPException) as exc:
                await upload_audiobook_to_youtube(
                    ab.id,
                    _upload_request(),
                    db=AsyncMock(),
                    settings=_settings(tmp_path),
                    svc=svc,
                )
        assert exc.value.status_code == 502
        # Pin: the upload row is marked failed even when the route 502s.
        svc.record_youtube_upload_failure.assert_awaited_once()


# ── GET /{id}/uploads ─────────────────────────────────────────────


class TestListAudiobookUploads:
    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.list_youtube_uploads = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await list_audiobook_uploads(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_serialises_uploads(self) -> None:
        u = SimpleNamespace(
            id=uuid4(),
            audiobook_id=uuid4(),
            youtube_video_id="yt-abc",
            youtube_url="https://youtu.be/abc",
            title="My Book",
            privacy_status="public",
            upload_status="done",
            error_message=None,
            playlist_id=None,
            created_at=datetime(2026, 1, 1, 12, 0),
            updated_at=datetime(2026, 1, 2, 13, 0),
        )
        svc = MagicMock()
        svc.list_youtube_uploads = AsyncMock(return_value=[u])
        out = await list_audiobook_uploads(uuid4(), svc=svc)
        assert len(out) == 1
        assert out[0]["youtube_video_id"] == "yt-abc"
        # Datetimes serialized as ISO strings.
        assert out[0]["created_at"].startswith("2026-01-01")
