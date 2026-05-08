"""Phase 2 client-side license activation + heartbeat.

Exchanges a short license key (UUID) for a signed JWT by calling the
owner-operated license server. Falls back to local-only validation when
``settings.license_server_url`` is unset (Phase 1 behavior, for dev or for
users who received a raw JWT via email).

The heartbeat helper performs the same round-trip periodically (24h by
default) and replaces the stored JWT. If the server returns 402 with an
explicit ``license_revoked`` signal, the caller zeros the stored token so
the next request flips the app into the EXPIRED/UNACTIVATED state.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class ActivationError(Exception):
    """Raised when the license server rejects an activation attempt."""

    def __init__(
        self, *, status_code: int, error: str, detail: dict[str, Any] | None = None
    ) -> None:
        super().__init__(f"{status_code}: {error}")
        self.status_code = status_code
        self.error = error
        self.detail = detail or {}


class ActivationNetworkError(Exception):
    """Raised when the license server is unreachable. Callers may fall back
    to local validation (e.g. treat the input as a JWT instead of a key)."""


def looks_like_jwt(value: str) -> bool:
    """Cheap heuristic: JWTs have two dots and are base64-ish, keys are UUIDs."""
    return value.count(".") == 2 and len(value) > 40


async def exchange_key_for_jwt(
    server_url: str,
    *,
    license_key: str,
    machine_id: str,
    version: str | None = None,
    timeout: float = 10.0,
) -> str:
    """POST ``/activate`` to the license server and return the minted JWT."""
    url = server_url.rstrip("/") + "/activate"
    payload = {"license_key": license_key, "machine_id": machine_id}
    if version:
        payload["version"] = version

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
        logger.warning("license_server_unreachable", url=url, error=str(exc)[:120])
        raise ActivationNetworkError(str(exc)) from exc

    if resp.status_code >= 400:
        detail: dict[str, Any] = {}
        try:
            detail = resp.json().get("detail", {})
        except Exception:
            pass
        error_name = (
            detail.get("error") if isinstance(detail, dict) else str(detail)
        ) or resp.reason_phrase
        raise ActivationError(
            status_code=resp.status_code,
            error=error_name or "activation_failed",
            detail=detail if isinstance(detail, dict) else {"raw": detail},
        )

    body = resp.json()
    token = body.get("license_jwt")
    if not token:
        raise ActivationError(status_code=500, error="malformed_response", detail=body)
    return str(token)


async def heartbeat_with_server(
    server_url: str,
    *,
    license_key: str,
    machine_id: str,
    version: str | None = None,
    timeout: float = 10.0,
) -> str:
    """POST ``/heartbeat`` — returns a freshly-minted JWT."""
    url = server_url.rstrip("/") + "/heartbeat"
    payload = {"license_key": license_key, "machine_id": machine_id}
    if version:
        payload["version"] = version

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
        raise ActivationNetworkError(str(exc)) from exc

    if resp.status_code >= 400:
        detail: dict[str, Any] = {}
        try:
            detail = resp.json().get("detail", {})
        except Exception:
            pass
        raise ActivationError(
            status_code=resp.status_code,
            error=(detail.get("error") if isinstance(detail, dict) else None) or "heartbeat_failed",
            detail=detail if isinstance(detail, dict) else {"raw": detail},
        )

    body = resp.json()
    token = body.get("license_jwt") or ""
    if not token:
        raise ActivationError(status_code=500, error="malformed_response", detail=body)
    return token


async def deactivate_with_server(
    server_url: str,
    *,
    license_key: str,
    machine_id: str,
    timeout: float = 10.0,
) -> None:
    """POST ``/deactivate`` — best-effort seat release.

    Network / 4xx errors are logged but not re-raised; the client still
    zeros its local JWT so the app locks regardless of whether the server
    acknowledged.
    """
    url = server_url.rstrip("/") + "/deactivate"
    payload = {"license_key": license_key, "machine_id": machine_id}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.post(url, json=payload)
    except Exception as exc:
        logger.info("license_server_deactivate_failed", error=str(exc)[:120])


async def list_activations_with_server(
    server_url: str,
    *,
    license_key: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """POST ``/activations`` → every machine currently holding a seat.

    Returns ``{tier, cap, activations: [{machine_id, first_seen,
    last_heartbeat, last_known_version}]}``. Raises :class:`ActivationError`
    on 4xx / 5xx or :class:`ActivationNetworkError` on transport failures.
    """
    url = server_url.rstrip("/") + "/activations"
    payload = {"license_key": license_key}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
    except (httpx.NetworkError, httpx.TimeoutException) as exc:
        raise ActivationNetworkError(str(exc)[:200]) from exc

    if resp.status_code >= 400:
        detail: dict[str, Any] = {}
        try:
            detail = resp.json().get("detail", {})
        except Exception:
            pass
        error_name = (
            detail.get("error") if isinstance(detail, dict) else str(detail)
        ) or resp.reason_phrase
        raise ActivationError(
            status_code=resp.status_code,
            error=str(error_name) or "list_failed",
            detail=detail if isinstance(detail, dict) else {"raw": detail},
        )
    body: dict[str, Any] = resp.json()
    return body


async def deactivate_machine_with_server(
    server_url: str,
    *,
    license_key: str,
    machine_id: str,
    timeout: float = 10.0,
) -> None:
    """POST ``/deactivate`` for an arbitrary ``machine_id``.

    Differs from :func:`deactivate_with_server` in that it surfaces
    server errors to the caller rather than swallowing them — useful
    when the UI shows a table of activations and wants to report why a
    specific deactivate failed ("this install is no longer registered",
    network down, etc.).
    """
    url = server_url.rstrip("/") + "/deactivate"
    payload = {"license_key": license_key, "machine_id": machine_id}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
    except (httpx.NetworkError, httpx.TimeoutException) as exc:
        raise ActivationNetworkError(str(exc)[:200]) from exc

    if resp.status_code >= 400:
        detail: dict[str, object] = {}
        try:
            detail = resp.json().get("detail", {})
        except Exception:
            pass
        error_name = (
            detail.get("error") if isinstance(detail, dict) else str(detail)
        ) or resp.reason_phrase
        raise ActivationError(
            status_code=resp.status_code,
            error=str(error_name) or "deactivate_failed",
            detail=detail if isinstance(detail, dict) else {"raw": detail},
        )
