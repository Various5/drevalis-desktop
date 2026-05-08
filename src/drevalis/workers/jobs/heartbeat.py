"""Worker heartbeat arq job function.

Jobs
----
- ``worker_heartbeat`` -- write a heartbeat timestamp to Redis every minute.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def worker_heartbeat(ctx: dict[str, Any]) -> None:
    """Write a heartbeat timestamp to Redis every minute.

    The TTL (180s) intentionally exceeds the API's 120-second liveness
    threshold by one full beat so that the key never *expires* before
    the API would already have flagged it stale. Without that margin a
    single missed beat would cause the key to disappear and the next
    GET to return None — indistinguishable from "no worker has ever
    started" — which is more alarming than "worker is one beat late".
    """
    from datetime import datetime

    from redis.asyncio import Redis as _Redis

    try:
        # Use a fresh Redis connection — the arq pool's set() may not
        # work reliably for plain key/value operations.
        _r = _Redis.from_url(ctx.get("redis_url", "redis://redis:6379/0"))
        try:
            await _r.set(
                "worker:heartbeat",
                datetime.now(UTC).isoformat(),
                ex=180,
            )
        finally:
            await _r.aclose()
    except Exception:
        # The heartbeat is the sentinel for worker liveness — silent
        # failures here cause /api/v1/jobs/worker/health to false-flag
        # the worker as dead with no log to investigate. Log loudly
        # so operators see the underlying Redis problem.
        logger.warning("worker_heartbeat_failed", exc_info=True)
