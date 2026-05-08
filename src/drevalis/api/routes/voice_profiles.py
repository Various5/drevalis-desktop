"""Voice Profiles API router — CRUD, voice testing, voice cloning.

Layering: this router calls ``VoiceProfileService`` only. No repository
imports, no TTS provider imports here (audit F-A-01).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.license.deprecation import apply_deprecation_headers
from drevalis.schemas.voice_profile import (
    CloneVoiceRequest,
    CloneVoiceResponse,
    VoiceProfileCreate,
    VoiceProfileResponse,
    VoiceProfileUpdate,
    VoiceTestRequest,
    VoiceTestResponse,
)
from drevalis.services.voice_profile import VoiceProfileService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/voice-profiles", tags=["voice-profiles"])


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VoiceProfileService:
    return VoiceProfileService(
        db,
        encryption_key=settings.encryption_key,
        storage_base_path=settings.storage_base_path,
        piper_models_path=settings.piper_models_path,
        kokoro_models_path=settings.kokoro_models_path,
        encryption_keys=settings.get_encryption_keys(),
    )


# ── List voice profiles ──────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[VoiceProfileResponse],
    status_code=status.HTTP_200_OK,
    summary="List all voice profiles",
)
async def list_voice_profiles(
    provider: str | None = Query(default=None, description="Filter by provider"),
    language_code: str | None = Query(
        default=None,
        description="Filter by BCP-47 language tag (e.g. 'en-US'). Profiles with "
        "language_code=NULL always pass through so legacy voices aren't hidden.",
    ),
    svc: VoiceProfileService = Depends(_service),
) -> list[VoiceProfileResponse]:
    profiles = await svc.list_filtered(provider=provider, language_code=language_code)
    return [VoiceProfileResponse.model_validate(p) for p in profiles]


# ── Generate ElevenLabs voice previews ───────────────────────────────────


@router.post(
    "/generate-previews",
    status_code=status.HTTP_200_OK,
    summary="Generate audio previews for all ElevenLabs voice profiles",
    description=(
        "Iterates over every voice profile whose provider is "
        "``comfyui_elevenlabs`` and that does not yet have a valid preview "
        "file on disk. For each one a short TTS sample is synthesised via "
        "ComfyUI, saved to ``storage/voice_previews/{profile_id}.wav``, and "
        "the ``sample_audio_path`` column is updated. Already-previewed "
        "profiles are skipped. Returns counts of generated, skipped, and "
        "failed profiles."
    ),
)
async def generate_voice_previews(
    force: bool = Query(
        default=False,
        description="If true, regenerate previews even when a WAV already exists "
        "on disk. Use to refresh stale samples (e.g. after the app rename).",
    ),
    svc: VoiceProfileService = Depends(_service),
) -> dict[str, int | str]:
    try:
        return await svc.generate_all_previews(force=force)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc


# ── Regenerate one profile's preview (all providers) ────────────────────


@router.post(
    "/{profile_id}/regenerate-preview",
    response_model=VoiceProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Force-regenerate the preview WAV for a single voice profile",
    description=(
        "Deletes the existing preview file (if any) and synthesises a fresh "
        "one using the current preview text. Works for edge / piper / kokoro "
        "profiles via the auto-preview path; ElevenLabs profiles should use "
        "``/generate-previews?force=true``."
    ),
)
async def regenerate_voice_preview(
    profile_id: UUID,
    svc: VoiceProfileService = Depends(_service),
) -> VoiceProfileResponse:
    try:
        profile = await svc.regenerate_preview(profile_id)
        return VoiceProfileResponse.model_validate(profile)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# ── Create voice profile ─────────────────────────────────────────────────


@router.post(
    "",
    response_model=VoiceProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new voice profile",
)
async def create_voice_profile(
    payload: VoiceProfileCreate,
    svc: VoiceProfileService = Depends(_service),
) -> VoiceProfileResponse:
    profile = await svc.create(payload)
    return VoiceProfileResponse.model_validate(profile)


# ── Get voice profile ────────────────────────────────────────────────────


@router.get(
    "/{profile_id}",
    response_model=VoiceProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a voice profile by ID",
)
async def get_voice_profile(
    profile_id: UUID,
    svc: VoiceProfileService = Depends(_service),
) -> VoiceProfileResponse:
    try:
        profile = await svc.get(profile_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return VoiceProfileResponse.model_validate(profile)


# ── Update voice profile ─────────────────────────────────────────────────


@router.put(
    "/{profile_id}",
    response_model=VoiceProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a voice profile",
)
async def update_voice_profile(
    profile_id: UUID,
    payload: VoiceProfileUpdate,
    svc: VoiceProfileService = Depends(_service),
) -> VoiceProfileResponse:
    try:
        profile = await svc.update(profile_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.detail) from exc
    return VoiceProfileResponse.model_validate(profile)


# ── Delete voice profile ─────────────────────────────────────────────────


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a voice profile",
)
async def delete_voice_profile(
    profile_id: UUID,
    svc: VoiceProfileService = Depends(_service),
) -> None:
    try:
        await svc.delete(profile_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# ── Test voice profile ───────────────────────────────────────────────────


@router.post(
    "/{profile_id}/test",
    response_model=VoiceTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Test voice with sample text",
)
async def test_voice_profile(
    profile_id: UUID,
    payload: VoiceTestRequest | None = None,
    svc: VoiceProfileService = Depends(_service),
) -> VoiceTestResponse:
    """Synthesise a short sample and return the result.

    Uses Piper, Edge, Kokoro, or ElevenLabs depending on the profile's
    provider.
    """
    text = payload.text if payload is not None else "Hello, this is a test of the voice profile."
    try:
        return await svc.test(profile_id, text)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# ── Voice cloning (Phase E) ──────────────────────────────────────────────


@router.post(
    "/clone",
    response_model=CloneVoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a VoiceProfile from an uploaded voice sample",
)
async def clone_voice(
    body: CloneVoiceRequest,
    response: Response,
    svc: VoiceProfileService = Depends(_service),
) -> CloneVoiceResponse:
    """Clone a voice from an existing asset.

    The asset must be an audio file (``kind='audio'``) already in the
    library. This route copies its path into
    ``VoiceProfile.sample_audio_path`` and creates a profile row.

    For ``elevenlabs`` we mark the profile as ``pending_training`` — a
    follow-up pass uploads the sample to ElevenLabs IVC and stores the
    returned ``voice_id`` back into ``elevenlabs_voice_id``. For local
    TTS (piper / kokoro) the profile is created but flagged
    ``pending_training`` since those engines need offline model
    fine-tuning which isn't automated yet.
    """
    apply_deprecation_headers(response, "elevenlabs")
    try:
        return await svc.clone(body)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
