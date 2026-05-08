"""Tests for ``AudiobookService._run_concat_phase`` (F-CQ-01 step 6).

Covers the concat → RenderPlan → silence-trim → chapter-timing-store
phase. The contract pinned here:

* Concat receives every chunk in iteration order, writes to
  ``audiobook.wav`` in the per-call output dir.
* RenderPlan excludes overlay SFX from the inline timeline.
* Silence trim only runs when ``settings.trim_leading_trailing_silence``.
* Trim shifts every chapter timing by the leading offset.
* Chapter dicts are mutated in place with rounded timing fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    AudiobookSettings,
    AudioChunk,
    ChapterTiming,
)


def _service(*, trim: bool = False) -> AudiobookService:
    svc = AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )
    # All async helper methods stubbed so the orchestrator-level test
    # focuses on the phase logic.
    svc._check_cancelled = AsyncMock()  # type: ignore[method-assign]
    svc._broadcast_progress = AsyncMock()  # type: ignore[method-assign]
    svc._dag_global = AsyncMock()  # type: ignore[method-assign]
    svc._concatenate_with_context = AsyncMock(return_value=[])  # type: ignore[method-assign]
    svc._persist_render_plan = AsyncMock()  # type: ignore[method-assign]
    svc._trim_silence_in_place = AsyncMock(return_value=0.0)  # type: ignore[method-assign]
    svc._is_overlay_sfx = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc.ffmpeg = AsyncMock()
    svc.ffmpeg.get_duration = AsyncMock(return_value=1.0)
    svc._settings = AudiobookSettings(trim_leading_trailing_silence=trim)
    return svc


def _chunk(idx: int) -> AudioChunk:
    return AudioChunk(
        path=Path(f"/tmp/chunk_{idx}.wav"),
        chapter_index=0,
        speaker="Narrator",
        block_index=0,
        chunk_index=idx,
    )


def _timing(idx: int, start: float, end: float) -> ChapterTiming:
    return ChapterTiming(
        chapter_index=idx,
        start_seconds=start,
        end_seconds=end,
        duration_seconds=end - start,
    )


# ── Concat + DAG transitions ─────────────────────────────────────────


class TestConcatBasics:
    async def test_writes_to_audiobook_wav_in_abs_dir(self) -> None:
        svc = _service()
        chapters = [{"index": 0, "title": "C0", "text": "..."}]
        final_audio, _ = await svc._run_concat_phase(
            all_chunks=[_chunk(0)],
            abs_dir=Path("/tmp/audiobook-x"),
            audiobook_id=uuid4(),
            chapters=chapters,
        )
        assert final_audio == Path("/tmp/audiobook-x/audiobook.wav")
        # Concat helper called with the full chunk list and that path.
        args = svc._concatenate_with_context.call_args.args
        assert args[1] == final_audio

    async def test_dag_concat_transitions(self) -> None:
        svc = _service()
        await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=[],
        )
        statuses = [c.args[1] for c in svc._dag_global.call_args_list]
        assert statuses == ["in_progress", "done"]

    async def test_cancellation_checked_before_concat(self) -> None:
        svc = _service()
        await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=[],
        )
        svc._check_cancelled.assert_awaited_once()

    async def test_progress_at_50_percent(self) -> None:
        svc = _service()
        await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=[],
        )
        # The mixing phase broadcasts at 50% (between TTS and image gen).
        bc = svc._broadcast_progress.call_args
        assert bc.args[1] == "mixing"
        assert bc.args[2] == 50


# ── RenderPlan ───────────────────────────────────────────────────────


class TestRenderPlan:
    async def test_overlay_sfx_excluded_from_inline_chunks(self) -> None:
        svc = _service()
        # Mark every other chunk as an overlay SFX.
        sfx_indexes = {1, 3}
        svc._is_overlay_sfx = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda c: c.chunk_index in sfx_indexes
        )

        chunks = [_chunk(i) for i in range(4)]
        await svc._run_concat_phase(
            all_chunks=chunks,
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=[],
        )
        # 4 chunks total, 2 overlay SFX → 2 inline-only durations probed.
        assert svc.ffmpeg.get_duration.await_count == 2

    async def test_render_plan_persisted_via_callback(self) -> None:
        svc = _service()
        await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=[],
        )
        svc._persist_render_plan.assert_awaited_once()
        # Render plan also stashed on the instance for later use
        # (priming-offset application during MP3 export).
        assert svc._render_plan is not None

    async def test_chunk_duration_failure_falls_back_to_zero(self) -> None:
        # If ffprobe/get_duration blows up on a single chunk, the
        # whole phase must NOT abort — fall back to 0.0 for that chunk.
        svc = _service()
        svc.ffmpeg.get_duration = AsyncMock(  # type: ignore[method-assign]
            side_effect=[1.0, RuntimeError("ffprobe died"), 2.0]
        )
        await svc._run_concat_phase(
            all_chunks=[_chunk(0), _chunk(1), _chunk(2)],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=[],
        )
        # Render plan still persisted despite the per-chunk failure.
        svc._persist_render_plan.assert_awaited_once()


# ── Silence trim ─────────────────────────────────────────────────────


class TestSilenceTrim:
    async def test_no_trim_when_setting_disabled(self) -> None:
        svc = _service(trim=False)
        await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=[],
        )
        svc._trim_silence_in_place.assert_not_awaited()

    async def test_trim_called_when_setting_enabled(self) -> None:
        svc = _service(trim=True)
        await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=[],
        )
        svc._trim_silence_in_place.assert_awaited_once()

    async def test_zero_offset_does_not_shift_timings(self) -> None:
        # When trim returns 0 (nothing to trim), timings pass through
        # unshifted.
        svc = _service(trim=True)
        svc._trim_silence_in_place = AsyncMock(return_value=0.0)  # type: ignore[method-assign]
        original_timing = _timing(0, 1.0, 5.0)
        svc._concatenate_with_context = AsyncMock(  # type: ignore[method-assign]
            return_value=[original_timing]
        )

        chapters = [{"index": 0, "title": "C0", "text": "..."}]
        _, timings = await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=chapters,
        )
        # Timing unchanged.
        assert timings[0].start_seconds == 1.0

    async def test_positive_offset_shifts_timings(self) -> None:
        svc = _service(trim=True)
        svc._trim_silence_in_place = AsyncMock(return_value=0.5)  # type: ignore[method-assign]
        # Stub the shift helper to confirm it's actually called.
        shifted = [_timing(0, 0.5, 4.5)]
        svc._shift_chapter_timings = MagicMock(return_value=shifted)  # type: ignore[method-assign]
        svc._concatenate_with_context = AsyncMock(  # type: ignore[method-assign]
            return_value=[_timing(0, 1.0, 5.0)]
        )

        chapters = [{"index": 0, "title": "C0", "text": "..."}]
        _, timings = await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=chapters,
        )
        # Shift helper called with the trim offset.
        svc._shift_chapter_timings.assert_called_once()
        offset = svc._shift_chapter_timings.call_args.args[1]
        assert offset == 0.5
        # Returned timings reflect the shift.
        assert timings == shifted


# ── Chapter timing storage ───────────────────────────────────────────


class TestChapterTimingStorage:
    async def test_chapter_dicts_get_timing_fields(self) -> None:
        svc = _service()
        svc._concatenate_with_context = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                _timing(0, 0.0, 10.123456),
                _timing(1, 10.123456, 25.987654),
            ]
        )
        chapters: list[dict[str, Any]] = [
            {"index": 0, "title": "C0", "text": "..."},
            {"index": 1, "title": "C1", "text": "..."},
        ]
        await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=chapters,
        )
        # Rounded to 3 decimal places.
        assert chapters[0]["start_seconds"] == 0.0
        assert chapters[0]["end_seconds"] == 10.123
        assert chapters[1]["start_seconds"] == 10.123
        assert chapters[1]["end_seconds"] == 25.988
        assert chapters[1]["duration_seconds"] == round(15.864198, 3)

    async def test_extra_timings_dont_index_out_of_chapters(self) -> None:
        # Defensive: if concat returns more timings than chapters
        # (shouldn't happen in practice but the guard is there), the
        # excess is silently skipped instead of crashing.
        svc = _service()
        svc._concatenate_with_context = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                _timing(0, 0.0, 5.0),
                _timing(99, 5.0, 10.0),  # out-of-range chapter index
            ]
        )
        chapters: list[dict[str, Any]] = [{"index": 0, "title": "C0", "text": "..."}]
        # Must not raise IndexError.
        await svc._run_concat_phase(
            all_chunks=[],
            abs_dir=Path("/tmp/x"),
            audiobook_id=uuid4(),
            chapters=chapters,
        )
        assert chapters[0]["start_seconds"] == 0.0
