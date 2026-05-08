"""Redis-backed cron lock for arq jobs.

arq runs cron jobs at a fixed schedule on every worker instance — if
two workers are running on the same Redis, both fire at every tick.
For idempotent jobs this is wasteful; for jobs that emit external
side-effects (YouTube / TikTok uploads, Stripe calls) it causes real
double-posts. A short Redis ``SET NX EX`` claim makes the first
worker to hit the tick the owner and turns the other's invocation
into a no-op for the rest of the tick window.

Usage::

    async def publish_scheduled_posts(ctx):
        async with cron_lock(ctx, "publish_scheduled_posts", ttl_s=280):
            # ... actual work ...
"""

from __future__ import annotations

import contextlib
import os
import socket
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@contextlib.asynccontextmanager
async def cron_lock(
    ctx: dict[str, Any],
    name: str,
    *,
    ttl_s: int = 280,
) -> AsyncIterator[bool]:
    """Try to acquire a Redis cron-claim named ``name``. Yields ``True``
    when this invocation is the owner, ``False`` when another worker
    already holds the lock — callers should check the flag and no-op
    when it's ``False``.

    ``ttl_s`` should be shorter than the cron interval so a crashed
    owner can't block the next run; 280s for a 300s (5 min) cadence
    is the usual fit.
    """
    redis = ctx.get("redis")
    if redis is None:
        # No Redis plumbed in (bare invocation, tests) — just run.
        yield True
        return

    key = f"cron:{name}"
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    try:
        # ``SET key owner NX EX ttl`` — atomic claim.
        acquired = await redis.set(key, owner, nx=True, ex=ttl_s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cron_lock_redis_error_running_anyway", name=name, error=str(exc)[:120])
        yield True
        return

    if not acquired:
        logger.info("cron_lock_skipped_held_by_other_worker", name=name)
        yield False
        return

    try:
        yield True
    finally:
        # Only release if we're still the owner (avoid racing with a
        # TTL-reclaimed successor). Lua guarantees atomicity.
        release_script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        try:
            await redis.eval(release_script, 1, key, owner)
        except Exception as exc:  # noqa: BLE001
            logger.debug("cron_lock_release_failed", name=name, error=str(exc)[:120])


__all__ = ["cron_lock"]
