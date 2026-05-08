"""SeriesService — series CRUD + AI episode-idea generation flows.

Layering: keeps the route file free of repository imports, raw Redis
calls, and LLM provider resolution (audit F-A-01).

Three repositories collaborate here (series, episode, llm_config) so
the service owns them. The async ``generate_series`` enqueue flow stays
on the route side because it produces a job_id only — no domain logic
to extract.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.repositories.episode import EpisodeRepository
from drevalis.repositories.llm_config import LLMConfigRepository
from drevalis.repositories.series import SeriesRepository
from drevalis.services.llm import (
    LLMService,
    OpenAICompatibleProvider,
    extract_json,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.models.episode import Episode
    from drevalis.models.series import Series

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


_SERIES_GEN_SYSTEM_PROMPT = """\
You are a premium YouTube Shorts series strategist. You create series that go viral because of genuinely fascinating, specific content — not generic clickbait.
Output ONLY valid JSON with this exact structure:
{
    "name": "compelling series name (max 50 chars)",
    "description": "2-3 sentence description of the series concept and what makes it unique",
    "visual_style": "ultra-detailed visual style for AI image generation: specific color palette, dramatic lighting style, cinematic composition, mood, aesthetic reference",
    "character_description": "describe the narrator/character IF the series features a specific character. Leave empty string '' for topics about landscapes, space, science, nature, cities, or abstract concepts where no character is needed",
    "episodes": [
        {"title": "specific compelling title with a number or bold claim", "topic": "2-3 sentences describing the SPECIFIC angle, including real names/dates/numbers. Must teach something 99% of people don't know."}
    ]
}
CRITICAL RULES:
- Series name must be bold and specific, not generic
- Each episode title MUST contain a specific detail (a name, year, number, or bold claim)
- Episode topics MUST be specific and fascinating — NOT generic overviews. Each should focus on ONE specific story, case, event, or revelation
- BAD example: "The history of hacking" — too generic
- GOOD example: "The teenager who hacked NASA at age 15 — and what he found"
- Visual style must be specific enough for AI to generate consistent, cinematic imagery
- Character description: leave '' for non-character content (landscapes, space, science, etc.)"""


_ADD_EPISODES_SYSTEM_PROMPT = """\
You are a premium YouTube Shorts content strategist. Given a series concept and existing episodes, \
suggest NEW episode ideas with genuinely fascinating, specific content that 99% of people don't know.
Output ONLY valid JSON: {"episodes": [{"title": "...", "topic": "..."}]}
RULES:
- Each title MUST contain a specific detail (name, year, number, or bold claim)
- Each topic must be 2-3 sentences describing ONE specific story, case, or revelation
- Focus on insider knowledge, counterintuitive facts, and stories that make people stop scrolling
- NEVER suggest generic overviews — every episode should have a unique, specific angle
- BAD: "Interesting facts about the ocean" / GOOD: "The 11,000m trench where pressure crushes steel — but life thrives" """


_TRENDING_SYSTEM_PROMPT = (
    "You are a viral content strategist. Suggest trending YouTube Shorts topics. "
    'Output ONLY valid JSON: {"topics": [{"title": "...", "angle": "unique angle", '
    '"hook": "attention-grabbing first line", "estimated_engagement": "high|medium|low"}]}'
)

_MAX_GENERATE_RETRIES = 2

_IMMUTABLE_AFTER_FIRST_GENERATION = ("content_format", "aspect_ratio")


class SeriesFieldLockedError(Exception):
    """Raised when content_format / aspect_ratio change is attempted on a series
    that already has non-draft episodes."""

    def __init__(self, locked_fields: list[str], non_draft_episode_count: int) -> None:
        self.locked_fields = locked_fields
        self.non_draft_episode_count = non_draft_episode_count
        super().__init__(f"locked fields: {locked_fields}")


class SeriesService:
    def __init__(self, db: AsyncSession, *, encryption_key: str, settings_obj: Any) -> None:
        self._db = db
        self._encryption_key = encryption_key
        self._settings = settings_obj  # carries lm_studio_base_url + lm_studio_default_model
        self._series = SeriesRepository(db)
        self._episodes = EpisodeRepository(db)
        self._llm_configs = LLMConfigRepository(db)

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def list_with_episode_counts(self) -> list[tuple[Series, int]]:
        return await self._series.list_with_episode_counts()

    async def get_with_relations(self, series_id: UUID) -> Series:
        series = await self._series.get_with_relations(series_id)
        if series is None:
            raise NotFoundError("Series", series_id)
        return series

    async def create(self, **payload: Any) -> Series:
        series = await self._series.create(**payload)
        await self._db.commit()
        await self._db.refresh(series)
        return series

    async def update(self, series_id: UUID, update_data: dict[str, Any]) -> Series:
        if not update_data:
            raise ValidationError("No fields to update")

        current = await self._series.get_by_id(series_id)
        if current is None:
            raise NotFoundError("Series", series_id)

        locked_fields = [
            f
            for f in _IMMUTABLE_AFTER_FIRST_GENERATION
            if f in update_data and getattr(current, f, None) != update_data[f]
        ]
        if locked_fields:
            non_draft = await self._episodes.count_non_draft_for_series(series_id)
            if non_draft > 0:
                raise SeriesFieldLockedError(locked_fields, non_draft)

        series = await self._series.update(series_id, **update_data)
        if series is None:
            raise NotFoundError("Series", series_id)
        await self._db.commit()
        await self._db.refresh(series)
        return series

    async def delete(self, series_id: UUID) -> None:
        deleted = await self._series.delete(series_id)
        if not deleted:
            raise NotFoundError("Series", series_id)
        await self._db.commit()

    # ── LLM provider resolution ──────────────────────────────────────────

    async def _resolve_provider(self, llm_config_id: UUID | None) -> Any:
        if llm_config_id:
            llm_config = await self._llm_configs.get_by_id(llm_config_id)
            if not llm_config:
                raise NotFoundError("LLMConfig", llm_config_id)
            return LLMService(
                encryption_key=self._encryption_key,
                encryption_keys=self._settings.get_encryption_keys(),
            ).get_provider(llm_config)

        configs = await self._llm_configs.get_all(limit=1)
        if configs:
            return LLMService(
                encryption_key=self._encryption_key,
                encryption_keys=self._settings.get_encryption_keys(),
            ).get_provider(configs[0])
        return OpenAICompatibleProvider(
            base_url=self._settings.lm_studio_base_url,
            model=self._settings.lm_studio_default_model,
        )

    # ── AI: synchronous full series generation ───────────────────────────

    async def generate_series_sync(
        self,
        *,
        idea: str,
        episode_count: int,
        target_duration_seconds: int,
        voice_profile_id: UUID | None,
        llm_config_id: UUID | None,
    ) -> tuple[Series, list[Episode]]:
        """Generate a complete series + episodes inline.

        Returns ``(series, episodes_created)``. Raises ``ValidationError``
        with the LLM error string on persistent malformed JSON.
        """
        provider = await self._resolve_provider(llm_config_id)

        user_prompt = (
            f"Create a YouTube Shorts series based on this idea:\n\n"
            f"{idea}\n\n"
            f"Generate exactly {episode_count} episode ideas.\n"
            f"Target duration per episode: {target_duration_seconds} seconds.\n\n"
            f"Return the JSON now:"
        )

        last_error: Exception | None = None
        data: dict[str, Any] | None = None

        for attempt in range(_MAX_GENERATE_RETRIES + 1):
            try:
                result = await provider.generate(
                    _SERIES_GEN_SYSTEM_PROMPT,
                    user_prompt,
                    temperature=0.8,
                    max_tokens=4096,
                    json_mode=True,
                )
                data = json.loads(extract_json(result.content))
                if not isinstance(data, dict) or "name" not in data or "episodes" not in data:
                    raise ValueError("Response missing required 'name' or 'episodes' keys")
                logger.info(
                    "series_generate_llm_complete",
                    attempt=attempt + 1,
                    series_name=data.get("name"),
                    episodes_count=len(data.get("episodes", [])),
                )
                break
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                last_error = exc
                logger.warning(
                    "series_generate_json_parse_failed",
                    attempt=attempt + 1,
                    max_retries=_MAX_GENERATE_RETRIES,
                    error=str(exc),
                )

        if data is None:
            raise ValidationError(
                f"LLM returned invalid JSON after {_MAX_GENERATE_RETRIES + 1} "
                f"attempts: {last_error}"
            )

        series = await self._series.create(
            name=data["name"][:255],
            description=data.get("description", ""),
            visual_style=data.get("visual_style", ""),
            character_description=data.get("character_description", ""),
            target_duration_seconds=target_duration_seconds,
            voice_profile_id=voice_profile_id,
        )

        episodes_created: list[Episode] = []
        for ep_data in data.get("episodes", [])[:episode_count]:
            title = str(ep_data.get("title", "Untitled"))[:500]
            topic = str(ep_data.get("topic", ""))
            ep = await self._episodes.create(
                series_id=series.id,
                title=title,
                topic=topic,
            )
            episodes_created.append(ep)

        await self._db.commit()
        logger.info(
            "series_generate_complete",
            series_id=str(series.id),
            series_name=series.name,
            episode_count=len(episodes_created),
        )
        return series, episodes_created

    # ── AI: add episodes to an existing series ───────────────────────────

    async def add_episodes_ai(
        self, series_id: UUID, count: int, llm_config_id: UUID | None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        series = await self._series.get_by_id(series_id)
        if not series:
            raise NotFoundError("Series", series_id)

        existing_eps = await self._episodes.get_by_series(series_id, limit=30)
        existing_titles = [ep.title[:60] for ep in existing_eps]

        provider = await self._resolve_provider(llm_config_id)

        user_prompt = (
            f"Series: {series.name}\n"
            f"Description: {series.description or 'N/A'}\n"
            f"Existing episodes: {', '.join(existing_titles) if existing_titles else 'None yet'}\n\n"
            f"Generate exactly {count} NEW episode ideas that fit this series.\n"
            f"Do NOT repeat existing episode topics.\n"
            f"Return the JSON now:"
        )

        data: dict[str, Any] | None = None
        for _attempt in range(3):
            try:
                result = await provider.generate(
                    _ADD_EPISODES_SYSTEM_PROMPT,
                    user_prompt,
                    temperature=0.8,
                    max_tokens=2048,
                    json_mode=True,
                )
                data = json.loads(extract_json(result.content))
                if not isinstance(data, dict) or "episodes" not in data:
                    raise ValueError("Missing 'episodes' key")
                break
            except (json.JSONDecodeError, ValueError):
                continue

        if data is None:
            raise ValidationError("LLM returned invalid JSON after retries")

        created_ids: list[str] = []
        episodes_payload = data["episodes"][:count]
        for ep_data in episodes_payload:
            title = ep_data.get("title", "Untitled")[:500]
            topic = ep_data.get("topic", "")
            ep = await self._episodes.create(
                series_id=series_id,
                title=title,
                topic=topic,
            )
            created_ids.append(str(ep.id))

        await self._db.commit()
        logger.info("add_episodes_ai_done", series_id=str(series_id), count=len(created_ids))
        return created_ids, episodes_payload

    # ── AI: trending-topic suggestions (no DB writes) ────────────────────

    async def suggest_trending_topics(self, series_id: UUID) -> list[dict[str, Any]]:
        series = await self._series.get_by_id(series_id)
        if not series:
            raise NotFoundError("Series", series_id)

        existing_eps = await self._episodes.get_by_series(series_id, limit=100)
        existing_titles = [ep.title for ep in existing_eps]

        provider = await self._resolve_provider(None)

        user_prompt = (
            f"Series: {series.name}\n"
            f"Description: {series.description or 'N/A'}\n"
            f"Existing episodes: "
            f"{', '.join(existing_titles[:20]) if existing_titles else 'None'}\n\n"
            "Suggest 10 trending/viral topic ideas. Focus on what's currently popular "
            "and would get maximum views. Return JSON now:"
        )

        result = await provider.generate(
            _TRENDING_SYSTEM_PROMPT,
            user_prompt,
            temperature=0.8,
            max_tokens=2048,
            json_mode=True,
        )
        try:
            data = json.loads(extract_json(result.content))
        except Exception:
            data = {"topics": []}
        topics = data.get("topics", [])
        return list(topics) if isinstance(topics, list) else []


__all__ = ["SeriesFieldLockedError", "SeriesService"]
