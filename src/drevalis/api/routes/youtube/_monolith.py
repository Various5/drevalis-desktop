"""YouTube integration API routes — OAuth, upload, playlists, analytics.

Layering: this router calls ``YouTubeAdminService`` (route
orchestration) + the existing ``YouTubeService`` (upstream API client)
only. No repository imports here (audit F-A-01).

The module-level ``build_youtube_service`` re-export is kept because
the audiobooks route imports it directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_redis, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
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


@router.get(
    "/callback",
    response_model=YouTubeChannelResponse,
    status_code=status.HTTP_200_OK,
    summary="Handle YouTube OAuth callback",
)
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str | None = Query(None, description="OAuth state parameter"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
    admin: YouTubeAdminService = Depends(_service),
) -> YouTubeChannelResponse:
    """Exchange the OAuth authorization code for tokens, store channel info."""
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth state parameter.",
        )
    state_key = f"youtube_oauth_state:{state}"
    try:
        stored = await redis.getdel(state_key)
    except Exception as exc:
        logger.error("youtube_oauth_state_lookup_failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth state store unavailable.",
        ) from exc
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state; retry the connect flow.",
        )

    yt_service = await build_youtube_service(settings, db)
    try:
        channel_info = await yt_service.handle_callback(code, state=state)
    except Exception as exc:
        logger.error("youtube_oauth_callback_failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth callback failed. Check server logs for details.",
        ) from exc

    try:
        channel = await admin.upsert_oauth_channel(channel_info)
    except ChannelCapExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "channel_cap_exceeded",
                "tier": exc.tier,
                "limit": exc.limit,
                "hint": "Upgrade tier to connect more YouTube channels.",
            },
        ) from exc
    return YouTubeChannelResponse.model_validate(channel)


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

    await yt_service.delete_video(
        channel.access_token_encrypted or "",
        channel.refresh_token_encrypted,
        channel.token_expiry,
        youtube_video_id,
    )
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

    try:
        await admin.refresh_and_persist_tokens(channel, yt_service, commit=True)
        stats = await yt_service.get_video_stats(
            access_token_encrypted=channel.access_token_encrypted or "",
            refresh_token_encrypted=channel.refresh_token_encrypted,
            token_expiry=channel.token_expiry,
            video_ids=ids,
        )
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
