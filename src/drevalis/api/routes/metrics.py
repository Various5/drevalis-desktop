"""Metrics API router -- exposes pipeline execution metrics.

Endpoints:
- GET /api/v1/metrics/steps       -- per-step average duration & success rate
- GET /api/v1/metrics/generations  -- overall generation counts
- GET /api/v1/metrics/recent       -- recent step execution history
- GET /api/v1/metrics/events      -- recent pipeline events for log viewer (DB-backed)
- GET /api/v1/metrics/usage       -- daily usage + compute-time aggregates
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.deps import get_db, get_redis
from drevalis.core.metrics import metrics
from drevalis.models.generation_job import GenerationJob

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get(
    "/steps",
    status_code=status.HTTP_200_OK,
    summary="Per-step pipeline statistics",
)
async def step_stats(redis: Redis = Depends(get_redis)) -> dict[str, Any]:
    """Return average duration, min/max, and success rate for each pipeline step.

    Response shape::

        {
            "script": {
                "count": 12,
                "avg_duration_seconds": 4.32,
                "min_duration_seconds": 2.1,
                "max_duration_seconds": 8.7,
                "success_rate": 0.917,
                "last_duration_seconds": 3.8
            },
            ...
        }
    """
    return await metrics.get_step_stats(redis)


@router.get(
    "/generations",
    status_code=status.HTTP_200_OK,
    summary="Overall generation pipeline statistics",
)
async def generation_stats(redis: Redis = Depends(get_redis)) -> dict[str, Any]:
    """Return total, success, and failed generation counts plus success rate.

    Response shape::

        {
            "total": 25,
            "success": 20,
            "failed": 5,
            "success_rate": 0.8
        }
    """
    return await metrics.get_generation_stats(redis)


@router.get(
    "/recent",
    status_code=status.HTTP_200_OK,
    summary="Recent step execution history",
)
async def recent_metrics(
    limit: int = Query(default=50, ge=1, le=500, description="Max entries to return"),
    redis: Redis = Depends(get_redis),
) -> list[dict[str, Any]]:
    """Return the most recent step executions (newest first).

    Each entry contains step name, duration, success flag, episode ID,
    and timestamp.
    """
    return await metrics.get_recent_metrics(redis, limit=limit)


@router.get(
    "/events",
    status_code=status.HTTP_200_OK,
    summary="Recent pipeline events for the log viewer",
)
async def get_recent_events(
    limit: int = Query(default=100, ge=1, le=500, description="Max events to return"),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get recent pipeline events from the database.

    Returns completed/failed generation jobs with duration, step, and
    episode info.  Uses the DB instead of in-process metrics so events
    persist across API restarts and include worker-side data.
    """
    from sqlalchemy import select

    from drevalis.models.generation_job import GenerationJob

    stmt = (
        select(GenerationJob)
        .where(GenerationJob.status.in_(["done", "failed"]))
        .order_by(GenerationJob.completed_at.desc().nullslast())
        .limit(limit)
    )
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    events = []
    for job in jobs:
        started = job.started_at
        completed = job.completed_at
        duration = 0.0
        if started and completed:
            duration = (completed - started).total_seconds()

        events.append(
            {
                "step": job.step,
                "duration_seconds": round(duration, 3),
                "success": job.status == "done",
                "episode_id": str(job.episode_id),
                "timestamp": (completed or started or job.created_at).isoformat(),
                "error_message": job.error_message,
            }
        )

    return events


@router.get(
    "/usage",
    status_code=status.HTTP_200_OK,
    summary="Daily usage + compute-time aggregates over a window",
)
async def usage_summary(
    days: int = Query(30, ge=1, le=365, description="Window length in days."),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return per-day + total usage derived from generation_jobs.

    Response shape::

        {
          "window_days": 30,
          "start_date": "2026-03-23",
          "end_date":   "2026-04-22",
          "totals": {
              "episodes_generated": 84,
              "pipeline_runs":      504,
              "pipeline_seconds":   21_482.5,
              "failures":           12,
              "failure_rate":       0.024,
              "per_step_seconds":   {"script": 418, "voice": 3212, ...}
          },
          "daily": [
              {"day": "2026-04-21", "episodes": 5, "pipeline_seconds": 1342.1, "failures": 0},
              ...
          ],
          "instrumentation_notes": [
              "LLM token counts are persisted per generation_job (tokens_prompt + tokens_completion).",
              "RunPod minutes appear on the RunPod dashboard directly.",
          ]
        }
    """
    now = datetime.now(UTC)
    start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Aggregate in Python rather than SQL: ``date_trunc`` and
    # ``extract(epoch from interval)`` are PostgreSQL-specific and the
    # desktop install is on SQLite. The window is bounded by ``days``
    # (≤ 365) so the row count is small even on heavy daily use.
    job_rows = (
        await db.execute(
            select(
                GenerationJob.started_at,
                GenerationJob.completed_at,
                GenerationJob.step,
                GenerationJob.status,
                GenerationJob.episode_id,
                GenerationJob.tokens_prompt,
                GenerationJob.tokens_completion,
            )
            .where(GenerationJob.started_at >= start)
            .where(GenerationJob.started_at.is_not(None))
            .where(GenerationJob.completed_at.is_not(None))
        )
    ).all()

    daily_buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"runs": 0, "seconds": 0.0, "failures": 0, "episodes": set()}  # type: ignore[dict-item]
    )
    per_step_seconds: dict[str, float] = defaultdict(float)
    distinct_episode_ids: set[Any] = set()
    tokens_prompt = 0
    tokens_completion = 0

    for row in job_rows:
        started: datetime = row.started_at
        completed: datetime = row.completed_at
        # SQLite returns naive datetimes — normalise to UTC for the
        # date() call so the bucketing is timezone-stable.
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=UTC)
        seconds = (completed - started).total_seconds()
        day_key = started.date().isoformat()

        bucket = daily_buckets[day_key]
        bucket["runs"] += 1
        bucket["seconds"] += seconds
        if row.status == "failed":
            bucket["failures"] += 1
        bucket["episodes"].add(row.episode_id)  # type: ignore[union-attr]

        if row.step:
            per_step_seconds[str(row.step)] += seconds
        distinct_episode_ids.add(row.episode_id)
        tokens_prompt += int(row.tokens_prompt or 0)
        tokens_completion += int(row.tokens_completion or 0)

    daily: list[dict[str, Any]] = []
    for day_key in sorted(daily_buckets.keys()):
        bucket = daily_buckets[day_key]
        daily.append(
            {
                "day": day_key,
                "episodes": len(bucket["episodes"]),  # type: ignore[arg-type]
                "pipeline_runs": int(bucket["runs"]),
                "pipeline_seconds": round(float(bucket["seconds"]), 1),
                "failures": int(bucket["failures"]),
            }
        )

    per_step_seconds_rounded = {k: round(v, 1) for k, v in per_step_seconds.items()}

    # Totals.
    total_runs = sum(d["pipeline_runs"] for d in daily)
    total_seconds = round(sum(d["pipeline_seconds"] for d in daily), 1)
    total_failures = sum(d["failures"] for d in daily)
    failure_rate = (total_failures / total_runs) if total_runs else 0.0
    total_episodes_distinct = len(distinct_episode_ids)

    return {
        "window_days": days,
        "start_date": start.date().isoformat(),
        "end_date": now.date().isoformat(),
        "totals": {
            "episodes_generated": total_episodes_distinct,
            "pipeline_runs": total_runs,
            "pipeline_seconds": total_seconds,
            "failures": total_failures,
            "failure_rate": round(failure_rate, 4),
            "per_step_seconds": per_step_seconds_rounded,
            "tokens_prompt": tokens_prompt,
            "tokens_completion": tokens_completion,
            "tokens_total": tokens_prompt + tokens_completion,
        },
        "daily": daily,
        "instrumentation_notes": [
            "ComfyUI + TTS compute is captured as wall-clock pipeline time, not GPU seconds.",
            "RunPod minutes are tracked on runpod.io directly; we don't proxy their billing.",
            "Token counts cover LLM calls that completed through drevalis' LLMService — "
            "models queried directly outside the pipeline won't appear here.",
        ],
    }
