"""Lambda Labs adapter — implements CloudGPUProvider over Lambda's REST API.

Lambda Labs has a much simpler inventory model than RunPod or Vast:
a fixed set of instance types, no templates, no spot pricing. Launch
by instance-type name; API returns the instance ID immediately.

API docs: https://cloud.lambda.ai/api/v1/docs
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from drevalis.services.cloud_gpu.base import (
    CloudGPUConfigError,
    CloudGPUProviderError,
    wrap_httpx_error,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_LAMBDA_BASE = "https://cloud.lambda.ai/api/v1"


class LambdaLabsProvider:
    """CloudGPUProvider backed by Lambda Labs' REST API."""

    name = "lambda"
    display_name = "Lambda Labs"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise CloudGPUConfigError(
                provider=self.name,
                hint="Add a Lambda Labs API key in Settings → API Keys (name: 'lambda_api_key'). Find yours at https://cloud.lambda.ai/api-keys.",
            )
        self._client = httpx.AsyncClient(
            base_url=_LAMBDA_BASE,
            auth=(api_key, ""),  # Lambda uses HTTP Basic with key as username, empty password
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def list_gpu_types(self) -> list[dict[str, Any]]:
        try:
            resp = await self._client.get("/instance-types")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, "fetch Lambda instance types", exc) from exc

        body = (resp.json() or {}).get("data", {})
        out: list[dict[str, Any]] = []
        for key, entry in body.items():
            spec = entry.get("instance_type", {})
            specs_detail = spec.get("specs", {})
            regions = [
                r.get("name")
                for r in entry.get("regions_with_capacity_available", [])
                if r.get("name")
            ]
            out.append(
                {
                    "id": str(key),
                    "label": str(spec.get("description") or key),
                    "vram_gb": int(
                        specs_detail.get("gpus", 0) and specs_detail.get("memory_gib", 0)
                    ),
                    "hourly_usd": round(float(spec.get("price_cents_per_hour") or 0) / 100.0, 3),
                    "provider": self.name,
                    # Lambda gates availability by region — expose the first
                    # available region so the UI can flag "out of stock".
                    "region": regions[0] if regions else None,
                    "metadata": entry,
                }
            )
        # Sort by price ascending.
        return sorted(out, key=lambda x: x["hourly_usd"])

    async def list_pods(self) -> list[dict[str, Any]]:
        try:
            resp = await self._client.get("/instances")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, "list Lambda instances", exc) from exc
        rows = (resp.json() or {}).get("data", [])
        return [self._normalise_pod(r) for r in rows]

    async def get_pod(self, pod_id: str) -> dict[str, Any] | None:
        try:
            resp = await self._client.get(f"/instances/{pod_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, f"fetch Lambda instance {pod_id}", exc) from exc
        row = (resp.json() or {}).get("data")
        return self._normalise_pod(row) if row else None

    async def create_pod(
        self,
        *,
        gpu_type_id: str,
        name: str,
        image: str | None = None,
        disk_gb: int = 40,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        # Lambda needs a region and at least one SSH key.
        gpu_types = await self.list_gpu_types()
        gpu_info = next((g for g in gpu_types if g["id"] == gpu_type_id), None)
        if not gpu_info or not gpu_info.get("region"):
            raise CloudGPUProviderError(
                provider=self.name,
                status_code=409,
                detail=(
                    f"Lambda instance type {gpu_type_id!r} has no currently-available "
                    "region. Try again later or pick a different tier."
                ),
            )

        # Pull registered SSH keys — Lambda requires one at launch.
        try:
            keys_resp = await self._client.get("/ssh-keys")
            keys_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(
                self.name,
                "load SSH keys (add one at https://cloud.lambda.ai/ssh-keys first)",
                exc,
            ) from exc
        keys = (keys_resp.json() or {}).get("data", [])
        if not keys:
            raise CloudGPUProviderError(
                provider=self.name,
                status_code=409,
                detail="No SSH keys registered with Lambda Labs. Add one at https://cloud.lambda.ai/ssh-keys first.",
            )

        try:
            resp = await self._client.post(
                "/instance-operations/launch",
                json={
                    "region_name": gpu_info["region"],
                    "instance_type_name": gpu_type_id,
                    "ssh_key_names": [keys[0]["name"]],
                    "file_system_names": [],
                    "quantity": 1,
                    "name": name,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, "launch Lambda instance", exc) from exc

        launched_ids = (resp.json() or {}).get("data", {}).get("instance_ids", [])
        if not launched_ids:
            raise CloudGPUProviderError(
                provider=self.name,
                status_code=500,
                detail="Lambda accepted the launch but returned no instance_ids.",
            )
        pod = await self.get_pod(launched_ids[0])
        return pod or {
            "id": launched_ids[0],
            "name": name,
            "status": "starting",
            "gpu_type_id": gpu_type_id,
            "public_url": None,
            "hourly_usd": gpu_info.get("hourly_usd", 0.0),
            "started_at": None,
            "provider": self.name,
            "metadata": {},
        }

    async def stop_pod(self, pod_id: str) -> dict[str, Any]:
        # Lambda has no "stop" — only terminate. Raise so the UI hides
        # the Stop button for Lambda pods rather than lying.
        raise CloudGPUProviderError(
            provider=self.name,
            status_code=405,
            detail=(
                "Lambda Labs doesn't support stop-without-delete. Use Delete to release "
                "the instance (billing stops immediately); re-launch when needed."
            ),
        )

    async def start_pod(self, pod_id: str) -> dict[str, Any]:
        raise CloudGPUProviderError(
            provider=self.name,
            status_code=405,
            detail="Lambda Labs doesn't support start — the instance is deleted when you stop billing.",
        )

    async def delete_pod(self, pod_id: str) -> None:
        try:
            resp = await self._client.post(
                "/instance-operations/terminate",
                json={"instance_ids": [pod_id]},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, "terminate Lambda instance", exc) from exc

    def _normalise_pod(self, row: dict[str, Any]) -> dict[str, Any]:
        status_map = {
            "booting": "starting",
            "active": "running",
            "unhealthy": "error",
            "terminated": "terminated",
            "terminating": "stopping",
        }
        raw = str(row.get("status") or "").lower()
        normalised = status_map.get(raw, "error")

        it = row.get("instance_type", {})
        hourly = float(it.get("price_cents_per_hour") or 0) / 100.0

        public_url = None
        if row.get("ip"):
            public_url = f"http://{row['ip']}:8188"

        return {
            "id": str(row.get("id", "")),
            "name": str(row.get("name") or f"lambda-{row.get('id')}"),
            "status": normalised,
            "gpu_type_id": str(it.get("name", "")),
            "public_url": public_url,
            "hourly_usd": round(hourly, 3),
            "started_at": None,
            "provider": self.name,
            "metadata": row,
        }
