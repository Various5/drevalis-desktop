"""Tests for ``AudiobookService._run_tts_phase`` (F-CQ-01 step 5).

The biggest single phase extracted out of ``generate``. Pin the
contract that:

* multi-voice routing fires when ``voice_casting`` has entries AND
  the chapter has multiple speaker blocks
* SFX-bearing chapters always go through multi-voice (sequential
  order matters)
* single-speaker chapters take the simpler single-voice path
* cancellation is checked between chapters
* progress events fire in the 5%-50% band
* DAG transitions to ``in_progress`` then ``done`` for every chapter
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    AudioChunk,
)


def _service(*, audiobook_id: UUID | None = None) -> AudiobookService:
    svc = AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )
    # Replace the methods that would otherwise touch real services.
    svc._check_cancelled = AsyncMock()  # type: ignore[method-assign]
    svc._broadcast_progress = AsyncMock()  # type: ignore[method-assign]
    svc._dag_chapter = AsyncMock()  # type: ignore[method-assign]
    svc._dag_chapter_done = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._parse_voice_blocks = MagicMock()  # type: ignore[method-assign]
    svc._generate_single_voice = AsyncMock(return_value=[])  # type: ignore[method-assign]
    svc._generate_multi_voice = AsyncMock(return_value=[])  # type: ignore[method-assign]
    return svc


def _voice_profile() -> Any:
    vp = MagicMock()
    vp.id = "vp-test"
    vp.provider = "edge"
    return vp


def _chunk(idx: int) -> AudioChunk:
    return AudioChunk(
        path=Path(f"/tmp/chunk_{idx}.wav"),
        chapter_index=idx,
        speaker="Narrator",
        block_index=0,
        chunk_index=idx,
    )


# ── Single-voice routing ────────────────────────────────────────────


class TestSingleVoiceRouting:
    async def test_no_casting_no_sfx_takes_single_voice_path(self) -> None:
        svc = _service()
        svc._parse_voice_blocks = MagicMock(return_value=[])  # type: ignore[method-assign]

        chapters = [{"index": 0, "text": "Once upon a time."}]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting=None,
            speed=1.0,
            pitch=1.0,
        )
        svc._generate_single_voice.assert_awaited_once()
        svc._generate_multi_voice.assert_not_awaited()

    async def test_single_speaker_block_unwrapped_to_text(self) -> None:
        # When the chapter has a single voice block with a [Speaker] tag,
        # we route to single-voice using the BLOCK's text rather than
        # the raw chapter text (the speaker tag itself shouldn't be read).
        svc = _service()
        svc._parse_voice_blocks = MagicMock(  # type: ignore[method-assign]
            return_value=[{"speaker": "Alice", "text": "Hello.", "kind": "voice"}]
        )

        chapters = [{"index": 0, "text": "[Alice] Hello."}]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting=None,
            speed=1.0,
            pitch=1.0,
        )
        kwargs = svc._generate_single_voice.call_args.kwargs
        assert kwargs["text"] == "Hello."


# ── Multi-voice routing ─────────────────────────────────────────────


class TestMultiVoiceRouting:
    async def test_multiple_blocks_with_casting_takes_multi_voice(self) -> None:
        svc = _service()
        svc._parse_voice_blocks = MagicMock(  # type: ignore[method-assign]
            return_value=[
                {"speaker": "Alice", "text": "Hi.", "kind": "voice"},
                {"speaker": "Bob", "text": "Hey.", "kind": "voice"},
            ]
        )

        chapters = [{"index": 0, "text": "[Alice] Hi.\n[Bob] Hey."}]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting={"Alice": "vp-a", "Bob": "vp-b"},
            speed=1.0,
            pitch=1.0,
        )
        svc._generate_multi_voice.assert_awaited_once()
        svc._generate_single_voice.assert_not_awaited()

    async def test_sfx_block_forces_multi_voice_even_without_casting(self) -> None:
        # The contract: SFX blocks must preserve sequential order with
        # voice blocks, so the multi-voice path runs even when no
        # voice_casting was provided. _generate_multi_voice falls back
        # to default_voice_profile internally.
        svc = _service()
        svc._parse_voice_blocks = MagicMock(  # type: ignore[method-assign]
            return_value=[
                {"speaker": "Narrator", "text": "She paused.", "kind": "voice"},
                {"description": "thunder", "duration": 4.0, "kind": "sfx"},
            ]
        )

        chapters = [{"index": 0, "text": "She paused.\n[SFX: thunder]"}]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting=None,
            speed=1.0,
            pitch=1.0,
        )
        svc._generate_multi_voice.assert_awaited_once()
        svc._generate_single_voice.assert_not_awaited()

    async def test_casting_alone_without_multiple_blocks_stays_single_voice(
        self,
    ) -> None:
        # voice_casting is set but only one block — single-voice still wins
        # (multi-voice path requires len(blocks) > 1).
        svc = _service()
        svc._parse_voice_blocks = MagicMock(  # type: ignore[method-assign]
            return_value=[{"speaker": "Alice", "text": "Hello.", "kind": "voice"}]
        )

        chapters = [{"index": 0, "text": "[Alice] Hello."}]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting={"Alice": "vp-a"},
            speed=1.0,
            pitch=1.0,
        )
        svc._generate_single_voice.assert_awaited_once()
        svc._generate_multi_voice.assert_not_awaited()


# ── Cancellation + progress + DAG transitions ───────────────────────


class TestSideEffects:
    async def test_cancellation_checked_per_chapter(self) -> None:
        svc = _service()
        svc._parse_voice_blocks = MagicMock(return_value=[])  # type: ignore[method-assign]

        chapters = [
            {"index": 0, "text": "First."},
            {"index": 1, "text": "Second."},
            {"index": 2, "text": "Third."},
        ]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting=None,
            speed=1.0,
            pitch=1.0,
        )
        # One cancellation check at the top of each chapter loop.
        assert svc._check_cancelled.await_count == 3

    async def test_progress_in_5_to_50_band(self) -> None:
        svc = _service()
        svc._parse_voice_blocks = MagicMock(return_value=[])  # type: ignore[method-assign]

        chapters = [{"index": i, "text": f"C{i}"} for i in range(4)]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting=None,
            speed=1.0,
            pitch=1.0,
        )
        # Each broadcast_progress call passes (audiobook_id, "tts", pct, msg).
        pcts = [c.args[2] for c in svc._broadcast_progress.call_args_list]
        # First chapter starts at 5%, last at < 50%.
        assert min(pcts) >= 5
        assert max(pcts) < 50
        # Strictly monotonic.
        assert pcts == sorted(pcts)

    async def test_dag_chapter_transitions_in_progress_then_done(self) -> None:
        svc = _service()
        svc._parse_voice_blocks = MagicMock(return_value=[])  # type: ignore[method-assign]

        chapters = [{"index": 0, "text": "First."}]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting=None,
            speed=1.0,
            pitch=1.0,
        )
        # Chapter 0 transitions: in_progress → done.
        statuses = [c.args[2] for c in svc._dag_chapter.call_args_list]
        assert statuses == ["in_progress", "done"]


class TestChunksAccumulation:
    async def test_returns_concatenated_chunks_in_chapter_order(self) -> None:
        svc = _service()
        svc._parse_voice_blocks = MagicMock(return_value=[])  # type: ignore[method-assign]
        # Chapter 0 returns [chunk_0], chapter 1 returns [chunk_1, chunk_2].
        svc._generate_single_voice = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                [_chunk(0)],
                [_chunk(1), _chunk(2)],
            ]
        )
        chapters = [
            {"index": 0, "text": "First."},
            {"index": 1, "text": "Second."},
        ]
        out = await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting=None,
            speed=1.0,
            pitch=1.0,
        )
        # Aggregated in iteration order — chunks from chapter 0 first.
        assert len(out) == 3
        assert out[0].chunk_index == 0
        assert out[1].chunk_index == 1
        assert out[2].chunk_index == 2

    async def test_empty_chapters_returns_empty_list(self) -> None:
        svc = _service()
        out = await svc._run_tts_phase(
            chapters=[],
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting=None,
            speed=1.0,
            pitch=1.0,
        )
        assert out == []
        # No cancellation check, no progress, no DAG events.
        svc._check_cancelled.assert_not_awaited()
        svc._broadcast_progress.assert_not_awaited()


class TestSpeedPitchPropagation:
    async def test_speed_and_pitch_threaded_to_single_voice(self) -> None:
        svc = _service()
        svc._parse_voice_blocks = MagicMock(return_value=[])  # type: ignore[method-assign]

        chapters = [{"index": 0, "text": "X."}]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting=None,
            speed=1.25,
            pitch=0.9,
        )
        kwargs = svc._generate_single_voice.call_args.kwargs
        assert kwargs["speed"] == 1.25
        assert kwargs["pitch"] == 0.9

    async def test_speed_and_pitch_threaded_to_multi_voice(self) -> None:
        svc = _service()
        svc._parse_voice_blocks = MagicMock(  # type: ignore[method-assign]
            return_value=[
                {"speaker": "A", "text": "Hi.", "kind": "voice"},
                {"speaker": "B", "text": "Hey.", "kind": "voice"},
            ]
        )

        chapters = [{"index": 0, "text": "[A] Hi.\n[B] Hey."}]
        await svc._run_tts_phase(
            chapters=chapters,
            abs_dir=Path("/tmp"),
            audiobook_id=uuid4(),
            voice_profile=_voice_profile(),
            voice_casting={"A": "vp-a", "B": "vp-b"},
            speed=1.5,
            pitch=1.1,
        )
        kwargs = svc._generate_multi_voice.call_args.kwargs
        assert kwargs["speed"] == 1.5
        assert kwargs["pitch"] == 1.1
