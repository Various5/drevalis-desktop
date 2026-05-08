"""Tests for ``AudiobookService._run_master_mix_phase`` (F-CQ-01 step 9).

Tiny phase but with a critical contract: the loudnorm pass must run
AFTER music mixing (so it integrates over the actual content) and
BEFORE captions/MP3 (so both consume the mastered WAV). Cancellation
is checked at the boundary; the loudnorm itself is non-fatal.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from drevalis.services.audiobook._monolith import AudiobookService


def _service() -> AudiobookService:
    svc = AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )
    svc._check_cancelled = AsyncMock()  # type: ignore[method-assign]
    svc._dag_global = AsyncMock()  # type: ignore[method-assign]
    svc._apply_master_loudnorm = AsyncMock()  # type: ignore[method-assign]
    return svc


class TestRunMasterMixPhase:
    async def test_calls_loudnorm_with_audio_path(self) -> None:
        svc = _service()
        audio = Path("/tmp/x/audiobook.wav")
        await svc._run_master_mix_phase(
            audiobook_id=uuid4(),
            final_audio=audio,
        )
        svc._apply_master_loudnorm.assert_awaited_once_with(audio)

    async def test_cancellation_checked_first(self) -> None:
        svc = _service()
        # Order of awaits must be: check_cancelled → dag in_progress
        # → loudnorm → dag done. If a user cancels right at the
        # boundary, we don't want to start a 30s loudnorm.
        order: list[str] = []
        svc._check_cancelled = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *_a, **_k: order.append("cancel")
        )
        svc._dag_global = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *args, **_k: order.append(f"dag:{args[1]}")
        )
        svc._apply_master_loudnorm = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *_a, **_k: order.append("loudnorm")
        )

        await svc._run_master_mix_phase(
            audiobook_id=uuid4(),
            final_audio=Path("/tmp/x.wav"),
        )
        assert order == ["cancel", "dag:in_progress", "loudnorm", "dag:done"]

    async def test_dag_transitions_in_progress_then_done(self) -> None:
        svc = _service()
        await svc._run_master_mix_phase(
            audiobook_id=uuid4(),
            final_audio=Path("/tmp/x.wav"),
        )
        statuses = [c.args[1] for c in svc._dag_global.call_args_list]
        assert statuses == ["in_progress", "done"]

    async def test_dag_uses_master_mix_stage_name(self) -> None:
        # Pin the stage name so the DAG persistence schema and the UI
        # progress legend stay in sync.
        svc = _service()
        await svc._run_master_mix_phase(
            audiobook_id=uuid4(),
            final_audio=Path("/tmp/x.wav"),
        )
        for c in svc._dag_global.call_args_list:
            assert c.args[0] == "master_mix"
