"""First-run onboarding status + dismissal.

A brand-new install lands on an empty dashboard with no ComfyUI
server, no LLM endpoint, and no voice profile configured — the user
has no idea what to click first. The onboarding wizard fills that
gap by walking them through the four required setup steps before
any generation can succeed.

This module exposes:

- ``GET  /api/v1/onboarding/status``    current setup completeness
                                         + whether the user has
                                         explicitly dismissed the
                                         wizard.
- ``POST /api/v1/onboarding/dismiss``   set the "don't show me again"
                                         flag.
- ``POST /api/v1/onboarding/reset``     clear the flag so the wizard
                                         pops back up on next load
                                         (used by Help → "Re-run
                                         onboarding").

Dismissed state lives in Redis under key ``onboarding:dismissed``
rather than its own Postgres table — it's a single boolean that
never takes part in joins, Redis is cheaper, and skipping a
migration keeps the upgrade path painless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select

from drevalis.core.database import get_db_session
from drevalis.core.deps import get_redis
from drevalis.models.comfyui import ComfyUIServer
from drevalis.models.llm_config import LLMConfig
from drevalis.models.voice_profile import VoiceProfile
from drevalis.models.youtube_channel import YouTubeChannel

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

_REDIS_KEY = "onboarding:dismissed"


class OnboardingStatusResponse(BaseModel):
    comfyui_servers: int
    llm_configs: int
    voice_profiles: int
    youtube_channels: int
    dismissed: bool
    # True when the wizard should be shown on page load: not dismissed
    # AND at least one of the critical three (comfyui / llm / voice)
    # is still empty. YouTube is optional.
    should_show: bool


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> OnboardingStatusResponse:
    async def _count(model: type) -> int:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one() or 0)

    comfyui_n = await _count(ComfyUIServer)
    llm_n = await _count(LLMConfig)
    voice_n = await _count(VoiceProfile)
    yt_n = await _count(YouTubeChannel)

    dismissed_raw = await redis.get(_REDIS_KEY)
    dismissed = bool(dismissed_raw)

    critical_missing = (comfyui_n == 0) or (llm_n == 0) or (voice_n == 0)

    return OnboardingStatusResponse(
        comfyui_servers=comfyui_n,
        llm_configs=llm_n,
        voice_profiles=voice_n,
        youtube_channels=yt_n,
        dismissed=dismissed,
        should_show=(not dismissed) and critical_missing,
    )


@router.post("/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_onboarding(redis: Redis = Depends(get_redis)) -> None:
    """Mark the wizard as dismissed. Survives container restarts because
    Redis is persisted via the stack's named volume (where configured)
    and because any future container start will just see the key and
    not nag the user again."""
    await redis.set(_REDIS_KEY, "1")


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_onboarding(redis: Redis = Depends(get_redis)) -> None:
    """Clear the dismissed flag. Used by the "Re-run onboarding" button
    in Help so the user can re-open the wizard without rummaging."""
    await redis.delete(_REDIS_KEY)
