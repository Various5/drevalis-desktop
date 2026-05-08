"""Tests for the RenderPlan data structures + builder (Task 13)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    AudioChunk,
    ChapterTiming,
    _strip_chunk_hash,
)
from drevalis.services.audiobook.render_plan import (
    AudioEvent,
    ChapterMarker,
    RenderPlan,
)


def _make_chunk(
    tmp_path: Path,
    chapter: int,
    chunk: int,
    speaker: str = "Narrator",
    hash_suffix: str = "a1b2c3d4e5f6",
) -> AudioChunk:
    p = tmp_path / f"ch{chapter:03d}_chunk_{chunk:04d}_{hash_suffix}.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 1024)
    return AudioChunk(
        path=p,
        chapter_index=chapter,
        speaker=speaker,
        block_index=0,
        chunk_index=chunk,
    )


def _make_sfx_chunk(tmp_path: Path, chapter: int, block: int) -> AudioChunk:
    p = tmp_path / f"ch{chapter:03d}_sfx_{block:04d}.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 1024)
    return AudioChunk(
        path=p,
        chapter_index=chapter,
        speaker="__SFX__",
        block_index=block,
        chunk_index=0,
    )


# ── AudioEvent / ChapterMarker / RenderPlan immutability ─────────────────


class TestImmutability:
    def test_audio_event_is_frozen(self) -> None:
        e = AudioEvent(
            kind="voice",
            chapter_idx=0,
            start_ms=0,
            duration_ms=1000,
        )
        with pytest.raises(FrozenInstanceError):
            e.start_ms = 999  # type: ignore[misc]

    def test_chapter_marker_is_frozen(self) -> None:
        m = ChapterMarker(chapter_idx=0, title="x", start_ms=0, end_ms=100)
        with pytest.raises(FrozenInstanceError):
            m.title = "y"  # type: ignore[misc]

    def test_render_plan_is_frozen(self) -> None:
        plan = RenderPlan(
            audiobook_id="ab",
            events=(),
            chapters=(),
            total_duration_ms=0,
        )
        with pytest.raises(FrozenInstanceError):
            plan.total_duration_ms = 1  # type: ignore[misc]

    def test_chapter_marker_duration_property(self) -> None:
        m = ChapterMarker(chapter_idx=0, title="x", start_ms=1000, end_ms=5500)
        assert m.duration_ms == 4500

    def test_chapter_marker_duration_clamped(self) -> None:
        # Pathological: start > end shouldn't yield a negative duration.
        m = ChapterMarker(chapter_idx=0, title="x", start_ms=10, end_ms=5)
        assert m.duration_ms == 0


# ── from_pipeline_outputs ────────────────────────────────────────────────


class TestFromPipelineOutputs:
    def test_single_chapter_single_chunk(self, tmp_path: Path) -> None:
        chunk = _make_chunk(tmp_path, 0, 0)
        timing = ChapterTiming(
            chapter_index=0,
            start_seconds=0.0,
            end_seconds=5.0,
            duration_seconds=5.0,
        )
        plan = RenderPlan.from_pipeline_outputs(
            audiobook_id="test",
            inline_chunks=[chunk],
            chapter_timings=[timing],
            chapters=[{"title": "Chapter One", "text": "..."}],
            chunk_durations_seconds={chunk.path.stem: 5.0},
        )
        assert len(plan.events) == 1
        ev = plan.events[0]
        assert ev.kind == "voice"
        assert ev.chapter_idx == 0
        assert ev.duration_ms == 5000
        assert ev.start_ms == 0
        assert ev.clip_id == "ch000_chunk_0000"
        assert plan.chapters[0].title == "Chapter One"
        assert plan.chapters[0].start_ms == 0
        assert plan.chapters[0].end_ms == 5000
        assert plan.total_duration_ms == 5000

    def test_event_start_ms_accumulates(self, tmp_path: Path) -> None:
        chunks = [_make_chunk(tmp_path, 0, i) for i in range(3)]
        timings = [
            ChapterTiming(0, 0.0, 6.0, 6.0),
        ]
        durations = {c.path.stem: 2.0 for c in chunks}
        plan = RenderPlan.from_pipeline_outputs(
            audiobook_id="test",
            inline_chunks=chunks,
            chapter_timings=timings,
            chapters=[{"title": "One", "text": "..."}],
            chunk_durations_seconds=durations,
        )
        assert [ev.start_ms for ev in plan.events] == [0, 2000, 4000]

    def test_sfx_chunks_emit_sfx_events(self, tmp_path: Path) -> None:
        v0 = _make_chunk(tmp_path, 0, 0)
        sfx = _make_sfx_chunk(tmp_path, 0, 5)
        v1 = _make_chunk(tmp_path, 0, 1)
        plan = RenderPlan.from_pipeline_outputs(
            audiobook_id="test",
            inline_chunks=[v0, sfx, v1],
            chapter_timings=[ChapterTiming(0, 0.0, 7.0, 7.0)],
            chapters=[{"title": "One", "text": "..."}],
            chunk_durations_seconds={
                v0.path.stem: 2.0,
                sfx.path.stem: 3.0,
                v1.path.stem: 2.0,
            },
        )
        kinds = [ev.kind for ev in plan.events]
        assert kinds == ["voice", "sfx", "voice"]
        # SFX events have no speaker_id.
        assert plan.events[1].speaker_id is None
        # Voice events do.
        assert plan.events[0].speaker_id == "Narrator"

    def test_missing_duration_yields_zero_duration_event(self, tmp_path: Path) -> None:
        chunk = _make_chunk(tmp_path, 0, 0)
        plan = RenderPlan.from_pipeline_outputs(
            audiobook_id="test",
            inline_chunks=[chunk],
            chapter_timings=[ChapterTiming(0, 0.0, 5.0, 5.0)],
            chapters=[{"title": "One", "text": "..."}],
            chunk_durations_seconds={},  # empty → zero
        )
        assert plan.events[0].duration_ms == 0

    def test_chapter_title_truncated_to_120(self, tmp_path: Path) -> None:
        chunk = _make_chunk(tmp_path, 0, 0)
        long_title = "x" * 200
        plan = RenderPlan.from_pipeline_outputs(
            audiobook_id="test",
            inline_chunks=[chunk],
            chapter_timings=[ChapterTiming(0, 0.0, 1.0, 1.0)],
            chapters=[{"title": long_title, "text": "..."}],
            chunk_durations_seconds={chunk.path.stem: 1.0},
        )
        assert len(plan.chapters[0].title) <= 120

    def test_clip_ids_match_list_clips_derivation(self, tmp_path: Path) -> None:
        # The Task 1 contract is that clip_id == _strip_chunk_hash(stem).
        # Render plan must produce the same IDs the editor's list_clips
        # emits — that's the "single source of truth" promise.
        chunk = _make_chunk(tmp_path, 3, 7, hash_suffix="a1b2c3d4e5f6")
        plan = RenderPlan.from_pipeline_outputs(
            audiobook_id="test",
            inline_chunks=[chunk],
            chapter_timings=[ChapterTiming(3, 0.0, 1.0, 1.0)],
            chapters=[{"title": f"Chapter {i + 1}", "text": "..."} for i in range(4)],
            chunk_durations_seconds={chunk.path.stem: 1.0},
        )
        # plan.clip_ids() should match what _strip_chunk_hash gives us.
        from_strip = _strip_chunk_hash(chunk.path.stem)
        assert plan.clip_ids() == [from_strip]
        assert from_strip == "ch003_chunk_0007"


# ── apply_priming_offset ─────────────────────────────────────────────────


class TestApplyPrimingOffset:
    def _sample_plan(self) -> RenderPlan:
        return RenderPlan(
            audiobook_id="test",
            events=(),
            chapters=(
                ChapterMarker(0, "One", 0, 60000),
                ChapterMarker(1, "Two", 60000, 120000),
            ),
            total_duration_ms=120000,
        )

    def test_zero_offset_returns_self(self) -> None:
        plan = self._sample_plan()
        assert plan.apply_priming_offset(0) is plan

    def test_positive_offset_shifts_chapters(self) -> None:
        plan = self._sample_plan()
        shifted = plan.apply_priming_offset(26)
        assert shifted.chapters[0].start_ms == 26
        assert shifted.chapters[0].end_ms == 60026
        assert shifted.chapters[1].start_ms == 60026
        assert shifted.chapters[1].end_ms == 120026
        assert shifted.total_duration_ms == 120026
        assert shifted.metadata.get("lame_priming_offset_ms") == 26

    def test_offset_does_not_mutate_original(self) -> None:
        plan = self._sample_plan()
        plan.apply_priming_offset(26)
        # Original frozen plan unchanged.
        assert plan.chapters[0].start_ms == 0
        assert plan.chapters[1].end_ms == 120000

    def test_negative_offset_clamped_to_zero(self) -> None:
        plan = self._sample_plan()
        # An MP3 *shorter* than the WAV is unusual but the math should
        # still produce a valid plan (start_ms clamped to ≥ 0).
        shifted = plan.apply_priming_offset(-100)
        assert shifted.chapters[0].start_ms == 0  # clamped


# ── to_dict ─────────────────────────────────────────────────────────────


class TestToDict:
    def test_round_trip_shape(self, tmp_path: Path) -> None:
        chunk = _make_chunk(tmp_path, 0, 0)
        plan = RenderPlan.from_pipeline_outputs(
            audiobook_id="ab-uuid",
            inline_chunks=[chunk],
            chapter_timings=[ChapterTiming(0, 0.0, 5.0, 5.0)],
            chapters=[{"title": "Chapter One", "text": "..."}],
            chunk_durations_seconds={chunk.path.stem: 5.0},
        )
        d = plan.to_dict()
        assert d["audiobook_id"] == "ab-uuid"
        assert isinstance(d["events"], list)
        assert d["events"][0]["clip_id"] == "ch000_chunk_0000"
        assert d["chapters"][0]["title"] == "Chapter One"
        assert d["total_duration_ms"] == 5000
        # JSON-serialisable.
        import json

        json.dumps(d)


# ── Service-side persist callback ────────────────────────────────────────


class TestServicePersistRenderPlan:
    """``_persist_render_plan`` fires the worker's callback with the
    serialised plan blob; failures are swallowed."""

    async def test_callback_invoked_with_plan_blob(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock

        captured: list[dict] = []

        async def _cb(blob: dict) -> None:
            captured.append(blob)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=AsyncMock(),
        )
        service._persist_render_plan_cb = _cb

        chunk = _make_chunk(tmp_path, 0, 0)
        plan = RenderPlan.from_pipeline_outputs(
            audiobook_id="ab",
            inline_chunks=[chunk],
            chapter_timings=[ChapterTiming(0, 0.0, 1.0, 1.0)],
            chapters=[{"title": "One", "text": "..."}],
            chunk_durations_seconds={chunk.path.stem: 1.0},
        )

        await service._persist_render_plan(plan)

        assert len(captured) == 1
        assert captured[0]["audiobook_id"] == "ab"
        assert captured[0]["total_duration_ms"] == 1000

    async def test_callback_failure_swallowed(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock

        async def _cb(blob: dict) -> None:
            raise ConnectionError("postgres down")

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=AsyncMock(),
        )
        service._persist_render_plan_cb = _cb

        plan = RenderPlan(
            audiobook_id="ab",
            events=(),
            chapters=(),
            total_duration_ms=0,
        )

        # Must not raise.
        await service._persist_render_plan(plan)

    async def test_no_callback_is_noop(self) -> None:
        from unittest.mock import AsyncMock

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=AsyncMock(),
        )
        # No _persist_render_plan_cb stashed.
        plan = RenderPlan(
            audiobook_id="ab",
            events=(),
            chapters=(),
            total_duration_ms=0,
        )
        await service._persist_render_plan(plan)  # no raise
