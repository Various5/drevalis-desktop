"""Generation Jobs API router — list, detail, active, status, cancel-all,
cancel, unified tasks.

Layering: this router calls ``JobsService`` only. No repository imports
or direct ``Redis`` client lifecycle here (audit F-A-01).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import InvalidStatusError, NotFoundError
from drevalis.schemas.generation_job import (
    GenerationJobExtendedResponse,
    GenerationJobListResponse,
    GenerationJobResponse,
)
from drevalis.services.jobs import VALID_PRIORITY_MODES, JobsService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _service(db: AsyncSession = Depends(get_db)) -> JobsService:
    return JobsService(db)


# ── Active jobs (must be before /{job_id} to avoid path conflict) ────────


@router.get(
    "/active",
    response_model=list[GenerationJobListResponse],
    status_code=status.HTTP_200_OK,
    summary="All currently running or queued jobs",
)
async def list_active_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    svc: JobsService = Depends(_service),
) -> list[GenerationJobListResponse]:
    jobs = await svc.list_active(limit)
    return [GenerationJobListResponse.model_validate(j) for j in jobs]


@router.get(
    "/status",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Queue status and generation statistics",
)
async def get_queue_status(
    svc: JobsService = Depends(_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the current queue status and generation statistics."""
    from drevalis.core.concurrency import effective_max_concurrent_generations

    return await svc.queue_status(
        effective_max_concurrent_generations(settings.max_concurrent_generations)
    )


@router.get(
    "/tasks/active",
    status_code=status.HTTP_200_OK,
    summary="Get ALL active background tasks from all sources",
)
async def get_active_tasks(
    svc: JobsService = Depends(_service),
) -> dict[str, list[dict[str, Any]]]:
    """Return a unified list of all active background tasks across the
    system: episode generation jobs, audiobook generation jobs, and LLM
    script/series generation jobs (from Redis). The frontend Activity
    Monitor polls this single endpoint."""
    return {"tasks": await svc.active_tasks()}


@router.post(
    "/cleanup",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Clean up orphaned queued/running jobs and stale generating episodes",
)
async def cleanup_stale_jobs(
    svc: JobsService = Depends(_service),
) -> dict[str, Any]:
    """Mark orphaned ``queued`` and ``running`` generation jobs as
    ``failed`` when their parent episode is no longer in ``generating``
    status, and reset stale ``generating`` episodes to ``draft``."""
    counts = await svc.cleanup_stale()
    return {
        "message": (
            f"Cleaned up {counts['cleaned_jobs']} orphaned job(s), "
            f"reset {counts['reset_episodes']} stale episode(s)"
        ),
        **counts,
    }


@router.post(
    "/cancel-all",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Emergency stop: cancel all generating episodes",
)
async def cancel_all_jobs(
    svc: JobsService = Depends(_service),
) -> dict[str, Any]:
    """Set cancel flags for every generating episode, mark
    running/queued jobs as failed, and update generating episodes to
    ``failed`` status."""
    counts = await svc.cancel_all()
    return {
        "message": f"Emergency stop: cancelled {counts['cancelled_episodes']} episode(s)",
        **counts,
    }


@router.post(
    "/retry-all-failed",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Retry all failed episodes from their first failed step",
)
async def retry_all_failed(
    priority: str = Query(
        default="shorts_first",
        description="Queue order: shorts_first, longform_first, fifo",
    ),
    svc: JobsService = Depends(_service),
) -> dict[str, Any]:
    """Find every ``failed`` episode and enqueue retry jobs."""
    counts = await svc.retry_all_failed(priority)
    return {
        "message": f"Retried {counts['retried']} failed episode(s) (priority: {priority})",
        **counts,
    }


@router.post(
    "/pause-all",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Pause all generating episodes (sets cancel flag, keeps status as failed for easy retry)",
)
async def pause_all(
    svc: JobsService = Depends(_service),
) -> dict[str, Any]:
    paused = await svc.pause_all()
    return {"message": f"Paused {paused} generating episode(s)", "paused": paused}


@router.post(
    "/set-priority",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Set job processing priority mode",
)
async def set_priority(
    mode: str = Query(..., description="shorts_first, longform_first, or fifo"),
    svc: JobsService = Depends(_service),
) -> dict[str, Any]:
    try:
        await svc.set_priority(mode)
    except InvalidStatusError as exc:
        raise HTTPException(422, f"Invalid priority mode: {mode}") from exc
    return {"message": f"Priority mode set to '{mode}'", "mode": mode}


@router.get(
    "/priority",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get current job priority mode",
)
async def get_priority(
    svc: JobsService = Depends(_service),
) -> dict[str, Any]:
    return {"mode": await svc.get_priority()}


@router.get(
    "/all",
    response_model=list[GenerationJobExtendedResponse],
    status_code=status.HTTP_200_OK,
    summary="List all jobs with filters and episode metadata",
)
async def list_all_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    episode_id: UUID | None = Query(default=None),
    step: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    svc: JobsService = Depends(_service),
) -> list[GenerationJobExtendedResponse]:
    """List all generation jobs with optional filters; joins with
    episodes and series for titles + series names."""
    jobs = await svc.list_all_filtered(
        status_filter=status_filter,
        episode_id=episode_id,
        step=step,
        offset=offset,
        limit=limit,
    )
    results: list[GenerationJobExtendedResponse] = []
    for job in jobs:
        episode_title: str | None = None
        series_name: str | None = None
        if job.episode is not None:
            episode_title = job.episode.title
            if job.episode.series is not None:
                series_name = job.episode.series.name
        results.append(
            GenerationJobExtendedResponse(
                id=job.id,
                episode_id=job.episode_id,
                step=job.step,
                status=job.status,
                progress_pct=job.progress_pct,
                started_at=job.started_at,
                completed_at=job.completed_at,
                error_message=job.error_message,
                retry_count=job.retry_count,
                worker_id=job.worker_id,
                created_at=job.created_at,
                updated_at=job.updated_at,
                episode_title=episode_title,
                series_name=series_name,
            )
        )
    return results


@router.get(
    "/worker/health",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Check if the arq worker is alive via Redis heartbeat",
)
async def worker_health(
    svc: JobsService = Depends(_service),
) -> dict[str, Any]:
    """Liveness from the Redis ``worker:heartbeat`` key (refreshed every
    60s with a 120s TTL by the worker)."""
    return await svc.worker_health()


@router.post(
    "/worker/restart",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Signal the worker to restart and reset all generating episodes",
)
async def restart_worker(
    svc: JobsService = Depends(_service),
) -> dict[str, Any]:
    """Set ``worker:restart_signal`` (5min TTL) and reset every
    ``generating`` episode to ``failed`` so the user can retry."""
    reset_count = await svc.restart_worker()
    return {
        "message": (
            f"Worker restart signalled. Reset {reset_count} generating episode(s) to failed."
        ),
        "reset_episodes": reset_count,
        "restart_signal_set": True,
    }


@router.post(
    "/{job_id}/cancel",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Cancel a specific generation job",
)
async def cancel_job(
    job_id: UUID,
    svc: JobsService = Depends(_service),
) -> dict[str, Any]:
    """Cancel a specific generation job. If no other running/queued
    jobs remain for the same episode, the episode is also marked as
    failed and a Redis cancel flag is set."""
    try:
        episode_id, episode_cancelled = await svc.cancel_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation job {job_id} not found",
        ) from exc
    except InvalidStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Job is in '{exc.current}' status. Only running or queued jobs can be cancelled."
            ),
        ) from exc

    return {
        "message": f"Job {job_id} cancelled",
        "job_id": str(job_id),
        "episode_id": str(episode_id),
        "episode_cancelled": episode_cancelled,
    }


@router.get(
    "",
    response_model=list[GenerationJobListResponse],
    status_code=status.HTTP_200_OK,
    summary="List generation jobs (filter by status, episode_id)",
)
async def list_jobs(
    episode_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    svc: JobsService = Depends(_service),
) -> list[GenerationJobListResponse]:
    """List generation jobs, optionally filtered by episode and/or status."""
    jobs = await svc.list_filtered(episode_id=episode_id, status_filter=status_filter, limit=limit)
    return [GenerationJobListResponse.model_validate(j) for j in jobs]


@router.get(
    "/{job_id}",
    response_model=GenerationJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Get generation job detail",
)
async def get_job(
    job_id: UUID,
    svc: JobsService = Depends(_service),
) -> GenerationJobResponse:
    try:
        job = await svc.get_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation job {job_id} not found",
        ) from exc
    return GenerationJobResponse.model_validate(job)


# Re-export the constant so it's visible from the package import.
__all__ = ["VALID_PRIORITY_MODES", "router"]
