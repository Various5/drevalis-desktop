"""Tests for ``AudiobookService._run_music_phase`` and
``_swap_in_mixed_audio`` (F-CQ-01 step 8).

Music phase is non-fatal — a music-mix failure must NOT block
audiobook completion. The swap helper has the trickiest invariant
in the whole monolith: backup → rename mixed → drop backup, with
**rollback on failure**. Pin every branch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
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
    svc._dag_chapter = AsyncMock()  # type: ignore[method-assign]
    svc._add_chapter_music = AsyncMock()  # type: ignore[method-assign]
    svc._add_music = AsyncMock()  # type: ignore[method-assign]
    return svc


def _timing(idx: int) -> ChapterTiming:
    return ChapterTiming(
        chapter_index=idx, start_seconds=0.0, end_seconds=10.0, duration_seconds=10.0
    )


# ── _run_music_phase: skip paths ─────────────────────────────────────


class TestSkipPaths:
    async def test_skipped_when_music_disabled(self, tmp_path: Path) -> None:
        svc = _service()
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"RIFF" + b"\x00" * 100)

        out = await svc._run_music_phase(
            chapters=[{"index": 0}],
            abs_dir=tmp_path,
            audiobook_id=uuid4(),
            final_audio=final,
            chapter_timings=[],
            duration=10.0,
            file_size=104,
            music_enabled=False,
            music_mood="calm",
            music_volume_db=-14.0,
            per_chapter_music=False,
        )
        # Returned the original size unchanged.
        assert out == 104
        # No side effects.
        svc._broadcast_progress.assert_not_awaited()
        svc._add_music.assert_not_awaited()
        svc._add_chapter_music.assert_not_awaited()

    async def test_skipped_when_no_mood_and_no_per_chapter(self, tmp_path: Path) -> None:
        # music_enabled=True but neither music_mood nor per_chapter_music
        # → nothing to mix, skip.
        svc = _service()
        out = await svc._run_music_phase(
            chapters=[{"index": 0}],
            abs_dir=tmp_path,
            audiobook_id=uuid4(),
            final_audio=tmp_path / "audiobook.wav",
            chapter_timings=[],
            duration=10.0,
            file_size=100,
            music_enabled=True,
            music_mood=None,
            music_volume_db=-14.0,
            per_chapter_music=False,
        )
        assert out == 100
        svc._add_music.assert_not_awaited()


# ── _run_music_phase: routing ────────────────────────────────────────


class TestRouting:
    async def test_per_chapter_with_timings_takes_chapter_path(self, tmp_path: Path) -> None:
        svc = _service()
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"\x00" * 100)
        mixed = tmp_path / "audiobook_with_music.wav"
        mixed.write_bytes(b"\x00" * 200)
        svc._add_chapter_music = AsyncMock(return_value=mixed)  # type: ignore[method-assign]

        await svc._run_music_phase(
            chapters=[{"index": 0}],
            abs_dir=tmp_path,
            audiobook_id=uuid4(),
            final_audio=final,
            chapter_timings=[_timing(0)],
            duration=10.0,
            file_size=100,
            music_enabled=True,
            music_mood="calm",
            music_volume_db=-14.0,
            per_chapter_music=True,
        )
        svc._add_chapter_music.assert_awaited_once()
        svc._add_music.assert_not_awaited()

    async def test_per_chapter_without_timings_falls_back_to_global(self, tmp_path: Path) -> None:
        # per_chapter_music=True but no chapter_timings → can't place
        # the crossfade. Falls back to global music if music_mood set.
        svc = _service()
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"\x00" * 100)
        mixed = tmp_path / "audiobook_with_music.wav"
        mixed.write_bytes(b"\x00" * 200)
        svc._add_music = AsyncMock(return_value=mixed)  # type: ignore[method-assign]

        await svc._run_music_phase(
            chapters=[{"index": 0}],
            abs_dir=tmp_path,
            audiobook_id=uuid4(),
            final_audio=final,
            chapter_timings=[],
            duration=10.0,
            file_size=100,
            music_enabled=True,
            music_mood="calm",
            music_volume_db=-14.0,
            per_chapter_music=True,
        )
        svc._add_music.assert_awaited_once()
        svc._add_chapter_music.assert_not_awaited()

    async def test_global_music_when_no_per_chapter_flag(self, tmp_path: Path) -> None:
        svc = _service()
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"\x00" * 100)
        mixed = tmp_path / "audiobook_with_music.wav"
        mixed.write_bytes(b"\x00" * 200)
        svc._add_music = AsyncMock(return_value=mixed)  # type: ignore[method-assign]

        await svc._run_music_phase(
            chapters=[{"index": 0}],
            abs_dir=tmp_path,
            audiobook_id=uuid4(),
            final_audio=final,
            chapter_timings=[_timing(0)],
            duration=10.0,
            file_size=100,
            music_enabled=True,
            music_mood="epic",
            music_volume_db=-12.0,
            per_chapter_music=False,
        )
        svc._add_music.assert_awaited_once()


# ── _run_music_phase: side effects ───────────────────────────────────


class TestSideEffects:
    async def test_progress_at_70_percent(self, tmp_path: Path) -> None:
        svc = _service()
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"\x00" * 100)
        svc._add_music = AsyncMock(return_value=final)  # type: ignore[method-assign]

        await svc._run_music_phase(
            chapters=[{"index": 0}],
            abs_dir=tmp_path,
            audiobook_id=uuid4(),
            final_audio=final,
            chapter_timings=[],
            duration=10.0,
            file_size=100,
            music_enabled=True,
            music_mood="calm",
            music_volume_db=-14.0,
            per_chapter_music=False,
        )
        bc = svc._broadcast_progress.call_args
        assert bc.args[1] == "music"
        assert bc.args[2] == 70

    async def test_dag_in_progress_then_done(self, tmp_path: Path) -> None:
        svc = _service()
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"\x00" * 100)
        svc._add_music = AsyncMock(return_value=final)  # type: ignore[method-assign]

        await svc._run_music_phase(
            chapters=[{"index": 0}, {"index": 1}],
            abs_dir=tmp_path,
            audiobook_id=uuid4(),
            final_audio=final,
            chapter_timings=[],
            duration=10.0,
            file_size=100,
            music_enabled=True,
            music_mood="calm",
            music_volume_db=-14.0,
            per_chapter_music=False,
        )
        statuses = [c.args[2] for c in svc._dag_chapter.call_args_list]
        # Two in_progress (per chapter, up front), two done.
        assert statuses[:2] == ["in_progress", "in_progress"]
        assert statuses[2:] == ["done", "done"]


# ── _run_music_phase: failure path ───────────────────────────────────


class TestFailureNonFatal:
    async def test_exception_caught_dag_marked_failed(self, tmp_path: Path) -> None:
        svc = _service()
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"\x00" * 100)
        svc._add_music = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("MusicGen out of memory")
        )

        # Must not raise.
        out = await svc._run_music_phase(
            chapters=[{"index": 0}, {"index": 1}],
            abs_dir=tmp_path,
            audiobook_id=uuid4(),
            final_audio=final,
            chapter_timings=[],
            duration=10.0,
            file_size=100,
            music_enabled=True,
            music_mood="calm",
            music_volume_db=-14.0,
            per_chapter_music=False,
        )
        # Returns original size — no swap happened.
        assert out == 100
        statuses = [c.args[2] for c in svc._dag_chapter.call_args_list]
        # Two in_progress, two failed.
        assert statuses[:2] == ["in_progress", "in_progress"]
        assert statuses[2:] == ["failed", "failed"]


# ── _swap_in_mixed_audio ─────────────────────────────────────────────


class TestSwapInMixedAudio:
    def test_no_op_when_mixer_returns_same_path(self, tmp_path: Path) -> None:
        # Some mixer implementations return ``audio_path`` unchanged
        # (no music mixed in). The swap must skip without touching disk.
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"\x00" * 100)
        out = AudiobookService._swap_in_mixed_audio(
            final_audio=final,
            mixed_path=final,
            file_size=100,
            log_event="x",
            audiobook_id=uuid4(),
        )
        assert out == 100

    def test_atomic_swap_replaces_final_with_mixed(self, tmp_path: Path) -> None:
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"orig")
        mixed = tmp_path / "audiobook_with_music.wav"
        mixed.write_bytes(b"new-mixed-content")

        out = AudiobookService._swap_in_mixed_audio(
            final_audio=final,
            mixed_path=mixed,
            file_size=4,
            log_event="x",
            audiobook_id=uuid4(),
        )
        # Returned size matches the new (post-swap) on-disk size.
        assert out == final.stat().st_size
        assert out > 4
        # final now holds the mixed content.
        assert final.read_bytes() == b"new-mixed-content"
        # Backup cleaned up.
        assert not (tmp_path / "audiobook.wav.bak").exists()
        # Source file gone (renamed away).
        assert not mixed.exists()

    def test_failure_during_rename_restores_backup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate a failure during ``mixed_path.rename(final_audio)``
        # — the swap must restore the backup and re-raise so the caller
        # sees the underlying failure.
        final = tmp_path / "audiobook.wav"
        final.write_bytes(b"original")
        mixed = tmp_path / "audiobook_with_music.wav"
        mixed.write_bytes(b"new")

        # Patch the mixed path's ``rename`` method via the Path class.
        original_rename = Path.rename
        call_count = {"n": 0}

        def _failing_rename(self: Path, target: Any) -> Any:
            call_count["n"] += 1
            # First call (final → backup) succeeds. Second call
            # (mixed → final) fails. Third call (backup → final, the
            # restore) succeeds.
            if call_count["n"] == 2:
                raise OSError("disk full mid-rename")
            return original_rename(self, target)

        monkeypatch.setattr(Path, "rename", _failing_rename)

        with pytest.raises(OSError, match="disk full"):
            AudiobookService._swap_in_mixed_audio(
                final_audio=final,
                mixed_path=mixed,
                file_size=8,
                log_event="x",
                audiobook_id=uuid4(),
            )
        # final still has the original content (rolled back).
        assert final.exists()
        assert final.read_bytes() == b"original"
        # Backup gone (it was renamed back to final).
        assert not (tmp_path / "audiobook.wav.bak").exists()
