"""Tests for ``AudiobookService._finalize_generate_result`` (F-CQ-01 step 13).

The final phase of ``generate``. Pin the contract that:

* 100% progress broadcasts before return so the UI's progress bar
  hits the end (otherwise it would freeze at 90% from the assembly
  stage).
* Result dict has the exact key set the route + worker expect.
* ``_chunk_paths`` is the deferred-cleanup handoff (underscore-
  prefixed because it's internal — never serialised to the API).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    AudioChunk,
)


def _service() -> AudiobookService:
    svc = AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )
    svc._broadcast_progress = AsyncMock()  # type: ignore[method-assign]
    return svc


def _chunk(idx: int) -> AudioChunk:
    return AudioChunk(
        path=Path(f"/tmp/x/chunks/chunk_{idx:04d}.wav"),
        chapter_index=0,
        speaker="Narrator",
        block_index=0,
        chunk_index=idx,
    )


# ── Progress broadcast ──────────────────────────────────────────────


class TestProgress:
    async def test_broadcasts_100_percent_done(self) -> None:
        svc = _service()
        await svc._finalize_generate_result(
            audiobook_id=uuid4(),
            audio_rel_path="x.wav",
            video_rel_path=None,
            mp3_rel_path=None,
            captions_ass_rel=None,
            captions_srt_rel=None,
            duration=10.0,
            file_size=1000,
            chapters=[],
            all_chunks=[],
        )
        bc = svc._broadcast_progress.call_args
        # (audiobook_id, stage, pct, message)
        assert bc.args[1] == "done"
        assert bc.args[2] == 100


# ── Result dict shape ───────────────────────────────────────────────


class TestResultDictShape:
    async def test_full_result_dict(self) -> None:
        svc = _service()
        ab_id = uuid4()
        chapters = [{"title": "C0"}]
        out = await svc._finalize_generate_result(
            audiobook_id=ab_id,
            audio_rel_path=f"audiobooks/{ab_id}/audiobook.wav",
            video_rel_path=f"audiobooks/{ab_id}/audiobook.mp4",
            mp3_rel_path=f"audiobooks/{ab_id}/audiobook.mp3",
            captions_ass_rel=f"audiobooks/{ab_id}/captions/captions.ass",
            captions_srt_rel=f"audiobooks/{ab_id}/captions/captions.srt",
            duration=120.5,
            file_size=20_000_000,
            chapters=chapters,
            all_chunks=[_chunk(0), _chunk(1)],
        )
        # Pin the exact key set the route + worker expect.
        assert set(out.keys()) == {
            "audio_rel_path",
            "video_rel_path",
            "mp3_rel_path",
            "captions_ass_rel_path",
            "captions_srt_rel_path",
            "duration_seconds",
            "file_size_bytes",
            "chapters",
            "_chunk_paths",
        }
        assert out["audio_rel_path"] == f"audiobooks/{ab_id}/audiobook.wav"
        assert out["video_rel_path"] == f"audiobooks/{ab_id}/audiobook.mp4"
        assert out["mp3_rel_path"] == f"audiobooks/{ab_id}/audiobook.mp3"
        assert out["duration_seconds"] == 120.5
        assert out["file_size_bytes"] == 20_000_000
        # Chapters passed through by reference.
        assert out["chapters"] is chapters

    async def test_audio_only_result_has_none_for_video_and_mp3(self) -> None:
        # When the caller never produced video/mp3 (audio_only or
        # phase failures), the result dict carries None for those
        # fields rather than missing keys.
        svc = _service()
        out = await svc._finalize_generate_result(
            audiobook_id=uuid4(),
            audio_rel_path="x.wav",
            video_rel_path=None,
            mp3_rel_path=None,
            captions_ass_rel=None,
            captions_srt_rel=None,
            duration=10.0,
            file_size=1000,
            chapters=[],
            all_chunks=[],
        )
        assert out["video_rel_path"] is None
        assert out["mp3_rel_path"] is None
        assert out["captions_ass_rel_path"] is None
        assert out["captions_srt_rel_path"] is None


# ── Deferred chunk cleanup handoff ──────────────────────────────────


class TestChunkPathsHandoff:
    async def test_chunk_paths_returned_for_deferred_cleanup(self) -> None:
        # Chunks are intentionally NOT deleted by ``generate`` — the
        # worker must clean them up AFTER a successful DB commit.
        # The result dict's ``_chunk_paths`` is the handoff.
        svc = _service()
        chunks = [_chunk(0), _chunk(1), _chunk(2)]
        out = await svc._finalize_generate_result(
            audiobook_id=uuid4(),
            audio_rel_path="x.wav",
            video_rel_path=None,
            mp3_rel_path=None,
            captions_ass_rel=None,
            captions_srt_rel=None,
            duration=10.0,
            file_size=1000,
            chapters=[],
            all_chunks=chunks,
        )
        assert out["_chunk_paths"] == [c.path for c in chunks]
        # Underscore prefix flags it as internal — the API serialiser
        # in the route layer should drop _-prefixed keys.
        assert all(k.startswith("_") for k in out if k.startswith("_"))

    async def test_empty_chunks_yields_empty_list(self) -> None:
        svc = _service()
        out = await svc._finalize_generate_result(
            audiobook_id=uuid4(),
            audio_rel_path="x.wav",
            video_rel_path=None,
            mp3_rel_path=None,
            captions_ass_rel=None,
            captions_srt_rel=None,
            duration=10.0,
            file_size=1000,
            chapters=[],
            all_chunks=[],
        )
        assert out["_chunk_paths"] == []
