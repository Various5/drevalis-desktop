"""ScheduledPost repository."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.scheduled_post import ScheduledPost

from .base import BaseRepository


class ScheduledPostRepository(BaseRepository[ScheduledPost]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ScheduledPost)

    async def get_pending(self, before: datetime) -> list[ScheduledPost]:
        stmt = (
            select(ScheduledPost)
            .where(ScheduledPost.status == "scheduled", ScheduledPost.scheduled_at <= before)
            .order_by(ScheduledPost.scheduled_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_content(self, content_type: str, content_id: UUID) -> list[ScheduledPost]:
        stmt = (
            select(ScheduledPost)
            .where(
                ScheduledPost.content_type == content_type, ScheduledPost.content_id == content_id
            )
            .order_by(ScheduledPost.scheduled_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_upcoming(self, limit: int = 20) -> list[ScheduledPost]:
        stmt = (
            select(ScheduledPost)
            .where(ScheduledPost.status == "scheduled")
            .order_by(ScheduledPost.scheduled_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_calendar(self, start: datetime, end: datetime) -> list[ScheduledPost]:
        stmt = (
            select(ScheduledPost)
            .where(ScheduledPost.scheduled_at >= start, ScheduledPost.scheduled_at <= end)
            .order_by(ScheduledPost.scheduled_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def prune_orphaned(self) -> int:
        """Delete scheduled posts whose referenced content row is gone.

        ``content_id`` is polymorphic (episode | audiobook), so the column
        carries no DB-level FK and rows can survive their parent's CASCADE.
        Walk pending + scheduled rows, dropping ones whose content has
        since been deleted. Returns the number of rows pruned.
        """
        from sqlalchemy import delete as _delete
        from sqlalchemy import exists
        from sqlalchemy import select as _select

        from drevalis.models.audiobook import Audiobook
        from drevalis.models.episode import Episode

        # Find orphans first via SELECT so we can return a count without
        # depending on Result.rowcount (typed as missing on SA 2.x).
        ep_orphan_ids = (
            (
                await self.session.execute(
                    _select(ScheduledPost.id).where(
                        ScheduledPost.content_type == "episode",
                        ~exists(_select(1).where(Episode.id == ScheduledPost.content_id)),
                    )
                )
            )
            .scalars()
            .all()
        )
        ab_orphan_ids = (
            (
                await self.session.execute(
                    _select(ScheduledPost.id).where(
                        ScheduledPost.content_type == "audiobook",
                        ~exists(_select(1).where(Audiobook.id == ScheduledPost.content_id)),
                    )
                )
            )
            .scalars()
            .all()
        )

        all_orphans = list(ep_orphan_ids) + list(ab_orphan_ids)
        if all_orphans:
            await self.session.execute(
                _delete(ScheduledPost).where(ScheduledPost.id.in_(all_orphans))
            )
            await self.session.commit()
        return len(all_orphans)
