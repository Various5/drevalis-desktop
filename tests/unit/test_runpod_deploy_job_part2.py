"""Tests for `workers/jobs/runpod.py` — comfyui + vllm registration paths.

The first test file pinned the polling/safety branches. This file
covers the post-RUNNING registration flow:

* Unknown ``pod_type`` → failed status with a clear message.
* `comfyui` registration: idempotent (skips when URL already exists)
  + connection test sets `connected=True` on success and
  `connected=False` (still ready) when the test fails.
* `vllm` registration: model_name auto-detected from `/v1/models`
  response and persisted; LLM server registered idempotently.
* The persisted Redis status key always uses the same JSON shape
  with `service_url` populated on success.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from drevalis.workers.jobs.runpod import auto_deploy_runpod_pod


class _RecordingRedis:
    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            payload = {"raw": value}
        self.writes.append((key, payload))


def _patch_runpod_service(*, list_pods_returns: list[Any]) -> Any:
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
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)


def _ctx_with_session(repo_returns: dict[str, Any]) -> tuple[Any, Any]:
    """Build a ctx + session whose repo helpers return the given data."""
    session = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    redis = _RecordingRedis()
    ctx = {"redis": redis, "session_factory": _sf}
    return ctx, session


# ── unknown pod_type ──────────────────────────────────────────────


class TestUnknownPodType:
    async def test_unknown_pod_type_marks_failed(
        self, fast_sleep: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Set up an env where the pod is RUNNING immediately so we
        # reach the dispatch branch.
        ctx, _ = _ctx_with_session({})
        with _patch_runpod_service(list_pods_returns=[{"id": "p1", "desiredStatus": "RUNNING"}]):
            out = await auto_deploy_runpod_pod(ctx, "p1", "kubernetes", "rp-key", 8188)
        assert out["status"] == "failed"
        assert "kubernetes" in out["message"]
        # Last status write reflects the unknown-pod_type message.
        assert any(
            w[1].get("status") == "failed" and "Unknown pod_type" in w[1].get("message", "")
            for w in ctx["redis"].writes
        )


# ── comfyui registration path ─────────────────────────────────────


class TestComfyUIRegistration:
    async def test_creates_server_and_marks_connected_on_200(self, fast_sleep: None) -> None:
        ctx, _ = _ctx_with_session({})

        repo = MagicMock()
        # No existing server with this URL → new registration runs.
        repo.get_all = AsyncMock(return_value=[])
        repo.create = AsyncMock()

        # ComfyUI /system_stats responds 200 → connection_ok=True.
        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"system": {}})

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with (
            _patch_runpod_service(list_pods_returns=[{"id": "p1", "desiredStatus": "RUNNING"}]),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.core.security.encrypt_value",
                return_value=(b"opaque", 1),
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await auto_deploy_runpod_pod(ctx, "p1", "comfyui", "rp-key", 8188)

        assert out["status"] == "ready"
        assert out["pod_id"] == "p1"
        assert out["service_url"] == "https://p1-8188.proxy.runpod.net"
        # New server was created (existing list was empty).
        repo.create.assert_awaited_once()
        # Final Redis status write marks ready+connected.
        ready_writes = [w for w in ctx["redis"].writes if w[1].get("status") == "ready"]
        assert ready_writes
        assert "registered and connected" in ready_writes[-1][1]["message"]

    async def test_skips_create_when_url_already_registered(self, fast_sleep: None) -> None:
        # Idempotent: existing server with same URL → no new row.
        ctx, _ = _ctx_with_session({})
        existing = SimpleNamespace(
            id=uuid4(),
            url="https://p1-8188.proxy.runpod.net",
        )
        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[existing])
        repo.create = AsyncMock()

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with (
            _patch_runpod_service(list_pods_returns=[{"id": "p1", "desiredStatus": "RUNNING"}]),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=repo,
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await auto_deploy_runpod_pod(ctx, "p1", "comfyui", "rp-key", 8188)

        assert out["status"] == "ready"
        repo.create.assert_not_awaited()

    async def test_marks_ready_pending_when_connection_test_fails(self, fast_sleep: None) -> None:
        # ComfyUI registered, but /system_stats returns 500 on every
        # attempt. Pin: status STILL goes "ready" but with the
        # "connection test pending" message — operator can act on it.
        ctx, _ = _ctx_with_session({})
        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[])
        repo.create = AsyncMock()

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with (
            _patch_runpod_service(list_pods_returns=[{"id": "p1", "desiredStatus": "RUNNING"}]),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.core.security.encrypt_value",
                return_value=(b"opaque", 1),
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await auto_deploy_runpod_pod(ctx, "p1", "comfyui", "rp-key", 8188)
        assert out["status"] == "ready"
        ready = [w for w in ctx["redis"].writes if w[1].get("status") == "ready"]
        assert ready
        assert "connection test pending" in ready[-1][1]["message"]

    async def test_connection_test_exception_swallowed(self, fast_sleep: None) -> None:
        # If httpx raises (e.g. DNS error mid-test), the loop continues
        # to the next attempt and eventually marks ready-pending.
        ctx, _ = _ctx_with_session({})
        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[])
        repo.create = AsyncMock()

        def _h(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns")

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with (
            _patch_runpod_service(list_pods_returns=[{"id": "p1", "desiredStatus": "RUNNING"}]),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.core.security.encrypt_value",
                return_value=(b"opaque", 1),
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await auto_deploy_runpod_pod(ctx, "p1", "comfyui", "rp-key", 8188)
        # Pin: even with ALL connection tests raising, the route
        # still returns ready (the server row IS created in DB).
        assert out["status"] == "ready"


# ── vllm registration path ────────────────────────────────────────


class TestVLLMRegistration:
    async def test_creates_config_and_detects_model_name(self, fast_sleep: None) -> None:
        # vLLM /v1/models responds 200 with model id → route persists
        # the detected name back to the config.
        ctx, _ = _ctx_with_session({})

        llm_repo = MagicMock()
        llm_repo.get_all = AsyncMock(return_value=[])
        target = SimpleNamespace(id=uuid4(), base_url="https://p1-1234.proxy.runpod.net/v1")
        llm_repo.create = AsyncMock(return_value=target)
        llm_repo.update = AsyncMock()

        # Second time get_all is called (model-update phase) the new
        # row is in the list.
        llm_repo.get_all.side_effect = [[], [target]]

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "qwen2.5-7b"}]})

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with (
            _patch_runpod_service(list_pods_returns=[{"id": "p1", "desiredStatus": "RUNNING"}]),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await auto_deploy_runpod_pod(ctx, "p1", "vllm", "rp-key", 1234)

        assert out["status"] == "ready"
        # Config created on first lookup, then updated with detected
        # model_name.
        llm_repo.create.assert_awaited_once()
        llm_repo.update.assert_awaited_once()
        update_kwargs = llm_repo.update.call_args.kwargs
        assert update_kwargs["model_name"] == "qwen2.5-7b"

        # Final Redis write includes model_name in the structured
        # status payload.
        ready = [w for w in ctx["redis"].writes if w[1].get("status") == "ready"]
        assert ready[-1][1].get("model_name") == "qwen2.5-7b"

    async def test_skips_create_when_base_url_already_registered(self, fast_sleep: None) -> None:
        ctx, _ = _ctx_with_session({})
        existing = SimpleNamespace(
            id=uuid4(),
            base_url="https://p1-1234.proxy.runpod.net/v1",
        )
        llm_repo = MagicMock()
        llm_repo.get_all = AsyncMock(return_value=[existing])
        llm_repo.create = AsyncMock()
        llm_repo.update = AsyncMock()

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with (
            _patch_runpod_service(list_pods_returns=[{"id": "p1", "desiredStatus": "RUNNING"}]),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await auto_deploy_runpod_pod(ctx, "p1", "vllm", "rp-key", 1234)
        assert out["status"] == "ready"
        llm_repo.create.assert_not_awaited()

    async def test_marks_ready_pending_when_model_still_loading(self, fast_sleep: None) -> None:
        # /v1/models returns 503 every attempt → vLLM model still
        # loading. Status STILL goes ready (config row exists) but
        # with "model still loading" in the message.
        ctx, _ = _ctx_with_session({})
        llm_repo = MagicMock()
        llm_repo.get_all = AsyncMock(return_value=[])
        llm_repo.create = AsyncMock()

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with (
            _patch_runpod_service(list_pods_returns=[{"id": "p1", "desiredStatus": "RUNNING"}]),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await auto_deploy_runpod_pod(ctx, "p1", "vllm", "rp-key", 1234)
        assert out["status"] == "ready"
        ready = [w for w in ctx["redis"].writes if w[1].get("status") == "ready"]
        assert ready
        assert "model still loading" in ready[-1][1]["message"]
