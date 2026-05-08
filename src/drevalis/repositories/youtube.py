"""YouTube repository — channel and upload query helpers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.youtube_channel import (
    YouTubeAudiobookUpload,
    YouTubeChannel,
    YouTubePlaylist,
    YouTubeUpload,
)

from .base import BaseRepository


class YouTubeChannelRepository(BaseRepository[YouTubeChannel]):
    """Repository for :class:`YouTubeChannel` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, YouTubeChannel)

    async def get_active(self) -> YouTubeChannel | None:
        """Return the currently active YouTube channel, if any."""
        stmt = select(YouTubeChannel).where(YouTubeChannel.is_active.is_(True)).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_channel_id(self, channel_id: str) -> YouTubeChannel | None:
        """Lookup a channel by its YouTube channel ID string."""
        stmt = select(YouTubeChannel).where(YouTubeChannel.channel_id == channel_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_channels(self) -> list[YouTubeChannel]:
        """Return all connected YouTube channels, newest first."""
        stmt = select(YouTubeChannel).order_by(YouTubeChannel.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate_all(self) -> None:
        """Set is_active=False on all channels."""
        stmt = select(YouTubeChannel).where(YouTubeChannel.is_active.is_(True))
        result = await self.session.execute(stmt)
        for channel in result.scalars().all():
            channel.is_active = False
        await self.session.flush()


class YouTubeUploadRepository(BaseRepository[YouTubeUpload]):
    """Repository for :class:`YouTubeUpload` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, YouTubeUpload)

    async def get_by_episode(self, episode_id: UUID) -> list[YouTubeUpload]:
        """Return all uploads for an episode, newest first."""
        stmt = (
            select(YouTubeUpload)
            .where(YouTubeUpload.episode_id == episode_id)
            .order_by(YouTubeUpload.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent(self, limit: int = 50) -> list[YouTubeUpload]:
        """Return the most recent uploads across all episodes."""
        stmt = select(YouTubeUpload).order_by(YouTubeUpload.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_existing_done(self, episode_id: UUID, channel_id: UUID) -> YouTubeUpload | None:
        """Return the earliest ``done`` upload for an (episode, channel) pair.

        Used as a duplicate-upload guard. If a ``done`` row already exists,
        callers should refuse to enqueue another upload.
        """
        stmt = (
            select(YouTubeUpload)
            .where(
                YouTubeUpload.episode_id == episode_id,
                YouTubeUpload.channel_id == channel_id,
                YouTubeUpload.upload_status == "done",
            )
            .order_by(YouTubeUpload.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_duplicates(self) -> list[list[YouTubeUpload]]:
        """Group ``done`` uploads by (episode_id, channel_id) and return
        every group with more than one row, newest first inside each group.

        The earliest row in each group is treated as the canonical upload;
        the rest are duplicates that should be removed.
        """
        stmt = (
            select(YouTubeUpload)
            .where(YouTubeUpload.upload_status == "done")
            .order_by(
                YouTubeUpload.episode_id,
                YouTubeUpload.channel_id,
                YouTubeUpload.created_at.asc(),
            )
        )
        result = await self.session.execute(stmt)
        groups: dict[tuple[UUID, UUID], list[YouTubeUpload]] = {}
        for row in result.scalars().all():
            key = (row.episode_id, row.channel_id)
            groups.setdefault(key, []).append(row)
        return [g for g in groups.values() if len(g) > 1]


class YouTubeAudiobookUploadRepository(BaseRepository[YouTubeAudiobookUpload]):
    """Repository for :class:`YouTubeAudiobookUpload` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, YouTubeAudiobookUpload)

    async def get_by_audiobook(self, audiobook_id: UUID) -> list[YouTubeAudiobookUpload]:
        """Return all uploads for an audiobook, newest first."""
        stmt = (
            select(YouTubeAudiobookUpload)
            .where(YouTubeAudiobookUpload.audiobook_id == audiobook_id)
            .order_by(YouTubeAudiobookUpload.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class YouTubePlaylistRepository(BaseRepository[YouTubePlaylist]):
    """Repository for :class:`YouTubePlaylist` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, YouTubePlaylist)

    async def get_by_channel(self, channel_id: UUID) -> list[YouTubePlaylist]:
        """Return all playlists for a channel, newest first."""
        stmt = (
            select(YouTubePlaylist)
            .where(YouTubePlaylist.channel_id == channel_id)
            .order_by(YouTubePlaylist.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_youtube_playlist_id(self, youtube_playlist_id: str) -> YouTubePlaylist | None:
        """Lookup a playlist by its YouTube playlist ID string."""
        stmt = select(YouTubePlaylist).where(
            YouTubePlaylist.youtube_playlist_id == youtube_playlist_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
