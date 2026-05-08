"""Music generation arq job.

Moved from the synchronous HTTP endpoint to avoid blocking uvicorn workers
for up to 10 minutes during AceStep workflow polling.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any
from uuid import UUID

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def generate_episode_music(
    ctx: dict[str, Any], episode_id: str, mood: str, duration_seconds: float
) -> dict[str, Any]:
    """Generate a background music track using AceStep 1.5 via ComfyUI.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    episode_id:
        UUID string of the target episode.
    mood:
        Mood keyword (e.g. "epic", "calm").
    duration_seconds:
        Desired track length in seconds (1-120).
    """
    from drevalis.core.config import Settings
    from drevalis.repositories.comfyui import ComfyUIServerRepository
    from drevalis.repositories.episode import EpisodeRepository
    from drevalis.services.comfyui import ComfyUIClient
    from drevalis.services.music import (
        _ACESTEP_MAX_DURATION,
        _MOOD_TAGS,
        MusicService,
    )

    db = ctx["db"]
    settings = Settings()

    structlog.contextvars.bind_contextvars(episode_id=episode_id, job="generate_episode_music")
    logger.info(
        "music_generate_job.start",
        mood=mood,
        duration=duration_seconds,
    )

    ep_repo = EpisodeRepository(db)
    episode = await ep_repo.get_by_id(UUID(episode_id))
    if episode is None:
        logger.error("music_generate_job.episode_not_found")
        return {"error": f"Episode {episode_id} not found"}

    # Resolve ComfyUI server
    server_repo = ComfyUIServerRepository(db)
    active_servers = await server_repo.get_active_servers()
    if not active_servers:
        logger.error("music_generate_job.no_comfyui_server")
        return {"error": "No active ComfyUI server configured"}

    server = active_servers[0]
    comfyui_api_key: str | None = None
    if server.api_key_encrypted:
        try:
            comfyui_api_key = settings.decrypt(server.api_key_encrypted)
        except Exception:
            logger.warning("music_generate_job.api_key_decrypt_failed", server_id=str(server.id))

    # Prepare output
    output_dir = settings.storage_base_path / "episodes" / episode_id / "music"
    output_dir.mkdir(parents=True, exist_ok=True)

    tags = _MOOD_TAGS.get(mood, f"{mood} instrumental background music")
    capped_duration = min(duration_seconds, _ACESTEP_MAX_DURATION)
    seed = random.randint(0, 2**31)

    workflow = MusicService._build_acestep_workflow(tags, capped_duration, seed)

    client = ComfyUIClient(base_url=server.url, api_key=comfyui_api_key)
    try:
        extra_data: dict[str, str] = {}
        if comfyui_api_key:
            extra_data["api_key_comfy_org"] = comfyui_api_key

        prompt_id = await client.queue_prompt(workflow, extra_data=extra_data or None)

        logger.info(
            "music_generate_job.submitted",
            episode_id=episode_id,
            mood=mood,
            duration=capped_duration,
            seed=seed,
            prompt_id=prompt_id,
            server_url=server.url,
        )

        # Poll with exponential backoff up to 10 minutes.
        delay = 2.0
        total_waited = 0.0
        history: dict[str, Any] | None = None
        while total_waited < 600.0:
            await asyncio.sleep(delay)
            total_waited += delay
            history = await client.get_history(prompt_id)
            if history is not None:
                break
            delay = min(delay * 1.5, 30.0)

        if history is None:
            logger.error("music_generate_job.timeout", episode_id=episode_id, waited=total_waited)
            return {"error": f"AceStep generation timed out after {int(total_waited)}s"}

        # Check for workflow-level errors.
        exec_status = history.get("status", {})
        if exec_status.get("status_str") == "error":
            messages = exec_status.get("messages", [])
            error_detail = "unknown ComfyUI error"
            for msg_type, msg_data in messages:
                if msg_type == "execution_error" and isinstance(msg_data, dict):
                    error_detail = (
                        f"node '{msg_data.get('node_type', '?')}': "
                        f"{msg_data.get('exception_message', 'unknown error')}"
                    )
                    break
            logger.error(
                "music_generate_job.workflow_error", detail=error_detail, prompt_id=prompt_id
            )
            return {"error": f"ComfyUI workflow error: {error_detail}"}

        # Locate the audio output.
        audio_info = MusicService._extract_audio_output(history.get("outputs", {}))
        if audio_info is None:
            logger.error("music_generate_job.no_audio_output", episode_id=episode_id)
            return {"error": "ComfyUI workflow completed but produced no audio output"}

        filename = audio_info.get("filename", "")
        subfolder = audio_info.get("subfolder", "")
        folder_type = audio_info.get("type", "output")

        audio_bytes = await client.download_image(filename, subfolder, folder_type)

        output_filename = f"{mood}_{seed}.mp3"
        output_path = output_dir / output_filename
        output_path.write_bytes(audio_bytes)

    finally:
        await client.close()

    # Measure actual duration
    from drevalis.services.ffmpeg import FFmpegService

    ffmpeg = FFmpegService(ffmpeg_path=settings.ffmpeg_path)
    actual_duration = 0.0
    try:
        actual_duration = await ffmpeg.get_duration(output_path)
    except Exception:
        pass

    relative_path = f"episodes/{episode_id}/music/{output_filename}"

    logger.info(
        "music_generate_job.done",
        episode_id=episode_id,
        path=relative_path,
        size_bytes=len(audio_bytes),
        duration=actual_duration,
    )

    return {
        "filename": output_filename,
        "path": relative_path,
        "mood": mood,
        "duration": actual_duration,
    }
