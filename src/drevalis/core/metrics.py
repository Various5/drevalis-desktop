"""Redis-backed pipeline metrics.

The collector lives in two processes — uvicorn writes none, the arq
worker writes most — so the previous in-process singleton silently
lost everything: routes read zeros while the worker happily incremented
its private dict. This module replaces it with Redis-backed counters
plus a capped recent-events list so the worker's writes are visible
through the API.

Public surface preserved:
- ``record_step(redis, step, duration, success, episode_id)``
- ``record_generation(redis, success)``
- ``get_step_stats(redis)``
- ``get_generation_stats(redis)``
- ``get_recent_metrics(redis, limit)``

The module-level ``metrics`` singleton is kept so existing imports
continue to resolve. Each call now takes the redis client explicitly;
callers in the worker pass ``self.redis`` and route handlers pass the
``Depends(get_redis)``-injected client.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from redis.asyncio import Redis


_KEY_KNOWN_STEPS = "metrics:steps_known"
_KEY_STEP_PREFIX = "metrics:step"  # ":<step>:<field>" suffix
_KEY_GEN_TOTAL = "metrics:gen:total"
_KEY_GEN_SUCCESS = "metrics:gen:success"
_KEY_GEN_FAILED = "metrics:gen:failed"
_KEY_RECENT = "metrics:recent"
_MAX_RECENT = 1000


def _step_key(step: str, field_name: str) -> str:
    return f"{_KEY_STEP_PREFIX}:{step}:{field_name}"


@dataclass
class StepMetric:
    """A single recorded pipeline step execution."""

    step: str
    duration_seconds: float
    success: bool
    episode_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "duration_seconds": round(self.duration_seconds, 3),
            "success": self.success,
            "episode_id": self.episode_id,
            "timestamp": self.timestamp.isoformat(),
        }


class MetricsCollector:
    """Thin facade over Redis counters."""

    async def record_step(
        self,
        redis: Redis,
        *,
        step: str,
        duration: float,
        success: bool,
        episode_id: str,
    ) -> None:
        """Record one pipeline-step outcome."""
        metric = StepMetric(
            step=step,
            duration_seconds=duration,
            success=success,
            episode_id=episode_id,
        )

        async with redis.pipeline(transaction=False) as pipe:
            pipe.sadd(_KEY_KNOWN_STEPS, step)
            pipe.incr(_step_key(step, "count"))
            if success:
                pipe.incr(_step_key(step, "success"))
            # Total duration uses INCRBYFLOAT for cross-process accumulation.
            pipe.incrbyfloat(_step_key(step, "total_dur"), duration)
            pipe.set(_step_key(step, "last_dur"), f"{duration:.6f}")
            # Min/max via Lua-free CAS isn't atomic, but worst case the
            # range is slightly off — acceptable for a metrics view.
            await pipe.execute()

        await self._update_min_max(redis, step, duration)
        await self._push_recent(redis, metric)

    async def record_generation(self, redis: Redis, *, success: bool) -> None:
        """Record one full pipeline run."""
        async with redis.pipeline(transaction=False) as pipe:
            pipe.incr(_KEY_GEN_TOTAL)
            if success:
                pipe.incr(_KEY_GEN_SUCCESS)
            else:
                pipe.incr(_KEY_GEN_FAILED)
            await pipe.execute()

    async def get_step_stats(self, redis: Redis) -> dict[str, Any]:
        """Return per-step aggregates."""
        steps_raw = await cast(Awaitable[set[Any]], redis.smembers(_KEY_KNOWN_STEPS))
        if not steps_raw:
            return {}
        steps = sorted(_decode(s) or "" for s in steps_raw)

        async with redis.pipeline(transaction=False) as pipe:
            for s in steps:
                pipe.get(_step_key(s, "count"))
                pipe.get(_step_key(s, "success"))
                pipe.get(_step_key(s, "total_dur"))
                pipe.get(_step_key(s, "last_dur"))
                pipe.get(_step_key(s, "min_dur"))
                pipe.get(_step_key(s, "max_dur"))
            results = await pipe.execute()

        out: dict[str, Any] = {}
        for idx, s in enumerate(steps):
            base = idx * 6
            count = int(_decode(results[base]) or 0)
            success = int(_decode(results[base + 1]) or 0)
            total_dur = float(_decode(results[base + 2]) or 0.0)
            last_dur = float(_decode(results[base + 3]) or 0.0)
            min_dur = float(_decode(results[base + 4]) or 0.0)
            max_dur = float(_decode(results[base + 5]) or 0.0)
            if count == 0:
                continue
            out[s] = {
                "count": count,
                "avg_duration_seconds": round(total_dur / count, 3),
                "min_duration_seconds": round(min_dur, 3),
                "max_duration_seconds": round(max_dur, 3),
                "success_rate": round(success / count, 3),
                "last_duration_seconds": round(last_dur, 3),
            }
        return out

    async def get_generation_stats(self, redis: Redis) -> dict[str, Any]:
        """Return overall generation counts."""
        async with redis.pipeline(transaction=False) as pipe:
            pipe.get(_KEY_GEN_TOTAL)
            pipe.get(_KEY_GEN_SUCCESS)
            pipe.get(_KEY_GEN_FAILED)
            total_raw, success_raw, failed_raw = await pipe.execute()

        total = int(_decode(total_raw) or 0)
        success = int(_decode(success_raw) or 0)
        failed = int(_decode(failed_raw) or 0)
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "success_rate": round(success / total, 3) if total > 0 else 0.0,
        }

    async def get_recent_metrics(self, redis: Redis, limit: int = 50) -> list[dict[str, Any]]:
        """Return up to ``limit`` most recent step metrics, newest first."""
        items = await cast(Awaitable[list[Any]], redis.lrange(_KEY_RECENT, 0, limit - 1))
        out: list[dict[str, Any]] = []
        for raw in items:
            decoded = _decode(raw)
            if decoded is None:
                continue
            try:
                out.append(json.loads(decoded))
            except (ValueError, TypeError):
                continue
        return out

    # ── internal helpers ──────────────────────────────────────────────

    async def _push_recent(self, redis: Redis, metric: StepMetric) -> None:
        payload = json.dumps(metric.to_dict())
        async with redis.pipeline(transaction=False) as pipe:
            pipe.lpush(_KEY_RECENT, payload)
            pipe.ltrim(_KEY_RECENT, 0, _MAX_RECENT - 1)
            await pipe.execute()

    async def _update_min_max(self, redis: Redis, step: str, duration: float) -> None:
        # Best-effort CAS. Two writers can race; the resulting min/max
        # may be off by one observation. Acceptable trade-off for a
        # dashboard metric (versus pulling in a Lua script).
        min_key = _step_key(step, "min_dur")
        max_key = _step_key(step, "max_dur")
        cur_min_raw = await redis.get(min_key)
        cur_max_raw = await redis.get(max_key)
        cur_min = float(_decode(cur_min_raw) or 0.0) if cur_min_raw else None
        cur_max = float(_decode(cur_max_raw) or 0.0) if cur_max_raw else None
        if cur_min is None or duration < cur_min:
            await redis.set(min_key, f"{duration:.6f}")
        if cur_max is None or duration > cur_max:
            await redis.set(max_key, f"{duration:.6f}")


def _decode(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


# ── singleton ────────────────────────────────────────────────────────
metrics = MetricsCollector()
