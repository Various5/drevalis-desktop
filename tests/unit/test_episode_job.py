"""Safety-branch tests for ``workers/jobs/episode.py``.

The five episode-orchestration jobs are heavy multi-service
compositions (PipelineOrchestrator drives ~15 minutes of GPU + LLM
+ TTS + ffmpeg work). Unit-level coverage here is bounded to the
high-value safety branches:

* `generate_episode` license-gate: license_not_usable → RuntimeError
  before any work starts.
* Demo mode short-circuit: redirects to `generate_episode_demo`.
* Priority deferral: longform episode + shorts_first mode + busy
  preferred queue → enqueues a deferred retry and returns
  ``status='deferred'``.
* The four reassemble/regenerate/retry handlers commit cleanly when
  the orchestrator runs successfully and re-raise on failure (with
  the persistence side-effect already done by the orchestrator).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from drevalis.workers.jobs.episode import (
    generate_episode,
    reassemble_episode,
    regenerate_scene,
    regenerate_voice,
    retry_episode_step,
)


def _ctx(**overrides: Any) -> dict[str, Any]:
    """Build a worker ctx with all the heavy service mocks the route
    expects. Each test customises the ones it cares about."""
    sf_session = AsyncMock()
    sf_session.commit = AsyncMock()

    @asynccontextmanager
    async def _sf() -> Any:
        yield sf_session

    base: dict[str, Any] = {
        "session_factory": _sf,
        "redis": AsyncMock(),
        "arq_redis": AsyncMock(),
        "llm_service": MagicMock(),
        "comfyui_service": MagicMock(),
        "tts_service": MagicMock(),
        "ffmpeg_service": MagicMock(),
        "caption_service": MagicMock(),
        "storage": MagicMock(),
        "music_service": MagicMock(),
    }
    base.update(overrides)
    return base


def _settings(*, demo_mode: bool = False) -> Any:
    s = MagicMock()
    s.demo_mode = demo_mode
    return s


def _license_state(usable: bool = True, status_value: str = "active") -> Any:
    state = MagicMock()
    state.is_usable = usable
    state.status = SimpleNamespace(value=status_value)
    return state


# ── generate_episode safety branches ────────────────────────────────


class TestGenerateEpisodeSafetyBranches:
    async def test_demo_mode_redirects_to_demo_pipeline(self) -> None:
        ctx = _ctx()
        ep_id = str(uuid4())
        with (
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(demo_mode=True),
            ),
            patch(
                "drevalis.workers.jobs.demo_pipeline.generate_episode_demo",
                AsyncMock(return_value={"status": "demo-success"}),
            ) as demo,
        ):
            out = await generate_episode(ctx, ep_id)
        assert out == {"status": "demo-success"}
        demo.assert_awaited_once()

    async def test_unusable_license_raises_runtime_error(self) -> None:
        # 4th-line license validation: blocks bypassing the on_job_start
        # hook + middleware + lifespan bootstrap.
        ctx = _ctx()
        with (
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(demo_mode=False),
            ),
            patch(
                "drevalis.core.license.state.get_state",
                return_value=_license_state(usable=False, status_value="expired"),
            ),
        ):
            with pytest.raises(RuntimeError, match="license_not_usable:expired"):
                await generate_episode(ctx, str(uuid4()))

    async def test_priority_deferral_enqueues_and_returns_deferred(
        self,
    ) -> None:
        # shorts_first mode + this episode is longform + a shorts run is
        # already generating → defer the longform job.
        ep_id = str(uuid4())

        # Redis returns the priority mode.
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"shorts_first")

        # Session returns episode + series with content_format=longform.
        ep = SimpleNamespace(id=uuid4(), series_id=uuid4())
        series = SimpleNamespace(content_format="longform")
        session = AsyncMock()
        # First execute → preferred_generating count > 0.
        result1 = MagicMock()
        result1.scalar = MagicMock(return_value=1)
        result2 = MagicMock()
        result2.scalar = MagicMock(return_value=0)
        session.execute = AsyncMock(side_effect=[result1, result2])

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        arq_redis = MagicMock()
        arq_redis.enqueue_job = AsyncMock()
        ctx = _ctx(session_factory=_sf, redis=redis, arq_redis=arq_redis)

        # Patch the repo lookups inside the priority branch.
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=ep)
        ser_repo = MagicMock()
        ser_repo.get_by_id = AsyncMock(return_value=series)

        with (
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(demo_mode=False),
            ),
            patch(
                "drevalis.core.license.state.get_state",
                return_value=_license_state(usable=True),
            ),
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.series.SeriesRepository",
                return_value=ser_repo,
            ),
        ):
            out = await generate_episode(ctx, ep_id)
        assert out["status"] == "deferred"
        assert out["reason"] == "shorts_first"
        # Re-enqueue happened with a 60s defer.
        arq_redis.enqueue_job.assert_awaited_once()
        kwargs = arq_redis.enqueue_job.call_args.kwargs
        assert kwargs["_defer_by"] == 60

    async def test_priority_redis_failure_falls_through(self) -> None:
        # Redis.get raises → priority_mode is None → the priority branch
        # is skipped and the route proceeds to the orchestrator path.
        # Pin: Redis hiccup doesn't block episode generation.
        ep_id = str(uuid4())
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))

        # Session: get_by_id returns None for the episode dispatch lookup
        # so we don't construct an orchestrator (we just want to see the
        # priority branch cleanly skip).
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf, redis=redis)

        # Stub the dispatch + orchestrator so we don't actually run.
        orch = MagicMock()
        orch.run = AsyncMock()
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=None)
        ser_repo = MagicMock()
        ser_repo.get_by_id = AsyncMock(return_value=None)
        with (
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(demo_mode=False),
            ),
            patch(
                "drevalis.core.license.state.get_state",
                return_value=_license_state(usable=True),
            ),
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.series.SeriesRepository",
                return_value=ser_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            out = await generate_episode(ctx, ep_id)
        assert out["status"] == "success"

    async def test_orchestrator_failure_reraises_for_arq_retry(self) -> None:
        ep_id = str(uuid4())
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        session = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf, redis=redis)

        orch = MagicMock()
        orch.run = AsyncMock(side_effect=RuntimeError("scenes step crashed"))
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=None)
        ser_repo = MagicMock()
        ser_repo.get_by_id = AsyncMock(return_value=None)

        with (
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(demo_mode=False),
            ),
            patch(
                "drevalis.core.license.state.get_state",
                return_value=_license_state(usable=True),
            ),
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.series.SeriesRepository",
                return_value=ser_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            # Pin: arq retry semantics depend on the exception
            # propagating, NOT a {"status": "failed"} return.
            with pytest.raises(RuntimeError, match="scenes step crashed"):
                await generate_episode(ctx, ep_id)


# ── reassemble_episode ────────────────────────────────────────────


class TestReassembleEpisode:
    async def test_reraises_on_orchestrator_failure(self) -> None:
        ep_id = str(uuid4())
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf)

        # Asset cleanup + job-status reset succeed; orchestrator fails.
        asset_repo = MagicMock()
        asset_repo.delete_by_episode_and_types = AsyncMock(return_value=3)
        job_repo = MagicMock()
        job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=None)

        orch = MagicMock()
        orch.run = AsyncMock(side_effect=RuntimeError("ffmpeg crashed"))

        with (
            patch(
                "drevalis.repositories.media_asset.MediaAssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.generation_job.GenerationJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            # Pin: re-raise so arq retries (don't return failed → arq
            # would consider the job complete).
            with pytest.raises(RuntimeError, match="ffmpeg crashed"):
                await reassemble_episode(ctx, ep_id)

    async def test_resets_done_steps_to_queued_before_running(
        self,
    ) -> None:
        ep_id = str(uuid4())
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf)

        # captions + thumbnail were 'done' previously; assembly was
        # 'queued' and shouldn't be touched.
        captions_job = SimpleNamespace(id=uuid4(), status="done")
        assembly_job = SimpleNamespace(id=uuid4(), status="queued")
        thumb_job = SimpleNamespace(id=uuid4(), status="done")

        async def _get(_ep_id: Any, step: str) -> Any:
            return {
                "captions": captions_job,
                "assembly": assembly_job,
                "thumbnail": thumb_job,
            }.get(step)

        asset_repo = MagicMock()
        asset_repo.delete_by_episode_and_types = AsyncMock(return_value=0)
        job_repo = MagicMock()
        job_repo.get_latest_by_episode_and_step = AsyncMock(side_effect=_get)
        job_repo.update = AsyncMock()

        orch = MagicMock()
        orch.run = AsyncMock()

        with (
            patch(
                "drevalis.repositories.media_asset.MediaAssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.generation_job.GenerationJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            out = await reassemble_episode(ctx, ep_id)
        assert out["status"] == "success"
        # Pin: only 'done' steps reset; queued assembly left alone.
        update_calls = job_repo.update.await_args_list
        reset_ids = {c.args[0] for c in update_calls}
        assert captions_job.id in reset_ids
        assert thumb_job.id in reset_ids
        assert assembly_job.id not in reset_ids


# ── regenerate_voice ──────────────────────────────────────────────


class TestRegenerateVoice:
    async def test_deletes_voice_assets_before_running(self) -> None:
        ep_id = str(uuid4())
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf)

        asset_repo = MagicMock()
        asset_repo.delete_by_episode_and_types = AsyncMock(return_value=5)
        job_repo = MagicMock()
        job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=None)

        orch = MagicMock()
        orch.run = AsyncMock()

        with (
            patch(
                "drevalis.repositories.media_asset.MediaAssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.generation_job.GenerationJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            out = await regenerate_voice(ctx, ep_id)
        assert out["status"] == "success"
        # Pin: voice + downstream asset types are deleted (scenes kept).
        kwargs = asset_repo.delete_by_episode_and_types.call_args.args[1]
        assert "voiceover" in kwargs
        assert "scene" not in kwargs

    async def test_reraises_on_failure(self) -> None:
        ep_id = str(uuid4())
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf)
        asset_repo = MagicMock()
        asset_repo.delete_by_episode_and_types = AsyncMock(return_value=0)
        job_repo = MagicMock()
        job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=None)
        orch = MagicMock()
        orch.run = AsyncMock(side_effect=RuntimeError("tts down"))
        with (
            patch(
                "drevalis.repositories.media_asset.MediaAssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.generation_job.GenerationJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            with pytest.raises(RuntimeError, match="tts down"):
                await regenerate_voice(ctx, ep_id)


# ── regenerate_scene ──────────────────────────────────────────────


class TestRegenerateScene:
    async def test_returns_failed_dict_on_orchestrator_error(self) -> None:
        # Pin: regenerate_scene differs from the others — it RETURNS
        # ``status="failed"`` instead of re-raising. Per-scene reruns
        # are user-driven and the worker shouldn't retry forever.
        ep_id = str(uuid4())
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf)

        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=None)
        job_repo = MagicMock()
        job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=None)
        asset_repo = MagicMock()
        asset_repo.delete_by_episode_and_scene = AsyncMock(return_value=2)

        orch = MagicMock()
        orch.run = AsyncMock(side_effect=RuntimeError("comfyui timeout"))

        with (
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.generation_job.GenerationJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.media_asset.MediaAssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            out = await regenerate_scene(ctx, ep_id, 3)
        assert out["status"] == "failed"
        assert "comfyui timeout" in out["error"]
        assert out["scene_number"] == 3

    async def test_visual_prompt_override_persisted(self) -> None:
        # Pin: when visual_prompt is supplied, the route loads the
        # script, replaces the matching scene's visual_prompt, and
        # commits before regenerating.
        ep_id = str(uuid4())
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf)

        # Episode with a 3-scene script.
        episode = SimpleNamespace(
            id=uuid4(),
            script={
                "title": "X",
                "description": "",
                "hook": "",
                "scenes": [
                    {
                        "scene_number": 1,
                        "narration": "n1",
                        "visual_prompt": "old1",
                        "duration_seconds": 5,
                    },
                    {
                        "scene_number": 2,
                        "narration": "n2",
                        "visual_prompt": "old2",
                        "duration_seconds": 5,
                    },
                    {
                        "scene_number": 3,
                        "narration": "n3",
                        "visual_prompt": "old3",
                        "duration_seconds": 5,
                    },
                ],
                "hashtags": [],
            },
        )
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=episode)
        job_repo = MagicMock()
        job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=None)
        asset_repo = MagicMock()
        asset_repo.delete_by_episode_and_scene = AsyncMock(return_value=1)

        orch = MagicMock()
        orch.run = AsyncMock()

        with (
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.generation_job.GenerationJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.media_asset.MediaAssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            out = await regenerate_scene(ctx, ep_id, 2, visual_prompt="brand new prompt")
        assert out["status"] == "success"
        # Scene 2's prompt was replaced; others kept.
        prompts = {s["scene_number"]: s["visual_prompt"] for s in episode.script["scenes"]}
        assert prompts[1] == "old1"
        assert prompts[2] == "brand new prompt"
        assert prompts[3] == "old3"


# ── retry_episode_step ────────────────────────────────────────────


class TestRetryEpisodeStep:
    async def test_returns_failed_dict_on_orchestrator_error(self) -> None:
        # Same swallow-and-return pattern as regenerate_scene — the
        # operator triggered this manually so retry-loop is undesirable.
        ep_id = str(uuid4())
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf)

        job_repo = MagicMock()
        job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=None)

        orch = MagicMock()
        orch.run = AsyncMock(side_effect=RuntimeError("step crashed"))

        with (
            patch(
                "drevalis.repositories.generation_job.GenerationJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            out = await retry_episode_step(ctx, ep_id, "scenes")
        assert out["status"] == "failed"
        assert "step crashed" in out["error"]
        assert out["step"] == "scenes"

    async def test_resets_failed_step_to_queued(self) -> None:
        ep_id = str(uuid4())
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf)

        # Existing failed job for this step → must be reset to queued.
        existing = SimpleNamespace(id=uuid4(), status="failed")
        job_repo = MagicMock()
        job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=existing)
        job_repo.update = AsyncMock()

        orch = MagicMock()
        orch.run = AsyncMock()

        with (
            patch(
                "drevalis.repositories.generation_job.GenerationJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            out = await retry_episode_step(ctx, ep_id, "scenes")
        assert out["status"] == "success"
        # Pin: the failed job was reset before the orchestrator ran.
        job_repo.update.assert_awaited_once()
        kwargs = job_repo.update.call_args.kwargs
        assert kwargs["status"] == "queued"
        assert kwargs["progress_pct"] == 0
        assert kwargs["error_message"] is None

    async def test_skips_reset_when_step_not_failed(self) -> None:
        # Pin: the route only resets jobs in 'failed' status. Done /
        # queued / running shouldn't be touched by retry.
        ep_id = str(uuid4())
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = _ctx(session_factory=_sf)

        existing = SimpleNamespace(id=uuid4(), status="done")
        job_repo = MagicMock()
        job_repo.get_latest_by_episode_and_step = AsyncMock(return_value=existing)
        job_repo.update = AsyncMock()

        orch = MagicMock()
        orch.run = AsyncMock()

        with (
            patch(
                "drevalis.repositories.generation_job.GenerationJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.services.pipeline.PipelineOrchestrator",
                return_value=orch,
            ),
        ):
            await retry_episode_step(ctx, ep_id, "scenes")
        job_repo.update.assert_not_awaited()
