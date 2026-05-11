"""In-process token-bucket rate limiter for license-server.

The license-server is a single-process Fly.io app (no Redis, no
multi-worker). A small in-memory limiter is enough for the volume
we expect (a few thousand activations/day at most) and keeps the
deployment footprint tight. If the app scales horizontally we'll
swap this for a Redis-backed limiter — the API stays the same.

Buckets are keyed by ``{prefix}:{client_ip}`` so a single attacker
IP can't exhaust activate, portal, checkout, and webhook buckets
with one request, AND each endpoint gets its own bucket size.

Usage::

    from app.rate_limit import RateLimiter, rate_limit_ip

    activate_rl = RateLimiter(capacity=10, refill_per_second=10/60)

    @router.post("/activate", dependencies=[Depends(rate_limit_ip(activate_rl))])
    async def activate(...): ...
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Awaitable

from fastapi import HTTPException, Request, status


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    """Fixed-capacity token bucket. Thread-safe-ish: Python's GIL plus
    the single-writer ``_buckets`` pattern means concurrent requests
    can't corrupt the dict even without a lock. Races lose at most a
    single token per caller, which is fine at the budgets we use.
    """

    __slots__ = ("capacity", "refill_per_second", "_buckets")

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity: int = capacity
        self.refill_per_second: float = refill_per_second
        self._buckets: dict[str, _Bucket] = {}

    def take(self, key: str) -> bool:
        """Try to spend one token. Returns True if the caller is under
        the budget; False if they should be throttled."""
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=float(self.capacity), last_refill=now)
            self._buckets[key] = bucket
        # Refill based on elapsed time.
        elapsed = now - bucket.last_refill
        bucket.tokens = min(
            float(self.capacity),
            bucket.tokens + elapsed * self.refill_per_second,
        )
        bucket.last_refill = now
        if bucket.tokens < 1.0:
            return False
        bucket.tokens -= 1.0
        return True


def _client_ip(request: Request) -> str:
    """Best-effort client IP extraction.

    Honours ``X-Forwarded-For`` (first hop) and ``X-Real-IP`` so the
    limiter doesn't collapse every request into one bucket behind
    Fly.io's edge.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",", 1)[0].strip() or "unknown"
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip() or "unknown"
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit_ip(
    limiter: RateLimiter,
    *,
    prefix: str = "",
) -> Callable[[Request], Awaitable[None]]:
    """FastAPI dependency factory — denies with 429 when the caller's
    IP has exhausted its budget on the given limiter."""

    async def _dep(request: Request) -> None:
        key = f"{prefix or 'rl'}:{_client_ip(request)}"
        if not limiter.take(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate_limited",
                headers={"Retry-After": "60"},
            )

    return _dep


__all__ = ["RateLimiter", "rate_limit_ip"]
