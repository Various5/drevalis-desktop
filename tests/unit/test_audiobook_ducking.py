"""Tests for the music + SFX ducking presets (Task 6).

Pre-Task-6 the music sidechain ran with hardcoded
``threshold=0.05:ratio=10:attack=20:release=400`` — aggressive enough
to pump audibly between sentences. Post-Task-6:

  * ``DUCKING_PRESETS`` exposes 5 named presets (static / subtle /
    normal / strong / cinematic).
  * Default is ``static`` — no sidechain at all, music sits at a fixed
    -22 dB under voice. Predictable, no pumping.
  * ``SFX_DUCKING`` carries SFX-overlay-specific params (faster attack
    + faster release + gentler ratio than the music ducker).
  * Master pre-loudnorm limiter ceiling moved from 0.95 (linear ≈
    -0.45 dBFS) to -1.0 dBFS so loudnorm has headroom.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    DEFAULT_DUCKING_PRESET,
    DUCKING_PRESETS,
    MASTER_LIMITER_CEILING_DB,
    SFX_DUCKING,
    AudiobookService,
    AudioChunk,
    _build_music_mix_graph,
    _resolve_ducking_preset,
)


class _StubStorage:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def resolve_path(self, rel: str) -> Path:
        return self.base_path / rel


class _CapturedProc:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


# ── Preset registry ──────────────────────────────────────────────────────


class TestDuckingPresetRegistry:
    def test_exact_set_of_presets(self) -> None:
        assert set(DUCKING_PRESETS.keys()) == {
            "static",
            "subtle",
            "normal",
            "strong",
            "cinematic",
        }

    def test_default_is_static(self) -> None:
        assert DEFAULT_DUCKING_PRESET == "static"

    def test_static_has_no_sidechain_params(self) -> None:
        preset = DUCKING_PRESETS["static"]
        assert preset["mode"] == "static"
        assert "threshold" not in preset
        assert "ratio" not in preset

    def test_sidechain_presets_carry_full_param_set(self) -> None:
        for name in ("subtle", "normal", "strong", "cinematic"):
            preset = DUCKING_PRESETS[name]
            assert preset["mode"] == "sidechain"
            for key in ("music_db", "threshold", "ratio", "attack", "release"):
                assert key in preset, f"preset {name!r} is missing {key!r}"

    def test_progression_makes_sense(self) -> None:
        # Stronger presets should: (a) sit music louder (closer to 0 dB
        # because the ducker pulls it down on dialogue) and (b) have
        # lower threshold or higher ratio. Sanity-check the curve.
        order = ["subtle", "normal", "strong", "cinematic"]
        music_dbs = [DUCKING_PRESETS[n]["music_db"] for n in order]
        # subtle (-20) → cinematic (-12) — strictly increasing toward 0.
        assert music_dbs == sorted(music_dbs)


# ── _resolve_ducking_preset ──────────────────────────────────────────────


class TestResolveDuckingPreset:
    def test_none_returns_static_default(self) -> None:
        assert _resolve_ducking_preset(None)["mode"] == "static"

    def test_case_insensitive(self) -> None:
        assert _resolve_ducking_preset("CINEMATIC")["mode"] == "sidechain"
        assert _resolve_ducking_preset("Static")["mode"] == "static"

    def test_unknown_falls_back_to_static(self) -> None:
        # Unknown name should not raise; warning is logged.
        preset = _resolve_ducking_preset("blastbeat")
        assert preset is DUCKING_PRESETS["static"]

    def test_whitespace_stripped(self) -> None:
        assert _resolve_ducking_preset("  normal  ")["mode"] == "sidechain"


# ── _build_music_mix_graph ───────────────────────────────────────────────


class TestBuildMusicMixGraph:
    """Most of Task 6's behaviour lives in this pure-string builder."""

    def test_static_mode_skips_sidechain(self) -> None:
        graph = _build_music_mix_graph(
            preset=DUCKING_PRESETS["static"],
            voice_gain_db=0.0,
            music_volume_db=-22.0,
            music_pad_ms=60000,
        )
        assert "sidechaincompress" not in graph
        # Voice + bgm both go straight to amix.
        assert "[voice][bgm]amix=inputs=2:duration=longest" in graph
        # Limiter at the master ceiling.
        assert f"alimiter=limit={MASTER_LIMITER_CEILING_DB}dB" in graph

    def test_cinematic_preset_numerics(self) -> None:
        graph = _build_music_mix_graph(
            preset=DUCKING_PRESETS["cinematic"],
            voice_gain_db=0.0,
            music_volume_db=-12.0,
            music_pad_ms=60000,
        )
        assert "sidechaincompress=threshold=0.08:ratio=8:attack=5:release=350" in graph

    def test_normal_preset_numerics(self) -> None:
        graph = _build_music_mix_graph(
            preset=DUCKING_PRESETS["normal"],
            voice_gain_db=0.0,
            music_volume_db=-18.0,
            music_pad_ms=60000,
        )
        assert "sidechaincompress=threshold=0.1:ratio=4:attack=10:release=600" in graph

    def test_subtle_preset_numerics(self) -> None:
        graph = _build_music_mix_graph(
            preset=DUCKING_PRESETS["subtle"],
            voice_gain_db=0.0,
            music_volume_db=-20.0,
            music_pad_ms=60000,
        )
        assert "sidechaincompress=threshold=0.125:ratio=3:attack=15:release=800" in graph

    def test_strong_preset_numerics(self) -> None:
        graph = _build_music_mix_graph(
            preset=DUCKING_PRESETS["strong"],
            voice_gain_db=0.0,
            music_volume_db=-15.0,
            music_pad_ms=60000,
        )
        assert "sidechaincompress=threshold=0.1:ratio=6:attack=8:release=400" in graph

    def test_master_limiter_ceiling_applied_in_all_modes(self) -> None:
        for name in DUCKING_PRESETS:
            graph = _build_music_mix_graph(
                preset=DUCKING_PRESETS[name],
                voice_gain_db=0.0,
                music_volume_db=-18.0,
                music_pad_ms=60000,
            )
            assert f"alimiter=limit={MASTER_LIMITER_CEILING_DB}dB" in graph, (
                f"preset {name!r} did not end the master chain with the limiter"
            )

    def test_voice_gain_propagates(self) -> None:
        graph = _build_music_mix_graph(
            preset=DUCKING_PRESETS["static"],
            voice_gain_db=3.5,
            music_volume_db=-18.0,
            music_pad_ms=60000,
        )
        assert "volume=+3.5dB" in graph

    def test_music_pad_propagates(self) -> None:
        graph = _build_music_mix_graph(
            preset=DUCKING_PRESETS["normal"],
            voice_gain_db=0.0,
            music_volume_db=-18.0,
            music_pad_ms=42000,
        )
        assert "apad=whole_dur=42000ms" in graph


# ── End-to-end: _add_music with default static preset ────────────────────


class _MockMusicService:
    def __init__(self, music_path: Path) -> None:
        self._path = music_path

    async def get_music_for_episode(self, mood: str, target_duration: float, episode_id):  # noqa: ANN003, ARG002
        return self._path


class TestAddMusicUsesPresetFromInstance:
    async def test_default_static_no_sidechain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        voice = tmp_path / "voice.wav"
        voice.write_bytes(b"RIFF" + b"\x00" * 1024)
        music = tmp_path / "music.wav"
        music.write_bytes(b"RIFF" + b"\x00" * 1024)

        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=60.0)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            Path(args[-1]).write_bytes(b"RIFF" + b"\x00" * 1024)
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )
        # No explicit preset -> resolves to static.
        service._ducking_preset = _resolve_ducking_preset(None)
        monkeypatch.setattr(service, "_resolve_music_service", lambda: _MockMusicService(music))

        await service._add_music(
            audio_path=voice,
            output_path=tmp_path / "out.wav",
            mood="calm",
            volume_db=-22.0,
            duration=60.0,
        )

        graph = captured[0][captured[0].index("-filter_complex") + 1]
        assert "sidechaincompress" not in graph

    async def test_explicit_cinematic_preset_wires_sidechain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        voice = tmp_path / "voice.wav"
        voice.write_bytes(b"RIFF" + b"\x00" * 1024)
        music = tmp_path / "music.wav"
        music.write_bytes(b"RIFF" + b"\x00" * 1024)

        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=60.0)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            Path(args[-1]).write_bytes(b"RIFF" + b"\x00" * 1024)
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )
        service._ducking_preset = _resolve_ducking_preset("cinematic")
        monkeypatch.setattr(service, "_resolve_music_service", lambda: _MockMusicService(music))

        await service._add_music(
            audio_path=voice,
            output_path=tmp_path / "out.wav",
            mood="calm",
            volume_db=-12.0,
            duration=60.0,
        )

        graph = captured[0][captured[0].index("-filter_complex") + 1]
        assert "sidechaincompress=threshold=0.08:ratio=8:attack=5:release=350" in graph


# ── SFX overlay uses SFX_DUCKING ─────────────────────────────────────────


def _make_overlay_chunk(
    tmp_path: Path,
    block_index: int,
    duck_db: float = -12.0,
) -> AudioChunk:
    p = tmp_path / f"ch000_sfx_{block_index:04d}.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 1024)
    return AudioChunk(
        path=p,
        chapter_index=0,
        speaker="__SFX__",
        block_index=block_index,
        chunk_index=0,
        overlay_voice_blocks=1,
        overlay_seconds=None,
        overlay_duck_db=duck_db,
    )


def _make_voice_chunk(tmp_path: Path, idx: int) -> AudioChunk:
    p = tmp_path / f"ch000_chunk_{idx:04d}.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 1024)
    return AudioChunk(
        path=p,
        chapter_index=0,
        speaker="Narrator",
        block_index=0,
        chunk_index=idx,
    )


class TestSfxOverlayUsesSfxDucking:
    async def test_overlay_filter_graph_pulls_from_sfx_ducking_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        v0 = _make_voice_chunk(tmp_path, 0)
        v1 = _make_voice_chunk(tmp_path, 1)
        sfx = _make_overlay_chunk(tmp_path, 10)

        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=2.0)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            Path(args[-1]).write_bytes(b"RIFF" + b"\x00" * 1024)
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        base = tmp_path / "audiobook.wav"
        base.write_bytes(b"RIFF" + b"\x00" * 1024)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )

        await service._mix_overlay_sfx(
            base_path=base,
            chunks_in_order=[v0, sfx, v1],
            inline_chunks=[v0, v1],
            overlays=[(1, sfx)],
        )

        graph = captured[0][captured[0].index("-filter_complex") + 1]
        # Numerics from SFX_DUCKING — not the music-ducker numerics.
        expected = (
            f"sidechaincompress=threshold={SFX_DUCKING['threshold']}"
            f":ratio={SFX_DUCKING['ratio']}"
            f":attack={SFX_DUCKING['attack']}"
            f":release={SFX_DUCKING['release']}"
        )
        assert expected in graph, (
            f"SFX overlay did not pull params from SFX_DUCKING; graph: {graph}"
        )

    def test_sfx_ducking_carries_required_keys(self) -> None:
        for key in ("threshold", "ratio", "attack", "release"):
            assert key in SFX_DUCKING
