"""GenerationJob repository — pipeline-step tracking & progress updates."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from drevalis.models.episode import Episode
from drevalis.models.generation_job import GenerationJob

from .base import BaseRepository


class GenerationJobRepository(BaseRepository[GenerationJob]):
    """Repository for :class:`GenerationJob` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, GenerationJob)

    async def get_by_episode(self, episode_id: UUID) -> list[GenerationJob]:
        """Return all jobs for an episode, ordered by pipeline step."""
        stmt = (
            select(GenerationJob)
            .where(GenerationJob.episode_id == episode_id)
            .order_by(GenerationJob.step, GenerationJob.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_jobs(self, limit: int = 50) -> list[GenerationJob]:
        """Return jobs with status ``queued`` or ``running``."""
        stmt = (
            select(GenerationJob)
            .where(GenerationJob.status.in_(("queued", "running")))
            .order_by(GenerationJob.created_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_failed_jobs(self, limit: int = 50) -> list[GenerationJob]:
        """Return jobs with status ``failed``."""
        stmt = (
            select(GenerationJob)
            .where(GenerationJob.status == "failed")
            .order_by(GenerationJob.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_progress(
        self,
        id: UUID,
        progress_pct: int,
    ) -> GenerationJob | None:
        """Update just the progress percentage of a job."""
        return await self.update(id, progress_pct=progress_pct)

    async def update_status(
        self,
        id: UUID,
        status: str,
        error_message: str | None = None,
    ) -> GenerationJob | None:
        """Update the status and optionally set an error message."""
        kwargs: dict[str, Any] = {"status": status}
        if error_message is not None:
            kwargs["error_message"] = error_message
        return await self.update(id, **kwargs)

    async def get_all_filtered(
        self,
        *,
        status_filter: str | None = None,
        episode_id: UUID | None = None,
        step: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[GenerationJob]:
        """Return jobs with optional filters, eagerly loading episode + series."""
        stmt = (
            select(GenerationJob)
            .options(selectinload(GenerationJob.episode).selectinload(Episode.series))
            .order_by(GenerationJob.created_at.desc())
        )
        if status_filter is not None:
            stmt = stmt.where(GenerationJob.status == status_filter)
        if episode_id is not None:
            stmt = stmt.where(GenerationJob.episode_id == episode_id)
        if step is not None:
            stmt = stmt.where(GenerationJob.step == step)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_by_episode_and_step(
        self,
        episode_id: UUID,
        step: str,
    ) -> GenerationJob | None:
        """Return the most recent job for a given episode and pipeline step."""
        stmt = (
            select(GenerationJob)
            .where(
                GenerationJob.episode_id == episode_id,
                GenerationJob.step == step,
            )
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_done_steps(self, episode_id: UUID) -> set[str]:
        """Return the set of pipeline steps that completed successfully.

        One query replaces a per-step loop of
        ``get_latest_by_episode_and_step`` calls when all the caller
        wants to know is "which steps can I skip on this regenerate".
        """
        stmt = (
            select(GenerationJob.step)
            .where(
                GenerationJob.episode_id == episode_id,
                GenerationJob.status == "done",
            )
            .distinct()
        )
        result = await self.session.execute(stmt)
        return {row for row in result.scalars().all()}
