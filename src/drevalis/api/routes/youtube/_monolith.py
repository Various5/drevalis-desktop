"""YouTube integration API routes — OAuth, upload, playlists, analytics.

Layering: this router calls ``YouTubeAdminService`` (route
orchestration) + the existing ``YouTubeService`` (upstream API client)
only. No repository imports here (audit F-A-01).

The module-level ``build_youtube_service`` re-export is kept because
the audiobooks route imports it directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import html as _html

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_redis, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.redis import get_arq_pool
from drevalis.schemas.youtube import (
    PlaylistAddVideo,
    PlaylistCreate,
    PlaylistResponse,
    VideoStatsResponse,
    YouTubeAuthURLResponse,
    YouTubeChannelResponse,
    YouTubeChannelUpdate,
    YouTubeConnectionStatus,
    YouTubeUploadListResponse,
    YouTubeUploadRequest,
    YouTubeUploadResponse,
)
from drevalis.services.youtube import (
    AnalyticsNotAuthorized,
    YouTubeService,
    YouTubeTokenExpiredError,
    fetch_token_scopes,
)
from drevalis.services.youtube_admin import (
    ChannelCapExceededError,
    DuplicateUploadError,
    MultipleChannelsAmbiguousError,
    NoChannelConnectedError,
    TokenRefreshError,
    YouTubeAdminService,
    YouTubeNotConfiguredError,
)
from drevalis.services.youtube_admin import (
    build_youtube_service as _build_youtube_service,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/youtube", tags=["youtube"])


# Public re-export — audiobooks route imports this directly. Mapping
# the YouTubeNotConfiguredError to HTTP happens here so callers get a
# consistent 503 shape.
async def build_youtube_service(settings: Settings, db: AsyncSession) -> YouTubeService:
    try:
        return await _build_youtube_service(settings, db)
    except YouTubeNotConfiguredError as exc:
        if exc.has_id_row or exc.has_secret_row:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "youtube_key_decrypt_failed",
                    "hint": (
                        "YouTube keys ARE stored in the DB but can't be decrypted "
                        "with the current ENCRYPTION_KEY. This usually means a "
                        "backup was restored onto a different encryption key. "
                        "Either restore the original ENCRYPTION_KEY in your .env, "
                        "or delete the old keys under Settings → API Keys and "
                        "re-enter them so they're re-encrypted."
                    ),
                    "id_stored": exc.has_id_row,
                    "secret_stored": exc.has_secret_row,
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "YouTube integration is not configured. Set "
                "YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET in your .env "
                "file, OR add them via Settings → Integrations → YouTube "
                "(they'll be Fernet-encrypted at rest)."
            ),
        ) from exc


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> YouTubeAdminService:
    return YouTubeAdminService(db, settings)


def _ambiguous_channel_400(exc: MultipleChannelsAmbiguousError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error": "channel_id_required",
            "reason": (
                "Multiple YouTube channels are connected. Pass "
                "?channel_id=<uuid> to specify which channel this operation targets."
            ),
            "connected_channels": [
                {"id": str(c.id), "channel_id": c.channel_id, "name": c.channel_name}
                for c in exc.channels
            ],
        },
    )


def _token_expired_401(exc: Exception, channel_id: object | None = None) -> HTTPException:
    """Build the 401 ``youtube_token_expired`` response the frontend keys off
    to render a per-channel "Reconnect" CTA. Shared by every route that can
    surface a dead/revoked grant (``TokenRefreshError`` from the explicit
    refresh, or ``YouTubeTokenExpiredError`` from an auto-refresh inside a
    Data/Analytics API call)."""
    detail: dict[str, Any] = {
        "error": "youtube_token_expired",
        "reason": str(exc),
        "hint": "Reconnect this channel via Settings → YouTube.",
    }
    if channel_id is not None:
        detail["channel_id"] = str(channel_id)
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


# ── OAuth flow ───────────────────────────────────────────────────────────


@router.get(
    "/auth-url",
    response_model=YouTubeAuthURLResponse,
    status_code=status.HTTP_200_OK,
    summary="Get YouTube OAuth authorization URL",
)
async def get_auth_url(
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> YouTubeAuthURLResponse:
    """Generate and return the Google OAuth consent URL.

    The ``state`` parameter is recorded in Redis (10-minute TTL) so the
    callback endpoint can verify it has not been forged. This prevents
    CSRF attacks where an attacker tricks the operator into binding an
    attacker-controlled YouTube channel to this install.
    """
    svc = await build_youtube_service(settings, db)
    url, state = svc.get_auth_url()
    try:
        await redis.setex(f"youtube_oauth_state:{state}", 600, "1")
    except Exception:
        logger.warning("youtube_oauth_state_persist_failed", exc_info=True)
    logger.info("youtube_auth_url_generated", state=state)
    return YouTubeAuthURLResponse(auth_url=url)


_OAUTH_CALLBACK_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{title} — Drevalis Creator Studio</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  :root {{ color-scheme: dark light; }}
  body {{
    margin: 0; padding: 0;
    min-height: 100vh;
    display: flex; align-items: center; justify-content: center;
    background: #0e1116; color: #e6e6e6;
    font: 15px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  }}
  .card {{
    max-width: 480px; padding: 32px 36px; border-radius: 14px;
    background: #161b22; border: 1px solid #2a2f37;
    box-shadow: 0 8px 40px rgba(0,0,0,0.35);
    text-align: center;
  }}
  .icon {{ font-size: 44px; line-height: 1; margin-bottom: 10px; }}
  h1 {{ margin: 0 0 8px; font-size: 20px; font-weight: 600; }}
  p {{ margin: 0 0 6px; color: #aab2c0; }}
  code {{
    display: inline-block; padding: 2px 6px; border-radius: 4px;
    background: #0b0e13; color: #d7dde5; font-size: 13px;
  }}
  .ok {{ color: #34d399; }}
  .err {{ color: #f87171; }}
</style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1 class="{status_class}">{title}</h1>
    <p>{body}</p>
    <p style="margin-top:14px;color:#6b7280;font-size:13px;">
      You can close this tab and return to Drevalis Creator Studio.
    </p>
  </div>
  <script>
    // Try to close ourselves shortly — works only when this tab was
    // script-opened by something we control; otherwise the close call
    // is silently ignored and the message above guides the user.
    setTimeout(function () {{ try {{ window.close(); }} catch (_) {{ }} }}, 800);
  </script>
</body>
</html>
"""


def _oauth_html(*, ok: bool, title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        _OAUTH_CALLBACK_HTML_TEMPLATE.format(
            title=_html.escape(title),
            body=_html.escape(body),
            icon="✓" if ok else "✕",
            status_class="ok" if ok else "err",
        ),
        status_code=status.HTTP_200_OK if ok else status.HTTP_400_BAD_REQUEST,
    )


@router.get(
    "/callback",
    response_class=HTMLResponse,
    summary="Handle YouTube OAuth callback",
)
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str | None = Query(None, description="OAuth state parameter"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
    admin: YouTubeAdminService = Depends(_service),
) -> HTMLResponse:
    """Exchange the OAuth authorization code for tokens, store channel info.

    Returns a small HTML success/failure page instead of a JSON payload
    because the user lands here in an *external* browser window — the
    Drevalis SPA polls its own backend separately. JSON would just dump
    raw text on the user's screen with no instruction on what to do next.
    """
    if not state:
        return _oauth_html(
            ok=False,
            title="Missing OAuth state",
            body=(
                "The authorization response was missing the state parameter. "
                "Return to Drevalis and try the Connect channel flow again."
            ),
        )
    state_key = f"youtube_oauth_state:{state}"
    try:
        # Atomic get-and-delete via Lua EVAL. We can't use ``redis.getdel``
        # directly because the bundled tporadowski/redis sidecar pins
        # Windows builds to Redis 5.0.14.1, and ``GETDEL`` only landed in
        # Redis 6.2. EVAL has been stable since 2.6 so this works on
        # every supported Redis version (bundled or system-installed).
        stored = await redis.eval(
            "local v = redis.call('GET', KEYS[1]); "
            "if v then redis.call('DEL', KEYS[1]) end; "
            "return v",
            1,
            state_key,
        )
    except Exception:
        logger.error("youtube_oauth_state_lookup_failed", exc_info=True)
        return _oauth_html(
            ok=False,
            title="OAuth state store unreachable",
            body=(
                "Drevalis couldn't verify the OAuth state — the local Redis "
                "sidecar may be down. Return to Drevalis and try again."
            ),
        )
    if not stored:
        return _oauth_html(
            ok=False,
            title="Authorization expired",
            body=(
                "The authorization link expired or was already used. Return to "
                "Drevalis and start the Connect channel flow again."
            ),
        )

    yt_service = await build_youtube_service(settings, db)
    try:
        channel_info = await yt_service.handle_callback(code, state=state)
    except Exception:
        logger.error("youtube_oauth_callback_failed", exc_info=True)
        return _oauth_html(
            ok=False,
            title="Couldn't finish the YouTube connection",
            body=(
                "Google returned a successful consent but Drevalis couldn't "
                "exchange the code for tokens. Check the in-app event log "
                "for details, then retry."
            ),
        )

    try:
        channel = await admin.upsert_oauth_channel(channel_info)
    except ChannelCapExceededError as exc:
        return _oauth_html(
            ok=False,
            title="Channel limit reached",
            body=(
                f"Your current tier ({exc.tier}) allows up to {exc.limit} "
                "channels. Upgrade or remove an existing channel in "
                "Settings → YouTube before connecting another."
            ),
        )

    # Kick off the channel-video sync in the background. This populates
    # ``youtube_channel_videos`` with what's already live on the channel
    # so the dashboard shows accurate "X videos / Y shorts" counts and
    # we can detect duplicates before re-uploading. Best-effort —
    # failure here is logged but doesn't break the connect flow.
    try:
        arq = get_arq_pool()
        await arq.enqueue_job("sync_youtube_channel_videos", str(channel.id))
        logger.info("youtube_channel_sync_enqueued", channel_id=str(channel.id))
    except Exception:
        logger.warning("youtube_channel_sync_enqueue_failed", exc_info=True)

    return _oauth_html(
        ok=True,
        title=f"Connected {channel.channel_name}",
        body=(
            "Drevalis is already polling for the new channel and will update "
            "the YouTube section in a few seconds."
        ),
    )


# ── Connection status / channels ─────────────────────────────────────────


@router.get(
    "/status",
    response_model=YouTubeConnectionStatus,
    status_code=status.HTTP_200_OK,
    summary="Check YouTube connection status",
)
async def connection_status(
    admin: YouTubeAdminService = Depends(_service),
) -> YouTubeConnectionStatus:
    all_channels, active = await admin.connection_status()
    if not all_channels:
        return YouTubeConnectionStatus(connected=False, channel=None, channels=[])

    channel_responses = [YouTubeChannelResponse.model_validate(c) for c in all_channels]
    primary = YouTubeChannelResponse.model_validate(active) if active else channel_responses[0]
    return YouTubeConnectionStatus(connected=True, channel=primary, channels=channel_responses)


# ── Channel videos (synced from YouTube) ─────────────────────────────────


@router.get(
    "/channels/{channel_id}/videos",
    status_code=status.HTTP_200_OK,
    summary="List videos that exist on the connected channel",
)
async def list_channel_videos(
    channel_id: UUID,
    kind: Literal["all", "shorts", "longform"] = Query(
        default="all",
        description="Filter by video kind. ``shorts`` = duration ≤ 60s.",
    ),
    source: Literal["all", "drevalis", "external"] = Query(
        default="all",
        description=(
            "Filter by who uploaded it. ``drevalis`` = only videos with "
            "a matching YouTubeUpload row (status='done'). ``external`` "
            "= only videos that have no Drevalis upload trail."
        ),
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Return videos previously enumerated by ``sync_youtube_channel_videos``.

    Empty list + ``synced=False`` means the sync job hasn't run yet for
    this channel (or returned zero videos). Hit ``POST .../resync`` to
    kick off a fresh enumeration.
    """
    from sqlalchemy import and_ as _and, func as _func, select as _select
    from sqlalchemy.orm import aliased

    from drevalis.models.youtube_channel import (
        YouTubeChannel,
        YouTubeChannelVideo,
        YouTubeUpload,
    )

    channel = await db.get(YouTubeChannel, channel_id)
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel_not_found",
        )

    # Outer-join YouTubeUpload so we can both annotate rows with
    # uploaded_via_drevalis AND filter on the join state. Each
    # YouTubeChannelVideo can have at most one ``done`` upload per
    # channel (Drevalis enforces channel/episode dedup); the COALESCE
    # below keeps a NULL when no upload exists.
    UploadAlias = aliased(YouTubeUpload)
    join_cond = _and(
        UploadAlias.youtube_video_id == YouTubeChannelVideo.youtube_video_id,
        UploadAlias.channel_id == YouTubeChannelVideo.channel_id,
        UploadAlias.upload_status == "done",
    )
    # Also pull ``UploadAlias.title`` so the frontend can detect drift
    # between the YouTube-side title (which the user may have edited
    # directly on YouTube) and the title we recorded at upload time.
    q = (
        _select(YouTubeChannelVideo, UploadAlias.episode_id, UploadAlias.title)
        .outerjoin(UploadAlias, join_cond)
        .where(YouTubeChannelVideo.channel_id == channel_id)
    )
    if kind == "shorts":
        q = q.where(YouTubeChannelVideo.is_short.is_(True))
    elif kind == "longform":
        q = q.where(YouTubeChannelVideo.is_short.is_(False))
    if source == "drevalis":
        q = q.where(UploadAlias.episode_id.is_not(None))
    elif source == "external":
        q = q.where(UploadAlias.episode_id.is_(None))
    q = q.order_by(YouTubeChannelVideo.published_at.desc().nulls_last())

    # ``total`` is the count over the *same* (kind, source) filter pair
    # so the UI's pagination footer reads correctly. Build a parallel
    # count query rather than running the full select(...).count()
    # which materialises every row.
    total_q = (
        _select(_func.count(YouTubeChannelVideo.id))
        .select_from(YouTubeChannelVideo)
        .outerjoin(UploadAlias, join_cond)
        .where(YouTubeChannelVideo.channel_id == channel_id)
    )
    if kind == "shorts":
        total_q = total_q.where(YouTubeChannelVideo.is_short.is_(True))
    elif kind == "longform":
        total_q = total_q.where(YouTubeChannelVideo.is_short.is_(False))
    if source == "drevalis":
        total_q = total_q.where(UploadAlias.episode_id.is_not(None))
    elif source == "external":
        total_q = total_q.where(UploadAlias.episode_id.is_(None))
    total = int((await db.execute(total_q)).scalar_one() or 0)

    rows = (await db.execute(q.limit(limit).offset(offset))).all()
    last_sync = max(
        (row[0].last_synced_at for row in rows if row[0].last_synced_at),
        default=None,
    )

    # Fall back to the Redis sync-marker when there are no video rows
    # for this channel. Worker writes the marker after every sync
    # (even on empty channels) so the UI can show "Synced at T, 0
    # videos" rather than "Never synced". Without this the empty-but-
    # synced state is indistinguishable from never-synced.
    sync_marker_meta: dict[str, Any] = {}
    if last_sync is None:
        try:
            raw = await redis.get(f"youtube:last_sync:{channel_id}")
            if raw:
                marker_str = raw.decode() if isinstance(raw, bytes) else str(raw)
                # Format from worker: "<iso>|synced=N|shorts=N|longform=N"
                parts = marker_str.split("|")
                if parts:
                    from datetime import datetime as _dt

                    try:
                        last_sync = _dt.fromisoformat(parts[0])
                    except ValueError:
                        pass
                    for p in parts[1:]:
                        if "=" in p:
                            k, v = p.split("=", 1)
                            try:
                                sync_marker_meta[k] = int(v)
                            except ValueError:
                                sync_marker_meta[k] = v
        except Exception:
            # Best-effort. If Redis is down the endpoint still works,
            # the frontend just doesn't get the empty-channel marker.
            pass

    # Quick aggregate counts so the UI can render "120 videos · 87 shorts"
    # without a second round trip.
    shorts_q = _select(_func.count()).select_from(YouTubeChannelVideo).where(
        YouTubeChannelVideo.channel_id == channel_id,
        YouTubeChannelVideo.is_short.is_(True),
    )
    longform_q = _select(_func.count()).select_from(YouTubeChannelVideo).where(
        YouTubeChannelVideo.channel_id == channel_id,
        YouTubeChannelVideo.is_short.is_(False),
    )
    shorts_total = int((await db.execute(shorts_q)).scalar_one() or 0)
    longform_total = int((await db.execute(longform_q)).scalar_one() or 0)

    return {
        "channel_id": str(channel_id),
        "total": total,
        "shorts_total": shorts_total,
        "longform_total": longform_total,
        "last_synced_at": last_sync.isoformat() if last_sync else None,
        "videos": [
            {
                "id": str(v.id),
                "youtube_video_id": v.youtube_video_id,
                "title": v.title,
                "description": v.description,
                "thumbnail_url": v.thumbnail_url,
                "published_at": v.published_at.isoformat() if v.published_at else None,
                "duration_seconds": v.duration_seconds,
                "is_short": v.is_short,
                "privacy_status": v.privacy_status,
                "view_count": v.view_count,
                "like_count": v.like_count,
                "comment_count": v.comment_count,
                "url": f"https://www.youtube.com/watch?v={v.youtube_video_id}",
                "uploaded_via_drevalis": ep_id is not None,
                "drevalis_episode_id": str(ep_id) if ep_id else None,
                # Title at upload time (per YouTubeUpload row). When this
                # differs from ``title`` the user edited the video on
                # YouTube after Drevalis published it; the UI surfaces
                # the drift so the operator can reconcile.
                "drevalis_local_title": local_title,
                "title_drifted": bool(
                    local_title is not None
                    and local_title.strip()
                    and local_title.strip() != (v.title or "").strip()
                ),
            }
            for v, ep_id, local_title in rows
        ],
    }


@router.post(
    "/channels/{channel_id}/videos/{video_pk}/import-as-episode",
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft episode pre-filled from an existing channel video",
)
async def import_video_as_episode(
    channel_id: UUID,
    video_pk: UUID,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Take a video that exists on the YouTube channel (synced by
    ``sync_youtube_channel_videos``) and create a new Drevalis Episode
    pre-filled from its title + description. Useful for back-filling
    episode rows for content that was uploaded before Drevalis was
    connected, so the Library page's "External" tab can be bulk-
    imported into the workflow.

    Body::

        {"series_id": "<uuid>"}

    The created episode is in ``draft`` status with the YouTube video
    URL stored in ``metadata_["youtube_video_url"]`` so the analytics
    cross-match picks it up. A reconciliation ``YouTubeUpload`` row
    (status='done') is also inserted so the episode shows as
    "Uploaded via Drevalis" in the Library going forward.
    """
    from drevalis.models.episode import Episode
    from drevalis.models.youtube_channel import (
        YouTubeChannel,
        YouTubeChannelVideo,
        YouTubeUpload,
    )

    series_id_raw = payload.get("series_id")
    if not series_id_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="series_id is required",
        )
    try:
        series_id = UUID(str(series_id_raw))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="series_id must be a UUID",
        ) from exc

    channel = await db.get(YouTubeChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="channel_not_found")
    video = await db.get(YouTubeChannelVideo, video_pk)
    if video is None or video.channel_id != channel_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="video_not_found")

    yt_url = f"https://www.youtube.com/watch?v={video.youtube_video_id}"
    episode = Episode(
        series_id=series_id,
        title=video.title or "Imported from YouTube",
        topic=(video.description or "")[:1000] or None,
        status="exported",  # already live on YouTube, no need to generate
        metadata_={
            "youtube_video_url": yt_url,
            "youtube_video_id": video.youtube_video_id,
            "imported_from_youtube": True,
            "imported_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    db.add(episode)
    await db.flush()  # populate episode.id

    upload = YouTubeUpload(
        episode_id=episode.id,
        channel_id=channel.id,
        youtube_video_id=video.youtube_video_id,
        youtube_url=yt_url,
        title=video.title or "",
        description=video.description,
        privacy_status=video.privacy_status or "public",
        upload_status="done",
    )
    db.add(upload)
    await db.commit()

    return {
        "episode_id": str(episode.id),
        "series_id": str(series_id),
        "youtube_video_id": video.youtube_video_id,
        "youtube_url": yt_url,
        "message": (
            f"Imported '{video.title}' as a new episode in status=exported. "
            "Find it in the series detail page or open it from the Library."
        ),
    }


@router.post(
    "/channels/{channel_id}/videos/{video_pk}/republish-as-draft",
    status_code=status.HTTP_201_CREATED,
    summary="Seed a brand-new Drevalis-generated episode from an existing channel video",
)
async def republish_video_as_draft(
    channel_id: UUID,
    video_pk: UUID,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Use an existing YouTube video's title + description as the seed
    for a fresh Drevalis-generated episode.

    Different from ``import-as-episode``:
    - ``status='draft'`` so the pipeline will actually generate
      (vs ``exported`` for import, which marks the existing
      external video as already-published).
    - No reconciliation ``YouTubeUpload`` row is created — this is
      a NEW episode that, when generated and uploaded, will be a
      *separate* listing on the channel.

    Body::

        {"series_id": "<uuid>"}

    Use case: "I have an old YouTube video, I want Drevalis to
    re-create the same topic with a fresh AI-generated script and
    voiceover, then publish it as a new video on the same channel."
    The pre-existing video stays untouched on YouTube; the new
    episode is independent.
    """
    from drevalis.models.episode import Episode
    from drevalis.models.youtube_channel import YouTubeChannel, YouTubeChannelVideo

    series_id_raw = payload.get("series_id")
    if not series_id_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="series_id is required",
        )
    try:
        series_id = UUID(str(series_id_raw))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="series_id must be a UUID",
        ) from exc

    channel = await db.get(YouTubeChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="channel_not_found")
    video = await db.get(YouTubeChannelVideo, video_pk)
    if video is None or video.channel_id != channel_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="video_not_found")

    episode = Episode(
        series_id=series_id,
        title=video.title or "Republished from YouTube",
        topic=(video.description or "")[:1000] or video.title or None,
        status="draft",
        metadata_={
            "republished_from_youtube": {
                "channel_id": str(channel_id),
                "source_video_id": video.youtube_video_id,
                "source_url": f"https://www.youtube.com/watch?v={video.youtube_video_id}",
                "republished_at": datetime.now(tz=UTC).isoformat(),
            }
        },
    )
    db.add(episode)
    await db.commit()

    return {
        "episode_id": str(episode.id),
        "series_id": str(series_id),
        "source_video_id": video.youtube_video_id,
        "message": (
            f"Created a draft episode seeded from '{video.title}'. "
            "Open the episode and click Generate to produce the new video."
        ),
    }


@router.get(
    "/channels/stats-overview",
    status_code=status.HTTP_200_OK,
    summary="Per-channel aggregates over the synced YouTubeChannelVideo table",
)
async def channels_stats_overview(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Channel-wide aggregates from the ``youtube_channel_videos`` sync
    table. Surfaces everything the user's YouTube channel has on it —
    not just videos Drevalis uploaded — so the YouTube dashboard can
    show "your channel has 141 videos, 4.2M views total" alongside
    the Drevalis-only-uploads stats.

    Output::

      {"channels": [
         {"channel_id": "...", "channel_name": "...",
          "youtube_channel_id": "UC...",
          "total_videos": 29, "shorts": 14, "longform": 15,
          "total_views": 1234, "total_likes": 67, "total_comments": 8,
          "last_synced_at": "...",
          "top_video": {"video_id": "...", "title": "...",
                        "thumbnail_url": "...", "view_count": 500,
                        "url": "https://..."}},
         ...],
       "totals": {"channels": 9, "total_videos": 141,
                  "total_views": 4200000, "total_likes": 50000,
                  "total_comments": 3000}}
    """
    from sqlalchemy import func as _func, select as _select

    from drevalis.models.youtube_channel import YouTubeChannel, YouTubeChannelVideo

    channels = (await db.execute(_select(YouTubeChannel))).scalars().all()
    channel_out: list[dict[str, Any]] = []
    grand_videos = 0
    grand_views = 0
    grand_likes = 0
    grand_comments = 0

    for ch in channels:
        agg = (
            await db.execute(
                _select(
                    _func.count(YouTubeChannelVideo.id),
                    _func.coalesce(_func.sum(YouTubeChannelVideo.view_count), 0),
                    _func.coalesce(_func.sum(YouTubeChannelVideo.like_count), 0),
                    _func.coalesce(_func.sum(YouTubeChannelVideo.comment_count), 0),
                    _func.max(YouTubeChannelVideo.last_synced_at),
                ).where(YouTubeChannelVideo.channel_id == ch.id)
            )
        ).one()
        # Aggregate is_short separately — SQLite doesn't sum booleans
        # cleanly across dialects.
        shorts_count = int(
            (
                await db.execute(
                    _select(_func.count())
                    .select_from(YouTubeChannelVideo)
                    .where(YouTubeChannelVideo.channel_id == ch.id)
                    .where(YouTubeChannelVideo.is_short.is_(True))
                )
            ).scalar_one()
            or 0
        )
        total_videos = int(agg[0] or 0)
        total_views = int(agg[1] or 0)
        total_likes = int(agg[2] or 0)
        total_comments = int(agg[3] or 0)
        last_sync = agg[4]

        # Fallback to Redis marker for empty channels so the UI can
        # still distinguish "synced + empty" from "never synced".
        if last_sync is None:
            try:
                raw = await redis.get(f"youtube:last_sync:{ch.id}")
                if raw:
                    marker_str = (
                        raw.decode() if isinstance(raw, bytes) else str(raw)
                    )
                    from datetime import datetime as _dt

                    try:
                        last_sync = _dt.fromisoformat(marker_str.split("|", 1)[0])
                    except ValueError:
                        pass
            except Exception:
                pass

        top = (
            await db.execute(
                _select(YouTubeChannelVideo)
                .where(YouTubeChannelVideo.channel_id == ch.id)
                .order_by(YouTubeChannelVideo.view_count.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        channel_out.append(
            {
                "channel_id": str(ch.id),
                "channel_name": ch.channel_name,
                "youtube_channel_id": ch.channel_id,
                "is_active": ch.is_active,
                "total_videos": total_videos,
                "shorts": shorts_count,
                "longform": total_videos - shorts_count,
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "last_synced_at": last_sync.isoformat() if last_sync else None,
                "top_video": (
                    {
                        "video_id": str(top.id),
                        "youtube_video_id": top.youtube_video_id,
                        "title": top.title,
                        "thumbnail_url": top.thumbnail_url,
                        "view_count": top.view_count,
                        "is_short": top.is_short,
                        "url": f"https://www.youtube.com/watch?v={top.youtube_video_id}",
                    }
                    if top is not None
                    else None
                ),
            }
        )
        grand_videos += total_videos
        grand_views += total_views
        grand_likes += total_likes
        grand_comments += total_comments

    return {
        "channels": channel_out,
        "totals": {
            "channels": len(channel_out),
            "total_videos": grand_videos,
            "total_views": grand_views,
            "total_likes": grand_likes,
            "total_comments": grand_comments,
        },
    }


@router.get(
    "/videos",
    status_code=status.HTTP_200_OK,
    summary="Flat list of every synced video across every connected channel",
)
async def list_all_videos(
    kind: Literal["all", "shorts", "longform"] = Query(default="all"),
    channel_id: UUID | None = Query(
        default=None,
        description="Optional channel filter. Omitted = all channels.",
    ),
    sort: Literal["views", "likes", "comments", "published"] = Query(
        default="views",
        description="Column to sort by — always descending.",
    ),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """One-shot fetch for the new Videos tab. Returns every synced
    video joined to its channel name + id, no per-channel round trip.
    Assumes the synced channel videos *are* the user's Drevalis-
    produced content — the cross-match flag on YouTubeUpload is no
    longer surfaced here, because users on pre-current versions
    don't necessarily have those rows and the cross-match was
    causing every video to appear as ``external``.
    """
    from sqlalchemy import func as _func, select as _select

    from drevalis.models.youtube_channel import YouTubeChannel, YouTubeChannelVideo

    q = (
        _select(YouTubeChannelVideo, YouTubeChannel.channel_name)
        .join(YouTubeChannel, YouTubeChannel.id == YouTubeChannelVideo.channel_id)
    )
    if channel_id is not None:
        q = q.where(YouTubeChannelVideo.channel_id == channel_id)
    if kind == "shorts":
        q = q.where(YouTubeChannelVideo.is_short.is_(True))
    elif kind == "longform":
        q = q.where(YouTubeChannelVideo.is_short.is_(False))

    sort_col = {
        "views": YouTubeChannelVideo.view_count.desc(),
        "likes": YouTubeChannelVideo.like_count.desc(),
        "comments": YouTubeChannelVideo.comment_count.desc(),
        "published": YouTubeChannelVideo.published_at.desc().nulls_last(),
    }[sort]
    q = q.order_by(sort_col)

    total_q = _select(_func.count(YouTubeChannelVideo.id)).select_from(
        YouTubeChannelVideo,
    )
    if channel_id is not None:
        total_q = total_q.where(YouTubeChannelVideo.channel_id == channel_id)
    if kind == "shorts":
        total_q = total_q.where(YouTubeChannelVideo.is_short.is_(True))
    elif kind == "longform":
        total_q = total_q.where(YouTubeChannelVideo.is_short.is_(False))
    total = int((await db.execute(total_q)).scalar_one() or 0)

    rows = (await db.execute(q.limit(limit).offset(offset))).all()
    return {
        "total": total,
        "videos": [
            {
                "id": str(v.id),
                "channel_id": str(v.channel_id),
                "channel_name": ch_name,
                "youtube_video_id": v.youtube_video_id,
                "title": v.title,
                "thumbnail_url": v.thumbnail_url,
                "published_at": v.published_at.isoformat() if v.published_at else None,
                "duration_seconds": v.duration_seconds,
                "is_short": v.is_short,
                "view_count": v.view_count,
                "like_count": v.like_count,
                "comment_count": v.comment_count,
                "url": f"https://www.youtube.com/watch?v={v.youtube_video_id}",
            }
            for v, ch_name in rows
        ],
    }


@router.get(
    "/recent-videos",
    status_code=status.HTTP_200_OK,
    summary="Most-recent videos across all connected channels",
)
async def recent_channel_videos(
    limit: int = Query(default=5, ge=1, le=50),
    channel_id: UUID | None = Query(
        default=None,
        description="Restrict to one channel. Omit to span all connected channels.",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """For the dashboard "your latest YouTube videos" widget.

    Pulls from ``youtube_channel_videos`` (populated by the sync worker
    on connect + resync), ordered by ``published_at DESC``. Joins
    against ``youtube_uploads`` to mark which ones Drevalis itself
    published — that's the foundation for the cross-match feature.
    """
    from sqlalchemy import select as _select
    from sqlalchemy.orm import aliased

    from drevalis.models.youtube_channel import (
        YouTubeChannel,
        YouTubeChannelVideo,
        YouTubeUpload,
    )

    q = (
        _select(YouTubeChannelVideo, YouTubeChannel.channel_name)
        .join(
            YouTubeChannel,
            YouTubeChannel.id == YouTubeChannelVideo.channel_id,
        )
    )
    if channel_id is not None:
        q = q.where(YouTubeChannelVideo.channel_id == channel_id)
    q = q.order_by(YouTubeChannelVideo.published_at.desc().nulls_last()).limit(limit)

    rows = (await db.execute(q)).all()
    if not rows:
        return {"videos": [], "total": 0}

    # Single-shot lookup of which video IDs Drevalis published itself.
    # ``upload_status='done'`` to exclude in-flight / failed rows so the
    # cross-match badge means "actually live on YouTube via Drevalis".
    video_ids = [v.youtube_video_id for v, _ in rows]
    uploads_q = _select(YouTubeUpload.youtube_video_id, YouTubeUpload.episode_id).where(
        YouTubeUpload.youtube_video_id.in_(video_ids),
        YouTubeUpload.upload_status == "done",
    )
    drevalis_map: dict[str, str] = {}
    for vid_id, ep_id in (await db.execute(uploads_q)).all():
        if vid_id:
            drevalis_map[vid_id] = str(ep_id) if ep_id else ""

    return {
        "videos": [
            {
                "id": str(v.id),
                "channel_id": str(v.channel_id),
                "channel_name": name,
                "youtube_video_id": v.youtube_video_id,
                "title": v.title,
                "thumbnail_url": v.thumbnail_url,
                "published_at": v.published_at.isoformat() if v.published_at else None,
                "duration_seconds": v.duration_seconds,
                "is_short": v.is_short,
                "view_count": v.view_count,
                "like_count": v.like_count,
                "url": f"https://www.youtube.com/watch?v={v.youtube_video_id}",
                # Cross-match: if Drevalis uploaded this video, expose
                # the episode_id so the UI can deep-link back into the
                # episode detail page.
                "drevalis_episode_id": drevalis_map.get(v.youtube_video_id),
                "uploaded_via_drevalis": v.youtube_video_id in drevalis_map,
            }
            for v, name in rows
        ],
        "total": len(rows),
    }


@router.post(
    "/check-title-conflict",
    status_code=status.HTTP_200_OK,
    summary="Check if a proposed title is too similar to an existing channel video",
)
async def check_title_conflict(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return existing channel videos whose title is suspiciously close
    to the proposed one.

    Used by the episode-create dialog as an inline warning ("you may
    have already published this"). Pure ``difflib.SequenceMatcher``
    comparison — no LLM call, no network round-trip, sub-100ms even
    for channels with thousands of videos because we keep everything
    in SQLite and run the comparison in Python.

    Request body::

        {"title": "...",
         "channel_id": "...",   // optional, restricts to one channel
         "threshold": 0.7}       // optional, 0..1 (default 0.7)

    Response::

        {"matches": [{"video_id": ..., "title": ...,
                       "similarity": 0.83, "published_at": ...,
                       "url": ..., "is_short": ...}],
         "checked": 412}
    """
    import difflib as _difflib

    from sqlalchemy import select as _select

    from drevalis.models.youtube_channel import YouTubeChannelVideo

    title = str(payload.get("title") or "").strip()
    if not title:
        return {"matches": [], "checked": 0}

    threshold = float(payload.get("threshold") or 0.7)
    threshold = max(0.0, min(1.0, threshold))

    channel_id_raw = payload.get("channel_id")
    channel_filter = None
    if channel_id_raw:
        try:
            channel_filter = UUID(str(channel_id_raw))
        except ValueError:
            pass

    q = _select(YouTubeChannelVideo)
    if channel_filter is not None:
        q = q.where(YouTubeChannelVideo.channel_id == channel_filter)

    rows = (await db.execute(q)).scalars().all()
    norm_title = title.lower()
    matches: list[dict[str, Any]] = []
    for v in rows:
        ratio = _difflib.SequenceMatcher(
            None, norm_title, (v.title or "").lower()
        ).ratio()
        if ratio >= threshold:
            matches.append(
                {
                    "video_id": str(v.id),
                    "youtube_video_id": v.youtube_video_id,
                    "title": v.title,
                    "similarity": round(ratio, 3),
                    "published_at": v.published_at.isoformat() if v.published_at else None,
                    "is_short": v.is_short,
                    "url": f"https://www.youtube.com/watch?v={v.youtube_video_id}",
                }
            )
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return {"matches": matches[:5], "checked": len(rows)}


@router.get(
    "/channels/{channel_id}/drevalis-videos",
    status_code=status.HTTP_200_OK,
    summary="Channel videos that Drevalis itself uploaded (cross-match)",
)
async def list_drevalis_uploaded_videos(
    channel_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Same shape as ``/channels/{id}/videos`` but filtered to videos
    that have a corresponding ``YouTubeUpload`` row with
    ``upload_status='done'``.

    Used by the Analytics view to show only Drevalis-published content
    when the user toggles "Drevalis uploads only".
    """
    from sqlalchemy import func as _func, select as _select

    from drevalis.models.youtube_channel import (
        YouTubeChannel,
        YouTubeChannelVideo,
        YouTubeUpload,
    )

    channel = await db.get(YouTubeChannel, channel_id)
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel_not_found",
        )

    base = (
        _select(YouTubeChannelVideo, YouTubeUpload.episode_id)
        .join(
            YouTubeUpload,
            (YouTubeUpload.youtube_video_id == YouTubeChannelVideo.youtube_video_id)
            & (YouTubeUpload.upload_status == "done"),
        )
        .where(YouTubeChannelVideo.channel_id == channel_id)
    )

    total_q = _select(_func.count()).select_from(base.subquery())
    total = int((await db.execute(total_q)).scalar_one() or 0)

    rows = (
        await db.execute(
            base.order_by(YouTubeChannelVideo.published_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return {
        "channel_id": str(channel_id),
        "total": total,
        "videos": [
            {
                "id": str(v.id),
                "youtube_video_id": v.youtube_video_id,
                "drevalis_episode_id": str(ep_id) if ep_id else None,
                "title": v.title,
                "thumbnail_url": v.thumbnail_url,
                "published_at": v.published_at.isoformat() if v.published_at else None,
                "duration_seconds": v.duration_seconds,
                "is_short": v.is_short,
                "view_count": v.view_count,
                "like_count": v.like_count,
                "comment_count": v.comment_count,
                "url": f"https://www.youtube.com/watch?v={v.youtube_video_id}",
            }
            for v, ep_id in rows
        ],
    }


@router.post(
    "/channels/{channel_id}/resync",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Manually re-enumerate the channel's videos",
)
async def resync_channel_videos(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Re-enqueue the channel-video sync job for a connected channel.

    The same job is enqueued automatically after a successful OAuth
    callback (see ``oauth_callback``). This endpoint is the manual
    "refresh" button — useful after a user uploads a video outside
    Drevalis and wants the dashboard to catch up without waiting for
    the next periodic resync.
    """
    from drevalis.models.youtube_channel import YouTubeChannel

    channel = await db.get(YouTubeChannel, channel_id)
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel_not_found",
        )

    try:
        arq = get_arq_pool()
        await arq.enqueue_job("sync_youtube_channel_videos", str(channel_id))
    except Exception as exc:
        logger.error("resync_enqueue_failed", channel_id=str(channel_id), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"could_not_enqueue: {type(exc).__name__}",
        ) from exc

    return {
        "channel_id": str(channel_id),
        "status": "enqueued",
        "message": "Sync queued — refresh in a few seconds to see the result.",
    }


@router.post(
    "/disconnect",
    status_code=status.HTTP_200_OK,
    summary="Disconnect YouTube channel",
)
async def disconnect(
    channel_id: UUID | None = Query(None, description="Specific channel to disconnect"),
    admin: YouTubeAdminService = Depends(_service),
) -> dict[str, str]:
    """Remove a YouTube channel connection. Destructive by design — when
    multiple channels are connected, ``channel_id`` is REQUIRED."""
    try:
        name = await admin.disconnect(channel_id)
    except MultipleChannelsAmbiguousError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "channel_id_required",
                "reason": (
                    "Multiple channels are connected; disconnect is destructive, "
                    "so the caller must specify which one. Pass ?channel_id=<uuid>."
                ),
                "connected_channels": [
                    {"id": str(c.id), "name": c.channel_name} for c in exc.channels
                ],
            },
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No YouTube channel found to disconnect",
        ) from exc
    return {"message": f"Disconnected YouTube channel: {name}"}


@router.get(
    "/channels",
    response_model=list[YouTubeChannelResponse],
    status_code=status.HTTP_200_OK,
    summary="List all connected YouTube channels",
)
async def list_channels(
    include_inactive: bool = Query(
        False, description="Include channels that have been disconnected"
    ),
    admin: YouTubeAdminService = Depends(_service),
) -> list[YouTubeChannelResponse]:
    """Return connected YouTube channels (active only by default)."""
    channels = await admin.list_channels(include_inactive=include_inactive)
    return [YouTubeChannelResponse.model_validate(c) for c in channels]


@router.delete(
    "/channels/{channel_id}",
    status_code=status.HTTP_200_OK,
    summary="Permanently delete a YouTube channel connection",
)
async def delete_channel(
    channel_id: UUID,
    admin: YouTubeAdminService = Depends(_service),
) -> dict[str, str]:
    try:
        name = await admin.delete_channel(channel_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"YouTube channel {channel_id} not found",
        ) from exc
    return {"message": f"Deleted YouTube channel: {name}"}


@router.put(
    "/channels/{channel_id}",
    response_model=YouTubeChannelResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a YouTube channel's scheduling config",
)
async def update_channel(
    channel_id: UUID,
    payload: YouTubeChannelUpdate,
    admin: YouTubeAdminService = Depends(_service),
) -> YouTubeChannelResponse:
    """Update upload_days and upload_time for a channel."""
    try:
        channel = await admin.update_channel(channel_id, payload.model_dump(exclude_unset=True))
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"YouTube channel {channel_id} not found",
        ) from exc
    return YouTubeChannelResponse.model_validate(channel)


# ── Delete video on YouTube ──────────────────────────────────────────────


@router.delete(
    "/videos/{youtube_video_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a video from YouTube",
)
async def delete_video(
    youtube_video_id: str,
    channel_id: UUID = Query(..., description="Channel that owns the video"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: YouTubeAdminService = Depends(_service),
) -> dict[str, str]:
    """Delete a video from YouTube using the owning channel's tokens."""
    yt_service = await build_youtube_service(settings, db)
    try:
        channel = await admin.resolve_channel(channel_id)
    except NotFoundError as exc:
        raise HTTPException(404, "Channel not found") from exc

    try:
        await admin.refresh_and_persist_tokens(channel, yt_service)
    except TokenRefreshError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "youtube_token_expired",
                "reason": str(exc),
                "hint": "Reconnect this channel via Settings -> YouTube.",
            },
        ) from exc

    try:
        await yt_service.delete_video(
            channel.access_token_encrypted or "",
            channel.refresh_token_encrypted,
            channel.token_expiry,
            youtube_video_id,
        )
    except YouTubeTokenExpiredError as exc:
        raise _token_expired_401(exc, channel.id) from exc
    await db.commit()
    return {"message": f"Deleted video {youtube_video_id}"}


# ── Episode upload ───────────────────────────────────────────────────────


@router.post(
    "/upload/{episode_id}",
    response_model=YouTubeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload an episode to YouTube",
)
async def upload_episode(
    episode_id: UUID,
    payload: YouTubeUploadRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: YouTubeAdminService = Depends(_service),
) -> YouTubeUploadResponse:
    """Upload the episode's video to YouTube. Auto-generates SEO if not
    cached, refreshes tokens, performs the upload, and best-effort adds
    the video to the series playlist."""
    if settings.demo_mode:
        fake_id = "demo_" + episode_id.hex[:11]
        now = datetime.now(tz=UTC)
        return YouTubeUploadResponse(
            id=uuid4(),
            episode_id=episode_id,
            channel_id=payload.channel_id or uuid4(),
            youtube_video_id=fake_id,
            youtube_url=f"https://www.youtube.com/watch?v={fake_id}",
            title=payload.title or "Demo episode",
            description=payload.description or "",
            privacy_status=payload.privacy_status or "private",
            upload_status="done",
            created_at=now,
            updated_at=now,
        )

    yt_service = await build_youtube_service(settings, db)

    try:
        episode, channel, video_path = await admin.resolve_episode_upload_target(
            episode_id, payload.channel_id
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc

    # Resolution order (after the Phase 2.3 prompt overhaul):
    #   1. payload.* (explicit caller override)
    #   2. script.description / .hashtags (vetted by check_script_content)
    #   3. SEO data (LLM call, applies the same banned-vocab rules)
    #   4. episode.title
    # The script step now produces a clean description for shorts +
    # longform; resolving SEO last means we don't burn an LLM call on
    # episodes that already have one. SEO still runs as a fallback when
    # the script field is empty (legacy episodes generated pre-2.3).
    script = episode.script if isinstance(episode.script, dict) else {}
    script_description = script.get("description") if isinstance(script, dict) else ""
    script_description = script_description if isinstance(script_description, str) else ""
    script_hashtags_raw = script.get("hashtags") if isinstance(script, dict) else []
    script_hashtags: list[str] = (
        [h for h in script_hashtags_raw if isinstance(h, str)]
        if isinstance(script_hashtags_raw, list)
        else []
    )

    seo_data: dict[str, Any] = {}
    if not (payload.description and payload.title and payload.tags) or not script_description:
        # Only call the SEO subsystem when we'd actually consume its
        # output — saves up to a 30-second LLM round-trip on uploads
        # whose script + payload already have everything we need.
        seo_data = await admin.get_or_generate_seo(episode)

    upload_title = (
        payload.title
        or (script.get("title") if isinstance(script.get("title"), str) else "")
        or seo_data.get("title")
        or episode.title
    )
    upload_description = (
        payload.description or script_description or seo_data.get("description", "")
    )
    upload_tags = (
        payload.tags or [h.lstrip("#") for h in script_hashtags] or seo_data.get("tags", [])
    )

    # Hashtag tail: prefer the script's own hashtags; only fall back to
    # SEO's when the script didn't supply any.
    hashtags_for_tail = script_hashtags or [
        str(h) for h in seo_data.get("hashtags", []) if isinstance(h, str)
    ]
    if hashtags_for_tail:
        hashtag_str = " ".join(h if h.startswith("#") else f"#{h}" for h in hashtags_for_tail)
        if hashtag_str and hashtag_str not in upload_description:
            sep = "\n\n" if upload_description else ""
            upload_description = f"{upload_description}{sep}{hashtag_str}"

    thumb_path = await admin.get_thumbnail_path(episode_id)

    try:
        await admin.refresh_and_persist_tokens(channel, yt_service, commit=True)
    except TokenRefreshError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "youtube_token_expired",
                "reason": str(exc),
                "hint": "Reconnect this channel via Settings -> YouTube.",
            },
        ) from exc

    try:
        upload = await admin.create_upload_row(
            episode_id=episode_id,
            channel_id=channel.id,
            title=upload_title,
            description=upload_description,
            privacy_status=payload.privacy_status,
        )
    except DuplicateUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_upload",
                "hint": (
                    "This episode is already published on this channel. "
                    "Delete the existing upload first, or use a different "
                    "channel."
                ),
                "existing_upload_id": str(exc.existing_upload_id),
                "existing_video_id": exc.existing_video_id,
            },
        ) from exc

    try:
        upload_result = await yt_service.upload_video(
            access_token_encrypted=channel.access_token_encrypted or "",
            refresh_token_encrypted=channel.refresh_token_encrypted,
            token_expiry=channel.token_expiry,
            video_path=video_path,
            title=upload_title,
            description=upload_description,
            tags=upload_tags,
            privacy_status=payload.privacy_status,
            thumbnail_path=thumb_path,
        )
        await admin.record_upload_success(
            upload,
            video_id=upload_result["video_id"],
            url=upload_result["url"],
            episode_id=episode_id,
        )
        logger.info(
            "youtube_upload_success",
            episode_id=str(episode_id),
            video_id=upload_result["video_id"],
        )

        await admin.auto_add_to_series_playlist(
            yt_service=yt_service,
            episode=episode,
            channel=channel,
            video_id=upload_result["video_id"],
            privacy_status=payload.privacy_status,
        )
    except YouTubeTokenExpiredError as exc:
        # Dead/revoked grant surfaced by the upload's auto-refresh — mark
        # the row failed (so it isn't stuck "uploading") and return the
        # actionable 401 reconnect signal instead of a generic 502.
        await admin.record_upload_failure(upload, str(exc))
        logger.warning("youtube_upload_token_expired", episode_id=str(episode_id))
        raise _token_expired_401(exc, channel.id) from exc
    except Exception as exc:
        await admin.record_upload_failure(upload, str(exc))
        logger.error(
            "youtube_upload_failed",
            episode_id=str(episode_id),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YouTube upload failed: {exc}",
        ) from exc

    return YouTubeUploadResponse.model_validate(upload)


# ── Upload history ───────────────────────────────────────────────────────


@router.get(
    "/uploads",
    response_model=list[YouTubeUploadListResponse],
    status_code=status.HTTP_200_OK,
    summary="List past YouTube uploads",
)
async def list_uploads(
    limit: int = Query(default=1000, ge=1, le=5000),
    admin: YouTubeAdminService = Depends(_service),
) -> list[YouTubeUploadListResponse]:
    uploads = await admin.list_uploads(limit)
    return [YouTubeUploadListResponse.model_validate(u) for u in uploads]


# ── Duplicate-upload sweep ──────────────────────────────────────────────


@router.get(
    "/uploads/duplicates",
    status_code=status.HTTP_200_OK,
    summary="Preview duplicate YouTube uploads grouped by (episode, channel)",
    description=(
        "Lists every (episode_id, channel_id) pair that has more than one "
        "``done`` upload row. The earliest row is treated as canonical; "
        "the rest are surfaced as ``duplicates`` so the operator can "
        "review before calling ``POST /uploads/dedupe``."
    ),
)
async def list_duplicate_uploads(
    admin: YouTubeAdminService = Depends(_service),
) -> dict[str, Any]:
    groups = await admin.find_duplicate_uploads()
    return {"count": len(groups), "groups": groups}


@router.post(
    "/uploads/dedupe",
    status_code=status.HTTP_200_OK,
    summary="Remove duplicate YouTube uploads (keeps earliest, deletes the rest)",
    description=(
        "For every duplicated (episode, channel) pair: keeps the earliest "
        "``done`` upload row, marks the rest as ``failed`` with an audit "
        "note, and (when ``delete_on_youtube=true``) deletes the duplicate "
        "videos from YouTube via the Data API. Idempotent — running it "
        "again on a clean install is a no-op."
    ),
)
async def dedupe_uploads(
    delete_on_youtube: bool = Query(
        default=True,
        description=(
            "When true, the YouTube videos for the duplicate rows are "
            "deleted via the Data API. When false, only the database rows "
            "are marked failed; the videos stay on YouTube."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: YouTubeAdminService = Depends(_service),
) -> dict[str, Any]:
    yt_service = await build_youtube_service(settings, db)
    return await admin.dedupe_uploads(yt_service=yt_service, delete_on_youtube=delete_on_youtube)


# ── Playlist management ──────────────────────────────────────────────────


@router.post(
    "/playlists",
    response_model=PlaylistResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a YouTube playlist",
)
async def create_playlist(
    payload: PlaylistCreate,
    channel_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: YouTubeAdminService = Depends(_service),
) -> PlaylistResponse:
    """Create a new playlist on the specified YouTube channel.

    Pass ``?channel_id=<uuid>`` to target a specific channel. With a
    single connected channel the parameter is optional.
    """
    yt_service = await build_youtube_service(settings, db)
    try:
        channel = await admin.resolve_channel(channel_id)
    except NoChannelConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No YouTube channel connected. Please authorize first.",
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"YouTube channel {channel_id} not found",
        ) from exc
    except MultipleChannelsAmbiguousError as exc:
        raise _ambiguous_channel_400(exc) from exc

    try:
        await admin.refresh_and_persist_tokens(channel, yt_service)
    except TokenRefreshError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "youtube_token_expired", "reason": str(exc)},
        ) from exc

    try:
        yt_playlist = await yt_service.create_playlist(
            access_token_encrypted=channel.access_token_encrypted or "",
            refresh_token_encrypted=channel.refresh_token_encrypted,
            token_expiry=channel.token_expiry,
            title=payload.title,
            description=payload.description,
            privacy_status=payload.privacy_status,
        )
    except YouTubeTokenExpiredError as exc:
        raise _token_expired_401(exc, channel.id) from exc
    except Exception as exc:
        logger.error("youtube_create_playlist_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create playlist: {exc}",
        ) from exc

    playlist = await admin.create_playlist_row(
        channel_id=channel.id,
        youtube_playlist_id=yt_playlist["playlist_id"],
        title=yt_playlist["title"],
        description=yt_playlist["description"] or None,
        privacy_status=yt_playlist["privacy_status"],
        item_count=yt_playlist["item_count"],
    )
    logger.info(
        "youtube_playlist_created_local",
        playlist_db_id=str(playlist.id),
        youtube_playlist_id=playlist.youtube_playlist_id,
    )
    return PlaylistResponse.model_validate(playlist)


@router.get(
    "/playlists",
    response_model=list[PlaylistResponse],
    status_code=status.HTTP_200_OK,
    summary="List managed YouTube playlists",
)
async def list_playlists(
    channel_id: UUID | None = None,
    admin: YouTubeAdminService = Depends(_service),
) -> list[PlaylistResponse]:
    try:
        channel = await admin.resolve_channel(channel_id)
    except NoChannelConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No YouTube channel connected. Please authorize first.",
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"YouTube channel {channel_id} not found",
        ) from exc
    except MultipleChannelsAmbiguousError as exc:
        raise _ambiguous_channel_400(exc) from exc

    playlists = await admin.list_playlists_for_channel(channel.id)
    return [PlaylistResponse.model_validate(p) for p in playlists]


@router.post(
    "/playlists/{playlist_id}/add",
    status_code=status.HTTP_200_OK,
    summary="Add a video to a YouTube playlist",
)
async def add_video_to_playlist(
    playlist_id: UUID,
    payload: PlaylistAddVideo,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: YouTubeAdminService = Depends(_service),
) -> dict[str, str]:
    """Add a YouTube video to one of the managed playlists."""
    yt_service = await build_youtube_service(settings, db)

    try:
        playlist, channel = await admin.get_playlist_with_channel(playlist_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        await admin.refresh_and_persist_tokens(channel, yt_service)
    except TokenRefreshError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "youtube_token_expired", "reason": str(exc)},
        ) from exc

    try:
        item = await yt_service.add_to_playlist(
            access_token_encrypted=channel.access_token_encrypted or "",
            refresh_token_encrypted=channel.refresh_token_encrypted,
            token_expiry=channel.token_expiry,
            playlist_id=playlist.youtube_playlist_id,
            video_id=payload.video_id,
        )
    except YouTubeTokenExpiredError as exc:
        raise _token_expired_401(exc, channel.id) from exc
    except Exception as exc:
        logger.error(
            "youtube_add_to_playlist_failed",
            playlist_id=str(playlist_id),
            video_id=payload.video_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to add video to playlist: {exc}",
        ) from exc

    await admin.increment_playlist_item_count(playlist)

    return {
        "message": "Video added to playlist",
        "playlist_item_id": item.get("id", ""),
        "video_id": payload.video_id,
        "youtube_playlist_id": playlist.youtube_playlist_id,
    }


@router.delete(
    "/playlists/{playlist_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a YouTube playlist",
)
async def delete_playlist(
    playlist_id: UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: YouTubeAdminService = Depends(_service),
) -> dict[str, str]:
    """Delete a playlist from YouTube and remove it from the local database."""
    yt_service = await build_youtube_service(settings, db)

    try:
        playlist, channel = await admin.get_playlist_with_channel(playlist_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        await admin.refresh_and_persist_tokens(channel, yt_service)
    except TokenRefreshError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "youtube_token_expired", "reason": str(exc)},
        ) from exc

    try:
        await yt_service.delete_playlist(
            access_token_encrypted=channel.access_token_encrypted or "",
            refresh_token_encrypted=channel.refresh_token_encrypted,
            token_expiry=channel.token_expiry,
            playlist_id=playlist.youtube_playlist_id,
        )
    except YouTubeTokenExpiredError as exc:
        raise _token_expired_401(exc, channel.id) from exc
    except Exception as exc:
        logger.error(
            "youtube_delete_playlist_failed",
            playlist_id=str(playlist_id),
            youtube_playlist_id=playlist.youtube_playlist_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to delete playlist on YouTube: {exc}",
        ) from exc

    youtube_playlist_id = playlist.youtube_playlist_id
    title = playlist.title
    await admin.delete_playlist_row(playlist_id)
    logger.info(
        "youtube_playlist_deleted_local",
        playlist_db_id=str(playlist_id),
        youtube_playlist_id=youtube_playlist_id,
    )
    return {
        "message": f"Playlist '{title}' deleted",
        "youtube_playlist_id": youtube_playlist_id,
    }


# ── Analytics ────────────────────────────────────────────────────────────


@router.get(
    "/analytics",
    response_model=list[VideoStatsResponse],
    status_code=status.HTTP_200_OK,
    summary="Fetch YouTube video statistics",
)
async def get_video_analytics(
    video_ids: str = Query(..., description="Comma-separated list of YouTube video IDs (max 50)"),
    channel_id: UUID | None = Query(
        None,
        description="Channel whose OAuth token is used to query the Data API. "
        "Required when multiple channels are connected.",
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: YouTubeAdminService = Depends(_service),
) -> list[VideoStatsResponse]:
    """Return view, like, and comment counts for a list of YouTube video IDs."""
    if settings.demo_mode:
        import random as _r

        ids = [v.strip() for v in video_ids.split(",") if v.strip()]
        rng = _r.Random(sum(ord(c) for c in (ids[0] if ids else "demo")))
        return [
            VideoStatsResponse(
                video_id=vid,
                title=f"Demo video {vid[:8]}",
                views=rng.randint(1_200, 58_000),
                likes=rng.randint(40, 2_200),
                comments=rng.randint(0, 180),
                published_at=None,
            )
            for vid in ids[:50]
        ]

    yt_service = await build_youtube_service(settings, db)
    try:
        channel = await admin.resolve_channel(channel_id)
    except NoChannelConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No YouTube channel connected. Please authorize first.",
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"YouTube channel {channel_id} not found",
        ) from exc
    except MultipleChannelsAmbiguousError as exc:
        raise _ambiguous_channel_400(exc) from exc

    ids = [v.strip() for v in video_ids.split(",") if v.strip()]
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="video_ids must contain at least one video ID",
        )
    # Hard upper bound only — YouTube's 50-IDs-per-call cap is enforced
    # inside ``yt_service.get_video_stats`` by chunking + merging, so
    # callers can hand us thousands of IDs without worrying about it.
    if len(ids) > 5000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="video_ids must contain at most 5000 IDs per request",
        )

    # Split refresh from fetch so a dead/revoked grant maps to an
    # actionable 401 "reconnect this channel" (mirroring the channel-
    # analytics endpoint + the upload/playlist routes) instead of a
    # generic 502. The explicit refresh surfaces TokenRefreshError; the
    # fetch can surface YouTubeTokenExpiredError when google-auth auto-
    # refreshes a still-locally-valid-but-revoked token inside the call.
    try:
        await admin.refresh_and_persist_tokens(channel, yt_service, commit=True)
    except TokenRefreshError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "youtube_token_expired",
                "reason": str(exc),
                "channel_id": str(channel.id),
                "hint": "Reconnect this channel via Settings → YouTube.",
            },
        ) from exc

    try:
        stats = await yt_service.get_video_stats(
            access_token_encrypted=channel.access_token_encrypted or "",
            refresh_token_encrypted=channel.refresh_token_encrypted,
            token_expiry=channel.token_expiry,
            video_ids=ids,
        )
    except YouTubeTokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "youtube_token_expired",
                "reason": str(exc),
                "channel_id": str(channel.id),
                "hint": "Reconnect this channel via Settings → YouTube.",
            },
        ) from exc
    except Exception as exc:
        logger.error(
            "youtube_analytics_failed",
            channel_id=str(channel.id),
            video_count=len(ids),
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "youtube_analytics_failed",
                "reason": str(exc)[:240],
                "channel_id": str(channel.id),
                "hint": (
                    "If this says 'invalid_grant' or 'unauthorized', the channel's "
                    "OAuth token expired — disconnect and reconnect the channel "
                    "in Settings. If it says 'quotaExceeded', YouTube's daily "
                    "quota is exhausted — retry tomorrow."
                ),
            },
        ) from exc

    return [VideoStatsResponse(**s) for s in stats]


@router.get(
    "/analytics/channel",
    status_code=status.HTTP_200_OK,
    summary="Pull channel-level analytics (views, watch time, retention, CTR)",
)
async def get_channel_analytics(
    channel_id: UUID | None = Query(
        None,
        description="Channel whose OAuth token is used. "
        "Required when multiple channels are connected.",
    ),
    days: int = Query(28, ge=1, le=365, description="Window length in days (1-365)."),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: YouTubeAdminService = Depends(_service),
) -> dict[str, Any]:
    """Fetch aggregate + daily KPIs for the window."""
    if settings.demo_mode:
        import random as _r
        from datetime import UTC as _UTC
        from datetime import date as _date
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        rng = _r.Random(days)
        end = _date.today()
        start = end - _td(days=days - 1)
        daily = []
        for i in range(days):
            d = start + _td(days=i)
            base = 800 + rng.randint(-120, 200) + (i * 18)
            daily.append(
                {
                    "day": d.isoformat(),
                    "views": max(100, base),
                    "minutes_watched": max(80, int(base * rng.uniform(0.8, 1.6))),
                }
            )
        totals = {
            "views": sum(cast(int, d["views"]) for d in daily),
            "minutes_watched": sum(cast(int, d["minutes_watched"]) for d in daily),
            "subscribers_gained": rng.randint(40, 220),
            "likes": rng.randint(600, 2400),
            "comments": rng.randint(30, 180),
            "shares": rng.randint(20, 160),
        }
        return {
            "window_days": days,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "totals": totals,
            "daily": daily,
            "fetched_at": _dt.now(tz=_UTC).isoformat(),
        }

    yt_service = await build_youtube_service(settings, db)
    try:
        channel = await admin.resolve_channel(channel_id)
    except NoChannelConnectedError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No YouTube channel connected. Please authorize first.",
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"YouTube channel {channel_id} not found"
        ) from exc
    except MultipleChannelsAmbiguousError as exc:
        raise _ambiguous_channel_400(exc) from exc

    try:
        await admin.refresh_and_persist_tokens(channel, yt_service, commit=True)
    except TokenRefreshError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "youtube_token_expired", "reason": str(exc)},
        ) from exc

    try:
        result = await yt_service.get_channel_analytics(
            access_token_encrypted=channel.access_token_encrypted or "",
            refresh_token_encrypted=channel.refresh_token_encrypted,
            token_expiry=channel.token_expiry,
            days=days,
        )
    except AnalyticsNotAuthorized as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "analytics_scope_missing",
                "hint": str(exc),
                "channel_id": str(channel.id),
            },
        ) from exc
    except YouTubeTokenExpiredError as exc:
        # Auto-refresh inside the analytics call hit a dead grant — map to
        # the same 401 reconnect signal as the explicit-refresh step above.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "youtube_token_expired",
                "reason": str(exc),
                "channel_id": str(channel.id),
                "hint": "Reconnect this channel via Settings → YouTube.",
            },
        ) from exc
    except Exception as exc:
        logger.error("youtube_channel_analytics_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch channel analytics: {exc}",
        ) from exc

    return {"channel_id": str(channel.id), **result}


@router.get(
    "/channels/{channel_id}/scopes",
    summary="Inspect what OAuth scopes the channel's token actually has",
)
async def get_channel_scopes(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    admin: YouTubeAdminService = Depends(_service),
) -> dict[str, Any]:
    """Returns the OAuth scopes the stored access token actually carries.

    Definitive answer to "did the user grant analytics scope" — hits
    Google's tokeninfo endpoint instead of inferring from a 403 on the
    Analytics API.
    """
    yt_service = await build_youtube_service(settings, db)
    try:
        channel = await admin.resolve_channel(channel_id)
    except NoChannelConnectedError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No YouTube channel connected. Please authorize first.",
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"YouTube channel {channel_id} not found"
        ) from exc

    try:
        await admin.refresh_and_persist_tokens(channel, yt_service, commit=True)
    except TokenRefreshError:
        # Continue with stale token — we'll surface "introspection failed"
        # below instead of bailing here.
        pass

    if not channel.access_token_encrypted:
        return {
            "channel_id": str(channel.id),
            "scopes": [],
            "has_analytics_scope": False,
            "has_upload_scope": False,
            "expected_scopes": YouTubeService.SCOPES,
            "token_introspection_failed": True,
            "hint": "No access token stored — channel must be reconnected.",
        }

    try:
        access_token = settings.decrypt(channel.access_token_encrypted)
    except Exception as exc:
        logger.warning("youtube.scope_introspect.decrypt_failed", error=str(exc)[:120])
        return {
            "channel_id": str(channel.id),
            "scopes": [],
            "has_analytics_scope": False,
            "has_upload_scope": False,
            "expected_scopes": YouTubeService.SCOPES,
            "token_introspection_failed": True,
            "hint": "Stored access token couldn't be decrypted.",
        }

    scopes = await fetch_token_scopes(access_token)
    return {
        "channel_id": str(channel.id),
        "scopes": scopes,
        "has_analytics_scope": "https://www.googleapis.com/auth/yt-analytics.readonly" in scopes,
        "has_upload_scope": "https://www.googleapis.com/auth/youtube.upload" in scopes,
        "expected_scopes": YouTubeService.SCOPES,
        "token_introspection_failed": not scopes,
        "hint": (
            "Reconnect required: your token is missing the analytics scope."
            if scopes and "https://www.googleapis.com/auth/yt-analytics.readonly" not in scopes
            else None
        ),
    }
