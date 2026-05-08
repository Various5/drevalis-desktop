"""Custom music track management.

Creators can upload their own music beds for use on a series. Tracks
live under ``storage/music/custom/`` and are referenced from the
series' ``music_mood`` field using a ``custom:<filename>`` prefix —
this keeps the existing mood plumbing untouched and transparently
falls through to :class:`MusicService`, which already knows how to
resolve that prefix.

Endpoints:

- ``GET    /api/v1/music/custom``              list uploaded tracks
- ``POST   /api/v1/music/custom``              multipart upload
- ``DELETE /api/v1/music/custom/{filename}``   remove a track + sidecar

Per-track sidechain overrides (``music_volume_db``, ``fade_in``,
``fade_out``) live as a small ``{filename}.json`` sidecar in the same
directory. Getting/putting those is a single ``PUT`` on the track
metadata.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from drevalis.core.config import Settings
from drevalis.core.deps import get_settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/music", tags=["music"])


_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB — plenty for a 5-minute stereo MP3
_ALLOWED_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class CustomTrack(BaseModel):
    filename: str
    size_bytes: int
    music_volume_db: float | None = Field(
        default=None,
        description="Per-track sidechain override in dB. When null, the series' music_volume_db wins.",
    )
    fade_in_seconds: float | None = None
    fade_out_seconds: float | None = None


class CustomTrackUpdate(BaseModel):
    music_volume_db: float | None = None
    fade_in_seconds: float | None = None
    fade_out_seconds: float | None = None


def _custom_dir(settings: Settings) -> Path:
    root = (settings.storage_base_path / "music" / "custom").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    """Sanitise a user-supplied filename. Rejects path-traversal attempts and
    collapses unusual characters so the stored name is predictable."""
    name = Path(name).name  # strip any directory components
    if not name or name.startswith("."):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_filename")
    safe = _SAFE_NAME_RE.sub("_", name)
    if len(safe) > 160:
        safe = safe[:160]
    return safe


def _sidecar_for(track_path: Path) -> Path:
    return track_path.with_suffix(track_path.suffix + ".json")


def _load_sidecar(track_path: Path) -> dict[str, Any]:
    sc = _sidecar_for(track_path)
    if not sc.exists():
        return {}
    try:
        data = json.loads(sc.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@router.get("/custom", response_model=list[CustomTrack])
async def list_custom_tracks(settings: Settings = Depends(get_settings)) -> list[CustomTrack]:
    """List every uploaded custom track + its per-track sidechain overrides."""
    root = _custom_dir(settings)
    out: list[CustomTrack] = []
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _ALLOWED_EXTS:
            continue
        meta = _load_sidecar(p)
        out.append(
            CustomTrack(
                filename=p.name,
                size_bytes=p.stat().st_size,
                music_volume_db=meta.get("music_volume_db"),
                fade_in_seconds=meta.get("fade_in_seconds"),
                fade_out_seconds=meta.get("fade_out_seconds"),
            )
        )
    return out


@router.post("/custom", response_model=CustomTrack, status_code=status.HTTP_201_CREATED)
async def upload_custom_track(
    file: UploadFile = File(..., description="MP3/WAV/OGG/FLAC/M4A, up to 25 MB"),
    settings: Settings = Depends(get_settings),
) -> CustomTrack:
    """Upload a music bed. Overwrites silently if a file with the same
    (sanitised) name already exists — users can iterate on the same
    track by re-uploading."""
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing_filename")
    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            {
                "error": "unsupported_audio_type",
                "hint": f"Allowed: {', '.join(sorted(_ALLOWED_EXTS))}",
                "received": ext or "(none)",
            },
        )

    safe_name = _safe_filename(file.filename)
    dest = _custom_dir(settings) / safe_name

    written = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(64 * 1024):
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    {"error": "track_too_large", "max_mb": _MAX_UPLOAD_BYTES // 1024 // 1024},
                )
            fh.write(chunk)

    logger.info("music_custom_uploaded", filename=safe_name, size=written)
    meta = _load_sidecar(dest)
    return CustomTrack(
        filename=safe_name,
        size_bytes=written,
        music_volume_db=meta.get("music_volume_db"),
        fade_in_seconds=meta.get("fade_in_seconds"),
        fade_out_seconds=meta.get("fade_out_seconds"),
    )


@router.put("/custom/{filename}", response_model=CustomTrack)
async def update_custom_track(
    filename: str,
    body: CustomTrackUpdate,
    settings: Settings = Depends(get_settings),
) -> CustomTrack:
    """Update the per-track sidechain/fade overrides. Writes a JSON
    sidecar next to the audio file."""
    safe_name = _safe_filename(filename)
    track = _custom_dir(settings) / safe_name
    if not track.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "track_not_found")

    meta = _load_sidecar(track)
    payload = body.model_dump(exclude_unset=True)
    # Deliberate: explicit None clears the override (falls back to series default).
    for k, v in payload.items():
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    if meta:
        _sidecar_for(track).write_text(json.dumps(meta), encoding="utf-8")
    else:
        _sidecar_for(track).unlink(missing_ok=True)
    return CustomTrack(
        filename=safe_name,
        size_bytes=track.stat().st_size,
        music_volume_db=meta.get("music_volume_db"),
        fade_in_seconds=meta.get("fade_in_seconds"),
        fade_out_seconds=meta.get("fade_out_seconds"),
    )


@router.delete("/custom/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_track(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> None:
    safe_name = _safe_filename(filename)
    track = _custom_dir(settings) / safe_name
    if track.exists():
        track.unlink()
    _sidecar_for(track).unlink(missing_ok=True)
    logger.info("music_custom_deleted", filename=safe_name)
