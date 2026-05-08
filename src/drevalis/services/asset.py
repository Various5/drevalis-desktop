"""AssetService — central asset library orchestration.

Layering: keeps the route file free of repository imports and the
filesystem cleanup logic (audit F-A-01).

Heavy bits the route owned (multipart parse, ffprobe, mime sniff)
stay in the route layer because they're FastAPI / runtime concerns —
the service handles the DB unit-of-work + dedup + file teardown.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError
from drevalis.repositories.asset import AssetRepository

if TYPE_CHECKING:
    from drevalis.models.asset import Asset

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class AssetService:
    def __init__(self, db: AsyncSession, storage_base_path: Path) -> None:
        self._db = db
        self._storage = Path(storage_base_path)
        self._repo = AssetRepository(db)

    async def get_by_hash(self, sha256: str) -> Asset | None:
        return await self._repo.get_by_hash(sha256)

    async def get(self, asset_id: UUID) -> Asset:
        a = await self._repo.get_by_id(asset_id)
        if a is None:
            raise NotFoundError("asset", asset_id)
        return a

    async def list_filtered(
        self,
        *,
        kind: str | None = None,
        search: str | None = None,
        tag: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Asset]:
        return await self._repo.list_filtered(
            kind=kind, search=search, tag=tag, offset=offset, limit=limit
        )

    async def create(self, **payload: Any) -> Asset:
        asset = await self._repo.create(**payload)
        await self._db.commit()
        return asset

    async def update_metadata(self, asset_id: UUID, **changes: Any) -> Asset:
        a = await self._repo.get_by_id(asset_id)
        if a is None:
            raise NotFoundError("asset", asset_id)
        if changes:
            await self._repo.update(asset_id, **changes)
            await self._db.commit()
            a = await self._repo.get_by_id(asset_id)
            assert a is not None
        return a

    async def delete(self, asset_id: UUID) -> None:
        """Delete is idempotent (matches previous in-route 204 behaviour)
        and best-effort cleans the on-disk directory."""
        a = await self._repo.get_by_id(asset_id)
        if a is None:
            return

        import shutil

        abs_dir = self._storage / Path(a.file_path).parent
        try:
            if abs_dir.exists():
                shutil.rmtree(abs_dir)
        except OSError:
            logger.warning("asset_file_cleanup_failed", asset_id=str(asset_id), exc_info=True)
        await self._repo.delete(asset_id)
        await self._db.commit()

    def absolute_file_path(self, asset: Asset) -> Path:
        """Resolve an asset's file path against the storage base."""
        return self._storage / asset.file_path
