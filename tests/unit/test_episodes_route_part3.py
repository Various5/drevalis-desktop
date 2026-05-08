"""Tests for ``api/routes/episodes/_monolith.py`` — part 3:
SEO scoring, raw-assets export, edit / preview / reset, inpaint,
continuity.

Pin the heuristic SEO grading + the deterministic edit-flow contracts:

* `_grade_for` thresholds: ≥90→A, ≥75→B, ≥55→C, else D.
* `get_seo_score` builds checks for title length / desc / tags /
  hashtags from either stored seo metadata OR raw episode fields.
  No LLM call — purely heuristic.
* `export_raw_assets` 404 when no media_assets at all; success
  builds a ZIP with per-kind dirs + README.
* `edit_video` 404 when no video / file missing; backs up to
  `final_original.mp4` on first edit.
* `edit_reset` 409 when no original backup exists.
* `generate_seo` enqueues a background job; 404 when episode/script
  missing.
* `inpaint_scene` rejects malformed base64 mask → 400; persists
  mask file + Redis hint.
* `check_script_continuity` returns `issues=[]` when no LLM config
  is registered (graceful degradation).
"""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.episodes._monolith import (
    InpaintRequest,
    _grade_for,
    check_script_continuity,
    edit_preview,
    edit_reset,
    edit_video,
    export_raw_assets,
    generate_seo,
    get_seo_score,
    inpaint_scene,
    seo_preflight,
)
from drevalis.schemas.episode import BorderConfig, VideoEditRequest
from drevalis.services.episode import (
    EpisodeNoScriptError,
    EpisodeNotFoundError,
)


def _settings(tmp_path: Path) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    s.ffmpeg_path = "ffmpeg"
    import base64 as _b64

    s.encryption_key = _b64.urlsafe_b64encode(b"\x00" * 32).decode()
    return s


def _make_episode(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "title": "Hook A",
        "topic": "intro",
        "script": None,
        "metadata_": None,
        "content_format": "shorts",
        "series": SimpleNamespace(name="My Series"),
        "created_at": datetime(2026, 1, 1),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── _grade_for ─────────────────────────────────────────────────────


class TestGradeFor:
    @pytest.mark.parametrize(
        ("score", "grade"),
        [
            (100, "A"),
            (90, "A"),
            (89, "B"),
            (75, "B"),
            (74, "C"),
            (55, "C"),
            (54, "D"),
            (0, "D"),
        ],
    )
    def test_thresholds(self, score: int, grade: str) -> None:
        assert _grade_for(score) == grade


# ── GET /seo-score ─────────────────────────────────────────────────


class TestGetSeoScore:
    async def test_episode_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_seo_score(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_falls_back_to_raw_episode_fields_when_no_seo(self) -> None:
        # No metadata_.seo → uses episode.title and episode.topic.
        svc = MagicMock()
        ep = _make_episode(
            title="A" * 50,  # in sweet spot 45-70
            topic="x" * 500,  # >= 400
            metadata_=None,
        )
        svc.get_or_raise = AsyncMock(return_value=ep)
        out = await get_seo_score(ep.id, svc=svc)
        assert out.has_seo_metadata is False
        assert out.overall_score >= 20  # title sweet spot alone

    async def test_uses_seo_metadata_when_present(self) -> None:
        svc = MagicMock()
        ep = _make_episode(
            title="raw",
            metadata_={
                "seo": {
                    "title": "Optimised Title — 50 Characters Long For Sweet Spot Yeah",
                    "description": "x" * 500,
                    "tags": [f"t{i}" for i in range(8)],
                    "hashtags": ["a", "b", "c", "d"],
                    "hook": "Watch this",
                }
            },
        )
        svc.get_or_raise = AsyncMock(return_value=ep)
        out = await get_seo_score(ep.id, svc=svc)
        assert out.has_seo_metadata is True
        # Some optional checks (hook + tag-in-description) lower the
        # ceiling; score still passes 50.
        assert out.overall_score >= 50
        assert out.summary  # non-empty

    async def test_short_title_emits_error_check(self) -> None:
        svc = MagicMock()
        ep = _make_episode(title="hi", topic=None, metadata_=None)
        svc.get_or_raise = AsyncMock(return_value=ep)
        out = await get_seo_score(ep.id, svc=svc)
        title_check = next(c for c in out.checks if c.id == "title_length")
        assert title_check.severity == "error"
        assert title_check.pass_ is False

    async def test_medium_title_emits_warn_with_partial_score(self) -> None:
        svc = MagicMock()
        ep = _make_episode(title="A" * 30, topic=None, metadata_=None)
        svc.get_or_raise = AsyncMock(return_value=ep)
        out = await get_seo_score(ep.id, svc=svc)
        title_check = next(c for c in out.checks if c.id == "title_length")
        assert title_check.severity == "warn"
        assert title_check.pass_ is False

    async def test_overlong_title_emits_warn(self) -> None:
        svc = MagicMock()
        ep = _make_episode(title="A" * 90, topic=None, metadata_=None)
        svc.get_or_raise = AsyncMock(return_value=ep)
        out = await get_seo_score(ep.id, svc=svc)
        title_check = next(c for c in out.checks if c.id == "title_length")
        assert title_check.severity == "warn"

    async def test_no_tags_emits_error(self) -> None:
        svc = MagicMock()
        ep = _make_episode(metadata_={"seo": {"title": "x", "tags": [], "hashtags": []}})
        svc.get_or_raise = AsyncMock(return_value=ep)
        out = await get_seo_score(ep.id, svc=svc)
        tag_check = next(c for c in out.checks if c.id == "tag_count")
        assert tag_check.severity == "error"

    async def test_too_many_hashtags_warn(self) -> None:
        svc = MagicMock()
        ep = _make_episode(
            metadata_={"seo": {"title": "x" * 50, "hashtags": [f"h{i}" for i in range(8)]}}
        )
        svc.get_or_raise = AsyncMock(return_value=ep)
        out = await get_seo_score(ep.id, svc=svc)
        hashtag_check = next(c for c in out.checks if c.id == "hashtag_count")
        assert hashtag_check.severity == "warn"

    async def test_summary_reflects_blocking_count(self) -> None:
        # No SEO + tiny title + no description + no tags + no hashtags
        # → multiple errors. Pin: summary mentions "blocking issue(s)".
        svc = MagicMock()
        ep = _make_episode(title="x", topic="", metadata_=None)
        svc.get_or_raise = AsyncMock(return_value=ep)
        out = await get_seo_score(ep.id, svc=svc)
        assert "blocking" in out.summary.lower()


# ── GET /export/raw-assets ─────────────────────────────────────────


class TestExportRawAssets:
    async def test_no_assets_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_with_series_or_raise = AsyncMock(return_value=_make_episode())
        svc.get_all_assets = AsyncMock(return_value=[])
        with pytest.raises(HTTPException) as exc:
            await export_raw_assets(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_episode_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_with_series_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await export_raw_assets(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_assembles_zip_with_per_kind_layout(self, tmp_path: Path) -> None:
        # Stage real files for two scenes + a video + a thumbnail.
        scene_a = tmp_path / "scene_a.png"
        scene_a.write_bytes(b"\x89PNG")
        scene_b = tmp_path / "scene_b.png"
        scene_b.write_bytes(b"\x89PNG")
        video = tmp_path / "video.mp4"
        video.write_bytes(b"\x00")
        # Build asset namespace objects matching what the route expects.
        from datetime import UTC

        a1 = SimpleNamespace(
            id=uuid4(),
            asset_type="scene",
            file_path="scene_a.png",
            scene_number=1,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        a2 = SimpleNamespace(
            id=uuid4(),
            asset_type="scene",
            file_path="scene_b.png",
            scene_number=2,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        a3 = SimpleNamespace(
            id=uuid4(),
            asset_type="video",
            file_path="video.mp4",
            scene_number=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        svc = MagicMock()
        svc.get_with_series_or_raise = AsyncMock(return_value=_make_episode())
        svc.get_all_assets = AsyncMock(return_value=[a1, a2, a3])

        out = await export_raw_assets(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert out.media_type == "application/zip"
        # The zip is non-trivial (>= 4 entries: 2 scenes + 1 video +
        # README).
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(out.body)) as zf:
            names = zf.namelist()
        # Per-kind subdirectories.
        assert any("/scene/scene_01" in n for n in names)
        assert any("/scene/scene_02" in n for n in names)
        assert any("/video/video" in n for n in names)
        assert any(n.endswith("README.txt") for n in names)


# ── edit_video ─────────────────────────────────────────────────────


class TestEditVideo:
    async def test_no_video_asset_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_latest_video_asset = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await edit_video(
                uuid4(),
                payload=VideoEditRequest(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_video_file_missing_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        asset = SimpleNamespace(id=uuid4(), file_path="missing.mp4")
        svc.get_latest_video_asset = AsyncMock(return_value=asset)
        with pytest.raises(HTTPException) as exc:
            await edit_video(
                uuid4(),
                payload=VideoEditRequest(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_first_edit_backs_up_original(self, tmp_path: Path) -> None:
        # Set up: video file exists, no original backup yet.
        ep_id = uuid4()
        out_dir = tmp_path / "episodes" / str(ep_id) / "output"
        out_dir.mkdir(parents=True)
        video = out_dir / "final.mp4"
        video.write_bytes(b"original-content")

        asset = SimpleNamespace(id=uuid4(), file_path=str(video.relative_to(tmp_path).as_posix()))
        svc = MagicMock()
        svc.get_latest_video_asset = AsyncMock(return_value=asset)
        svc.update_asset_metadata = AsyncMock()

        # Stub the FFmpegService so we don't shell out.
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.apply_video_effects = AsyncMock()
        ffmpeg_mock.get_duration = AsyncMock(return_value=60.0)

        # apply_video_effects should write to final_edited.mp4.
        async def _fake_apply(**kwargs: Any) -> None:
            kwargs["output_path"].write_bytes(b"edited-content")

        ffmpeg_mock.apply_video_effects.side_effect = _fake_apply

        with patch("drevalis.services.ffmpeg.FFmpegService", return_value=ffmpeg_mock):
            out = await edit_video(
                ep_id,
                payload=VideoEditRequest(speed=1.0),
                settings=_settings(tmp_path),
                svc=svc,
            )
        # final_original.mp4 created with ORIGINAL content.
        backup = video.parent / "final_original.mp4"
        assert backup.exists()
        assert backup.read_bytes() == b"original-content"
        # The active video file is now the edited one.
        assert video.read_bytes() == b"edited-content"
        assert out.duration_seconds == 60.0

    async def test_subsequent_edit_does_not_overwrite_original(self, tmp_path: Path) -> None:
        # Original backup already exists from a prior edit.
        ep_id = uuid4()
        out_dir = tmp_path / "episodes" / str(ep_id) / "output"
        out_dir.mkdir(parents=True)
        video = out_dir / "final.mp4"
        video.write_bytes(b"current-content")
        backup = video.parent / "final_original.mp4"
        backup.write_bytes(b"original-from-first-edit")

        asset = SimpleNamespace(id=uuid4(), file_path=str(video.relative_to(tmp_path).as_posix()))
        svc = MagicMock()
        svc.get_latest_video_asset = AsyncMock(return_value=asset)
        svc.update_asset_metadata = AsyncMock()

        ffmpeg_mock = MagicMock()

        async def _fake_apply(**kwargs: Any) -> None:
            kwargs["output_path"].write_bytes(b"new-edited")

        ffmpeg_mock.apply_video_effects = AsyncMock(side_effect=_fake_apply)
        ffmpeg_mock.get_duration = AsyncMock(return_value=42.0)

        with patch("drevalis.services.ffmpeg.FFmpegService", return_value=ffmpeg_mock):
            await edit_video(
                ep_id,
                payload=VideoEditRequest(border=BorderConfig()),
                settings=_settings(tmp_path),
                svc=svc,
            )
        # Backup is preserved (not overwritten with current-content).
        assert backup.read_bytes() == b"original-from-first-edit"


# ── edit_preview ───────────────────────────────────────────────────


class TestEditPreview:
    async def test_no_video_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_video_asset_path = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await edit_preview(
                uuid4(),
                payload=VideoEditRequest(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_uses_original_when_present(self, tmp_path: Path) -> None:
        ep_id = uuid4()
        out_dir = tmp_path / "episodes" / str(ep_id) / "output"
        out_dir.mkdir(parents=True)
        video = out_dir / "final.mp4"
        video.write_bytes(b"current")
        original = out_dir / "final_original.mp4"
        original.write_bytes(b"original")

        svc = MagicMock()
        svc.get_video_asset_path = AsyncMock(
            return_value=str(video.relative_to(tmp_path).as_posix())
        )

        ffmpeg_mock = MagicMock()
        captured: dict[str, Any] = {}

        async def _fake_preview(**kwargs: Any) -> None:
            captured.update(kwargs)
            kwargs["output_path"].write_bytes(b"prev")

        ffmpeg_mock.generate_preview = AsyncMock(side_effect=_fake_preview)
        ffmpeg_mock.get_duration = AsyncMock(return_value=10.0)

        with patch("drevalis.services.ffmpeg.FFmpegService", return_value=ffmpeg_mock):
            await edit_preview(
                ep_id,
                payload=VideoEditRequest(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        # Pin: the source for the preview is the original backup, NOT
        # the (already-edited) current video.
        assert captured["input_path"] == original

    async def test_falls_back_to_current_when_no_backup(self, tmp_path: Path) -> None:
        ep_id = uuid4()
        out_dir = tmp_path / "episodes" / str(ep_id) / "output"
        out_dir.mkdir(parents=True)
        video = out_dir / "final.mp4"
        video.write_bytes(b"current")

        svc = MagicMock()
        svc.get_video_asset_path = AsyncMock(
            return_value=str(video.relative_to(tmp_path).as_posix())
        )

        ffmpeg_mock = MagicMock()
        captured: dict[str, Any] = {}

        async def _fake_preview(**kwargs: Any) -> None:
            captured.update(kwargs)
            kwargs["output_path"].write_bytes(b"prev")

        ffmpeg_mock.generate_preview = AsyncMock(side_effect=_fake_preview)
        ffmpeg_mock.get_duration = AsyncMock(return_value=10.0)

        with patch("drevalis.services.ffmpeg.FFmpegService", return_value=ffmpeg_mock):
            await edit_preview(
                ep_id,
                payload=VideoEditRequest(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        # Source path is the current video (no original backup).
        assert captured["input_path"] == video


# ── edit_reset ─────────────────────────────────────────────────────


class TestEditReset:
    async def test_no_video_asset_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_latest_video_asset = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await edit_reset(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_no_backup_409(self, tmp_path: Path) -> None:
        # Pin: 409 (Conflict) — episode HAS a video, but it's never
        # been edited so there's nothing to reset to.
        ep_id = uuid4()
        out_dir = tmp_path / "episodes" / str(ep_id) / "output"
        out_dir.mkdir(parents=True)
        video = out_dir / "final.mp4"
        video.write_bytes(b"x")
        asset = SimpleNamespace(id=uuid4(), file_path=str(video.relative_to(tmp_path).as_posix()))
        svc = MagicMock()
        svc.get_latest_video_asset = AsyncMock(return_value=asset)
        with pytest.raises(HTTPException) as exc:
            await edit_reset(ep_id, settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 409

    async def test_success_restores_original_and_drops_preview(self, tmp_path: Path) -> None:
        ep_id = uuid4()
        out_dir = tmp_path / "episodes" / str(ep_id) / "output"
        out_dir.mkdir(parents=True)
        video = out_dir / "final.mp4"
        video.write_bytes(b"edited")
        backup = out_dir / "final_original.mp4"
        backup.write_bytes(b"original")
        preview = out_dir / "preview.mp4"
        preview.write_bytes(b"prev")

        asset = SimpleNamespace(id=uuid4(), file_path=str(video.relative_to(tmp_path).as_posix()))
        svc = MagicMock()
        svc.get_latest_video_asset = AsyncMock(return_value=asset)
        svc.update_asset_metadata = AsyncMock()

        ffmpeg_mock = MagicMock()
        ffmpeg_mock.get_duration = AsyncMock(return_value=30.0)

        with patch("drevalis.services.ffmpeg.FFmpegService", return_value=ffmpeg_mock):
            out = await edit_reset(ep_id, settings=_settings(tmp_path), svc=svc)
        # Active video matches the backup contents.
        assert video.read_bytes() == b"original"
        # Preview file was deleted.
        assert not preview.exists()
        assert out.duration_seconds == 30.0


# ── generate_seo ──────────────────────────────────────────────────


class TestGenerateSEO:
    async def test_success_enqueues(self) -> None:
        svc = MagicMock()
        svc.get_with_script_or_raise = AsyncMock()
        redis = MagicMock()
        redis.enqueue_job = AsyncMock()
        out = await generate_seo(uuid4(), redis=redis, svc=svc)
        assert out["status"] == "queued"
        redis.enqueue_job.assert_awaited_once()

    async def test_episode_or_script_missing_404(self) -> None:
        svc = MagicMock()
        svc.get_with_script_or_raise = AsyncMock(side_effect=EpisodeNoScriptError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await generate_seo(uuid4(), redis=MagicMock(), svc=svc)
        assert exc.value.status_code == 404


# ── seo_preflight ──────────────────────────────────────────────────


class TestSeoPreflight:
    async def test_episode_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await seo_preflight(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404

    async def test_routes_to_run_preflight_with_platform(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ep = _make_episode(
            title="Hook",
            topic="topic",
            metadata_={"seo": {"title": "Optimised", "tags": [], "hashtags": []}},
            content_format="longform",
        )
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_thumbnail_asset_path = AsyncMock(return_value=None)

        result_obj = MagicMock()
        result_obj.to_dict = MagicMock(
            return_value={"score": 80, "grade": "B", "blocking": False, "checks": []}
        )

        with patch(
            "drevalis.services.seo_preflight.preflight",
            return_value=result_obj,
        ) as run:
            out = await seo_preflight(ep.id, settings=_settings(tmp_path), svc=svc)
        # longform → youtube_longform platform.
        called_kwargs = run.call_args.kwargs
        assert called_kwargs["platform"] == "youtube_longform"
        assert out.score == 80

    async def test_shorts_format_routes_to_youtube_shorts(self, tmp_path: Path) -> None:
        svc = MagicMock()
        ep = _make_episode(content_format="shorts", metadata_=None)
        svc.get_or_raise = AsyncMock(return_value=ep)
        svc.get_thumbnail_asset_path = AsyncMock(return_value=None)

        result_obj = MagicMock()
        result_obj.to_dict = MagicMock(
            return_value={"score": 0, "grade": "D", "blocking": True, "checks": []}
        )
        with patch(
            "drevalis.services.seo_preflight.preflight",
            return_value=result_obj,
        ) as run:
            await seo_preflight(ep.id, settings=_settings(tmp_path), svc=svc)
        assert run.call_args.kwargs["platform"] == "youtube_shorts"


# ── inpaint_scene ──────────────────────────────────────────────────


class TestInpaintScene:
    async def test_invalid_base64_400(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await inpaint_scene(
                uuid4(),
                1,
                body=InpaintRequest(mask_png_base64="!!!not-base64!!!", prompt="x"),
                settings=_settings(tmp_path),
                redis=AsyncMock(),
                svc=svc,
            )
        assert exc.value.status_code == 400

    async def test_episode_not_found_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await inpaint_scene(
                uuid4(),
                1,
                body=InpaintRequest(
                    mask_png_base64=base64.b64encode(b"\x89PNG").decode(),
                    prompt="x",
                ),
                settings=_settings(tmp_path),
                redis=AsyncMock(),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_success_writes_mask_and_enqueues(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_or_raise = AsyncMock()
        redis = AsyncMock()
        redis.setex = AsyncMock()
        arq = MagicMock()
        arq.enqueue_job = AsyncMock()

        ep_id = uuid4()
        mask_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with patch(
            "drevalis.api.routes.episodes._monolith.get_arq_pool",
            return_value=arq,
        ):
            out = await inpaint_scene(
                ep_id,
                3,
                body=InpaintRequest(
                    mask_png_base64=base64.b64encode(mask_bytes).decode(),
                    prompt="redraw the sky",
                ),
                settings=_settings(tmp_path),
                redis=redis,
                svc=svc,
            )
        assert out["status"] == "enqueued"
        # Mask file landed under episodes/{id}/scenes/.
        mask_path = tmp_path / "episodes" / str(ep_id) / "scenes" / "scene_03.mask.png"
        assert mask_path.exists()
        assert mask_path.read_bytes() == mask_bytes
        # Redis hint persisted with the prompt + 1h TTL.
        redis.setex.assert_awaited_once()
        args = redis.setex.await_args.args
        assert args[0] == f"inpaint:{ep_id}:3"
        assert args[1] == 3600
        assert args[2] == "redraw the sky"
        # arq job enqueued with the prompt as third argument.
        arq.enqueue_job.assert_awaited_once()
        kwargs_args = arq.enqueue_job.call_args.args
        assert kwargs_args[0] == "regenerate_scene"
        assert kwargs_args[1] == str(ep_id)
        assert kwargs_args[2] == 3
        assert kwargs_args[3] == "redraw the sky"


# ── check_script_continuity ────────────────────────────────────────


class TestContinuityCheck:
    async def test_episode_or_script_missing_404(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_with_script_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await check_script_continuity(
                uuid4(),
                db=AsyncMock(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_no_llm_configured_returns_empty(self, tmp_path: Path) -> None:
        # Pin: when no LLM config exists, the route degrades gracefully
        # to issues=[] instead of erroring out. Operators without an
        # LLM can still use the rest of the editor.
        svc = MagicMock()
        svc.get_with_script_or_raise = AsyncMock(return_value=(_make_episode(), MagicMock()))
        cfg_svc = MagicMock()
        cfg_svc.list_all = AsyncMock(return_value=[])
        with patch(
            "drevalis.services.llm_config.LLMConfigService",
            return_value=cfg_svc,
        ):
            out = await check_script_continuity(
                uuid4(),
                db=AsyncMock(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert out.issues == []

    async def test_with_llm_runs_check_continuity(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_with_script_or_raise = AsyncMock(return_value=(_make_episode(), MagicMock()))
        llm_cfg = MagicMock()
        cfg_svc = MagicMock()
        cfg_svc.list_all = AsyncMock(return_value=[llm_cfg])

        issue = MagicMock()
        issue.to_dict = MagicMock(
            return_value={
                "from_scene": 1,
                "to_scene": 2,
                "severity": "warn",
                "issue": "abrupt jump",
                "suggestion": "add transition",
            }
        )

        with (
            patch(
                "drevalis.services.llm_config.LLMConfigService",
                return_value=cfg_svc,
            ),
            patch(
                "drevalis.services.continuity.check_continuity",
                AsyncMock(return_value=[issue]),
            ),
        ):
            out = await check_script_continuity(
                uuid4(),
                db=AsyncMock(),
                settings=_settings(tmp_path),
                svc=svc,
            )
        assert len(out.issues) == 1
        assert out.issues[0].severity == "warn"
