"""Tests for ``AudiobookService._run_mp3_export_phase`` (F-CQ-01 step 11).

The MP3 export has two nested non-fatal blocks:

* Outer (mp3_export) — WAV→MP3 conversion failure flips DAG to
  failed and returns None (audiobook ships WAV-only).
* Inner (id3_tags) — ID3 / CHAP write failure flips ID3 DAG to
  failed but does NOT abort the export. The MP3 is already on disk
  and playable.

Plus the LAME-priming-offset probe and its application via the
RenderPlan's chapter markers — pin that the CHAP frames stay
locked to audible boundaries within ±5 ms.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.services.audiobook._monolith import AudiobookService


def _service(*, mp3_dur: float = 100.026, wav_dur: float = 100.0) -> AudiobookService:
    svc = AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )
    svc._dag_global = AsyncMock()  # type: ignore[method-assign]
    svc._convert_to_mp3 = AsyncMock()  # type: ignore[method-assign]
    svc.ffmpeg = AsyncMock()
    # Probes WAV first, then MP3.
    svc.ffmpeg.get_duration = AsyncMock(side_effect=[wav_dur, mp3_dur])
    svc.storage = MagicMock()
    svc.storage.resolve_path = MagicMock(side_effect=lambda p: Path("/tmp") / p)

    # Stub the RenderPlan so we can observe priming-offset application.
    @dataclass(frozen=True)
    class _Marker:
        title: str
        start_ms: int
        end_ms: int

    plan = MagicMock()
    plan.chapters = [
        _Marker(title="Intro", start_ms=0, end_ms=15_000),
        _Marker(title="C1", start_ms=15_000, end_ms=60_000),
    ]
    plan.apply_priming_offset = MagicMock(return_value=plan)
    svc._render_plan = plan
    return svc


def _patch_id3(write_mock: AsyncMock) -> Any:
    """Patch the late-imported ``write_audiobook_id3``."""
    id3_mod = MagicMock()
    id3_mod.write_audiobook_id3 = write_mock
    return patch.dict(sys.modules, {"drevalis.services.audiobook.id3": id3_mod})


# ── Happy path ──────────────────────────────────────────────────────


class TestSuccess:
    async def test_returns_mp3_rel_path_and_marks_dag_done(self) -> None:
        ab_id = uuid4()
        svc = _service()
        write_id3 = AsyncMock()

        with _patch_id3(write_id3):
            out = await svc._run_mp3_export_phase(
                audiobook_id=ab_id,
                final_audio=Path("/tmp/x/audiobook.wav"),
                chapters=[{"title": "C0"}],
                title="My Book",
                cover_image_path=None,
            )

        assert out == f"audiobooks/{ab_id}/audiobook.mp3"
        # WAV→MP3 conversion called.
        svc._convert_to_mp3.assert_awaited_once()
        # mp3_export DAG: in_progress → done. id3_tags: in_progress → done.
        statuses = [(c.args[0], c.args[1]) for c in svc._dag_global.call_args_list]
        assert ("mp3_export", "in_progress") in statuses
        assert ("mp3_export", "done") in statuses
        assert ("id3_tags", "in_progress") in statuses
        assert ("id3_tags", "done") in statuses


# ── LAME priming offset ─────────────────────────────────────────────


class TestPrimingOffset:
    async def test_offset_applied_to_render_plan(self) -> None:
        # 100.026s MP3 vs 100.0s WAV → 26 ms LAME priming offset.
        svc = _service(mp3_dur=100.026, wav_dur=100.0)
        with _patch_id3(AsyncMock()):
            await svc._run_mp3_export_phase(
                audiobook_id=uuid4(),
                final_audio=Path("/tmp/x/audiobook.wav"),
                chapters=[{"title": "C0"}],
                title="X",
                cover_image_path=None,
            )
        svc._render_plan.apply_priming_offset.assert_called_once_with(26)

    async def test_zero_offset_when_durations_equal(self) -> None:
        svc = _service(mp3_dur=100.0, wav_dur=100.0)
        with _patch_id3(AsyncMock()):
            await svc._run_mp3_export_phase(
                audiobook_id=uuid4(),
                final_audio=Path("/tmp/x/audiobook.wav"),
                chapters=[{"title": "C0"}],
                title="X",
                cover_image_path=None,
            )
        svc._render_plan.apply_priming_offset.assert_called_once_with(0)

    async def test_probe_failure_falls_back_to_zero_offset(self) -> None:
        # A failing probe must not abort the whole MP3 export — fall
        # back to a 0 ms offset (CHAP frames still within ±50 ms).
        svc = _service()
        svc.ffmpeg.get_duration = AsyncMock(side_effect=RuntimeError("ffprobe died"))

        with _patch_id3(AsyncMock()):
            await svc._run_mp3_export_phase(
                audiobook_id=uuid4(),
                final_audio=Path("/tmp/x/audiobook.wav"),
                chapters=[{"title": "C0"}],
                title="X",
                cover_image_path=None,
            )
        svc._render_plan.apply_priming_offset.assert_called_once_with(0)


# ── ID3 chapters built from RenderPlan ──────────────────────────────


class TestId3Chapters:
    async def test_id3_chapters_sourced_from_priming_adjusted_plan(self) -> None:
        # The CHAP frames must come from the RenderPlan's marker
        # timestamps (in ms → sec), not from the chapters list passed
        # in. This is what keeps CHAP within ±5 ms of audible
        # boundaries when the LAME priming offset is non-zero.
        svc = _service()
        write_id3 = AsyncMock()
        with _patch_id3(write_id3):
            await svc._run_mp3_export_phase(
                audiobook_id=uuid4(),
                final_audio=Path("/tmp/x/audiobook.wav"),
                chapters=[{"title": "ignored"}],
                title="X",
                cover_image_path=None,
            )
        kwargs = write_id3.call_args.kwargs
        passed = kwargs["chapters"]
        # Sourced from the plan markers, not from the input list.
        assert passed[0]["title"] == "Intro"
        assert passed[0]["start_seconds"] == 0.0
        assert passed[0]["end_seconds"] == 15.0
        assert passed[1]["title"] == "C1"
        assert passed[1]["start_seconds"] == 15.0
        assert passed[1]["end_seconds"] == 60.0


# ── Cover art ───────────────────────────────────────────────────────


class TestCoverArt:
    async def test_no_cover_when_path_not_supplied(self) -> None:
        svc = _service()
        write_id3 = AsyncMock()
        with _patch_id3(write_id3):
            await svc._run_mp3_export_phase(
                audiobook_id=uuid4(),
                final_audio=Path("/tmp/x/audiobook.wav"),
                chapters=[{"title": "C0"}],
                title="X",
                cover_image_path=None,
            )
        assert write_id3.call_args.kwargs["cover_path"] is None

    async def test_cover_passed_when_resolved_path_exists(self, tmp_path: Path) -> None:
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        svc = _service()
        svc.storage.resolve_path = MagicMock(return_value=cover)
        write_id3 = AsyncMock()
        with _patch_id3(write_id3):
            await svc._run_mp3_export_phase(
                audiobook_id=uuid4(),
                final_audio=Path("/tmp/x/audiobook.wav"),
                chapters=[{"title": "C0"}],
                title="X",
                cover_image_path="audiobooks/x/cover.jpg",
            )
        assert write_id3.call_args.kwargs["cover_path"] == cover

    async def test_missing_cover_silently_skipped(self) -> None:
        # Path resolves to something that doesn't exist on disk → cover_path=None.
        svc = _service()
        svc.storage.resolve_path = MagicMock(return_value=Path("/tmp/ghost.jpg"))
        write_id3 = AsyncMock()
        with _patch_id3(write_id3):
            await svc._run_mp3_export_phase(
                audiobook_id=uuid4(),
                final_audio=Path("/tmp/x/audiobook.wav"),
                chapters=[{"title": "C0"}],
                title="X",
                cover_image_path="audiobooks/x/cover.jpg",
            )
        assert write_id3.call_args.kwargs["cover_path"] is None


# ── Failure paths (non-fatal) ───────────────────────────────────────


class TestFailureNonFatal:
    async def test_mp3_conversion_failure_returns_none(self) -> None:
        # WAV→MP3 conversion blows up. Audiobook ships WAV-only.
        svc = _service()
        svc._convert_to_mp3 = AsyncMock(side_effect=RuntimeError("ffmpeg died"))  # type: ignore[method-assign]

        out = await svc._run_mp3_export_phase(
            audiobook_id=uuid4(),
            final_audio=Path("/tmp/x/audiobook.wav"),
            chapters=[{"title": "C0"}],
            title="X",
            cover_image_path=None,
        )
        assert out is None
        statuses = [(c.args[0], c.args[1]) for c in svc._dag_global.call_args_list]
        assert ("mp3_export", "failed") in statuses

    async def test_id3_failure_keeps_mp3_export(self) -> None:
        # ID3 write fails (mutagen hiccup) but the MP3 is on disk.
        # Return the rel path as success — only the metadata is
        # missing, the audiobook is still playable.
        svc = _service()
        ab_id = uuid4()
        write_id3 = AsyncMock(side_effect=RuntimeError("mutagen explosion"))
        with _patch_id3(write_id3):
            out = await svc._run_mp3_export_phase(
                audiobook_id=ab_id,
                final_audio=Path("/tmp/x/audiobook.wav"),
                chapters=[{"title": "C0"}],
                title="X",
                cover_image_path=None,
            )
        # MP3 path returned despite ID3 failure.
        assert out == f"audiobooks/{ab_id}/audiobook.mp3"
        statuses = [(c.args[0], c.args[1]) for c in svc._dag_global.call_args_list]
        assert ("mp3_export", "done") in statuses
        assert ("id3_tags", "failed") in statuses
