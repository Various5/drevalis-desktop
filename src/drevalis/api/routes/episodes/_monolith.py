"""Episodes lifecycle / pipeline / script-editing / regenerate / inpaint.

Sub-routers for music / exports / seo / publish / quality live in
sibling modules in this package; ``episodes/__init__.py`` aggregates
them all under the single public ``router`` import that
``api/router.py`` consumes.

Inpaint stays here because it's a *scene-level* operation that shares
the regenerate codepath conceptually (it just hands the workflow a
mask in addition to the prompt).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from drevalis.api.routes.episodes._helpers import (
    _episode_service,
    _episode_to_list,
    _episode_to_response,
    logger,
)
from drevalis.core.concurrency import effective_max_concurrent_generations
from drevalis.core.config import Settings
from drevalis.core.deps import get_redis, get_settings
from drevalis.core.redis import get_arq_pool
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
)
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

router = APIRouter(prefix="/api/v1/episodes", tags=["episodes"])


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


@router.post(
    "/{episode_id}/restore",
    response_model=EpisodeResponse,
    summary="Restore a soft-deleted episode from the trash (undo delete)",
)
async def restore_episode(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> EpisodeResponse:
    """Undo a delete — bring a trashed episode back. 404 if it isn't in the trash."""
    try:
        episode = await svc.restore(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not in trash",
        ) from exc
    return _episode_to_response(episode)


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


# ── Music / Exports / SEO / Publish / Quality sub-routers ────────────────
#
# Extracted in alpha.28 into sibling modules:
#   * ``music.py``    — /music/* + /set-music
#   * ``exports.py``  — /export/* + /thumbnail + /edit/*
#   * ``seo.py``      — /seo-score, /seo, /seo-preflight, /seo-variants,
#                       /publish-all, /continuity, /quality-report
#
# This file (originally 2855 lines) keeps only lifecycle, pipeline
# control, script + scene editing, regenerate-* operations, and the
# inpaint route. Inpaint stays here because it's a *scene-level*
# operation and shares the regenerate codepath conceptually.
#
# Each sub-router has its own ``router = APIRouter(prefix=...)`` with
# the same ``/api/v1/episodes`` prefix; ``episodes/__init__.py``
# aggregates them so the public ``router`` import keeps working.
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

    # CodeQL py/path-injection: same textbook ``realpath`` +
    # ``startswith`` sanitizer pattern as the thumbnail handler.
    import os
    import os.path as _osp

    safe_episode_id = _osp.basename(str(episode_id))
    safe_scene_segment = _osp.basename(f"scene_{int(scene_number):02d}.mask.png")
    base_real = _osp.realpath(str(settings.storage_base_path))
    candidate_real = _osp.realpath(
        _osp.join(base_real, "episodes", safe_episode_id, "scenes", safe_scene_segment)
    )
    if not (
        candidate_real == base_real
        or candidate_real.startswith(base_real + os.sep)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid scene path")
    # Pure ``os`` API on the sanitized string — wrapping in ``Path()``
    # would re-introduce taint in CodeQL's flow model.
    os.makedirs(_osp.dirname(candidate_real), exist_ok=True)
    with open(candidate_real, "wb") as _mask_fh:
        _mask_fh.write(mask_bytes)
    mask_path_basename = _osp.basename(candidate_real)

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
    return {"status": "enqueued", "mask_path": mask_path_basename}


