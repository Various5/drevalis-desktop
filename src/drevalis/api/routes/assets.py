"""Central asset library routes.

The asset library is the single place where user-provided media lives
(reference images, B-roll, raw ingest videos, custom music, logos).
Everywhere else in the app references an ``asset_id`` rather than
duplicating bytes.

Endpoints:

- ``POST /api/v1/assets``             multipart upload — sniffs mime +
                                      probes dimensions/duration; dedups
                                      by SHA-256.
- ``GET  /api/v1/assets``             list with kind / tag / search
                                      filter + pagination.
- ``GET  /api/v1/assets/{id}``        single asset metadata.
- ``GET  /api/v1/assets/{id}/file``   streams the raw file for preview.
- ``PATCH /api/v1/assets/{id}``       update tags / description.
- ``DELETE /api/v1/assets/{id}``      remove from library + delete file.

Layering: the route owns multipart parse + ffprobe + mime sniff
(FastAPI / runtime concerns); ``AssetService`` owns DB unit-of-work
+ dedup + file teardown.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession  # runtime import — FastAPI Depends

from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError
from drevalis.services.asset import AssetService

if TYPE_CHECKING:
    from drevalis.core.config import Settings
    from drevalis.models.asset import Asset

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["assets"])


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AssetService:
    return AssetService(db, settings.storage_base_path)


# Kinds we sniff from mime type prefix. ``other`` is the catch-all.
_MIME_KIND: dict[str, str] = {
    "image/": "image",
    "video/": "video",
    "audio/": "audio",
}

# Max upload size (hard cap at the HTTP layer — the frontend should
# reject larger files sooner). Raise cautiously: this lives in RAM
# during the multipart parse.
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    filename: str
    file_path: str
    file_size_bytes: int
    mime_type: str | None
    hash_sha256: str
    width: int | None
    height: int | None
    duration_seconds: float | None
    tags: list[str]
    description: str | None
    created_at: datetime

    @classmethod
    def from_orm(cls, a: Asset) -> AssetResponse:
        return cls(
            id=a.id,
            kind=a.kind,
            filename=a.filename,
            file_path=a.file_path,
            file_size_bytes=a.file_size_bytes,
            mime_type=a.mime_type,
            hash_sha256=a.hash_sha256,
            width=a.width,
            height=a.height,
            duration_seconds=a.duration_seconds,
            tags=list(a.tags or []),
            description=a.description,
            created_at=a.created_at,
        )


class AssetUpdate(BaseModel):
    tags: list[str] | None = None
    description: str | None = None


# ──────────────────────────────────────────────────────────────────────


def _kind_from_mime(mime: str | None) -> str:
    if not mime:
        return "other"
    for prefix, kind in _MIME_KIND.items():
        if mime.startswith(prefix):
            return kind
    return "other"


def _safe_filename(name: str) -> str:
    # Keep only a narrow allowlist so filesystem + URL paths can't be
    # tricked into traversal. The UUID in the path below is already
    # unique, so losing pretty casing here is cosmetic at worst.
    base = Path(name).name  # strip any directory bits the client sent
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:120] or "asset"


async def _probe_media(path: Path) -> tuple[int | None, int | None, float | None]:
    """Use ffprobe to extract width / height / duration. Returns ``None``
    for each field when ffprobe is missing or the file isn't media."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0 or not stdout:
            return None, None, None
        data = json.loads(stdout)
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None, None

    width = height = None
    duration: float | None = None
    for stream in data.get("streams") or []:
        if stream.get("codec_type") in ("video", "image") and width is None:
            width = stream.get("width")
            height = stream.get("height")
    fmt = data.get("format") or {}
    try:
        if fmt.get("duration"):
            duration = float(fmt["duration"])
    except (TypeError, ValueError):
        duration = None
    return width, height, duration


# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/api/v1/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    file: UploadFile = File(...),
    tags: str | None = Form(default=None),  # comma-separated
    description: str | None = Form(default=None),
    svc: AssetService = Depends(_service),
    settings: Settings = Depends(get_settings),
) -> AssetResponse:
    """Upload a new asset to the central library.

    Deduplication: files with the same SHA-256 collapse to one row. If
    the hash matches an existing asset, the upload returns the existing
    asset (201 Created is still returned for client simplicity).
    """
    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"asset exceeds max size of {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB",
        )
    if not contents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")

    sha256 = hashlib.sha256(contents).hexdigest()

    existing = await svc.get_by_hash(sha256)
    if existing is not None:
        logger.info("asset_upload_deduped", asset_id=str(existing.id), hash=sha256)
        return AssetResponse.from_orm(existing)

    kind = _kind_from_mime(file.content_type)
    filename = _safe_filename(file.filename or "asset")
    asset_id = uuid4()
    # Store as storage/assets/<kind>s/<uuid>/<safe-filename>
    kind_dir = f"{kind}s" if kind != "other" else "other"
    rel_path = Path("assets") / kind_dir / str(asset_id) / filename
    abs_path = Path(settings.storage_base_path) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(contents)

    width, height, duration = await _probe_media(abs_path)

    tag_list: list[str] = []
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()][:20]

    asset = await svc.create(
        id=asset_id,
        kind=kind,
        filename=filename,
        file_path=rel_path.as_posix(),
        file_size_bytes=len(contents),
        mime_type=file.content_type,
        hash_sha256=sha256,
        width=width,
        height=height,
        duration_seconds=duration,
        tags=tag_list,
        description=description,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    logger.info(
        "asset_uploaded",
        asset_id=str(asset.id),
        kind=asset.kind,
        size=asset.file_size_bytes,
    )
    return AssetResponse.from_orm(asset)


@router.get("/api/v1/assets", response_model=list[AssetResponse])
async def list_assets(
    kind: str | None = Query(default=None, pattern="^(image|video|audio|other)$"),
    search: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=60),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    svc: AssetService = Depends(_service),
) -> list[AssetResponse]:
    rows = await svc.list_filtered(kind=kind, search=search, tag=tag, offset=offset, limit=limit)
    return [AssetResponse.from_orm(a) for a in rows]


@router.get("/api/v1/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: UUID,
    svc: AssetService = Depends(_service),
) -> AssetResponse:
    try:
        a = await svc.get(asset_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "asset not found") from exc
    return AssetResponse.from_orm(a)


@router.get("/api/v1/assets/{asset_id}/file")
async def get_asset_file(
    asset_id: UUID,
    svc: AssetService = Depends(_service),
) -> FileResponse:
    try:
        a = await svc.get(asset_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "asset not found") from exc
    abs_path = svc.absolute_file_path(a)
    if not abs_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "asset file missing on disk")
    return FileResponse(str(abs_path), media_type=a.mime_type or "application/octet-stream")


@router.patch("/api/v1/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: UUID,
    body: AssetUpdate,
    svc: AssetService = Depends(_service),
) -> AssetResponse:
    changes: dict[str, Any] = {}
    if body.tags is not None:
        changes["tags"] = [t.strip() for t in body.tags if t.strip()][:20]
    if body.description is not None:
        changes["description"] = body.description
    try:
        a = await svc.update_metadata(asset_id, **changes)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "asset not found") from exc
    return AssetResponse.from_orm(a)


@router.delete("/api/v1/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: UUID,
    svc: AssetService = Depends(_service),
) -> None:
    await svc.delete(asset_id)
