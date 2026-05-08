"""Optional API key authentication middleware.

If the ``API_AUTH_TOKEN`` environment variable is set, all API requests must
include it as a Bearer token in the ``Authorization`` header.  If the variable
is not set, authentication is disabled (local dev mode).

Usage in ``main.py``::

    from drevalis.core.auth import OptionalAPIKeyMiddleware
    app.add_middleware(OptionalAPIKeyMiddleware)
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# S-4: Rate-limit constants for failed auth attempts.
# After _AUTH_FAIL_LIMIT failures from the same IP within _AUTH_FAIL_WINDOW
# seconds, the middleware returns 429 without inspecting the token.
_AUTH_FAIL_LIMIT: int = 10
_AUTH_FAIL_WINDOW: int = 300  # 5 minutes


class OptionalAPIKeyMiddleware(BaseHTTPMiddleware):
    """Require a Bearer token on all API endpoints when API_AUTH_TOKEN is set.

    * If ``API_AUTH_TOKEN`` is **not** set in the environment, all requests
      are allowed through (local dev mode).
    * If it **is** set, every request to ``/api/``, ``/ws/``, or ``/storage/``
      must include ``Authorization: Bearer <token>``.
    * The ``/health`` endpoint is always exempt.
    * Repeated auth failures from the same IP are rate-limited via Redis
      (S-4, CWE-307, OWASP A07:2021).
    """

    def __init__(self, app: Any, token: str | None = None) -> None:
        super().__init__(app)
        raw = token if token is not None else os.environ.get("API_AUTH_TOKEN")
        # Treat empty/whitespace same as unset. The installer writes
        # `API_AUTH_TOKEN=` to seed a blank slot for future hardening;
        # without this coercion the middleware would enforce against an
        # empty expected value, fail every request, and lock out the IP
        # with 429 after 10 failures — bricking a fresh install.
        self._token: str | None = raw.strip() if (raw and raw.strip()) else None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # If no token is configured, allow everything (local dev mode).
        if not self._token:
            return await call_next(request)

        path = request.url.path

        # Always allow health checks and OpenAPI docs.
        exempt_prefixes = ("/health", "/docs", "/redoc", "/openapi.json")
        if any(path.startswith(p) for p in exempt_prefixes):
            return await call_next(request)

        # Guard API routes, WebSocket upgrades, and static storage files.
        # /storage/ is included so that generated media files are not publicly
        # accessible when an auth token is configured (S-8).
        guarded_prefixes = ("/api/", "/ws/", "/storage/")
        if not any(path.startswith(p) for p in guarded_prefixes):
            return await call_next(request)

        # ------------------------------------------------------------------
        # S-4: Per-IP rate limit on auth failures.
        # Check BEFORE inspecting the token so a blocked IP never reaches
        # the comparison and cannot enumerate valid tokens via timing.
        #
        # Behind nginx / NPM, ``request.client.host`` is the proxy's IP —
        # every caller collapses into one bucket. Prefer the left-most
        # entry of ``X-Forwarded-For`` when present and trust the first
        # hop only. We keep the fallback to the socket peer for direct
        # traffic.
        # ------------------------------------------------------------------
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip: str = forwarded.split(",", 1)[0].strip() or "unknown"
        elif request.headers.get("x-real-ip"):
            client_ip = request.headers["x-real-ip"].strip()
        elif request.client:
            client_ip = request.client.host
        else:
            client_ip = "unknown"
        rate_key: str = f"auth_fail:{client_ip}"

        try:
            # Import lazily — pool is only available after lifespan startup.
            from redis.asyncio import Redis as _Redis

            from drevalis.core.redis import get_pool

            _redis: _Redis = _Redis(connection_pool=get_pool())
            try:
                fail_count_raw = await _redis.get(rate_key)
                fail_count: int = int(fail_count_raw) if fail_count_raw else 0
            finally:
                await _redis.aclose()
        except Exception:
            # If Redis is unavailable, degrade gracefully and allow the
            # request through rather than blocking all traffic.
            fail_count = 0

        if fail_count >= _AUTH_FAIL_LIMIT:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many failed authentication attempts. Try again later."},
            )

        # ------------------------------------------------------------------
        # Token validation
        # ------------------------------------------------------------------
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            await _record_auth_failure(client_ip)
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )
        provided_token = auth_header[7:]  # Strip "Bearer "
        if not secrets.compare_digest(provided_token, self._token):
            await _record_auth_failure(client_ip)
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API token"},
            )

        return await call_next(request)


async def _record_auth_failure(client_ip: str) -> None:
    """Increment the Redis failure counter for *client_ip*.

    Sets a TTL of ``_AUTH_FAIL_WINDOW`` seconds on the first write so the
    key expires automatically.  Errors are swallowed — rate limiting is
    best-effort and must not interrupt the normal auth flow.

    CWE-307 (Improper Restriction of Excessive Authentication Attempts),
    OWASP A07:2021 (Identification and Authentication Failures).
    """
    rate_key = f"auth_fail:{client_ip}"
    try:
        from redis.asyncio import Redis as _Redis

        from drevalis.core.redis import get_pool

        _redis: _Redis = _Redis(connection_pool=get_pool())
        try:
            pipe = _redis.pipeline()
            pipe.incr(rate_key)
            # Only set the TTL if the key is new (NX=True); this preserves
            # the original expiry window across multiple failures.
            pipe.expire(rate_key, _AUTH_FAIL_WINDOW, nx=True)
            await pipe.execute()
        finally:
            await _redis.aclose()
    except Exception:
        pass  # Best-effort — never block auth flow due to Redis errors.


# ── Login form rate limiting (F-S-09) ──────────────────────────────────


# Per-(IP, email) login attempt counters live alongside the API-token
# bucket so a single Redis key prefix governs the whole auth surface.
# The middleware's per-IP bucket already covers Bearer-token attempts;
# this pair extends the same bucket pattern to the login form.
_LOGIN_FAIL_LIMIT: int = 10
_LOGIN_FAIL_WINDOW: int = 600  # 10 minutes


class LoginRateLimitedError(Exception):
    """Raised when the (IP, email) pair has exceeded the login attempt cap."""


async def check_login_rate_limit(client_ip: str, email: str) -> None:
    """Raise ``LoginRateLimitedError`` if (client_ip, email) is over its
    failure budget.

    Combined key so a brute-force attacker rotating IPs against a single
    account still trips the limiter (per-email bucket), and a single
    misbehaving IP scanning many accounts also trips it (per-IP bucket).
    Failures decay automatically after ``_LOGIN_FAIL_WINDOW`` seconds.
    """
    key_ip = f"login_fail:ip:{client_ip}"
    key_email = f"login_fail:email:{email.lower()}"
    try:
        from redis.asyncio import Redis as _Redis

        from drevalis.core.redis import get_pool

        _redis: _Redis = _Redis(connection_pool=get_pool())
        try:
            ip_count_raw, email_count_raw = await _redis.mget([key_ip, key_email])
            ip_count = int(ip_count_raw) if ip_count_raw else 0
            email_count = int(email_count_raw) if email_count_raw else 0
        finally:
            await _redis.aclose()
    except Exception:
        # Redis unavailable — degrade gracefully (fail-open). The
        # underlying PBKDF2 cost (~480k iterations) still imposes a
        # CPU-bound floor on attempt rate.
        return

    if ip_count >= _LOGIN_FAIL_LIMIT or email_count >= _LOGIN_FAIL_LIMIT:
        raise LoginRateLimitedError(
            f"Too many failed login attempts. Try again in {_LOGIN_FAIL_WINDOW // 60} minutes."
        )


async def record_login_failure(client_ip: str, email: str) -> None:
    """Increment both per-IP and per-email login failure counters.

    Best-effort: Redis errors are swallowed so a downed cache doesn't
    block the auth flow.
    """
    key_ip = f"login_fail:ip:{client_ip}"
    key_email = f"login_fail:email:{email.lower()}"
    try:
        from redis.asyncio import Redis as _Redis

        from drevalis.core.redis import get_pool

        _redis: _Redis = _Redis(connection_pool=get_pool())
        try:
            pipe = _redis.pipeline()
            pipe.incr(key_ip)
            pipe.expire(key_ip, _LOGIN_FAIL_WINDOW, nx=True)
            pipe.incr(key_email)
            pipe.expire(key_email, _LOGIN_FAIL_WINDOW, nx=True)
            await pipe.execute()
        finally:
            await _redis.aclose()
    except Exception:
        pass
