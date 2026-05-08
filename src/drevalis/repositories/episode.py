"""Episode repository — filtering, eager-loading, status helpers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from drevalis.models.episode import Episode

from .base import BaseRepository


class EpisodeRepository(BaseRepository[Episode]):
    """Repository for :class:`Episode` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Episode)

    async def get_by_series(
        self,
        series_id: UUID,
        status_filter: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Episode]:
        """List episodes for a series, optionally filtered by status."""
        stmt = (
            select(Episode)
            .where(Episode.series_id == series_id)
            .order_by(Episode.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if status_filter is not None:
            stmt = stmt.where(Episode.status == status_filter)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_assets(self, id: UUID) -> Episode | None:
        """Load an episode with its media_assets and generation_jobs."""
        stmt = (
            select(Episode)
            .where(Episode.id == id)
            .options(
                selectinload(Episode.media_assets),
                selectinload(Episode.generation_jobs),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(self, id: UUID, new_status: str) -> Episode | None:
        """Update only the status field of an episode."""
        return await self.update(id, status=new_status)

    async def get_recent(self, limit: int = 10) -> list[Episode]:
        """Return the most recently created episodes across all series."""
        stmt = (
            select(Episode)
            .options(selectinload(Episode.series))
            .order_by(Episode.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_ids(self, ids: list[UUID]) -> dict[UUID, Episode]:
        """Return episodes for the given IDs, indexed by id.

        Single round-trip replacement for a per-id ``get_by_id`` loop;
        missing rows are simply absent from the returned dict.
        """
        if not ids:
            return {}
        stmt = select(Episode).where(Episode.id.in_(ids))
        result = await self.session.execute(stmt)
        return {ep.id: ep for ep in result.scalars().all()}

    async def get_by_status(self, status: str, limit: int = 50) -> list[Episode]:
        """Return all episodes with the given status."""
        stmt = (
            select(Episode)
            .options(selectinload(Episode.series))
            .where(Episode.status == status)
            .order_by(Episode.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_status(self, status: str) -> int:
        """Return the count of episodes with the given status."""
        stmt = select(func.count()).select_from(Episode).where(Episode.status == status)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_non_draft_for_series(self, series_id: UUID) -> int:
        """Count episodes of *series_id* that have moved past the ``draft``
        status (i.e. generating, review, editing, exported, or failed).

        Used by the series-update endpoint to enforce that pipeline-
        critical fields are not changed once they would affect an
        already-committed render.
        """
        stmt = (
            select(func.count())
            .select_from(Episode)
            .where(Episode.series_id == series_id, Episode.status != "draft")
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
