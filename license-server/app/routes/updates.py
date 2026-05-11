"""Release manifest delivery.

Clients poll ``GET /updates/manifest?license=<key>&current=<version>`` to
learn if a newer release is available and where to pull images from.

License gating: only licenses with ``status='active'`` and a ``period_end``
still in the future receive the manifest. Revoked/expired installs get
402, which the frontend translates into "renew to receive updates".

Manifest storage: a single JSON file on disk (``/data/manifest.json`` in
production). Owner updates it via ``POST /admin/updates/publish`` after
pushing new images to GHCR. Keeping it on disk avoids adding a second DB
table for a value that changes less than once a week.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app import db
from app.config import get_settings
from app.routes.admin import _require_admin

router = APIRouter(tags=["updates"])


# ────────────────────────── Manifest storage ──────────────────────────


def _manifest_path() -> Path:
    # Colocated with the SQLite DB on the Fly volume.
    db_path = Path(get_settings().database_path)
    return db_path.parent / "manifest.json"


def _default_manifest() -> dict[str, Any]:
    """Ship a "nothing new" manifest when the owner hasn't published one yet."""
    return {
        "current_stable": "0.0.0",
        "image_tags": {},
        "changelog_url": None,
        "mandatory_security_update": False,
        "published_at": 0,
    }


def _read_manifest() -> dict[str, Any]:
    path = _manifest_path()
    if not path.exists():
        return _default_manifest()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_manifest()


def _write_manifest(data: dict[str, Any]) -> None:
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ────────────────────────── Client: manifest fetch ──────────────────────────


class ManifestResponse(BaseModel):
    current_stable: str
    image_tags: dict[str, str] = Field(default_factory=dict)
    changelog_url: str | None = None
    mandatory_security_update: bool = False
    published_at: int = 0
    update_available: bool
    current_installed: str | None = None


def _semver_tuple(v: str) -> tuple[int, ...]:
    """Best-effort semver comparison. Bad inputs sort as (0,)."""
    try:
        parts = v.lstrip("v").split(".")
        return tuple(int(p.split("-")[0]) for p in parts)
    except Exception:
        return (0,)


@router.get("/updates/manifest", response_model=ManifestResponse)
async def get_manifest(
    license: str = Query(..., min_length=8, description="License key (UUID)"),
    current: str | None = Query(None, description="Client's currently-running version"),
) -> ManifestResponse:
    row = await db.get_license(license)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "license_not_found"},
        )
    if row["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "license_revoked", "hint": "Renew to receive updates."},
        )
    if row["period_end"] < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "license_expired", "hint": "Renew to receive updates."},
        )

    m = _read_manifest()
    update_available = False
    if current and m.get("current_stable"):
        update_available = _semver_tuple(m["current_stable"]) > _semver_tuple(current)

    return ManifestResponse(
        current_stable=m.get("current_stable", "0.0.0"),
        image_tags=m.get("image_tags", {}),
        changelog_url=m.get("changelog_url"),
        mandatory_security_update=bool(m.get("mandatory_security_update", False)),
        published_at=int(m.get("published_at", 0)),
        update_available=update_available,
        current_installed=current,
    )


# ────────────────────────── Admin: publish manifest ──────────────────────────


class PublishRequest(BaseModel):
    current_stable: str
    image_tags: dict[str, str]
    changelog_url: str | None = None
    mandatory_security_update: bool = False


# Image registry allowlist for the updater supply chain. Every manifest
# image MUST match one of these prefixes (registry + owner/org) — the
# updater sidecar has root-equivalent power via /var/run/docker.sock, so
# a compromised admin token that could publish ``attacker/malicious:tag``
# would be catastrophic. Comma-separated override via
# ``UPDATE_IMAGE_ALLOWLIST`` env var for self-hosters using a different
# registry.
import os as _os

_DEFAULT_IMAGE_ALLOWLIST = (
    "ghcr.io/drevaliscs/,"
    "ghcr.io/drevalis/"
)
_IMAGE_ALLOWLIST: tuple[str, ...] = tuple(
    p.strip() for p in _os.environ.get("UPDATE_IMAGE_ALLOWLIST", _DEFAULT_IMAGE_ALLOWLIST).split(",") if p.strip()
)


def _validate_image_tags(image_tags: dict[str, str]) -> None:
    """Reject any image not from an allowlisted registry prefix.

    Also requires each image tag to carry an explicit tag or digest
    (``repo:tag`` or ``repo@sha256:...``) so the updater pulls a
    pinned version — no floating ``:latest`` implicitly upgrading
    past what the admin published.
    """
    for service, image in image_tags.items():
        image_str = str(image).strip()
        if not image_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"empty image tag for service {service!r}",
            )
        if not any(image_str.startswith(prefix) for prefix in _IMAGE_ALLOWLIST):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"image {image_str!r} for {service!r} is not in the "
                    f"registry allowlist {_IMAGE_ALLOWLIST}"
                ),
            )
        # Require a tag or digest — no implicit :latest.
        path_part = image_str.split("/", 2)[-1]
        if ":" not in path_part and "@sha256:" not in image_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"image {image_str!r} for {service!r} must carry an "
                    "explicit tag (``repo:1.2.3``) or digest "
                    "(``repo@sha256:...``); implicit :latest is rejected"
                ),
            )


@router.post(
    "/admin/updates/publish",
    dependencies=[Depends(_require_admin)],
    response_model=ManifestResponse,
)
async def publish_manifest(body: PublishRequest) -> ManifestResponse:
    """Owner writes the new manifest after pushing images to GHCR.

    Typically called from the GitHub Actions workflow that publishes a
    release — see the release pipeline notes in the main repo README.

    Image tags are validated against the registry allowlist; a
    compromised admin token cannot point customers at attacker-
    controlled images.
    """
    _validate_image_tags(body.image_tags)
    data = {
        "current_stable": body.current_stable,
        "image_tags": body.image_tags,
        "changelog_url": body.changelog_url,
        "mandatory_security_update": body.mandatory_security_update,
        "published_at": int(time.time()),
    }
    _write_manifest(data)
    return ManifestResponse(
        **data,
        update_available=False,
        current_installed=None,
    )


@router.get(
    "/admin/updates/current",
    dependencies=[Depends(_require_admin)],
)
async def get_current_manifest() -> dict:
    return _read_manifest()
