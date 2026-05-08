"""RunPodOrchestrator — domain layer over the RunPod GraphQL client.

Wraps the low-level ``RunPodService`` (httpx GraphQL client) and adds:

- API-key resolution from the encrypted ``api_key_store`` with env-var
  fallback,
- create-pod idempotency dedup via Redis SET NX,
- HF_TOKEN auto-injection from the same store,
- multi-repo registration flows (ComfyUI + LLM config) including
  reachability probing,
- Redis-backed deploy-status lookup.

This file exists so the runpod route file can stay free of repository
imports, encryption helpers, and httpx orchestration (audit F-A-01).
The lower-level GraphQL client remains in ``services/runpod.py``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.security import decrypt_value, decrypt_value_multi, encrypt_value
from drevalis.repositories.api_key_store import ApiKeyStoreRepository
from drevalis.repositories.comfyui import ComfyUIServerRepository
from drevalis.repositories.llm_config import LLMConfigRepository
from drevalis.schemas.runpod import (
    RunPodCreatePodRequest,
    RunPodRegisterPodRequest,
    RunPodRegisterResponse,
)
from drevalis.services.runpod import RunPodService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_RUNPOD_KEY_NAME = "runpod"
_HF_KEY_NAME = "hf_token"


class RunPodAuthError(Exception):
    """Raised when no RunPod API key is configured anywhere."""


class DuplicatePodCreateError(Exception):
    """Raised when a duplicate create-pod request is detected within the dedup window."""


class RunPodOrchestrator:
    def __init__(
        self,
        db: AsyncSession,
        *,
        encryption_key: str,
        encryption_keys: dict[int, str] | None = None,
    ) -> None:
        self._db = db
        self._encryption_key = encryption_key
        self._encryption_keys: dict[int, str] = encryption_keys or {1: encryption_key}
        self._key_store = ApiKeyStoreRepository(db)
        self._comfyui = ComfyUIServerRepository(db)
        self._llm = LLMConfigRepository(db)

    def _decrypt(self, ciphertext: str) -> str:
        if len(self._encryption_keys) > 1:
            plaintext, _ = decrypt_value_multi(ciphertext, self._encryption_keys)
            return plaintext
        return decrypt_value(ciphertext, self._encryption_key)

    def _encrypt(self, plaintext: str) -> tuple[str, int]:
        return encrypt_value(
            plaintext,
            self._encryption_key,
            version=max(self._encryption_keys),
        )

    # ── API key resolution ───────────────────────────────────────────────

    async def resolve_api_key(self, env_fallback: str | None) -> str:
        """Resolve the RunPod API key from DB store first, then env var."""
        entry = await self._key_store.get_by_key_name(_RUNPOD_KEY_NAME)
        if entry is not None:
            try:
                return self._decrypt(entry.encrypted_value)
            except Exception:
                pass
        if env_fallback:
            return env_fallback
        raise RunPodAuthError(
            "RunPod API key is not configured. "
            "Add it via POST /api/v1/settings/api-keys or set RUNPOD_API_KEY in .env."
        )

    # ── Pure pass-throughs (here so the route doesn't import RunPodService) ─

    async def list_gpu_types(self, api_key: str) -> list[dict[str, Any]]:
        async with RunPodService(api_key) as svc:
            return await svc.get_gpu_types()

    async def list_templates(self, api_key: str, category: str | None) -> list[dict[str, Any]]:
        async with RunPodService(api_key) as svc:
            return await svc.get_templates(category=category)

    async def list_pods(self, api_key: str) -> list[dict[str, Any]]:
        async with RunPodService(api_key) as svc:
            return await svc.list_pods()

    async def start_pod(self, api_key: str, pod_id: str) -> dict[str, Any]:
        async with RunPodService(api_key) as svc:
            return await svc.start_pod(pod_id)

    async def stop_pod(self, api_key: str, pod_id: str) -> dict[str, Any]:
        async with RunPodService(api_key) as svc:
            return await svc.stop_pod(pod_id)

    async def delete_pod(self, api_key: str, pod_id: str) -> None:
        async with RunPodService(api_key) as svc:
            await svc.delete_pod(pod_id)

    # ── Create pod (idempotent + HF token + auto-deploy enqueue) ─────────

    async def create_pod(self, api_key: str, payload: RunPodCreatePodRequest) -> dict[str, Any]:
        from drevalis.core.redis import get_arq_pool
        from drevalis.core.redis import get_pool as _get_redis_pool

        # 1. dedup
        fingerprint = hashlib.sha256(
            f"{payload.name}|{payload.gpu_type_id}|{payload.image}".encode()
        ).hexdigest()[:16]
        idem_key = f"runpod_create:{fingerprint}"
        try:
            from redis.asyncio import Redis

            rc: Redis = Redis(connection_pool=_get_redis_pool())
            try:
                if not await rc.set(idem_key, "1", ex=60, nx=True):
                    raise DuplicatePodCreateError(
                        "A create-pod request with the same name, GPU type, and image was "
                        "submitted within the last 60s. Retry in a minute if intentional, or "
                        "check /pods to see the pod that is already being provisioned."
                    )
            finally:
                await rc.aclose()
        except DuplicatePodCreateError:
            raise
        except Exception:
            # Redis unavailable — allow the request through.
            pass

        # 2. build env, auto-inject HF_TOKEN if not supplied
        pod_env: dict[str, str] = dict(payload.env) if payload.env else {}
        if "HF_TOKEN" not in pod_env:
            try:
                hf_row = await self._key_store.get_by_key_name(_HF_KEY_NAME)
                if hf_row:
                    pod_env["HF_TOKEN"] = self._decrypt(hf_row.encrypted_value)
            except Exception:
                pass

        # 3. provision via GraphQL
        async with RunPodService(api_key) as svc:
            result = await svc.create_pod(
                name=payload.name,
                gpu_type_id=payload.gpu_type_id,
                image=payload.image,
                gpu_count=payload.gpu_count,
                volume_gb=payload.volume_gb,
                ports=payload.ports,
                template_id=payload.template_id,
                env=pod_env if pod_env else None,
                docker_args=payload.docker_args,
            )

        # 4. enqueue auto-deploy poll-and-register
        pod_id = result.get("id", "")
        if pod_id:
            arq = get_arq_pool()
            image_lower = payload.image.lower()
            if "comfyui" in image_lower:
                pod_type = "comfyui"
                register_port = 8188
            else:
                pod_type = "vllm"
                register_port = 8000
            await arq.enqueue_job(
                "auto_deploy_runpod_pod",
                pod_id,
                pod_type,
                api_key,
                register_port,
            )
        return result

    # ── Register as ComfyUI server ───────────────────────────────────────

    async def register_as_comfyui(
        self, api_key: str, pod_id: str, payload: RunPodRegisterPodRequest
    ) -> RunPodRegisterResponse:
        async with RunPodService(api_key) as svc:
            pods = await svc.list_pods()

        pod = next((p for p in pods if p.get("id") == pod_id), None)
        if pod is None:
            raise NotFoundError("Pod", pod_id)

        comfyui_url = _extract_proxy_url(pod, payload.comfyui_port)
        if comfyui_url is None:
            raise ValidationError(
                f"Could not find a proxy URL for port {payload.comfyui_port} in pod "
                f"'{pod_id}' runtime info. Ensure the pod is running and the port is exposed."
            )

        server_name = payload.server_name or f"runpod-{pod_id}"
        existing_servers = await self._comfyui.get_all()
        existing = next((s for s in existing_servers if s.url == comfyui_url), None)

        encrypted_key, key_version = self._encrypt(api_key)

        if existing is None:
            server = await self._comfyui.create(
                name=server_name,
                url=comfyui_url,
                api_key_encrypted=encrypted_key,
                api_key_version=key_version,
                max_concurrent=payload.max_concurrent,
                is_active=True,
            )
            await self._db.commit()
            await self._db.refresh(server)
        else:
            server = existing

        connection_ok, message = await _probe_http(
            f"{comfyui_url}/system_stats",
            headers={"Authorization": f"Bearer {api_key}"},
            label=f"ComfyUI at {comfyui_url}",
        )
        return RunPodRegisterResponse(
            pod_id=pod_id,
            comfyui_server_id=str(server.id),
            comfyui_url=comfyui_url,
            connection_ok=connection_ok,
            message=message,
        )

    # ── Register as LLM server ───────────────────────────────────────────

    async def register_as_llm(
        self, api_key: str, pod_id: str, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        llm_port = (payload or {}).get("port", 8000)
        model_name = (payload or {}).get("model", "auto")

        async with RunPodService(api_key) as svc:
            pods = await svc.list_pods()

        pod = next((p for p in pods if p.get("id") == pod_id), None)
        if pod is None:
            raise NotFoundError("Pod", pod_id)

        llm_url = _extract_proxy_url(pod, llm_port)
        if llm_url is None:
            raise ValidationError(
                f"Could not find proxy URL for port {llm_port} on pod '{pod_id}'. "
                "Ensure the pod is running and the port is exposed."
            )
        base_url = llm_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"

        server_name = f"runpod-llm-{pod_id}"
        existing_configs = await self._llm.get_all()
        existing = next((c for c in existing_configs if c.base_url == base_url), None)

        # vLLM pods are deployed without API keys (RunPod proxy strips auth).
        encrypted_key, key_ver = "", 1

        if existing is None:
            config = await self._llm.create(
                name=server_name,
                base_url=base_url,
                model_name=model_name,
                api_key_encrypted=encrypted_key,
                api_key_version=key_ver,
            )
            await self._db.commit()
            await self._db.refresh(config)
        else:
            await self._llm.update(
                existing.id, api_key_encrypted=encrypted_key, api_key_version=key_ver
            )
            await self._db.commit()
            config = existing

        connection_ok = False
        message: str
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(f"{base_url}/models")
                connection_ok = resp.status_code == 200
                if connection_ok:
                    models = resp.json().get("data", [])
                    if models and model_name == "auto":
                        detected = models[0].get("id", "auto")
                        await self._llm.update(config.id, model_name=detected)
                        await self._db.commit()
                        model_name = detected
                    message = f"LLM at {base_url} is reachable. Model: {model_name}"
                else:
                    message = f"LLM returned HTTP {resp.status_code}"
        except Exception as exc:
            message = f"Connection test failed: {str(exc)[:200]}"

        return {
            "pod_id": pod_id,
            "llm_config_id": str(config.id),
            "llm_url": base_url,
            "model_name": model_name,
            "connection_ok": connection_ok,
            "message": message,
        }

    # ── Deploy status (Redis lookup) ─────────────────────────────────────

    async def deploy_status(self, pod_id: str) -> dict[str, Any]:
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool

        client: Redis = Redis(connection_pool=get_pool())
        try:
            raw = await client.get(f"runpod_deploy:{pod_id}:status")
            if raw is None:
                return {
                    "pod_id": pod_id,
                    "status": "unknown",
                    "message": "No deployment tracking found",
                }
            payload_str = raw if isinstance(raw, str) else raw.decode()
            parsed: dict[str, Any] = json.loads(payload_str)
            return parsed
        finally:
            await client.aclose()


# ── Helpers ───────────────────────────────────────────────────────────────


async def _probe_http(
    url: str, *, headers: dict[str, str] | None = None, label: str
) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), headers=headers or {}) as client:
            resp = await client.get(url)
            ok = resp.status_code == 200
            if ok:
                return True, f"{label} is reachable."
            return False, f"{label} returned HTTP {resp.status_code}."
    except Exception as exc:
        return False, f"Connection test failed: {str(exc)[:200]}"


def _extract_proxy_url(pod: dict[str, Any], port: int) -> str | None:
    """Derive the public RunPod proxy URL for a given container port."""
    pod_id: str = pod.get("id", "")

    runtime = pod.get("runtime") or {}
    ports: list[dict[str, Any]] = runtime.get("ports", [])
    for port_info in ports:
        if port_info.get("privatePort") == port:
            proxy_url: str | None = port_info.get("url") or port_info.get("proxyUrl")
            if proxy_url:
                return proxy_url.rstrip("/")
            break

    if pod_id:
        return f"https://{pod_id}-{port}.proxy.runpod.net"
    return None


__all__ = [
    "DuplicatePodCreateError",
    "RunPodAuthError",
    "RunPodOrchestrator",
]
