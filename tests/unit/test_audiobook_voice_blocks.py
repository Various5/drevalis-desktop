"""Tests for [Speaker] / [SFX] block parsing and multi-voice dispatch.

Covers the generation-path code that was previously only exercised
end-to-end:

  * ``_parse_voice_blocks`` — the script grammar that splits raw audiobook
    text into voice + SFX blocks. Misparses here cascade into wrong
    speakers, lost SFX, or all narration silently routed to the default
    voice.
  * ``_is_overlay_sfx`` — distinguishes sequential SFX (a chunk inserted
    between voice blocks) from overlay SFX (sidechain ducked under voice).
  * ``_generate_multi_voice`` — speaker-to-voice-profile dispatch with the
    casting map, including normalised name matching, fallback to default
    when a speaker is uncast or the profile lookup fails, and SFX block
    routing through the dedicated provider.

All tests use lightweight stubs and AsyncMocks — no ffmpeg, no DB, no real
TTS. Provider concurrency is exercised in ``test_audiobook_concurrency``;
this module focuses on routing correctness.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    _PROVIDER_SEMAPHORES,
    AudiobookService,
    AudioChunk,
)

# ── Shared stubs ────────────────────────────────────────────────────────


class _StubStorage:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def resolve_path(self, rel: str) -> Path:
        return self.base_path / rel


class _StubVoiceProfile:
    def __init__(self, vp_id: str = "11111111-1111-1111-1111-111111111111") -> None:
        self.id = vp_id
        self.provider = "edge"
        self.model_name = "en_US-amy"


class _RecordingProvider:
    """TTS provider that records each invocation's text/voice_id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Path]] = []

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        path: Path,
        *,
        speed: float,
        pitch: float,
    ) -> None:
        del speed, pitch
        self.calls.append((text, voice_id, path))
        path.write_bytes(b"RIFF" + b"\x00" * 1024)


class _StubTTSService:
    """Routes get_provider/get_voice_id by voice-profile id."""

    def __init__(self, profile_to_provider: dict[str, _RecordingProvider]) -> None:
        self._map = profile_to_provider
        self._voice_ids = {pid: f"voice-{pid[:8]}" for pid in profile_to_provider}

    def get_provider(self, voice_profile: _StubVoiceProfile) -> _RecordingProvider:
        return self._map[voice_profile.id]

    def _voice_id_for(self, voice_profile: _StubVoiceProfile) -> str:
        return self._voice_ids[voice_profile.id]


def _make_service(tmp_path: Path, tts_service: _StubTTSService) -> AudiobookService:
    service = AudiobookService(
        tts_service=tts_service,
        ffmpeg_service=AsyncMock(),
        storage=_StubStorage(tmp_path),
    )
    service._current_audiobook_id = None  # disables the cancel poll
    return service


# ══════════════════════════════════════════════════════════════════════
# _parse_voice_blocks
# ══════════════════════════════════════════════════════════════════════


def _parser() -> AudiobookService:
    # _parse_voice_blocks doesn't touch any deps, so a bare service works.
    return AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )


class TestParseVoiceBlocksSpeakers:
    def test_untagged_text_defaults_to_narrator(self) -> None:
        blocks = _parser()._parse_voice_blocks("Once upon a time.")
        assert blocks == [{"kind": "voice", "speaker": "Narrator", "text": "Once upon a time."}]

    def test_speaker_tag_switches_voice(self) -> None:
        text = "[Alice] Hello.\n[Bob] World."
        blocks = _parser()._parse_voice_blocks(text)
        assert [b["speaker"] for b in blocks] == ["Alice", "Bob"]
        assert [b["text"] for b in blocks] == ["Hello.", "World."]

    def test_speaker_tag_alone_then_following_text(self) -> None:
        text = "[Alice]\nHello there."
        blocks = _parser()._parse_voice_blocks(text)
        assert blocks == [{"kind": "voice", "speaker": "Alice", "text": "Hello there."}]

    def test_multi_paragraph_block_joined(self) -> None:
        text = "[Alice] Para one.\n\nPara two."
        blocks = _parser()._parse_voice_blocks(text)
        assert len(blocks) == 1
        assert "Para one." in blocks[0]["text"]
        assert "Para two." in blocks[0]["text"]

    def test_markdown_heading_lines_skipped(self) -> None:
        text = "## Chapter 1\n[Alice] Hello."
        blocks = _parser()._parse_voice_blocks(text)
        assert blocks == [{"kind": "voice", "speaker": "Alice", "text": "Hello."}]

    def test_empty_voice_blocks_dropped(self) -> None:
        text = "[Alice]\n[Bob] Real text."
        blocks = _parser()._parse_voice_blocks(text)
        assert [b["speaker"] for b in blocks] == ["Bob"]

    def test_speaker_name_stripped(self) -> None:
        blocks = _parser()._parse_voice_blocks("[  Alice  ] Hello.")
        assert blocks[0]["speaker"] == "Alice"

    def test_blank_input_yields_no_blocks(self) -> None:
        assert _parser()._parse_voice_blocks("") == []
        assert _parser()._parse_voice_blocks("\n\n\n") == []


class TestParseVoiceBlocksSfx:
    def test_minimal_sfx_uses_defaults(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: thunder]")
        assert len(blocks) == 1
        sfx = blocks[0]
        assert sfx["kind"] == "sfx"
        assert sfx["description"] == "thunder"
        assert sfx["duration"] == 4.0
        assert sfx["loop"] is False
        assert sfx["prompt_influence"] is None
        assert sfx["under_voice_blocks"] is None
        assert sfx["under_seconds"] is None
        assert sfx["duck_db"] == -12.0

    def test_sfx_dur_modifier(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: rain | dur=8]")
        assert blocks[0]["duration"] == 8.0

    def test_sfx_duration_alias(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: rain | duration=12]")
        assert blocks[0]["duration"] == 12.0

    def test_sfx_loop_flag(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: ambient | loop]")
        assert blocks[0]["loop"] is True

    def test_sfx_influence_modifier(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: rain | influence=0.4]")
        assert blocks[0]["prompt_influence"] == 0.4

    def test_sfx_prompt_influence_alias(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: rain | prompt_influence=0.7]")
        assert blocks[0]["prompt_influence"] == 0.7

    def test_sfx_under_next(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: hum | under=next]")
        assert blocks[0]["under_voice_blocks"] == 1
        assert blocks[0]["under_seconds"] is None

    def test_sfx_under_all(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: hum | under=all]")
        assert blocks[0]["under_voice_blocks"] == 999

    def test_sfx_under_block_count(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: hum | under=3]")
        assert blocks[0]["under_voice_blocks"] == 3
        assert blocks[0]["under_seconds"] is None

    def test_sfx_under_seconds_treated_as_seconds_when_large(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: hum | under=12]")
        # >5 → seconds, not block count
        assert blocks[0]["under_voice_blocks"] is None
        assert blocks[0]["under_seconds"] == 12.0

    def test_sfx_under_fractional_treated_as_seconds(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: hum | under=2.5]")
        assert blocks[0]["under_voice_blocks"] is None
        assert blocks[0]["under_seconds"] == 2.5

    def test_sfx_duck_modifier(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: hum | under=next | duck=-18]")
        assert blocks[0]["duck_db"] == -18.0

    def test_sfx_duck_db_alias(self) -> None:
        blocks = _parser()._parse_voice_blocks("[SFX: hum | under=next | duck_db=-9.5]")
        assert blocks[0]["duck_db"] == -9.5

    def test_sfx_invalid_value_silently_ignored(self) -> None:
        # ``dur=abc`` is unparsable — kept as default 4.0 rather than crashing.
        blocks = _parser()._parse_voice_blocks("[SFX: rain | dur=abc]")
        assert blocks[0]["duration"] == 4.0

    def test_sfx_case_insensitive_tag(self) -> None:
        blocks = _parser()._parse_voice_blocks("[sfx: rain]")
        assert blocks[0]["kind"] == "sfx"
        blocks = _parser()._parse_voice_blocks("[SFX: rain]")
        assert blocks[0]["kind"] == "sfx"

    def test_sfx_does_not_match_speaker_tag(self) -> None:
        # An ``[SFX]`` without ``:`` is not an SFX block — it falls
        # through to the speaker-tag regex and becomes a speaker.
        blocks = _parser()._parse_voice_blocks("[SFX] Hi.")
        assert blocks[0]["kind"] == "voice"
        assert blocks[0]["speaker"] == "SFX"

    def test_sfx_then_voice_block_ordering(self) -> None:
        text = "[SFX: door slam]\n[Alice] Who's there?"
        blocks = _parser()._parse_voice_blocks(text)
        assert [b["kind"] for b in blocks] == ["sfx", "voice"]
        assert blocks[1]["speaker"] == "Alice"


class TestIsOverlaySfx:
    def _service(self) -> AudiobookService:
        return _parser()

    def test_voice_chunk_is_not_overlay(self, tmp_path: Path) -> None:
        chunk = AudioChunk(
            path=tmp_path / "x.wav",
            chapter_index=0,
            speaker="Alice",
            block_index=0,
            chunk_index=0,
        )
        assert self._service()._is_overlay_sfx(chunk) is False

    def test_sequential_sfx_is_not_overlay(self, tmp_path: Path) -> None:
        chunk = AudioChunk(
            path=tmp_path / "x.wav",
            chapter_index=0,
            speaker="__SFX__",
            block_index=0,
            chunk_index=0,
            overlay_voice_blocks=None,
            overlay_seconds=None,
        )
        assert self._service()._is_overlay_sfx(chunk) is False

    def test_overlay_sfx_with_block_count(self, tmp_path: Path) -> None:
        chunk = AudioChunk(
            path=tmp_path / "x.wav",
            chapter_index=0,
            speaker="__SFX__",
            block_index=0,
            chunk_index=0,
            overlay_voice_blocks=2,
        )
        assert self._service()._is_overlay_sfx(chunk) is True

    def test_overlay_sfx_with_seconds(self, tmp_path: Path) -> None:
        chunk = AudioChunk(
            path=tmp_path / "x.wav",
            chapter_index=0,
            speaker="__SFX__",
            block_index=0,
            chunk_index=0,
            overlay_seconds=4.0,
        )
        assert self._service()._is_overlay_sfx(chunk) is True

    def test_voice_chunk_with_overlay_metadata_is_not_overlay(self, tmp_path: Path) -> None:
        # Defensive: speaker must be the SFX sentinel for overlay routing.
        chunk = AudioChunk(
            path=tmp_path / "x.wav",
            chapter_index=0,
            speaker="Alice",
            block_index=0,
            chunk_index=0,
            overlay_seconds=4.0,
        )
        assert self._service()._is_overlay_sfx(chunk) is False


# ══════════════════════════════════════════════════════════════════════
# _generate_multi_voice — speaker → voice-profile dispatch
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def reset_provider_semaphores() -> None:
    _PROVIDER_SEMAPHORES.clear()


@pytest.fixture(autouse=True)
def _stub_safety_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass ffmpeg-based safety filtering for every test in this module."""

    async def _noop(self: AudiobookService, chunk_path: Path) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(AudiobookService, "_safety_filter_chunk", _noop)


class TestGenerateMultiVoiceCasting:
    def setup_method(self) -> None:
        _PROVIDER_SEMAPHORES.clear()

    async def test_each_speaker_routed_to_assigned_voice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        alice = _StubVoiceProfile("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        bob = _StubVoiceProfile("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        narrator = _StubVoiceProfile("11111111-1111-1111-1111-111111111111")

        alice_provider = _RecordingProvider()
        bob_provider = _RecordingProvider()
        narrator_provider = _RecordingProvider()
        alice_provider.__class__.__name__ = "EdgeTTSProvider"
        bob_provider.__class__.__name__ = "EdgeTTSProvider"
        narrator_provider.__class__.__name__ = "EdgeTTSProvider"

        tts = _StubTTSService(
            {
                alice.id: alice_provider,
                bob.id: bob_provider,
                narrator.id: narrator_provider,
            }
        )
        service = _make_service(tmp_path, tts)

        async def _fake_get_voice_profile(
            self: AudiobookService, vp_id: str
        ) -> _StubVoiceProfile | None:  # noqa: ARG001
            return {alice.id: alice, bob.id: bob}.get(vp_id)

        monkeypatch.setattr(AudiobookService, "_get_voice_profile", _fake_get_voice_profile)

        blocks = [
            {"kind": "voice", "speaker": "Alice", "text": "Hello."},
            {"kind": "voice", "speaker": "Bob", "text": "World."},
        ]
        casting = {"Alice": alice.id, "Bob": bob.id}

        chunks = await service._generate_multi_voice(
            blocks=blocks,
            voice_casting=casting,
            default_voice_profile=narrator,
            output_dir=tmp_path,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        assert len(alice_provider.calls) == 1
        assert alice_provider.calls[0][0] == "Hello."
        assert len(bob_provider.calls) == 1
        assert bob_provider.calls[0][0] == "World."
        assert narrator_provider.calls == []
        assert {c.speaker for c in chunks} == {"Alice", "Bob"}

    async def test_uncast_speaker_falls_back_to_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        narrator = _StubVoiceProfile("11111111-1111-1111-1111-111111111111")
        narrator_provider = _RecordingProvider()
        narrator_provider.__class__.__name__ = "EdgeTTSProvider"
        tts = _StubTTSService({narrator.id: narrator_provider})
        service = _make_service(tmp_path, tts)

        async def _no_profile(self: AudiobookService, vp_id: str) -> None:  # noqa: ARG001
            return None

        monkeypatch.setattr(AudiobookService, "_get_voice_profile", _no_profile)

        blocks = [{"kind": "voice", "speaker": "Stranger", "text": "Boo."}]
        chunks = await service._generate_multi_voice(
            blocks=blocks,
            voice_casting={},
            default_voice_profile=narrator,
            output_dir=tmp_path,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        assert len(narrator_provider.calls) == 1
        assert narrator_provider.calls[0][0] == "Boo."
        assert chunks[0].speaker == "Stranger"

    async def test_missing_voice_profile_falls_back_to_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Casting names a profile id that the DB lookup can't resolve;
        # the multi-voice path must fall back to the default profile
        # rather than crashing.
        narrator = _StubVoiceProfile("11111111-1111-1111-1111-111111111111")
        narrator_provider = _RecordingProvider()
        narrator_provider.__class__.__name__ = "EdgeTTSProvider"
        tts = _StubTTSService({narrator.id: narrator_provider})
        service = _make_service(tmp_path, tts)

        async def _missing_profile(self: AudiobookService, vp_id: str) -> None:  # noqa: ARG001
            return None

        monkeypatch.setattr(AudiobookService, "_get_voice_profile", _missing_profile)

        blocks = [{"kind": "voice", "speaker": "Alice", "text": "Hi."}]
        casting = {"Alice": "deadbeef-dead-beef-dead-beefdeadbeef"}

        chunks = await service._generate_multi_voice(
            blocks=blocks,
            voice_casting=casting,
            default_voice_profile=narrator,
            output_dir=tmp_path,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        assert len(narrator_provider.calls) == 1
        assert chunks[0].speaker == "Alice"

    async def test_speaker_name_normalised_against_casting_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Block speaker is ``NARRATOR.`` (uppercase + trailing period);
        # casting key is ``Narrator``. The normaliser strips
        # case + non-alphanumerics so they should match.
        narrator = _StubVoiceProfile("11111111-1111-1111-1111-111111111111")
        custom = _StubVoiceProfile("22222222-2222-2222-2222-222222222222")
        narrator_provider = _RecordingProvider()
        custom_provider = _RecordingProvider()
        narrator_provider.__class__.__name__ = "EdgeTTSProvider"
        custom_provider.__class__.__name__ = "EdgeTTSProvider"
        tts = _StubTTSService({narrator.id: narrator_provider, custom.id: custom_provider})
        service = _make_service(tmp_path, tts)

        async def _fake_lookup(self: AudiobookService, vp_id: str) -> _StubVoiceProfile | None:  # noqa: ARG001
            return {custom.id: custom}.get(vp_id)

        monkeypatch.setattr(AudiobookService, "_get_voice_profile", _fake_lookup)

        blocks = [{"kind": "voice", "speaker": "NARRATOR.", "text": "Hi."}]
        casting = {"Narrator": custom.id}

        await service._generate_multi_voice(
            blocks=blocks,
            voice_casting=casting,
            default_voice_profile=narrator,
            output_dir=tmp_path,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        # Custom got the call, default did not.
        assert len(custom_provider.calls) == 1
        assert narrator_provider.calls == []

    async def test_normalised_match_does_not_substring_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pre-fix, ``Nate`` would substring-match ``Narrator``. Post-fix,
        # the normaliser is exact (after stripping non-alphanumerics).
        narrator = _StubVoiceProfile("11111111-1111-1111-1111-111111111111")
        custom = _StubVoiceProfile("22222222-2222-2222-2222-222222222222")
        narrator_provider = _RecordingProvider()
        custom_provider = _RecordingProvider()
        narrator_provider.__class__.__name__ = "EdgeTTSProvider"
        custom_provider.__class__.__name__ = "EdgeTTSProvider"
        tts = _StubTTSService({narrator.id: narrator_provider, custom.id: custom_provider})
        service = _make_service(tmp_path, tts)

        async def _fake_lookup(self: AudiobookService, vp_id: str) -> _StubVoiceProfile | None:  # noqa: ARG001
            return {custom.id: custom}.get(vp_id)

        monkeypatch.setattr(AudiobookService, "_get_voice_profile", _fake_lookup)

        blocks = [{"kind": "voice", "speaker": "Nate", "text": "Hi."}]
        casting = {"Narrator": custom.id}

        await service._generate_multi_voice(
            blocks=blocks,
            voice_casting=casting,
            default_voice_profile=narrator,
            output_dir=tmp_path,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        # Nate didn't accidentally inherit Narrator's voice.
        assert custom_provider.calls == []
        assert len(narrator_provider.calls) == 1


class TestGenerateMultiVoiceSfx:
    def setup_method(self) -> None:
        _PROVIDER_SEMAPHORES.clear()

    async def test_sfx_block_routed_to_sfx_chunk_helper(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        narrator = _StubVoiceProfile("11111111-1111-1111-1111-111111111111")
        narrator_provider = _RecordingProvider()
        narrator_provider.__class__.__name__ = "EdgeTTSProvider"
        tts = _StubTTSService({narrator.id: narrator_provider})
        service = _make_service(tmp_path, tts)

        sfx_chunk = AudioChunk(
            path=tmp_path / "sfx.wav",
            chapter_index=0,
            speaker="__SFX__",
            block_index=0,
            chunk_index=0,
        )

        sfx_calls: list[dict[str, object]] = []

        async def _fake_sfx(
            self: AudiobookService,
            *,
            block: dict[str, object],
            output_dir: Path,
            chapter_index: int,
            block_index: int,
        ) -> AudioChunk:  # noqa: ARG001
            sfx_calls.append(block)
            return sfx_chunk

        monkeypatch.setattr(AudiobookService, "_generate_sfx_chunk", _fake_sfx)

        blocks: list[dict[str, object]] = [
            {"kind": "sfx", "description": "thunder", "duration": 4.0},
            {"kind": "voice", "speaker": "Narrator", "text": "After thunder."},
        ]

        chunks = await service._generate_multi_voice(
            blocks=blocks,
            voice_casting={},
            default_voice_profile=narrator,
            output_dir=tmp_path,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        assert len(sfx_calls) == 1
        assert sfx_calls[0]["description"] == "thunder"
        assert sfx_chunk in chunks
        assert any(c.speaker == "Narrator" for c in chunks)
        assert len(narrator_provider.calls) == 1

    async def test_sfx_chunk_returning_none_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Graceful degradation when no ComfyUI server is available:
        # _generate_sfx_chunk returns None and the multi-voice loop
        # must continue without that chunk rather than raising.
        narrator = _StubVoiceProfile("11111111-1111-1111-1111-111111111111")
        narrator_provider = _RecordingProvider()
        narrator_provider.__class__.__name__ = "EdgeTTSProvider"
        tts = _StubTTSService({narrator.id: narrator_provider})
        service = _make_service(tmp_path, tts)

        async def _no_sfx(
            self: AudiobookService,
            *,
            block: dict[str, object],
            output_dir: Path,
            chapter_index: int,
            block_index: int,
        ) -> None:  # noqa: ARG001
            return None

        monkeypatch.setattr(AudiobookService, "_generate_sfx_chunk", _no_sfx)

        blocks: list[dict[str, object]] = [
            {"kind": "sfx", "description": "thunder", "duration": 4.0},
            {"kind": "voice", "speaker": "Narrator", "text": "Continued."},
        ]

        chunks = await service._generate_multi_voice(
            blocks=blocks,
            voice_casting={},
            default_voice_profile=narrator,
            output_dir=tmp_path,
            chapter_index=0,
            speed=1.0,
            pitch=1.0,
        )

        # SFX dropped, narrator still rendered.
        assert all(c.speaker != "__SFX__" for c in chunks)
        assert len(narrator_provider.calls) == 1
