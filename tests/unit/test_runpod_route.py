"""Tests for ``api/routes/runpod.py``.

Pin the per-status RunPodAPIError mapping (401/403/404/429/other) and
the duplicate-create + auth-resolve guards. ``_handle_runpod_error``
is the central conversion table; if it drifts the UI gets the wrong
prompt back ("rate limited" vs "auth invalid").
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from drevalis.api.routes.runpod import (
    _handle_runpod_error,
    _orchestrator,
    _resolve_api_key,
    create_pod,
    delete_pod,
    get_deploy_status,
    list_gpu_types,
    list_pods,
    list_templates,
    register_pod_as_comfyui_server,
    register_pod_as_llm_server,
    start_pod,
    stop_pod,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.runpod import (
    RunPodCreatePodRequest,
    RunPodRegisterPodRequest,
    RunPodRegisterResponse,
)
from drevalis.services.runpod import RunPodAPIError
from drevalis.services.runpod_orchestrator import (
    DuplicatePodCreateError,
    RunPodAuthError,
    RunPodOrchestrator,
)


def _settings() -> Any:
    s = MagicMock()
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    s.runpod_api_key = ""
    return s


def _gpu_payload() -> dict[str, Any]:
    return {
        "id": "NVIDIA RTX A4000",
        "displayName": "RTX A4000",
        "memoryInGb": 16,
        "secureCloud": True,
        "communityCloud": False,
        "securePrice": 0.34,
    }


def _pod_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "abc123",
        "name": "drevalis-comfyui",
        "desiredStatus": "RUNNING",
    }
    base.update(overrides)
    return base


# ── _orchestrator factory ──────────────────────────────────────────


class TestOrchestratorFactory:
    def test_returns_orchestrator(self) -> None:
        orch = _orchestrator(db=AsyncMock(), settings=_settings())
        assert isinstance(orch, RunPodOrchestrator)


# ── _resolve_api_key ───────────────────────────────────────────────


class TestResolveApiKey:
    async def test_returns_api_key(self) -> None:
        orch = MagicMock()
        orch.resolve_api_key = AsyncMock(return_value="rp-secret")
        out = await _resolve_api_key(orch=orch, settings=_settings())
        assert out == "rp-secret"

    async def test_auth_error_maps_to_503(self) -> None:
        # Pin: missing API key on a feature-gated route → 503, NOT 401.
        # The UI shows "RunPod is not configured" instead of treating it
        # as a session-expiry condition.
        orch = MagicMock()
        orch.resolve_api_key = AsyncMock(side_effect=RunPodAuthError("no key configured"))
        with pytest.raises(HTTPException) as exc:
            await _resolve_api_key(orch=orch, settings=_settings())
        assert exc.value.status_code == 503


# ── _handle_runpod_error ───────────────────────────────────────────


class TestHandleRunpodError:
    @pytest.mark.parametrize("upstream_status", [401, 403])
    def test_auth_failures_map_to_401(self, upstream_status: int) -> None:
        out = _handle_runpod_error(RunPodAPIError(status_code=upstream_status, detail="bad token"))
        assert out.status_code == 401
        assert "API key" in out.detail

    def test_404_maps_to_404_with_detail_passed_through(self) -> None:
        out = _handle_runpod_error(RunPodAPIError(status_code=404, detail="pod abc123 missing"))
        assert out.status_code == 404
        assert "pod abc123 missing" in out.detail

    def test_429_maps_to_429(self) -> None:
        out = _handle_runpod_error(RunPodAPIError(status_code=429, detail="rate limited"))
        assert out.status_code == 429

    def test_other_status_maps_to_502_bad_gateway(self) -> None:
        # Pin: anything else (500, 503, 504, or our "0" for transport
        # errors) is reported as 502 Bad Gateway — the upstream is
        # unreachable from our POV.
        out = _handle_runpod_error(RunPodAPIError(status_code=500, detail="upstream crash"))
        assert out.status_code == 502


# ── Lookup endpoints ───────────────────────────────────────────────


class TestLookups:
    async def test_list_gpu_types_success(self) -> None:
        orch = MagicMock()
        orch.list_gpu_types = AsyncMock(return_value=[_gpu_payload()])
        out = await list_gpu_types(orch=orch, api_key="k")
        assert out[0].display_name == "RTX A4000"
        assert out[0].secure_cloud is True

    async def test_list_gpu_types_propagates_runpod_error(self) -> None:
        orch = MagicMock()
        orch.list_gpu_types = AsyncMock(
            side_effect=RunPodAPIError(status_code=429, detail="slow down")
        )
        with pytest.raises(HTTPException) as exc:
            await list_gpu_types(orch=orch, api_key="k")
        assert exc.value.status_code == 429

    async def test_list_templates_passes_category(self) -> None:
        orch = MagicMock()
        orch.list_templates = AsyncMock(return_value=[])
        await list_templates(category="comfyui", orch=orch, api_key="k")
        orch.list_templates.assert_awaited_once_with("k", "comfyui")

    async def test_list_templates_runpod_error(self) -> None:
        orch = MagicMock()
        orch.list_templates = AsyncMock(
            side_effect=RunPodAPIError(status_code=401, detail="no auth")
        )
        with pytest.raises(HTTPException) as exc:
            await list_templates(category=None, orch=orch, api_key="k")
        assert exc.value.status_code == 401

    async def test_list_pods_success(self) -> None:
        orch = MagicMock()
        orch.list_pods = AsyncMock(return_value=[_pod_payload()])
        out = await list_pods(orch=orch, api_key="k")
        assert out[0].id == "abc123"

    async def test_list_pods_runpod_error(self) -> None:
        orch = MagicMock()
        orch.list_pods = AsyncMock(side_effect=RunPodAPIError(status_code=502, detail="oops"))
        with pytest.raises(HTTPException) as exc:
            await list_pods(orch=orch, api_key="k")
        assert exc.value.status_code == 502


# ── Pod lifecycle ──────────────────────────────────────────────────


class TestPodLifecycle:
    async def test_create_pod_success(self) -> None:
        orch = MagicMock()
        orch.create_pod = AsyncMock(return_value=_pod_payload())
        body = RunPodCreatePodRequest(name="drevalis-comfyui")
        out = await create_pod(payload=body, orch=orch, api_key="k")
        assert out.id == "abc123"

    async def test_create_pod_duplicate_maps_to_409(self) -> None:
        # Pin: provisioning the same pod twice in 60s → 409 with a
        # structured `duplicate_create` detail so the UI can show a
        # toast pointing at the existing pod.
        orch = MagicMock()
        orch.create_pod = AsyncMock(
            side_effect=DuplicatePodCreateError("already provisioning abc123")
        )
        body = RunPodCreatePodRequest(name="x")
        with pytest.raises(HTTPException) as exc:
            await create_pod(payload=body, orch=orch, api_key="k")
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "duplicate_create"

    async def test_create_pod_runpod_error(self) -> None:
        orch = MagicMock()
        orch.create_pod = AsyncMock(
            side_effect=RunPodAPIError(status_code=429, detail="rate limit")
        )
        body = RunPodCreatePodRequest(name="x")
        with pytest.raises(HTTPException) as exc:
            await create_pod(payload=body, orch=orch, api_key="k")
        assert exc.value.status_code == 429

    async def test_start_pod_success(self) -> None:
        orch = MagicMock()
        orch.start_pod = AsyncMock(return_value=_pod_payload())
        out = await start_pod(pod_id="abc", orch=orch, api_key="k")
        assert out.id == "abc123"

    async def test_start_pod_runpod_error(self) -> None:
        orch = MagicMock()
        orch.start_pod = AsyncMock(side_effect=RunPodAPIError(status_code=404, detail="no pod"))
        with pytest.raises(HTTPException) as exc:
            await start_pod(pod_id="abc", orch=orch, api_key="k")
        assert exc.value.status_code == 404

    async def test_stop_pod_success(self) -> None:
        orch = MagicMock()
        orch.stop_pod = AsyncMock(return_value=_pod_payload(desiredStatus="EXITED"))
        out = await stop_pod(pod_id="abc", orch=orch, api_key="k")
        assert out.desired_status == "EXITED"

    async def test_stop_pod_runpod_error(self) -> None:
        orch = MagicMock()
        orch.stop_pod = AsyncMock(side_effect=RunPodAPIError(status_code=403, detail="forbidden"))
        with pytest.raises(HTTPException) as exc:
            await stop_pod(pod_id="abc", orch=orch, api_key="k")
        assert exc.value.status_code == 401  # 403 maps to 401 in our table

    async def test_delete_pod_success(self) -> None:
        orch = MagicMock()
        orch.delete_pod = AsyncMock()
        await delete_pod(pod_id="abc", orch=orch, api_key="k")
        orch.delete_pod.assert_awaited_once_with("k", "abc")

    async def test_delete_pod_runpod_error(self) -> None:
        orch = MagicMock()
        orch.delete_pod = AsyncMock(side_effect=RunPodAPIError(status_code=502, detail="upstream"))
        with pytest.raises(HTTPException) as exc:
            await delete_pod(pod_id="abc", orch=orch, api_key="k")
        assert exc.value.status_code == 502


# ── Registration endpoints ─────────────────────────────────────────


class TestRegisterAsComfyUI:
    async def test_success(self) -> None:
        orch = MagicMock()
        resp = RunPodRegisterResponse(
            pod_id="abc",
            comfyui_server_id="srv-1",
            comfyui_url="https://abc-8188.proxy.runpod.net",
            connection_ok=True,
            message="ok",
        )
        orch.register_as_comfyui = AsyncMock(return_value=resp)
        body = RunPodRegisterPodRequest()
        out = await register_pod_as_comfyui_server(
            pod_id="abc", payload=body, orch=orch, api_key="k"
        )
        assert out.connection_ok is True

    async def test_runpod_error_passes_through(self) -> None:
        orch = MagicMock()
        orch.register_as_comfyui = AsyncMock(
            side_effect=RunPodAPIError(status_code=502, detail="upstream")
        )
        with pytest.raises(HTTPException) as exc:
            await register_pod_as_comfyui_server(
                pod_id="abc",
                payload=RunPodRegisterPodRequest(),
                orch=orch,
                api_key="k",
            )
        assert exc.value.status_code == 502

    async def test_not_found_maps_to_404(self) -> None:
        orch = MagicMock()
        from uuid import uuid4

        orch.register_as_comfyui = AsyncMock(side_effect=NotFoundError("pod", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await register_pod_as_comfyui_server(
                pod_id="abc",
                payload=RunPodRegisterPodRequest(),
                orch=orch,
                api_key="k",
            )
        assert exc.value.status_code == 404

    async def test_validation_error_maps_to_422(self) -> None:
        orch = MagicMock()
        orch.register_as_comfyui = AsyncMock(side_effect=ValidationError("port mapping missing"))
        with pytest.raises(HTTPException) as exc:
            await register_pod_as_comfyui_server(
                pod_id="abc",
                payload=RunPodRegisterPodRequest(),
                orch=orch,
                api_key="k",
            )
        assert exc.value.status_code == 422


class TestRegisterAsLLM:
    async def test_success(self) -> None:
        orch = MagicMock()
        orch.register_as_llm = AsyncMock(return_value={"llm_config_id": "cfg-1"})
        out = await register_pod_as_llm_server(pod_id="abc", payload=None, orch=orch, api_key="k")
        assert out["llm_config_id"] == "cfg-1"

    async def test_runpod_error(self) -> None:
        orch = MagicMock()
        orch.register_as_llm = AsyncMock(side_effect=RunPodAPIError(status_code=401, detail="bad"))
        with pytest.raises(HTTPException) as exc:
            await register_pod_as_llm_server(pod_id="abc", payload=None, orch=orch, api_key="k")
        assert exc.value.status_code == 401

    async def test_not_found_maps_to_404(self) -> None:
        orch = MagicMock()
        from uuid import uuid4

        orch.register_as_llm = AsyncMock(side_effect=NotFoundError("pod", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await register_pod_as_llm_server(pod_id="abc", payload=None, orch=orch, api_key="k")
        assert exc.value.status_code == 404

    async def test_validation_maps_to_422(self) -> None:
        orch = MagicMock()
        orch.register_as_llm = AsyncMock(side_effect=ValidationError("port mapping missing"))
        with pytest.raises(HTTPException) as exc:
            await register_pod_as_llm_server(pod_id="abc", payload=None, orch=orch, api_key="k")
        assert exc.value.status_code == 422


# ── Deploy status ──────────────────────────────────────────────────


class TestDeployStatus:
    async def test_returns_orchestrator_payload(self) -> None:
        orch = MagicMock()
        orch.deploy_status = AsyncMock(return_value={"status": "ready", "url": "x"})
        out = await get_deploy_status(pod_id="abc", orch=orch)
        assert out["status"] == "ready"
