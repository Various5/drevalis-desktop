"""RunPod auto-deployment arq job function.

Jobs
----
- ``auto_deploy_runpod_pod`` -- poll a RunPod pod until RUNNING then register it.
"""

from __future__ import annotations

from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def auto_deploy_runpod_pod(
    ctx: dict[str, Any],
    pod_id: str,
    pod_type: str,
    api_key: str,
    register_port: int,
) -> dict[str, Any]:
    """Background job: poll RunPod pod until RUNNING, then auto-register.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    pod_id:
        RunPod pod ID to poll and register.
    pod_type:
        Either ``'comfyui'`` or ``'vllm'``.
    api_key:
        Plaintext RunPod API key (used for both RunPod GraphQL and as bearer
        token for the service connection test).
    register_port:
        Container port to use when constructing the RunPod proxy URL.

    Returns
    -------
    dict:
        Final status dict with ``status``, ``pod_id``, and ``service_url``.
    """
    import asyncio
    import json

    from drevalis.services.runpod import RunPodService

    log = logger.bind(pod_id=pod_id, pod_type=pod_type, job="auto_deploy_runpod_pod")

    redis_client = ctx["redis"]
    redis_key = f"runpod_deploy:{pod_id}:status"

    # Helper to persist status in Redis with a 1-hour TTL so the frontend
    # can poll GET /pods/{pod_id}/deploy-status at any point during the run.
    async def set_status(status: str, message: str, **extra: object) -> None:
        data: dict[str, Any] = {
            "pod_id": pod_id,
            "status": status,
            "message": message,
            "pod_type": pod_type,
            **extra,
        }
        await redis_client.set(redis_key, json.dumps(data), ex=3600)

    await set_status("deploying", "Pod created, waiting for startup...")
    log.info("auto_deploy_start")

    # ── Poll until pod reaches RUNNING (max 5 minutes, 10-second intervals) ──
    MAX_POLL_ATTEMPTS = 30
    POLL_INTERVAL_SECONDS = 10
    pod_running = False

    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

        try:
            async with RunPodService(api_key) as svc:
                pods = await svc.list_pods()

            pod = next((p for p in pods if p.get("id") == pod_id), None)
            if pod is None:
                await set_status("failed", f"Pod {pod_id} not found in RunPod account")
                log.error("auto_deploy_pod_not_found")
                return {"status": "failed", "message": "Pod not found"}

            pod_status = (pod.get("desiredStatus") or "").upper()
            await set_status(
                "starting",
                f"Pod status: {pod_status} (attempt {attempt}/{MAX_POLL_ATTEMPTS})",
            )
            log.debug("auto_deploy_poll", attempt=attempt, pod_status=pod_status)

            if pod_status == "RUNNING":
                pod_running = True
                break

        except Exception as exc:
            log.warning("auto_deploy_poll_error", attempt=attempt, error=str(exc))
            await set_status(
                "starting",
                f"Polling... (attempt {attempt}/{MAX_POLL_ATTEMPTS})",
            )

    if not pod_running:
        await set_status("failed", "Pod did not reach RUNNING status within 5 minutes")
        log.error("auto_deploy_timeout")
        return {"status": "failed", "message": "Timeout waiting for pod"}

    # ── Extra grace period: services need a moment to bind their ports ──
    SERVICE_INIT_WAIT_SECONDS = 15
    await set_status("registering", "Pod is running. Waiting for services to initialize...")
    log.info("auto_deploy_pod_running", waiting_seconds=SERVICE_INIT_WAIT_SECONDS)
    await asyncio.sleep(SERVICE_INIT_WAIT_SECONDS)

    # Proxy URL is always deterministic for RunPod.
    proxy_url = f"https://{pod_id}-{register_port}.proxy.runpod.net"

    session_factory = ctx["session_factory"]

    if pod_type == "comfyui":
        async with session_factory() as session:
            from drevalis.core.config import Settings
            from drevalis.repositories.comfyui import ComfyUIServerRepository

            repo = ComfyUIServerRepository(session)
            server_name = f"runpod-{pod_id}"

            # Idempotent: skip creation if a server with this URL already exists.
            existing_servers = await repo.get_all()
            existing_server = next((s for s in existing_servers if s.url == proxy_url), None)

            if existing_server is None:
                settings = Settings()
                encrypted_key, key_version = settings.encrypt(api_key)
                await repo.create(
                    name=server_name,
                    url=proxy_url,
                    api_key_encrypted=encrypted_key,
                    api_key_version=key_version,
                    max_concurrent=2,
                    is_active=True,
                )
                await session.commit()
                log.info("comfyui_server_registered", url=proxy_url)
            else:
                log.info("comfyui_server_already_registered", url=proxy_url)

        # Test connectivity — ComfyUI is typically fast to start.
        import httpx

        COMFYUI_TEST_ATTEMPTS = 3
        COMFYUI_TEST_INTERVAL_SECONDS = 5
        connection_ok = False
        for test_attempt in range(COMFYUI_TEST_ATTEMPTS):
            try:
                async with httpx.AsyncClient(
                    timeout=10.0,
                    headers={"Authorization": f"Bearer {api_key}"},
                ) as client:
                    resp = await client.get(f"{proxy_url}/system_stats")
                    if resp.status_code == 200:
                        connection_ok = True
                        break
            except Exception as exc:
                log.debug(
                    "comfyui_connection_test_failed",
                    attempt=test_attempt + 1,
                    error=str(exc),
                )
            await asyncio.sleep(COMFYUI_TEST_INTERVAL_SECONDS)

        if connection_ok:
            await set_status(
                "ready",
                f"ComfyUI registered and connected at {proxy_url}",
                registered=True,
                service_url=proxy_url,
            )
            log.info(
                "auto_deploy_complete", pod_type="comfyui", proxy_url=proxy_url, connected=True
            )
        else:
            await set_status(
                "ready",
                f"ComfyUI registered at {proxy_url} (connection test pending)",
                registered=True,
                service_url=proxy_url,
            )
            log.info(
                "auto_deploy_complete", pod_type="comfyui", proxy_url=proxy_url, connected=False
            )

    elif pod_type == "vllm":
        import httpx

        from drevalis.core.config import Settings

        Settings()
        base_url = f"{proxy_url}/v1"

        async with session_factory() as session:
            from drevalis.repositories.llm_config import LLMConfigRepository

            llm_repo = LLMConfigRepository(session)
            server_name = f"runpod-llm-{pod_id}"

            # vLLM pods are deployed without API key auth (RunPod proxy
            # strips Authorization headers anyway). Store empty key.
            encrypted_key, key_ver = "", 1  # No encryption needed for empty key

            # Idempotent: skip creation if a config with this base_url already exists.
            existing_configs = await llm_repo.get_all()
            existing_config = next((c for c in existing_configs if c.base_url == base_url), None)

            if existing_config is None:
                await llm_repo.create(
                    name=server_name,
                    base_url=base_url,
                    model_name="auto",
                    api_key_encrypted=encrypted_key,
                    api_key_version=key_ver,
                )
                await session.commit()
                log.info("llm_config_registered", url=base_url)
            else:
                log.info("llm_config_already_registered", url=base_url)

        # vLLM takes 1-3 extra minutes to load the model after the pod starts.
        # Use more attempts with longer waits between them.
        VLLM_TEST_ATTEMPTS = 6
        VLLM_TEST_INTERVAL_SECONDS = 15
        model_name = "auto"
        connection_ok = False

        for test_attempt in range(VLLM_TEST_ATTEMPTS):
            await set_status(
                "registering",
                f"Waiting for LLM to load model (attempt {test_attempt + 1}/{VLLM_TEST_ATTEMPTS})...",
            )
            try:
                async with httpx.AsyncClient(
                    timeout=15.0,
                    headers={},  # No auth needed — RunPod proxy strips auth headers
                ) as client:
                    resp = await client.get(f"{base_url}/models")
                    if resp.status_code == 200:
                        models = resp.json().get("data", [])
                        if models:
                            model_name = models[0].get("id", "auto")
                            # Persist the detected model name to the DB.
                            async with session_factory() as session:
                                llm_repo = LLMConfigRepository(session)
                                all_configs = await llm_repo.get_all()
                                target = next(
                                    (c for c in all_configs if c.base_url == base_url),
                                    None,
                                )
                                if target is not None:
                                    await llm_repo.update(target.id, model_name=model_name)
                                    await session.commit()
                        connection_ok = True
                        break
            except Exception as exc:
                log.debug(
                    "vllm_connection_test_failed",
                    attempt=test_attempt + 1,
                    error=str(exc),
                )
            await asyncio.sleep(VLLM_TEST_INTERVAL_SECONDS)

        if connection_ok:
            await set_status(
                "ready",
                f"LLM registered: {model_name} at {base_url}",
                registered=True,
                service_url=base_url,
                model_name=model_name,
            )
            log.info("auto_deploy_complete", pod_type="vllm", base_url=base_url, model=model_name)
        else:
            await set_status(
                "ready",
                f"LLM registered at {base_url} (model still loading)",
                registered=True,
                service_url=base_url,
            )
            log.info("auto_deploy_complete", pod_type="vllm", base_url=base_url, connected=False)

    else:
        await set_status("failed", f"Unknown pod_type '{pod_type}'. Expected 'comfyui' or 'vllm'.")
        log.error("auto_deploy_unknown_pod_type", pod_type=pod_type)
        return {"status": "failed", "message": f"Unknown pod_type: {pod_type}"}

    return {"status": "ready", "pod_id": pod_id, "service_url": proxy_url}
