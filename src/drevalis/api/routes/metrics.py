"""Metrics API router -- exposes pipeline execution metrics.

Endpoints:
- GET /api/v1/metrics/steps       -- per-step average duration & success rate
- GET /api/v1/metrics/generations  -- overall generation counts
- GET /api/v1/metrics/recent       -- recent step execution history
- GET /api/v1/metrics/events      -- recent pipeline events for log viewer (DB-backed)
- GET /api/v1/metrics/usage       -- daily usage + compute-time aggregates
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.deps import get_db, get_redis
from drevalis.core.metrics import metrics
from drevalis.models.episode import Episode
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

    # Aggregate per-day on the database side — keeps the response
    # constant-size regardless of how many episodes are on this install.
    day_expr = func.date_trunc("day", GenerationJob.started_at)
    duration_expr = func.extract("epoch", GenerationJob.completed_at - GenerationJob.started_at)
    rows = (
        await db.execute(
            select(
                day_expr.label("day"),
                func.count().label("runs"),
                func.coalesce(func.sum(duration_expr), 0.0).label("seconds"),
                func.sum(func.cast(GenerationJob.status == "failed", type_=Integer)).label(
                    "failures"
                ),
                func.count(func.distinct(GenerationJob.episode_id)).label("episodes"),
            )
            .where(GenerationJob.started_at >= start)
            .where(GenerationJob.started_at.is_not(None))
            .where(GenerationJob.completed_at.is_not(None))
            .group_by(day_expr)
            .order_by(day_expr)
        )
    ).all()

    daily: list[dict[str, Any]] = []
    for row in rows:
        day_value: datetime | None = row.day
        daily.append(
            {
                "day": day_value.date().isoformat() if day_value else None,
                "episodes": int(row.episodes or 0),
                "pipeline_runs": int(row.runs or 0),
                "pipeline_seconds": round(float(row.seconds or 0), 1),
                "failures": int(row.failures or 0),
            }
        )

    # Per-step totals — how much time each step of the pipeline consumed.
    step_rows = (
        await db.execute(
            select(
                GenerationJob.step,
                func.coalesce(func.sum(duration_expr), 0.0).label("seconds"),
            )
            .where(GenerationJob.started_at >= start)
            .where(GenerationJob.started_at.is_not(None))
            .where(GenerationJob.completed_at.is_not(None))
            .group_by(GenerationJob.step)
        )
    ).all()

    # LLM token totals over the window.
    token_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(GenerationJob.tokens_prompt), 0).label("prompt"),
                func.coalesce(func.sum(GenerationJob.tokens_completion), 0).label("completion"),
            ).where(GenerationJob.started_at >= start)
        )
    ).one()
    tokens_prompt = int(token_row.prompt or 0)
    tokens_completion = int(token_row.completion or 0)
    per_step_seconds = {str(r.step): round(float(r.seconds or 0), 1) for r in step_rows}

    # Totals.
    total_runs = sum(d["pipeline_runs"] for d in daily)
    total_seconds = round(sum(d["pipeline_seconds"] for d in daily), 1)
    total_failures = sum(d["failures"] for d in daily)
    failure_rate = (total_failures / total_runs) if total_runs else 0.0

    # Episodes-generated counter (distinct episodes touched in the window).
    # The GROUP BY day lets the same episode count once per day it was
    # worked on — fine for the chart, but for totals we want distinct:
    distinct_eps = await db.execute(
        select(func.count(func.distinct(Episode.id)))
        .select_from(Episode)
        .join(GenerationJob, GenerationJob.episode_id == Episode.id)
        .where(GenerationJob.started_at >= start)
    )
    total_episodes_distinct = int(distinct_eps.scalar_one() or 0)

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
            "per_step_seconds": per_step_seconds,
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
