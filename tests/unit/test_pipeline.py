"""Tests for PipelineOrchestrator -- mocking all external services."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from drevalis.services.pipeline import (
    PIPELINE_ORDER,
    PipelineOrchestrator,
    PipelineStep,
)


@contextmanager
def _no_metrics():
    """Replace MetricsCollector calls with no-ops for the duration.

    The production calls land on Redis pipelines; tests use AsyncMock
    redis which doesn't satisfy that protocol. We're not testing
    metrics here, so silence them.
    """
    with (
        patch(
            "drevalis.services.pipeline._monolith.metrics.record_step",
            AsyncMock(return_value=None),
        ),
        patch(
            "drevalis.services.pipeline._monolith.metrics.record_generation",
            AsyncMock(return_value=None),
        ),
    ):
        yield


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_mock_episode(
    *,
    episode_id: UUID | None = None,
    series: MagicMock | None = None,
    script: dict | None = None,
    title: str = "Test Episode",
    topic: str | None = "test topic",
    status: str = "draft",
) -> MagicMock:
    """Create a mock Episode ORM object."""
    ep = MagicMock()
    ep.id = episode_id or uuid4()
    ep.title = title
    ep.topic = topic
    ep.status = status
    ep.script = script
    ep.override_llm_config = None
    ep.override_voice_profile = None
    ep.metadata_ = {}

    if series is None:
        series = _make_mock_series()
    ep.series = series

    return ep


def _make_mock_series() -> MagicMock:
    """Create a mock Series ORM object with all necessary config."""
    series = MagicMock()
    series.id = uuid4()
    series.name = "Test Series"
    series.llm_config = MagicMock()
    series.llm_config.id = uuid4()
    series.voice_profile = MagicMock()
    series.voice_profile.provider = "piper"
    series.comfyui_server = MagicMock()
    series.comfyui_server.id = uuid4()
    series.comfyui_workflow = MagicMock()
    series.comfyui_workflow.workflow_json_path = "workflows/test.json"
    series.comfyui_workflow.input_mappings = {
        "mappings": [
            {"sf_field": "visual_prompt", "node_id": "3", "field_name": "text"},
        ],
        "output_node_id": "9",
        "output_field_name": "images",
    }
    series.script_prompt_template = MagicMock()
    series.script_prompt_template.system_prompt = "You are a script writer."
    series.script_prompt_template.user_prompt_template = "Write about {topic}"
    series.visual_prompt_template = None
    series.visual_style = "cinematic, 4K"
    series.character_description = "a wise cat"
    series.target_duration_seconds = 30
    series.default_language = "en-US"
    return series


def _make_mock_job(
    *,
    job_id: UUID | None = None,
    step: str = "script",
    status: str = "running",
    progress_pct: int = 0,
    retry_count: int = 0,
) -> MagicMock:
    """Create a mock GenerationJob object."""
    job = MagicMock()
    job.id = job_id or uuid4()
    job.step = step
    job.status = status
    job.progress_pct = progress_pct
    job.retry_count = retry_count
    return job


def _build_orchestrator(
    episode_id: UUID | None = None,
) -> tuple[PipelineOrchestrator, dict[str, AsyncMock]]:
    """Build a PipelineOrchestrator with all services mocked."""
    eid = episode_id or uuid4()

    redis_mock = AsyncMock()
    # cancel-flag check returns None so the pipeline doesn't bail out
    # before the first step.
    redis_mock.get = AsyncMock(return_value=None)
    mocks = {
        "db_session": AsyncMock(),
        "redis": redis_mock,
        "llm_service": AsyncMock(),
        "comfyui_service": AsyncMock(),
        "tts_service": AsyncMock(),
        "ffmpeg_service": AsyncMock(),
        "caption_service": AsyncMock(),
        "storage": AsyncMock(),
    }

    orchestrator = PipelineOrchestrator(
        episode_id=eid,
        db_session=mocks["db_session"],
        redis=mocks["redis"],
        llm_service=mocks["llm_service"],
        comfyui_service=mocks["comfyui_service"],
        tts_service=mocks["tts_service"],
        ffmpeg_service=mocks["ffmpeg_service"],
        caption_service=mocks["caption_service"],
        storage=mocks["storage"],
    )

    return orchestrator, mocks


class TestPipelineStepEnum:
    """Test pipeline step enumeration and ordering."""

    def test_pipeline_order_has_six_steps(self) -> None:
        assert len(PIPELINE_ORDER) == 6

    def test_pipeline_order_sequence(self) -> None:
        expected = [
            PipelineStep.SCRIPT,
            PipelineStep.VOICE,
            PipelineStep.SCENES,
            PipelineStep.CAPTIONS,
            PipelineStep.ASSEMBLY,
            PipelineStep.THUMBNAIL,
        ]
        assert expected == PIPELINE_ORDER

    def test_pipeline_step_values(self) -> None:
        assert PipelineStep.SCRIPT.value == "script"
        assert PipelineStep.VOICE.value == "voice"
        assert PipelineStep.SCENES.value == "scenes"
        assert PipelineStep.CAPTIONS.value == "captions"
        assert PipelineStep.ASSEMBLY.value == "assembly"
        assert PipelineStep.THUMBNAIL.value == "thumbnail"


class TestPipelineRunsAllSteps:
    """Test that the pipeline executes all steps in order."""

    async def test_pipeline_runs_all_steps_in_order(self) -> None:
        orchestrator, mocks = _build_orchestrator()
        episode = _make_mock_episode()

        # Mock _load_episode to return our episode
        orchestrator._load_episode = AsyncMock(return_value=episode)

        # Mock repo: no existing completed jobs
        orchestrator.job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=None)

        # Mock job creation
        orchestrator.job_repo.create = AsyncMock(
            side_effect=lambda **kwargs: _make_mock_job(step=kwargs.get("step", "script"))
        )
        orchestrator.job_repo.get_by_id = AsyncMock(
            side_effect=lambda jid: _make_mock_job(job_id=jid)
        )

        # Mock episode repo
        orchestrator.episode_repo.update_status = AsyncMock()
        orchestrator.episode_repo.update = AsyncMock()

        # Mock step handlers so they don't do real work
        step_calls: list[str] = []

        async def _mock_step(step_name: str):
            async def handler(ep, ser, job):
                step_calls.append(step_name)

            return handler

        for step in PIPELINE_ORDER:
            handler = AsyncMock(side_effect=lambda *a, sn=step.value: step_calls.append(sn))
            setattr(orchestrator, f"_step_{step.value}", handler)

        # Mock _broadcast_progress and _mark_step_done
        orchestrator._broadcast_progress = AsyncMock()
        orchestrator._mark_step_done = AsyncMock()
        orchestrator._ensure_job = AsyncMock(return_value=_make_mock_job())
        # Mock the post-step quality gate so its repo accesses (against
        # an AsyncMock-backed db_session) don't leak unawaited coroutines
        # in the test output. Production behaviour is exercised in the
        # dedicated quality-gate tests.
        orchestrator._run_quality_gates = AsyncMock()

        with _no_metrics():
            await orchestrator.run()

        # All 6 steps should have been called
        assert len(step_calls) == 6
        assert step_calls == [s.value for s in PIPELINE_ORDER]

        # Episode status should be set to "review" at the end
        orchestrator.episode_repo.update_status.assert_any_call(orchestrator.episode_id, "review")


class TestPipelineSkipsCompletedSteps:
    """Test that completed steps are skipped on resume."""

    async def test_pipeline_skips_completed_steps(self) -> None:
        orchestrator, mocks = _build_orchestrator()
        episode = _make_mock_episode()
        orchestrator._load_episode = AsyncMock(return_value=episode)
        orchestrator.episode_repo.update_status = AsyncMock()

        # Script and voice are already done
        def _mock_get_latest(eid, step):
            if step in ("script", "voice"):
                return _make_mock_job(step=step, status="done")
            return None

        orchestrator.job_repo.get_latest_by_episode_and_step = AsyncMock(
            side_effect=_mock_get_latest
        )

        step_calls: list[str] = []
        orchestrator._ensure_job = AsyncMock(return_value=_make_mock_job())
        orchestrator._broadcast_progress = AsyncMock()
        orchestrator._mark_step_done = AsyncMock()
        # See sibling test — gate is exercised in dedicated test files.
        orchestrator._run_quality_gates = AsyncMock()

        for step in PIPELINE_ORDER:
            handler = AsyncMock(side_effect=lambda *a, sn=step.value: step_calls.append(sn))
            setattr(orchestrator, f"_step_{step.value}", handler)

        with _no_metrics():
            await orchestrator.run()

        # Script and voice should NOT be in step_calls
        assert "script" not in step_calls
        assert "voice" not in step_calls
        # Remaining 4 steps should be called
        assert len(step_calls) == 4
        assert step_calls[0] == "scenes"


class TestPipelineHandlesStepFailure:
    """Test that a failed step is handled correctly."""

    async def test_pipeline_handles_step_failure(self) -> None:
        orchestrator, mocks = _build_orchestrator()
        episode = _make_mock_episode()
        orchestrator._load_episode = AsyncMock(return_value=episode)
        orchestrator.episode_repo.update_status = AsyncMock()

        orchestrator.job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=None)

        test_job = _make_mock_job()
        orchestrator._ensure_job = AsyncMock(return_value=test_job)
        orchestrator._broadcast_progress = AsyncMock()

        # Make _step_script raise an error
        orchestrator._step_script = AsyncMock(side_effect=RuntimeError("LLM API down"))
        orchestrator._handle_step_failure = AsyncMock()

        with _no_metrics(), pytest.raises(RuntimeError, match="LLM API down"):
            await orchestrator.run()

        # _handle_step_failure should have been called
        orchestrator._handle_step_failure.assert_awaited_once()
        call_args = orchestrator._handle_step_failure.call_args
        assert call_args[0][0] is test_job  # job
        assert call_args[0][1] == PipelineStep.SCRIPT  # step
        assert isinstance(call_args[0][2], RuntimeError)  # error


class TestPipelineBroadcastsProgress:
    """Test that progress is broadcast during pipeline execution."""

    async def test_pipeline_broadcasts_progress(self) -> None:
        orchestrator, mocks = _build_orchestrator()
        episode = _make_mock_episode()
        orchestrator._load_episode = AsyncMock(return_value=episode)
        orchestrator.episode_repo.update_status = AsyncMock()

        # Only one step (script) to keep test focused
        def _mock_get_latest(eid, step):
            if step != "script":
                return _make_mock_job(step=step, status="done")
            return None

        orchestrator.job_repo.get_latest_by_episode_and_step = AsyncMock(
            side_effect=_mock_get_latest
        )

        test_job = _make_mock_job(step="script")
        orchestrator._ensure_job = AsyncMock(return_value=test_job)

        # Track broadcast calls
        broadcast_calls: list[tuple] = []
        original_broadcast = AsyncMock(side_effect=lambda *a, **kw: broadcast_calls.append((a, kw)))
        orchestrator._broadcast_progress = original_broadcast

        orchestrator._step_script = AsyncMock()
        orchestrator._mark_step_done = AsyncMock()

        with _no_metrics():
            await orchestrator.run()

        # Should have broadcast at least "Starting..." (0%) and "complete" (100%)
        # for the script step
        assert len(broadcast_calls) >= 2

        # Check that the first call is the "starting" broadcast
        first_call_args = broadcast_calls[0][0]
        assert first_call_args[0] == PipelineStep.SCRIPT
        assert first_call_args[1] == 0  # 0% progress
        assert first_call_args[2] == "running"


class TestPipelineUpdatesEpisodeStatus:
    """Test that episode status is updated during the pipeline."""

    async def test_pipeline_updates_episode_status(self) -> None:
        orchestrator, mocks = _build_orchestrator()
        episode = _make_mock_episode()
        orchestrator._load_episode = AsyncMock(return_value=episode)

        # Make all steps already done so the pipeline completes immediately
        orchestrator.job_repo.get_latest_by_episode_and_step = AsyncMock(
            return_value=_make_mock_job(status="done")
        )
        orchestrator.episode_repo.update_status = AsyncMock()
        orchestrator._broadcast_progress = AsyncMock()

        with _no_metrics():
            await orchestrator.run()

        # Should update to "generating" at start and "review" at end
        status_calls = [
            call.args[1] for call in orchestrator.episode_repo.update_status.call_args_list
        ]
        assert "generating" in status_calls
        assert "review" in status_calls
