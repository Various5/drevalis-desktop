"""System-level endpoints that must work independently of the Tauri shell.

Currently exposes the desktop **update-status** check behind the in-app
"a new version is available — download it manually" banner.

Why this exists separately from the Tauri updater plugin: the desktop
shell's in-app updater goes through a custom IPC command
(``check_for_channel``) that is subject to Tauri's per-origin ACL. A
mis-scoped ACL once shipped a build whose updater was rejected at runtime
("command check_for_channel not allowed by acl"), and because that command
*is* the update-check path, the broken build could never pull its own fix
(see CHANGELOG v1.0.0-rc.3). This endpoint is a plain HTTP GET the SPA can
call over the same origin it already loads from — no Tauri IPC, no ACL — so
a broken auto-updater can never again leave the user with *no* signal that a
newer build exists. It is deliberately read-only and unauthenticated (it
returns only the app's own version and a public GitHub release manifest), so
it is also exempt from the license gate (see ``core/license/gate.py``) —
an unlicensed/expired install is exactly the one that may need to update.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from drevalis.core.deps import get_redis

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# Channel-specific Tauri updater manifests — the SAME artifacts the Rust
# shell's updater reads (see tauri/src-tauri/src/main.rs UPDATER_*_URL), so
# the banner's notion of "latest" matches what an in-app update would install.
# These are ``releases/latest/download/`` URLs, which 302-redirect to the
# asset — httpx must be told to follow redirects.
_STABLE_MANIFEST_URL = (
    "https://github.com/Various5/drevalis-desktop/releases/latest/download/latest.json"
)
_RC_MANIFEST_URL = (
    "https://github.com/Various5/drevalis-desktop/releases/latest/download/latest-rc.json"
)
# Human-facing page we send the user to for a manual download.
_RELEASES_PAGE_URL = "https://github.com/Various5/drevalis-desktop/releases/latest"

_CACHE_TTL = 30 * 60  # 30 min — release cadence is days; don't hammer GitHub.
_NUMERIC_IDENT = re.compile(r"^\d+$")


class UpdateStatusResponse(BaseModel):
    """Result of the decoupled (non-Tauri) update check."""

    current_version: str
    latest_version: str | None = None
    update_available: bool = False
    channel: str = "stable"
    # Always populated so the UI has somewhere to send the user even when the
    # manifest fetch failed.
    download_url: str = _RELEASES_PAGE_URL
    notes: str | None = None
    pub_date: str | None = None
    # Set when the check couldn't complete (offline, GitHub down, …). The
    # endpoint still returns 200 with ``update_available=False`` so the
    # frontend never has to handle an error path for a best-effort nudge.
    reason: str | None = None


def _current_app_version() -> str:
    """Return the running desktop app's version.

    The Tauri shell injects ``DREVALIS_RELEASE`` (= ``CARGO_PKG_VERSION``,
    e.g. ``1.0.0-rc.4``) into the backend process — that is the authoritative
    source on desktop. ``APP_VERSION`` is the Docker build-arg equivalent. We
    fall back to the installed package metadata, then a ``0.0.0-dev`` sentinel
    for source dev runs so the comparison degrades gracefully rather than
    crashing.
    """
    for var in ("DREVALIS_RELEASE", "APP_VERSION"):
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
    try:
        from importlib.metadata import version

        return version("drevalis")
    except Exception:
        return "0.0.0-dev"


def _version_key(raw: str) -> tuple[tuple[int, int, int], int, tuple[tuple[int, int, str], ...]]:
    """Sortable SemVer-precedence key for the formats this project ships.

    Handles ``MAJOR.MINOR.PATCH`` optionally followed by a ``-<prerelease>``
    (``1.0.0``, ``1.0.0-rc.4``, ``0.1.0-alpha.50``), and tolerates a leading
    ``v`` and trailing ``+build`` metadata. SemVer precedence rules applied:

    * a final release outranks any of its pre-releases (encoded via the middle
      ``1`` vs ``0`` marker);
    * pre-release identifiers are compared field-by-field, numeric ones
      numerically and ranked below alphanumeric ones.
    """
    s = raw.strip().lstrip("vV").split("+", 1)[0]
    release_part, _, pre_part = s.partition("-")

    nums: list[int] = []
    for chunk in release_part.split("."):
        try:
            nums.append(int(chunk))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    release_key = (nums[0], nums[1], nums[2])

    if not pre_part:
        # Marker 1 → final release sorts above any pre-release (marker 0).
        return (release_key, 1, ())

    idents: list[tuple[int, int, str]] = []
    for ident in pre_part.split("."):
        if _NUMERIC_IDENT.match(ident):
            idents.append((0, int(ident), ""))  # numeric: lowest sub-precedence
        else:
            idents.append((1, 0, ident))  # alphanumeric
    return (release_key, 0, tuple(idents))


def _is_newer(latest: str, current: str) -> bool:
    """True when ``latest`` is a strictly newer version than ``current``."""
    try:
        return _version_key(latest) > _version_key(current)
    except Exception:
        # Never suppress a real update because of an unparseable string: a
        # false positive only points the user at a download page, while a
        # false negative hides a fix. Bias toward surfacing it.
        return latest.strip() != current.strip()


async def _fetch_manifest(channel: str, redis: Redis) -> dict[str, Any] | None:
    """Fetch + cache the channel manifest. Returns None on any failure."""
    url = _RC_MANIFEST_URL if channel == "rc" else _STABLE_MANIFEST_URL
    cache_key = f"drevalis:update_manifest:{channel}"

    try:
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            return data if isinstance(data, dict) else None
    except Exception:
        # Redis hiccup — fall through to a live fetch.
        pass

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0), follow_redirects=True
        ) as client:
            resp = await client.get(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "drevalis-creator-studio",
                },
            )
        if resp.status_code != 200:
            logger.info("update_manifest_http_error", channel=channel, status=resp.status_code)
            return None
        manifest = resp.json()
    except Exception as exc:  # noqa: BLE001 — best-effort; never fail the UI.
        logger.info("update_manifest_fetch_failed", channel=channel, error=str(exc)[:120])
        return None

    if not isinstance(manifest, dict):
        return None
    try:
        await redis.setex(cache_key, _CACHE_TTL, json.dumps(manifest))
    except Exception:
        pass
    return manifest


@router.get("/update-status", response_model=UpdateStatusResponse)
async def update_status(
    channel: str = Query("stable", description="Update channel: 'stable' or 'rc'."),
    redis: Redis = Depends(get_redis),
) -> UpdateStatusResponse:
    """Report whether a newer desktop build is published on the user's channel.

    Decoupled from the Tauri updater IPC on purpose — this is a plain HTTP
    check the SPA can rely on even when the in-app updater is broken or
    unreachable. Always returns 200; failures degrade to
    ``update_available=False`` with a ``reason``.
    """
    chan = "rc" if channel == "rc" else "stable"
    current = _current_app_version()

    manifest = await _fetch_manifest(chan, redis)
    if manifest is None:
        return UpdateStatusResponse(
            current_version=current, channel=chan, reason="unavailable"
        )

    raw_latest = manifest.get("version")
    latest = raw_latest.strip() if isinstance(raw_latest, str) and raw_latest.strip() else None
    notes = manifest.get("notes")
    pub_date = manifest.get("pub_date")

    return UpdateStatusResponse(
        current_version=current,
        latest_version=latest,
        update_available=bool(latest and _is_newer(latest, current)),
        channel=chan,
        download_url=_RELEASES_PAGE_URL,
        notes=notes if isinstance(notes, str) and notes.strip() else None,
        pub_date=pub_date if isinstance(pub_date, str) and pub_date.strip() else None,
    )
