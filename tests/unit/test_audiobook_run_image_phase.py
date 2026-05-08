"""Tests for ``AudiobookService._run_image_phase`` (F-CQ-01 step 7).

The image phase is non-fatal — chapter image generation failure must
NOT abort the audiobook (we still want a usable WAV/MP3 output).
The contract pinned here:

* Skipped entirely when image gen disabled OR output_format=audio_only
* DAG flipped to in_progress for every chapter, then done on success
* Image paths written into chapter dicts on success
* Exception caught, every chapter's DAG flipped to failed, no re-raise
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from drevalis.services.audiobook._monolith import AudiobookService


def _service() -> AudiobookService:
    svc = AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )
    svc._broadcast_progress = AsyncMock()  # type: ignore[method-assign]
    svc._dag_chapter = AsyncMock()  # type: ignore[method-assign]
    svc._generate_chapter_images = AsyncMock(return_value=[])  # type: ignore[method-assign]
    return svc


# ── Skip paths ───────────────────────────────────────────────────────


class TestSkipPaths:
    async def test_skipped_when_image_gen_disabled(self) -> None:
        svc = _service()
        out = await svc._run_image_phase(
            chapters=[{"index": 0}],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            output_format="audio_video",
            image_generation_enabled=False,
            video_width=1920,
            video_height=1080,
        )
        assert out == []
        # No DAG transitions, no progress broadcast.
        svc._broadcast_progress.assert_not_awaited()
        svc._dag_chapter.assert_not_awaited()
        svc._generate_chapter_images.assert_not_awaited()

    async def test_skipped_for_audio_only_output(self) -> None:
        # Even with image_generation_enabled=True, audio_only has no
        # place to display the image.
        svc = _service()
        out = await svc._run_image_phase(
            chapters=[{"index": 0}],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            output_format="audio_only",
            image_generation_enabled=True,
            video_width=1920,
            video_height=1080,
        )
        assert out == []
        svc._generate_chapter_images.assert_not_awaited()

    @pytest.mark.parametrize("fmt", ["audio_image", "audio_video"])
    async def test_runs_for_image_friendly_formats(self, fmt: str) -> None:
        svc = _service()
        await svc._run_image_phase(
            chapters=[{"index": 0}],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            output_format=fmt,
            image_generation_enabled=True,
            video_width=1920,
            video_height=1080,
        )
        svc._generate_chapter_images.assert_awaited_once()


# ── Happy path ───────────────────────────────────────────────────────


class TestHappyPath:
    async def test_progress_at_55_percent(self) -> None:
        svc = _service()
        await svc._run_image_phase(
            chapters=[{"index": 0}],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            output_format="audio_image",
            image_generation_enabled=True,
            video_width=1920,
            video_height=1080,
        )
        bc = svc._broadcast_progress.call_args
        assert bc.args[1] == "images"
        assert bc.args[2] == 55

    async def test_dag_in_progress_then_done_for_each_chapter(self) -> None:
        svc = _service()
        svc._generate_chapter_images = AsyncMock(  # type: ignore[method-assign]
            return_value=[Path("/tmp/x/ch000.png"), Path("/tmp/x/ch001.png")]
        )
        chapters: list[dict[str, Any]] = [{"index": 0}, {"index": 1}]
        await svc._run_image_phase(
            chapters=chapters,
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            output_format="audio_video",
            image_generation_enabled=True,
            video_width=1920,
            video_height=1080,
        )
        statuses = [c.args[2] for c in svc._dag_chapter.call_args_list]
        # Two in_progress (one per chapter, up front), then two done.
        assert statuses[:2] == ["in_progress", "in_progress"]
        assert statuses[2:] == ["done", "done"]

    async def test_image_path_written_into_chapter_dict(self) -> None:
        svc = _service()
        ab_id = uuid4()
        svc._generate_chapter_images = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                Path(f"/tmp/x/audiobooks/{ab_id}/images/ch000.png"),
                Path(f"/tmp/x/audiobooks/{ab_id}/images/ch001.png"),
            ]
        )
        chapters: list[dict[str, Any]] = [{"index": 0}, {"index": 1}]
        await svc._run_image_phase(
            chapters=chapters,
            abs_dir=Path(f"/tmp/x/audiobooks/{ab_id}"),
            audiobook_id=ab_id,
            output_format="audio_image",
            image_generation_enabled=True,
            video_width=1920,
            video_height=1080,
        )
        # Storage-relative path written into each chapter.
        assert chapters[0]["image_path"] == f"audiobooks/{ab_id}/images/ch000.png"
        assert chapters[1]["image_path"] == f"audiobooks/{ab_id}/images/ch001.png"

    async def test_returns_image_path_list(self) -> None:
        svc = _service()
        paths = [Path("/tmp/x/ch000.png"), Path("/tmp/x/ch001.png")]
        svc._generate_chapter_images = AsyncMock(  # type: ignore[method-assign]
            return_value=paths
        )
        out = await svc._run_image_phase(
            chapters=[{"index": 0}, {"index": 1}],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            output_format="audio_image",
            image_generation_enabled=True,
            video_width=1920,
            video_height=1080,
        )
        assert out == paths


# ── Failure path (must not re-raise) ────────────────────────────────


class TestFailureNonFatal:
    async def test_exception_caught_dag_marked_failed(self) -> None:
        # CRITICAL: image-gen failure must NOT abort the audiobook.
        # Pin that the exception is swallowed and every chapter's DAG
        # is flipped to ``failed`` so the UI can show the partial state.
        svc = _service()
        svc._generate_chapter_images = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("ComfyUI down")
        )
        chapters = [{"index": 0}, {"index": 1}, {"index": 2}]
        # Must not raise.
        out = await svc._run_image_phase(
            chapters=chapters,
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            output_format="audio_image",
            image_generation_enabled=True,
            video_width=1920,
            video_height=1080,
        )
        # No image paths returned.
        assert out == []
        # All three chapters first marked in_progress, then failed.
        statuses = [c.args[2] for c in svc._dag_chapter.call_args_list]
        # First three are in_progress (set up front), then three failed.
        assert statuses[:3] == ["in_progress", "in_progress", "in_progress"]
        assert statuses[3:] == ["failed", "failed", "failed"]
        # Chapter dicts NOT mutated with image_path on failure.
        for ch in chapters:
            assert "image_path" not in ch


# ── Dimension propagation ────────────────────────────────────────────


class TestDimensionPropagation:
    async def test_width_and_height_passed_to_helper(self) -> None:
        svc = _service()
        await svc._run_image_phase(
            chapters=[{"index": 0}],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            output_format="audio_video",
            image_generation_enabled=True,
            video_width=1080,
            video_height=1920,
        )
        kwargs = svc._generate_chapter_images.call_args.kwargs
        assert kwargs["video_width"] == 1080
        assert kwargs["video_height"] == 1920
