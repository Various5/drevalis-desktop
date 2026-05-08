"""Audiobooks API router — CRUD, generation, cover image upload, and AI
script generation.

Layering: this router calls ``AudiobookAdminService`` (route
orchestration) + the existing ``AudiobookService`` (heavy generation
helpers) only. No repository imports here (audit F-A-01).
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.license.features import fastapi_dep_require_feature
from drevalis.schemas.audiobook import (
    AudiobookCreate,
    AudiobookListResponse,
    AudiobookResponse,
    AudiobookUpdate,
)
from drevalis.services.audiobook_admin import (
    AudiobookAdminService,
    NoChannelSelectedError,
)

log = structlog.get_logger(__name__)

# Audiobook studio is a Pro+ feature per the marketing pricing matrix.
# The router-wide gate covers CRUD, generation, regeneration, and AI
# script generation. Read-only listing is also gated — Creator tier
# never sees an audiobooks tab in the UI.
router = APIRouter(
    prefix="/api/v1/audiobooks",
    tags=["audiobooks"],
    dependencies=[Depends(fastapi_dep_require_feature("audiobooks"))],
)


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AudiobookAdminService:
    return AudiobookAdminService(db, settings.storage_base_path)


# ── AI Script Generation schemas ───────────────────────────────────────


class AudiobookScriptRequest(BaseModel):
    concept: str = Field(..., min_length=10)
    characters: list[dict[str, Any]] = Field(
        default_factory=lambda: [{"name": "Narrator", "description": "Omniscient narrator"}]
    )
    target_minutes: int = Field(default=10, ge=1, le=180)
    mood: str = Field(default="neutral")


class AudiobookScriptResponse(BaseModel):
    title: str
    script: str
    characters: list[str]
    chapters: list[str]
    word_count: int
    estimated_minutes: float


class ScriptJobResponse(BaseModel):
    job_id: str
    status: str


class ScriptJobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: AudiobookScriptResponse | None = None
    error: str | None = None


# ── AI Script Generation endpoints ─────────────────────────────────────


@router.post(
    "/generate-script",
    response_model=ScriptJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start async AI audiobook script generation",
)
async def generate_audiobook_script(
    payload: AudiobookScriptRequest,
    svc: AudiobookAdminService = Depends(_service),
) -> ScriptJobResponse:
    """Enqueue an LLM job to generate a full audiobook script. Returns
    immediately with a ``job_id``; poll
    ``GET /api/v1/audiobooks/script-job/{job_id}`` for the result."""
    job_id = await svc.enqueue_script_job(payload.model_dump())
    log.info(
        "audiobook.script.job_enqueued",
        job_id=job_id,
        concept_length=len(payload.concept),
        target_minutes=payload.target_minutes,
    )
    return ScriptJobResponse(job_id=job_id, status="generating")


@router.get(
    "/script-job/{job_id}",
    response_model=ScriptJobStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll for script generation job status",
)
async def get_script_job(
    job_id: str,
    svc: AudiobookAdminService = Depends(_service),
) -> ScriptJobStatusResponse:
    try:
        job = await svc.get_script_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found") from exc
    result_obj: AudiobookScriptResponse | None = None
    if job["result"] is not None:
        result_obj = AudiobookScriptResponse.model_validate(job["result"])
    return ScriptJobStatusResponse(
        job_id=job_id,
        status=job["status"],
        result=result_obj,
        error=job["error"],
    )


@router.post(
    "/script-job/{job_id}/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel a script generation job",
)
async def cancel_script_job(
    job_id: str,
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, str]:
    try:
        await svc.cancel_script_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found") from exc
    return {"message": "Cancelled"}


# ── Combined AI Create (single-form) ───────────────────────────────────


class AudiobookAICreateRequest(BaseModel):
    """Request body for the single-form AI audiobook creator. The LLM
    writes the script, then TTS generates audio — all in one
    background job."""

    concept: str = Field(..., min_length=10)
    characters: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "name": "Narrator",
                "description": "Omniscient narrator",
                "gender": "male",
                "voice_profile_id": None,
            }
        ]
    )
    target_minutes: float = Field(default=5, ge=1, le=180)
    mood: str = "neutral"
    output_format: str = "audio_only"
    music_enabled: bool = False
    music_mood: str | None = None
    music_volume_db: float = -14.0
    speed: float = 1.0
    pitch: float = 1.0
    image_generation_enabled: bool = False
    per_chapter_music: bool = False


@router.post(
    "/create-ai",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an AI audiobook -- LLM writes script, then TTS generates audio",
)
async def create_ai_audiobook(
    payload: AudiobookAICreateRequest,
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Create an AI audiobook: the LLM writes the script, then TTS
    generates audio. All heavy work runs in the background. Returns
    immediately with the audiobook ID and ``generating`` status."""
    try:
        audiobook = await svc.create_ai(payload)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {
        "audiobook_id": str(audiobook.id),
        "status": "generating",
        "title": audiobook.title,
    }


# ── Synchronous fallback (kept for backwards compatibility) ────────────


@router.post(
    "/generate-script-sync",
    response_model=AudiobookScriptResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate an audiobook script using AI (synchronous fallback)",
)
async def generate_audiobook_script_sync(
    payload: AudiobookScriptRequest,
    settings: Settings = Depends(get_settings),
) -> AudiobookScriptResponse:
    """Synchronous fallback: generate a script and wait for the result inline."""
    from drevalis.services.llm import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(
        base_url=settings.lm_studio_base_url,
        model=settings.lm_studio_default_model,
    )

    target_words = payload.target_minutes * 150
    char_list = "\n".join(f"- {c['name']}: {c['description']}" for c in payload.characters)

    system_prompt = """You are a professional audiobook scriptwriter.

CRITICAL FORMATTING RULES:
- EVERY single line of text MUST start with [CharacterName]
- Non-dialogue narration MUST use [Narrator]
- NEVER write any text without a [Speaker] tag at the start
- Each speaker change requires a new [Speaker] tag on a new line
- Use ## Chapter Title for chapter breaks

Example format:
## Chapter 1: The Beginning

[Narrator] The rain hadn't stopped for three days. The city was drowning.

[Jack] I need a drink.

[Narrator] He reached for the bottle on his desk, but it was empty. Like everything else in his life.

[Rosie] Mr. Hartley? Are you there?

Write naturally with emotion and tension. Every line tagged."""

    user_prompt = f"""Write an audiobook script based on this concept:

{payload.concept}

Characters:
{char_list}

Mood/tone: {payload.mood}
Target length: approximately {target_words} words ({payload.target_minutes} minutes of narration)

Write the complete script now. Start with a title line, then ## Chapter 1, and continue through the story."""

    log.info(
        "audiobook.script.generate_start_sync",
        concept_length=len(payload.concept),
        character_count=len(payload.characters),
        target_minutes=payload.target_minutes,
        mood=payload.mood,
    )

    try:
        result = await provider.generate(
            system_prompt,
            user_prompt,
            temperature=0.85,
            max_tokens=8000,
            json_mode=False,
        )
    except Exception as exc:
        log.error("audiobook.script.generate_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM generation failed: {exc}",
        ) from exc

    script_text = result.content.strip()
    lines = script_text.split("\n")
    title = lines[0].strip().lstrip("#").strip() if lines else "Untitled"
    chapters = re.findall(r"^##\s+(.+)$", script_text, re.MULTILINE)
    raw_tags = re.findall(r"^\[([^\]]+)\]", script_text, re.MULTILINE)
    characters_found = sorted(
        {t.strip() for t in raw_tags if not t.strip().lower().startswith("sfx")}
    )
    word_count = len(script_text.split())

    log.info(
        "audiobook.script.generate_done_sync",
        title=title,
        word_count=word_count,
        chapters=len(chapters),
        characters=characters_found,
    )

    return AudiobookScriptResponse(
        title=title,
        script=script_text,
        characters=characters_found,
        chapters=chapters,
        word_count=word_count,
        estimated_minutes=round(word_count / 150, 1),
    )


# ── List / Create ──────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[AudiobookListResponse],
    status_code=status.HTTP_200_OK,
    summary="List all audiobooks",
)
async def list_audiobooks(
    status_filter: str | None = Query(default=None, alias="status", description="Filter by status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    svc: AudiobookAdminService = Depends(_service),
) -> list[AudiobookListResponse]:
    audiobooks = await svc.list_filtered(status_filter=status_filter, offset=offset, limit=limit)
    return [AudiobookListResponse.model_validate(a) for a in audiobooks]


@router.post(
    "",
    response_model=AudiobookResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an audiobook and start generation",
)
async def create_audiobook(
    payload: AudiobookCreate,
    svc: AudiobookAdminService = Depends(_service),
) -> AudiobookResponse:
    """Create an audiobook record and enqueue the generation job. The
    response is returned immediately with status ``generating``; the
    actual TTS work runs asynchronously in the arq worker."""
    from drevalis.schemas.audiobook import resolve_audiobook_settings

    try:
        resolved_settings = resolve_audiobook_settings(
            preset=payload.preset,
            overrides=payload.settings_override,
        )
        settings_blob: dict[str, Any] | None = resolved_settings.model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid audiobook settings: {exc}",
        ) from exc

    try:
        audiobook = await svc.create(payload, settings_blob)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.detail) from exc
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return AudiobookResponse.model_validate(audiobook)


# ── Upload cover image ─────────────────────────────────────────────────


@router.post(
    "/upload-cover",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a cover image for audiobook generation",
)
async def upload_cover_image(
    file: UploadFile,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Upload a cover image to be used with audio_image output format.

    Size-capped at 10 MiB and magic-byte-verified via Pillow so an
    operator (or malicious LAN client on an exposed install) can't OOM
    the worker with a multi-GB body or smuggle an HTML/JS polyglot
    through the ``.png`` extension filter and have it served back from
    ``/storage/audiobooks/``.
    """
    MAX_COVER_BYTES = 10 * 1024 * 1024

    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File must be an image, got {file.content_type}",
        )

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_COVER_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Cover image exceeds {MAX_COVER_BYTES // (1024 * 1024)} MiB limit.",
            )
        chunks.append(chunk)
    content = b"".join(chunks)

    try:
        from PIL import Image as _Image
        from PIL import UnidentifiedImageError as _UnidentifiedImageError

        with _Image.open(io.BytesIO(content)) as img:
            img.verify()
    except (_UnidentifiedImageError, Exception) as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is not a valid image.",
        ) from exc

    ext = Path(file.filename).suffix.lower() if file.filename else ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        ext = ".png"
    unique_name = f"{uuid4()}{ext}"

    covers_dir = settings.storage_base_path / "audiobooks" / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)

    dest = covers_dir / unique_name
    dest.write_bytes(content)

    rel_path = f"audiobooks/covers/{unique_name}"
    log.info(
        "audiobook.cover_uploaded",
        path=rel_path,
        size_bytes=len(content),
        content_type=file.content_type,
    )
    return {"cover_image_path": rel_path}


# ── Get / Update / Update text ─────────────────────────────────────────


@router.get(
    "/{audiobook_id}",
    response_model=AudiobookResponse,
    status_code=status.HTTP_200_OK,
    summary="Get audiobook detail",
)
async def get_audiobook(
    audiobook_id: UUID,
    svc: AudiobookAdminService = Depends(_service),
) -> AudiobookResponse:
    try:
        audiobook = await svc.get(audiobook_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc
    return AudiobookResponse.model_validate(audiobook)


@router.put(
    "/{audiobook_id}",
    response_model=AudiobookResponse,
    status_code=status.HTTP_200_OK,
    summary="Update audiobook metadata",
)
async def update_audiobook(
    audiobook_id: UUID,
    payload: AudiobookUpdate,
    svc: AudiobookAdminService = Depends(_service),
) -> AudiobookResponse:
    try:
        audiobook = await svc.update_metadata(audiobook_id, payload.model_dump(exclude_unset=True))
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.detail) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc
    return AudiobookResponse.model_validate(audiobook)


class AudiobookTextUpdate(BaseModel):
    text: str = Field(..., min_length=1)


@router.put(
    "/{audiobook_id}/text",
    response_model=AudiobookResponse,
    status_code=status.HTTP_200_OK,
    summary="Update audiobook text without regenerating",
)
async def update_audiobook_text(
    audiobook_id: UUID,
    payload: AudiobookTextUpdate,
    svc: AudiobookAdminService = Depends(_service),
) -> AudiobookResponse:
    """Update the audiobook's text content. Does NOT regenerate audio."""
    try:
        audiobook = await svc.update_text(audiobook_id, payload.text)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc
    return AudiobookResponse.model_validate(audiobook)


# ── Regenerate chapter / chapter image ────────────────────────────────


class ChapterRegeneratePayload(BaseModel):
    text: str | None = Field(default=None, description="Optional replacement text for the chapter")


@router.post(
    "/{audiobook_id}/regenerate-chapter/{chapter_index}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Regenerate a single chapter's audio",
)
async def regenerate_chapter(
    audiobook_id: UUID,
    chapter_index: int,
    payload: ChapterRegeneratePayload | None = None,
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Regenerate a single chapter's audio, then re-concatenate the full audiobook."""
    new_text = payload.text if payload else None
    try:
        await svc.regenerate_chapter(audiobook_id, chapter_index, new_text)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.detail) from exc
    return {
        "message": f"Chapter {chapter_index} regeneration enqueued",
        "audiobook_id": str(audiobook_id),
        "chapter_index": chapter_index,
    }


class ChapterImageRegeneratePayload(BaseModel):
    prompt_override: str | None = Field(
        default=None,
        description=(
            "Optional ComfyUI prompt to use instead of the chapter title. "
            "Useful when the auto-derived prompt produces a poor image."
        ),
    )


@router.post(
    "/{audiobook_id}/regenerate-chapter-image/{chapter_index}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Regenerate a single chapter's illustration",
)
async def regenerate_chapter_image(
    audiobook_id: UUID,
    chapter_index: int,
    payload: ChapterImageRegeneratePayload | None = None,
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Regenerate a single chapter's image only. Faster than the full
    chapter regen (no TTS, no reassembly)."""
    prompt_override = payload.prompt_override if payload else None
    try:
        await svc.regenerate_chapter_image(audiobook_id, chapter_index, prompt_override)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.detail) from exc
    return {
        "message": f"Chapter {chapter_index} image regeneration enqueued",
        "audiobook_id": str(audiobook_id),
        "chapter_index": chapter_index,
    }


# ── Voices / cancel / regenerate / remix ──────────────────────────────


@router.put(
    "/{audiobook_id}/voices",
    status_code=status.HTTP_200_OK,
    summary="Update voice casting and optionally regenerate",
)
async def update_audiobook_voices(
    audiobook_id: UUID,
    payload: dict[str, Any],
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Update voice assignments for an audiobook. Optionally regenerate audio."""
    try:
        regenerated = await svc.update_voices(
            audiobook_id,
            payload.get("voice_casting"),
            payload.get("voice_profile_id"),
            bool(payload.get("regenerate", False)),
        )
    except NotFoundError as exc:
        raise HTTPException(404, "Audiobook not found") from exc
    if regenerated:
        return {"message": "Voices updated and regeneration started", "status": "generating"}
    return {"message": "Voices updated"}


@router.post(
    "/{audiobook_id}/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel an in-progress audiobook generation",
)
async def cancel_audiobook(
    audiobook_id: UUID,
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Set the cancel flag for a running audiobook generation. Returns
    immediately — actual cancellation lands at the next step boundary."""
    try:
        new_status = await svc.cancel(audiobook_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc

    if new_status != "cancel-signalled":
        return {
            "message": "Audiobook is not generating; nothing to cancel.",
            "audiobook_id": str(audiobook_id),
            "status": new_status,
        }
    return {
        "message": "Cancel signal sent. The job will stop at the next step boundary.",
        "audiobook_id": str(audiobook_id),
    }


@router.post(
    "/{audiobook_id}/music-preview",
    status_code=status.HTTP_200_OK,
    summary="Render a 30s music preview to sanity-check before commit",
)
async def music_preview(
    audiobook_id: UUID,
    mood: str = Query(..., min_length=1, description="Music mood (matches MusicService keywords)"),
    seconds: float = Query(30.0, ge=5.0, le=120.0),
    volume_db: float = Query(-14.0, ge=-30.0, le=0.0),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Mix a short preview snippet so the user can hear the mood +
    ducking behaviour before committing to a full generation run."""
    from typing import cast

    from redis.asyncio import Redis

    from drevalis.core.redis import get_pool
    from drevalis.services.audiobook import AudiobookService
    from drevalis.services.comfyui import ComfyUIPool, ComfyUIService
    from drevalis.services.ffmpeg import FFmpegService
    from drevalis.services.storage import LocalStorage

    try:
        await svc.get(audiobook_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc

    storage = LocalStorage(base_path=settings.storage_base_path)
    pool = ComfyUIPool()
    await pool.sync_from_db(db)
    comfyui_svc = ComfyUIService(pool=pool, storage=storage) if pool._servers else None

    redis = Redis(connection_pool=get_pool())
    try:
        ab_svc = AudiobookService(
            tts_service=cast(Any, None),
            ffmpeg_service=FFmpegService(),
            storage=storage,
            db_session=db,
            comfyui_service=comfyui_svc,
            redis=redis,
        )
        preview_path = await ab_svc.render_music_preview(
            audiobook_id=audiobook_id,
            mood=mood,
            volume_db=volume_db,
            seconds=seconds,
        )
    finally:
        await redis.aclose()

    if not preview_path.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Could not render preview — MusicService returned no track. "
                "Either the mood is missing from the curated library and no "
                "ComfyUI server is registered for AceStep generation, or the "
                "ffmpeg mix failed. Check the worker logs for "
                "'audiobook.music.no_track_resolved'."
            ),
        )

    rel = f"audiobooks/{audiobook_id}/music_preview.wav"
    return {
        "audiobook_id": str(audiobook_id),
        "mood": mood,
        "seconds": seconds,
        "url": f"/storage/{rel}",
        "rel_path": rel,
    }


@router.post(
    "/{audiobook_id}/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Regenerate the entire audiobook audio",
)
async def regenerate_audiobook(
    audiobook_id: UUID,
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Regenerate the entire audiobook from its current text."""
    try:
        await svc.regenerate(audiobook_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc
    return {
        "message": "Full audiobook regeneration enqueued",
        "audiobook_id": str(audiobook_id),
    }


@router.get(
    "/{audiobook_id}/clips",
    status_code=status.HTTP_200_OK,
    summary="List every cached audio clip for the multi-track editor",
)
async def list_clips(
    audiobook_id: UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Return per-track clip lists + the current per-clip overrides."""
    from typing import cast

    from drevalis.services.audiobook import AudiobookService
    from drevalis.services.ffmpeg import FFmpegService
    from drevalis.services.storage import LocalStorage

    try:
        ab = await svc.get(audiobook_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc

    storage = LocalStorage(base_path=settings.storage_base_path)
    ab_svc = AudiobookService(
        tts_service=cast(Any, None),
        ffmpeg_service=FFmpegService(),
        storage=storage,
        db_session=db,
        comfyui_service=None,
    )
    payload = await ab_svc.list_clips(audiobook_id)
    overrides = (ab.track_mix or {}).get("clips") or {}
    payload["overrides"] = overrides
    return payload


class TrackMixPayload(BaseModel):
    voice_db: float | None = Field(default=None, ge=-30, le=20)
    music_db: float | None = Field(default=None, ge=-30, le=20)
    sfx_db: float | None = Field(default=None, ge=-30, le=20)
    voice_mute: bool | None = None
    music_mute: bool | None = None
    sfx_mute: bool | None = None
    clips: dict[str, dict[str, Any]] | None = None


@router.post(
    "/{audiobook_id}/remix",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-render the audio mix with new track gains (no TTS / image regen)",
)
async def remix_audiobook(
    audiobook_id: UUID,
    payload: TrackMixPayload,
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Persist new ``track_mix`` settings and enqueue a remix job."""
    try:
        current_mix = await svc.remix(audiobook_id, payload.model_dump(exclude_none=True))
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc
    return {
        "message": "Remix enqueued",
        "audiobook_id": str(audiobook_id),
        "track_mix": current_mix,
    }


# ── Delete ─────────────────────────────────────────────────────────────


@router.delete(
    "/{audiobook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an audiobook and its files",
)
async def delete_audiobook(
    audiobook_id: UUID,
    svc: AudiobookAdminService = Depends(_service),
) -> None:
    try:
        await svc.delete(audiobook_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc


# ── YouTube upload ─────────────────────────────────────────────────────


class AudiobookYouTubeUploadRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list)
    privacy_status: str = Field(default="private")


@router.post(
    "/{audiobook_id}/upload-youtube",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload audiobook video to YouTube",
)
async def upload_audiobook_to_youtube(
    audiobook_id: UUID,
    payload: AudiobookYouTubeUploadRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    svc: AudiobookAdminService = Depends(_service),
) -> dict[str, Any]:
    """Upload the audiobook's video to YouTube. Requires an active
    YouTube channel connection and a generated video (``output_format``
    must be ``audio_image`` or ``audio_video``)."""
    from drevalis.api.routes.youtube import build_youtube_service

    yt_service = await build_youtube_service(settings, db)

    try:
        audiobook, channel, video_path = await svc.prepare_youtube_upload(audiobook_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.detail) from exc
    except NoChannelSelectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "no_channel_selected",
                "hint": (
                    "Assign a youtube_channel_id to the audiobook, or connect a "
                    "single YouTube channel so the target is unambiguous."
                ),
            },
        ) from exc

    updated_tokens = await yt_service.refresh_tokens_if_needed(
        channel.access_token_encrypted or "",
        channel.refresh_token_encrypted,
        channel.token_expiry,
    )
    if updated_tokens:
        for key, value in updated_tokens.items():
            setattr(channel, key, value)
        await db.flush()

    upload = await svc.create_youtube_upload_row(
        audiobook_id=audiobook_id,
        channel_id=channel.id,
        title=payload.title,
        privacy_status=payload.privacy_status,
    )

    try:
        result = await yt_service.upload_video(
            access_token_encrypted=channel.access_token_encrypted or "",
            refresh_token_encrypted=channel.refresh_token_encrypted,
            token_expiry=channel.token_expiry,
            video_path=video_path,
            title=payload.title,
            description=payload.description,
            tags=payload.tags,
            privacy_status=payload.privacy_status,
            thumbnail_path=None,
        )
        await svc.record_youtube_upload_success(
            upload, video_id=result["video_id"], url=result["url"]
        )
        log.info(
            "audiobook.youtube_upload_success",
            audiobook_id=str(audiobook_id),
            video_id=result["video_id"],
            upload_id=str(upload.id),
        )
        return {
            "status": "done",
            "youtube_video_id": result["video_id"],
            "youtube_url": result["url"],
            "upload_id": str(upload.id),
        }
    except Exception as exc:
        await svc.record_youtube_upload_failure(upload, str(exc))
        log.error(
            "audiobook.youtube_upload_failed",
            audiobook_id=str(audiobook_id),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YouTube upload failed: {exc}",
        ) from exc


@router.get(
    "/{audiobook_id}/uploads",
    status_code=status.HTTP_200_OK,
    summary="List YouTube upload history for an audiobook",
)
async def list_audiobook_uploads(
    audiobook_id: UUID,
    svc: AudiobookAdminService = Depends(_service),
) -> list[dict[str, Any]]:
    """Return all YouTube upload attempts for a given audiobook, newest first."""
    try:
        uploads = await svc.list_youtube_uploads(audiobook_id)
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Audiobook {audiobook_id} not found"
        ) from exc

    return [
        {
            "id": str(u.id),
            "audiobook_id": str(u.audiobook_id),
            "youtube_video_id": u.youtube_video_id,
            "youtube_url": u.youtube_url,
            "title": u.title,
            "privacy_status": u.privacy_status,
            "upload_status": u.upload_status,
            "error_message": u.error_message,
            "playlist_id": u.playlist_id,
            "created_at": u.created_at.isoformat(),
            "updated_at": u.updated_at.isoformat(),
        }
        for u in uploads
    ]
