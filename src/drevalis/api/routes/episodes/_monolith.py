"""Episodes API router -- CRUD, generation, retry, script management, and export."""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.concurrency import effective_max_concurrent_generations
from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_redis, get_settings
from drevalis.core.license.deprecation import apply_deprecation_headers
from drevalis.core.redis import get_arq_pool
from drevalis.models.episode import Episode
from drevalis.schemas.episode import (
    BulkGenerateRequest,
    BulkGenerateResponse,
    EpisodeCreate,
    EpisodeListResponse,
    EpisodeResponse,
    EpisodeUpdate,
    GenerateRequest,
    GenerateResponse,
    RetryResponse,
    ScriptUpdate,
    SetMusicRequest,
    VideoEditRequest,
    VideoEditResponse,
)
from drevalis.schemas.script import EpisodeScript
from drevalis.services.episode import (
    ConcurrencyCapReachedError,
    EpisodeInvalidStatusError,
    EpisodeNoScriptError,
    EpisodeNotFoundError,
    EpisodeService,
    NoFailedJobError,
    SceneNotFoundError,
    ScriptValidationError,
)
from drevalis.services.storage import LocalStorage


def _episode_service(db: AsyncSession = Depends(get_db)) -> EpisodeService:
    return EpisodeService(db)


logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/episodes", tags=["episodes"])

# ── Helper: build EpisodeResponse with relations ─────────────────────────


def _episode_to_response(episode: Episode) -> EpisodeResponse:
    """Convert an Episode ORM object (with relations loaded) to a response."""
    return EpisodeResponse.model_validate(episode)


def _episode_to_list(episode: Episode) -> EpisodeListResponse:
    """Convert an Episode ORM object to a list response."""
    return EpisodeListResponse.model_validate(episode)


# ── Recent episodes (must be before /{episode_id} to avoid path conflict) ─


@router.get(
    "/recent",
    response_model=list[EpisodeListResponse],
    status_code=status.HTTP_200_OK,
    summary="Recent episodes across all series",
)
async def list_recent_episodes(
    limit: int = Query(default=10, ge=1, le=100),
    svc: EpisodeService = Depends(_episode_service),
) -> list[EpisodeListResponse]:
    """Return the most recently created episodes across all series."""
    episodes = await svc.list_recent(limit)
    return [_episode_to_list(ep) for ep in episodes]


# ── List episodes ─────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[EpisodeListResponse],
    status_code=status.HTTP_200_OK,
    summary="List episodes (filter by series_id, status)",
)
async def list_episodes(
    series_id: UUID | None = Query(default=None),
    status_filter: Literal["draft", "generating", "review", "editing", "exported", "failed"]
    | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    svc: EpisodeService = Depends(_episode_service),
) -> list[EpisodeListResponse]:
    """List episodes, optionally filtered by series and/or status."""
    episodes = await svc.list_filtered(
        series_id=series_id,
        status_filter=status_filter,
        offset=offset,
        limit=limit,
    )
    return [_episode_to_list(ep) for ep in episodes]


# ── Create episode ────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=EpisodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new episode (draft status)",
)
async def create_episode(
    payload: EpisodeCreate,
    svc: EpisodeService = Depends(_episode_service),
) -> EpisodeResponse:
    """Create a new episode in draft status."""
    episode = await svc.create(
        series_id=payload.series_id,
        title=payload.title,
        topic=payload.topic,
    )
    return _episode_to_response(episode)


# ── Bulk generate ─────────────────────────────────────────────────────────


@router.post(
    "/bulk-generate",
    response_model=BulkGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue generation for multiple episodes at once",
    description=(
        "Accepts a list of episode UUIDs and enqueues the full generation pipeline "
        "for each one that is in ``draft`` or ``failed`` status. Episodes in any "
        "other status, or those that would exceed the concurrency cap, are silently "
        "skipped and reported in the ``skipped_ids`` list."
    ),
)
async def bulk_generate(
    payload: BulkGenerateRequest,
    svc: EpisodeService = Depends(_episode_service),
    settings: Settings = Depends(get_settings),
) -> BulkGenerateResponse:
    """Enqueue the full generation pipeline for each eligible episode.

    Only episodes with ``draft`` or ``failed`` status are eligible. The
    concurrency gate is applied per-episode: once ``MAX_CONCURRENT_GENERATIONS``
    is reached, remaining episodes are skipped rather than raising an error.
    """
    queued_ids, skipped_ids = await svc.bulk_generate(
        payload.episode_ids,
        effective_max_concurrent_generations(settings.max_concurrent_generations),
    )
    return BulkGenerateResponse(
        queued=len(queued_ids),
        skipped=len(skipped_ids),
        total=len(payload.episode_ids),
        queued_ids=queued_ids,
        skipped_ids=skipped_ids,
    )


# ── Get episode detail ────────────────────────────────────────────────────


@router.get(
    "/{episode_id}",
    response_model=EpisodeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get episode with assets and jobs",
)
async def get_episode(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> EpisodeResponse:
    """Fetch a single episode by ID with media assets and generation jobs."""
    try:
        episode = await svc.get_with_assets_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc
    return _episode_to_response(episode)


# ── Update episode ────────────────────────────────────────────────────────


@router.put(
    "/{episode_id}",
    response_model=EpisodeResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an episode",
)
async def update_episode(
    episode_id: UUID,
    payload: EpisodeUpdate,
    svc: EpisodeService = Depends(_episode_service),
) -> EpisodeResponse:
    """Update an existing episode. Only provided (non-None) fields are changed."""
    update_data = payload.model_dump(exclude_unset=True)
    try:
        episode = await svc.update(episode_id, update_data)
    except ScriptValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc
    return _episode_to_response(episode)


# ── Delete episode ────────────────────────────────────────────────────────


@router.delete(
    "/{episode_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an episode and cleanup files",
)
async def delete_episode(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> None:
    """Delete an episode, its generation jobs, media assets, and storage files."""
    storage = LocalStorage(settings.storage_base_path)
    try:
        await svc.delete(episode_id, storage_delete_dir=storage.delete_episode_dir)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc


# ── Generate episode ──────────────────────────────────────────────────────


@router.post(
    "/{episode_id}/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Kick off the generation pipeline",
)
async def generate_episode(
    episode_id: UUID,
    payload: GenerateRequest | None = None,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> GenerateResponse:
    """Enqueue generation jobs for the episode's pipeline steps."""
    from drevalis.core.license.quota import check_and_increment_episode_quota
    from drevalis.core.redis import get_redis as _get_redis_gen

    async for _redis in _get_redis_gen():
        await check_and_increment_episode_quota(_redis)
        break

    requested_steps: list[str] | None = list(payload.steps) if payload and payload.steps else None
    try:
        job_ids = await svc.generate(
            episode_id,
            requested_steps,
            effective_max_concurrent_generations(settings.max_concurrent_generations),
        )
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc
    except EpisodeInvalidStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Episode is in '{exc.current_status}' status and cannot be regenerated. "
                "Only 'draft' or 'failed' episodes can be generated."
            ),
        ) from exc
    except ConcurrencyCapReachedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    return GenerateResponse(
        episode_id=episode_id,
        job_ids=job_ids,
        message=f"Generation enqueued with {len(job_ids)} steps",
    )


# ── Retry from failed step ───────────────────────────────────────────────


@router.post(
    "/{episode_id}/retry",
    response_model=RetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry from the first failed step",
)
async def retry_episode(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> RetryResponse:
    """Find the first failed generation job and re-enqueue it."""
    try:
        job_id, step = await svc.retry_first_failed(
            episode_id, effective_max_concurrent_generations(settings.max_concurrent_generations)
        )
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc
    except ConcurrencyCapReachedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except NoFailedJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No failed jobs found for this episode",
        ) from exc
    return RetryResponse(
        episode_id=episode_id,
        job_id=job_id,
        step=step,
        message=f"Retry enqueued for step '{step}'",
    )


# ── Retry specific step ──────────────────────────────────────────────────


@router.post(
    "/{episode_id}/retry/{step}",
    response_model=RetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a specific pipeline step",
)
async def retry_episode_step(
    episode_id: UUID,
    step: Literal["script", "voice", "scenes", "captions", "assembly", "thumbnail"],
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> RetryResponse:
    """Re-enqueue a specific pipeline step for the episode."""
    try:
        job_id = await svc.retry_step(
            episode_id,
            step,
            effective_max_concurrent_generations(settings.max_concurrent_generations),
        )
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc
    except ConcurrencyCapReachedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    return RetryResponse(
        episode_id=episode_id,
        job_id=job_id,
        step=step,
        message=f"Retry enqueued for step '{step}'",
    )


# ── Get episode script ───────────────────────────────────────────────────


@router.get(
    "/{episode_id}/script",
    response_model=dict | None,
    status_code=status.HTTP_200_OK,
    summary="Get just the script",
)
async def get_episode_script(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any] | None:
    """Return the script JSONB field for an episode."""
    try:
        return await svc.get_script(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc


# ── Update episode script ────────────────────────────────────────────────


@router.put(
    "/{episode_id}/script",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Update the script",
)
async def update_episode_script(
    episode_id: UUID,
    payload: ScriptUpdate,
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Validate and persist a new script for the episode."""
    try:
        return await svc.update_script(episode_id, payload.script)
    except ScriptValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc


# ── Update a single scene ─────────────────────────────────────────────


@router.put(
    "/{episode_id}/scenes/{scene_number}",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Update a single scene in the episode script",
)
async def update_scene(
    episode_id: UUID,
    scene_number: int,
    payload: dict[str, Any],
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Modify fields of a specific scene within the episode's script JSONB.

    Accepted payload keys: ``narration``, ``visual_prompt``,
    ``duration_seconds``, ``keywords``. Only provided keys are changed.
    """
    try:
        scene_dump = await svc.update_scene(episode_id, scene_number, payload)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found or has no script",
        ) from exc
    except SceneNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_number} not found",
        ) from exc
    return {"message": f"Scene {scene_number} updated", "scene": scene_dump}


# ── Delete a scene ────────────────────────────────────────────────────


@router.delete(
    "/{episode_id}/scenes/{scene_number}",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Remove a scene from the episode script",
)
async def delete_scene(
    episode_id: UUID,
    scene_number: int,
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Delete a scene from the script and remove associated media assets."""
    try:
        remaining, deleted_count = await svc.delete_scene(episode_id, scene_number)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found or has no script",
        ) from exc
    except SceneNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_number} not found",
        ) from exc
    except ScriptValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return {
        "message": f"Scene {scene_number} deleted",
        "remaining_scenes": remaining,
        "media_assets_deleted": deleted_count,
    }


# ── Reorder scenes ───────────────────────────────────────────────────


@router.post(
    "/{episode_id}/scenes/reorder",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Reorder scenes in the episode script",
)
async def reorder_scenes(
    episode_id: UUID,
    payload: dict[str, Any],
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Reorder scenes by providing the desired scene number order.

    Payload: ``{"order": [3, 1, 2, 5, 4, 6]}``
    """
    order = payload.get("order")
    if not order or not isinstance(order, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Payload must include 'order' as a list of scene numbers",
        )
    try:
        new_order = await svc.reorder_scenes(episode_id, order)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found or has no script",
        ) from exc
    except ScriptValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return {"message": "Scenes reordered", "order": new_order}


# ── Split / merge scenes (script-only edits, no re-run) ────────────────────


@router.post(
    "/{episode_id}/scenes/{scene_number}/split",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Split one scene into two at a narration character offset",
)
async def split_scene(
    episode_id: UUID,
    scene_number: int,
    payload: dict[str, Any],
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Split scene ``scene_number`` at ``char_offset`` inside its narration."""
    char_offset = payload.get("char_offset")
    try:
        total_scenes = await svc.split_scene(
            episode_id,
            scene_number,
            int(char_offset) if char_offset is not None else None,
        )
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found or has no script",
        ) from exc
    except SceneNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_number} not found",
        ) from exc
    except ScriptValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return {"message": f"Scene {scene_number} split", "total_scenes": total_scenes}


@router.post(
    "/{episode_id}/scenes/merge",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Merge two adjacent scenes into one",
)
async def merge_scenes(
    episode_id: UUID,
    payload: dict[str, Any],
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Merge scene ``scene_number`` with the scene immediately after it."""
    target = int(payload.get("scene_number") or 0)
    try:
        total_scenes = await svc.merge_scenes(episode_id, target)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found or has no script",
        ) from exc
    except ScriptValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return {
        "message": f"Scenes {target} and {target + 1} merged",
        "total_scenes": total_scenes,
    }


# ── Regenerate a single scene's image ────────────────────────────────


@router.post(
    "/{episode_id}/regenerate-scene/{scene_number}",
    response_model=dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Regenerate a single scene's image and reassemble",
)
async def regenerate_scene(
    episode_id: UUID,
    scene_number: int,
    payload: dict[str, Any] | None = None,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Enqueue a job to regenerate a single scene's image/video.

    Optionally accepts ``{"visual_prompt": "new prompt"}`` to override
    the prompt before regenerating. After the scene is regenerated,
    the video is automatically reassembled.
    """
    visual_prompt_override = payload.get("visual_prompt") if payload else None
    try:
        job_ids = await svc.regenerate_scene(
            episode_id,
            scene_number,
            visual_prompt_override,
            effective_max_concurrent_generations(settings.max_concurrent_generations),
        )
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found or has no script",
        ) from exc
    except SceneNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_number} not found",
        ) from exc
    except ConcurrencyCapReachedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    return {
        "message": f"Scene {scene_number} regeneration enqueued",
        "episode_id": str(episode_id),
        "scene_number": scene_number,
        "job_ids": [str(j) for j in job_ids],
    }


# ── Regenerate voice ─────────────────────────────────────────────────


@router.post(
    "/{episode_id}/regenerate-voice",
    response_model=dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run voice + captions + assembly",
    description=(
        "Re-runs voice synthesis, captions, and assembly while keeping scene images. "
        "Optional query parameters allow overriding the voice profile, speed, and pitch "
        "for this regeneration without permanently changing the series configuration."
    ),
)
async def regenerate_voice(
    episode_id: UUID,
    voice_profile_id: UUID | None = Query(
        None,
        description="Override voice profile for this regeneration only",
    ),
    speed: float | None = Query(
        None,
        ge=0.5,
        le=2.0,
        description="Playback speed multiplier override (0.5–2.0)",
    ),
    pitch: float | None = Query(
        None,
        ge=-12.0,
        le=12.0,
        description="Pitch shift in semitones override (-12 to +12)",
    ),
    payload: dict[str, Any] | None = None,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Enqueue a job to re-run voice synthesis, captions, and assembly.

    Scene images are kept. Useful when changing voice profiles or editing
    narration text.

    Override precedence: query parameters take priority over the JSON body's
    ``voice_profile_id`` field, which itself takes priority over the episode's
    existing stored override.

    Args:
        episode_id: UUID of the episode to regenerate.
        voice_profile_id: Query-param override for the voice profile.
        speed: Query-param speed multiplier (stored in episode ``metadata_``).
        pitch: Query-param pitch shift in semitones (stored in episode ``metadata_``).
        payload: Optional JSON body; legacy ``voice_profile_id`` key still accepted.
        db: Injected async database session.
        settings: Injected application settings.

    Returns:
        Confirmation dict with the enqueued job IDs.

    Raises:
        HTTPException 404: if the episode does not exist or has no script.
        HTTPException 429: if the concurrency cap is reached.
    """
    resolved_vp_id: UUID | None = voice_profile_id
    if resolved_vp_id is None and payload and "voice_profile_id" in payload:
        resolved_vp_id = payload["voice_profile_id"]

    try:
        job_ids = await svc.regenerate_voice(
            episode_id,
            voice_profile_id=resolved_vp_id,
            speed=speed,
            pitch=pitch,
            base_max=effective_max_concurrent_generations(settings.max_concurrent_generations),
        )
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found or has no script",
        ) from exc
    except ConcurrencyCapReachedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    return {
        "message": "Voice regeneration enqueued (voice + captions + assembly + thumbnail)",
        "episode_id": str(episode_id),
        "job_ids": [str(j) for j in job_ids],
    }


# ── Reassemble ───────────────────────────────────────────────────────


@router.post(
    "/{episode_id}/reassemble",
    response_model=dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run captions + assembly + thumbnail",
)
async def reassemble(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Enqueue a job to re-run captions, assembly, and thumbnail extraction."""
    try:
        job_ids = await svc.reassemble(
            episode_id, effective_max_concurrent_generations(settings.max_concurrent_generations)
        )
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found or has no script",
        ) from exc
    except ConcurrencyCapReachedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    return {
        "message": "Reassembly enqueued (captions + assembly + thumbnail)",
        "episode_id": str(episode_id),
        "job_ids": [str(j) for j in job_ids],
    }


# ── Regenerate captions ───────────────────────────────────────────────────


@router.post(
    "/{episode_id}/regenerate-captions",
    response_model=dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Change caption style and reassemble",
    description=(
        "Stores the requested caption style preset on the episode as an override, "
        "then enqueues a reassembly job (captions + assembly + thumbnail). "
        "Voice audio and scene images are kept. "
        "Valid preset names match those understood by the CaptionService "
        "(e.g. ``youtube_highlight``, ``minimal``, ``karaoke``)."
    ),
)
async def regenerate_captions(
    episode_id: UUID,
    caption_style: str = Query(
        "youtube_highlight",
        description="Caption style preset name to apply before reassembling",
    ),
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Store a new caption style override and enqueue reassembly."""
    try:
        job_ids = await svc.regenerate_captions(
            episode_id,
            caption_style,
            effective_max_concurrent_generations(settings.max_concurrent_generations),
        )
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found or has no script",
        ) from exc
    except ConcurrencyCapReachedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    return {
        "message": f"Caption style '{caption_style}' applied; reassembly enqueued",
        "episode_id": str(episode_id),
        "caption_style": caption_style,
        "job_ids": [str(j) for j in job_ids],
    }


# ── Cost estimation ─────────────────────────────────────────────────


@router.post(
    "/{episode_id}/estimate-cost",
    status_code=status.HTTP_200_OK,
    summary="Estimate generation cost for an episode",
)
async def estimate_cost(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Estimate TTS cost and duration for generating this episode."""
    try:
        return await svc.estimate_cost(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(404, f"Episode {episode_id} not found") from exc


# ── Duplicate episode ────────────────────────────────────────────────


@router.post(
    "/{episode_id}/duplicate",
    response_model=EpisodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate an episode as a new draft",
)
async def duplicate_episode(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> EpisodeResponse:
    """Create a copy of the episode with ``draft`` status and the same script."""
    try:
        new_episode = await svc.duplicate(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc
    return _episode_to_response(new_episode)


# ── Reset to draft ───────────────────────────────────────────────────


@router.post(
    "/{episode_id}/reset",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Reset episode to draft status",
)
async def reset_episode(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Reset the episode to ``draft`` status, clearing all generation jobs."""
    try:
        deleted_jobs = await svc.reset_to_draft(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc
    return {
        "message": "Episode reset to draft",
        "episode_id": str(episode_id),
        "jobs_deleted": deleted_jobs,
    }


# ── Cancel generation ───────────────────────────────────────────────


@router.post(
    "/{episode_id}/cancel",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Cancel a generating episode",
)
async def cancel_episode(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Cancel an in-progress generation for the episode."""
    try:
        cancelled_jobs = await svc.cancel(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc
    except EpisodeInvalidStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Episode is in '{exc.current_status}' status, not 'generating'. "
                "Only generating episodes can be cancelled."
            ),
        ) from exc
    return {
        "message": "Episode generation cancelled",
        "episode_id": str(episode_id),
        "cancelled_jobs": cancelled_jobs,
    }


# ── Music tab endpoints ───────────────────────────────────────────────────

# Maximum AceStep generation duration in seconds (AceStep hard cap).
_ACESTEP_MAX_DURATION_SECONDS: float = 120.0

# Audio extensions scanned when listing music tracks for an episode.
_AUDIO_EXTENSIONS: tuple[str, ...] = (".mp3", ".wav", ".ogg", ".flac")


async def _ffprobe_duration(path: Path, ffprobe_exe: str = "ffprobe") -> float:
    """Return the duration of an audio/video file in seconds via ffprobe.

    Args:
        path: Absolute path to the audio file.
        ffprobe_exe: Name or path of the ffprobe binary.

    Returns:
        Duration in seconds, or 0.0 if ffprobe fails or the file has no
        parseable duration.
    """
    cmd = [
        ffprobe_exe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return 0.0
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0


@router.get(
    "/{episode_id}/music/moods",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="List available music mood options",
    description=(
        "Returns the full set of mood keywords understood by the AceStep music "
        "generator, with human-readable labels and truncated tag descriptions."
    ),
)
async def list_music_moods(episode_id: UUID) -> dict[str, Any]:
    """Return the static mood catalogue from the music service.

    The ``episode_id`` path parameter is accepted for URL consistency with the
    other music endpoints but is not used — moods are global, not per-episode.
    """
    from drevalis.services.music import _MOOD_TAGS

    moods = [
        {
            "value": key,
            "label": key.replace("_", " ").title(),
            "description": tags[:80],
        }
        for key, tags in _MOOD_TAGS.items()
    ]
    return {"moods": moods}


@router.get(
    "/{episode_id}/music",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="List available music tracks for an episode",
    description=(
        "Scans ``storage/episodes/{episode_id}/music/`` and "
        "``storage/music/generated/`` for audio files and returns their "
        "relative paths and ffprobe-measured durations."
    ),
)
async def list_episode_music(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """List all music tracks available for the given episode."""
    try:
        return await svc.list_music_tracks(
            episode_id,
            settings.storage_base_path,
            _ffprobe_duration,
            _AUDIO_EXTENSIONS,
        )
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc


@router.post(
    "/{episode_id}/music/generate",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Generate a background music track via AceStep / ComfyUI",
    description=(
        "Submits an AceStep 1.5 workflow to the first active ComfyUI server, "
        "polls for completion, downloads the resulting MP3, and saves it to "
        "``storage/episodes/{episode_id}/music/``.  Returns the relative path "
        "and measured duration of the new track."
    ),
)
async def generate_episode_music(
    episode_id: UUID,
    payload: dict[str, Any],
    redis: ArqRedis = Depends(get_redis),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Enqueue music generation as a background job."""
    try:
        await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc

    mood = payload.get("mood")
    if not mood or not isinstance(mood, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'mood' is required and must be a non-empty string.",
        )
    mood = mood.lower().strip()

    raw_duration = payload.get("duration", 30)
    try:
        duration_seconds = float(raw_duration)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'duration' must be a number (seconds).",
        ) from None
    if not (1.0 <= duration_seconds <= _ACESTEP_MAX_DURATION_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"'duration' must be between 1 and {int(_ACESTEP_MAX_DURATION_SECONDS)} seconds."
            ),
        )

    await redis.enqueue_job(
        "generate_episode_music",
        str(episode_id),
        mood,
        duration_seconds,
    )

    return {"status": "queued", "message": "Music generation started in background"}


@router.post(
    "/{episode_id}/music/select",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Select a music track for the episode's next assembly",
    description=(
        "Persists ``selected_music_path`` in the episode's ``metadata_`` JSONB "
        "field.  The pipeline's assembly step reads this field and uses the "
        "specified track instead of auto-generating music."
    ),
)
async def select_episode_music(
    episode_id: UUID,
    payload: dict[str, Any],
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Store the user's chosen music track on the episode record."""
    if "music_path" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'music_path' is required (pass null to clear the selection).",
        )

    music_path: str | None = payload["music_path"]

    if music_path is not None:
        resolved = settings.storage_base_path / music_path
        if not resolved.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Music file not found at storage path '{music_path}'.",
            )

    try:
        selected = await svc.select_music(episode_id, music_path)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc

    return {
        "episode_id": str(episode_id),
        "selected_music_path": selected,
        "message": (f"Music track selected: {selected}" if selected else "Music selection cleared"),
    }


# ── Set music settings ────────────────────────────────────────────────────


@router.post(
    "/{episode_id}/set-music",
    response_model=dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Configure background music and optionally reassemble",
    description=(
        "Stores ``music_enabled``, ``music_mood``, and ``music_volume_db`` in the "
        "episode's ``metadata_`` JSONB under the ``music_settings`` key. "
        "When ``reassemble`` is ``true`` (the default), a reassembly job is also "
        "enqueued so the change takes effect immediately in the output video."
    ),
)
async def set_music(
    episode_id: UUID,
    payload: SetMusicRequest,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Store music configuration on the episode and optionally trigger reassembly."""
    try:
        return await svc.set_music(
            episode_id,
            music_enabled=payload.music_enabled,
            music_mood=payload.music_mood,
            music_volume_db=payload.music_volume_db,
            reassemble=payload.reassemble,
            base_max=effective_max_concurrent_generations(settings.max_concurrent_generations),
        )
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc
    except ConcurrencyCapReachedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc


# ── Export helpers ────────────────────────────────────────────────────────


def _sanitize_filename(series_name: str, episode_title: str) -> str:
    """Build a filesystem-safe filename from series and episode names."""
    raw = f"{series_name}_{episode_title}"
    safe = re.sub(r"[^\w\s-]", "", raw)
    safe = re.sub(r"\s+", "_", safe.strip())
    return safe[:100] or "export"


async def _load_episode_with_series(episode_id: UUID, svc: EpisodeService) -> Episode:
    """Thin wrapper around ``EpisodeService.get_with_series_or_raise``
    that maps NotFound → 404 so the export endpoints stay terse."""
    try:
        return await svc.get_with_series_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc


def _build_description(episode: Episode) -> str:
    """Build a text description from the episode's script and series metadata."""
    script = None
    if episode.script:
        try:
            script = EpisodeScript.model_validate(episode.script)
        except Exception:
            pass

    lines: list[str] = []
    lines.append(script.title if script else episode.title)
    lines.append("")

    if script and script.description:
        lines.append(script.description)
        lines.append("")

    if script and script.hashtags:
        lines.append(" ".join(f"#{tag}" for tag in script.hashtags))
        lines.append("")

    series_name = episode.series.name if episode.series else "N/A"
    lines.append(f"Series: {series_name}")
    lines.append("")

    lines.append("--- Script ---")
    if script:
        for scene in script.scenes:
            lines.append(f"\n[Scene {scene.scene_number}]")
            lines.append(scene.narration)

    return "\n".join(lines)


# ── Export video ─────────────────────────────────────────────────────────


@router.get(
    "/{episode_id}/export/video",
    status_code=status.HTTP_200_OK,
    summary="Download the final video with a friendly filename",
    tags=["export"],
)
async def export_video(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> FileResponse:
    """Serve the episode's final video file with a sanitized filename."""
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    rel = await svc.get_video_asset_path(episode_id)
    if rel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode",
        )
    video_path = Path(settings.storage_base_path) / rel
    if not video_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file not found on disk",
        )

    logger.info("export_video", episode_id=str(episode_id), path=str(video_path))
    return FileResponse(
        path=str(video_path),
        filename=f"{safe_name}.mp4",
        media_type="video/mp4",
    )


# ── Export thumbnail ─────────────────────────────────────────────────────


@router.get(
    "/{episode_id}/export/thumbnail",
    status_code=status.HTTP_200_OK,
    summary="Download the thumbnail image with a friendly filename",
    tags=["export"],
)
async def export_thumbnail(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> FileResponse:
    """Serve the episode's thumbnail image with a sanitized filename."""
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    rel = await svc.get_thumbnail_asset_path(episode_id)
    if rel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No thumbnail asset found for this episode",
        )
    thumb_path = Path(settings.storage_base_path) / rel
    if not thumb_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail file not found on disk",
        )

    logger.info("export_thumbnail", episode_id=str(episode_id), path=str(thumb_path))
    return FileResponse(
        path=str(thumb_path),
        filename=f"{safe_name}_thumbnail.jpg",
        media_type="image/jpeg",
    )


# ── Upload custom thumbnail ──────────────────────────────────────────────


@router.post(
    "/{episode_id}/thumbnail",
    status_code=status.HTTP_200_OK,
    summary="Replace the episode's thumbnail with a user-uploaded image",
    tags=["thumbnail"],
)
async def upload_thumbnail(
    episode_id: UUID,
    file: UploadFile = File(
        ...,
        description="PNG or JPEG. Max 4 MB. Saved as storage/episodes/{id}/output/thumbnail.jpg.",
    ),
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Accept a user-edited thumbnail image and replace the episode's
    thumbnail asset.

    Used by the in-app thumbnail editor — the frontend renders the
    composited image (base + text overlay) on a Canvas, exports to PNG,
    and POSTs the blob here. Any previous thumbnail MediaAsset rows are
    deleted so the freshly-uploaded file is the single source of truth.
    """
    # 1. Validate input.
    content_type = (file.content_type or "").lower()
    if content_type not in ("image/png", "image/jpeg", "image/jpg"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error": "unsupported_image_type",
                "hint": "Upload a PNG or JPEG.",
                "received": content_type or "(missing)",
            },
        )

    # Stream into memory up to 4 MiB; abort larger files so a malformed
    # client can't flood the disk.
    MAX_BYTES = 4 * 1024 * 1024
    data = bytearray()
    while chunk := await file.read(64 * 1024):
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "error": "thumbnail_too_large",
                    "hint": f"Max {MAX_BYTES // 1024 // 1024} MB.",
                },
            )

    # 2. Load episode, ensure the output directory exists.
    try:
        await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="episode_not_found",
        ) from exc

    base = Path(settings.storage_base_path)
    rel_path = f"episodes/{episode_id}/output/thumbnail.jpg"
    abs_path = base / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    # 3. Re-encode to JPEG so YouTube (which caps thumbs at 2MB JPEG)
    #    always accepts it regardless of what the browser sent.
    from io import BytesIO

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - Pillow ships with the image deps
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pillow not installed; thumbnail editor requires it",
        ) from exc

    try:
        img: Any = Image.open(BytesIO(bytes(data)))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        img.save(abs_path, format="JPEG", quality=92, optimize=True)
    except Exception as exc:
        logger.error("thumbnail_upload_decode_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not decode uploaded image.",
        ) from exc

    file_size = abs_path.stat().st_size

    # 4. Point the MediaAsset + episode metadata at the new file.
    new_asset = await svc.replace_thumbnail_asset(
        episode_id, rel_path=rel_path, file_size=file_size
    )

    logger.info(
        "thumbnail_uploaded",
        episode_id=str(episode_id),
        size_bytes=file_size,
        asset_id=str(new_asset.id),
    )
    return {
        "message": "Thumbnail replaced.",
        "asset_id": str(new_asset.id),
        "file_path": rel_path,
        "size_bytes": file_size,
    }


# ── Export description ───────────────────────────────────────────────────


@router.get(
    "/{episode_id}/export/description",
    status_code=status.HTTP_200_OK,
    summary="Download a text description file for the episode",
    tags=["export"],
)
async def export_description(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> Response:
    """Generate and serve a plain-text description file with title, description,
    hashtags, series info, and full script narration."""
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    content = _build_description(episode)

    logger.info("export_description", episode_id=str(episode_id))
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_description.txt"',
        },
    )


# ── Export bundle (ZIP) ──────────────────────────────────────────────────


@router.get(
    "/{episode_id}/export/bundle",
    status_code=status.HTTP_200_OK,
    summary="Download a ZIP bundle with video, thumbnail, description, and captions",
    tags=["export"],
)
async def export_bundle(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> Response:
    """Create an in-memory ZIP archive containing the video, thumbnail,
    description text, and SRT captions (when available)."""
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    base = Path(settings.storage_base_path)
    video_rel = await svc.get_video_asset_path(episode_id)
    thumb_rel = await svc.get_thumbnail_asset_path(episode_id)
    caption_rel = await svc.get_caption_asset_path(episode_id)

    if video_rel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode; cannot create bundle",
        )

    description_content = _build_description(episode)
    video_path = base / video_rel
    thumb_path = (base / thumb_rel) if thumb_rel else None
    srt_path = (base / caption_rel) if caption_rel else None

    def _build() -> bytes:
        # MP4/JPG/SRT are already compressed (or tiny); ZIP_STORED keeps
        # the bundle ~the same size and skips the DEFLATE CPU cost
        # which previously blocked the uvicorn event loop for several
        # seconds on a 100 MB+ video.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            if video_path.exists():
                zf.write(str(video_path), f"{safe_name}.mp4")
            if thumb_path and thumb_path.exists():
                zf.write(str(thumb_path), f"{safe_name}_thumbnail.jpg")
            zf.writestr(f"{safe_name}_description.txt", description_content)
            if srt_path and srt_path.exists():
                zf.write(str(srt_path), f"{safe_name}_captions.srt")
        return buf.getvalue()

    # Run in a thread so file I/O and ZipFile.write() don't block the
    # event loop while the uvicorn worker waits on a large MP4.
    payload = await asyncio.to_thread(_build)

    logger.info("export_bundle", episode_id=str(episode_id), zip_size=len(payload))
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_bundle.zip"',
        },
    )


class SEOCheck(BaseModel):
    id: str
    label: str
    pass_: bool = Field(alias="pass")
    severity: str  # "ok" | "warn" | "error" | "info"
    hint: str

    model_config = {"populate_by_name": True}


class SEOScoreResponse(BaseModel):
    overall_score: int  # 0 - 100
    grade: str  # "A" | "B" | "C" | "D"
    summary: str
    has_seo_metadata: bool
    checks: list[SEOCheck]


def _grade_for(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 55:
        return "C"
    return "D"


@router.get(
    "/{episode_id}/seo-score",
    response_model=SEOScoreResponse,
    tags=["seo"],
    summary="Deterministic SEO heuristics for the current episode metadata",
)
async def get_seo_score(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> SEOScoreResponse:
    """Pure heuristics — no LLM call. Returns a list of pass/fail checks
    against YouTube-style SEO best practices."""
    try:
        episode = await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="episode_not_found",
        ) from exc

    meta = episode.metadata_ or {}
    seo = meta.get("seo") if isinstance(meta, dict) else None
    has_seo = isinstance(seo, dict)

    # Use the LLM-generated SEO metadata when present, otherwise fall
    # back to the raw episode fields — that way the score is available
    # before SEO generation has been run (and nudges the user to run it).
    title = (seo or {}).get("title") or episode.title or ""
    description = (seo or {}).get("description") or (episode.topic or "")
    hashtags = list((seo or {}).get("hashtags") or [])
    tags = list((seo or {}).get("tags") or [])
    hook = (seo or {}).get("hook") or ""

    checks: list[SEOCheck] = []
    score = 0

    # Title length — YouTube shows the first 60-70 chars in search.
    tlen = len(title)
    if 45 <= tlen <= 70:
        checks.append(
            SEOCheck(
                id="title_length",
                label="Title length",
                pass_=True,
                severity="ok",
                hint=f"{tlen} chars — in the sweet spot.",
            )
        )
        score += 20
    elif tlen < 20:
        checks.append(
            SEOCheck(
                id="title_length",
                label="Title length",
                pass_=False,
                severity="error",
                hint=f"Only {tlen} chars — likely to underperform. Aim for 45-70.",
            )
        )
    elif tlen < 45:
        checks.append(
            SEOCheck(
                id="title_length",
                label="Title length",
                pass_=False,
                severity="warn",
                hint=f"{tlen} chars — try expanding toward 45-70 for better CTR.",
            )
        )
        score += 10
    else:  # > 70
        checks.append(
            SEOCheck(
                id="title_length",
                label="Title length",
                pass_=False,
                severity="warn",
                hint=f"{tlen} chars — will be truncated in search. Trim toward 60-65.",
            )
        )
        score += 10

    # Description length — >= 125 chars fills the visible snippet; >= 400 is ideal.
    dlen = len(description)
    if dlen >= 400:
        checks.append(
            SEOCheck(
                id="desc_length",
                label="Description depth",
                pass_=True,
                severity="ok",
                hint=f"{dlen} chars — plenty of room for context + links.",
            )
        )
        score += 20
    elif dlen >= 125:
        checks.append(
            SEOCheck(
                id="desc_length",
                label="Description depth",
                pass_=False,
                severity="warn",
                hint=f"{dlen} chars — enough for search snippet; expand toward 400 for more keyword coverage.",
            )
        )
        score += 12
    else:
        checks.append(
            SEOCheck(
                id="desc_length",
                label="Description depth",
                pass_=False,
                severity="error",
                hint=f"Only {dlen} chars. YouTube shows ~125 chars in search; add context, keywords, and a CTA.",
            )
        )

    # Tag count — 5-15 keywords is healthy.
    tag_count = len(tags)
    if 5 <= tag_count <= 15:
        checks.append(
            SEOCheck(
                id="tag_count",
                label="Keyword tags",
                pass_=True,
                severity="ok",
                hint=f"{tag_count} tags — good spread.",
            )
        )
        score += 15
    elif 1 <= tag_count < 5:
        checks.append(
            SEOCheck(
                id="tag_count",
                label="Keyword tags",
                pass_=False,
                severity="warn",
                hint=f"Only {tag_count} tags. Aim for 5-15 to help discovery.",
            )
        )
        score += 7
    elif tag_count > 15:
        checks.append(
            SEOCheck(
                id="tag_count",
                label="Keyword tags",
                pass_=False,
                severity="warn",
                hint=f"{tag_count} tags is over-tagging territory. Trim to 5-15 strongest.",
            )
        )
        score += 8
    else:
        checks.append(
            SEOCheck(
                id="tag_count",
                label="Keyword tags",
                pass_=False,
                severity="error",
                hint="No keyword tags — add 5-15 to help YouTube's algorithm place this.",
            )
        )

    # Hashtags — 3-5 is YouTube's own recommendation.
    htag_count = len(hashtags)
    if 3 <= htag_count <= 5:
        checks.append(
            SEOCheck(
                id="hashtag_count",
                label="Hashtags",
                pass_=True,
                severity="ok",
                hint=f"{htag_count} hashtags — matches YouTube's own guidance.",
            )
        )
        score += 10
    elif 1 <= htag_count < 3:
        checks.append(
            SEOCheck(
                id="hashtag_count",
                label="Hashtags",
                pass_=False,
                severity="warn",
                hint=f"Only {htag_count} hashtag(s). YouTube recommends 3-5 — add one or two more.",
            )
        )
        score += 5
    elif htag_count > 5:
        checks.append(
            SEOCheck(
                id="hashtag_count",
                label="Hashtags",
                pass_=False,
                severity="warn",
                hint=f"{htag_count} hashtags — YouTube caps at 15, but only the first 3 render in the title bar. Keep the strongest 3-5.",
            )
        )
        score += 5
    else:
        checks.append(
            SEOCheck(
                id="hashtag_count",
                label="Hashtags",
                pass_=False,
                severity="warn",
                hint="No hashtags set. Add 3-5 to appear in topical feeds.",
            )
        )

    # Hook — must be non-empty and fit in ~8 seconds of speech (~25 words).
    hook_words = len(hook.split())
    if 6 <= hook_words <= 25 and hook.strip():
        checks.append(
            SEOCheck(
                id="hook",
                label="Opening hook",
                pass_=True,
                severity="ok",
                hint=f"{hook_words}-word hook — fits the first 8-10 seconds.",
            )
        )
        score += 15
    elif hook.strip() and hook_words > 25:
        checks.append(
            SEOCheck(
                id="hook",
                label="Opening hook",
                pass_=False,
                severity="warn",
                hint=f"Hook is {hook_words} words — too long to land in the first 8 seconds. Tighten to 10-20.",
            )
        )
        score += 7
    elif hook.strip():
        checks.append(
            SEOCheck(
                id="hook",
                label="Opening hook",
                pass_=False,
                severity="warn",
                hint=f"Hook is only {hook_words} words — add a concrete claim or question.",
            )
        )
        score += 7
    else:
        checks.append(
            SEOCheck(
                id="hook",
                label="Opening hook",
                pass_=False,
                severity="error",
                hint="No hook set. Generate SEO metadata or write a 10-20 word opener — this is the single biggest retention lever.",
            )
        )

    # CTA — at least one of (subscribe, comment, like, follow) in the description.
    cta_patterns = ("subscribe", "comment", "like", "follow", "share")
    cta_hits = [w for w in cta_patterns if w in description.lower()]
    if cta_hits:
        checks.append(
            SEOCheck(
                id="cta",
                label="Call to action",
                pass_=True,
                severity="ok",
                hint=f"Found: {', '.join(cta_hits)}.",
            )
        )
        score += 10
    else:
        checks.append(
            SEOCheck(
                id="cta",
                label="Call to action",
                pass_=False,
                severity="warn",
                hint="No CTA in description. Add 'Subscribe for more…' or 'Comment if this helped' to lift engagement signals.",
            )
        )

    # Keyword density — at least one of the top-3 tags should appear in the description.
    if tags and description:
        d_lower = description.lower()
        matched = [t for t in tags[:5] if t.lower() in d_lower]
        if matched:
            checks.append(
                SEOCheck(
                    id="keyword_density",
                    label="Keyword reuse",
                    pass_=True,
                    severity="ok",
                    hint=f"Top tag(s) appear in description: {', '.join(matched)}.",
                )
            )
            score += 10
        else:
            checks.append(
                SEOCheck(
                    id="keyword_density",
                    label="Keyword reuse",
                    pass_=False,
                    severity="warn",
                    hint="None of your top tags appear in the description. Weave 1-2 in naturally to reinforce the topic.",
                )
            )
    else:
        checks.append(
            SEOCheck(
                id="keyword_density",
                label="Keyword reuse",
                pass_=False,
                severity="info",
                hint="Set keyword tags + description first, then this check will score.",
            )
        )

    # SEO-metadata freshness flag — info-only, doesn't move the score.
    if not has_seo:
        checks.append(
            SEOCheck(
                id="seo_generated",
                label="SEO metadata",
                pass_=False,
                severity="info",
                hint="Run 'Generate SEO' to replace these heuristics with LLM-optimised title/description/tags.",
            )
        )
    else:
        vs = (seo or {}).get("virality_score")
        if isinstance(vs, (int, float)) and vs > 0:
            checks.append(
                SEOCheck(
                    id="seo_generated",
                    label="SEO metadata",
                    pass_=True,
                    severity="info",
                    hint=f"LLM virality estimate: {vs}/10.",
                )
            )

    score = max(0, min(100, score))
    grade = _grade_for(score)

    error_count = sum(1 for c in checks if c.severity == "error")
    warn_count = sum(1 for c in checks if c.severity == "warn")

    if error_count:
        summary = f"{error_count} blocking issue(s) and {warn_count} improvement(s) flagged."
    elif warn_count:
        summary = f"Looks solid — {warn_count} optional improvement(s)."
    else:
        summary = "All heuristics green. Ready to publish."

    return SEOScoreResponse(
        overall_score=score,
        grade=grade,
        summary=summary,
        has_seo_metadata=has_seo,
        checks=checks,
    )


@router.get(
    "/{episode_id}/export/raw-assets",
    status_code=status.HTTP_200_OK,
    summary="Download a ZIP of every per-scene image, voice segment, and caption asset",
    tags=["export"],
)
async def export_raw_assets(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> Response:
    """Zip every raw generation asset — one file per scene image, per
    voice segment, the final composited assets, and any ASS/SRT caption
    files. Useful for debugging, moving content between installs, or
    cherry-picking scenes for a manual re-edit outside the pipeline.

    Layout inside the archive::

        <safe_name>/scenes/scene_01.png
        <safe_name>/scenes/scene_02.png
        <safe_name>/voice/segment_01.wav
        <safe_name>/captions/captions.ass
        <safe_name>/captions/captions.srt
        <safe_name>/video/final.mp4       (when present)
        <safe_name>/thumbnail/thumb.jpg   (when present)
        <safe_name>/README.txt            (asset index + generation notes)
    """
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    base = Path(settings.storage_base_path)

    all_assets = await svc.get_all_assets(episode_id)
    if not all_assets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No media assets found for this episode yet",
        )

    # Group assets by kind for a tidy zip layout.
    # MediaAsset.asset_type is the authoritative enum — one of
    # scene / voice / caption / video / thumbnail / music (+ variants).
    per_kind: dict[str, list[Any]] = {}
    for a in all_assets:
        per_kind.setdefault(a.asset_type, []).append(a)

    def _build() -> tuple[bytes, dict[str, int]]:
        included: dict[str, int] = {}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for kind, assets in per_kind.items():
                # Sort by scene_number when present, otherwise by created_at
                # so segment_01 < segment_02 inside the archive.
                assets.sort(key=lambda a: (a.scene_number or 0, a.created_at or 0))
                for a in assets:
                    src = base / a.file_path
                    if not src.exists():
                        continue
                    ext = Path(a.file_path).suffix or ""
                    if a.scene_number is not None:
                        entry = f"{safe_name}/{kind}/{kind}_{a.scene_number:02d}{ext}"
                    else:
                        entry = f"{safe_name}/{kind}/{kind}{ext}"
                        if included.get(kind):
                            entry = f"{safe_name}/{kind}/{kind}_{str(a.id)[:8]}{ext}"
                    zf.write(str(src), entry)
                    included[kind] = included.get(kind, 0) + 1

            readme_lines = [
                f"Drevalis raw-assets export for: {series_name} — {episode.title}",
                f"Episode ID: {episode.id}",
                f"Generated: {episode.created_at}",
                "",
                "Contents:",
            ]
            for kind, count in sorted(included.items()):
                readme_lines.append(f"  {kind:<12} {count} file(s)")
            readme_lines.append("")
            readme_lines.append(
                "Regenerating any asset rebuilds the database row with a new "
                "UUID — so re-running an export after edits will overwrite this "
                "archive, not merge with it."
            )
            zf.writestr(f"{safe_name}/README.txt", "\n".join(readme_lines))
        return buf.getvalue(), included

    payload, included = await asyncio.to_thread(_build)
    logger.info(
        "export_raw_assets",
        episode_id=str(episode_id),
        zip_size=len(payload),
        kinds=list(per_kind.keys()),
    )
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_raw_assets.zip"',
        },
    )


# ── Video editing ─────────────────────────────────────────────────────────


@router.post(
    "/{episode_id}/edit",
    response_model=VideoEditResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply video edits (trim, border, effects) and save",
)
async def edit_video(
    episode_id: UUID,
    payload: VideoEditRequest,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> VideoEditResponse:
    """Apply edits to the episode's final video.

    Backs up the original video on first edit so it can be restored via
    the ``/edit/reset`` endpoint.
    """
    from drevalis.services.ffmpeg import FFmpegService

    base = Path(settings.storage_base_path)
    video_asset = await svc.get_latest_video_asset(episode_id)
    if video_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode",
        )
    video_path = base / video_asset.file_path
    if not video_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file not found on disk",
        )

    original_path = video_path.parent / "final_original.mp4"
    if not original_path.exists():
        import shutil

        await asyncio.to_thread(shutil.copy2, str(video_path), str(original_path))

    ffmpeg = FFmpegService(ffmpeg_path=settings.ffmpeg_path)
    edited_path = video_path.parent / "final_edited.mp4"

    await ffmpeg.apply_video_effects(
        input_path=original_path,
        output_path=edited_path,
        start_seconds=payload.trim_start,
        end_seconds=payload.trim_end,
        border_width=payload.border.width if payload.border else 0,
        border_color=payload.border.color if payload.border else "black",
        border_style=payload.border.style if payload.border else "solid",
        color_filter=payload.color_filter,
        speed=payload.speed,
    )

    import shutil

    await asyncio.to_thread(shutil.move, str(edited_path), str(video_path))

    duration = await ffmpeg.get_duration(video_path)
    file_size = video_path.stat().st_size
    await svc.update_asset_metadata(
        video_asset.id, file_size_bytes=file_size, duration_seconds=duration
    )

    logger.info("video_edited", episode_id=str(episode_id))
    return VideoEditResponse(
        episode_id=episode_id,
        message="Video edits applied successfully",
        video_path=video_asset.file_path,
        duration_seconds=duration,
    )


@router.post(
    "/{episode_id}/edit/preview",
    response_model=VideoEditResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a low-quality preview of video edits",
)
async def edit_preview(
    episode_id: UUID,
    payload: VideoEditRequest,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> VideoEditResponse:
    """Generate a quick low-res preview with the requested edits applied."""
    from drevalis.services.ffmpeg import FFmpegService

    base = Path(settings.storage_base_path)

    video_rel = await svc.get_video_asset_path(episode_id)
    if video_rel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode",
        )
    video_path = base / video_rel
    # Use the original if it exists, otherwise use the current video
    original_path = video_path.parent / "final_original.mp4"
    source_path = original_path if original_path.exists() else video_path

    preview_path = video_path.parent / "preview.mp4"
    ffmpeg = FFmpegService(ffmpeg_path=settings.ffmpeg_path)

    await ffmpeg.generate_preview(
        input_path=source_path,
        output_path=preview_path,
        start_seconds=payload.trim_start,
        end_seconds=payload.trim_end,
        border_width=payload.border.width if payload.border else 0,
        border_color=payload.border.color if payload.border else "black",
        border_style=payload.border.style if payload.border else "solid",
        color_filter=payload.color_filter,
        speed=payload.speed,
    )

    preview_relative = f"episodes/{episode_id}/output/preview.mp4"
    duration = await ffmpeg.get_duration(preview_path)

    return VideoEditResponse(
        episode_id=episode_id,
        message="Preview generated",
        video_path=preview_relative,
        duration_seconds=duration,
    )


@router.post(
    "/{episode_id}/edit/reset",
    response_model=VideoEditResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset video to the original assembly output",
)
async def edit_reset(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> VideoEditResponse:
    """Restore the original assembled video, undoing all edits."""
    from drevalis.services.ffmpeg import FFmpegService

    base = Path(settings.storage_base_path)
    video_asset = await svc.get_latest_video_asset(episode_id)
    if video_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode",
        )

    video_path = base / video_asset.file_path
    original_path = video_path.parent / "final_original.mp4"
    if not original_path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No original video backup found -- video has not been edited",
        )

    import shutil

    await asyncio.to_thread(shutil.copy2, str(original_path), str(video_path))

    ffmpeg = FFmpegService(ffmpeg_path=settings.ffmpeg_path)
    duration = await ffmpeg.get_duration(video_path)
    file_size = video_path.stat().st_size
    await svc.update_asset_metadata(
        video_asset.id, file_size_bytes=file_size, duration_seconds=duration
    )

    preview_path = video_path.parent / "preview.mp4"
    if preview_path.exists():
        preview_path.unlink()

    logger.info("video_edit_reset", episode_id=str(episode_id))
    return VideoEditResponse(
        episode_id=episode_id,
        message="Video restored to original",
        video_path=video_asset.file_path,
        duration_seconds=duration,
    )


# ── SEO optimization ─────────────────────────────────────────────────────


@router.post(
    "/{episode_id}/seo",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Generate SEO-optimized metadata using AI",
)
async def generate_seo(
    episode_id: UUID,
    redis: ArqRedis = Depends(get_redis),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Enqueue SEO generation as a background job."""
    try:
        await svc.get_with_script_or_raise(episode_id)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(404, "Episode not found or has no script") from exc

    await redis.enqueue_job("generate_seo_async", str(episode_id))
    return {"status": "queued", "message": "SEO generation started in background"}


# ── Cross-platform bulk publish ─────────────────────────────────────────


class PublishAllRequest(BaseModel):
    """Fan-out publish to every selected platform."""

    platforms: list[Literal["youtube", "tiktok", "instagram", "facebook", "x"]] = Field(
        ...,
        min_length=1,
        description="Platforms to publish to. Only platforms the episode's series + connected "
        "accounts cover will actually be enqueued; the rest are returned as skipped.",
    )
    title: str | None = Field(
        default=None,
        description="Override title. Defaults to the episode's SEO title or raw title.",
    )
    description: str | None = Field(
        default=None,
        description="Override description. Defaults to episode.metadata.seo.description or topic.",
    )
    privacy: Literal["public", "unlisted", "private"] = "public"


class PublishAllResponse(BaseModel):
    episode_id: str
    accepted: list[dict[str, Any]]
    skipped: list[dict[str, Any]]


@router.post(
    "/{episode_id}/publish-all",
    response_model=PublishAllResponse,
    summary="Publish the finished episode to YouTube + connected social platforms in one shot",
    tags=["publishing"],
)
async def publish_all(
    episode_id: UUID,
    body: PublishAllRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    svc: EpisodeService = Depends(_episode_service),
) -> PublishAllResponse:
    """Cross-platform bulk publish.

    Iterates the platforms the caller selected. For each:

    - **youtube**: requires the episode's series to have ``youtube_channel_id``
      set. Creates a YouTubeUpload row; the worker's upload cron picks it up.
    - **tiktok** / **instagram**: requires a connected SocialPlatform row
      for that platform. Creates a SocialUpload row; the social worker picks
      it up.

    Each platform that can't be fulfilled (no connection, missing video,
    tier gate, etc.) is returned in ``skipped`` with a human-readable
    reason rather than aborting the whole request.
    """
    apply_deprecation_headers(response, "cross_platform_bulk")
    from drevalis.models.social_platform import SocialPlatform, SocialUpload
    from drevalis.models.youtube_channel import YouTubeUpload

    try:
        episode = await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc
    if episode.status not in ("review", "exported", "editing"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Episode must be in review/exported/editing; current status is '{episode.status}'.",
        )

    if await svc.get_video_asset_path(episode_id) is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Episode has no finished video yet. Generate / reassemble first.",
        )

    seo = (episode.metadata_ or {}).get("seo") if isinstance(episode.metadata_, dict) else None
    effective_title = body.title or (seo or {}).get("title") or episode.title
    effective_description = (
        body.description or (seo or {}).get("description") or (episode.topic or "")
    )
    effective_tags = (seo or {}).get("tags") or []
    effective_hashtags = (seo or {}).get("hashtags") or []

    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    # ── YouTube ─────────────────────────────────────────────────────────
    if "youtube" in body.platforms:
        # Load series to resolve the assigned channel.
        await db.refresh(episode, attribute_names=["series"])
        yt_channel_id = (
            getattr(episode.series, "youtube_channel_id", None) if episode.series else None
        )
        if not yt_channel_id:
            skipped.append(
                {
                    "platform": "youtube",
                    "reason": "The episode's series has no assigned YouTube channel. "
                    "Set one in Settings → YouTube or on the series.",
                }
            )
        else:
            # Duplicate guard — refuse to enqueue a second YouTube upload
            # for an episode that's already published on this channel.
            from drevalis.repositories.youtube import YouTubeUploadRepository

            existing = await YouTubeUploadRepository(db).get_existing_done(
                episode.id, yt_channel_id
            )
            if existing is not None:
                skipped.append(
                    {
                        "platform": "youtube",
                        "reason": (
                            "Already published on this channel. "
                            f"Existing upload {existing.id} → "
                            f"{existing.youtube_url or existing.youtube_video_id}."
                        ),
                    }
                )
            else:
                upload = YouTubeUpload(
                    episode_id=episode.id,
                    channel_id=yt_channel_id,
                    title=effective_title,
                    description=effective_description,
                    privacy_status=body.privacy,
                    upload_status="pending",
                )
                db.add(upload)
                await db.flush()
                accepted.append(
                    {
                        "platform": "youtube",
                        "upload_id": str(upload.id),
                        "channel_id": str(yt_channel_id),
                    }
                )

    # ── TikTok / Instagram / Facebook / X ───────────────────────────────
    # All four uploaders ship in workers/jobs/social.py; the route fans
    # out to whichever platforms the caller requested and have an active
    # connected account. The social cron picks the SocialUpload rows up
    # on its next tick.
    for plat_name in ("tiktok", "instagram", "facebook", "x"):
        if plat_name not in body.platforms:
            continue

        from sqlalchemy import select as _select

        row = await db.execute(
            _select(SocialPlatform).where(
                SocialPlatform.platform == plat_name,
                SocialPlatform.is_active.is_(True),
            )
        )
        plat = row.scalar_one_or_none()
        if not plat:
            tier_hint = "Pro tier" if plat_name == "tiktok" else "Studio tier"
            skipped.append(
                {
                    "platform": plat_name,
                    "reason": f"No active {plat_name} account connected. Connect one in "
                    f"Settings → Social Platforms ({tier_hint}).",
                }
            )
            continue

        hashtags_str = " ".join(effective_hashtags) if effective_hashtags else None
        su = SocialUpload(
            platform_id=plat.id,
            episode_id=episode.id,
            content_type="episode",
            title=effective_title,
            description=effective_description,
            hashtags=hashtags_str,
            upload_status="pending",
        )
        db.add(su)
        await db.flush()
        accepted.append(
            {
                "platform": plat_name,
                "upload_id": str(su.id),
                "platform_account_id": str(plat.id),
            }
        )

    await db.commit()

    logger.info(
        "episode_publish_all",
        episode_id=str(episode_id),
        accepted=[a["platform"] for a in accepted],
        skipped=[s["platform"] for s in skipped],
    )

    _ = effective_tags  # reserved for future YouTube Data-API tag upload
    return PublishAllResponse(
        episode_id=str(episode_id),
        accepted=accepted,
        skipped=skipped,
    )


# ── SEO Pre-flight (Phase C) ──────────────────────────────────────────


class PreflightCheck(BaseModel):
    id: str
    severity: str  # "pass" | "warn" | "fail" | "info"
    title: str
    message: str
    suggestion: str | None = None


class PreflightResponse(BaseModel):
    score: int
    grade: str
    blocking: bool
    checks: list[PreflightCheck]


@router.post(
    "/{episode_id}/seo-preflight",
    response_model=PreflightResponse,
    tags=["seo"],
    summary="Pre-upload SEO pre-flight scoring",
)
async def seo_preflight(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> PreflightResponse:
    """Run the richer pre-upload checks on the current episode state.

    Does NOT hit the LLM. Combines stored SEO metadata (from
    ``generate_seo_async``) with the live script fields.
    """
    from drevalis.services.seo_preflight import preflight as run_preflight

    try:
        episode = await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc

    meta = episode.metadata_ or {}
    seo = meta.get("seo") if isinstance(meta, dict) else None
    seo = seo or {}

    script_payload = episode.script or {}
    hook_text: str = str((seo.get("hook") or script_payload.get("hook") or "") or "")

    content_format = getattr(episode, "content_format", "shorts") or "shorts"
    platform = "youtube_longform" if content_format == "longform" else "youtube_shorts"

    thumb_rel = await svc.get_thumbnail_asset_path(episode_id)
    thumb_path = Path(settings.storage_base_path) / thumb_rel if thumb_rel else None

    result = run_preflight(
        title=str(seo.get("title") or episode.title or ""),
        description=str(seo.get("description") or episode.topic or ""),
        hashtags=list(seo.get("hashtags") or []),
        tags=list(seo.get("tags") or []),
        hook_text=hook_text,
        hook_duration_seconds=None,  # could derive from caption timestamps later
        thumbnail_path=thumb_path,
        platform=platform,  # type: ignore[arg-type]
    )
    return PreflightResponse.model_validate(result.to_dict())


class VariantResponse(BaseModel):
    titles: list[str]
    thumbnail_prompts: list[str]
    descriptions: list[str]


@router.post(
    "/{episode_id}/seo-variants",
    response_model=VariantResponse,
    tags=["seo"],
    summary="Ask the LLM for alternate titles / thumbnails / descriptions",
)
async def seo_variants(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> VariantResponse:
    """Quick A/B options without mutating the episode. The frontend's
    pre-flight dialog offers one-click "Apply" for each suggestion.
    """
    import json as _json

    from drevalis.services.llm import LLMService, extract_json
    from drevalis.services.llm_config import LLMConfigService

    try:
        episode, _script = await svc.get_with_script_or_raise(episode_id)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc

    configs = (
        await LLMConfigService(
            db,
            settings.encryption_key,
            encryption_keys=settings.get_encryption_keys(),
        ).list_all()
    )[:1]
    if not configs:
        # No LLM configured — degrade gracefully with template variants
        # derived from the existing title.
        base_title = episode.title or "Untitled"
        return VariantResponse(
            titles=[
                base_title,
                f"{base_title} (you won't believe it)",
                f"I tried {base_title.lower()} — here's what happened",
                f"The real reason {base_title.lower()}",
                f"{base_title} explained in 60 seconds",
            ],
            thumbnail_prompts=[
                f"{base_title}, close-up, high contrast, 3-point lighting",
                f"{base_title}, split-screen before/after, bold text overlay",
                f"{base_title}, face-forward with shocked expression, bright colors",
            ],
            descriptions=[
                (episode.topic or base_title)[:200],
            ],
        )

    llm_service = LLMService(
        encryption_key=settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )
    provider = llm_service.get_provider(configs[0])
    narration = " ".join(
        (s.get("narration") or "") for s in (episode.script or {}).get("scenes") or []
    )

    system = (
        "You are a short-form video SEO editor. Return ONLY valid JSON in this shape:\n"
        '{"titles": ["...","...","...","...","..."],'
        '"thumbnail_prompts": ["...","...","..."],'
        '"descriptions": ["...","...","..."]}\n'
        "Titles: 5 alternates, ≤60 chars each, each with a different psychological angle "
        "(curiosity, outcome, contradiction, specificity, direct-benefit). "
        "Thumbnail prompts: 3 stills, each visually distinct, describe the shot not the title. "
        "Descriptions: 3 alternates ≤500 chars, first sentence is the hook."
    )
    user = (
        f"Original title: {episode.title}\n"
        f"Narration excerpt: {narration[:900]}\n\n"
        "Return the JSON now."
    )
    result = await provider.generate(system, user, temperature=0.8, max_tokens=1200, json_mode=True)
    try:
        data = _json.loads(extract_json(result.content))
    except Exception:
        data = {"titles": [], "thumbnail_prompts": [], "descriptions": []}

    return VariantResponse(
        titles=[str(t)[:100] for t in (data.get("titles") or [])][:5],
        thumbnail_prompts=[str(t)[:400] for t in (data.get("thumbnail_prompts") or [])][:5],
        descriptions=[str(t)[:500] for t in (data.get("descriptions") or [])][:5],
    )


# ── Inpaint a single scene (Phase E) ────────────────────────────────


class InpaintRequest(BaseModel):
    """Payload for scene inpainting.

    ``mask_png_base64`` is a base64-encoded PNG where white = redraw,
    black = keep. Dimensions must match the scene image. ``prompt``
    is what the model should paint inside the masked region.
    """

    mask_png_base64: str
    prompt: str = Field(..., min_length=1, max_length=2000)


@router.post(
    "/{episode_id}/scenes/{scene_number}/inpaint",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["scenes"],
    summary="Inpaint a region of a scene image",
)
async def inpaint_scene(
    episode_id: UUID,
    scene_number: int,
    body: InpaintRequest,
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, str]:
    """Store the mask and enqueue a ``regenerate_scene`` run tagged
    with an inpaint flag in Redis so the scenes worker invokes the
    inpaint workflow instead of full regeneration."""
    import base64

    try:
        await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc

    try:
        mask_bytes = base64.b64decode(body.mask_png_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"mask_png_base64 invalid: {exc}") from exc

    scenes_dir = Path(settings.storage_base_path) / "episodes" / str(episode_id) / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    mask_path = scenes_dir / f"scene_{scene_number:02d}.mask.png"
    mask_path.write_bytes(mask_bytes)

    # Surface the inpaint hint via Redis so the worker can pick it up
    # without a schema change. Key expires with the typical gen window.
    await redis.setex(
        f"inpaint:{episode_id}:{scene_number}",
        3600,
        body.prompt,
    )

    arq = get_arq_pool()
    await arq.enqueue_job(
        "regenerate_scene",
        str(episode_id),
        scene_number,
        body.prompt,
    )
    logger.info(
        "scene_inpaint_enqueued",
        episode_id=str(episode_id),
        scene_number=scene_number,
        mask_bytes=len(mask_bytes),
    )
    return {"status": "enqueued", "mask_path": str(mask_path.name)}


# ── Continuity checker (Phase E) ────────────────────────────────────


class ContinuityIssueResponse(BaseModel):
    from_scene: int
    to_scene: int
    severity: str
    issue: str
    suggestion: str


class ContinuityResponse(BaseModel):
    issues: list[ContinuityIssueResponse]


@router.post(
    "/{episode_id}/continuity",
    response_model=ContinuityResponse,
    tags=["scenes"],
    summary="Flag jarring transitions in the script before generation",
)
async def check_script_continuity(
    episode_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> ContinuityResponse:
    """Run the LLM-driven continuity check over the current script.

    No-op (returns issues=[]) when no LLM config exists. Non-destructive —
    the caller decides whether to act on the warnings.
    """
    apply_deprecation_headers(response, "continuity_check")
    from drevalis.services.continuity import check_continuity
    from drevalis.services.llm import LLMService
    from drevalis.services.llm_config import LLMConfigService

    try:
        _episode, script = await svc.get_with_script_or_raise(episode_id)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode or script missing") from exc

    configs = (
        await LLMConfigService(
            db,
            settings.encryption_key,
            encryption_keys=settings.get_encryption_keys(),
        ).list_all()
    )[:1]
    if not configs:
        return ContinuityResponse(issues=[])

    llm_service = LLMService(
        encryption_key=settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )
    issues = await check_continuity(script=script, llm_service=llm_service, llm_config=configs[0])
    return ContinuityResponse(
        issues=[ContinuityIssueResponse.model_validate(i.to_dict()) for i in issues]
    )


# ── Script content quality report (Phase 2.9) ──────────────────────────


class QualityReportResponse(BaseModel):
    """Result of running ``check_script_content`` against a stored script."""

    gate: str
    passed: bool
    issues: list[str]
    metrics: dict[str, Any]


@router.post(
    "/{episode_id}/quality-report",
    response_model=QualityReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Run the script-content quality gate against this episode's stored script",
)
async def episode_quality_report(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    svc: EpisodeService = Depends(_episode_service),
) -> QualityReportResponse:
    """Re-runs :func:`check_script_content` against the persisted script
    so already-generated episodes can be graded without regeneration.

    The series' ``tone_profile`` (when set) parameterises the gate the
    same way it would during the generation step.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from drevalis.models.episode import Episode as EpisodeModel
    from drevalis.services.quality_gates import check_script_content

    try:
        _episode, script = await svc.get_with_script_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc
    except EpisodeNoScriptError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "episode has no script yet — generate first",
        ) from exc

    # Load the series in a single round-trip for tone_profile.
    stmt = (
        select(EpisodeModel)
        .where(EpisodeModel.id == episode_id)
        .options(selectinload(EpisodeModel.series))
    )
    res = await db.execute(stmt)
    eager = res.scalar_one_or_none()
    tone_profile: dict[str, Any] | None = None
    if eager is not None and eager.series is not None:
        tone_profile = getattr(eager.series, "tone_profile", None)

    report = await check_script_content(script, tone_profile)
    return QualityReportResponse(
        gate=report.gate,
        passed=report.passed,
        issues=list(report.issues),
        metrics=dict(report.metrics),
    )
