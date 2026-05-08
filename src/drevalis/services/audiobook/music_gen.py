"""Background-music helpers for audiobooks.

Two free functions:

- ``_resolve_music_service``: constructs a ``MusicService`` wired up to the
  first registered ComfyUI server (so AceStep generation works for audiobooks).
- ``render_music_preview``: renders a short mixed preview WAV so users can
  hear how music + ducking will sound before committing to a full run.

``AudiobookService`` delegates to both via thin shims.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from drevalis.services.comfyui import ComfyUIService
    from drevalis.services.storage import StorageBackend

log = structlog.get_logger(__name__)


def _resolve_music_service(
    storage: StorageBackend,
    comfyui_service: ComfyUIService | None,
) -> Any | None:
    """Construct a MusicService that can ALSO call AceStep via ComfyUI.

    Earlier versions instantiated MusicService without
    ``comfyui_base_url`` / ``comfyui_api_key``, so AceStep
    generation never ran for audiobooks — every request fell
    straight through to the curated library, which could be
    empty for moods we hadn't pre-stocked. The first registered
    ComfyUI server on the pool is used; the music backend is
    cheap to run alongside image / TTS workloads.
    """
    from drevalis.services.music import MusicService

    storage_base = getattr(storage, "base_path", None)
    if storage_base is None:
        log.warning("audiobook.music.no_storage_base")
        return None

    comfyui_url: str | None = None
    comfyui_key: str | None = None
    if comfyui_service is not None:
        try:
            servers = getattr(comfyui_service._pool, "_servers", {})
            if servers:
                first_id = next(iter(servers))
                client = servers[first_id][0]
                comfyui_url = getattr(client, "base_url", None)
                comfyui_key = getattr(client, "api_key", None)
        except Exception as exc:
            log.warning(
                "audiobook.music.comfyui_url_resolve_failed",
                error=str(exc)[:120],
            )

    return MusicService(
        storage_base_path=storage_base,
        ffmpeg_path="ffmpeg",
        comfyui_base_url=comfyui_url,
        comfyui_api_key=comfyui_key,
    )


async def render_music_preview(
    audiobook_id: UUID,
    mood: str,
    storage: StorageBackend,
    add_music_fn: Callable[..., Coroutine[Any, Any, Path]],
    volume_db: float = -14.0,
    seconds: float = 30.0,
) -> Path:
    """Render a short mixed preview so users can sanity-check music
    before committing to a full generation run.

    Mixes the resolved music track (from the library or AceStep)
    under the audiobook's existing voiceover when one exists, or
    under a synthesised silent track otherwise. Output:
    ``audiobooks/{id}/music_preview.wav``. Always overwrites.
    """
    rel_dir = f"audiobooks/{audiobook_id}"
    abs_dir = storage.resolve_path(rel_dir)
    abs_dir.mkdir(parents=True, exist_ok=True)
    preview_path = abs_dir / "music_preview.wav"

    existing_voice = abs_dir / "audiobook.wav"
    if existing_voice.exists():
        voice_input: Path = existing_voice
        trim_voice = True
    else:
        # No voice yet — synthesise a silent ``seconds`` baseline
        # so the preview still demonstrates loudness + ducking
        # behaviour against silence.
        voice_input = abs_dir / "_preview_silence.wav"
        silence_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            f"{seconds:.1f}",
            "-c:a",
            "pcm_s16le",
            str(voice_input),
        ]
        sproc = await asyncio.create_subprocess_exec(
            *silence_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await sproc.communicate()
        trim_voice = False

    # Trim voice to ``seconds`` if it exists; otherwise we already
    # produced exactly ``seconds`` of silence above.
    clip_voice = abs_dir / "_preview_voice_clip.wav"
    if trim_voice:
        trim_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(voice_input),
            "-t",
            f"{seconds:.1f}",
            "-c:a",
            "pcm_s16le",
            str(clip_voice),
        ]
        tproc = await asyncio.create_subprocess_exec(
            *trim_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await tproc.communicate()
    else:
        # Voice IS the silence file — just rename our reference.
        clip_voice = voice_input

    await add_music_fn(
        audio_path=clip_voice,
        output_path=preview_path,
        mood=mood,
        volume_db=volume_db,
        duration=seconds,
    )

    # Best-effort cleanup of the intermediate silence file.
    try:
        if not trim_voice and voice_input.exists():
            voice_input.unlink()
        if trim_voice and clip_voice.exists():
            clip_voice.unlink()
    except Exception:
        pass

    return preview_path
