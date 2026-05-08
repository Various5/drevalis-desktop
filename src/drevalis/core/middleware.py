"""Request logging middleware for structured observability.

Logs every HTTP request with method, path, status code, and duration.
Injects a unique ``request_id`` into the structlog context so all log
entries produced during request handling can be correlated.

Quiet paths (``/health``, ``/api/v1/metrics/*``) are logged at DEBUG
level to avoid noise in production logs.
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger: structlog.stdlib.BoundLogger = structlog.get_logger("drevalis.middleware")

# Paths that should only be logged at DEBUG level to reduce noise.
_QUIET_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/api/v1/metrics",
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that logs every HTTP request/response cycle.

    For each request:
    1. Generates a unique ``request_id`` (UUID4).
    2. Binds ``request_id`` into the structlog context-vars so all
       downstream log calls automatically include it.
    3. Logs the completed request with method, path, status code,
       and duration in milliseconds.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = str(uuid.uuid4())
        method = request.method
        path = request.url.path

        # Bind request context into structlog context-vars
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            http_method=method,
            http_path=path,
        )

        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error(
                "request_error",
                duration_ms=duration_ms,
                exc_info=True,
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        status_code = response.status_code

        # Determine log level: quiet paths at DEBUG, everything else at INFO
        is_quiet = any(path.startswith(prefix) for prefix in _QUIET_PATH_PREFIXES)
        log_fn = logger.debug if is_quiet else logger.info

        log_fn(
            "request_completed",
            status_code=status_code,
            duration_ms=duration_ms,
        )

        # Pass request_id downstream as a response header for client correlation
        response.headers["X-Request-ID"] = request_id

        # Clean up context-vars after the request is done
        structlog.contextvars.clear_contextvars()

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set conservative defense-in-depth headers on every response.

    The single-tenant local-first architecture makes these mostly
    defensive — but ``/storage/*`` serves user-generated files whose
    content type we don't fully trust, so ``X-Content-Type-Options:
    nosniff`` + ``X-Frame-Options: DENY`` prevent a hostile upload
    (VULN-008 family) from being reinterpreted as HTML/JS by a
    permissive browser or iframed into a UI-redress attack.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), camera=(), microphone=()",
        )
        return response
