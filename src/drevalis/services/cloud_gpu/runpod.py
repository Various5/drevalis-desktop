"""RunPod adapter — conforms the existing RunPodService to CloudGPUProvider.

Zero runtime behaviour change — we just reshape the responses into the
provider-agnostic dicts defined in :mod:`drevalis.services.cloud_gpu.base`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from drevalis.services.cloud_gpu.base import (
    CloudGPUConfigError,
    wrap_provider_api_error,
)
from drevalis.services.runpod import RunPodAPIError, RunPodService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class RunPodProvider:
    """CloudGPUProvider backed by RunPod's GraphQL API."""

    name = "runpod"
    display_name = "RunPod"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise CloudGPUConfigError(
                provider=self.name,
                hint="Add a RunPod API key in Settings → API Keys (name: 'runpod_api_key').",
            )
        self._service = RunPodService(api_key=api_key)

    async def close(self) -> None:
        await self._service.close()

    # ── Reads ─────────────────────────────────────────────────────────

    async def list_gpu_types(self) -> list[dict[str, Any]]:
        try:
            raw = await self._service.get_gpu_types()
        except RunPodAPIError as exc:
            raise wrap_provider_api_error(self.name, exc) from exc

        out: list[dict[str, Any]] = []
        for g in raw:
            # RunPod returns both secure + community prices. Prefer
            # the lower of the two so the UI shows "from $X/hr".
            price_candidates = [
                float(g.get("securePrice") or 0),
                float(g.get("communityPrice") or 0),
            ]
            price = min([p for p in price_candidates if p > 0], default=0.0)
            out.append(
                {
                    "id": str(g.get("id") or g.get("displayName", "")),
                    "label": str(g.get("displayName") or "Unknown GPU"),
                    "vram_gb": int(g.get("memoryInGb") or 0),
                    "hourly_usd": round(price, 3),
                    "provider": self.name,
                    "region": None,
                    "metadata": g,
                }
            )
        return out

    async def list_pods(self) -> list[dict[str, Any]]:
        try:
            raw = await self._service.list_pods()
        except RunPodAPIError as exc:
            raise wrap_provider_api_error(self.name, exc) from exc
        return [self._normalise_pod(p) for p in raw]

    async def get_pod(self, pod_id: str) -> dict[str, Any] | None:
        pods = await self.list_pods()
        for p in pods:
            if p["id"] == pod_id:
                return p
        return None

    # ── Mutations ─────────────────────────────────────────────────────

    async def create_pod(
        self,
        *,
        gpu_type_id: str,
        name: str,
        image: str | None = None,
        disk_gb: int = 40,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            kwargs: dict[str, Any] = {
                "name": name,
                "gpu_type_id": gpu_type_id,
                "volume_gb": disk_gb,
            }
            if image:
                kwargs["image"] = image
            if env:
                kwargs["env"] = env
            raw = await self._service.create_pod(**kwargs)
        except RunPodAPIError as exc:
            raise wrap_provider_api_error(self.name, exc) from exc
        return self._normalise_pod(raw)

    async def stop_pod(self, pod_id: str) -> dict[str, Any]:
        try:
            raw = await self._service.stop_pod(pod_id)
        except RunPodAPIError as exc:
            raise wrap_provider_api_error(self.name, exc) from exc
        return self._normalise_pod(raw)

    async def start_pod(self, pod_id: str) -> dict[str, Any]:
        try:
            raw = await self._service.start_pod(pod_id)
        except RunPodAPIError as exc:
            raise wrap_provider_api_error(self.name, exc) from exc
        return self._normalise_pod(raw)

    async def delete_pod(self, pod_id: str) -> None:
        try:
            await self._service.delete_pod(pod_id)
        except RunPodAPIError as exc:
            raise wrap_provider_api_error(self.name, exc) from exc

    # ── Helpers ───────────────────────────────────────────────────────

    def _normalise_pod(self, p: dict[str, Any]) -> dict[str, Any]:
        # RunPod reports desiredStatus + lastStatusChange.
        raw_status = (p.get("desiredStatus") or "").upper()
        normalised_status = {
            "RUNNING": "running",
            "PROVISIONING": "starting",
            "STARTING": "starting",
            "STOPPING": "stopping",
            "STOPPED": "stopped",
            "EXITED": "stopped",
            "TERMINATED": "terminated",
        }.get(raw_status, "error")

        public_url = None
        runtime = p.get("runtime") or {}
        for port in runtime.get("ports") or []:
            if port.get("isIpPublic") and str(port.get("privatePort")) in {"8188", "8000", "3000"}:
                public_url = f"http://{port.get('ip')}:{port.get('publicPort')}"
                break

        started_at = p.get("lastStartedAt") or p.get("createdAt")
        if isinstance(started_at, (int, float)):
            started_at = datetime.fromtimestamp(started_at).isoformat()

        return {
            "id": str(p.get("id", "")),
            "name": str(p.get("name", "")),
            "status": normalised_status,
            "gpu_type_id": str((p.get("machine") or {}).get("gpuTypeId", "")),
            "public_url": public_url,
            "hourly_usd": float(p.get("costPerHr") or 0.0),
            "started_at": started_at,
            "provider": self.name,
            "metadata": p,
        }
