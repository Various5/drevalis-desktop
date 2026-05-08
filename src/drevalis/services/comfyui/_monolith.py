"""ComfyUI integration service with multi-server pool and workflow injection.

Architecture:

* :class:`ComfyUIClient` -- low-level HTTP client for a single ComfyUI server.
* :class:`ComfyUIPool` -- manages multiple servers with per-server concurrency
  semaphores and a least-loaded acquisition strategy.
* :class:`ComfyUIService` -- high-level service consumed by the generation
  pipeline.  Handles workflow loading, parameter injection, prompt submission,
  polling, image downloading, and storage.
"""

from __future__ import annotations

import asyncio
import copy
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
import structlog

from drevalis.core.validators import sanitize_filename
from drevalis.schemas.comfyui import WorkflowInputMapping
from drevalis.schemas.script import SceneScript

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.services.storage import StorageBackend

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Timeout configuration for httpx calls.
_CONNECT_TIMEOUT: float = 10.0
_READ_TIMEOUT: float = 600.0  # image generation can be slow, especially on AMD ROCm
_WRITE_TIMEOUT: float = 30.0

# Polling configuration (exponential backoff).
_POLL_INITIAL_DELAY: float = 1.0
_POLL_MAX_DELAY: float = 5.0
_POLL_BACKOFF_FACTOR: float = 2.0
_POLL_MAX_TOTAL_SECONDS: float = 1200.0  # 20 min — Qwen Image at 50 steps is slow

# Fallback cap for scene-image/video parallelism when the pool's
# advertised capacity is unknown (e.g. a unit test that constructs
# ComfyUIService without registering any servers). The real production
# value is derived dynamically from registered server capacity via
# ComfyUIPool.total_capacity().
_MAX_SCENE_CONCURRENCY: int = 4

# Type alias for scene-level progress callbacks.
# Called with (message, scene_number) so the pipeline can broadcast per-scene updates.
SceneProgressCallback = Callable[[str, int], Awaitable[None]]


# ── Data structures ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    """Metadata about a single image produced by ComfyUI."""

    file_path: str  # relative to storage base
    width: int
    height: int
    seed: int
    prompt: str
    # Preserved through partial-failure gather() so callers map back to
    # the originating scene without positional indexing. None when the
    # image wasn't generated in a per-scene context (e.g. cover art).
    scene_number: int | None = None


@dataclass(frozen=True, slots=True)
class GeneratedVideo:
    """Metadata about a single video clip produced by ComfyUI."""

    file_path: str  # relative to storage base
    duration_seconds: float
    width: int
    height: int
    seed: int
    prompt: str
    scene_number: int | None = None


# ── Low-level client ───────────────────────────────────────────────────────


class ComfyUIClient:
    """HTTP client for a single ComfyUI server instance."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url: str = base_url.rstrip("/")

        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT,
                read=_READ_TIMEOUT,
                write=_WRITE_TIMEOUT,
                pool=_CONNECT_TIMEOUT,
            ),
        )

    async def close(self) -> None:
        """Gracefully close the underlying HTTP client."""
        await self._client.aclose()

    # ── API calls ──────────────────────────────────────────────────────

    async def queue_prompt(
        self,
        workflow: dict[str, Any],
        extra_data: dict[str, Any] | None = None,
    ) -> str:
        """Submit a workflow for execution.

        Returns the ``prompt_id`` assigned by ComfyUI.
        ``extra_data`` is passed alongside the prompt for hidden inputs
        like ``auth_token_comfy_org`` required by platform nodes.
        """
        payload: dict[str, Any] = {"prompt": workflow}
        if extra_data:
            payload["extra_data"] = extra_data
        logger.debug("comfyui_queue_prompt", url=self.base_url)

        # Use /api/prompt when extra_data contains platform auth (required
        # for partner nodes like ElevenLabs), otherwise use /prompt.
        endpoint = "/api/prompt" if extra_data else "/prompt"
        response = await self._client.post(endpoint, json=payload)
        if response.status_code != 200:
            body = response.text[:500]
            logger.error("comfyui_prompt_rejected", status=response.status_code, body=body)
        response.raise_for_status()

        data = response.json()
        prompt_id: str = data["prompt_id"]

        logger.info(
            "comfyui_prompt_queued",
            prompt_id=prompt_id,
            url=self.base_url,
        )
        return prompt_id

    async def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        """Retrieve execution results for *prompt_id*.

        Returns ``None`` if the prompt is still executing.
        """
        response = await self._client.get(f"/history/{prompt_id}")
        response.raise_for_status()

        data = response.json()
        if prompt_id not in data:
            return None
        result: dict[str, Any] = data[prompt_id]
        return result

    async def get_queue_status(self) -> dict[str, Any]:
        """Return the current queue length and running prompts."""
        response = await self._client.get("/queue")
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    async def download_image(
        self,
        filename: str,
        subfolder: str,
        folder_type: str,
    ) -> bytes:
        """Download a generated image from the ComfyUI server."""
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        }
        logger.debug(
            "comfyui_download_image",
            filename=filename,
            subfolder=subfolder,
        )

        response = await self._client.get("/view", params=params)
        response.raise_for_status()
        return response.content

    async def upload_image(self, image_bytes: bytes, filename: str) -> str:
        """Upload an image to ComfyUI's input folder.

        Returns the filename as stored by ComfyUI (may differ from input).
        """
        import io

        files = {"image": (filename, io.BytesIO(image_bytes), "image/png")}
        data = {"subfolder": "", "overwrite": "true"}

        response = await self._client.post("/upload/image", files=files, data=data)
        response.raise_for_status()
        result = response.json()
        uploaded_name = result.get("name", filename)
        logger.info("comfyui_image_uploaded", filename=uploaded_name)
        return str(uploaded_name)

    async def download_video(
        self,
        filename: str,
        subfolder: str,
        folder_type: str,
    ) -> bytes:
        """Download a generated video from the ComfyUI server.

        ComfyUI's ``/view`` endpoint serves both image and video files,
        so this is functionally identical to :meth:`download_image` but
        with a longer read timeout for larger video payloads.
        """
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        }
        logger.debug(
            "comfyui_download_video",
            filename=filename,
            subfolder=subfolder,
        )

        response = await self._client.get("/view", params=params)
        response.raise_for_status()
        return response.content

    async def clear_history(self, prompt_id: str | None = None) -> None:
        """Clear ComfyUI output history to free disk space on the server."""
        try:
            if prompt_id:
                await self._client.post("/history", json={"delete": [prompt_id]})
            else:
                await self._client.post("/history", json={"clear": True})
        except Exception:
            pass  # Non-fatal — cleanup is best-effort

    async def test_connection(self) -> bool:
        """Return ``True`` if the server is reachable."""
        try:
            response = await self._client.get(
                "/system_stats",
                timeout=httpx.Timeout(5.0),
            )
            return response.status_code == 200
        except (httpx.HTTPError, OSError):
            logger.warning(
                "comfyui_connection_test_failed",
                url=self.base_url,
            )
            return False


# ── Server pool ────────────────────────────────────────────────────────────


class ComfyUIPool:
    """Manages multiple ComfyUI servers with per-server concurrency limits.

    Use :meth:`acquire` as an async context manager to obtain a server
    lease — the semaphore is released automatically on exit.
    """

    def __init__(self) -> None:
        # Maps server_id -> (client, semaphore)
        self._servers: dict[UUID, tuple[ComfyUIClient, asyncio.Semaphore]] = {}
        # Mirror of registered max_concurrent so total_capacity() works
        # without poking at semaphore internals.
        self._capacity: dict[UUID, int] = {}

    def register_server(
        self,
        server_id: UUID,
        client: ComfyUIClient,
        max_concurrent: int,
    ) -> None:
        """Register a ComfyUI server in the pool."""
        self._servers[server_id] = (client, asyncio.Semaphore(max_concurrent))
        self._capacity[server_id] = max_concurrent
        logger.info(
            "comfyui_server_registered",
            server_id=str(server_id),
            base_url=client.base_url,
            max_concurrent=max_concurrent,
        )

    def unregister_server(self, server_id: UUID) -> None:
        """Remove a server from the pool."""
        self._servers.pop(server_id, None)
        self._capacity.pop(server_id, None)
        logger.info("comfyui_server_unregistered", server_id=str(server_id))

    def total_capacity(self) -> int:
        """Return the sum of registered server capacities.

        Returns ``_MAX_SCENE_CONCURRENCY`` when the pool is empty so
        callers (scene gen) don't divide-by-zero on an unconfigured
        install — they just won't actually run, the per-server
        semaphore acquire fails first.
        """
        return sum(self._capacity.values()) or _MAX_SCENE_CONCURRENCY

    async def sync_from_db(self, session: AsyncSession) -> None:
        """Re-sync the pool with currently active ComfyUI servers from the DB.

        Removes deactivated servers, replaces servers whose URL or concurrency
        changed, and registers new ones.  Called before each pipeline run so
        the pool always reflects the current database state.
        """
        from drevalis.repositories.comfyui import ComfyUIServerRepository

        repo = ComfyUIServerRepository(session)
        active_servers = await repo.get_active_servers()
        active_ids = {srv.id for srv in active_servers}

        # Remove servers that are no longer active
        stale_ids = set(self._servers.keys()) - active_ids
        for sid in stale_ids:
            old_client, _ = self._servers.pop(sid)
            self._capacity.pop(sid, None)
            await old_client.close()
            logger.info("comfyui_pool_removed_stale_server", server_id=str(sid))

        # Register new servers and replace existing ones whose config changed
        for srv in active_servers:
            if srv.id in self._servers:
                existing_client, existing_sem = self._servers[srv.id]
                # Check if URL or concurrency changed — if so, replace
                if existing_client.base_url != srv.url.rstrip("/"):
                    logger.info(
                        "comfyui_pool_replacing_server",
                        server_id=str(srv.id),
                        old_url=existing_client.base_url[:40],
                        new_url=srv.url[:40],
                    )
                    await existing_client.close()
                    client = ComfyUIClient(base_url=srv.url, api_key=None)
                    self._servers[srv.id] = (client, asyncio.Semaphore(srv.max_concurrent))
                    self._capacity[srv.id] = srv.max_concurrent
            else:
                client = ComfyUIClient(base_url=srv.url, api_key=None)
                self._servers[srv.id] = (client, asyncio.Semaphore(srv.max_concurrent))
                self._capacity[srv.id] = srv.max_concurrent
                logger.info(
                    "comfyui_pool_added_server",
                    server_id=str(srv.id),
                    name=srv.name,
                    url=srv.url[:40],
                )

        logger.info("comfyui_pool_synced", active_count=len(self._servers))

    @asynccontextmanager
    async def acquire(
        self,
        server_id: UUID | None = None,
    ) -> AsyncIterator[tuple[UUID, ComfyUIClient]]:
        """Acquire a server lease.

        If *server_id* is ``None``, servers are tried in round-robin order.
        Unhealthy servers are automatically skipped and removed from the
        pool so subsequent calls don't waste time on them.

        Yields ``(server_id, client)`` and releases the semaphore on exit.
        """
        if not self._servers:
            raise RuntimeError("No ComfyUI servers registered in the pool.")

        if server_id is not None:
            if server_id not in self._servers:
                raise KeyError(f"ComfyUI server {server_id} is not registered.")
            candidates = [server_id]
        else:
            # Round-robin starting point, then try all remaining servers.
            # ``itertools.count`` is atomic across concurrent awaits —
            # the previous read-modify-write on ``self._rr_index`` could
            # race under asyncio.gather.
            import itertools as _itertools

            server_ids = list(self._servers.keys())
            if not hasattr(self, "_rr_counter"):
                self._rr_counter = _itertools.count()
            start = (next(self._rr_counter) % len(server_ids)) if server_ids else 0
            candidates = server_ids[start:] + server_ids[:start]

        # Drop any server still in its cool-down window — they'll be
        # re-eligible automatically once the timestamp passes. Callers
        # that explicitly pinned a ``server_id`` always get that server,
        # regardless of cool-down (so the user can force-retry).
        import time as _time

        _cd_map = getattr(self, "_cooldown", {})
        if server_id is None and _cd_map:
            now = _time.monotonic()
            live_candidates = [c for c in candidates if _cd_map.get(c, 0) <= now]
            # Drop keys that have expired so the dict doesn't grow
            # without bound.
            for sid, exp in list(_cd_map.items()):
                if exp <= now:
                    _cd_map.pop(sid, None)
            candidates = (
                live_candidates or candidates
            )  # if every server is cooled down, try them anyway

        last_error: Exception | None = None
        for chosen_id in candidates:
            if chosen_id not in self._servers:
                continue
            client, semaphore = self._servers[chosen_id]

            logger.debug(
                "comfyui_acquiring_server",
                server_id=str(chosen_id),
            )
            await semaphore.acquire()

            # Verify the server is responsive before handing the lease to
            # the caller. A brief timeout / 5xx puts the server in a
            # short cool-down instead of permanently dropping it — a 1s
            # hiccup used to evict the server until the whole worker
            # restarted (audit: P1 resilience). Servers that keep failing
            # stay cooled down; healthy next-time pings clear the mark.
            try:
                await asyncio.wait_for(client.get_queue_status(), timeout=5.0)
            except Exception as ping_exc:
                semaphore.release()
                last_error = ping_exc
                if not hasattr(self, "_cooldown"):
                    self._cooldown = {}
                import time as _time

                self._cooldown[chosen_id] = _time.monotonic() + 60.0
                logger.warning(
                    "comfyui_server_unhealthy_cooldown",
                    server_id=str(chosen_id),
                    server_url=client.base_url[:60],
                    error=str(ping_exc)[:120],
                    cooldown_seconds=60,
                    remaining_candidates=len(candidates) - candidates.index(chosen_id) - 1,
                )
                continue

            try:
                yield chosen_id, client
            finally:
                semaphore.release()
                logger.debug(
                    "comfyui_server_released",
                    server_id=str(chosen_id),
                )
            return  # Successfully yielded — done

        # All candidates failed
        raise RuntimeError(f"All ComfyUI servers failed health checks. Last error: {last_error}")

    async def close_all(self) -> None:
        """Close all registered clients."""
        for _, (client, _) in self._servers.items():
            await client.close()
        self._servers.clear()


# ── High-level service ─────────────────────────────────────────────────────


class ComfyUIService:
    """Orchestrates image generation through ComfyUI.

    Loads workflow JSON from disk, injects dynamic parameters, submits to
    a server from the pool, polls for completion, downloads the result,
    and persists it via the storage backend.
    """

    def __init__(self, pool: ComfyUIPool, storage: StorageBackend) -> None:
        self._pool = pool
        self._storage = storage

    # ── workflow helpers ────────────────────────────────────────────────

    @staticmethod
    def inject_params(
        workflow: dict[str, Any],
        mappings: WorkflowInputMapping,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        seed: int,
        *,
        character_ref_image: str | None = None,
        style_ref_image: str | None = None,
        character_lora: str | None = None,
        style_lora: str | None = None,
        character_strength: float | None = None,
        style_strength: float | None = None,
    ) -> dict[str, Any]:
        """Inject dynamic parameters into a ComfyUI API-format workflow.

        Returns a **new** dict — the original is not mutated.

        Phase-E locks (character / style reference images + LoRAs +
        strengths) are only injected when the workflow declares a
        matching ``sf_field`` in its ``input_mappings``; workflows that
        don't advertise a slot for them are silently left alone.
        """
        wf = copy.deepcopy(workflow)

        value_map: dict[str, str | int | float] = {
            "visual_prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "seed": seed,
        }
        # Only expose Phase-E keys when the caller actually supplied a value —
        # otherwise the workflow would overwrite a meaningful default with
        # None/empty and drop the lock entirely.
        if character_ref_image:
            value_map["character_ref_image"] = character_ref_image
        if style_ref_image:
            value_map["style_ref_image"] = style_ref_image
        if character_lora:
            value_map["character_lora"] = character_lora
        if style_lora:
            value_map["style_lora"] = style_lora
        if character_strength is not None:
            value_map["character_strength"] = float(character_strength)
        if style_strength is not None:
            value_map["style_strength"] = float(style_strength)

        for mapping in mappings.mappings:
            if mapping.sf_field not in value_map:
                logger.warning(
                    "comfyui_unknown_mapping_field",
                    sf_field=mapping.sf_field,
                )
                continue

            node_id = mapping.node_id
            field_name = mapping.field_name

            if node_id not in wf:
                logger.warning(
                    "comfyui_node_not_found",
                    node_id=node_id,
                    sf_field=mapping.sf_field,
                )
                continue

            node = wf[node_id]
            if "inputs" not in node:
                node["inputs"] = {}

            node["inputs"][field_name] = value_map[mapping.sf_field]
            logger.debug(
                "comfyui_param_injected",
                node_id=node_id,
                field=field_name,
                sf_field=mapping.sf_field,
            )

        return wf

    async def _load_workflow(self, workflow_path: str) -> dict[str, Any]:
        """Load a workflow JSON file from storage."""
        raw = await self._storage.read_file(workflow_path)
        workflow: dict[str, Any] = json.loads(raw)
        return workflow

    async def _poll_until_complete(
        self,
        client: ComfyUIClient,
        prompt_id: str,
        *,
        on_poll: Callable[[float, int], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Poll ``/history`` with exponential backoff until the prompt finishes.

        If *on_poll* is provided, it is called on each poll iteration with
        ``(elapsed_seconds, poll_count)`` for fine-grained progress reporting.

        Returns the history entry for *prompt_id*.

        Raises :class:`TimeoutError` if the total wait exceeds
        ``_POLL_MAX_TOTAL_SECONDS``.
        """
        delay = _POLL_INITIAL_DELAY
        elapsed = 0.0
        attempt = 0

        while elapsed < _POLL_MAX_TOTAL_SECONDS:
            result = await client.get_history(prompt_id)
            if result is not None:
                logger.info(
                    "comfyui_prompt_complete",
                    prompt_id=prompt_id,
                    elapsed_seconds=round(elapsed, 1),
                )
                return result

            attempt += 1
            if on_poll is not None:
                try:
                    await on_poll(elapsed, attempt)
                except Exception:
                    logger.debug("on_poll_callback_error", exc_info=True)

            logger.debug(
                "comfyui_poll_waiting",
                prompt_id=prompt_id,
                delay=delay,
                elapsed=round(elapsed, 1),
            )
            await asyncio.sleep(delay)
            elapsed += delay
            delay = min(delay * _POLL_BACKOFF_FACTOR, _POLL_MAX_DELAY)

        raise TimeoutError(
            f"ComfyUI prompt {prompt_id} did not complete within {_POLL_MAX_TOTAL_SECONDS}s."
        )

    def _extract_output_images(
        self,
        history: dict[str, Any],
        output_node_id: str,
        output_field_name: str,
    ) -> list[dict[str, Any]]:
        """Pull output metadata dicts from the history entry.

        Works for both image and video outputs.  ComfyUI stores image
        results under the ``"images"`` key and video results under the
        ``"videos"`` key within a node's output dict.

        Lookup order for the target node:
        1. ``node_output[output_field_name]``
        2. ``node_output["videos"]``  (video workflow fallback)
        3. ``node_output["images"]``  (image workflow fallback)
        4. Scan ALL output nodes for any list of dicts with a ``"filename"`` key.

        Each returned item has keys: ``filename``, ``subfolder``, ``type``.
        """
        outputs = history.get("outputs", {})
        logger.debug(
            "comfyui_extract_outputs",
            output_keys=list(outputs.keys()),
            target_node=output_node_id,
            target_field=output_field_name,
            full_outputs={k: list(v.keys()) for k, v in outputs.items()},
        )
        node_output = outputs.get(output_node_id, {})

        # Step 1: try the explicitly configured field name
        result: list[dict[str, Any]] = node_output.get(output_field_name, [])

        # Step 2: try "videos" key (for video workflow nodes)
        if not result:
            result = node_output.get("videos", [])

        # Step 3: try "images" key (for image workflow nodes)
        if not result:
            result = node_output.get("images", [])

        # Step 4: scan ALL output nodes for any list of dicts with "filename"
        if not result:
            for nid, nout in outputs.items():
                for field, val in nout.items():
                    if (
                        isinstance(val, list)
                        and val
                        and isinstance(val[0], dict)
                        and "filename" in val[0]
                    ):
                        logger.info(
                            "comfyui_found_output_on_different_node",
                            node_id=nid,
                            field=field,
                            count=len(val),
                        )
                        return val
        return result

    # ── public API ─────────────────────────────────────────────────────

    async def generate_image(
        self,
        server_id: UUID | None,
        workflow_path: str,
        input_mappings: WorkflowInputMapping,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1080,
        height: int = 1920,
        seed: int | None = None,
        *,
        save_relative_dir: str = "",
        character_ref_image: str | None = None,
        style_ref_image: str | None = None,
        character_lora: str | None = None,
        style_lora: str | None = None,
        character_strength: float | None = None,
        style_strength: float | None = None,
    ) -> GeneratedImage:
        """Generate a single image end-to-end.

        Steps:
        1. Load workflow JSON from disk.
        2. Inject parameters (prompt, seed, dimensions).
        3. Submit to ComfyUI and poll until complete.
        4. Download the resulting image.
        5. Persist via the storage backend.

        Returns a :class:`GeneratedImage` with the relative storage path.
        """
        if seed is None:
            seed = random.randint(0, 2**31 - 1)  # ComfyUI max is 2147483647

        workflow = await self._load_workflow(workflow_path)
        injected = self.inject_params(
            workflow,
            input_mappings,
            prompt,
            negative_prompt,
            width,
            height,
            seed,
            character_ref_image=character_ref_image,
            style_ref_image=style_ref_image,
            character_lora=character_lora,
            style_lora=style_lora,
            character_strength=character_strength,
            style_strength=style_strength,
        )

        async with self._pool.acquire(server_id) as (sid, client):
            prompt_id = await client.queue_prompt(injected)
            history = await self._poll_until_complete(client, prompt_id)

            # Extract output image metadata
            image_metas = self._extract_output_images(
                history,
                input_mappings.output_node_id,
                input_mappings.output_field_name,
            )

            if not image_metas:
                raise RuntimeError(
                    f"ComfyUI prompt {prompt_id} produced no output images "
                    f"on node {input_mappings.output_node_id}."
                )

            # Download the first output image
            img_meta = image_metas[0]
            image_bytes = await client.download_image(
                filename=img_meta["filename"],
                subfolder=img_meta.get("subfolder", ""),
                folder_type=img_meta.get("type", "output"),
            )

        # Sanitize the filename from the ComfyUI response to prevent
        # path traversal or overwriting arbitrary files within storage.
        safe_filename = sanitize_filename(img_meta["filename"])
        # Use a UUID-based name to avoid collisions and eliminate any
        # residual risk from attacker-chosen filenames.
        import uuid as _uuid

        ext = Path(safe_filename).suffix or ".png"
        safe_filename = f"{_uuid.uuid4().hex}{ext}"

        # Persist to storage
        if save_relative_dir:
            relative_path = f"{save_relative_dir}/{safe_filename}"
        else:
            relative_path = safe_filename

        await self._storage.save_file(relative_path, image_bytes)

        logger.info(
            "image_generated",
            relative_path=relative_path,
            width=width,
            height=height,
            seed=seed,
        )

        return GeneratedImage(
            file_path=relative_path,
            width=width,
            height=height,
            seed=seed,
            prompt=prompt,
        )

    # ── Quality boost constants ────────────────────────────────────────

    # Kept for backward-compatibility with any external code that still reads
    # QUALITY_SUFFIX directly.  Internal prompt building now uses QUALITY_SUFFIXES.
    QUALITY_SUFFIX: str = "highly detailed, cinematic lighting, sharp focus, professional quality"

    # Per-genre quality suffixes.  The pipeline matches series.visual_style
    # against these keys (substring, case-insensitive) and picks the first
    # match; "default" is the fallback.
    QUALITY_SUFFIXES: dict[str, str] = {
        "anime": (
            "anime key visual, studio lighting, cel shaded, vibrant colors, detailed linework"
        ),
        "photorealistic": (
            "8K photorealistic, cinematic lighting, sharp focus, ultra detailed, DSLR quality"
        ),
        "oil_painting": (
            "masterful oil painting, rich textures, gallery quality, dramatic brushwork, fine art"
        ),
        "3d_render": (
            "octane render, ray traced, volumetric lighting, 8K, physically based materials"
        ),
        "watercolor": (
            "delicate watercolor wash, soft edges, luminous transparency, artistic composition"
        ),
        "default": ("highly detailed, cinematic lighting, sharp focus, professional quality"),
    }

    CAMERA_ANGLES: list[str] = [
        "wide establishing shot",
        "close-up detail shot",
        "medium shot",
        "low angle dramatic shot",
        "overhead birds-eye view",
        "dutch angle dynamic composition",
        "over-the-shoulder perspective",
        "extreme close-up macro shot",
        # Extended set (16 total)
        "tracking shot following motion",
        "profile silhouette shot",
        "worm's-eye upward view",
        "symmetrical centered composition",
        "rule-of-thirds off-center framing",
        "tight crop emotional portrait",
        "panoramic wide landscape",
        "canted angle tension shot",
    ]

    VARIETY_TOKENS: list[str] = [
        "dramatic lighting, deep shadows",
        "soft golden hour lighting, warm tones",
        "high contrast, vivid colors",
        "moody atmospheric lighting, cool tones",
        "bright and clean, professional look",
        "cinematic depth of field, bokeh background",
        # Extended set (12 total)
        "volumetric lighting, god rays through atmosphere",
        "neon-lit cyberpunk aesthetic, electric glow",
        "muted desaturated palette, film grain texture",
        "high-key bright ethereal glow, dreamy",
        "chiaroscuro dramatic contrast, Renaissance style",
        "twilight blue hour ambiance, serene dusk",
    ]

    DEFAULT_NEGATIVE: str = (
        "blurry, low quality, watermark, text, deformed, bad anatomy, "
        "jpeg artifacts, cropped, worst quality, low resolution, "
        "oversaturated, ugly, duplicate, morbid, mutilated, "
        "out of frame, poorly drawn, bad proportions, "
        "multiple people, two people, duplicate figure, clone, twin, "
        "split image, two bodies"
    )

    @staticmethod
    def _resolve_quality_suffix(visual_style: str, suffixes: dict[str, str]) -> str:
        """Return the best-matching quality suffix for *visual_style*.

        Iterates over *suffixes* keys in insertion order and returns the value
        for the first key found as a case-insensitive substring of
        *visual_style*.  Falls back to ``suffixes["default"]`` when no key
        matches.

        Args:
            visual_style: The series visual style string (may be empty).
            suffixes: Mapping of style key → quality suffix string.

        Returns:
            The matching quality suffix string.
        """
        if visual_style:
            lower = visual_style.lower()
            for key, value in suffixes.items():
                if key != "default" and key in lower:
                    return value
        return suffixes.get("default", "highly detailed, cinematic lighting, sharp focus")

    async def generate_scene_images(
        self,
        server_id: UUID | None,
        workflow_path: str,
        input_mappings: WorkflowInputMapping,
        scenes: list[SceneScript],
        visual_style: str,
        character_description: str,
        episode_id: UUID,
        negative_prompt: str | None = None,
        progress_callback: SceneProgressCallback | None = None,
        base_seed: int | None = None,
        *,
        reference_asset_paths: list[str] | None = None,
        character_lock: dict[str, Any] | None = None,
        style_lock: dict[str, Any] | None = None,
        character_lock_paths: list[str] | None = None,
        style_lock_paths: list[str] | None = None,
    ) -> list[GeneratedImage]:
        """Generate images for all scenes in an episode.

        Runs up to ``ComfyUIPool.total_capacity()`` concurrent generation
        tasks (sum of per-server max_concurrent).  Each scene's ``visual_prompt`` is prefixed with the
        *visual_style* and *character_description* for consistency.
        A quality suffix is automatically appended to every positive prompt,
        and a default negative prompt is used unless overridden via
        *negative_prompt*.

        Camera angle and variety token are selected with a seeded
        ``random.Random`` instance (seed = ``scene_number + base_seed``) so
        that repeated runs with the same seed produce identical prompt
        decoration while still distributing variety across scenes.

        If *progress_callback* is provided, it is called before and after
        each scene generation with ``(message, scene_number)`` for
        fine-grained progress reporting.

        Images are saved to
        ``episodes/{episode_id}/scenes/scene_{NNN}.png``.
        """
        # Ensure the episode directory tree exists.
        await self._storage.ensure_episode_dirs(episode_id)
        save_dir = f"episodes/{episode_id}/scenes"

        # Resolve negative prompt: caller override > default.
        effective_negative = (
            negative_prompt if negative_prompt is not None else self.DEFAULT_NEGATIVE
        )

        # Resolve quality suffix once per call — it depends only on visual_style.
        quality = self._resolve_quality_suffix(visual_style, self.QUALITY_SUFFIXES)

        # Phase E: the character / style reference images and LoRAs are
        # threaded into each ``generate_image`` call below. They land on
        # the workflow via ``inject_params`` through the matching
        # ``sf_field`` entries (character_ref_image / style_ref_image /
        # character_lora / style_lora / character_strength /
        # style_strength). Workflows without those mappings silently
        # ignore the values.
        if character_lock_paths or style_lock_paths:
            logger.info(
                "comfyui_locks_active",
                character_refs=len(character_lock_paths or []),
                style_refs=len(style_lock_paths or []),
                character_strength=(character_lock or {}).get("strength"),
                style_strength=(style_lock or {}).get("strength"),
                character_lora=(character_lock or {}).get("lora"),
                style_lora=(style_lock or {}).get("lora"),
            )

        # Outer cap = total registered server capacity; per-server
        # semaphores still bound each individual server's GPU slots,
        # so this only governs the asyncio.gather fan-out width.
        semaphore = asyncio.Semaphore(self._pool.total_capacity())

        async def _gen_one(scene: SceneScript) -> GeneratedImage:
            # Scene description FIRST so the main subject is prioritized by
            # the diffusion model, avoiding doubled characters when the
            # character description was previously placed before the scene.
            full_prompt_parts: list[str] = []
            # Phase C: per-scene style override prepended so it dominates.
            scene_style = getattr(scene, "style_override", None)
            if scene_style:
                full_prompt_parts.append(scene_style)
            full_prompt_parts.append(scene.visual_prompt)
            # Use a seeded RNG so angle/variety are deterministic per scene but
            # distributed across the full expanded pools rather than round-robin.
            # Per-scene ``seed`` override wins over base_seed when provided.
            scene_seed_override = getattr(scene, "seed", None)
            rng_seed = (
                scene_seed_override
                if scene_seed_override is not None
                else (scene.scene_number + (base_seed or 42))
            )
            rng = random.Random(rng_seed)
            angle = rng.choice(self.CAMERA_ANGLES)
            # Camera angle goes right after the scene style prefix when
            # one is set; otherwise at the very front so the angle is the
            # first thing the diffusion model sees.
            full_prompt_parts.insert(1 if scene_style else 0, angle)
            if character_description:
                full_prompt_parts.append(f"featuring {character_description}")
            else:
                # No character defined — reinforce cinematic composition so the
                # diffusion model doesn't fall back to injecting a generic figure.
                full_prompt_parts.append(
                    "cinematic composition, dramatic lighting, professional photography, "
                    "8k ultra HD, masterful detail"
                )
            if visual_style:
                full_prompt_parts.append(visual_style)
            full_prompt_parts.append(quality)
            # Add per-scene lighting/mood variety via the same seeded RNG.
            variety = rng.choice(self.VARIETY_TOKENS)
            full_prompt_parts.append(variety)
            full_prompt = ", ".join(full_prompt_parts)

            # Phase C: per-scene negative prompt override.
            scene_negative = getattr(scene, "negative_prompt_override", None)
            scene_effective_negative = scene_negative if scene_negative else effective_negative

            async with semaphore:
                # Broadcast: starting this scene
                if progress_callback:
                    await progress_callback(
                        f"Scene {scene.scene_number}/{len(scenes)}: generating image...",
                        scene.scene_number,
                    )

                logger.info(
                    "scene_image_generation_start",
                    episode_id=str(episode_id),
                    scene_number=scene.scene_number,
                    per_scene_override=bool(scene_style or scene_negative or scene_seed_override),
                )
                result = await self.generate_image(
                    server_id=server_id,
                    workflow_path=workflow_path,
                    input_mappings=input_mappings,
                    prompt=full_prompt,
                    negative_prompt=scene_effective_negative,
                    width=1080,
                    height=1920,
                    save_relative_dir=save_dir,
                    # Phase-E locks — first ref image wins for simplicity;
                    # multi-ref blending is a workflow-level concern.
                    character_ref_image=character_lock_paths[0] if character_lock_paths else None,
                    style_ref_image=style_lock_paths[0] if style_lock_paths else None,
                    character_lora=(character_lock or {}).get("lora"),
                    style_lora=(style_lock or {}).get("lora"),
                    character_strength=(character_lock or {}).get("strength"),
                    style_strength=(style_lock or {}).get("strength"),
                )

                # Broadcast: scene done
                if progress_callback:
                    await progress_callback(
                        f"Scene {scene.scene_number}/{len(scenes)}: image complete",
                        scene.scene_number,
                    )

                # Stamp the scene identity so the caller can map successes
                # back to their scene after partial-failure filtering.
                return replace(result, scene_number=scene.scene_number)

        tasks = [asyncio.create_task(_gen_one(scene)) for scene in scenes]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate successful results from failures so a single bad scene does
        # not cancel all in-flight work.
        generated: list[GeneratedImage] = []
        failures: list[tuple[int, BaseException]] = []
        for i, result in enumerate(raw_results):
            if isinstance(result, BaseException):
                failures.append((i, result))
                logger.warning(
                    "scene_generation_failed",
                    scene_index=i,
                    error=str(result)[:100],
                )
            else:
                generated.append(result)

        if failures and not generated:
            # Every scene failed — re-raise the first exception so the pipeline
            # marks the step as failed rather than silently producing no output.
            raise failures[0][1]

        if failures:
            logger.warning(
                "scene_generation_partial",
                succeeded=len(generated),
                failed=len(failures),
            )

        logger.info(
            "scene_images_generation_complete",
            episode_id=str(episode_id),
            count=len(generated),
        )
        return generated

    # ── Video generation ──────────────────────────────────────────────

    async def generate_video(
        self,
        server_id: UUID | None,
        workflow_path: str,
        input_mappings: WorkflowInputMapping,
        prompt: str,
        negative_prompt: str = "",
        seed: int | None = None,
        *,
        save_relative_dir: str = "",
    ) -> GeneratedVideo:
        """Generate a single video clip end-to-end via ComfyUI.

        Steps:
        1. Load workflow JSON from disk.
        2. Inject prompt, negative_prompt, and seed (no width/height --
           video workflows embed their own resolution via the ``size`` field).
        3. Submit to ComfyUI and poll until complete.
        4. Download the resulting video.
        5. Persist via the storage backend.

        Returns a :class:`GeneratedVideo` with the relative storage path.
        """
        import uuid as _uuid

        if seed is None:
            seed = random.randint(0, 2**31 - 1)

        workflow = await self._load_workflow(workflow_path)

        # For video workflows we inject only prompt, negative_prompt, and seed.
        # Width/height are encoded in the workflow's "size" field (e.g. "1080p: 9:16").
        injected = copy.deepcopy(workflow)
        value_map: dict[str, str | int] = {
            "visual_prompt": prompt,
            "negative_prompt": negative_prompt,
            "seed": seed,
        }

        for mapping in input_mappings.mappings:
            val = value_map.get(mapping.sf_field)
            if val is not None and mapping.node_id in injected:
                if "inputs" not in injected[mapping.node_id]:
                    injected[mapping.node_id]["inputs"] = {}
                injected[mapping.node_id]["inputs"][mapping.field_name] = val
                logger.debug(
                    "comfyui_video_param_injected",
                    node_id=mapping.node_id,
                    field=mapping.field_name,
                    sf_field=mapping.sf_field,
                )

        async with self._pool.acquire(server_id) as (sid, client):
            prompt_id = await client.queue_prompt(injected)
            history = await self._poll_until_complete(client, prompt_id)

            output_metas = self._extract_output_images(
                history,
                input_mappings.output_node_id,
                input_mappings.output_field_name,
            )

            if not output_metas:
                raise RuntimeError(
                    f"ComfyUI prompt {prompt_id} produced no video output "
                    f"on node {input_mappings.output_node_id}."
                )

            meta = output_metas[0]
            video_bytes = await client.download_video(
                filename=meta["filename"],
                subfolder=meta.get("subfolder", ""),
                folder_type=meta.get("type", "output"),
            )

        # Persist to storage with a UUID-based filename
        safe_filename = f"{_uuid.uuid4().hex}.mp4"
        relative_path = (
            f"{save_relative_dir}/{safe_filename}" if save_relative_dir else safe_filename
        )
        await self._storage.save_file(relative_path, video_bytes)

        logger.info(
            "video_generated",
            relative_path=relative_path,
            seed=seed,
            prompt_length=len(prompt),
        )

        return GeneratedVideo(
            file_path=relative_path,
            duration_seconds=5.0,  # Wan 2.6 default clip length
            width=1080,
            height=1920,
            seed=seed,
            prompt=prompt,
        )

    async def generate_scene_videos(
        self,
        server_id: UUID | None,
        workflow_path: str,
        input_mappings: WorkflowInputMapping,
        scenes: list[SceneScript],
        visual_style: str,
        character_description: str,
        episode_id: UUID,
        negative_prompt: str | None = None,
        *,
        image_workflow_path: str | None = None,
        image_input_mappings: WorkflowInputMapping | None = None,
        progress_callback: SceneProgressCallback | None = None,
        base_seed: int | None = None,
        motion_reference_paths_by_scene: dict[int, str] | None = None,
    ) -> list[GeneratedVideo]:
        """Generate video clips for all scenes in an episode.

        Two modes:
        - **Direct text-to-video**: If the workflow is a pure t2v workflow,
          submits prompt directly.
        - **Image-to-video** (default if image_workflow_path is set): First
          generates a static image per scene, uploads it to ComfyUI, then
          runs the i2v workflow to animate it.  Produces much better results.

        Camera angle and variety token are selected with a seeded
        ``random.Random`` instance (seed = ``scene_number + base_seed``) for
        deterministic prompt decoration that is still distributed across the
        full expanded pools.

        If *progress_callback* is provided, it is called before and after
        each scene generation with ``(message, scene_number)``.

        Videos are saved to ``episodes/{episode_id}/scenes/``.
        """
        await self._storage.ensure_episode_dirs(episode_id)
        save_dir = f"episodes/{episode_id}/scenes"

        effective_negative = (
            negative_prompt if negative_prompt is not None else self.DEFAULT_NEGATIVE
        )

        # Resolve quality suffix once per call.
        quality = self._resolve_quality_suffix(visual_style, self.QUALITY_SUFFIXES)

        # Outer cap = total registered server capacity; per-server
        # semaphores still bound each individual server's GPU slots,
        # so this only governs the asyncio.gather fan-out width.
        semaphore = asyncio.Semaphore(self._pool.total_capacity())

        async def _build_prompt(scene: SceneScript) -> str:
            prompt_parts: list[str] = [scene.visual_prompt]
            # Use a seeded RNG for deterministic but varied angle/token selection.
            rng = random.Random(scene.scene_number + (base_seed or 42))
            angle = rng.choice(self.CAMERA_ANGLES)
            prompt_parts.insert(1, angle)
            if character_description:
                prompt_parts.append(f"featuring {character_description}")
            else:
                # No character defined — reinforce cinematic composition so the
                # diffusion model doesn't fall back to injecting a generic figure.
                prompt_parts.append(
                    "cinematic composition, dramatic lighting, professional photography, "
                    "8k ultra HD, masterful detail"
                )
            if visual_style:
                prompt_parts.append(visual_style)
            prompt_parts.append(quality)
            # Add per-scene lighting/mood variety via the same seeded RNG.
            variety = rng.choice(self.VARIETY_TOKENS)
            prompt_parts.append(variety)
            return ", ".join(prompt_parts)

        async def _gen_one(scene: SceneScript) -> GeneratedVideo:
            full_prompt = await _build_prompt(scene)

            async with semaphore:
                # Broadcast: starting this scene
                if progress_callback:
                    await progress_callback(
                        f"Scene {scene.scene_number}/{len(scenes)}: generating video...",
                        scene.scene_number,
                    )

                logger.info(
                    "scene_video_generation_start",
                    episode_id=str(episode_id),
                    scene_number=scene.scene_number,
                )

                # If we have an image workflow, do two-stage: image → upload → i2v
                if image_workflow_path and image_input_mappings:
                    # Stage 1: Generate a static image
                    if progress_callback:
                        await progress_callback(
                            f"Scene {scene.scene_number}/{len(scenes)}: generating reference image...",
                            scene.scene_number,
                        )
                    logger.info("scene_video_stage1_image", scene_number=scene.scene_number)
                    img = await self.generate_image(
                        server_id=server_id,
                        workflow_path=image_workflow_path,
                        input_mappings=image_input_mappings,
                        prompt=full_prompt,
                        negative_prompt=effective_negative,
                        save_relative_dir=save_dir,
                    )

                    # Stage 2: Upload image to ComfyUI and run i2v workflow
                    if progress_callback:
                        await progress_callback(
                            f"Scene {scene.scene_number}/{len(scenes)}: animating image to video...",
                            scene.scene_number,
                        )
                    logger.info("scene_video_stage2_animate", scene_number=scene.scene_number)
                    img_abs_path = self._storage.resolve_path(img.file_path)
                    img_bytes = img_abs_path.read_bytes()

                    async with self._pool.acquire(server_id) as (sid, client):
                        uploaded_name = await client.upload_image(
                            img_bytes, f"scene_{scene.scene_number}_{episode_id}.png"
                        )

                        # Load and inject the i2v workflow
                        workflow = await self._load_workflow(workflow_path)
                        injected = copy.deepcopy(workflow)

                        # Inject prompt and seed
                        for mapping in input_mappings.mappings:
                            value_map = {
                                "visual_prompt": full_prompt
                                + ", cinematic motion, smooth camera movement",
                                "negative_prompt": effective_negative,
                                "seed": random.randint(0, 2**31 - 1),
                            }
                            val = value_map.get(mapping.sf_field)
                            if val is not None and mapping.node_id in injected:
                                injected[mapping.node_id]["inputs"][mapping.field_name] = val

                        # Inject uploaded image filename into LoadImage node
                        for node_id, node in injected.items():
                            if node.get("class_type") == "LoadImage":
                                node["inputs"]["image"] = uploaded_name
                                break

                        # Submit and poll
                        prompt_id = await client.queue_prompt(injected)
                        history = await self._poll_until_complete(client, prompt_id)

                        output_metas = self._extract_output_images(
                            history,
                            input_mappings.output_node_id,
                            input_mappings.output_field_name,
                        )
                        if not output_metas:
                            raise RuntimeError(
                                f"ComfyUI i2v prompt {prompt_id} produced no video output"
                            )

                        meta = output_metas[0]
                        video_bytes = await client.download_video(
                            filename=meta["filename"],
                            subfolder=meta.get("subfolder", ""),
                            folder_type=meta.get("type", "output"),
                        )

                    # Save video
                    import uuid as _uuid

                    safe_filename = f"{_uuid.uuid4().hex}.mp4"
                    relative_path = f"{save_dir}/{safe_filename}"
                    abs_path = self._storage.resolve_path(relative_path)
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_bytes(video_bytes)

                    video_result = GeneratedVideo(
                        file_path=relative_path,
                        duration_seconds=3.4,
                        width=704,
                        height=1280,
                        seed=0,
                        prompt=full_prompt,
                        scene_number=scene.scene_number,
                    )

                    # Broadcast: scene video done
                    if progress_callback:
                        await progress_callback(
                            f"Scene {scene.scene_number}/{len(scenes)}: video complete",
                            scene.scene_number,
                        )

                    return video_result

                else:
                    # Direct text-to-video (e.g. Wan API nodes)
                    result = await self.generate_video(
                        server_id=server_id,
                        workflow_path=workflow_path,
                        input_mappings=input_mappings,
                        prompt=full_prompt,
                        negative_prompt=effective_negative,
                        save_relative_dir=save_dir,
                    )

                    # Broadcast: scene video done
                    if progress_callback:
                        await progress_callback(
                            f"Scene {scene.scene_number}/{len(scenes)}: video complete",
                            scene.scene_number,
                        )

                    return replace(result, scene_number=scene.scene_number)

        tasks = [asyncio.create_task(_gen_one(s)) for s in scenes]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate successful results from failures so a single bad scene does
        # not cancel all in-flight work.
        generated_videos: list[GeneratedVideo] = []
        failures: list[tuple[int, BaseException]] = []
        for i, result in enumerate(raw_results):
            if isinstance(result, BaseException):
                failures.append((i, result))
                logger.warning(
                    "scene_video_generation_failed",
                    scene_index=i,
                    error=str(result)[:100],
                )
            else:
                generated_videos.append(result)

        if failures and not generated_videos:
            # Every scene failed — re-raise the first exception.
            raise failures[0][1]

        if failures:
            logger.warning(
                "scene_video_generation_partial",
                succeeded=len(generated_videos),
                failed=len(failures),
            )

        logger.info(
            "scene_videos_generation_complete",
            episode_id=str(episode_id),
            count=len(generated_videos),
        )
        return generated_videos
