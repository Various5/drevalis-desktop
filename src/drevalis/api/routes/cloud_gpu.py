"""Unified cloud GPU API — one surface across RunPod / Vast.ai / Lambda.

All endpoints take ``provider`` either as a path segment or body field.
Shape of responses is normalised by
:mod:`drevalis.services.cloud_gpu.base` — callers never branch on
provider.

The legacy ``/api/v1/runpod/*`` routes remain as deprecated aliases
for a release; new UI wires through here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession  # runtime import — FastAPI Depends

from drevalis.core.deps import get_db, get_settings
from drevalis.core.license.features import fastapi_dep_require_feature
from drevalis.services.cloud_gpu import (
    CloudGPUConfigError,
    CloudGPUProviderError,
    get_provider,
    list_providers_with_status,
)

if TYPE_CHECKING:
    from drevalis.core.config import Settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/cloud-gpu",
    tags=["cloud-gpu"],
    # Pro / Studio only — Solo users get 402 on every endpoint here.
    dependencies=[Depends(fastapi_dep_require_feature("runpod"))],
)


def _provider_path(name: str = Path(..., description="runpod | vastai | lambda")) -> str:
    if name not in {"runpod", "vastai", "lambda"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"error": "unknown_provider", "provider": name},
        )
    return name


def _handle_provider_exc(exc: Exception) -> None:
    if isinstance(exc, CloudGPUConfigError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "provider_not_configured",
                "provider": exc.provider,
                "hint": exc.detail,
            },
        ) from exc
    if isinstance(exc, CloudGPUProviderError):
        raise HTTPException(
            status_code=exc.status_code if 400 <= exc.status_code < 600 else 502,
            detail={"error": "provider_error", "provider": exc.provider, "message": exc.detail},
        ) from exc


# ── Providers list + status ────────────────────────────────────────────


@router.get("/providers")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    """List every supported provider + whether an API key is on file."""
    return await list_providers_with_status(db, settings)


# ── GPU types ──────────────────────────────────────────────────────────


@router.get("/{name}/gpu-types")
async def list_gpu_types(
    name: str = Depends(_provider_path),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    try:
        provider = await get_provider(name, db, settings)
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    try:
        return await provider.list_gpu_types()
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    finally:
        if hasattr(provider, "close"):
            await provider.close()


# ── Pods ───────────────────────────────────────────────────────────────


@router.get("/{name}/pods")
async def list_pods(
    name: str = Depends(_provider_path),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    try:
        provider = await get_provider(name, db, settings)
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    try:
        return await provider.list_pods()
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    finally:
        if hasattr(provider, "close"):
            await provider.close()


@router.get("/pods")
async def list_all_pods(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    """Convenience: fan out to every configured provider and aggregate."""
    statuses = await list_providers_with_status(db, settings)
    all_pods: list[dict[str, Any]] = []
    for s in statuses:
        if not s["configured"]:
            continue
        try:
            provider = await get_provider(s["name"], db, settings)
            try:
                pods = await provider.list_pods()
                all_pods.extend(pods)
            finally:
                if hasattr(provider, "close"):
                    await provider.close()
        except CloudGPUProviderError as exc:
            logger.warning(
                "cloud_gpu.aggregate_list_failed",
                provider=s["name"],
                error=exc.detail,
            )
    return all_pods


class LaunchRequest(BaseModel):
    gpu_type_id: str = Field(..., description="As returned by /providers/{name}/gpu-types")
    name: str = Field(..., min_length=1, max_length=120)
    image: str | None = Field(default=None, description="Optional container image override.")
    disk_gb: int = Field(default=40, ge=10, le=2000)
    env: dict[str, str] | None = None


@router.post("/{name}/pods", status_code=status.HTTP_201_CREATED)
async def launch_pod(
    body: LaunchRequest,
    name: str = Depends(_provider_path),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        provider = await get_provider(name, db, settings)
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    try:
        return await provider.create_pod(
            gpu_type_id=body.gpu_type_id,
            name=body.name,
            image=body.image,
            disk_gb=body.disk_gb,
            env=body.env,
        )
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    finally:
        if hasattr(provider, "close"):
            await provider.close()


@router.post("/{name}/pods/{pod_id}/stop")
async def stop_pod(
    pod_id: str,
    name: str = Depends(_provider_path),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        provider = await get_provider(name, db, settings)
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    try:
        return await provider.stop_pod(pod_id)
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    finally:
        if hasattr(provider, "close"):
            await provider.close()


@router.post("/{name}/pods/{pod_id}/start")
async def start_pod(
    pod_id: str,
    name: str = Depends(_provider_path),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        provider = await get_provider(name, db, settings)
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    try:
        return await provider.start_pod(pod_id)
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    finally:
        if hasattr(provider, "close"):
            await provider.close()


@router.delete("/{name}/pods/{pod_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pod(
    pod_id: str,
    name: str = Depends(_provider_path),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    try:
        provider = await get_provider(name, db, settings)
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    try:
        await provider.delete_pod(pod_id)
    except Exception as exc:
        _handle_provider_exc(exc)
        raise
    finally:
        if hasattr(provider, "close"):
            await provider.close()
