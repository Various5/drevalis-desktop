"""LicenseGateMiddleware — returns 402 on protected routes when the license
is missing, expired, or invalid.

Exempt paths that ALWAYS respond (so the frontend can show the activation
wizard and health checks can run):

- ``/health``
- ``/api/v1/license/*``        (status, activate, deactivate)
- ``/docs``, ``/redoc``, ``/openapi.json``   (developer discoverability)
- ``/storage/*``               (static media; files are already on disk, no
                               additional compute, and blocking them would
                               prevent the user from downloading their own
                               past output)

Everything else under ``/api/`` or ``/ws/`` returns 402 when the license
state is not usable.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from drevalis.core.license.state import get_state, is_bootstrapped
from drevalis.core.license.verifier import bootstrap_license_state, refresh_if_stale

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/api/v1/license",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/storage",
)

_GUARDED_PREFIXES: tuple[str, ...] = ("/api/", "/ws/")


class LicenseGateMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        *,
        exempt_prefixes: Iterable[str] = _EXEMPT_PREFIXES,
        guarded_prefixes: Iterable[str] = _GUARDED_PREFIXES,
    ) -> None:
        super().__init__(app)
        self._exempt = tuple(exempt_prefixes)
        self._guarded = tuple(guarded_prefixes)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Exempt paths always pass.
        if any(path.startswith(p) for p in self._exempt):
            return await call_next(request)

        # Only guard API and WS routes; static assets etc. are not our job.
        if not any(path.startswith(p) for p in self._guarded):
            return await call_next(request)

        # Demo mode: bypass the licence gate entirely. The demo install is
        # public by design; there's nothing to activate.
        try:
            from drevalis.core.deps import get_settings

            if get_settings().demo_mode:
                return await call_next(request)
        except Exception:
            pass

        # Pull fresh state if another uvicorn worker bumped the version.
        # Cheap: one Redis GET, only rebootstraps when the counter moved.
        try:
            from drevalis.core.database import get_session_factory
            from drevalis.core.deps import get_settings
            from drevalis.core.redis import get_redis as _get_redis_gen

            settings = get_settings()

            # Startup race guard: if lifespan hasn't yet completed
            # bootstrap_license_state in this worker process, do it now
            # before deciding to 402. Without this, a request that
            # lands in the tiny window between uvicorn's process fork
            # and the lifespan callback sees the default UNACTIVATED
            # state and wrongly blocks the caller.
            if not is_bootstrapped():
                try:
                    await bootstrap_license_state(
                        get_session_factory(),
                        public_key_override_pem=settings.license_public_key_override,
                    )
                except Exception:
                    logger.debug("license_bootstrap_race_failed", exc_info=True)

            async for _r in _get_redis_gen():
                await refresh_if_stale(
                    get_session_factory(),
                    _r,
                    public_key_override_pem=settings.license_public_key_override,
                )
                break
        except Exception:
            logger.debug("license_refresh_skipped", exc_info=True)

        state = get_state()
        if state.is_usable:
            return await call_next(request)

        # Not usable → 402 with a machine-readable detail the frontend uses
        # to route to the activation wizard. This is the *normal* state
        # during onboarding — every request the wizard doesn't explicitly
        # ping generates one line, so keep it at DEBUG to avoid drowning
        # the operator in expected-output.
        logger.debug(
            "license_gate_blocked",
            path=path,
            status=state.status.value,
        )
        return JSONResponse(
            status_code=402,
            content={
                "detail": {
                    "error": "license_required",
                    "state": state.status.value,
                    "error_message": state.error,
                }
            },
        )
