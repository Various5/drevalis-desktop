"""A/B test pair management — link two same-series episodes for comparison.

Endpoints:

- ``POST   /api/v1/ab-tests``               create a new pair
- ``GET    /api/v1/ab-tests``               list all pairs (optionally per series)
- ``GET    /api/v1/ab-tests/{id}``          one pair + per-episode YouTube stats
- ``DELETE /api/v1/ab-tests/{id}``          untrack the pair (episodes kept)

The comparison itself (``winner_episode_id``, ``comparison_at``) is
populated by a future scheduled worker that pulls YouTube analytics
for both episodes 7 days after the later upload. For v1 we just
surface the raw view counts side-by-side so the operator can eyeball
the result.

Layering: this router calls ``ABTestService`` only. No repository or
ORM imports here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession  # runtime import — FastAPI Depends

from drevalis.core.deps import get_db
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.license.features import fastapi_dep_require_feature
from drevalis.services.ab_test import ABTestService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# A/B title testing piggy-backs on the SEO pre-flight feature flag —
# both ship together at Creator+ per the marketing pricing matrix.
router = APIRouter(
    prefix="/api/v1/ab-tests",
    tags=["ab-tests"],
    dependencies=[Depends(fastapi_dep_require_feature("seo_preflight"))],
)


def _service(db: AsyncSession = Depends(get_db)) -> ABTestService:
    return ABTestService(db)


class ABTestCreate(BaseModel):
    series_id: UUID
    episode_a_id: UUID
    episode_b_id: UUID
    variant_label: str = Field(..., min_length=1, max_length=255)
    notes: str | None = None


class ABTestResponse(BaseModel):
    id: UUID
    series_id: UUID
    episode_a_id: UUID
    episode_b_id: UUID
    variant_label: str
    notes: str | None
    winner_episode_id: UUID | None
    comparison_at: str | None
    created_at: str


class ABTestStats(BaseModel):
    episode_id: UUID
    title: str
    status: str
    youtube_video_id: str | None
    youtube_url: str | None
    youtube_views: int | None
    youtube_likes: int | None
    youtube_comments: int | None


class ABTestDetail(ABTestResponse):
    episode_a_stats: ABTestStats
    episode_b_stats: ABTestStats


def _serialise(t: Any) -> ABTestResponse:
    return ABTestResponse(
        id=t.id,
        series_id=t.series_id,
        episode_a_id=t.episode_a_id,
        episode_b_id=t.episode_b_id,
        variant_label=t.variant_label,
        notes=t.notes,
        winner_episode_id=t.winner_episode_id,
        comparison_at=t.comparison_at.isoformat() if t.comparison_at else None,
        created_at=t.created_at.isoformat() if t.created_at else "",
    )


def _missing_stats(episode_id: UUID) -> ABTestStats:
    return ABTestStats(
        episode_id=episode_id,
        title="(missing episode)",
        status="deleted",
        youtube_video_id=None,
        youtube_url=None,
        youtube_views=None,
        youtube_likes=None,
        youtube_comments=None,
    )


@router.post(
    "",
    response_model=ABTestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link two episodes as an A/B test pair",
)
async def create_ab_test(
    body: ABTestCreate,
    svc: ABTestService = Depends(_service),
) -> ABTestResponse:
    try:
        test = await svc.create(
            series_id=body.series_id,
            episode_a_id=body.episode_a_id,
            episode_b_id=body.episode_b_id,
            variant_label=body.variant_label,
            notes=body.notes,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or both episodes not found.") from exc
    logger.info("ab_test_created", id=str(test.id), series_id=str(body.series_id))
    return _serialise(test)


@router.get("", response_model=list[ABTestResponse])
async def list_ab_tests(
    series_id: UUID | None = Query(None, description="Filter by series."),
    svc: ABTestService = Depends(_service),
) -> list[ABTestResponse]:
    rows = await svc.list_all(series_id)
    return [_serialise(t) for t in rows]


@router.get("/{test_id}", response_model=ABTestDetail)
async def get_ab_test(
    test_id: UUID,
    svc: ABTestService = Depends(_service),
) -> ABTestDetail:
    """Return the pair plus side-by-side YouTube view counts.

    View counts come from our local YouTubeUpload rows (populated by
    the upload + periodic refresh path). We deliberately don't call
    the Data API here to keep the page snappy — if the user wants
    fresh numbers they can hit YouTube → Analytics which does a live
    fetch.
    """
    try:
        test = await svc.get(test_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ab_test_not_found") from exc

    raw_stats = await svc.stats_for_pair(test)
    return ABTestDetail(
        **_serialise(test).model_dump(),
        episode_a_stats=(
            ABTestStats(**raw_stats[test.episode_a_id])
            if test.episode_a_id in raw_stats
            else _missing_stats(test.episode_a_id)
        ),
        episode_b_stats=(
            ABTestStats(**raw_stats[test.episode_b_id])
            if test.episode_b_id in raw_stats
            else _missing_stats(test.episode_b_id)
        ),
    )


@router.delete("/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ab_test(
    test_id: UUID,
    svc: ABTestService = Depends(_service),
) -> None:
    await svc.delete(test_id)
    logger.info("ab_test_deleted", id=str(test_id))
