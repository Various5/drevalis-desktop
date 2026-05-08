"""Pure-helper coverage for ``services/audiobook/_monolith.py`` (F-Tst-07).

The audiobook monolith is 1631 stmts at ~43% coverage. The big-async
generation paths (multi-voice rendering, ffmpeg invocation, multi-output
export) need a heavy mock harness to test. This file targets the
unit-testable seams that ship without one:

- ``_build_music_mix_graph`` — pure ffmpeg filter_complex string
- ``_mp3_encoder_args`` — pure encoder argv builder
- ``_resolve_ducking_preset`` — case-insensitive preset lookup
- ``_chunk_limit`` / ``_provider_concurrency`` — substring routing
- ``_chunk_cache_hash`` / ``_strip_chunk_hash`` — content-hash cache key
- ``_provider_identity`` — best-effort attribute extraction
- ``AudiobookService._score_chapter_split`` — split-quality scorer
- ``AudiobookService._filter_markdown_matches`` — heading-context filter
- ``AudiobookService._filter_allcaps_matches`` — alpha-ratio filter
- ``AudiobookService._split_long_sentence`` — comma fallback splitter
- ``AudiobookService._repair_bracket_splits`` — keeps ``[…]`` intact

Coverage delta: ~70 lines previously uncovered are now exercised.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from drevalis.services.audiobook._monolith import (
    DEFAULT_DUCKING_PRESET,
    DUCKING_PRESETS,
    AudiobookService,
    _build_music_mix_graph,
    _chunk_cache_hash,
    _chunk_limit,
    _mp3_encoder_args,
    _provider_concurrency,
    _provider_identity,
    _resolve_ducking_preset,
    _strip_chunk_hash,
)

# ── _build_music_mix_graph ────────────────────────────────────────────────


class TestBuildMusicMixGraph:
    def test_static_mode_omits_sidechain(self) -> None:
        graph = _build_music_mix_graph(
            preset={"mode": "static"},
            voice_gain_db=0.0,
            music_volume_db=-22.0,
            music_pad_ms=0,
        )
        assert "sidechaincompress" not in graph
        assert "amix=inputs=2" in graph
        assert "alimiter" in graph
        assert "[0:a]volume=+0.0dB[voice]" in graph
        assert "[1:a]apad=whole_dur=0ms,volume=-22.0dB[bgm]" in graph

    def test_sidechain_mode_includes_compressor(self) -> None:
        graph = _build_music_mix_graph(
            preset={
                "mode": "sidechain",
                "threshold": 0.1,
                "ratio": 4,
                "attack": 10,
                "release": 600,
            },
            voice_gain_db=2.5,
            music_volume_db=-18.0,
            music_pad_ms=500,
        )
        assert "[bgm][voice]sidechaincompress=" in graph
        assert "threshold=0.1" in graph
        assert "ratio=4" in graph
        assert "attack=10" in graph
        assert "release=600" in graph
        assert "[ducked]" in graph
        # Voice gain prefix should round to 1 decimal with explicit sign.
        assert "[0:a]volume=+2.5dB[voice]" in graph

    def test_negative_voice_gain_signed(self) -> None:
        graph = _build_music_mix_graph(
            preset={"mode": "static"},
            voice_gain_db=-3.5,
            music_volume_db=-22.0,
            music_pad_ms=0,
        )
        assert "[0:a]volume=-3.5dB[voice]" in graph


# ── _mp3_encoder_args ─────────────────────────────────────────────────────


class TestMp3EncoderArgs:
    def test_cbr_modes(self) -> None:
        for mode, bitrate in [("cbr_128", "128"), ("cbr_192", "192"), ("cbr_256", "256")]:
            args = _mp3_encoder_args(mode)
            assert args == ["-codec:a", "libmp3lame", "-b:a", f"{bitrate}k"]

    def test_vbr_v0(self) -> None:
        assert _mp3_encoder_args("vbr_v0") == ["-codec:a", "libmp3lame", "-q:a", "0"]

    def test_vbr_v2(self) -> None:
        assert _mp3_encoder_args("vbr_v2") == ["-codec:a", "libmp3lame", "-q:a", "2"]

    def test_unknown_mode_falls_back_to_192(self) -> None:
        # Unknown mode shouldn't fail the audiobook — the fallback is
        # the pre-Task-9 default of 192 kbps CBR.
        assert _mp3_encoder_args("flat_potato") == [
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
        ]


# ── _resolve_ducking_preset ───────────────────────────────────────────────


class TestResolveDuckingPreset:
    def test_none_returns_default(self) -> None:
        result = _resolve_ducking_preset(None)
        assert result is DUCKING_PRESETS[DEFAULT_DUCKING_PRESET]

    def test_known_preset_case_insensitive(self) -> None:
        for spelling in ("subtle", "SUBTLE", "  Subtle  "):
            result = _resolve_ducking_preset(spelling)
            assert result is DUCKING_PRESETS["subtle"]

    def test_unknown_preset_falls_back(self) -> None:
        result = _resolve_ducking_preset("nonexistent")
        # Don't compare by name — fall back is the default preset object.
        assert result is DUCKING_PRESETS[DEFAULT_DUCKING_PRESET]


# ── _chunk_limit ──────────────────────────────────────────────────────────


class TestChunkLimit:
    def test_known_providers(self) -> None:
        assert _chunk_limit("piper") == 700
        assert _chunk_limit("kokoro") == 900
        assert _chunk_limit("edge") == 1200
        assert _chunk_limit("elevenlabs") == 2200

    def test_longest_key_wins(self) -> None:
        # ``comfyui_elevenlabs`` should resolve to the ComfyUI cap (2200)
        # not split between the two — both happen to be 2200, but the
        # function picks the longer key first.
        assert _chunk_limit("comfyui_elevenlabs") == 2200

    def test_substring_match(self) -> None:
        assert _chunk_limit("PiperTTSProvider") == 700
        assert _chunk_limit("EdgeTTSProvider") == 1200

    def test_unknown_provider_default(self) -> None:
        assert _chunk_limit("totally_unknown") == 700  # _DEFAULT_CHUNK_LIMIT


# ── _provider_concurrency ─────────────────────────────────────────────────


class TestProviderConcurrency:
    def test_known_providers(self) -> None:
        assert _provider_concurrency("piper") == 2
        assert _provider_concurrency("kokoro") == 4
        assert _provider_concurrency("edge") == 6
        assert _provider_concurrency("elevenlabs") == 2  # _DEFAULT_ELEVENLABS_CONCURRENCY
        # ComfyUI route uses 1 — the underlying ComfyUI pool already
        # serialises requests so we don't double-up.
        assert _provider_concurrency("comfyui_elevenlabs") == 1

    def test_unknown_provider_default(self) -> None:
        assert _provider_concurrency("OtherProvider") == 2

    def test_elevenlabs_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("ELEVENLABS_CONCURRENCY", "8")
        assert _provider_concurrency("ElevenLabsTTSProvider") == 8

    def test_elevenlabs_env_invalid_ignored(self, monkeypatch) -> None:
        monkeypatch.setenv("ELEVENLABS_CONCURRENCY", "not-a-number")
        # Falls back to the configured default.
        assert _provider_concurrency("elevenlabs") == 2

    def test_elevenlabs_env_zero_ignored(self, monkeypatch) -> None:
        monkeypatch.setenv("ELEVENLABS_CONCURRENCY", "0")
        assert _provider_concurrency("elevenlabs") == 2

    def test_comfyui_route_ignores_elevenlabs_env(self, monkeypatch) -> None:
        # ComfyUI cap should NOT be bumped by the ElevenLabs env knob —
        # ComfyUI is its own bottleneck.
        monkeypatch.setenv("ELEVENLABS_CONCURRENCY", "16")
        assert _provider_concurrency("comfyui_elevenlabs") == 1


# ── _chunk_cache_hash + _strip_chunk_hash ─────────────────────────────────


class TestChunkCacheHash:
    def test_deterministic(self) -> None:
        kwargs = {
            "text": "hello world",
            "speaker_id": "narrator",
            "voice_profile_id": "vp-1",
            "provider": "piper",
            "model": "en_US-amy-medium",
            "speed": 1.0,
            "pitch": 1.0,
            "sample_rate": 22050,
        }
        a = _chunk_cache_hash(**kwargs)
        b = _chunk_cache_hash(**kwargs)
        assert a == b
        assert len(a) == 12
        # Hex characters only.
        assert re.fullmatch(r"[0-9a-f]{12}", a)

    def test_different_text_different_hash(self) -> None:
        base = {
            "speaker_id": "narrator",
            "voice_profile_id": "vp-1",
            "provider": "piper",
            "model": "en_US-amy-medium",
            "speed": 1.0,
            "pitch": 1.0,
            "sample_rate": 22050,
        }
        a = _chunk_cache_hash(text="A", **base)
        b = _chunk_cache_hash(text="B", **base)
        assert a != b

    def test_speed_change_invalidates(self) -> None:
        base = {
            "text": "hi",
            "speaker_id": "narrator",
            "voice_profile_id": "vp-1",
            "provider": "piper",
            "model": "en_US-amy-medium",
            "pitch": 1.0,
            "sample_rate": 22050,
        }
        assert _chunk_cache_hash(speed=1.0, **base) != _chunk_cache_hash(speed=1.1, **base)


class TestStripChunkHash:
    def test_strips_recognised_suffix(self) -> None:
        assert _strip_chunk_hash("ch003_chunk_0007_a1b2c3d4e5f6") == "ch003_chunk_0007"

    def test_no_hash_passthrough(self) -> None:
        assert _strip_chunk_hash("ch003_chunk_0007") == "ch003_chunk_0007"

    def test_short_hex_not_stripped(self) -> None:
        # 11 chars — not the 12-char hash format.
        assert _strip_chunk_hash("legacy_a1b2c3d4e5") == "legacy_a1b2c3d4e5"


# ── _provider_identity ────────────────────────────────────────────────────


class TestProviderIdentity:
    def test_uses_explicit_name_attr(self) -> None:
        provider = SimpleNamespace(name="my-provider")
        voice = SimpleNamespace(model_name="my-model")
        assert _provider_identity(provider, voice) == ("my-provider", "my-model")

    def test_falls_back_to_class_name(self) -> None:
        class MyProvider:
            pass

        provider = MyProvider()
        voice = SimpleNamespace()
        name, model = _provider_identity(provider, voice)
        assert name == "MyProvider"
        # No model_name / model / voice_id → empty string fallback.
        assert model == ""

    def test_voice_id_is_last_resort_for_model(self) -> None:
        provider = SimpleNamespace(provider_name="x")
        voice = SimpleNamespace(voice_id="voice-abc")
        assert _provider_identity(provider, voice) == ("x", "voice-abc")


# ── AudiobookService static helpers ───────────────────────────────────────


class TestScoreChapterSplit:
    def test_fewer_than_two_matches_returns_zero(self) -> None:
        m = list(re.finditer(r"X", "X some prose"))
        assert AudiobookService._score_chapter_split(m, "X some prose") == 0.0

    def test_too_short_segment_returns_zero(self) -> None:
        # Minimum segment length guard: matches close together → 0.
        text = "A" + "x" * 50 + "A" + "y" * 50 + "A"
        m = list(re.finditer(r"A", text))
        assert AudiobookService._score_chapter_split(m, text) == 0.0

    def test_consistent_segments_score_higher_than_noisy(self) -> None:
        # Same total length (so mean segment is constant), but ``even``
        # has zero variance and ``noisy`` has high variance — the
        # 1/(1+CV) factor should pull noisy below even.
        even = "X" + ("p" * 1000) + "X" + ("q" * 1000) + "X" + ("r" * 1000)
        noisy = "X" + ("p" * 600) + "X" + ("q" * 600) + "X" + ("r" * 1800)
        m_even = list(re.finditer(r"X", even))
        m_noisy = list(re.finditer(r"X", noisy))
        s_even = AudiobookService._score_chapter_split(m_even, even)
        s_noisy = AudiobookService._score_chapter_split(m_noisy, noisy)
        assert s_even > s_noisy


class TestFilterMarkdownMatches:
    def test_blank_line_anchored_kept(self) -> None:
        text = "Some intro.\n\n## Chapter 1\n\nBody of chapter 1."
        matches = list(re.finditer(r"^## (?P<title>.+)$", text, flags=re.MULTILINE))
        kept = AudiobookService._filter_markdown_matches(matches, text)
        assert len(kept) == 1

    def test_inline_heading_rejected(self) -> None:
        # ``## Note`` is part of running prose, not a chapter break.
        text = "Some sentence.\n## Note: this is inline\nMore prose."
        matches = list(re.finditer(r"^## (?P<title>.+)$", text, flags=re.MULTILINE))
        kept = AudiobookService._filter_markdown_matches(matches, text)
        assert kept == []

    def test_heading_at_end_of_text_kept(self) -> None:
        text = "Body.\n\n## Chapter 1"
        matches = list(re.finditer(r"^## (?P<title>.+)$", text, flags=re.MULTILINE))
        kept = AudiobookService._filter_markdown_matches(matches, text)
        assert len(kept) == 1


class TestFilterAllcapsMatches:
    def test_real_chapter_header_kept(self) -> None:
        text = "THE FIRST ENCOUNTER"
        matches = list(re.finditer(r"^(?P<title>[A-Z ]+)$", text, flags=re.MULTILINE))
        kept = AudiobookService._filter_allcaps_matches(matches)
        assert len(kept) == 1

    def test_screenplay_scene_cue_rejected_by_alpha_ratio(self) -> None:
        # Heavy non-alpha content (numbers, punctuation) → filtered.
        text = "INT. 1234 — DAY"
        matches = list(re.finditer(r"^(?P<title>.+)$", text, flags=re.MULTILINE))
        kept = AudiobookService._filter_allcaps_matches(matches)
        assert kept == []

    def test_trailing_comma_rejected(self) -> None:
        text = "FIRST PART,"
        matches = list(re.finditer(r"^(?P<title>.+)$", text, flags=re.MULTILINE))
        kept = AudiobookService._filter_allcaps_matches(matches)
        assert kept == []


class TestSplitLongSentence:
    def test_comma_fallback(self) -> None:
        sentence = "first piece, second piece, third piece, fourth piece, fifth piece"
        chunks = AudiobookService._split_long_sentence(sentence, 25)
        # Every chunk fits in the limit (or is one runaway piece).
        for chunk in chunks:
            assert len(chunk) <= 25 or "," not in chunk

    def test_runaway_piece_hard_split(self) -> None:
        long_token = "x" * 30
        chunks = AudiobookService._split_long_sentence(long_token, 10)
        # No comma to split on → hard character split into 10-char chunks.
        assert all(len(c) <= 10 for c in chunks)
        assert "".join(chunks) == long_token

    def test_short_sentence_returned_as_is(self) -> None:
        chunks = AudiobookService._split_long_sentence("short", 100)
        assert chunks == ["short"]


class TestRepairBracketSplits:
    def test_balanced_brackets_unchanged(self) -> None:
        chunks = ["First [Speaker] line.", "Second [SFX: bang] line."]
        assert AudiobookService._repair_bracket_splits(chunks) == chunks

    def test_single_chunk_returned_unchanged(self) -> None:
        chunks = ["just one chunk"]
        assert AudiobookService._repair_bracket_splits(chunks) == chunks

    def test_empty_list_returned_unchanged(self) -> None:
        assert AudiobookService._repair_bracket_splits([]) == []


class TestSplitText:
    def test_short_text_returns_single_chunk(self) -> None:
        svc = AudiobookService.__new__(AudiobookService)  # bypass __init__
        result = svc._split_text("hello", 100)
        assert result == ["hello"]

    def test_empty_text_returns_single_empty(self) -> None:
        svc = AudiobookService.__new__(AudiobookService)
        result = svc._split_text("", 100)
        assert result == [""]

    def test_paragraph_split_packs_to_limit(self) -> None:
        svc = AudiobookService.__new__(AudiobookService)
        text = "first paragraph.\n\nsecond paragraph.\n\nthird paragraph."
        chunks = svc._split_text(text, 50)
        # Each chunk fits in the limit and the rejoined text has all 3 paragraphs.
        for chunk in chunks:
            assert len(chunk) <= 50
        joined = " ".join(chunks)
        assert "first" in joined and "second" in joined and "third" in joined

    def test_oversize_paragraph_sentence_split(self) -> None:
        svc = AudiobookService.__new__(AudiobookService)
        # One paragraph, 4 sentences, limit forces sentence split.
        text = "Sentence one. Sentence two. Sentence three. Sentence four."
        chunks = svc._split_text(text, 25)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 25 or chunk.count(".") <= 1
