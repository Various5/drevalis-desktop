"""Episode repository — filtering, eager-loading, status helpers, soft-delete.

Every read method excludes soft-deleted rows (``deleted_at IS NOT NULL``).
``soft_delete`` / ``restore`` move episodes in and out of the trash; the
inherited ``delete`` remains a hard purge for permanent removal.
"""

from __future__ import annotations

from datetime import UTC, datetime
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

    # ── Read (soft-deleted rows excluded) ────────────────────────────────

    async def get_by_id(self, id: UUID) -> Episode | None:
        """Fetch a single live episode by id, or *None* (trashed → None)."""
        stmt = select(Episode).where(Episode.id == id, Episode.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(self, offset: int = 0, limit: int = 100) -> list[Episode]:
        stmt = (
            select(Episode)
            .where(Episode.deleted_at.is_(None))
            .order_by(Episode.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        stmt = select(func.count()).select_from(Episode).where(Episode.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_by_series(
        self,
        series_id: UUID,
        status_filter: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Episode]:
        """List live episodes for a series, optionally filtered by status."""
        stmt = (
            select(Episode)
            .where(Episode.series_id == series_id, Episode.deleted_at.is_(None))
            .order_by(Episode.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if status_filter is not None:
            stmt = stmt.where(Episode.status == status_filter)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_assets(self, id: UUID) -> Episode | None:
        """Load a live episode with its media_assets and generation_jobs."""
        stmt = (
            select(Episode)
            .where(Episode.id == id, Episode.deleted_at.is_(None))
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
        """Return the most recently created live episodes across all series."""
        stmt = (
            select(Episode)
            .options(selectinload(Episode.series))
            .where(Episode.deleted_at.is_(None))
            .order_by(Episode.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_ids(self, ids: list[UUID]) -> dict[UUID, Episode]:
        """Return live episodes for the given IDs, indexed by id.

        Single round-trip replacement for a per-id ``get_by_id`` loop;
        missing (or trashed) rows are simply absent from the returned dict.
        """
        if not ids:
            return {}
        stmt = select(Episode).where(Episode.id.in_(ids), Episode.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return {ep.id: ep for ep in result.scalars().all()}

    async def get_by_status(self, status: str, limit: int = 50) -> list[Episode]:
        """Return all live episodes with the given status."""
        stmt = (
            select(Episode)
            .options(selectinload(Episode.series))
            .where(Episode.status == status, Episode.deleted_at.is_(None))
            .order_by(Episode.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_status(self, status: str) -> int:
        """Return the count of live episodes with the given status."""
        stmt = (
            select(func.count())
            .select_from(Episode)
            .where(Episode.status == status, Episode.deleted_at.is_(None))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_non_draft_for_series(self, series_id: UUID) -> int:
        """Count live episodes of *series_id* past the ``draft`` status.

        Used by the series-update endpoint to enforce that pipeline-critical
        fields aren't changed once they'd affect an already-committed render.
        """
        stmt = (
            select(func.count())
            .select_from(Episode)
            .where(
                Episode.series_id == series_id,
                Episode.status != "draft",
                Episode.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # ── Soft-delete / restore ────────────────────────────────────────────

    async def soft_delete(self, id: UUID) -> bool:
        """Move an episode to the trash (set ``deleted_at``). Operates on the
        raw row so it bypasses the alive filter. Returns False if the episode
        doesn't exist or is already trashed."""
        instance = await self.session.get(Episode, id)
        if instance is None or instance.deleted_at is not None:
            return False
        instance.deleted_at = datetime.now(tz=UTC)
        await self.session.flush()
        return True

    async def restore(self, id: UUID) -> Episode | None:
        """Bring a trashed episode back (clear ``deleted_at``). Returns the
        episode, or None if it doesn't exist or isn't trashed."""
        instance = await self.session.get(Episode, id)
        if instance is None or instance.deleted_at is None:
            return None
        instance.deleted_at = None
        await self.session.flush()
        await self.session.refresh(instance)
        return instance
