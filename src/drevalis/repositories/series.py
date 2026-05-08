"""Series repository — eager-loading helpers & episode-count query."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from drevalis.models.episode import Episode
from drevalis.models.series import Series

from .base import BaseRepository


class SeriesRepository(BaseRepository[Series]):
    """Repository for the :class:`Series` aggregate root."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Series)

    async def get_with_relations(self, id: UUID) -> Series | None:
        """Load a Series with all its configuration relationships eagerly.

        Eagerly loads: voice_profile, comfyui_server, comfyui_workflow,
        llm_config, script_prompt_template, visual_prompt_template.
        """
        stmt = (
            select(Series)
            .where(Series.id == id)
            .options(
                selectinload(Series.voice_profile),
                selectinload(Series.comfyui_server),
                selectinload(Series.comfyui_workflow),
                selectinload(Series.llm_config),
                selectinload(Series.script_prompt_template),
                selectinload(Series.visual_prompt_template),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_with_episode_counts(self) -> list[tuple[Series, int]]:
        """Return all series together with their episode counts.

        Returns a list of ``(Series, episode_count)`` tuples ordered by
        series name.
        """
        episode_count = func.count(Episode.id).label("episode_count")
        stmt = (
            select(Series, episode_count)
            .outerjoin(Episode, Episode.series_id == Series.id)
            .group_by(Series.id)
            .order_by(Series.name)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
