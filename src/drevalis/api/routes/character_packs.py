"""Character pack routes.

Packs are reusable bundles of ``character_lock`` + ``style_lock`` with
a display name, optional description, and thumbnail asset. Applying a
pack copies its lock payloads onto a series; deleting the pack does
not retroactively affect series that used it.

Layering: this router calls ``CharacterPackService`` only. No
repository or model imports here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.deps import get_db
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.license.features import fastapi_dep_require_feature
from drevalis.services.character_pack import CharacterPackService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Character + style locks is a Pro+ feature per the marketing pricing matrix.
router = APIRouter(
    prefix="/api/v1/character-packs",
    tags=["character-packs"],
    dependencies=[Depends(fastapi_dep_require_feature("character_packs"))],
)


def _service(db: AsyncSession = Depends(get_db)) -> CharacterPackService:
    return CharacterPackService(db)


class CharacterPackResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    thumbnail_asset_id: UUID | None
    character_lock: dict[str, Any] | None
    style_lock: dict[str, Any] | None
    created_at: datetime


class CharacterPackCreate(BaseModel):
    name: str
    description: str | None = None
    thumbnail_asset_id: UUID | None = None
    character_lock: dict[str, Any] | None = None
    style_lock: dict[str, Any] | None = None


class ApplyPackRequest(BaseModel):
    series_id: UUID


def _to_response(p: Any) -> CharacterPackResponse:
    return CharacterPackResponse(
        id=p.id,
        name=p.name,
        description=p.description,
        thumbnail_asset_id=p.thumbnail_asset_id,
        character_lock=p.character_lock,
        style_lock=p.style_lock,
        created_at=p.created_at,
    )


@router.get("", response_model=list[CharacterPackResponse])
async def list_packs(
    svc: CharacterPackService = Depends(_service),
) -> list[CharacterPackResponse]:
    rows = await svc.list()
    return [_to_response(r) for r in rows]


@router.post(
    "",
    response_model=CharacterPackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pack(
    body: CharacterPackCreate,
    svc: CharacterPackService = Depends(_service),
) -> CharacterPackResponse:
    try:
        pack = await svc.create(
            name=body.name,
            description=body.description,
            thumbnail_asset_id=body.thumbnail_asset_id,
            character_lock=body.character_lock,
            style_lock=body.style_lock,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
    return _to_response(pack)


@router.delete("/{pack_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pack(
    pack_id: UUID,
    svc: CharacterPackService = Depends(_service),
) -> None:
    await svc.delete(pack_id)


@router.post("/{pack_id}/apply", response_model=dict)
async def apply_pack(
    pack_id: UUID,
    body: ApplyPackRequest,
    svc: CharacterPackService = Depends(_service),
) -> dict[str, Any]:
    """Copy this pack's lock payloads onto a series. Overwrites existing
    character_lock + style_lock on the series.
    """
    try:
        result = await svc.apply(pack_id, body.series_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    logger.info(
        "character_pack_applied",
        pack=str(pack_id),
        series=str(body.series_id),
    )
    return result
