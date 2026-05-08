"""Social platform repository -- platform and upload query helpers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.social_platform import SocialPlatform, SocialUpload

from .base import BaseRepository


class SocialPlatformRepository(BaseRepository[SocialPlatform]):
    """Repository for :class:`SocialPlatform` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SocialPlatform)

    async def get_active_by_platform(self, platform: str) -> SocialPlatform | None:
        """Return the currently active account for a given platform, if any."""
        stmt = (
            select(SocialPlatform)
            .where(
                SocialPlatform.platform == platform,
                SocialPlatform.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list[SocialPlatform]:
        """Return all active platform accounts across all platforms."""
        stmt = (
            select(SocialPlatform)
            .where(SocialPlatform.is_active.is_(True))
            .order_by(SocialPlatform.platform, SocialPlatform.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate_platform(self, platform: str) -> None:
        """Set is_active=False on all accounts for a given platform."""
        stmt = select(SocialPlatform).where(
            SocialPlatform.platform == platform,
            SocialPlatform.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        for account in result.scalars().all():
            account.is_active = False
        await self.session.flush()


class SocialUploadRepository(BaseRepository[SocialUpload]):
    """Repository for :class:`SocialUpload` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SocialUpload)

    async def get_by_content(
        self,
        content_type: str,
        content_id: UUID,
    ) -> list[SocialUpload]:
        """Return all uploads for a specific piece of content, newest first."""
        stmt = (
            select(SocialUpload)
            .where(
                SocialUpload.content_type == content_type,
                SocialUpload.episode_id == content_id,
            )
            .order_by(SocialUpload.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_platform(
        self,
        platform_id: UUID,
        limit: int = 50,
    ) -> list[SocialUpload]:
        """Return the most recent uploads for a platform account."""
        stmt = (
            select(SocialUpload)
            .where(SocialUpload.platform_id == platform_id)
            .order_by(SocialUpload.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent(self, limit: int = 50) -> list[SocialUpload]:
        """Return the most recent uploads across all platforms."""
        stmt = select(SocialUpload).order_by(SocialUpload.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_platform_stats(self) -> list[dict[str, Any]]:
        """Aggregate upload counts and engagement per platform.

        Returns a list of dicts with keys: platform, total_uploads,
        successful_uploads, total_views, total_likes, total_comments, total_shares.
        """
        stmt = (
            select(
                SocialPlatform.platform,
                func.count(SocialUpload.id).label("total_uploads"),
                func.count(SocialUpload.id)
                .filter(SocialUpload.upload_status == "done")
                .label("successful_uploads"),
                func.coalesce(func.sum(SocialUpload.views), 0).label("total_views"),
                func.coalesce(func.sum(SocialUpload.likes), 0).label("total_likes"),
                func.coalesce(func.sum(SocialUpload.comments), 0).label("total_comments"),
                func.coalesce(func.sum(SocialUpload.shares), 0).label("total_shares"),
            )
            .join(SocialPlatform, SocialUpload.platform_id == SocialPlatform.id)
            .group_by(SocialPlatform.platform)
        )
        result = await self.session.execute(stmt)
        return [
            {
                "platform": row.platform,
                "total_uploads": row.total_uploads,
                "successful_uploads": row.successful_uploads,
                "total_views": row.total_views,
                "total_likes": row.total_likes,
                "total_comments": row.total_comments,
                "total_shares": row.total_shares,
            }
            for row in result.all()
        ]
