"""Series-related arq job functions.

Jobs
----
- ``generate_series_async`` -- background LLM series + episode generation.
"""

from __future__ import annotations

from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def generate_series_async(
    ctx: dict[str, Any], job_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Background LLM series generation.

    Generates series configuration and episodes via LLM, persists them to
    the database, and stores the result in Redis.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    job_id:
        Unique job identifier.
    payload:
        Dict with keys: idea, episode_count, target_duration_seconds,
        voice_profile_id (optional), llm_config_id (optional).
    """
    import json
    from uuid import UUID

    from drevalis.core.config import Settings

    log = logger.bind(job_id=job_id, job="generate_series_async")
    log.info("job_start")

    redis_client = ctx["redis"]

    try:
        # Check for early cancellation
        current_status = await redis_client.get(f"script_job:{job_id}:status")
        if current_status == "cancelled":
            log.info("job_already_cancelled")
            return {"status": "cancelled"}

        from drevalis.repositories.episode import EpisodeRepository
        from drevalis.repositories.llm_config import LLMConfigRepository
        from drevalis.repositories.series import SeriesRepository
        from drevalis.services.llm import (
            LLMService,
            OpenAICompatibleProvider,
            extract_json,
        )

        settings = Settings()

        session_factory = ctx["session_factory"]
        async with session_factory() as session:
            # Resolve LLM provider
            llm_config_id = payload.get("llm_config_id")
            if llm_config_id:
                llm_config = await LLMConfigRepository(session).get_by_id(UUID(llm_config_id))
                if not llm_config:
                    raise ValueError("LLM config not found")
                llm_service = LLMService(
                    encryption_key=settings.encryption_key,
                    encryption_keys=settings.get_encryption_keys(),
                )
                provider = llm_service.get_provider(llm_config)
            else:
                provider = OpenAICompatibleProvider(
                    base_url=settings.lm_studio_base_url,
                    model=settings.lm_studio_default_model,
                )

            episode_count = payload.get("episode_count", 10)
            target_duration = payload.get("target_duration_seconds", 30)

            system_prompt = """\
You are a YouTube Shorts series creator. Generate a complete series configuration from the user's idea.
Output ONLY valid JSON with this exact structure:
{
    "name": "catchy series name (max 50 chars)",
    "description": "2-3 sentence description of the series concept",
    "visual_style": "detailed visual style for AI image/video generation: color palette, lighting, aesthetic, mood",
    "character_description": "describe the narrator/character: appearance, setting, vibe (for consistent visuals across episodes)",
    "episodes": [
        {"title": "catchy episode title", "topic": "1-2 sentence description of what this episode covers"}
    ]
}
Make the series name catchy and YouTube-friendly.
Visual style should be specific enough for AI image generation (mention colors, lighting, composition).
Character description should be detailed enough to generate consistent visuals.
Each episode topic should be specific and actionable, not vague."""

            user_prompt = (
                f"Create a YouTube Shorts series based on this idea:\n\n"
                f"{payload['idea']}\n\n"
                f"Generate exactly {episode_count} episode ideas.\n"
                f"Target duration per episode: {target_duration} seconds.\n\n"
                f"Return the JSON now:"
            )

            # Call LLM with retry
            max_retries = 2
            last_error: Exception | None = None
            data: dict[str, Any] | None = None

            for attempt in range(max_retries + 1):
                # Check cancellation between retries
                current_status = await redis_client.get(f"script_job:{job_id}:status")
                if current_status == "cancelled":
                    log.info("job_cancelled_during_retries")
                    return {"status": "cancelled"}

                try:
                    result = await provider.generate(
                        system_prompt,
                        user_prompt,
                        temperature=0.8,
                        max_tokens=4096,
                        json_mode=True,
                    )

                    raw = result.content
                    extracted = extract_json(raw)
                    data = json.loads(extracted)

                    if not isinstance(data, dict) or "name" not in data or "episodes" not in data:
                        raise ValueError("Response missing required 'name' or 'episodes' keys")

                    log.info(
                        "llm_complete",
                        attempt=attempt + 1,
                        series_name=data.get("name"),
                    )
                    break

                except (json.JSONDecodeError, ValueError, KeyError) as exc:
                    last_error = exc
                    log.warning(
                        "json_parse_failed",
                        attempt=attempt + 1,
                        error=str(exc),
                    )

            if data is None:
                raise ValueError(
                    f"LLM returned invalid JSON after {max_retries + 1} attempts: {last_error}"
                )

            # Create the series in the database
            voice_profile_id = payload.get("voice_profile_id")
            vp_uuid = UUID(voice_profile_id) if voice_profile_id else None

            series_repo = SeriesRepository(session)
            new_series = await series_repo.create(
                name=data["name"][:255],
                description=data.get("description", ""),
                visual_style=data.get("visual_style", ""),
                character_description=data.get("character_description", ""),
                target_duration_seconds=target_duration,
                voice_profile_id=vp_uuid,
            )

            # Create episodes
            episode_repo = EpisodeRepository(session)
            episodes_created: list[dict[str, Any]] = []

            for ep_data in data.get("episodes", [])[:episode_count]:
                title = str(ep_data.get("title", "Untitled"))[:500]
                topic = str(ep_data.get("topic", ""))
                ep = await episode_repo.create(
                    series_id=new_series.id,
                    title=title,
                    topic=topic,
                )
                episodes_created.append({"title": ep.title, "topic": ep.topic or ""})

            await session.commit()

            result_dict = {
                "series_id": str(new_series.id),
                "series_name": new_series.name,
                "episode_count": len(episodes_created),
                "episodes": episodes_created,
            }

            await redis_client.set(f"script_job:{job_id}:result", json.dumps(result_dict), ex=3600)
            await redis_client.set(f"script_job:{job_id}:status", "done", ex=3600)

            log.info(
                "job_complete",
                series_id=str(new_series.id),
                episode_count=len(episodes_created),
            )
            return {"status": "done"}

    except Exception as exc:
        log.error("job_failed", error=str(exc), exc_info=True)
        await redis_client.set(f"script_job:{job_id}:error", str(exc)[:500], ex=3600)
        await redis_client.set(f"script_job:{job_id}:status", "failed", ex=3600)
        return {"status": "failed", "error": str(exc)}
