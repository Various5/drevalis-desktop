"""Series API router — CRUD + AI generation.

Layering: this router calls ``SeriesService`` only. No repository
imports or LLM provider resolution here (audit F-A-01). The async
generate-job enqueue path keeps its raw Redis calls because there's no
domain logic to extract — it only minds a job_id.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.redis import get_arq_pool, get_pool
from drevalis.schemas.series import (
    SeriesCreate,
    SeriesListResponse,
    SeriesResponse,
    SeriesUpdate,
)
from drevalis.services.series import SeriesFieldLockedError, SeriesService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/series", tags=["series"])


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SeriesService:
    return SeriesService(
        db,
        encryption_key=settings.encryption_key,
        settings_obj=settings,
    )


# ── AI generation schemas ────────────────────────────────────────────────


class SeriesGenerateRequest(BaseModel):
    """Payload for AI-generating a complete series from a natural language idea."""

    idea: str = Field(
        ..., min_length=10, description="Natural language description of the series idea"
    )
    episode_count: int = Field(default=10, ge=1, le=50)
    target_duration_seconds: Literal[15, 30, 60] = 30
    voice_profile_id: UUID | None = None
    llm_config_id: UUID | None = None


class _GeneratedEpisode(BaseModel):
    title: str
    topic: str


class SeriesGenerateResponse(BaseModel):
    series_id: UUID
    series_name: str
    episode_count: int
    episodes: list[_GeneratedEpisode]


class SeriesGenerateJobResponse(BaseModel):
    job_id: str
    status: str


class SeriesGenerateJobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: SeriesGenerateResponse | None = None
    error: str | None = None


class AddEpisodesRequest(BaseModel):
    count: int = Field(5, ge=1, le=20)
    llm_config_id: UUID | None = None


# ── AI generate endpoint (async via arq) ──────────────────────────────


@router.post(
    "/generate",
    response_model=SeriesGenerateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="AI-generate a series + episodes (async via background job)",
)
async def generate_series(
    payload: SeriesGenerateRequest,
) -> SeriesGenerateJobResponse:
    """Enqueue an LLM job to generate a complete series. Returns a
    ``job_id``; poll ``GET /api/v1/series/generate-job/{job_id}``."""
    job_id = str(uuid4())

    redis_client: Redis = Redis(connection_pool=get_pool())
    try:
        await redis_client.set(f"script_job:{job_id}:status", "generating", ex=3600)
        await redis_client.set(
            f"script_job:{job_id}:input",
            json.dumps({"type": "series", "idea": payload.idea}),
            ex=3600,
        )
        arq = get_arq_pool()
        await arq.enqueue_job("generate_series_async", job_id, payload.model_dump(mode="json"))
    finally:
        await redis_client.aclose()

    logger.info(
        "series_generate_job_enqueued",
        job_id=job_id,
        idea_length=len(payload.idea),
        episode_count=payload.episode_count,
    )
    return SeriesGenerateJobResponse(job_id=job_id, status="generating")


@router.get(
    "/generate-job/{job_id}",
    response_model=SeriesGenerateJobStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll for series generation job status",
)
async def get_series_generate_job(job_id: str) -> SeriesGenerateJobStatusResponse:
    redis_client: Redis = Redis(connection_pool=get_pool())
    try:
        raw_status = await redis_client.get(f"script_job:{job_id}:status")
        if not raw_status:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

        job_status = raw_status if isinstance(raw_status, str) else raw_status.decode()

        result: SeriesGenerateResponse | None = None
        error: str | None = None

        if job_status == "done":
            result_json = await redis_client.get(f"script_job:{job_id}:result")
            if result_json:
                raw = result_json if isinstance(result_json, str) else result_json.decode()
                result = SeriesGenerateResponse.model_validate(json.loads(raw))
        elif job_status == "failed":
            raw_error = await redis_client.get(f"script_job:{job_id}:error")
            if raw_error:
                error = raw_error if isinstance(raw_error, str) else raw_error.decode()

        return SeriesGenerateJobStatusResponse(
            job_id=job_id,
            status=job_status,
            result=result,
            error=error,
        )
    finally:
        await redis_client.aclose()


@router.post(
    "/generate-job/{job_id}/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel a series generation job",
)
async def cancel_series_generate_job(job_id: str) -> dict[str, str]:
    redis_client: Redis = Redis(connection_pool=get_pool())
    try:
        existing = await redis_client.get(f"script_job:{job_id}:status")
        if not existing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
        await redis_client.set(f"script_job:{job_id}:status", "cancelled", ex=3600)
    finally:
        await redis_client.aclose()
    logger.info("series_generate_job_cancelled", job_id=job_id)
    return {"message": "Cancelled"}


# ── Synchronous fallback ──────────────────────────────────────────────


@router.post(
    "/generate-sync",
    response_model=SeriesGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="AI-generate a series + episodes (synchronous fallback)",
)
async def generate_series_sync(
    payload: SeriesGenerateRequest,
    svc: SeriesService = Depends(_service),
) -> SeriesGenerateResponse:
    """Synchronous fallback: generate a series and wait for the result inline."""
    try:
        series, episodes = await svc.generate_series_sync(
            idea=payload.idea,
            episode_count=payload.episode_count,
            target_duration_seconds=payload.target_duration_seconds,
            voice_profile_id=payload.voice_profile_id,
            llm_config_id=payload.llm_config_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LLM config not found") from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.detail) from exc

    return SeriesGenerateResponse(
        series_id=series.id,
        series_name=series.name,
        episode_count=len(episodes),
        episodes=[_GeneratedEpisode(title=ep.title, topic=ep.topic or "") for ep in episodes],
    )


# ── List / Create / Get / Update / Delete ─────────────────────────────


@router.get(
    "",
    response_model=list[SeriesListResponse],
    status_code=status.HTTP_200_OK,
    summary="List all series with episode counts",
)
async def list_series(
    svc: SeriesService = Depends(_service),
) -> list[SeriesListResponse]:
    rows = await svc.list_with_episode_counts()
    return [
        SeriesListResponse(
            id=series.id,
            name=series.name,
            description=series.description,
            target_duration_seconds=series.target_duration_seconds,
            episode_count=count,
            created_at=series.created_at,
        )
        for series, count in rows
    ]


@router.post(
    "",
    response_model=SeriesResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new series",
)
async def create_series(
    payload: SeriesCreate,
    svc: SeriesService = Depends(_service),
) -> SeriesResponse:
    series = await svc.create(**payload.model_dump())
    return SeriesResponse.model_validate(series)


@router.get(
    "/{series_id}",
    response_model=SeriesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get series with all relations",
)
async def get_series(
    series_id: UUID,
    svc: SeriesService = Depends(_service),
) -> SeriesResponse:
    try:
        series = await svc.get_with_relations(series_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return SeriesResponse.model_validate(series)


@router.put(
    "/{series_id}",
    response_model=SeriesResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a series",
)
async def update_series(
    series_id: UUID,
    payload: SeriesUpdate,
    svc: SeriesService = Depends(_service),
) -> SeriesResponse:
    """Update an existing series. Only provided (non-None) fields change.

    ``content_format`` and ``aspect_ratio`` are immutable once any
    episode has moved past ``draft`` because they're read by both the
    script and assembly steps from different rows — changing them
    silently mis-renders existing episodes on reassemble. The caller
    must clone the series instead.
    """
    update_data = payload.model_dump(exclude_unset=True)
    try:
        series = await svc.update(series_id, update_data)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.detail) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except SeriesFieldLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "series_field_locked",
                "locked_fields": exc.locked_fields,
                "reason": (
                    "These fields are immutable once any episode has moved past 'draft' — "
                    "changing them would silently mis-render existing episodes on "
                    "reassemble. Duplicate the series into a new one with the desired "
                    "format instead."
                ),
                "non_draft_episode_count": exc.non_draft_episode_count,
            },
        ) from exc
    return SeriesResponse.model_validate(series)


@router.delete(
    "/{series_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a series (cascades to episodes)",
)
async def delete_series(
    series_id: UUID,
    svc: SeriesService = Depends(_service),
) -> None:
    try:
        await svc.delete(series_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# ── Add AI-generated episodes to an existing series ──────────────────────


@router.post(
    "/{series_id}/add-episodes",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="AI-generate new episode ideas and add them as drafts",
)
async def add_episodes_ai(
    series_id: UUID,
    payload: AddEpisodesRequest,
    svc: SeriesService = Depends(_service),
) -> dict[str, Any]:
    """Use the LLM to generate new episode ideas for an existing series.
    Creates episodes as drafts so they can be reviewed before generation."""
    try:
        created_ids, episodes_payload = await svc.add_episodes_ai(
            series_id, payload.count, payload.llm_config_id
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.detail) from exc
    return {
        "message": f"Created {len(created_ids)} new episode draft(s)",
        "episode_ids": created_ids,
        "episodes": episodes_payload,
    }


# ── Trending topics suggestion ───────────────────────────────────────────


@router.post(
    "/{series_id}/trending-topics",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="AI-suggest trending topic ideas for this series",
)
async def suggest_trending_topics(
    series_id: UUID,
    svc: SeriesService = Depends(_service),
) -> dict[str, Any]:
    try:
        topics = await svc.suggest_trending_topics(series_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"series_id": str(series_id), "topics": topics}
