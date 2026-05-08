"""Audiobook repository -- CRUD with status filtering."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.audiobook import Audiobook

from .base import BaseRepository


class AudiobookRepository(BaseRepository[Audiobook]):
    """Repository for :class:`Audiobook` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Audiobook)

    async def get_by_status(self, status: str) -> list[Audiobook]:
        """Return audiobooks filtered by status."""
        stmt = (
            select(Audiobook)
            .where(Audiobook.status == status)
            .order_by(Audiobook.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
