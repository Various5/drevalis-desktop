"""Tests for the AudiobookSettings + platform presets (Task 9)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from drevalis.schemas.audiobook import (
    DEFAULT_PLATFORM_PRESET,
    PLATFORM_PRESETS,
    AudiobookSettings,
    resolve_audiobook_settings,
)
from drevalis.services.audiobook._monolith import (
    AudiobookService,
    _mp3_encoder_args,
)


class _StubStorage:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def resolve_path(self, rel: str) -> Path:
        return self.base_path / rel


class _CapturedProc:
    def __init__(self, returncode: int = 0, stderr_bytes: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr_bytes

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self._stderr


# ── AudiobookSettings defaults ───────────────────────────────────────────


class TestAudiobookSettingsDefaults:
    def test_default_matches_narrative_preset(self) -> None:
        defaults = AudiobookSettings().model_dump()
        narrative = PLATFORM_PRESETS["narrative"].model_dump()
        assert defaults == narrative

    def test_default_targets(self) -> None:
        s = AudiobookSettings()
        assert s.loudness_target_lufs == -18.0
        assert s.true_peak_dbfs == -2.0
        assert s.loudness_lra == 14.0
        assert s.mp3_mode == "vbr_v0"
        assert s.video_codec == "libx264"
        assert s.video_crf == 21
        assert s.ducking_preset == "static"
        assert s.chapter_silence_ms == 1200
        assert s.speaker_change_silence_ms == 400
        assert s.intra_speaker_silence_ms == 150

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AudiobookSettings(unknown_field=42)


# ── PLATFORM_PRESETS ─────────────────────────────────────────────────────


class TestPlatformPresets:
    def test_exact_set_of_presets(self) -> None:
        assert set(PLATFORM_PRESETS.keys()) == {
            "narrative",
            "podcast",
            "streaming",
            "acx",
        }
        assert DEFAULT_PLATFORM_PRESET == "narrative"

    def test_podcast_deltas(self) -> None:
        p = PLATFORM_PRESETS["podcast"]
        assert p.loudness_target_lufs == -16.0
        assert p.loudness_lra == 11.0
        assert p.ducking_preset == "normal"
        assert p.mp3_mode == "vbr_v0"

    def test_streaming_deltas(self) -> None:
        s = PLATFORM_PRESETS["streaming"]
        assert s.loudness_target_lufs == -14.0
        assert s.loudness_lra == 11.0
        assert s.true_peak_dbfs == -1.0
        assert s.mp3_mode == "vbr_v0"
        assert s.sample_rate == 48000

    def test_acx_deltas(self) -> None:
        a = PLATFORM_PRESETS["acx"]
        assert a.loudness_target_lufs == -20.0
        assert a.loudness_lra == 18.0
        assert a.true_peak_dbfs == -3.0
        assert a.mp3_mode == "cbr_192"
        assert a.sample_rate == 44100


# ── resolve_audiobook_settings ───────────────────────────────────────────


class TestResolveAudiobookSettings:
    def test_none_preset_returns_narrative(self) -> None:
        s = resolve_audiobook_settings()
        assert s.model_dump() == PLATFORM_PRESETS["narrative"].model_dump()

    def test_named_preset(self) -> None:
        s = resolve_audiobook_settings(preset="podcast")
        assert s.loudness_target_lufs == -16.0

    def test_case_insensitive(self) -> None:
        s = resolve_audiobook_settings(preset="ACX")
        assert s.loudness_target_lufs == -20.0

    def test_unknown_preset_falls_back_to_narrative(self) -> None:
        s = resolve_audiobook_settings(preset="blastbeat")
        assert s.loudness_target_lufs == -18.0

    def test_overrides_merge_on_top_of_preset(self) -> None:
        s = resolve_audiobook_settings(
            preset="podcast",
            overrides={"video_crf": 18, "mp3_mode": "cbr_256"},
        )
        # Preset values still applied
        assert s.loudness_target_lufs == -16.0
        # Overrides win
        assert s.video_crf == 18
        assert s.mp3_mode == "cbr_256"

    def test_unknown_override_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            resolve_audiobook_settings(overrides={"not_a_field": True})


# ── _mp3_encoder_args ────────────────────────────────────────────────────


class TestMp3EncoderArgs:
    @pytest.mark.parametrize(
        "mode, expected_kbps",
        [("cbr_128", "128k"), ("cbr_192", "192k"), ("cbr_256", "256k")],
    )
    def test_cbr_modes(self, mode: str, expected_kbps: str) -> None:
        argv = _mp3_encoder_args(mode)
        assert argv == ["-codec:a", "libmp3lame", "-b:a", expected_kbps]

    @pytest.mark.parametrize(
        "mode, expected_q",
        [("vbr_v0", "0"), ("vbr_v2", "2")],
    )
    def test_vbr_modes(self, mode: str, expected_q: str) -> None:
        argv = _mp3_encoder_args(mode)
        assert argv == ["-codec:a", "libmp3lame", "-q:a", expected_q]

    def test_unknown_mode_falls_back(self) -> None:
        argv = _mp3_encoder_args("flac_high")
        assert argv == ["-codec:a", "libmp3lame", "-b:a", "192k"]


# ── _convert_to_mp3 picks up settings ────────────────────────────────────


class TestConvertToMp3HonoursSettings:
    async def test_cbr_256_emits_b_a_256k(
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
        service._settings = AudiobookSettings(mp3_mode="cbr_256")

        await service._convert_to_mp3(wav)

        argv = captured[0]
        assert "-b:a" in argv
        assert argv[argv.index("-b:a") + 1] == "256k"

    async def test_vbr_v0_emits_q_a_0(
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
        service._settings = AudiobookSettings(mp3_mode="vbr_v0")

        await service._convert_to_mp3(wav)

        argv = captured[0]
        assert "-q:a" in argv
        assert argv[argv.index("-q:a") + 1] == "0"
        assert "-b:a" not in argv


# ── _apply_master_loudnorm picks up settings ─────────────────────────────


class TestMasterLoudnormHonoursSettings:
    async def test_acx_targets_propagate_to_pass1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wav = tmp_path / "audiobook.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 4096)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            # Return empty stderr so the parser fails and the
            # single-pass fallback runs (we only care about argv shape).
            if not Path(args[-1]).exists():
                Path(args[-1]).write_bytes(b"RIFF" + b"\x00" * 4096)
            return _CapturedProc(returncode=0, stderr_bytes=b"no json")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        service._settings = PLATFORM_PRESETS["acx"]

        await service._apply_master_loudnorm(wav)

        # Pass 1 (measure) — first ffmpeg invocation.
        af1 = captured[0][captured[0].index("-af") + 1]
        assert "I=-20.0" in af1
        assert "TP=-3.0" in af1
        assert "LRA=18.0" in af1

    async def test_streaming_sample_rate_in_pass2_argv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wav = tmp_path / "audiobook.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 4096)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            out = Path(args[-1])
            if not out.exists() and str(out) != "-":
                try:
                    out.write_bytes(b"RIFF" + b"\x00" * 4096)
                except OSError:
                    pass
            return _CapturedProc(returncode=0, stderr_bytes=b"no json")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        service._settings = PLATFORM_PRESETS["streaming"]  # 48 kHz

        await service._apply_master_loudnorm(wav)

        # Pass 2 — second ffmpeg invocation.
        argv2 = captured[1]
        assert argv2[argv2.index("-ar") + 1] == "48000"


# ── _create_audiobook_video picks up settings ────────────────────────────


class TestCreateAudiobookVideoHonoursSettings:
    async def test_libx265_and_crf_propagate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        audio = tmp_path / "audiobook.wav"
        audio.write_bytes(b"RIFF" + b"\x00" * 4096)
        out = tmp_path / "out.mp4"

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))

            class _StreamingProc:
                returncode = 0
                stderr = AsyncMock()

                async def wait(self):
                    return 0

            class _LinesReader:
                async def readline(self):
                    return b""

            proc = _StreamingProc()
            proc.stderr = _LinesReader()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        service._settings = AudiobookSettings(
            video_codec="libx265",
            video_crf=18,
            video_preset="slow",
        )

        # Output write happens after readline loop — fake the file.
        out.write_bytes(b"\x00" * 1024)

        await service._create_audiobook_video(
            audio_path=audio,
            output_path=out,
            cover_image_path=None,
            duration=10.0,
            captions_path=None,
            with_waveform=False,
            width=1920,
            height=1080,
        )

        argv = captured[0]
        assert "-c:v" in argv and argv[argv.index("-c:v") + 1] == "libx265"
        assert "-crf" in argv and argv[argv.index("-crf") + 1] == "18"
        assert "-preset" in argv and argv[argv.index("-preset") + 1] == "slow"
        # No ``-b:v`` — CRF mode replaces fixed bitrate.
        assert "-b:v" not in argv


# ── _pauses honours settings ─────────────────────────────────────────────


class TestPausesHonourSettings:
    def test_default_pauses_match_narrative(self) -> None:
        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(Path("/tmp")),
        )
        # No _settings set — falls back to AudiobookSettings() defaults.
        within, speaker, chapter = service._pauses()
        assert within == 0.15
        assert speaker == 0.4
        assert chapter == 1.2

    def test_custom_pauses_override(self) -> None:
        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(Path("/tmp")),
        )
        service._settings = AudiobookSettings(
            chapter_silence_ms=2000,
            speaker_change_silence_ms=600,
            intra_speaker_silence_ms=200,
        )
        within, speaker, chapter = service._pauses()
        assert within == 0.2
        assert speaker == 0.6
        assert chapter == 2.0
