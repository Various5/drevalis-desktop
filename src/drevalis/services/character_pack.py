"""CharacterPackService — bundles character_lock + style_lock for re-use.

Layering: keeps the router free of repository imports (audit F-A-01).
``apply()`` orchestrates two repos (CharacterPack via direct session
access for simple gets, SeriesRepository for the lock copy) — exactly
the kind of cross-resource flow that justifies a service layer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.models.character_pack import CharacterPack
from drevalis.repositories.series import SeriesRepository


class CharacterPackService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list(self) -> list[CharacterPack]:
        result = await self._db.execute(
            select(CharacterPack).order_by(CharacterPack.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        thumbnail_asset_id: UUID | None,
        character_lock: dict[str, Any] | None,
        style_lock: dict[str, Any] | None,
    ) -> CharacterPack:
        if not name.strip():
            raise ValidationError("name required")
        pack = CharacterPack(
            name=name.strip()[:120],
            description=(description or "").strip() or None,
            thumbnail_asset_id=thumbnail_asset_id,
            character_lock=character_lock,
            style_lock=style_lock,
        )
        self._db.add(pack)
        await self._db.commit()
        await self._db.refresh(pack)
        return pack

    async def delete(self, pack_id: UUID) -> None:
        # Delete is idempotent — missing pack is a no-op (matches the
        # previous in-route 204 behaviour).
        pack = await self._db.get(CharacterPack, pack_id)
        if pack is None:
            return
        await self._db.delete(pack)
        await self._db.commit()

    async def apply(self, pack_id: UUID, series_id: UUID) -> dict[str, Any]:
        """Copy a pack's lock payloads onto a series. Overwrites existing
        character_lock + style_lock on the series.
        """
        pack = await self._db.get(CharacterPack, pack_id)
        if pack is None:
            raise NotFoundError("character pack", pack_id)

        series_repo = SeriesRepository(self._db)
        series = await series_repo.get_by_id(series_id)
        if series is None:
            raise NotFoundError("series", series_id)

        await series_repo.update(
            series.id,
            character_lock=pack.character_lock,
            style_lock=pack.style_lock,
        )
        await self._db.commit()
        return {
            "series_id": str(series.id),
            "character_lock": pack.character_lock,
            "style_lock": pack.style_lock,
        }
