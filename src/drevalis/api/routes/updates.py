"""Update status + apply endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from drevalis.core.deps import get_redis, get_settings
from drevalis.core.license.features import fastapi_dep_require_feature
from drevalis.services.updates import check_for_updates, request_update_apply

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from drevalis.core.config import Settings


router = APIRouter(
    prefix="/api/v1/updates",
    tags=["updates"],
    # Updates are part of the subscription — gate behind an active license.
    dependencies=[Depends(fastapi_dep_require_feature("basic_generation"))],
)


class UpdateStatusResponse(BaseModel):
    current_installed: str | None = None
    current_stable: str | None = None
    update_available: bool = False
    mandatory_security_update: bool = False
    changelog_url: str | None = None
    image_tags: dict[str, str] = {}
    unavailable: bool = False
    reason: str | None = None


class ApplyResponse(BaseModel):
    queued: bool
    hint: str


class ProgressResponse(BaseModel):
    """Last status frame written by the updater sidecar.

    Phases (sequential):
      - ``idle``        : no update in progress
      - ``pulling``     : ``docker compose pull`` running
      - ``pulled``      : pull finished, about to recreate services
      - ``restarting``  : ``docker compose up -d`` running
      - ``done``        : stack restarted successfully
      - ``failed``      : pull or restart failed; ``detail`` explains why

    ``started_at`` is set on the first frame of a cycle and kept until
    the cycle finishes, so the UI can render elapsed time.
    """

    phase: str = "idle"
    detail: str = ""
    ts: str = ""
    started_at: str = ""


@router.get("/status", response_model=UpdateStatusResponse)
async def get_status(
    force: bool = Query(False, description="Bypass cache"),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> UpdateStatusResponse:
    manifest = await check_for_updates(
        redis,
        server_url=settings.license_server_url,
        force=force,
    )
    return UpdateStatusResponse(**manifest)


@router.get("/progress", response_model=ProgressResponse)
async def get_progress() -> ProgressResponse:
    """Return the last phase the updater wrote.

    Polled by the frontend's full-screen update overlay at ~1.5s cadence.
    During the ``restarting`` phase this app container itself gets
    recycled, so the frontend also needs to handle the endpoint going
    unreachable - that transition is itself a progress signal.
    """
    import json
    from pathlib import Path

    status_path = Path("/shared/update_status.json")
    if not status_path.exists():
        return ProgressResponse()  # idle defaults
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ProgressResponse(phase="idle", detail="status file unreadable")
    return ProgressResponse(
        phase=data.get("phase", "idle"),
        detail=data.get("detail", ""),
        ts=data.get("ts", ""),
        started_at=data.get("started_at", ""),
    )


class ChangelogEntry(BaseModel):
    """A single GitHub release — tag, title, body, date, URL."""

    version: str
    name: str
    body: str
    published_at: str | None = None
    html_url: str | None = None
    is_prerelease: bool = False


class ChangelogResponse(BaseModel):
    entries: list[ChangelogEntry] = []
    cached: bool = False
    source: str = "github"
    error: str | None = None


@router.get("/changelog", response_model=ChangelogResponse)
async def get_changelog(
    limit: int = Query(20, ge=1, le=100),
    force: bool = Query(False, description="Bypass the 1-hour Redis cache"),
    redis: Redis = Depends(get_redis),
) -> ChangelogResponse:
    """Return recent release notes from the project's GitHub repo.

    Cached in Redis for 1 hour so a chatty UI doesn't burn the
    unauthenticated GitHub API quota (60/hr). ``?force=true`` bypasses
    the cache when the user explicitly hits a refresh button.
    """
    import json

    import httpx

    cache_key = f"drevalis:changelog:limit:{limit}"
    if not force:
        try:
            cached = await redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                return ChangelogResponse(**data, cached=True)
        except Exception:
            # Redis hiccup — fall through to a live fetch.
            pass

    url = f"https://api.github.com/repos/DrevalisCS/creator-studio/releases?per_page={limit}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "drevalis-creator-studio",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 403:
            # Rate limited or corporate proxy. Return any stale cache we
            # have rather than surfacing an empty list to the UI.
            try:
                cached = await redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    return ChangelogResponse(
                        **data,
                        cached=True,
                        error="GitHub API rate limited; showing cached data",
                    )
            except Exception:
                pass
            return ChangelogResponse(error="GitHub API rate limited — try again in 10 minutes")
        if resp.status_code != 200:
            return ChangelogResponse(error=f"GitHub returned HTTP {resp.status_code}")
        releases = resp.json()
    except (httpx.NetworkError, httpx.TimeoutException) as exc:
        return ChangelogResponse(
            error=f"Could not reach GitHub: {type(exc).__name__}",
        )
    except Exception as exc:  # noqa: BLE001 — defensive for UI
        return ChangelogResponse(
            error=f"Unexpected error: {type(exc).__name__}: {str(exc)[:120]}",
        )

    entries = [
        ChangelogEntry(
            version=r.get("tag_name") or "",
            name=r.get("name") or r.get("tag_name") or "",
            body=r.get("body") or "",
            published_at=r.get("published_at"),
            html_url=r.get("html_url"),
            is_prerelease=bool(r.get("prerelease")),
        )
        for r in releases
        if isinstance(r, dict)
    ]

    payload = {"entries": [e.model_dump() for e in entries]}
    try:
        # 1-hour cache; within that window, the endpoint stays snappy
        # + GitHub isn't hit repeatedly even if the user refreshes.
        await redis.setex(cache_key, 3600, json.dumps(payload))
    except Exception:
        pass

    return ChangelogResponse(**payload)


@router.post("/apply", response_model=ApplyResponse)
async def apply_update() -> ApplyResponse:
    """Ask the updater sidecar to pull new images and restart the stack.

    This is fire-and-forget: the sidecar reads a flag file, runs
    ``docker compose pull && up -d --remove-orphans``, and the new
    containers take over. The browser will reconnect automatically when
    the new frontend comes back online.
    """
    try:
        await request_update_apply()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "could_not_queue_update", "reason": str(exc)[:200]},
        ) from exc
    return ApplyResponse(
        queued=True,
        hint=(
            "Update queued. The updater sidecar pulls new images and "
            "restarts the stack within ~60 seconds. Reload the page once "
            "you see the connection drop and recover."
        ),
    )
