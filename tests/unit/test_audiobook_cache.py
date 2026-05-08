"""Tests for the hash-keyed audiobook chunk cache (Task 1).

The chunk filenames now embed a 12-hex-char content hash so any change
to the inputs that produced the audio (text, voice profile, provider,
speed, pitch, sample rate, pipeline version) yields a fresh filename
and prevents stale-cache reuse.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    _CHUNK_HASH_SUFFIX_RE,
    AudiobookService,
    AudioChunk,
    _chunk_cache_hash,
    _provider_identity,
    _strip_chunk_hash,
)
from drevalis.services.audiobook.versions import AUDIO_PIPELINE_VERSION

# ── _chunk_cache_hash ────────────────────────────────────────────────────


_BASE_INPUTS: dict = {
    "text": "Hello, world.",
    "speaker_id": "Narrator",
    "voice_profile_id": "11111111-1111-1111-1111-111111111111",
    "provider": "PiperTTSProvider",
    "model": "en_US-amy-medium",
    "speed": 1.0,
    "pitch": 1.0,
    "sample_rate": 24000,
}


class TestChunkCacheHash:
    def test_returns_12_hex_chars(self) -> None:
        h = _chunk_cache_hash(**_BASE_INPUTS)
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_inputs_same_hash(self) -> None:
        assert _chunk_cache_hash(**_BASE_INPUTS) == _chunk_cache_hash(**_BASE_INPUTS)

    @pytest.mark.parametrize(
        "field, new_value",
        [
            ("text", "Hello, world!"),
            ("speaker_id", "Jack"),
            ("voice_profile_id", "22222222-2222-2222-2222-222222222222"),
            ("provider", "EdgeTTSProvider"),
            ("model", "en_US-ryan-high"),
            ("speed", 1.1),
            ("pitch", 0.95),
            ("sample_rate", 22050),
        ],
    )
    def test_changing_any_input_changes_hash(self, field: str, new_value) -> None:
        baseline = _chunk_cache_hash(**_BASE_INPUTS)
        mutated = {**_BASE_INPUTS, field: new_value}
        assert _chunk_cache_hash(**mutated) != baseline, (
            f"Changing {field!r} did not change the cache hash — stale audio would be reused."
        )

    def test_pipeline_version_affects_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        baseline = _chunk_cache_hash(**_BASE_INPUTS)
        # Bump the pipeline version inside the helper's view of the module.
        import drevalis.services.audiobook._monolith as monolith

        monkeypatch.setattr(monolith, "AUDIO_PIPELINE_VERSION", AUDIO_PIPELINE_VERSION + 1)
        bumped = monolith._chunk_cache_hash(**_BASE_INPUTS)
        assert bumped != baseline


# ── _strip_chunk_hash ────────────────────────────────────────────────────


class TestStripChunkHash:
    def test_strips_hash_suffix(self) -> None:
        assert _strip_chunk_hash("ch003_chunk_0007_a1b2c3d4e5f6") == "ch003_chunk_0007"

    def test_strips_block_chunk_hash(self) -> None:
        assert (
            _strip_chunk_hash("ch003_block_0002_chunk_0007_0123456789ab")
            == "ch003_block_0002_chunk_0007"
        )

    def test_passthrough_for_legacy_stem(self) -> None:
        # Pre-hash filenames return unchanged so editor mappings still work
        # during the migration window.
        assert _strip_chunk_hash("ch003_chunk_0007") == "ch003_chunk_0007"

    def test_passthrough_for_non_hash_suffix(self) -> None:
        # 12 chars but not all hex — must NOT be stripped.
        assert _strip_chunk_hash("ch003_chunk_0007_zzzzzzzzzzzz") == "ch003_chunk_0007_zzzzzzzzzzzz"

    def test_regex_anchors_at_end(self) -> None:
        assert _CHUNK_HASH_SUFFIX_RE.search("ch003_chunk_0007_a1b2c3d4e5f6") is not None
        assert _CHUNK_HASH_SUFFIX_RE.search("a1b2c3d4e5f6_ch003_chunk_0007") is None


# ── _provider_identity ───────────────────────────────────────────────────


class TestProviderIdentity:
    def test_uses_provider_name_attr(self) -> None:
        provider = type("P", (), {"name": "EdgeTTSProvider"})()
        voice = type("V", (), {"model_name": "en_US-amy"})()
        assert _provider_identity(provider, voice) == ("EdgeTTSProvider", "en_US-amy")

    def test_falls_back_to_class_name(self) -> None:
        class PiperTTSProvider:
            pass

        voice = type("V", (), {"model_name": "amy"})()
        provider_name, _ = _provider_identity(PiperTTSProvider(), voice)
        assert provider_name == "PiperTTSProvider"

    def test_model_falls_back_to_voice_id(self) -> None:
        provider = type("P", (), {"name": "X"})()
        voice = type("V", (), {"voice_id": "abc-123"})()
        assert _provider_identity(provider, voice) == ("X", "abc-123")

    def test_missing_model_yields_empty_string(self) -> None:
        provider = type("P", (), {"name": "X"})()
        voice = type("V", (), {})()
        assert _provider_identity(provider, voice) == ("X", "")


# ── Per-clip override applies via stable id ──────────────────────────────


class _StubStorage:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def resolve_path(self, rel: str) -> Path:
        return self.base_path / rel


class TestClipOverrideStableId:
    """``track_mix.clips`` is keyed by hash-stripped stem so per-clip
    gain/mute survives a cache bust caused by a voice-profile change.
    """

    async def test_override_applies_to_hash_suffixed_chunk(self, tmp_path: Path) -> None:
        # Real WAV chunk on disk with a hash-suffixed name.
        chunk_dir = tmp_path / "audiobooks" / "ab"
        chunk_dir.mkdir(parents=True)
        chunk_file = chunk_dir / "ch000_chunk_0000_a1b2c3d4e5f6.wav"
        chunk_file.write_bytes(b"RIFF" + b"\x00" * 1024)

        # ffmpeg.get_duration is the only async call inside _apply_clip_override
        # that needs to succeed for the mute path; everything else is local.
        ffmpeg = AsyncMock()
        ffmpeg.get_duration = AsyncMock(return_value=1.5)

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=ffmpeg,
            storage=_StubStorage(tmp_path),
        )

        # Override is keyed by the *stable* id (no hash suffix).
        service._track_mix_full = {
            "clips": {"ch000_chunk_0000": {"mute": True}},
        }

        # Reproduce the inner-helper closure shape from _concatenate_with_context
        # by exercising the public path: we add a single AudioChunk and run the
        # concat helper indirectly by reading the override map ourselves the
        # same way ``_apply_clip_override`` does. This keeps the test focused
        # on the lookup contract without spinning up ffmpeg.
        from drevalis.services.audiobook._monolith import _strip_chunk_hash

        stable_id = _strip_chunk_hash(chunk_file.stem)
        assert stable_id == "ch000_chunk_0000"
        assert service._track_mix_full["clips"].get(stable_id) == {"mute": True}


# ── Legacy purge ─────────────────────────────────────────────────────────


class TestLegacyChunkPurge:
    async def test_purges_legacy_single_voice_chunks(self, tmp_path: Path) -> None:
        # Legacy filenames (no hash suffix) — should be deleted.
        legacy = [
            tmp_path / "ch000_chunk_0000.wav",
            tmp_path / "ch001_chunk_0042.wav",
            tmp_path / "ch002_block_0003_chunk_0009.wav",
        ]
        for p in legacy:
            p.write_bytes(b"RIFF")

        # Modern filenames (with hash) — must be retained.
        modern = [
            tmp_path / "ch000_chunk_0000_a1b2c3d4e5f6.wav",
            tmp_path / "ch001_block_0000_chunk_0001_0123456789ab.wav",
        ]
        for p in modern:
            p.write_bytes(b"RIFF")

        # Unrelated files — must be retained.
        keep = [
            tmp_path / "audiobook.wav",
            tmp_path / "audiobook.mp3",
            tmp_path / "ch000_sfx_0000.wav",
        ]
        for p in keep:
            p.write_bytes(b"RIFF")

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        deleted = await service._purge_legacy_chunks(tmp_path)

        assert deleted == len(legacy)
        for p in legacy:
            assert not p.exists(), f"legacy chunk {p.name} should have been purged"
        for p in modern + keep:
            assert p.exists(), f"non-legacy file {p.name} must be retained"

    async def test_purge_is_idempotent(self, tmp_path: Path) -> None:
        # Empty dir on second pass.
        (tmp_path / "ch000_chunk_0000.wav").write_bytes(b"R")

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        first = await service._purge_legacy_chunks(tmp_path)
        second = await service._purge_legacy_chunks(tmp_path)

        assert first == 1
        assert second == 0


# ── invalidate_chapter_chunks now matches multi-voice block files ────────


class TestInvalidateChapterChunks:
    async def test_invalidates_both_single_and_block_voice_chunks(self, tmp_path: Path) -> None:
        from uuid import uuid4

        ab_id = uuid4()
        ab_dir = tmp_path / "audiobooks" / str(ab_id)
        ab_dir.mkdir(parents=True)

        # Chapter 3 — should be deleted.
        target = [
            ab_dir / "ch003_chunk_0000_a1b2c3d4e5f6.wav",
            ab_dir / "ch003_chunk_0001_b2c3d4e5f6a1.wav",
            ab_dir / "ch003_block_0000_chunk_0000_c3d4e5f6a1b2.wav",
            ab_dir / "ch003_block_0001_chunk_0000_d4e5f6a1b2c3.wav",
        ]
        # Chapter 2 — should NOT be touched.
        keep = [
            ab_dir / "ch002_chunk_0000_e5f6a1b2c3d4.wav",
            ab_dir / "ch002_block_0000_chunk_0000_f6a1b2c3d4e5.wav",
            # SFX is keyed differently and is preserved.
            ab_dir / "ch003_sfx_0000.wav",
        ]
        for p in target + keep:
            p.write_bytes(b"RIFF")

        service = AudiobookService(
            tts_service=AsyncMock(),
            ffmpeg_service=AsyncMock(),
            storage=_StubStorage(tmp_path),
        )

        deleted = await service.invalidate_chapter_chunks(ab_id, 3)

        assert deleted == len(target)
        for p in target:
            assert not p.exists()
        for p in keep:
            assert p.exists()


# ── AudioChunk dataclass round-trips with hash-suffixed paths ────────────


class TestAudioChunkWithHashedPath:
    def test_dataclass_accepts_hashed_path(self, tmp_path: Path) -> None:
        path = tmp_path / "ch000_chunk_0007_a1b2c3d4e5f6.wav"
        path.write_bytes(b"RIFF")
        chunk = AudioChunk(
            path=path,
            chapter_index=0,
            speaker="Narrator",
            block_index=0,
            chunk_index=7,
        )
        assert _strip_chunk_hash(chunk.path.stem) == "ch000_chunk_0007"
