"""Client-side update checker.

Hits the license server's ``/updates/manifest`` endpoint to learn if a
newer release is available. Results are cached in Redis for 6 hours — the
license server is free-tier, so we don't hammer it.

Gating: the manifest endpoint requires an active license and uses the
``jti`` claim as the key, so expired/revoked installs automatically stop
seeing updates (the response is 402 ``license_revoked`` / ``license_expired``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from drevalis.core.license.state import get_state

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_CACHE_KEY = "updates:manifest_cache"
_CACHE_TTL = 6 * 3600  # 6h
# Bind-mounted at /shared in both the app and the updater sidecar. See
# docker-compose.yml — the ``updater_shared`` named volume.
_UPDATE_FLAG_PATH = "/shared/do_update"


def _resolve_current_version() -> str:
    """Return the installed version.

    Baked into the image by the release workflow via ``APP_VERSION`` build
    arg → env var. In local dev where the env var is unset we fall back
    to the package metadata (pyproject ``version``), and finally to the
    ``0.0.0-dev`` sentinel so the UI clearly signals that the running
    process wasn't built through a release tag.
    """
    import os

    env = os.environ.get("APP_VERSION")
    if env and env.strip():
        return env.strip()
    try:
        from importlib.metadata import version

        return version("drevalis")
    except Exception:
        return "0.0.0-dev"


_CURRENT_VERSION = _resolve_current_version()


class UpdateCheckError(Exception):
    def __init__(
        self, *, status_code: int, error: str, detail: dict[str, Any] | None = None
    ) -> None:
        super().__init__(f"{status_code}: {error}")
        self.status_code = status_code
        self.error = error
        self.detail = detail or {}


async def _fetch_manifest(server_url: str, license_key: str) -> dict[str, Any]:
    from drevalis.core.http_retry import request_with_retry

    url = server_url.rstrip("/") + "/updates/manifest"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await request_with_retry(
            client,
            "GET",
            url,
            params={"license": license_key, "current": _CURRENT_VERSION},
            label="license.updates.manifest",
            max_attempts=3,
        )
    if resp.status_code >= 400:
        detail: dict[str, Any] = {}
        try:
            detail = resp.json().get("detail", {})
        except Exception:
            pass
        raise UpdateCheckError(
            status_code=resp.status_code,
            error=(detail.get("error") if isinstance(detail, dict) else None)
            or "update_check_failed",
            detail=detail if isinstance(detail, dict) else {"raw": detail},
        )
    body: dict[str, Any] = resp.json()
    return body


async def check_for_updates(
    redis: Redis,
    *,
    server_url: str | None,
    force: bool = False,
) -> dict[str, Any]:
    """Return the latest manifest, cached 6h in Redis.

    Returns a dict matching ``ManifestResponse`` on the server, plus an
    ``unavailable`` boolean when the caller has no license / no server.
    """
    if not server_url:
        return {
            "unavailable": True,
            "reason": "license_server_not_configured",
            "current_installed": _CURRENT_VERSION,
        }

    state = get_state()
    if not state.is_usable or state.claims is None:
        return {
            "unavailable": True,
            "reason": "license_required",
            "current_installed": _CURRENT_VERSION,
        }

    if not force:
        try:
            cached = await redis.get(_CACHE_KEY)
            if cached:
                cached_body: dict[str, Any] = json.loads(cached)
                return cached_body
        except Exception:
            pass

    try:
        manifest = await _fetch_manifest(server_url, state.claims.jti)
    except httpx.HTTPError as exc:
        logger.info("updates_fetch_network_error", error=str(exc)[:120])
        return {
            "unavailable": True,
            "reason": "network_error",
            "current_installed": _CURRENT_VERSION,
        }
    except UpdateCheckError as exc:
        logger.info(
            "updates_fetch_rejected",
            status_code=exc.status_code,
            error=exc.error,
        )
        return {
            "unavailable": True,
            "reason": exc.error,
            "current_installed": _CURRENT_VERSION,
        }

    manifest["current_installed"] = _CURRENT_VERSION
    manifest.setdefault("update_available", False)
    try:
        await redis.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(manifest))
    except Exception:
        pass
    return manifest


async def request_update_apply() -> None:
    """Drop a flag file that the updater sidecar container polls.

    The sidecar has ``/var/run/docker.sock`` mounted and a bind mount on
    the same ``/tmp`` directory; on seeing the flag it runs
    ``docker compose pull && up -d`` and deletes the flag.

    We deliberately don't raise on filesystem errors here — the UI will
    simply show that no update happened. The caller shows the user a
    "click again if nothing happens in 5 minutes" nudge.
    """
    import os

    os.makedirs(os.path.dirname(_UPDATE_FLAG_PATH), exist_ok=True)
    try:
        with open(_UPDATE_FLAG_PATH, "w", encoding="utf-8") as fh:
            fh.write("1\n")
    except OSError as exc:
        logger.error("update_flag_write_failed", error=str(exc)[:200])
        raise
