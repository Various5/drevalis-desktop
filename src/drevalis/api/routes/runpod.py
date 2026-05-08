"""RunPod API router — cloud GPU pod management and ComfyUI/LLM registration.

Layering: this router calls ``RunPodOrchestrator`` only. No repository
imports, no httpx/redis/encryption helpers here (audit F-A-01). The
upstream GraphQL client (``services/runpod.py``) is reached via the
orchestrator.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.license.features import fastapi_dep_require_feature
from drevalis.schemas.runpod import (
    RunPodCreatePodRequest,
    RunPodGpuTypeResponse,
    RunPodPodResponse,
    RunPodRegisterPodRequest,
    RunPodRegisterResponse,
    RunPodTemplateResponse,
)
from drevalis.services.runpod import RunPodAPIError
from drevalis.services.runpod_orchestrator import (
    DuplicatePodCreateError,
    RunPodAuthError,
    RunPodOrchestrator,
)

router = APIRouter(
    prefix="/api/v1/runpod",
    tags=["runpod"],
    dependencies=[Depends(fastapi_dep_require_feature("runpod"))],
)


def _orchestrator(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RunPodOrchestrator:
    return RunPodOrchestrator(
        db,
        encryption_key=settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )


async def _resolve_api_key(
    orch: RunPodOrchestrator = Depends(_orchestrator),
    settings: Settings = Depends(get_settings),
) -> str:
    try:
        return await orch.resolve_api_key(settings.runpod_api_key)
    except RunPodAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def _handle_runpod_error(exc: RunPodAPIError) -> HTTPException:
    """Map a RunPodAPIError to an appropriate FastAPI HTTPException."""
    match exc.status_code:
        case 401 | 403:
            http_status = status.HTTP_401_UNAUTHORIZED
            message = "RunPod API key is invalid or lacks permissions."
        case 404:
            http_status = status.HTTP_404_NOT_FOUND
            message = f"Resource not found on RunPod: {exc.detail}"
        case 429:
            http_status = status.HTTP_429_TOO_MANY_REQUESTS
            message = "RunPod API rate limit exceeded. Please retry shortly."
        case _:
            http_status = status.HTTP_502_BAD_GATEWAY
            message = f"RunPod API returned an error: {exc.detail}"
    return HTTPException(status_code=http_status, detail=message)


# ── Lookups ──────────────────────────────────────────────────────────────


@router.get(
    "/gpu-types",
    response_model=list[RunPodGpuTypeResponse],
    status_code=status.HTTP_200_OK,
    summary="List available RunPod GPU types with pricing",
)
async def list_gpu_types(
    orch: RunPodOrchestrator = Depends(_orchestrator),
    api_key: str = Depends(_resolve_api_key),
) -> list[RunPodGpuTypeResponse]:
    try:
        raw = await orch.list_gpu_types(api_key)
    except RunPodAPIError as exc:
        raise _handle_runpod_error(exc) from exc
    return [RunPodGpuTypeResponse(**entry) for entry in raw]


@router.get(
    "/templates",
    response_model=list[RunPodTemplateResponse],
    status_code=status.HTTP_200_OK,
    summary="List RunPod pod templates",
)
async def list_templates(
    category: str | None = Query(default=None),
    orch: RunPodOrchestrator = Depends(_orchestrator),
    api_key: str = Depends(_resolve_api_key),
) -> list[RunPodTemplateResponse]:
    try:
        raw = await orch.list_templates(api_key, category)
    except RunPodAPIError as exc:
        raise _handle_runpod_error(exc) from exc
    return [RunPodTemplateResponse(**entry) for entry in raw]


@router.get(
    "/pods",
    response_model=list[RunPodPodResponse],
    status_code=status.HTTP_200_OK,
    summary="List all RunPod pods",
)
async def list_pods(
    orch: RunPodOrchestrator = Depends(_orchestrator),
    api_key: str = Depends(_resolve_api_key),
) -> list[RunPodPodResponse]:
    try:
        raw = await orch.list_pods(api_key)
    except RunPodAPIError as exc:
        raise _handle_runpod_error(exc) from exc
    return [RunPodPodResponse(**pod) for pod in raw]


# ── Pod lifecycle ─────────────────────────────────────────────────────────


@router.post(
    "/pods",
    response_model=RunPodPodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create (provision) a new RunPod pod",
)
async def create_pod(
    payload: RunPodCreatePodRequest,
    orch: RunPodOrchestrator = Depends(_orchestrator),
    api_key: str = Depends(_resolve_api_key),
) -> RunPodPodResponse:
    """Provision a new GPU pod. Auto-injects HF_TOKEN; deduped 60s on
    (name, gpu_type, image)."""
    try:
        result = await orch.create_pod(api_key, payload)
    except DuplicatePodCreateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "duplicate_create", "hint": str(exc)},
        ) from exc
    except RunPodAPIError as exc:
        raise _handle_runpod_error(exc) from exc
    return RunPodPodResponse(**result)


@router.post(
    "/pods/{pod_id}/start",
    response_model=RunPodPodResponse,
    status_code=status.HTTP_200_OK,
    summary="Start (resume) a stopped RunPod pod",
)
async def start_pod(
    pod_id: str,
    orch: RunPodOrchestrator = Depends(_orchestrator),
    api_key: str = Depends(_resolve_api_key),
) -> RunPodPodResponse:
    try:
        result = await orch.start_pod(api_key, pod_id)
    except RunPodAPIError as exc:
        raise _handle_runpod_error(exc) from exc
    return RunPodPodResponse(**result)


@router.post(
    "/pods/{pod_id}/stop",
    response_model=RunPodPodResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop a running RunPod pod",
)
async def stop_pod(
    pod_id: str,
    orch: RunPodOrchestrator = Depends(_orchestrator),
    api_key: str = Depends(_resolve_api_key),
) -> RunPodPodResponse:
    try:
        result = await orch.stop_pod(api_key, pod_id)
    except RunPodAPIError as exc:
        raise _handle_runpod_error(exc) from exc
    return RunPodPodResponse(**result)


@router.delete(
    "/pods/{pod_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a RunPod pod",
)
async def delete_pod(
    pod_id: str,
    orch: RunPodOrchestrator = Depends(_orchestrator),
    api_key: str = Depends(_resolve_api_key),
) -> None:
    try:
        await orch.delete_pod(api_key, pod_id)
    except RunPodAPIError as exc:
        raise _handle_runpod_error(exc) from exc


# ── Registration as ComfyUI / LLM server ─────────────────────────────────


@router.post(
    "/pods/{pod_id}/register",
    response_model=RunPodRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a running pod as a ComfyUI server",
)
async def register_pod_as_comfyui_server(
    pod_id: str,
    payload: RunPodRegisterPodRequest,
    orch: RunPodOrchestrator = Depends(_orchestrator),
    api_key: str = Depends(_resolve_api_key),
) -> RunPodRegisterResponse:
    """Fetches pod runtime info, derives the public ComfyUI proxy URL,
    creates a ComfyUI server entry in the database, and tests the
    connection."""
    try:
        return await orch.register_as_comfyui(api_key, pod_id, payload)
    except RunPodAPIError as exc:
        raise _handle_runpod_error(exc) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Pod '{pod_id}' not found in RunPod account."
        ) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.detail) from exc


@router.post(
    "/pods/{pod_id}/register-llm",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Register a running pod as an LLM server",
)
async def register_pod_as_llm_server(
    pod_id: str,
    payload: dict[str, Any] | None = None,
    orch: RunPodOrchestrator = Depends(_orchestrator),
    api_key: str = Depends(_resolve_api_key),
) -> dict[str, Any]:
    """Derives the proxy URL, creates an LLM config entry, and tests the
    connection."""
    try:
        return await orch.register_as_llm(api_key, pod_id, payload)
    except RunPodAPIError as exc:
        raise _handle_runpod_error(exc) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Pod '{pod_id}' not found") from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.detail) from exc


# ── Auto-deploy status ───────────────────────────────────────────────────


@router.get(
    "/pods/{pod_id}/deploy-status",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get auto-deploy status for a pod",
)
async def get_deploy_status(
    pod_id: str,
    orch: RunPodOrchestrator = Depends(_orchestrator),
) -> dict[str, Any]:
    return await orch.deploy_status(pod_id)
