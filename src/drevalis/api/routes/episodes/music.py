"""Music sub-routes for an episode.

Owns:
  * ``GET /{episode_id}/music/moods`` — list mood catalogue
  * ``GET /{episode_id}/music``        — list track files on disk
  * ``POST /{episode_id}/music/generate`` — enqueue AceStep generation
  * ``POST /{episode_id}/music/select``   — pin a track for next assembly
  * ``POST /{episode_id}/set-music``      — full music settings + reassemble

Extracted from the original ``_monolith.py`` (alpha.28). ``_ffprobe_duration``
lives here because nothing outside the music routes uses it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from drevalis.api.routes.episodes._helpers import _episode_service, logger
from drevalis.core.concurrency import effective_max_concurrent_generations
from drevalis.core.config import Settings
from drevalis.core.deps import get_settings
from drevalis.core.redis import get_arq_pool
from drevalis.schemas.episode import SetMusicRequest
from drevalis.services.episode import (
    ConcurrencyCapReachedError,
    EpisodeNotFoundError,
    EpisodeService,
)

router = APIRouter(prefix="/api/v1/episodes", tags=["episodes"])

# Hard cap on the AceStep workflow's ``length_sec`` knob. The AceStep 1.5
# checkpoint OOMs on most consumer GPUs above ~2 minutes, so we reject
# requests before submission rather than letting ComfyUI fail mid-run.
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

    # arq jobs must be enqueued via the dedicated arq pool singleton, NOT the
    # plain Redis client yielded by ``get_redis`` (which has no enqueue_job —
    # calling it there raised AttributeError and surfaced as a 500).
    try:
        arq = get_arq_pool()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background worker not ready yet; try again in a moment.",
        ) from exc
    await arq.enqueue_job(
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


# ``logger`` is imported from _helpers so info logs from any of the
# route handlers still attribute correctly. Marked as referenced so
# linters don't flag the import as unused.
_ = logger
