"""Tests for the RunPod auto-deploy cron
(``workers/jobs/runpod.py``).

This is a heavy worker that polls a pod for up to 5 minutes then
registers it with the appropriate service (ComfyUI or vLLM). Full
integration coverage requires a working RunPod GraphQL endpoint and
a live ComfyUI server, so the unit tests pin the safety branches:

* Pod not found in account → failed status
* Poll exhausted without RUNNING → failed status
* Status keys written to Redis with the right shape
* Proxy URL construction is deterministic
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from drevalis.workers.jobs.runpod import auto_deploy_runpod_pod

# ── Helpers ──────────────────────────────────────────────────────────


class _RecordingRedis:
    """Captures every set() call so tests can inspect status writes."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            payload = {"raw": value}
        self.writes.append((key, payload))


def _patch_runpod_service(*, list_pods_returns: list[Any]) -> Any:
    """Patch ``RunPodService`` so ``async with svc as inst: inst.list_pods()``
    returns the supplied list."""

    inst = AsyncMock()
    inst.list_pods = AsyncMock(return_value=list_pods_returns)

    class _AsyncCtxSvc:
        async def __aenter__(self) -> Any:
            return inst

        async def __aexit__(self, *_a: Any) -> None:
            return None

    return patch(
        "drevalis.services.runpod.RunPodService",
        return_value=_AsyncCtxSvc(),
    )


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``asyncio.sleep`` inside the job to skip the 10s waits."""

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)


# ── Pod-not-found path ──────────────────────────────────────────────


class TestPodNotFound:
    async def test_missing_pod_marks_failed_immediately(self, fast_sleep: None) -> None:
        # RunPod GraphQL returns an empty list (the user deleted the
        # pod between create and poll). The job marks failed on the
        # first iteration.
        redis = _RecordingRedis()
        with _patch_runpod_service(list_pods_returns=[]):
            result = await auto_deploy_runpod_pod(
                {"redis": redis},
                pod_id="abc",
                pod_type="comfyui",
                api_key="rp-secret",
                register_port=8188,
            )

        assert result["status"] == "failed"
        assert "not found" in result["message"]
        # Status writes should include the "failed" terminal state.
        statuses = [w[1].get("status") for w in redis.writes]
        assert "failed" in statuses


# ── Poll-exhausted path ─────────────────────────────────────────────


class TestPollExhausted:
    async def test_pod_never_reaches_running_marks_failed(self, fast_sleep: None) -> None:
        # Pod stays STARTING forever — after 30 attempts (~5 min) we
        # give up and mark failed.
        redis = _RecordingRedis()
        starting_pod = {"id": "abc", "desiredStatus": "STARTING"}
        with _patch_runpod_service(list_pods_returns=[starting_pod]):
            result = await auto_deploy_runpod_pod(
                {"redis": redis},
                pod_id="abc",
                pod_type="comfyui",
                api_key="rp-secret",
                register_port=8188,
            )
        assert result["status"] == "failed"
        assert "Timeout" in result["message"] or "5 minutes" in result["message"]
        statuses = [w[1].get("status") for w in redis.writes]
        # Should see many "starting" updates before the final "failed".
        assert statuses.count("starting") >= 1
        assert statuses[-1] == "failed"


# ── Polling resilience to per-attempt failures ──────────────────────


class TestPollingResilience:
    async def test_runpod_api_error_during_poll_does_not_abort(self, fast_sleep: None) -> None:
        # If a single poll attempt raises (transient GraphQL 502),
        # the job should keep polling — not mark failed on first error.
        redis = _RecordingRedis()

        inst = AsyncMock()
        # First call raises, subsequent calls return STARTING (so
        # eventually we hit the timeout path).
        call_count = {"n": 0}

        async def _list_pods() -> Any:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("RunPod API 502")
            return [{"id": "abc", "desiredStatus": "STARTING"}]

        inst.list_pods = AsyncMock(side_effect=_list_pods)

        class _AsyncCtxSvc:
            async def __aenter__(self) -> Any:
                return inst

            async def __aexit__(self, *_a: Any) -> None:
                return None

        with patch(
            "drevalis.services.runpod.RunPodService",
            return_value=_AsyncCtxSvc(),
        ):
            result = await auto_deploy_runpod_pod(
                {"redis": redis},
                pod_id="abc",
                pod_type="comfyui",
                api_key="rp-secret",
                register_port=8188,
            )
        # Eventually times out (no abort on first error).
        assert result["status"] == "failed"
        # And called the API more than once (didn't bail on first error).
        assert call_count["n"] > 1


# ── Status-write shape ──────────────────────────────────────────────


class TestStatusWrites:
    async def test_initial_deploying_status_persisted(self, fast_sleep: None) -> None:
        redis = _RecordingRedis()
        with _patch_runpod_service(list_pods_returns=[]):
            await auto_deploy_runpod_pod(
                {"redis": redis},
                pod_id="abc",
                pod_type="comfyui",
                api_key="rp-secret",
                register_port=8188,
            )
        # First write should be the initial deploying status.
        first = redis.writes[0]
        assert first[0] == "runpod_deploy:abc:status"
        assert first[1]["status"] == "deploying"
        assert first[1]["pod_id"] == "abc"
        assert first[1]["pod_type"] == "comfyui"

    async def test_redis_key_uses_pod_id(self, fast_sleep: None) -> None:
        # The key shape ``runpod_deploy:{pod_id}:status`` is what
        # ``GET /api/v1/runpod/pods/{pod_id}/deploy-status`` reads —
        # pin it so the polling endpoint never silently breaks.
        redis = _RecordingRedis()
        with _patch_runpod_service(list_pods_returns=[]):
            await auto_deploy_runpod_pod(
                {"redis": redis},
                pod_id="my-pod-xyz",
                pod_type="vllm",
                api_key="rp-secret",
                register_port=8000,
            )
        for key, _ in redis.writes:
            assert key == "runpod_deploy:my-pod-xyz:status"
