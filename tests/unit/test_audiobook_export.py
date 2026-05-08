"""Tests for the MP3 export filter chain (Task 2).

The pre-Task-2 export filter chain ran ``silenceremove`` at both ends,
which silently shortened intentional dramatic pauses inside the
audiobook. The new chain runs only ``loudnorm`` by default; an opt-in
trim runs on the WAV BEFORE timing math + captions are produced so
CHAP frames + ASS captions stay in sync.

These tests focus on the regression guards:

1. ``silenceremove`` is *not* in the default MP3 export argv.
2. ``loudnorm`` is still in the default argv.
3. ``_shift_chapter_timings`` correctly subtracts the leading offset.
4. (Slow / requires ffmpeg) A 3-second mid-track silence survives the
   round trip from WAV through ``_convert_to_mp3`` to MP3.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    ChapterTiming,
)


class _StubStorage:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def resolve_path(self, rel: str) -> Path:
        return self.base_path / rel


# ── _convert_to_mp3 default filter chain ─────────────────────────────────


class _CapturedProc:
    """Stand-in for ``asyncio.subprocess.Process`` that records the argv."""

    def __init__(self) -> None:
        self.returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


class TestConvertToMp3FilterChain:
    """Task 2 stripped ``silenceremove`` (intentional pauses survive).
    Task 3 stripped the rest of the export-time filter chain — the
    encoder reads an already-mastered WAV. The argv must therefore
    carry no ``-af`` at all and no ``silenceremove`` substring.
    """

    async def test_silenceremove_not_in_default_argv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wav = tmp_path / "audiobook.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 1024)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            return _CapturedProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        await service._convert_to_mp3(wav)

        assert captured, "ffmpeg was not invoked"
        argv = captured[0]
        # Post-Task-3 contract: no -af at all in the export argv.
        assert "-af" not in argv, (
            f"MP3 export should carry no filter chain post-Task-3; argv had -af: {argv}"
        )

    async def test_encoder_settings_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wav = tmp_path / "audiobook.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 1024)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            return _CapturedProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        await service._convert_to_mp3(wav)

        argv = captured[0]
        # Encoder is still libmp3lame; the bitrate flag depends on
        # ``settings.mp3_mode`` (Task 9). Default is ``vbr_v0`` →
        # ``-q:a 0``; pre-Task-9 default of ``cbr_192`` → ``-b:a 192k``.
        # Either is acceptable so long as a libmp3lame encoder spec
        # is in argv.
        assert "libmp3lame" in argv
        assert ("-b:a" in argv) or ("-q:a" in argv)


# ── _shift_chapter_timings ────────────────────────────────────────────────


class TestShiftChapterTimings:
    def test_zero_offset_returns_input_unchanged(self) -> None:
        timings = [
            ChapterTiming(0, 0.0, 60.0, 60.0),
            ChapterTiming(1, 60.0, 120.0, 60.0),
        ]
        assert AudiobookService._shift_chapter_timings(timings, 0.0) is timings

    def test_negative_offset_is_no_op(self) -> None:
        timings = [ChapterTiming(0, 5.0, 10.0, 5.0)]
        assert AudiobookService._shift_chapter_timings(timings, -3.0) is timings

    def test_subtracts_offset_from_start_and_end(self) -> None:
        timings = [
            ChapterTiming(0, 1.5, 60.0, 58.5),
            ChapterTiming(1, 60.0, 120.0, 60.0),
        ]
        shifted = AudiobookService._shift_chapter_timings(timings, 1.5)
        assert shifted[0].start_seconds == 0.0
        assert shifted[0].end_seconds == pytest.approx(58.5)
        assert shifted[0].duration_seconds == pytest.approx(58.5)
        assert shifted[1].start_seconds == pytest.approx(58.5)
        assert shifted[1].end_seconds == pytest.approx(118.5)

    def test_clamps_negative_starts_to_zero(self) -> None:
        # Pathological case: leading offset larger than first chapter's start.
        timings = [ChapterTiming(0, 0.5, 10.0, 9.5)]
        shifted = AudiobookService._shift_chapter_timings(timings, 2.0)
        assert shifted[0].start_seconds == 0.0
        assert shifted[0].end_seconds == pytest.approx(8.0)
        assert shifted[0].duration_seconds == pytest.approx(8.0)


# ── Slow round-trip test (real ffmpeg) ───────────────────────────────────


_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.mark.slow
@pytest.mark.skipif(
    not _FFMPEG_AVAILABLE,
    reason="ffmpeg / ffprobe not on PATH; run on a workstation with ffmpeg installed.",
)
class TestMp3ExportPreservesInternalSilence:
    """Generate a WAV with a 3-second mid-track silence, convert to MP3,
    confirm the silence survives. This is the empirical bug fix the
    Task 2 brief asks for. Skipped automatically when ffmpeg isn't
    available in the test environment.
    """

    async def _ffprobe_duration(self, path: Path) -> float:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        return float(out.decode().strip())

    async def test_three_second_pause_survives_mp3_export(self, tmp_path: Path) -> None:
        wav = tmp_path / "audiobook.wav"

        # Tone (1s) + silence (3s) + tone (1s) — 5s total
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
            "-map",
            "[out]",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        assert wav.exists()

        original_duration = await self._ffprobe_duration(wav)
        assert original_duration == pytest.approx(5.0, abs=0.1)

        # Use real FFmpegService.get_duration via a thin shim — we only
        # need _convert_to_mp3 to succeed; ffmpeg invocations inside it
        # are real here.
        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        mp3 = await service._convert_to_mp3(wav)

        assert mp3.exists()
        mp3_duration = await self._ffprobe_duration(mp3)
        # ±100 ms tolerance for encoder priming (LAME ~26 ms) and any
        # rounding in loudnorm. The 3-second internal silence MUST be
        # intact; we'd see ≈ 2.0 s if silenceremove had eaten the gap.
        assert mp3_duration == pytest.approx(original_duration, abs=0.1), (
            f"MP3 duration {mp3_duration:.3f}s differs from source "
            f"{original_duration:.3f}s by more than 100 ms — internal "
            f"silence may have been stripped."
        )
