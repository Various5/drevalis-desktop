"""Tests for provider-aware chunking + bracket invariant (Task 12)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    CHUNK_LIMITS,
    AudiobookService,
    _chunk_limit,
)


def _svc() -> AudiobookService:
    """Bare service instance for parser methods that don't touch I/O."""
    return AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )


# ── _chunk_limit ─────────────────────────────────────────────────────────


class TestChunkLimitLookup:
    def test_piper_limit(self) -> None:
        assert _chunk_limit("PiperTTSProvider") == 700

    def test_kokoro_limit(self) -> None:
        assert _chunk_limit("KokoroTTSProvider") == 900

    def test_edge_limit(self) -> None:
        assert _chunk_limit("EdgeTTSProvider") == 1200

    def test_elevenlabs_limit(self) -> None:
        assert _chunk_limit("ElevenLabsTTSProvider") == 2200

    def test_comfyui_elevenlabs_resolves_longest_match(self) -> None:
        # ``comfyui_elevenlabs`` and ``elevenlabs`` both happen to be
        # 2200; longest-key-wins still applies for symmetry with
        # _provider_concurrency. Verified via the provider name.
        assert _chunk_limit("ComfyUIElevenLabsTTSProvider") == 2200

    def test_unknown_falls_back_to_default(self) -> None:
        assert _chunk_limit("SomeMysteryProvider") == 700

    def test_case_insensitive(self) -> None:
        assert _chunk_limit("PIPER_TTS") == 700
        assert _chunk_limit("edgetts") == 1200

    def test_chunk_limits_dict_carries_expected_providers(self) -> None:
        assert set(CHUNK_LIMITS.keys()) == {
            "piper",
            "kokoro",
            "edge",
            "elevenlabs",
            "comfyui_elevenlabs",
        }


# ── _split_text basics ───────────────────────────────────────────────────


class TestSplitTextBasics:
    def test_empty_returns_empty_string(self) -> None:
        assert _svc()._split_text("", max_chars=500) == [""]

    def test_whitespace_only_returns_empty_string(self) -> None:
        assert _svc()._split_text("   \n\n  ", max_chars=500) == [""]

    def test_short_text_is_one_chunk(self) -> None:
        assert _svc()._split_text("Just a short line.", max_chars=500) == ["Just a short line."]

    def test_max_chars_respected(self) -> None:
        # 100 short sentences + max=500 → multiple chunks, none over 500.
        text = "Hello there. " * 100
        chunks = _svc()._split_text(text, max_chars=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 500


# ── Larger limit ⇒ fewer chunks ──────────────────────────────────────────


class TestProviderLimitProducesFewerChunks:
    def test_elevenlabs_2200_vs_piper_700(self) -> None:
        # Long body of consistent sentences.
        text = "Hello there. " * 200
        chunks_700 = _svc()._split_text(text, max_chars=700)
        chunks_2200 = _svc()._split_text(text, max_chars=2200)
        assert len(chunks_2200) < len(chunks_700)
        # Brief acceptance: ~30% fewer chunks. We're more permissive
        # — anything ≤ 70% of the smaller-limit chunk count satisfies
        # the contract.
        assert len(chunks_2200) <= len(chunks_700) * 0.7, (
            f"expected ≤70% chunk count at 2200 vs 700; got {len(chunks_2200)} vs {len(chunks_700)}"
        )


# ── Paragraph priority ───────────────────────────────────────────────────


class TestParagraphSplit:
    def test_paragraph_boundaries_packed_when_fit(self) -> None:
        # Each paragraph alone < max_chars, all together also < max_chars
        # → 1 chunk.
        text = "Para 1, short.\n\nPara 2, also short.\n\nPara 3."
        chunks = _svc()._split_text(text, max_chars=500)
        assert len(chunks) == 1

    def test_oversize_paragraph_splits_on_sentences(self) -> None:
        # One paragraph that exceeds max_chars; must split internally.
        para = "Some long sentence. " * 50  # ~ 1000 chars
        chunks = _svc()._split_text(para, max_chars=300)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 300


# ── Bracket invariant ────────────────────────────────────────────────────


class TestBracketInvariant:
    def test_sfx_tag_not_split_across_chunks(self) -> None:
        # Construct a text where the natural split lands on the [SFX:]
        # token. Make the prefix exactly the chunk-limit boundary so
        # the bracket repair has to kick in.
        prefix = "A short sentence here. " * 5  # ~ 110 chars
        sfx = "[SFX: heavy rain on the porch | dur=4]"
        suffix = " She paused and looked outside. " * 10
        text = f"{prefix}{sfx} {suffix}"
        chunks = _svc()._split_text(text, max_chars=120)
        for chunk in chunks:
            # No chunk should END with an unmatched '['.
            assert chunk.count("[") == chunk.count("]"), f"unbalanced brackets in chunk: {chunk!r}"

    def test_speaker_tag_kept_intact(self) -> None:
        text = (
            "First narrator line that is reasonably long. "
            "[Jack] Hey, what is going on here?"
            " More narration that follows the dialogue tag."
        )
        chunks = _svc()._split_text(text, max_chars=80)
        for chunk in chunks:
            assert chunk.count("[") == chunk.count("]"), f"chunk {chunk!r} has unbalanced brackets"

    def test_well_formed_text_passes_through_repair_unchanged(self) -> None:
        # Sanity: the repair doesn't mangle text where no bracket
        # straddles a boundary.
        text = "A. " * 200
        chunks = _svc()._split_text(text, max_chars=500)
        joined = " ".join(chunks)
        # Original has 200 sentences; rejoining shouldn't lose any.
        assert joined.count("A.") == 200


# ── Comma fallback ───────────────────────────────────────────────────────


class TestCommaFallback:
    def test_runaway_sentence_falls_back_to_commas(self) -> None:
        # A sentence with no terminal punctuation that exceeds max_chars
        # — must split on commas.
        sentence = ", ".join([f"clause number {i}" for i in range(100)]) + "."
        chunks = _svc()._split_text(sentence, max_chars=300)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 300


# ── Wire-up: callers pass the right limit ────────────────────────────────


class TestSplitTextWireUp:
    """``_generate_single_voice`` and ``_generate_multi_voice`` should
    both pass the per-provider limit to ``_split_text``.
    """

    async def test_single_voice_uses_provider_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[int] = []

        original = AudiobookService._split_text

        def _wrapped(self, text: str, max_chars: int) -> list[str]:
            captured.append(max_chars)
            return original(self, text, max_chars)

        monkeypatch.setattr(AudiobookService, "_split_text", _wrapped)

        # Stub the rest of the synth path so the call resolves quickly.
        async def _noop_safety(self, p):  # noqa: ANN001, ARG001
            return None

        monkeypatch.setattr(AudiobookService, "_safety_filter_chunk", _noop_safety)

        provider = AsyncMock()

        async def _synth(text, voice_id, path, *, speed, pitch):  # noqa: ANN001, ANN003, ARG001
            from pathlib import Path as _P

            _P(path).write_bytes(b"RIFF" + b"\x00" * 1024)

        provider.synthesize = AsyncMock(side_effect=_synth)
        # ``_provider_identity`` checks ``.name`` before falling back
        # to ``type(provider).__name__``; setting ``__class__.__name__``
        # on a Mock doesn't take, so use ``.name`` directly.
        provider.name = "EdgeTTSProvider"

        class _StubTTS:
            def get_provider(self, vp):  # noqa: ARG002
                return provider

            def _voice_id_for(self, vp):  # noqa: ARG002
                return "amy"

        class _VP:
            id = "11111111-1111-1111-1111-111111111111"
            provider = "edge"
            model_name = "en_US-amy"

        import tempfile
        from pathlib import Path as _P

        tmp = _P(tempfile.mkdtemp())

        class _Storage:
            def __init__(self, base):
                self.base_path = base

            def resolve_path(self, rel):
                return self.base_path / rel

        service = AudiobookService(
            tts_service=_StubTTS(),
            ffmpeg_service=AsyncMock(),
            storage=_Storage(tmp),
        )
        service._current_audiobook_id = None  # disables cancel poll

        await service._generate_single_voice(
            text="A short body for chunking.",
            voice_profile=_VP(),
            output_dir=tmp,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        assert captured, "_split_text was never called"
        # Edge default = 1200.
        assert captured[0] == 1200, f"expected Edge limit (1200), got {captured[0]}"
