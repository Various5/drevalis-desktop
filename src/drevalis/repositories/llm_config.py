"""LLMConfig repository — base methods only."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.llm_config import LLMConfig

from .base import BaseRepository


class LLMConfigRepository(BaseRepository[LLMConfig]):
    """Repository for :class:`LLMConfig` entities (base methods only)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LLMConfig)
