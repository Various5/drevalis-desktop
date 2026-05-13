"""LLM cost tracker.

Surfaces the rolling token spend captured in ``generation_jobs.tokens_*``
as a $-equivalent the user sees in the dashboard. The rate comes from
``Settings.cost_per_1k_*_tokens_usd`` so the operator can match their
actual provider pricing.

Scope (v1): aggregate totals + daily series. Per-provider / per-model
breakdown ships when ``generation_jobs`` gets the ``llm_provider`` +
``llm_model`` columns — that's a follow-up.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.models.generation_job import GenerationJob

router = APIRouter(prefix="/api/v1/cost", tags=["cost"])


class CostDailyEntry(BaseModel):
    day: str
    tokens_prompt: int
    tokens_completion: int
    estimated_usd: float


class CostSummaryResponse(BaseModel):
    window_days: int
    tokens_prompt: int
    tokens_completion: int
    tokens_total: int
    estimated_usd: float
    rate_per_1k_prompt: float
    rate_per_1k_completion: float
    daily: list[CostDailyEntry]


def _estimate_usd(
    *,
    tokens_prompt: int,
    tokens_completion: int,
    settings: Settings,
) -> float:
    """Apply the configured per-1k rates and round to 4 dp.

    Rounding is at the response edge only — the underlying floats stay
    full-precision in case a frontend wants to do its own math.
    """
    return round(
        (tokens_prompt / 1000.0) * settings.cost_per_1k_prompt_tokens_usd
        + (tokens_completion / 1000.0) * settings.cost_per_1k_completion_tokens_usd,
        4,
    )


@router.get(
    "/summary",
    response_model=CostSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Estimated LLM spend over a rolling window",
)
async def cost_summary(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    days: int = Query(default=30, ge=1, le=365),
) -> CostSummaryResponse:
    """Return total LLM tokens + a $-equivalent for the last ``days``.

    Numbers are computed from completed ``generation_jobs`` rows so
    in-flight runs don't double-count. Rates come from the env-loaded
    settings; if the operator hasn't tuned them, the response will
    show generic defaults that are close to GPT-4o-mini pricing.
    """
    now = datetime.now(UTC)
    start = (now - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    rows = (
        await db.execute(
            select(
                GenerationJob.started_at,
                GenerationJob.tokens_prompt,
                GenerationJob.tokens_completion,
            )
            .where(GenerationJob.started_at >= start)
            .where(GenerationJob.started_at.is_not(None))
            .where(GenerationJob.completed_at.is_not(None))
        )
    ).all()

    daily: dict[str, dict[str, int]] = defaultdict(
        lambda: {"prompt": 0, "completion": 0}
    )
    total_prompt = 0
    total_completion = 0

    for row in rows:
        started: datetime = row.started_at
        # SQLite returns naive datetimes — normalise so the date()
        # bucket is timezone-stable across operator timezones.
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        day_key = started.date().isoformat()
        p = int(row.tokens_prompt or 0)
        c = int(row.tokens_completion or 0)
        daily[day_key]["prompt"] += p
        daily[day_key]["completion"] += c
        total_prompt += p
        total_completion += c

    daily_out: list[CostDailyEntry] = []
    for day_key in sorted(daily.keys()):
        bucket = daily[day_key]
        daily_out.append(
            CostDailyEntry(
                day=day_key,
                tokens_prompt=bucket["prompt"],
                tokens_completion=bucket["completion"],
                estimated_usd=_estimate_usd(
                    tokens_prompt=bucket["prompt"],
                    tokens_completion=bucket["completion"],
                    settings=settings,
                ),
            )
        )

    return CostSummaryResponse(
        window_days=days,
        tokens_prompt=total_prompt,
        tokens_completion=total_completion,
        tokens_total=total_prompt + total_completion,
        estimated_usd=_estimate_usd(
            tokens_prompt=total_prompt,
            tokens_completion=total_completion,
            settings=settings,
        ),
        rate_per_1k_prompt=settings.cost_per_1k_prompt_tokens_usd,
        rate_per_1k_completion=settings.cost_per_1k_completion_tokens_usd,
        daily=daily_out,
    )


# Tag the type with a usage hint for the OpenAPI docs.
_: Any = CostSummaryResponse
