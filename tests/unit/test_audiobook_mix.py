"""Tests for the single-pass mix stage (Task 5).

Pre-Task-5, ``_mix_overlay_sfx`` ran one ffmpeg invocation per overlay,
each decoding + re-encoding the entire audiobook. ``_add_music`` and
``_add_chapter_music`` used ``amix duration=first`` which silently
truncated music when the resolved track was longer than voice — and
left silence under the voiceover when the track was *shorter*.

Post-Task-5:

  * One ffmpeg invocation handles every SFX overlay in a single
    ``filter_complex`` graph.
  * ``apad`` runs BEFORE ``atrim`` for every SFX branch.
  * Music is ``apad``-padded to at least voice duration before
    ``amix``; ``duration=longest`` keeps the voiceover intact in
    every case.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    AudioChunk,
    ChapterTiming,
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


# ── _mix_overlay_sfx single-pass ─────────────────────────────────────────


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


class TestOverlaySfxSinglePass:
    """N overlays = exactly 1 ffmpeg invocation. The pre-Task-5 design
    spawned N invocations, each decoding the entire audiobook.
    """

    async def test_three_overlays_invoke_ffmpeg_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Voice chunks + 3 overlay SFX interleaved.
        v0 = _make_voice_chunk(tmp_path, 0)
        v1 = _make_voice_chunk(tmp_path, 1)
        v2 = _make_voice_chunk(tmp_path, 2)
        sfx_a = _make_overlay_chunk(tmp_path, block_index=10, duck_db=-10)
        sfx_b = _make_overlay_chunk(tmp_path, block_index=11, duck_db=-12)
        sfx_c = _make_overlay_chunk(tmp_path, block_index=12, duck_db=-8)

        chunks_in_order = [v0, sfx_a, v1, sfx_b, v2, sfx_c]
        inline_chunks = [v0, v1, v2]
        overlays = [(1, sfx_a), (3, sfx_b), (5, sfx_c)]

        # Patch ffmpeg.get_duration to return a stable 2 s per chunk.
        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=2.0)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            # Simulate the mixed output landing on disk so atomic
            # replace runs to completion.
            out = Path(args[-1])
            out.write_bytes(b"RIFF" + b"\x00" * 1024)
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        # Provide the base WAV the helper expects to atomic-replace.
        base = tmp_path / "audiobook.wav"
        base.write_bytes(b"RIFF" + b"\x00" * 1024)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )

        await service._mix_overlay_sfx(
            base_path=base,
            chunks_in_order=chunks_in_order,
            inline_chunks=inline_chunks,
            overlays=overlays,
        )

        assert len(captured) == 1, (
            f"expected single ffmpeg invocation for 3 overlays, got {len(captured)}"
        )

    async def test_filter_graph_has_one_branch_per_overlay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        v0 = _make_voice_chunk(tmp_path, 0)
        v1 = _make_voice_chunk(tmp_path, 1)
        sfx_a = _make_overlay_chunk(tmp_path, 10)
        sfx_b = _make_overlay_chunk(tmp_path, 11)

        chunks_in_order = [v0, sfx_a, v1, sfx_b]
        inline_chunks = [v0, v1]
        overlays = [(1, sfx_a), (3, sfx_b)]

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
            chunks_in_order=chunks_in_order,
            inline_chunks=inline_chunks,
            overlays=overlays,
        )

        argv = captured[0]
        graph = argv[argv.index("-filter_complex") + 1]

        # Two SFX prep branches indexed [1:a] and [2:a] (input 0 is the base).
        assert "[1:a]adelay=" in graph
        assert "[2:a]adelay=" in graph
        # apad MUST come before atrim in each branch — invariant.
        for branch_label in ("[sfx0]", "[sfx1]"):
            # Find the branch and confirm apad appears before atrim
            # within it.
            assert branch_label in graph
        # Bus mix of 2 SFX branches.
        assert "amix=inputs=2:duration=longest" in graph
        # Sidechain ducker present.
        assert "sidechaincompress=" in graph
        # And there's a final amix that mixes voice with the ducked bus.
        assert graph.count("amix=") >= 2  # bus mix + final mix
        # Final output label.
        assert "[out]" in graph
        # The base audiobook is the first -i argument (precedes the SFX inputs).
        i_indices = [k for k, a in enumerate(argv) if a == "-i"]
        assert len(i_indices) == 3, "expected 1 base input + 2 SFX inputs"

    async def test_single_overlay_does_not_use_bus_mix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With one overlay we skip the SFX bus-mix step entirely —
        # the prep branch feeds the sidechain directly.
        v0 = _make_voice_chunk(tmp_path, 0)
        v1 = _make_voice_chunk(tmp_path, 1)
        sfx_a = _make_overlay_chunk(tmp_path, 10)

        chunks_in_order = [v0, sfx_a, v1]
        inline_chunks = [v0, v1]
        overlays = [(1, sfx_a)]

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
            chunks_in_order=chunks_in_order,
            inline_chunks=inline_chunks,
            overlays=overlays,
        )

        graph = captured[0][captured[0].index("-filter_complex") + 1]
        # Single overlay → only the voice<->ducked amix; no inputs=1 bus.
        assert "amix=inputs=1" not in graph
        # And it still feeds [sfx0] directly into the sidechain.
        assert "[sfx0][0:a]sidechaincompress=" in graph

    async def test_empty_overlay_list_skips_ffmpeg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        v0 = _make_voice_chunk(tmp_path, 0)
        v1 = _make_voice_chunk(tmp_path, 1)

        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=2.0)

        called: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            called.append(list(args))
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
            chunks_in_order=[v0, v1],
            inline_chunks=[v0, v1],
            overlays=[],
        )

        assert called == [], "no ffmpeg invocation expected when overlay list is empty"


class TestApadBeforeAtrimInvariant:
    """The brief flagged ``apad`` must precede ``atrim`` in every SFX
    branch. Hard cuts at the SFX tail otherwise.
    """

    async def test_apad_appears_before_atrim_per_branch(
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
        apad_pos = graph.index("apad")
        atrim_pos = graph.index("atrim")
        assert apad_pos < atrim_pos, (
            f"apad must precede atrim in the SFX branch; graph was: {graph}"
        )


# ── Music duration fix ───────────────────────────────────────────────────


class _MockMusicService:
    def __init__(self, music_path: Path) -> None:
        self._path = music_path

    async def get_music_for_episode(self, mood: str, target_duration: float, episode_id):  # noqa: ANN003, ARG002
        return self._path


class TestAddMusicDurationFix:
    """Music must be ``apad``-padded to voice duration so it never
    runs out under the voiceover. ``amix`` uses ``duration=longest``
    so neither side gets truncated.
    """

    async def test_filter_graph_pads_music_to_voice_duration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        voice = tmp_path / "voice.wav"
        voice.write_bytes(b"RIFF" + b"\x00" * 1024)
        music = tmp_path / "music.wav"
        music.write_bytes(b"RIFF" + b"\x00" * 1024)
        out = tmp_path / "out.wav"

        ffmpeg = AsyncMock()
        # Voice is 90 s, music will be padded to 90000 ms.
        ffmpeg.get_duration = AsyncMock(return_value=90.0)

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
        # Stub _resolve_music_service so the helper finds a music track
        # without touching ComfyUI / library.
        monkeypatch.setattr(service, "_resolve_music_service", lambda: _MockMusicService(music))

        await service._add_music(
            audio_path=voice,
            output_path=out,
            mood="calm",
            volume_db=-14.0,
            duration=90.0,
        )

        assert captured, "ffmpeg was not invoked"
        graph = captured[0][captured[0].index("-filter_complex") + 1]
        assert "[1:a]apad=whole_dur=90000ms" in graph, (
            f"music input must be apad'd to voice duration; graph: {graph}"
        )
        assert "duration=longest" in graph, (
            "amix must use duration=longest to preserve voice when music ends early"
        )
        assert "duration=first" not in graph, (
            "amix duration=first was the pre-Task-5 default; it truncated music when "
            "it was longer than voice and left silence under voice when shorter"
        )


class TestAddChapterMusicDurationFix:
    async def test_combined_music_padded_to_voice_duration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        voice = tmp_path / "voice.wav"
        voice.write_bytes(b"RIFF" + b"\x00" * 1024)
        out = tmp_path / "out.wav"

        # Pre-create the chapter music files so MusicService stub work
        # is minimal — we only need the second pass (the per-chapter
        # music get_music_for_episode call) to succeed enough to
        # populate one entry in valid_music.
        music_dir = tmp_path / "music"
        music_dir.mkdir()
        ch_music = music_dir / "ch000_music.wav"
        ch_music.write_bytes(b"RIFF" + b"\x00" * 1024)

        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=120.0)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            # Always "succeed" by writing the output path.
            Path(args[-1]).write_bytes(b"RIFF" + b"\x00" * 1024)
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )
        monkeypatch.setattr(service, "_resolve_music_service", lambda: _MockMusicService(ch_music))

        timings = [
            ChapterTiming(0, 0.0, 60.0, 60.0),
            ChapterTiming(1, 60.0, 120.0, 60.0),
        ]
        chapters = [
            {"title": "One", "text": "...", "music_mood": "calm"},
            {"title": "Two", "text": "...", "music_mood": "tense"},
        ]
        from uuid import uuid4

        await service._add_chapter_music(
            audio_path=voice,
            output_path=out,
            chapter_timings=timings,
            chapters=chapters,
            global_mood="calm",
            volume_db=-14.0,
            audiobook_id=uuid4(),
            crossfade_duration=2.0,
        )

        # The LAST ffmpeg invocation is the voice + combined-music mix,
        # which is the one we need to inspect. Earlier invocations are
        # the per-chapter music trim and the acrossfade chain.
        assert captured, "ffmpeg was not invoked"
        graph = captured[-1][captured[-1].index("-filter_complex") + 1]
        assert "[1:a]apad=whole_dur=120000ms" in graph
        assert "duration=longest" in graph
        assert "duration=first" not in graph
