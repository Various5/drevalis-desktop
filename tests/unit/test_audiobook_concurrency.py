"""Tests for per-provider TTS concurrency (Task 4).

Pre-Task-4, chunks within a chapter rendered strictly sequentially.
Post-Task-4, they render concurrently up to a per-provider in-flight
cap (``_PROVIDER_CONCURRENCY``). Cancellation polling fires at every
TTS attempt so users don't have to wait for a hundreds-of-chunks
chapter to drain before Cancel takes effect.

These tests guard:

  * ``_provider_concurrency`` resolution (substring + longest-key-wins).
  * Env-var override on ElevenLabs.
  * Singleton ``asyncio.Semaphore`` per provider name.
  * ``_generate_single_voice`` parallelises up to the cap (mock provider
    counts in-flight invocations).
  * Cache hits don't burn semaphore slots.
  * Output ordering is stable regardless of provider completion order.
  * Mid-chapter cancel raises CancelledError out of gather.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    _PROVIDER_SEMAPHORES,
    AudiobookService,
    _get_provider_semaphore,
    _provider_concurrency,
)


class _StubStorage:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def resolve_path(self, rel: str) -> Path:
        return self.base_path / rel


# ── _provider_concurrency ────────────────────────────────────────────────


class TestProviderConcurrencyLookup:
    def test_piper_default(self) -> None:
        assert _provider_concurrency("PiperTTSProvider") == 2

    def test_kokoro_default(self) -> None:
        assert _provider_concurrency("KokoroTTSProvider") == 4

    def test_edge_default(self) -> None:
        assert _provider_concurrency("EdgeTTSProvider") == 6

    def test_elevenlabs_default(self) -> None:
        assert _provider_concurrency("ElevenLabsTTSProvider") == 2

    def test_comfyui_elevenlabs_resolves_to_one_not_two(self) -> None:
        # Longest-key-wins: ``comfyui_elevenlabs`` (1) must win over
        # the plain ``elevenlabs`` (2) substring match.
        assert _provider_concurrency("ComfyUIElevenLabsTTSProvider") == 1
        assert _provider_concurrency("ComfyUIElevenLabsSoundEffectsProvider") == 1

    def test_unknown_provider_falls_back_to_two(self) -> None:
        assert _provider_concurrency("SomeMysteryProvider") == 2

    def test_case_insensitive(self) -> None:
        assert _provider_concurrency("PIPER") == 2
        assert _provider_concurrency("edge_tts") == 6

    def test_elevenlabs_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ELEVENLABS_CONCURRENCY", "5")
        assert _provider_concurrency("ElevenLabsTTSProvider") == 5

    def test_elevenlabs_env_override_invalid_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ELEVENLABS_CONCURRENCY", "abc")
        assert _provider_concurrency("ElevenLabsTTSProvider") == 2
        monkeypatch.setenv("ELEVENLABS_CONCURRENCY", "0")
        assert _provider_concurrency("ElevenLabsTTSProvider") == 2

    def test_elevenlabs_env_does_not_affect_comfyui_elevenlabs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ELEVENLABS_CONCURRENCY", "8")
        # ComfyUI-routed ElevenLabs goes through ComfyUI's own pool —
        # the env knob must not override it.
        assert _provider_concurrency("ComfyUIElevenLabsTTSProvider") == 1


# ── _get_provider_semaphore ─────────────────────────────────────────────


class TestProviderSemaphoreSingleton:
    def setup_method(self) -> None:
        # Tests share a process-wide registry — clear so the test is
        # deterministic regardless of order.
        _PROVIDER_SEMAPHORES.clear()

    def test_same_name_returns_same_semaphore(self) -> None:
        a = _get_provider_semaphore("PiperTTSProvider")
        b = _get_provider_semaphore("PiperTTSProvider")
        assert a is b

    def test_different_names_yield_different_semaphores(self) -> None:
        a = _get_provider_semaphore("PiperTTSProvider")
        b = _get_provider_semaphore("EdgeTTSProvider")
        assert a is not b


# ── _generate_single_voice parallelism ──────────────────────────────────


class _ConcurrencyTrackingProvider:
    """Mock TTS provider that records max in-flight concurrency."""

    def __init__(self, hold_seconds: float = 0.05) -> None:
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0
        self.completion_order: list[str] = []
        self.hold = hold_seconds
        self._lock = asyncio.Lock()

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        path: Path,
        *,
        speed: float,
        pitch: float,
    ) -> None:
        async with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.calls += 1
        await asyncio.sleep(self.hold)
        async with self._lock:
            self.in_flight -= 1
            self.completion_order.append(text)
        # Write a real-enough file so the cache check downstream passes.
        path.write_bytes(b"RIFF" + b"\x00" * 1024)


class _StubVoiceProfile:
    def __init__(self) -> None:
        self.id = "11111111-1111-1111-1111-111111111111"
        self.provider = "edge"
        self.model_name = "en_US-amy"


class _StubTTSService:
    def __init__(self, provider: _ConcurrencyTrackingProvider) -> None:
        self._provider = provider

    def get_provider(self, voice_profile) -> _ConcurrencyTrackingProvider:  # noqa: ARG002
        return self._provider

    def _voice_id_for(self, voice_profile) -> str:  # noqa: ARG002
        return "amy"


class TestGenerateSingleVoiceParallelism:
    def setup_method(self) -> None:
        _PROVIDER_SEMAPHORES.clear()

    async def test_chunks_render_concurrently_up_to_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force the provider's class name to map to a known cap of 6
        # (the default for "edge"). 12 chunks split text → at least 2
        # waves of in-flight work expected.
        provider = _ConcurrencyTrackingProvider(hold_seconds=0.05)
        # Override the class lookup so _provider_identity sees "edge".
        provider.__class__.__name__ = "EdgeTTSProvider"

        # _safety_filter_chunk runs ffmpeg per chunk after synth — short
        # circuit it so the test stays fast and ffmpeg-free.
        # Stub takes ``self`` because it's bound on the class.
        async def _noop_safety(self, chunk_path: Path) -> None:  # noqa: ANN001, ARG001
            return None

        monkeypatch.setattr(AudiobookService, "_safety_filter_chunk", _noop_safety)

        service = AudiobookService(
            tts_service=_StubTTSService(provider),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        # Provide audiobook_id so the cancel-poll path is reachable
        # without raising. Mock redis returns None → no cancel.
        service._current_audiobook_id = None  # disables cancel poll

        # Edge's chunk limit is 1200 (Task 12). Use 480-char sentences
        # so the splitter produces ~12 chunks rather than packing all
        # into one. (Pre-Task-12 default 500 max_chars produced 12+
        # chunks from the old fixture; the new larger limit needs a
        # longer fixture to exercise the parallelism cap.)
        long_sentence = "A" * 480
        text = ". ".join(long_sentence for _ in range(15)) + "."
        chunks = await service._generate_single_voice(
            text=text,
            voice_profile=_StubVoiceProfile(),
            output_dir=tmp_path,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        assert provider.calls > 0, "provider was never called"
        # Edge cap is 6 — we expect to see a peak in-flight of 6 once
        # there are at least 6 chunks queued. Don't assert == 6 because
        # tasks can complete before the next is scheduled in the loop;
        # do assert > 1 (parallelism actually happened) and <= 6 (cap).
        assert provider.max_in_flight > 1, (
            f"chunks rendered serially (max in-flight = {provider.max_in_flight}); "
            "Task 4 parallelism not engaged."
        )
        assert provider.max_in_flight <= 6, (
            f"max in-flight {provider.max_in_flight} exceeds the Edge cap of 6"
        )

        # Output ordering must follow chunk_index regardless of which
        # ffmpeg invocation completed first.
        indices = [c.chunk_index for c in chunks]
        assert indices == sorted(indices), f"AudioChunk list out of order: {indices}"

    async def test_cache_hits_do_not_take_semaphore_slots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pre-populate cached chunks for every sentence so the synth
        # path never executes; provider should record 0 calls.
        provider = _ConcurrencyTrackingProvider(hold_seconds=0.0)
        provider.__class__.__name__ = "PiperTTSProvider"

        async def _noop_safety(chunk_path: Path) -> None:  # noqa: ARG001
            return None

        monkeypatch.setattr(AudiobookService, "_safety_filter_chunk", _noop_safety)

        service = AudiobookService(
            tts_service=_StubTTSService(provider),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        service._current_audiobook_id = None

        # Compute the exact cache hashes that _generate_single_voice
        # will produce and seed the cache files.
        from drevalis.services.audiobook._monolith import _chunk_cache_hash

        text = ". ".join(f"Sentence {i}" for i in range(5)) + "."
        # Replicate the splitter — same as production.
        from drevalis.services.audiobook._monolith import AudiobookService as Svc

        split = Svc._split_text(service, text, max_chars=500)  # type: ignore[arg-type]
        for i, t in enumerate(split):
            h = _chunk_cache_hash(
                text=t,
                speaker_id="Narrator",
                voice_profile_id=_StubVoiceProfile().id,
                provider="PiperTTSProvider",
                model="en_US-amy",
                speed=1.0,
                pitch=1.0,
                sample_rate=24000,
            )
            (tmp_path / f"ch000_chunk_{i:04d}_{h}.wav").write_bytes(b"RIFF" + b"\x00" * 1024)

        chunks = await service._generate_single_voice(
            text=text,
            voice_profile=_StubVoiceProfile(),
            output_dir=tmp_path,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        assert provider.calls == 0, (
            f"cache hits should not invoke the provider, but it ran {provider.calls} times"
        )
        assert len(chunks) == len(split)


# ── Cancellation propagation ────────────────────────────────────────────


class TestCancellationMidChapter:
    def setup_method(self) -> None:
        _PROVIDER_SEMAPHORES.clear()

    async def test_cancelled_error_propagates_out_of_gather(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = _ConcurrencyTrackingProvider(hold_seconds=0.01)
        provider.__class__.__name__ = "EdgeTTSProvider"

        # _safety_filter_chunk is bound; stub takes ``self`` too.
        async def _noop_safety(self, chunk_path: Path) -> None:  # noqa: ANN001, ARG001
            return None

        monkeypatch.setattr(AudiobookService, "_safety_filter_chunk", _noop_safety)

        service = AudiobookService(
            tts_service=_StubTTSService(provider),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )
        from uuid import uuid4

        ab_id = uuid4()
        service._current_audiobook_id = ab_id

        # Task 10: the retry loop now polls ``_cancel`` (debounced),
        # not raw ``_check_cancelled``. Stub the new method to raise
        # after the first call so a mid-chapter cancel materialises.
        call_count = {"n": 0}

        async def _fake_cancel() -> None:
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise asyncio.CancelledError("user cancelled")

        monkeypatch.setattr(service, "_cancel", _fake_cancel)

        # Long enough to split into many chunks (max_chars=500 each)
        # so multiple gather'd render coroutines call _cancel and the
        # second one trips the raise.
        long_sentence = "A" * 480
        text = ". ".join(long_sentence for _ in range(10)) + "."

        with pytest.raises(asyncio.CancelledError):
            await service._generate_single_voice(
                text=text,
                voice_profile=_StubVoiceProfile(),
                output_dir=tmp_path,
                chapter_index=0,
                speed=1.0,
                pitch=1.0,
            )
