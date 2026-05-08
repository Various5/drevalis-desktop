"""Tests for ``api/routes/episodes/_monolith.py`` — second half:
regenerate, reassemble, music, set-music, exports.

Pin:

* `regenerate_scene` / `regenerate_voice` / `reassemble` /
  `regenerate_captions`: NotFoundError + NoScript → 404,
  ConcurrencyCapReached → 429, SceneNotFound → 404 (regenerate_scene
  only).
* `regenerate_voice` override precedence: query > body > stored.
* `cancel_episode` InvalidStatus → 409 with the current status.
* Music endpoints validate `mood` (required string) and `duration`
  (numeric in [1, 120]) at the route layer before reaching the service.
* `select_episode_music` requires `music_path` key (passing null
  clears); rejects paths that don't exist on disk with 404.
* `_sanitize_filename` strips bad chars, truncates to 100, falls back
  to `"export"` when nothing usable remains.
* Export endpoints 404 on missing assets / files-not-on-disk.
* `upload_thumbnail` rejects non-image content type → 415, oversize →
  413, undecodable image → 400.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from drevalis.api.routes.episodes._monolith import (
    _build_description,
    _ffprobe_duration,
    _sanitize_filename,
    cancel_episode,
    duplicate_episode,
    estimate_cost,
    export_bundle,
    export_description,
    export_thumbnail,
    export_video,
    generate_episode_music,
    list_episode_music,
    list_music_moods,
    reassemble,
    regenerate_captions,
    regenerate_scene,
    regenerate_voice,
    reset_episode,
    select_episode_music,
    set_music,
    upload_thumbnail,
)
from drevalis.schemas.episode import SetMusicRequest
from drevalis.services.episode import (
    ConcurrencyCapReachedError,
    EpisodeInvalidStatusError,
    EpisodeNoScriptError,
    EpisodeNotFoundError,
    SceneNotFoundError,
)


def _settings(tmp_path: Path) -> Any:
    s = MagicMock()
    s.max_concurrent_generations = 4
    s.storage_base_path = tmp_path
    return s


def _make_episode(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "series_id": uuid4(),
        "title": "Hook A",
        "topic": None,
        "status": "draft",
        "script": None,
        "base_path": None,
        "generation_log": None,
        "metadata_": None,
        "override_voice_profile_id": None,
        "override_llm_config_id": None,
        "override_caption_style": None,
        "content_format": "shorts",
        "chapters": None,
        "total_duration_seconds": None,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
        "media_assets": [],
        "generation_jobs": [],
        "series": SimpleNamespace(name="My Series"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── _ffprobe_duration ──────────────────────────────────────────────


class TestFfprobeDuration:
    async def test_returns_duration_on_zero_returncode(self, tmp_path: Path) -> None:
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"42.5\n", b""))
        with patch(
            "drevalis.api.routes.episodes._monolith.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            out = await _ffprobe_duration(tmp_path / "x.wav")
        assert out == pytest.approx(42.5)

    async def test_non_zero_returncode_returns_zero(self, tmp_path: Path) -> None:
        proc = MagicMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"err"))
        with patch(
            "drevalis.api.routes.episodes._monolith.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            out = await _ffprobe_duration(tmp_path / "x.wav")
        assert out == 0.0

    async def test_unparseable_stdout_returns_zero(self, tmp_path: Path) -> None:
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"N/A\n", b""))
        with patch(
            "drevalis.api.routes.episodes._monolith.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            out = await _ffprobe_duration(tmp_path / "x.wav")
        assert out == 0.0


# ── regenerate_scene ───────────────────────────────────────────────


class TestRegenerateScene:
    async def test_success(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_scene = AsyncMock(return_value=[uuid4()])
        out = await regenerate_scene(
            uuid4(),
            2,
            {"visual_prompt": "new prompt"},
            settings=_settings(tmp_path),
            svc=svc,
        )
        assert out["scene_number"] == 2

    async def test_omitted_payload_passes_none_prompt(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_scene = AsyncMock(return_value=[])
        await regenerate_scene(
            uuid4(),
            1,
            None,
            settings=_settings(tmp_path),
            svc=svc,
        )
        called_prompt = svc.regenerate_scene.call_args.args[2]
        assert called_prompt is None

    async def test_no_script_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_scene = AsyncMock(side_effect=EpisodeNoScriptError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await regenerate_scene(uuid4(), 1, None, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_scene_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_scene = AsyncMock(side_effect=SceneNotFoundError(99))
        with pytest.raises(HTTPException) as exc:
            await regenerate_scene(uuid4(), 99, None, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404
        assert "99" in exc.value.detail

    async def test_concurrency_429(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_scene = AsyncMock(side_effect=ConcurrencyCapReachedError(4))
        with pytest.raises(HTTPException) as exc:
            await regenerate_scene(uuid4(), 1, None, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 429


# ── regenerate_voice ───────────────────────────────────────────────


class TestRegenerateVoice:
    async def test_query_param_takes_priority_over_body(self, tmp_path: Path) -> None:
        # Query param wins over JSON body's voice_profile_id.
        svc = MagicMock()
        svc.regenerate_voice = AsyncMock(return_value=[])
        query_id = uuid4()
        body_id = uuid4()
        await regenerate_voice(
            uuid4(),
            voice_profile_id=query_id,
            speed=None,
            pitch=None,
            payload={"voice_profile_id": str(body_id)},
            settings=_settings(tmp_path),
            svc=svc,
        )
        kwargs = svc.regenerate_voice.call_args.kwargs
        assert kwargs["voice_profile_id"] == query_id

    async def test_body_used_when_query_omitted(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_voice = AsyncMock(return_value=[])
        body_id = uuid4()
        await regenerate_voice(
            uuid4(),
            voice_profile_id=None,
            speed=None,
            pitch=None,
            payload={"voice_profile_id": body_id},
            settings=_settings(tmp_path),
            svc=svc,
        )
        kwargs = svc.regenerate_voice.call_args.kwargs
        assert kwargs["voice_profile_id"] == body_id

    async def test_no_payload_at_all_passes_none(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_voice = AsyncMock(return_value=[])
        await regenerate_voice(
            uuid4(),
            voice_profile_id=None,
            speed=None,
            pitch=None,
            payload=None,
            settings=_settings(tmp_path),
            svc=svc,
        )
        kwargs = svc.regenerate_voice.call_args.kwargs
        assert kwargs["voice_profile_id"] is None

    async def test_speed_pitch_pass_through(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_voice = AsyncMock(return_value=[])
        await regenerate_voice(
            uuid4(),
            voice_profile_id=None,
            speed=1.25,
            pitch=2.0,
            payload=None,
            settings=_settings(tmp_path),
            svc=svc,
        )
        kwargs = svc.regenerate_voice.call_args.kwargs
        assert kwargs["speed"] == 1.25
        assert kwargs["pitch"] == 2.0

    async def test_no_script_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_voice = AsyncMock(side_effect=EpisodeNoScriptError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await regenerate_voice(
                uuid4(),
                voice_profile_id=None,
                speed=None,
                pitch=None,
                payload=None,
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_concurrency_429(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_voice = AsyncMock(side_effect=ConcurrencyCapReachedError(4))
        with pytest.raises(HTTPException) as exc:
            await regenerate_voice(
                uuid4(),
                voice_profile_id=None,
                speed=None,
                pitch=None,
                payload=None,
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 429


# ── reassemble ─────────────────────────────────────────────────────


class TestReassemble:
    async def test_success(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.reassemble = AsyncMock(return_value=[uuid4(), uuid4()])
        out = await reassemble(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert "Reassembly enqueued" in out["message"]

    async def test_no_script_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.reassemble = AsyncMock(side_effect=EpisodeNoScriptError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await reassemble(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_concurrency_429(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.reassemble = AsyncMock(side_effect=ConcurrencyCapReachedError(4))
        with pytest.raises(HTTPException) as exc:
            await reassemble(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 429


# ── regenerate_captions ────────────────────────────────────────────


class TestRegenerateCaptions:
    async def test_success_includes_style_in_message(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_captions = AsyncMock(return_value=[uuid4()])
        out = await regenerate_captions(
            uuid4(),
            caption_style="karaoke",
            settings=_settings(tmp_path),
            svc=svc,
        )
        assert "karaoke" in out["message"]

    async def test_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.regenerate_captions = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await regenerate_captions(
                uuid4(),
                caption_style="minimal",
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404


# ── estimate_cost / duplicate / reset ──────────────────────────────


class TestSimpleHandlers:
    async def test_estimate_cost_success(self) -> None:
        svc = MagicMock()
        svc.estimate_cost = AsyncMock(return_value={"tts_cost_usd": 0.12})
        out = await estimate_cost(uuid4(), svc=svc)
        assert out["tts_cost_usd"] == 0.12

    async def test_estimate_cost_404(self) -> None:
        svc = MagicMock()
        svc.estimate_cost = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await estimate_cost(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_duplicate_success(self) -> None:
        svc = MagicMock()
        new_ep = _make_episode(title="Hook A (copy)")
        svc.duplicate = AsyncMock(return_value=new_ep)
        out = await duplicate_episode(uuid4(), svc=svc)
        assert out.title == "Hook A (copy)"

    async def test_duplicate_not_found_404(self) -> None:
        svc = MagicMock()
        svc.duplicate = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await duplicate_episode(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_reset_returns_jobs_deleted(self) -> None:
        svc = MagicMock()
        svc.reset_to_draft = AsyncMock(return_value=7)
        out = await reset_episode(uuid4(), svc=svc)
        assert out["jobs_deleted"] == 7

    async def test_reset_not_found_404(self) -> None:
        svc = MagicMock()
        svc.reset_to_draft = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await reset_episode(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── cancel_episode ────────────────────────────────────────────────


class TestCancelEpisode:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.cancel = AsyncMock(return_value=3)
        out = await cancel_episode(uuid4(), svc=svc)
        assert out["cancelled_jobs"] == 3

    async def test_invalid_status_409(self) -> None:
        svc = MagicMock()
        svc.cancel = AsyncMock(
            side_effect=EpisodeInvalidStatusError(
                episode_id=uuid4(),
                current_status="exported",
                allowed=["generating"],
            )
        )
        with pytest.raises(HTTPException) as exc:
            await cancel_episode(uuid4(), svc=svc)
        assert exc.value.status_code == 409
        assert "exported" in exc.value.detail

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.cancel = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await cancel_episode(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── Music endpoints ────────────────────────────────────────────────


class TestMusicMoods:
    async def test_lists_static_catalogue(self) -> None:
        out = await list_music_moods(uuid4())
        assert "moods" in out
        assert len(out["moods"]) > 0
        # Each entry has the right keys.
        first = out["moods"][0]
        assert {"value", "label", "description"} <= set(first.keys())


class TestListEpisodeMusic:
    async def test_delegates_to_service(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.list_music_tracks = AsyncMock(return_value={"tracks": []})
        out = await list_episode_music(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert out == {"tracks": []}

    async def test_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.list_music_tracks = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await list_episode_music(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404


class TestGenerateEpisodeMusic:
    async def test_success_enqueues(self) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock()
        redis = MagicMock()
        redis.enqueue_job = AsyncMock()
        out = await generate_episode_music(
            uuid4(), {"mood": "epic", "duration": 30}, redis=redis, svc=svc
        )
        assert out["status"] == "queued"
        redis.enqueue_job.assert_awaited_once()

    async def test_episode_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await generate_episode_music(
                uuid4(),
                {"mood": "epic", "duration": 30},
                redis=MagicMock(),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_missing_mood_400(self) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await generate_episode_music(uuid4(), {"duration": 30}, redis=MagicMock(), svc=svc)
        assert exc.value.status_code == 400

    async def test_empty_mood_400(self) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await generate_episode_music(
                uuid4(), {"mood": "", "duration": 30}, redis=MagicMock(), svc=svc
            )
        assert exc.value.status_code == 400

    async def test_non_numeric_duration_400(self) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await generate_episode_music(
                uuid4(),
                {"mood": "epic", "duration": "long"},
                redis=MagicMock(),
                svc=svc,
            )
        assert exc.value.status_code == 400

    async def test_oversized_duration_400(self) -> None:
        # Pin the AceStep 120s hard cap.
        svc = MagicMock()
        svc.get_or_raise = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await generate_episode_music(
                uuid4(),
                {"mood": "epic", "duration": 200},
                redis=MagicMock(),
                svc=svc,
            )
        assert exc.value.status_code == 400


class TestSelectEpisodeMusic:
    async def test_missing_music_path_400(self, tmp_path: Path) -> None:
        svc = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await select_episode_music(uuid4(), {}, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 400

    async def test_clear_selection_succeeds(self, tmp_path: Path) -> None:
        # Pin: passing music_path=None clears the selection (no
        # file-existence check fires).
        svc = MagicMock()
        svc.select_music = AsyncMock(return_value=None)
        out = await select_episode_music(
            uuid4(),
            {"music_path": None},
            settings=_settings(tmp_path),
            svc=svc,
        )
        assert "cleared" in out["message"]

    async def test_path_not_on_disk_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await select_episode_music(
                uuid4(),
                {"music_path": "music/nonexistent.mp3"},
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404
        assert "Music file not found" in exc.value.detail

    async def test_existing_path_persisted(self, tmp_path: Path) -> None:
        # Real file on disk.
        track = tmp_path / "music" / "track.mp3"
        track.parent.mkdir(parents=True)
        track.write_bytes(b"\x00")

        svc = MagicMock()
        svc.select_music = AsyncMock(return_value="music/track.mp3")
        out = await select_episode_music(
            uuid4(),
            {"music_path": "music/track.mp3"},
            settings=_settings(tmp_path),
            svc=svc,
        )
        assert out["selected_music_path"] == "music/track.mp3"

    async def test_episode_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.select_music = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        out_path = tmp_path / "music" / "track.mp3"
        out_path.parent.mkdir(parents=True)
        out_path.write_bytes(b"\x00")
        with pytest.raises(HTTPException) as exc:
            await select_episode_music(
                uuid4(),
                {"music_path": "music/track.mp3"},
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404


# ── set_music ──────────────────────────────────────────────────────


class TestSetMusic:
    async def test_success(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.set_music = AsyncMock(return_value={"music_enabled": True})
        out = await set_music(
            uuid4(),
            SetMusicRequest(music_enabled=True, music_mood="epic"),
            settings=_settings(tmp_path),
            svc=svc,
        )
        assert out["music_enabled"] is True

    async def test_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.set_music = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await set_music(
                uuid4(),
                SetMusicRequest(music_enabled=False),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_concurrency_429(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.set_music = AsyncMock(side_effect=ConcurrencyCapReachedError(4))
        with pytest.raises(HTTPException) as exc:
            await set_music(
                uuid4(),
                SetMusicRequest(music_enabled=True),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 429


# ── _sanitize_filename / _build_description ────────────────────────


class TestSanitizeFilename:
    def test_strips_bad_chars(self) -> None:
        out = _sanitize_filename("Series: Test/Co", 'Hook "A"')
        # No slashes / colons / quotes survive.
        assert "/" not in out
        assert ":" not in out
        assert '"' not in out

    def test_truncates_to_100(self) -> None:
        out = _sanitize_filename("S" * 60, "T" * 80)
        assert len(out) <= 100

    def test_normal_input_underscored(self) -> None:
        out = _sanitize_filename("My Series", "Hook A")
        assert out == "My_Series_Hook_A"


class TestBuildDescription:
    def test_handles_no_script(self) -> None:
        ep = _make_episode(title="Hook A", script=None)
        out = _build_description(ep)
        assert "Hook A" in out
        assert "My Series" in out

    def test_builds_with_script(self) -> None:
        script = {
            "title": "Hooked!",
            "description": "Catchy hook description",
            "scenes": [
                {
                    "scene_number": 1,
                    "narration": "Once upon a time",
                    "visual_prompt": "x",
                    "duration_seconds": 5,
                }
            ],
            "hashtags": ["short", "viral"],
        }
        ep = _make_episode(script=script)
        out = _build_description(ep)
        assert "Hooked!" in out
        assert "Catchy hook description" in out
        assert "#short" in out
        assert "Once upon a time" in out

    def test_invalid_script_falls_back_to_episode_title(self) -> None:
        # Pin: malformed JSONB script doesn't crash; description still
        # has the episode title at the top.
        ep = _make_episode(title="Hook A", script={"weird": "shape"})
        out = _build_description(ep)
        assert "Hook A" in out


# ── export_video / export_thumbnail / export_description ───────────


class TestExportEndpoints:
    async def test_video_no_asset_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ep = _make_episode()
        svc.get_with_series_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await export_video(ep.id, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_video_file_not_on_disk_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ep = _make_episode()
        svc.get_with_series_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="missing.mp4")
        with pytest.raises(HTTPException) as exc:
            await export_video(ep.id, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404
        assert "Video file not found" in exc.value.detail

    async def test_video_returns_file_response(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ep = _make_episode(title="Hook A")
        svc.get_with_series_or_raise = AsyncMock(return_value=ep)
        out_path = tmp_path / "video.mp4"
        out_path.write_bytes(b"\x00" * 100)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")

        out = await export_video(ep.id, settings=_settings(tmp_path), svc=svc)
        # FileResponse with sanitized filename.
        assert out.media_type == "video/mp4"
        assert "Hook" in out.filename or "Series" in out.filename

    async def test_episode_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_with_series_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await export_video(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_thumbnail_no_asset_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ep = _make_episode()
        svc.get_with_series_or_raise = AsyncMock(return_value=ep)
        svc.get_thumbnail_asset_path = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await export_thumbnail(ep.id, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_thumbnail_file_missing_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ep = _make_episode()
        svc.get_with_series_or_raise = AsyncMock(return_value=ep)
        svc.get_thumbnail_asset_path = AsyncMock(return_value="missing.jpg")
        with pytest.raises(HTTPException) as exc:
            await export_thumbnail(ep.id, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_description_returns_text(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ep = _make_episode(title="Hook A")
        svc.get_with_series_or_raise = AsyncMock(return_value=ep)
        out = await export_description(ep.id, svc=svc)
        assert out.media_type.startswith("text/plain")
        assert "Hook A" in out.body.decode()


# ── export_bundle ──────────────────────────────────────────────────


class TestExportBundle:
    async def test_no_video_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ep = _make_episode()
        svc.get_with_series_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value=None)
        svc.get_thumbnail_asset_path = AsyncMock(return_value=None)
        svc.get_caption_asset_path = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await export_bundle(ep.id, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_assembles_zip_bundle(self, tmp_path: Path) -> None:
        # Stage real files so the ZipFile.write paths succeed.
        video = tmp_path / "video.mp4"
        video.write_bytes(b"\x00" * 100)
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"\x00" * 50)
        srt = tmp_path / "captions.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello")

        svc = MagicMock()
        ep = _make_episode(title="Hook A")
        svc.get_with_series_or_raise = AsyncMock(return_value=ep)
        svc.get_video_asset_path = AsyncMock(return_value="video.mp4")
        svc.get_thumbnail_asset_path = AsyncMock(return_value="thumb.jpg")
        svc.get_caption_asset_path = AsyncMock(return_value="captions.srt")

        out = await export_bundle(ep.id, settings=_settings(tmp_path), svc=svc)
        assert out.media_type == "application/zip"
        assert len(out.body) > 0


# ── upload_thumbnail ───────────────────────────────────────────────


def _ufile(content: bytes, filename: str = "t.png", mime: str = "image/png") -> Any:
    f = MagicMock(spec=UploadFile)
    f.filename = filename
    f.content_type = mime
    chunks = [content[i : i + 64 * 1024] for i in range(0, len(content), 64 * 1024)] + [b""]

    async def _read(_size: int) -> bytes:
        return chunks.pop(0) if chunks else b""

    f.read = AsyncMock(side_effect=_read)
    return f


class TestUploadThumbnail:
    async def test_unsupported_mime_415(self, tmp_path: Path) -> None:
        svc = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await upload_thumbnail(
                uuid4(),
                file=_ufile(b"data", mime="application/pdf"),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 415
        assert exc.value.detail["error"] == "unsupported_image_type"

    async def test_oversize_413(self, tmp_path: Path) -> None:
        svc = MagicMock()
        big = b"\xff" * (5 * 1024 * 1024)
        with pytest.raises(HTTPException) as exc:
            await upload_thumbnail(
                uuid4(),
                file=_ufile(big),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 413

    async def test_episode_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        # Use a real PNG so we get past the Pillow decode and reach the
        # episode lookup (where 404 fires).
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format="PNG")
        with pytest.raises(HTTPException) as exc:
            await upload_thumbnail(
                uuid4(),
                file=_ufile(buf.getvalue()),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_undecodable_400(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await upload_thumbnail(
                uuid4(),
                file=_ufile(b"not a png", mime="image/png"),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 400

    async def test_success_writes_jpeg_and_replaces_asset(self, tmp_path: Path) -> None:
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGBA", (10, 10), (0, 0, 255, 128)).save(buf, format="PNG")

        svc = MagicMock()
        svc.get_or_raise = AsyncMock()
        new_asset = SimpleNamespace(id=uuid4())
        svc.replace_thumbnail_asset = AsyncMock(return_value=new_asset)
        ep_id = uuid4()
        out = await upload_thumbnail(
            ep_id,
            file=_ufile(buf.getvalue()),
            settings=_settings(tmp_path),
            svc=svc,
        )
        assert out["asset_id"] == str(new_asset.id)
        # File written under episodes/{id}/output/thumbnail.jpg.
        target = tmp_path / "episodes" / str(ep_id) / "output" / "thumbnail.jpg"
        assert target.exists()
        # First two bytes are the JPEG SOI marker (\xFF\xD8).
        assert target.read_bytes()[:2] == b"\xff\xd8"
