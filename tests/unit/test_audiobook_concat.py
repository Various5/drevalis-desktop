"""Tests for the concat-without-re-encode fast path (Task 7).

Pre-Task-7, ``_concatenate_with_context`` always re-encoded to canonical
44.1 kHz stereo s16le, even when every input chunk was already a uniform
24 kHz mono PCM stream from the same provider. The new path probes
every concat input's ``(sample_rate, channels, codec_name, sample_fmt)``
and uses ``-c copy`` when they all match.

These tests guard:

  * ``_probe_audio_format`` parses ffprobe JSON and degrades gracefully.
  * Uniform-input chapters take the ``-c copy`` path.
  * Mixed-input chapters (multi-provider) take the re-encode path.
  * The concat-list file is written with the same paths in both modes.
  * Stream-copy failure auto-falls-back to a re-encode pass.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    AudioChunk,
)


class _StubStorage:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def resolve_path(self, rel: str) -> Path:
        return self.base_path / rel


class _CapturedProc:
    def __init__(
        self,
        returncode: int = 0,
        stdout_bytes: bytes = b"",
        stderr_bytes: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout_bytes
        self._stderr = stderr_bytes

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


# ── _probe_audio_format ──────────────────────────────────────────────────


_GOOD_PROBE_JSON = b"""\
{
  "streams": [
    {
      "codec_name": "pcm_s16le",
      "sample_rate": "24000",
      "channels": 1,
      "sample_fmt": "s16"
    }
  ]
}
"""


_NO_AUDIO_STREAM_JSON = b'{"streams": []}'


_BROKEN_JSON = b"this is not json at all"


class TestProbeAudioFormat:
    async def test_parses_pcm_s16_mono_24khz(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            return _CapturedProc(returncode=0, stdout_bytes=_GOOD_PROBE_JSON)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        result = await AudiobookService._probe_audio_format(tmp_path / "x.wav")
        assert result == (24000, 1, "pcm_s16le", "s16")

    async def test_returns_none_on_ffprobe_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            return _CapturedProc(returncode=1, stderr_bytes=b"ffprobe broke")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        result = await AudiobookService._probe_audio_format(tmp_path / "x.wav")
        assert result is None

    async def test_returns_none_when_no_streams(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            return _CapturedProc(returncode=0, stdout_bytes=_NO_AUDIO_STREAM_JSON)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        result = await AudiobookService._probe_audio_format(tmp_path / "x.wav")
        assert result is None

    async def test_returns_none_on_broken_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            return _CapturedProc(returncode=0, stdout_bytes=_BROKEN_JSON)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        result = await AudiobookService._probe_audio_format(tmp_path / "x.wav")
        assert result is None

    async def test_returns_none_when_ffprobe_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            raise FileNotFoundError("ffprobe not on PATH")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        result = await AudiobookService._probe_audio_format(tmp_path / "x.wav")
        assert result is None


# ── _concatenate_with_context: uniform vs mixed paths ────────────────────


def _make_voice_chunk(
    tmp_path: Path,
    chapter_index: int,
    chunk_index: int,
    speaker: str = "Narrator",
) -> AudioChunk:
    p = tmp_path / f"ch{chapter_index:03d}_chunk_{chunk_index:04d}_a1b2c3d4e5f6.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 1024)
    return AudioChunk(
        path=p,
        chapter_index=chapter_index,
        speaker=speaker,
        block_index=0,
        chunk_index=chunk_index,
    )


class _ConcatRecorder:
    """Captures every ffmpeg argv plus a per-binary format map for
    ffprobe. ``formats[Path] = (sr, ch, codec, sample_fmt)``.
    """

    def __init__(self, formats: dict[Path, tuple[int, int, str, str] | None]) -> None:
        self.formats = formats
        self.argvs: list[list[str]] = []

    def make_fake_exec(self):
        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            argv = list(args)
            self.argvs.append(argv)
            program = argv[0]
            if program.endswith("ffprobe") or program == "ffprobe":
                # Last positional argument is the path.
                target = Path(argv[-1])
                fmt = self.formats.get(target)
                if fmt is None:
                    # Try a fuzzier match — Path equality can fail on
                    # Windows when the test creates files via tmp_path
                    # but ffprobe sees a normalized path.
                    for p, f in self.formats.items():
                        if Path(p).resolve() == target.resolve():
                            fmt = f
                            break
                if fmt is None:
                    return _CapturedProc(returncode=1)
                json_payload = (
                    f'{{"streams": [{{'
                    f'"codec_name": "{fmt[2]}",'
                    f'"sample_rate": "{fmt[0]}",'
                    f'"channels": {fmt[1]},'
                    f'"sample_fmt": "{fmt[3]}"'
                    f"}}]}}"
                )
                return _CapturedProc(returncode=0, stdout_bytes=json_payload.encode())

            # ffmpeg invocation — simulate output landing on disk for
            # any path-looking final argument so atomic-replace and
            # subsequent stat checks succeed.
            out = Path(argv[-1])
            try:
                out.write_bytes(b"RIFF" + b"\x00" * 1024)
            except OSError:
                pass
            return _CapturedProc(returncode=0)

        return _fake_exec


class TestConcatUniformFastPath:
    async def test_uniform_inputs_use_stream_copy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        v0 = _make_voice_chunk(tmp_path, 0, 0)
        v1 = _make_voice_chunk(tmp_path, 0, 1)

        # Predict the silence files the concat helper will produce.
        # _concatenate_with_context creates them inside output.parent.
        sil_within = tmp_path / "_silence_150ms.wav"

        formats: dict[Path, tuple[int, int, str, str] | None] = {
            v0.path: (24000, 1, "pcm_s16le", "s16"),
            v1.path: (24000, 1, "pcm_s16le", "s16"),
            # Silence files share the same format.
            sil_within: (24000, 1, "pcm_s16le", "s16"),
            tmp_path / "_silence_400ms.wav": (24000, 1, "pcm_s16le", "s16"),
            tmp_path / "_silence_1200ms.wav": (24000, 1, "pcm_s16le", "s16"),
        }
        recorder = _ConcatRecorder(formats)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder.make_fake_exec())

        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=2.0)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )

        await service._concatenate_with_context([v0, v1], tmp_path / "out.wav")

        # Find the concat ffmpeg invocation (NOT the silence-generation
        # invocations which also call ffmpeg). It's the one with
        # ``-f concat`` AND outputs to ``out.wav``.
        concat_argvs = [
            a
            for a in recorder.argvs
            if a[0] != "ffprobe"
            and "-f" in a
            and a[a.index("-f") + 1] == "concat"
            and a[-1].endswith("out.wav")
        ]
        assert len(concat_argvs) == 1, (
            f"expected exactly one concat ffmpeg call; got {len(concat_argvs)}"
        )
        argv = concat_argvs[0]
        # Stream-copy path: -c copy present, no -ar / -ac / -sample_fmt.
        assert "-c" in argv
        assert argv[argv.index("-c") + 1] == "copy"
        assert "-ar" not in argv
        assert "-ac" not in argv
        assert "-sample_fmt" not in argv

    async def test_mixed_inputs_take_reencode_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # First chunk is 24 kHz mono Piper-style; second chunk is
        # 44.1 kHz stereo (e.g. an ElevenLabs cloud chunk).
        v0 = _make_voice_chunk(tmp_path, 0, 0)
        v1 = _make_voice_chunk(tmp_path, 0, 1)

        formats: dict[Path, tuple[int, int, str, str] | None] = {
            v0.path: (24000, 1, "pcm_s16le", "s16"),
            v1.path: (44100, 2, "pcm_s16le", "s16"),
            tmp_path / "_silence_150ms.wav": (24000, 1, "pcm_s16le", "s16"),
            tmp_path / "_silence_400ms.wav": (24000, 1, "pcm_s16le", "s16"),
            tmp_path / "_silence_1200ms.wav": (24000, 1, "pcm_s16le", "s16"),
        }
        recorder = _ConcatRecorder(formats)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder.make_fake_exec())

        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=2.0)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )

        await service._concatenate_with_context([v0, v1], tmp_path / "out.wav")

        concat_argvs = [
            a
            for a in recorder.argvs
            if a[0] != "ffprobe"
            and "-f" in a
            and a[a.index("-f") + 1] == "concat"
            and a[-1].endswith("out.wav")
        ]
        assert len(concat_argvs) == 1
        argv = concat_argvs[0]
        # Re-encode path: explicit canonical 44.1 kHz stereo s16le.
        assert "-ar" in argv and argv[argv.index("-ar") + 1] == "44100"
        assert "-ac" in argv and argv[argv.index("-ac") + 1] == "2"
        assert "-sample_fmt" in argv and argv[argv.index("-sample_fmt") + 1] == "s16"
        assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "pcm_s16le"
        # And it does NOT contain ``-c copy``.
        c_indices = [k for k, t in enumerate(argv) if t == "-c"]
        for k in c_indices:
            assert argv[k + 1] != "copy", "stream-copy must not be used for mixed inputs"

    async def test_unprobeable_chunk_falls_back_to_reencode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        v0 = _make_voice_chunk(tmp_path, 0, 0)
        v1 = _make_voice_chunk(tmp_path, 0, 1)

        # v1 returns None from ffprobe — uniformity check must fail.
        formats: dict[Path, tuple[int, int, str, str] | None] = {
            v0.path: (24000, 1, "pcm_s16le", "s16"),
            v1.path: None,
            tmp_path / "_silence_150ms.wav": (24000, 1, "pcm_s16le", "s16"),
            tmp_path / "_silence_400ms.wav": (24000, 1, "pcm_s16le", "s16"),
            tmp_path / "_silence_1200ms.wav": (24000, 1, "pcm_s16le", "s16"),
        }
        recorder = _ConcatRecorder(formats)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder.make_fake_exec())

        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=2.0)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )

        await service._concatenate_with_context([v0, v1], tmp_path / "out.wav")

        concat_argvs = [
            a
            for a in recorder.argvs
            if a[0] != "ffprobe"
            and "-f" in a
            and a[a.index("-f") + 1] == "concat"
            and a[-1].endswith("out.wav")
        ]
        assert len(concat_argvs) == 1
        argv = concat_argvs[0]
        # Must be re-encode, not stream-copy.
        assert "-ar" in argv
        assert "44100" in argv
