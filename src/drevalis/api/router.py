"""Main API router -- aggregates all sub-routers under ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel

from drevalis.api.routes.ab_tests import router as ab_tests_router
from drevalis.api.routes.api_keys import router as api_keys_router
from drevalis.api.routes.assets import router as assets_router
from drevalis.api.routes.audiobooks import router as audiobooks_router
from drevalis.api.routes.auth import router as auth_router
from drevalis.api.routes.backup import router as backup_router
from drevalis.api.routes.character_packs import router as character_packs_router
from drevalis.api.routes.cloud_gpu import router as cloud_gpu_router
from drevalis.api.routes.comfyui import router as comfyui_router
from drevalis.api.routes.diagnostics import router as diagnostics_router
from drevalis.api.routes.editor import router as editor_router
from drevalis.api.routes.episodes import router as episodes_router
from drevalis.api.routes.events import router as events_router
from drevalis.api.routes.jobs import router as jobs_router
from drevalis.api.routes.license import router as license_router
from drevalis.api.routes.llm import router as llm_router
from drevalis.api.routes.metrics import router as metrics_router
from drevalis.api.routes.music import router as music_router
from drevalis.api.routes.onboarding import router as onboarding_router
from drevalis.api.routes.prompt_templates import router as prompt_templates_router
from drevalis.api.routes.runpod import router as runpod_router
from drevalis.api.routes.schedule import router as schedule_router
from drevalis.api.routes.series import router as series_router
from drevalis.api.routes.settings import router as settings_router
from drevalis.api.routes.social import router as social_router
from drevalis.api.routes.updates import router as updates_router
from drevalis.api.routes.video_ingest import router as video_ingest_router
from drevalis.api.routes.video_templates import router as video_templates_router
from drevalis.api.routes.voice_profiles import router as voice_profiles_router
from drevalis.api.routes.youtube import router as youtube_router

# -- Top-level router ------------------------------------------------------
router = APIRouter()

# -- Health check (no prefix) ---------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["health"],
)
async def health_check() -> HealthResponse:
    """Liveness / readiness probe."""
    return HealthResponse()


# -- Include all sub-routers ----------------------------------------------
router.include_router(series_router)
router.include_router(episodes_router)
router.include_router(voice_profiles_router)
router.include_router(audiobooks_router)
router.include_router(comfyui_router)
router.include_router(llm_router)
router.include_router(prompt_templates_router)
router.include_router(jobs_router)
router.include_router(license_router)
router.include_router(updates_router)
router.include_router(metrics_router)
router.include_router(settings_router)
router.include_router(api_keys_router)
router.include_router(runpod_router)
router.include_router(social_router)
router.include_router(youtube_router)
router.include_router(schedule_router)
router.include_router(video_templates_router)
router.include_router(backup_router)
router.include_router(onboarding_router)
router.include_router(music_router)
router.include_router(ab_tests_router)
router.include_router(cloud_gpu_router)
router.include_router(auth_router)
router.include_router(assets_router)
router.include_router(video_ingest_router)
router.include_router(editor_router)
router.include_router(character_packs_router)
router.include_router(diagnostics_router)
router.include_router(events_router)
