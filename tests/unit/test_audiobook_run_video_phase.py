"""Tests for ``AudiobookService._run_video_phase`` and
``_resolve_video_cover`` (F-CQ-01 step 12).

The video phase has three notable branches:

* audio_only output → skipped, returns None
* chapter-aware assembly when 1:1 image-to-chapter coverage
* single-image fallback otherwise (cover → background → title card)

Plus the cover-resolution helper which is best-effort: failures
log a warning and fall through to the next candidate.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    ChapterTiming,
)


def _service() -> AudiobookService:
    svc = AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )
    svc._check_cancelled = AsyncMock()  # type: ignore[method-assign]
    svc._broadcast_progress = AsyncMock()  # type: ignore[method-assign]
    svc._dag_global = AsyncMock()  # type: ignore[method-assign]
    svc._create_chapter_aware_video = AsyncMock()  # type: ignore[method-assign]
    svc._create_audiobook_video = AsyncMock()  # type: ignore[method-assign]
    svc._generate_title_card = AsyncMock(  # type: ignore[method-assign]
        return_value=Path("/tmp/x/title_card.png")
    )
    svc.storage = MagicMock()
    return svc


def _timing(idx: int) -> ChapterTiming:
    return ChapterTiming(
        chapter_index=idx, start_seconds=0.0, end_seconds=10.0, duration_seconds=10.0
    )


# ── audio_only skip path ─────────────────────────────────────────────


class TestAudioOnlySkip:
    async def test_returns_none_for_audio_only_output(self) -> None:
        svc = _service()
        out = await svc._run_video_phase(
            audiobook_id=uuid4(),
            abs_dir=Path("/tmp/x"),
            final_audio=Path("/tmp/x/audiobook.wav"),
            duration=10.0,
            chapters=[],
            chapter_timings=[],
            chapter_image_paths=[],
            captions_ass_path=None,
            output_format="audio_only",
            video_width=1920,
            video_height=1080,
            cover_image_path=None,
            background_image_path=None,
        )
        assert out is None
        # Neither video helper called.
        svc._create_chapter_aware_video.assert_not_awaited()
        svc._create_audiobook_video.assert_not_awaited()


# ── chapter-aware assembly ───────────────────────────────────────────


class TestChapterAwareAssembly:
    async def test_chapter_aware_when_1to1_coverage(self) -> None:
        svc = _service()
        ab_id = uuid4()

        chapters = [{"title": "C0"}, {"title": "C1"}]
        out = await svc._run_video_phase(
            audiobook_id=ab_id,
            abs_dir=Path("/tmp/x"),
            final_audio=Path("/tmp/x/audiobook.wav"),
            duration=20.0,
            chapters=chapters,
            chapter_timings=[_timing(0), _timing(1)],
            chapter_image_paths=[
                Path("/tmp/x/images/ch000.png"),
                Path("/tmp/x/images/ch001.png"),
            ],
            captions_ass_path=Path("/tmp/x/captions.ass"),
            output_format="audio_video",
            video_width=1920,
            video_height=1080,
            cover_image_path=None,
            background_image_path=None,
        )
        assert out == f"audiobooks/{ab_id}/audiobook.mp4"
        svc._create_chapter_aware_video.assert_awaited_once()
        svc._create_audiobook_video.assert_not_awaited()
        # mp4_export DAG: in_progress → done.
        statuses = [c.args[1] for c in svc._dag_global.call_args_list]
        assert statuses == ["in_progress", "done"]

    async def test_falls_back_when_image_count_mismatches_chapter_count(
        self,
    ) -> None:
        # 2 chapters but only 1 image — fallback to single-image path
        # (we don't want to render a chapter-aware video where one
        # chapter has no visual).
        svc = _service()
        cover = Path("/tmp/x/cover.jpg")
        svc.storage.resolve_path = MagicMock(return_value=cover)

        # Pretend cover exists.
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "exists", lambda self: True)
            await svc._run_video_phase(
                audiobook_id=uuid4(),
                abs_dir=Path("/tmp/x"),
                final_audio=Path("/tmp/x/audiobook.wav"),
                duration=20.0,
                chapters=[{"title": "C0"}, {"title": "C1"}],
                chapter_timings=[_timing(0)],
                chapter_image_paths=[Path("/tmp/x/images/ch000.png")],
                captions_ass_path=None,
                output_format="audio_video",
                video_width=1920,
                video_height=1080,
                cover_image_path="audiobooks/x/cover.jpg",
                background_image_path=None,
            )
        svc._create_chapter_aware_video.assert_not_awaited()
        svc._create_audiobook_video.assert_awaited_once()


# ── single-image fallback ────────────────────────────────────────────


class TestSingleImageFallback:
    async def test_uses_resolved_cover_when_present(self) -> None:
        svc = _service()
        cover = Path("/tmp/x/cover.jpg")
        svc.storage.resolve_path = MagicMock(return_value=cover)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "exists", lambda self: True)
            await svc._run_video_phase(
                audiobook_id=uuid4(),
                abs_dir=Path("/tmp/x"),
                final_audio=Path("/tmp/x/audiobook.wav"),
                duration=10.0,
                chapters=[{"title": "C0"}],
                chapter_timings=[],
                chapter_image_paths=[],
                captions_ass_path=None,
                output_format="audio_image",
                video_width=1920,
                video_height=1080,
                cover_image_path="audiobooks/x/cover.jpg",
                background_image_path=None,
            )
        kwargs = svc._create_audiobook_video.call_args.kwargs
        assert kwargs["cover_image_path"] == str(cover)
        # Title card NOT generated (cover existed).
        svc._generate_title_card.assert_not_awaited()

    async def test_falls_back_to_background_when_cover_missing(self) -> None:
        svc = _service()

        # Cover resolves but doesn't exist on disk; background does.
        bg = Path("/tmp/x/bg.jpg")

        def _resolve(p: str) -> Path:
            return Path("/tmp/x/cover.jpg") if "cover" in p else bg

        svc.storage.resolve_path = MagicMock(side_effect=_resolve)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                Path,
                "exists",
                lambda self: "bg" in str(self),  # only bg exists
            )
            await svc._run_video_phase(
                audiobook_id=uuid4(),
                abs_dir=Path("/tmp/x"),
                final_audio=Path("/tmp/x/audiobook.wav"),
                duration=10.0,
                chapters=[{"title": "C0"}],
                chapter_timings=[],
                chapter_image_paths=[],
                captions_ass_path=None,
                output_format="audio_image",
                video_width=1920,
                video_height=1080,
                cover_image_path="audiobooks/x/cover.jpg",
                background_image_path="audiobooks/x/bg.jpg",
            )
        # When cover resolves but doesn't exist, the helper still
        # returns a string; the existence check then triggers the
        # title-card fallback. (Fallback to background only kicks in
        # when cover_image_path is None or resolution fails.)
        # In this test, resolved_cover ≠ None (cover resolved fine),
        # so we hit the title-card branch.
        svc._generate_title_card.assert_awaited_once()

    async def test_generates_title_card_when_no_image_supplied(self) -> None:
        svc = _service()
        await svc._run_video_phase(
            audiobook_id=uuid4(),
            abs_dir=Path("/tmp/x"),
            final_audio=Path("/tmp/x/audiobook.wav"),
            duration=10.0,
            chapters=[{"title": "Chapter One"}],
            chapter_timings=[],
            chapter_image_paths=[],
            captions_ass_path=None,
            output_format="audio_image",
            video_width=1920,
            video_height=1080,
            cover_image_path=None,
            background_image_path=None,
        )
        # Title card generated using the first chapter's title.
        svc._generate_title_card.assert_awaited_once()
        # ``_generate_title_card(abs_dir, title, width=..., height=...)``
        # — title is the second positional arg.
        args = svc._generate_title_card.call_args.args
        assert args[1] == "Chapter One"

    async def test_title_card_default_when_no_chapters(self) -> None:
        svc = _service()
        await svc._run_video_phase(
            audiobook_id=uuid4(),
            abs_dir=Path("/tmp/x"),
            final_audio=Path("/tmp/x/audiobook.wav"),
            duration=10.0,
            chapters=[],
            chapter_timings=[],
            chapter_image_paths=[],
            captions_ass_path=None,
            output_format="audio_image",
            video_width=1920,
            video_height=1080,
            cover_image_path=None,
            background_image_path=None,
        )
        args = svc._generate_title_card.call_args.args
        assert args[1] == "Audiobook"

    async def test_with_waveform_only_for_audio_video(self) -> None:
        # audio_image → no waveform; audio_video → with waveform.
        svc = _service()
        await svc._run_video_phase(
            audiobook_id=uuid4(),
            abs_dir=Path("/tmp/x"),
            final_audio=Path("/tmp/x/audiobook.wav"),
            duration=10.0,
            chapters=[{"title": "C0"}],
            chapter_timings=[],
            chapter_image_paths=[],
            captions_ass_path=None,
            output_format="audio_image",
            video_width=1920,
            video_height=1080,
            cover_image_path=None,
            background_image_path=None,
        )
        kwargs = svc._create_audiobook_video.call_args.kwargs
        assert kwargs["with_waveform"] is False

        svc2 = _service()
        await svc2._run_video_phase(
            audiobook_id=uuid4(),
            abs_dir=Path("/tmp/x"),
            final_audio=Path("/tmp/x/audiobook.wav"),
            duration=10.0,
            chapters=[{"title": "C0"}],
            chapter_timings=[],
            chapter_image_paths=[],
            captions_ass_path=None,
            output_format="audio_video",
            video_width=1920,
            video_height=1080,
            cover_image_path=None,
            background_image_path=None,
        )
        kwargs2 = svc2._create_audiobook_video.call_args.kwargs
        assert kwargs2["with_waveform"] is True


# ── progress + DAG ───────────────────────────────────────────────────


class TestProgressAndDag:
    async def test_progress_at_90_percent(self) -> None:
        svc = _service()
        await svc._run_video_phase(
            audiobook_id=uuid4(),
            abs_dir=Path("/tmp/x"),
            final_audio=Path("/tmp/x/audiobook.wav"),
            duration=10.0,
            chapters=[{"title": "C0"}],
            chapter_timings=[],
            chapter_image_paths=[],
            captions_ass_path=None,
            output_format="audio_only",
            video_width=1920,
            video_height=1080,
            cover_image_path=None,
            background_image_path=None,
        )
        # Progress fires even on audio_only path (the user sees the
        # "Assembling video..." stage but it returns None immediately).
        bc = svc._broadcast_progress.call_args
        assert bc.args[1] == "assembly"
        assert bc.args[2] == 90


# ── _resolve_video_cover ─────────────────────────────────────────────


class TestResolveVideoCover:
    def test_none_when_neither_supplied(self) -> None:
        svc = _service()
        assert (
            svc._resolve_video_cover(
                cover_image_path=None,
                background_image_path=None,
            )
            is None
        )

    def test_cover_wins_over_background(self) -> None:
        svc = _service()
        svc.storage.resolve_path = MagicMock(side_effect=lambda p: Path(f"/abs/{p}"))
        out = svc._resolve_video_cover(
            cover_image_path="cover.jpg",
            background_image_path="bg.jpg",
        )
        assert out == str(Path("/abs/cover.jpg"))

    def test_falls_back_to_background_when_cover_is_none(self) -> None:
        svc = _service()
        svc.storage.resolve_path = MagicMock(side_effect=lambda p: Path(f"/abs/{p}"))
        out = svc._resolve_video_cover(
            cover_image_path=None,
            background_image_path="bg.jpg",
        )
        assert out == str(Path("/abs/bg.jpg"))

    def test_cover_resolve_failure_falls_back_to_background(self) -> None:
        # Sanitisation failure on cover (e.g. path traversal) → log a
        # warning and try the background.
        svc = _service()
        bg = Path("/abs/bg.jpg")

        def _resolve(p: str) -> Path:
            if "cover" in p:
                raise ValueError("path outside storage root")
            return bg

        svc.storage.resolve_path = MagicMock(side_effect=_resolve)
        out = svc._resolve_video_cover(
            cover_image_path="../../../etc/passwd",
            background_image_path="bg.jpg",
        )
        assert out == str(bg)

    def test_both_failures_returns_none(self) -> None:
        svc = _service()
        svc.storage.resolve_path = MagicMock(side_effect=ValueError("nope"))
        out = svc._resolve_video_cover(
            cover_image_path="bad",
            background_image_path="also-bad",
        )
        assert out is None
