"""Tests for the debounced cancellation path (Task 10)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from drevalis.schemas.audiobook import AudiobookSettings
from drevalis.services.audiobook._monolith import (
    AudiobookService,
    CancelChecker,
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


# ── CancelChecker mechanics ──────────────────────────────────────────────


class TestCancelChecker:
    async def test_check_no_op_when_redis_none(self) -> None:
        checker = CancelChecker(redis=None, audiobook_id=uuid4())
        # Must not raise; must not block.
        await checker.check()

    async def test_check_raises_when_flag_set(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")
        checker = CancelChecker(redis=redis, audiobook_id=uuid4())
        with pytest.raises(asyncio.CancelledError):
            await checker.check()

    async def test_check_silent_when_flag_unset(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        checker = CancelChecker(redis=redis, audiobook_id=uuid4())
        await checker.check()  # no raise

    async def test_redis_exception_swallowed(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        checker = CancelChecker(redis=redis, audiobook_id=uuid4())
        # Must NOT raise — cancellation is UX, not correctness.
        await checker.check()

    async def test_debounces_under_one_second(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        checker = CancelChecker(redis=redis, audiobook_id=uuid4())

        # 50 quick calls in tight succession → only the first hits Redis.
        for _ in range(50):
            await checker.check()
        assert redis.get.await_count == 1, (
            f"expected 1 Redis call (debounce), got {redis.get.await_count}"
        )

    async def test_debounce_lifts_after_one_second(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        ab_id = uuid4()
        checker = CancelChecker(redis=redis, audiobook_id=ab_id)

        await checker.check()
        # Forge the timestamp to simulate 1.5 s elapsed.
        checker._last_check = time.monotonic() - 1.5
        await checker.check()

        assert redis.get.await_count == 2


# ── _cancel instance helper ──────────────────────────────────────────────


class TestServiceCancel:
    async def test_no_checker_is_noop(self, tmp_path: Path) -> None:
        # No CancelChecker stashed (helper called outside generate).
        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        await service._cancel()  # must not raise

    async def test_with_checker_propagates_cancel(self, tmp_path: Path) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")
        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        service._cancel_checker = CancelChecker(redis=redis, audiobook_id=uuid4())
        with pytest.raises(asyncio.CancelledError):
            await service._cancel()


# ── _apply_master_loudnorm cancel ────────────────────────────────────────


class TestMasterLoudnormCancellation:
    async def test_cancel_before_loudnorm_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wav = tmp_path / "audiobook.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 4096)

        ffmpeg_called: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            ffmpeg_called.append(list(args))
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        service._settings = AudiobookSettings()

        # Cancel flag pre-set.
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")
        service._cancel_checker = CancelChecker(redis=redis, audiobook_id=uuid4())

        with pytest.raises(asyncio.CancelledError):
            await service._apply_master_loudnorm(wav)

        assert ffmpeg_called == [], (
            "ffmpeg should not have been spawned — cancel must abort before any pass"
        )


# ── _add_music cancel ────────────────────────────────────────────────────


class _MockMusicService:
    def __init__(self, music_path: Path) -> None:
        self._path = music_path

    async def get_music_for_episode(self, mood: str, target_duration: float, episode_id):  # noqa: ANN003, ARG002
        return self._path


class TestAddMusicCancellation:
    async def test_cancel_before_music_resolve(
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
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )
        service._settings = AudiobookSettings()
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")
        service._cancel_checker = CancelChecker(redis=redis, audiobook_id=uuid4())

        # Even though we patch _resolve_music_service, the ``await self._cancel()``
        # at the top of _add_music should fire FIRST.
        monkeypatch.setattr(service, "_resolve_music_service", lambda: _MockMusicService(music))

        with pytest.raises(asyncio.CancelledError):
            await service._add_music(
                audio_path=voice,
                output_path=tmp_path / "out.wav",
                mood="calm",
                volume_db=-22.0,
                duration=60.0,
            )

        assert captured == [], "no ffmpeg call should occur after a pre-set cancel"


# ── _mix_overlay_sfx cancel ──────────────────────────────────────────────


class TestMixOverlaySfxCancellation:
    async def test_cancel_before_overlay_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from drevalis.services.audiobook._monolith import AudioChunk

        v0 = tmp_path / "ch000_chunk_0000.wav"
        v0.write_bytes(b"RIFF" + b"\x00" * 1024)
        sfx = tmp_path / "ch000_sfx_0000.wav"
        sfx.write_bytes(b"RIFF" + b"\x00" * 1024)
        base = tmp_path / "audiobook.wav"
        base.write_bytes(b"RIFF" + b"\x00" * 1024)

        v_chunk = AudioChunk(
            path=v0, chapter_index=0, speaker="Narrator", block_index=0, chunk_index=0
        )
        sfx_chunk = AudioChunk(
            path=sfx,
            chapter_index=0,
            speaker="__SFX__",
            block_index=10,
            chunk_index=0,
            overlay_voice_blocks=1,
        )

        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=2.0)

        captured: list[list[str]] = []

        async def _fake_exec(*args: str, **kwargs):  # noqa: ANN003, ARG001
            captured.append(list(args))
            return _CapturedProc(returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")
        service._cancel_checker = CancelChecker(redis=redis, audiobook_id=uuid4())

        with pytest.raises(asyncio.CancelledError):
            await service._mix_overlay_sfx(
                base_path=base,
                chunks_in_order=[v_chunk, sfx_chunk],
                inline_chunks=[v_chunk],
                overlays=[(1, sfx_chunk)],
            )

        assert captured == [], "no ffmpeg invocation expected after a pre-set cancel flag"


# ── Synthesize-chunk-with-retry uses debounced checker ───────────────────


class TestSynthesizeRetryUsesDebouncedChecker:
    """The retry loop now polls via ``_cancel`` (debounced) instead of
    raw ``_check_cancelled`` (not debounced). 30 in-flight chunks
    should produce ~1 Redis call, not 30.
    """

    async def test_redis_traffic_bounded_by_debounce(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Stub the synth path so each chunk completes quickly without
        # touching real ffmpeg or providers.
        provider = AsyncMock()

        async def _synth(text, voice_id, path, *, speed, pitch):  # noqa: ANN001, ANN003, ARG001
            path.write_bytes(b"RIFF" + b"\x00" * 1024)

        provider.synthesize = AsyncMock(side_effect=_synth)
        provider.__class__.__name__ = "EdgeTTSProvider"

        # _safety_filter_chunk is a bound method on AudiobookService;
        # the stub needs to accept ``self`` too.
        async def _noop_safety(self, p):  # noqa: ANN001, ARG001
            return None

        monkeypatch.setattr(AudiobookService, "_safety_filter_chunk", _noop_safety)

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
            redis=redis,
        )
        service._cancel_checker = CancelChecker(redis=redis, audiobook_id=uuid4())

        # Run 30 retry-loop attempts (single attempt each since synth
        # succeeds on first try) and confirm Redis was hit at most once
        # within the 1-second window.
        for i in range(30):
            chunk_path = tmp_path / f"chunk_{i:04d}.wav"
            await service._synthesize_chunk_with_retry(
                provider, "hello", "amy", chunk_path, speed=1.0, pitch=1.0
            )

        assert redis.get.await_count <= 2, (
            f"debounced cancel poll should hit Redis at most ~1 time per second; "
            f"got {redis.get.await_count} calls in tight loop"
        )
