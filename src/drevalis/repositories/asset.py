"""Asset + VideoIngestJob repositories."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.asset import Asset, VideoIngestJob

from .base import BaseRepository


class AssetRepository(BaseRepository[Asset]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Asset)

    async def get_by_hash(self, sha256: str) -> Asset | None:
        """Dedup lookup: return the existing row for this hash, or None."""
        stmt = select(Asset).where(Asset.hash_sha256 == sha256)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_ids(self, ids: list[UUID]) -> dict[UUID, Asset]:
        """Return assets for the given IDs, indexed by id (single round-trip)."""
        if not ids:
            return {}
        stmt = select(Asset).where(Asset.id.in_(ids))
        result = await self.session.execute(stmt)
        return {a.id: a for a in result.scalars().all()}

    async def list_filtered(
        self,
        *,
        kind: str | None = None,
        search: str | None = None,
        tag: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Asset]:
        stmt = select(Asset).order_by(Asset.created_at.desc())
        conds = []
        if kind:
            conds.append(Asset.kind == kind)
        if tag:
            conds.append(Asset.tags.any(tag))  # type: ignore[arg-type]
        if search:
            needle = f"%{search.lower()}%"
            conds.append(
                or_(
                    Asset.filename.ilike(needle),
                    Asset.description.ilike(needle),
                )
            )
        if conds:
            stmt = stmt.where(and_(*conds))
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class VideoIngestJobRepository(BaseRepository[VideoIngestJob]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, VideoIngestJob)

    async def get_by_asset_id(self, asset_id: UUID) -> VideoIngestJob | None:
        stmt = select(VideoIngestJob).where(VideoIngestJob.asset_id == asset_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()
