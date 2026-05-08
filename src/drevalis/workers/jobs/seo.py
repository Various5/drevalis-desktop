"""SEO generation arq job.

Moved from the synchronous HTTP endpoint to avoid blocking uvicorn workers
during LLM inference (can take up to 30 minutes on slow local models).
"""

from __future__ import annotations

import json as _json
from typing import Any
from uuid import UUID

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def generate_seo_async(ctx: dict[str, Any], episode_id: str) -> dict[str, Any]:
    """Generate SEO-optimized metadata for an episode using LLM.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    episode_id:
        UUID string of the target episode.
    """
    from drevalis.core.config import Settings
    from drevalis.repositories.episode import EpisodeRepository
    from drevalis.repositories.llm_config import LLMConfigRepository
    from drevalis.schemas.script import EpisodeScript
    from drevalis.services.llm import (
        LLMService,
        OpenAICompatibleProvider,
        extract_json,
    )

    db = ctx["db"]
    settings = Settings()

    # Bind context so every downstream provider/log call carries the
    # episode id without each callee having to take or rebind it.
    structlog.contextvars.bind_contextvars(episode_id=episode_id, job="generate_seo_async")
    logger.info("seo_generate_job.start")

    ep_repo = EpisodeRepository(db)
    episode = await ep_repo.get_by_id(UUID(episode_id))
    if not episode or not episode.script:
        logger.error("seo_generate_job.episode_not_found")
        return {"error": "Episode not found or has no script"}

    script = EpisodeScript.model_validate(episode.script)
    narration = " ".join(s.narration for s in script.scenes if s.narration)

    # Resolve LLM
    configs = await LLMConfigRepository(db).get_all(limit=1)
    if configs:
        llm_service = LLMService(
            encryption_key=settings.encryption_key,
            encryption_keys=settings.get_encryption_keys(),
        )
        provider = llm_service.get_provider(configs[0])
    else:
        provider = OpenAICompatibleProvider(
            base_url=settings.lm_studio_base_url,
            model=settings.lm_studio_default_model,
        )

    from drevalis.services.seo_prompts import (
        SEO_SYSTEM_PROMPT,
        build_seo_user_prompt,
    )

    existing_description = ""
    if isinstance(episode.script, dict):
        raw_desc = episode.script.get("description")
        if isinstance(raw_desc, str):
            existing_description = raw_desc

    result = await provider.generate(
        SEO_SYSTEM_PROMPT,
        build_seo_user_prompt(
            title=episode.title,
            narration=narration,
            script_description=existing_description,
        ),
        temperature=0.7,
        max_tokens=1024,
        json_mode=True,
    )
    try:
        data = _json.loads(extract_json(result.content))
    except Exception:
        data = {
            "title": episode.title,
            "description": narration[:200],
            "hashtags": [],
            "tags": [],
            "hook": "",
            "virality_score": 0,
            "virality_reasoning": "",
        }

    # Store SEO data in episode metadata
    metadata = dict(episode.metadata_ or {}) if episode.metadata_ else {}
    metadata["seo"] = data
    await ep_repo.update(episode.id, metadata_=metadata)
    await db.commit()

    logger.info(
        "seo_generate_job.done",
        virality_score=data.get("virality_score", 0),
    )

    response: dict[str, Any] = data
    return response
