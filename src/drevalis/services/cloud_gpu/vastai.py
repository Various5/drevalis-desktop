"""Vast.ai adapter — implements CloudGPUProvider over Vast.ai's REST API.

Vast.ai is a marketplace of offers (individual GPU machines listed by
hosts). Unlike RunPod, there's no fixed catalogue — the inventory
changes minute-to-minute. To fit the ``list_gpu_types`` contract we
aggregate offers by GPU model and return the cheapest price seen per
model as the representative row. When the user launches, we pick the
cheapest currently-available offer matching that GPU model.

API docs: https://vast.ai/docs/api/search-templates
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from drevalis.services.cloud_gpu.base import (
    CloudGPUConfigError,
    wrap_httpx_error,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_VAST_BASE = "https://console.vast.ai/api/v0"


class VastAIProvider:
    """CloudGPUProvider backed by Vast.ai's REST API."""

    name = "vastai"
    display_name = "Vast.ai"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise CloudGPUConfigError(
                provider=self.name,
                hint="Add a Vast.ai API key in Settings → API Keys (name: 'vastai_api_key'). Find yours at https://vast.ai/account/.",
            )
        self._api_key = api_key
        # Vast expects `Bearer <key>` in the Authorization header.
        self._client = httpx.AsyncClient(
            base_url=_VAST_BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ── Reads ─────────────────────────────────────────────────────────

    async def list_gpu_types(self) -> list[dict[str, Any]]:
        """Aggregate the offer marketplace by GPU model. Returns one
        normalised row per distinct GPU tier, using the cheapest
        current price as the representative."""
        body = {
            "q": {
                "rentable": {"eq": True},
                "verified": {"eq": True},
                "order": [["dph_total", "asc"]],
                "type": "ask",
                "limit": 500,
            },
        }
        try:
            resp = await self._client.put("/bundles", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, "fetch Vast.ai offers", exc) from exc

        offers = (resp.json() or {}).get("offers", [])
        per_model: dict[str, dict[str, Any]] = {}
        for o in offers:
            model = str(o.get("gpu_name") or "").strip()
            if not model:
                continue
            price = float(o.get("dph_total") or 0)
            if price <= 0:
                continue
            if model not in per_model or price < per_model[model]["hourly_usd"]:
                per_model[model] = {
                    "id": str(o.get("id")),  # concrete offer id — used to launch
                    "label": model,
                    "vram_gb": int(o.get("gpu_ram", 0) // 1024) if o.get("gpu_ram") else 0,
                    "hourly_usd": round(price, 3),
                    "provider": self.name,
                    "region": o.get("geolocation"),
                    "metadata": o,
                }
        return sorted(per_model.values(), key=lambda x: x["hourly_usd"])

    async def list_pods(self) -> list[dict[str, Any]]:
        try:
            resp = await self._client.get("/instances")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, "list Vast.ai instances", exc) from exc
        instances = (resp.json() or {}).get("instances", [])
        return [self._normalise_pod(i) for i in instances]

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
        """``gpu_type_id`` here is a concrete offer ID from list_gpu_types —
        Vast.ai doesn't have generic SKUs, each row in the marketplace
        is a specific machine."""
        payload = {
            "client_id": "me",
            "image": image or "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
            "disk": disk_gb,
            "runtype": "ssh",
            "label": name,
        }
        if env:
            payload["env"] = " ".join(f"-e {k}={v}" for k, v in env.items())
        try:
            resp = await self._client.put(f"/asks/{gpu_type_id}/", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, "create Vast.ai instance", exc) from exc
        data = resp.json() or {}
        new_id = str(data.get("new_contract") or data.get("id") or "")
        # Poll list to get the normalised shape.
        pod = await self.get_pod(new_id)
        return pod or {
            "id": new_id,
            "name": name,
            "status": "starting",
            "gpu_type_id": gpu_type_id,
            "public_url": None,
            "hourly_usd": 0.0,
            "started_at": None,
            "provider": self.name,
            "metadata": data,
        }

    async def stop_pod(self, pod_id: str) -> dict[str, Any]:
        try:
            resp = await self._client.put(f"/instances/{pod_id}/", json={"state": "stopped"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, f"stop Vast.ai instance {pod_id}", exc) from exc
        return (await self.get_pod(pod_id)) or {"id": pod_id, "status": "stopped"}

    async def start_pod(self, pod_id: str) -> dict[str, Any]:
        try:
            resp = await self._client.put(f"/instances/{pod_id}/", json={"state": "running"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, f"start Vast.ai instance {pod_id}", exc) from exc
        return (await self.get_pod(pod_id)) or {"id": pod_id, "status": "starting"}

    async def delete_pod(self, pod_id: str) -> None:
        try:
            resp = await self._client.delete(f"/instances/{pod_id}/")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(self.name, f"delete Vast.ai instance {pod_id}", exc) from exc

    # ── Helpers ───────────────────────────────────────────────────────

    def _normalise_pod(self, i: dict[str, Any]) -> dict[str, Any]:
        status_map = {
            "running": "running",
            "exited": "stopped",
            "stopped": "stopped",
            "loading": "starting",
            "created": "starting",
        }
        raw = str(i.get("actual_status") or i.get("cur_state") or "").lower()
        normalised = status_map.get(raw, "error" if raw else "starting")

        public_url = None
        if i.get("ssh_host") and i.get("ports"):
            # Ports dict: {"8188/tcp": [{"HostPort": "1234"}], ...}
            ports = i.get("ports") or {}
            for private, mappings in ports.items():
                if str(private).startswith(("8188", "8000", "3000")) and mappings:
                    host_port = mappings[0].get("HostPort")
                    if host_port:
                        public_url = f"http://{i['ssh_host']}:{host_port}"
                        break

        started_at = i.get("start_date")

        return {
            "id": str(i.get("id", "")),
            "name": str(i.get("label") or f"vast-{i.get('id')}"),
            "status": normalised,
            "gpu_type_id": str(i.get("gpu_name") or ""),
            "public_url": public_url,
            "hourly_usd": float(i.get("dph_total") or 0.0),
            "started_at": started_at,
            "provider": self.name,
            "metadata": i,
        }
