"""Tests for PipelineOrchestrator lifecycle helpers (F-Tst-02 follow-up).

Covers the small, tightly-bounded helpers around cancellation +
step-failure bookkeeping that the high-level
``test_pipeline.py::TestPipelineRunsAllSteps`` flow does not exercise:

  * ``_check_cancelled`` — Redis cancel-key handling.
  * ``_clear_cancel_flag`` — happy path + Redis-failure swallow.
  * ``_handle_step_failure`` — job + episode error mirroring, broadcast
    payload, suggestion fallback, and DB-failure resilience.

Each test wires up the orchestrator with AsyncMock services and asserts
on the recorded call args. No external services or DB.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from drevalis.services.pipeline import PipelineOrchestrator, PipelineStep


def _build() -> tuple[PipelineOrchestrator, dict[str, AsyncMock]]:
    eid = uuid4()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)

    o = PipelineOrchestrator(
        episode_id=eid,
        db_session=AsyncMock(),
        redis=redis,
        llm_service=AsyncMock(),
        comfyui_service=AsyncMock(),
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        caption_service=AsyncMock(),
        storage=AsyncMock(),
    )
    return o, {"redis": redis}


# ── _check_cancelled ─────────────────────────────────────────────────


class TestCheckCancelled:
    async def test_no_cancel_key_returns_silently(self) -> None:
        o, mocks = _build()
        mocks["redis"].get = AsyncMock(return_value=None)
        # Should not raise.
        await o._check_cancelled()
        mocks["redis"].get.assert_awaited_with(f"cancel:{o.episode_id}")

    async def test_empty_string_does_not_trigger_cancel(self) -> None:
        # Redis returns ``""`` (truthy-bytes b"" is falsy) so a stale
        # empty value doesn't accidentally fire cancellation.
        o, mocks = _build()
        mocks["redis"].get = AsyncMock(return_value=b"")
        await o._check_cancelled()  # no raise

    async def test_cancel_key_set_raises_cancelled_error(self) -> None:
        o, mocks = _build()
        mocks["redis"].get = AsyncMock(return_value=b"1")
        with pytest.raises(asyncio.CancelledError):
            await o._check_cancelled()

    async def test_cancel_key_with_arbitrary_value_still_cancels(self) -> None:
        # Production sets ``"1"`` but anything truthy must trigger.
        o, mocks = _build()
        mocks["redis"].get = AsyncMock(return_value=b"requested")
        with pytest.raises(asyncio.CancelledError):
            await o._check_cancelled()


# ── _clear_cancel_flag ───────────────────────────────────────────────


class TestClearCancelFlag:
    async def test_deletes_episode_specific_key(self) -> None:
        o, mocks = _build()
        await o._clear_cancel_flag()
        mocks["redis"].delete.assert_awaited_once_with(f"cancel:{o.episode_id}")

    async def test_redis_exception_swallowed_and_logged(self) -> None:
        o, mocks = _build()
        mocks["redis"].delete = AsyncMock(side_effect=RuntimeError("redis down"))
        # Must not raise — clean-up failures should never mask the
        # cancellation itself or block status updates.
        await o._clear_cancel_flag()


# ── _handle_step_failure ─────────────────────────────────────────────


class TestHandleStepFailure:
    def _setup(self) -> tuple[PipelineOrchestrator, MagicMock]:
        o, _ = _build()
        # Replace repos + helpers with mocks so we can assert call args.
        o.job_repo = MagicMock()
        o.job_repo.update = AsyncMock()
        o.episode_repo = MagicMock()
        o.episode_repo.update = AsyncMock()
        o.db = AsyncMock()
        o.db.commit = AsyncMock()
        o._broadcast_progress = AsyncMock()
        job = MagicMock()
        job.id = uuid4()
        job.progress_pct = 42
        job.retry_count = 0
        return o, job

    async def test_marks_job_failed_with_truncated_message(self) -> None:
        o, job = self._setup()
        long_err = RuntimeError("x" * 5000)
        await o._handle_step_failure(job, PipelineStep.SCRIPT, long_err)

        update_call = o.job_repo.update.call_args
        assert update_call.args[0] == job.id
        kwargs = update_call.kwargs
        assert kwargs["status"] == "failed"
        assert kwargs["retry_count"] == 1  # incremented from 0
        # error_message truncated to 2000 chars
        assert len(kwargs["error_message"]) <= 2000

    async def test_mirrors_error_onto_episode_with_step_prefix(self) -> None:
        o, job = self._setup()
        await o._handle_step_failure(job, PipelineStep.VOICE, RuntimeError("boom"))

        ep_update = o.episode_repo.update.call_args
        assert ep_update.args[0] == o.episode_id
        assert ep_update.kwargs["status"] == "failed"
        assert ep_update.kwargs["error_message"].startswith("voice: ")
        assert "boom" in ep_update.kwargs["error_message"]

    async def test_db_commit_invoked(self) -> None:
        o, job = self._setup()
        await o._handle_step_failure(job, PipelineStep.SCRIPT, RuntimeError("x"))
        o.db.commit.assert_awaited_once()

    async def test_broadcast_called_with_failed_status(self) -> None:
        o, job = self._setup()
        await o._handle_step_failure(job, PipelineStep.SCENES, RuntimeError("comfyui dead"))

        bc = o._broadcast_progress.call_args
        # Positional: (step, progress_pct, status, message)
        assert bc.args[0] == PipelineStep.SCENES
        assert bc.args[1] == job.progress_pct
        assert bc.args[2] == "failed"
        assert "scenes" in bc.args[3].lower()
        # Kwargs: error + detail with suggestion
        assert "comfyui" in bc.kwargs["error"].lower()
        assert "suggestion" in bc.kwargs["detail"]

    async def test_explicit_suggestion_overrides_auto(self) -> None:
        o, job = self._setup()
        await o._handle_step_failure(
            job,
            PipelineStep.ASSEMBLY,
            RuntimeError("ffmpeg crashed"),
            suggestion="Operator: rerun with --hwaccel none",
        )
        bc = o._broadcast_progress.call_args
        assert bc.kwargs["detail"]["suggestion"] == "Operator: rerun with --hwaccel none"

    async def test_auto_suggestion_used_when_not_provided(self) -> None:
        o, job = self._setup()
        await o._handle_step_failure(
            job, PipelineStep.SCRIPT, RuntimeError("comfyui server unreachable")
        )
        bc = o._broadcast_progress.call_args
        assert "ComfyUI" in bc.kwargs["detail"]["suggestion"]

    async def test_db_failure_does_not_block_broadcast(self) -> None:
        # If the DB write fails, the user must still see the failure
        # broadcast — otherwise the UI sticks at "running".
        o, job = self._setup()
        o.job_repo.update = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        await o._handle_step_failure(job, PipelineStep.SCRIPT, RuntimeError("x"))

        # Broadcast still fired despite DB error.
        o._broadcast_progress.assert_awaited_once()
        bc = o._broadcast_progress.call_args
        assert bc.args[2] == "failed"

    async def test_retry_count_carried_forward(self) -> None:
        o, job = self._setup()
        job.retry_count = 2
        await o._handle_step_failure(job, PipelineStep.SCRIPT, RuntimeError("x"))
        assert o.job_repo.update.call_args.kwargs["retry_count"] == 3
