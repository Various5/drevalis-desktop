"""Video edit session repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.video_edit_session import VideoEditSession

from .base import BaseRepository


class VideoEditSessionRepository(BaseRepository[VideoEditSession]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, VideoEditSession)

    async def get_by_episode(self, episode_id: UUID) -> VideoEditSession | None:
        stmt = select(VideoEditSession).where(VideoEditSession.episode_id == episode_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()
