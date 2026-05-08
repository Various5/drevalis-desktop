"""PromptTemplate repository — type filtering."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.prompt_template import PromptTemplate

from .base import BaseRepository


class PromptTemplateRepository(BaseRepository[PromptTemplate]):
    """Repository for :class:`PromptTemplate` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PromptTemplate)

    async def get_by_type(self, template_type: str) -> list[PromptTemplate]:
        """Return prompt templates filtered by type (script|visual|hook|hashtag)."""
        stmt = (
            select(PromptTemplate)
            .where(PromptTemplate.template_type == template_type)
            .order_by(PromptTemplate.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
