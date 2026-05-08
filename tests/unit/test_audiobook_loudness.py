"""Tests for the loudnorm strategy (Task 3).

The pre-Task-3 pipeline ran integrated loudness three times: per-chunk,
post-concat, and at MP3 export. Each pass compounded the previous one
and produced inter-sentence pumping because the per-chunk pass measured
sub-second audio that never converges. The new strategy is:

  * Per-chunk: peak safety only (highpass + alimiter).
  * Master stage: two-pass measure-then-apply EBU R128, once.
  * MP3 export: no filtering; encode the already-mastered WAV.

These tests guard the argv shapes (regression), the ffmpeg-stderr JSON
parser (which is fragile across versions and locales), and the
two-pass-vs-fallback control flow.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    LOUDNESS_LRA,
    LOUDNESS_TARGET_LUFS,
    TRUE_PEAK_DBFS,
    AudiobookService,
)


class _StubStorage:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def resolve_path(self, rel: str) -> Path:
        return self.base_path / rel


class _CapturedProc:
    """Stand-in for an ``asyncio.subprocess.Process``."""

    def __init__(self, stderr_text: str = "", returncode: int = 0) -> None:
        self._stderr = stderr_text.encode("utf-8")
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self._stderr


# ── Per-chunk safety filter ──────────────────────────────────────────────


class TestSafetyFilterChunk:
    """Per-chunk pass must NOT carry loudnorm anymore — that was the
    root cause of inter-sentence pumping. It runs aresample +
    highpass + alimiter only.
    """

    async def test_argv_carries_safety_filters_no_loudnorm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunk = tmp_path / "ch000_chunk_0000_a1b2c3d4e5f6.wav"
        chunk.write_bytes(b"RIFF" + b"\x00" * 1024)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            # Simulate ffmpeg writing the .norm.wav output so the
            # in-place replace path runs to completion.
            out = Path(args[-1])
            out.write_bytes(b"RIFF" + b"\x00" * 2048)
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        await service._safety_filter_chunk(chunk)

        assert captured, "ffmpeg was not invoked"
        argv = captured[0]
        af_idx = argv.index("-af")
        af = argv[af_idx + 1]
        assert "loudnorm" not in af, (
            "Per-chunk loudnorm must not run — sub-second integrated-loudness "
            "doesn't converge and creates inter-sentence pumping."
        )
        assert "aresample=24000" in af
        assert "highpass=f=60" in af
        assert "alimiter=limit=0.95" in af


# ── _parse_loudnorm_json ─────────────────────────────────────────────────


_REAL_LOUDNORM_STDERR = """\
ffmpeg version 6.1 Copyright (c) 2000-2023 the FFmpeg developers
[Parsed_loudnorm_0 @ 0x55d2] Some banner text
[Parsed_loudnorm_0 @ 0x55d2]
{
    "input_i" : "-21.45",
    "input_tp" : "-3.21",
    "input_lra" : "8.40",
    "input_thresh" : "-31.59",
    "output_i" : "-18.04",
    "output_tp" : "-2.00",
    "output_lra" : "8.20",
    "output_thresh" : "-28.18",
    "normalization_type" : "dynamic",
    "target_offset" : "-0.04"
}
"""

_TRUNCATED_LOUDNORM_STDERR = """\
[Parsed_loudnorm_0 @ 0x55d2]
{
    "input_i" : "-21.45",
    "input_tp" : "-3.21"
}
"""

_NO_JSON_STDERR = "Pure error output, no JSON block here at all."


class TestParseLoudnormJson:
    def test_extracts_required_fields(self) -> None:
        parsed = AudiobookService._parse_loudnorm_json(_REAL_LOUDNORM_STDERR)
        assert parsed is not None
        assert parsed["input_i"] == "-21.45"
        assert parsed["input_tp"] == "-3.21"
        assert parsed["input_lra"] == "8.40"
        assert parsed["input_thresh"] == "-31.59"
        assert parsed["target_offset"] == "-0.04"

    def test_returns_none_when_required_field_missing(self) -> None:
        assert AudiobookService._parse_loudnorm_json(_TRUNCATED_LOUDNORM_STDERR) is None

    def test_returns_none_when_no_json_block(self) -> None:
        assert AudiobookService._parse_loudnorm_json(_NO_JSON_STDERR) is None

    def test_returns_none_when_json_invalid(self) -> None:
        broken = '[Parsed_loudnorm_0]\n{\n    "input_i" : "-18",\n    not valid json,\n}'
        assert AudiobookService._parse_loudnorm_json(broken) is None


# ── _apply_master_loudnorm two-pass shape ────────────────────────────────


class TestApplyMasterLoudnormTwoPass:
    """When pass 1 returns parseable measurements, pass 2 must include
    every ``measured_*`` key plus ``offset`` plus ``linear=true``.
    """

    async def test_two_pass_argv_carries_measured_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wav = tmp_path / "audiobook.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 4096)

        argvs: list[list[str]] = []
        call = {"n": 0}

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            argvs.append(list(args))
            call["n"] += 1
            if call["n"] == 1:
                # Pass 1: return loudnorm JSON on stderr.
                return _CapturedProc(stderr_text=_REAL_LOUDNORM_STDERR, returncode=0)
            # Pass 2: write the .master.wav output and succeed.
            out = Path(args[-1])
            out.write_bytes(b"RIFF" + b"\x00" * 4096)
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        await service._apply_master_loudnorm(wav)

        assert len(argvs) == 2, "Expected pass 1 (measure) + pass 2 (apply)"

        # Pass 1: print_format=json + -f null -
        af1 = argvs[0][argvs[0].index("-af") + 1]
        assert "print_format=json" in af1
        assert "-f" in argvs[0]
        # Find where -f appears, value should be 'null'
        assert argvs[0][argvs[0].index("-f") + 1] == "null"

        # Pass 2: full measured_* set + offset + linear=true
        af2 = argvs[1][argvs[1].index("-af") + 1]
        for key in (
            "measured_I=-21.45",
            "measured_TP=-3.21",
            "measured_LRA=8.40",
            "measured_thresh=-31.59",
            "offset=-0.04",
            "linear=true",
        ):
            assert key in af2, f"pass 2 -af missing {key!r}: {af2}"
        # And targets propagated from constants.
        assert f"I={LOUDNESS_TARGET_LUFS}" in af2
        assert f"TP={TRUE_PEAK_DBFS}" in af2
        assert f"LRA={LOUDNESS_LRA}" in af2

        # Pass 2 must end in pcm_s16le 44.1 kHz stereo so the master
        # WAV is in canonical export format.
        assert "pcm_s16le" in argvs[1]
        assert "44100" in argvs[1]


class TestApplyMasterLoudnormFallback:
    """Pass 1 unparseable → fall back to single-pass loudnorm.
    Single-pass argv must NOT contain any ``measured_*`` keys.
    """

    async def test_single_pass_when_measurements_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wav = tmp_path / "audiobook.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 4096)

        argvs: list[list[str]] = []
        call = {"n": 0}

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            argvs.append(list(args))
            call["n"] += 1
            if call["n"] == 1:
                # Pass 1: stderr without parseable JSON.
                return _CapturedProc(stderr_text=_NO_JSON_STDERR, returncode=0)
            out = Path(args[-1])
            out.write_bytes(b"RIFF" + b"\x00" * 4096)
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        await service._apply_master_loudnorm(wav)

        assert len(argvs) == 2
        af2 = argvs[1][argvs[1].index("-af") + 1]
        assert "measured_I" not in af2
        assert "measured_TP" not in af2
        assert "linear=true" not in af2, (
            "linear=true requires measured values; must not be set on the fallback single-pass."
        )
        # Targets still applied.
        assert "loudnorm=" in af2
        assert f"I={LOUDNESS_TARGET_LUFS}" in af2


# ── MP3 export — loudnorm must be gone ───────────────────────────────────


class TestConvertToMp3HasNoLoudnorm:
    """Task 2 stripped silenceremove; Task 3 strips loudnorm too. The
    encoder now reads the already-mastered WAV.
    """

    async def test_mp3_export_argv_has_no_filter_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wav = tmp_path / "audiobook.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 1024)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        await service._convert_to_mp3(wav)

        argv = captured[0]
        # No -af at all in the new argv.
        assert "-af" not in argv, f"MP3 export should carry no filter chain; argv had -af: {argv}"
        # Encoder still libmp3lame; bitrate flag is mode-dependent
        # post-Task-9 (default vbr_v0 → -q:a 0).
        assert "libmp3lame" in argv
        assert ("-b:a" in argv) or ("-q:a" in argv)


# ── Slow round-trip (real ffmpeg) ────────────────────────────────────────


_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.mark.slow
@pytest.mark.skipif(
    not _FFMPEG_AVAILABLE,
    reason="ffmpeg / ffprobe not on PATH; run on a workstation with ffmpeg installed.",
)
class TestMasterLoudnormHitsTarget:
    """Render a tone, master-loudnorm it, measure with another loudnorm
    pass-1 invocation, assert the measured ``input_i`` is within ±0.5
    LUFS of the target. This is the empirical contract from the brief.
    """

    async def _measure_lufs(self, path: Path) -> float | None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-af",
            f"loudnorm=I={LOUDNESS_TARGET_LUFS}:TP={TRUE_PEAK_DBFS}:"
            f"LRA={LOUDNESS_LRA}:print_format=json",
            "-f",
            "null",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        parsed = AudiobookService._parse_loudnorm_json(err.decode("utf-8", errors="replace"))
        if not parsed:
            return None
        return float(parsed["input_i"])

    async def test_master_loudnorm_hits_target_within_half_lufs(self, tmp_path: Path) -> None:
        wav = tmp_path / "audiobook.wav"

        # 30-second sine sweep — enough audio for the loudnorm window
        # to converge. Speech-like dynamics aren't required for a level
        # check.
        gen = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=30",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(wav),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await gen.communicate()
        assert wav.exists()

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        await service._apply_master_loudnorm(wav)
        measured = await self._measure_lufs(wav)
        assert measured is not None, "measurement pass produced no parseable JSON"
        assert measured == pytest.approx(LOUDNESS_TARGET_LUFS, abs=0.5), (
            f"Mastered LUFS {measured:.2f} differs from target "
            f"{LOUDNESS_TARGET_LUFS:.2f} by more than 0.5 LUFS."
        )
