"""arq job: enumerate a connected YouTube channel's existing videos.

Triggered automatically after a successful OAuth callback (so a fresh
connect populates the dashboard immediately) and manually via
``POST /api/v1/youtube/channels/{id}/resync`` when the user wants a
refresh.

Idempotent: each row is upserted by ``(channel_id, youtube_video_id)``.
Re-runs update view/like/comment counts in place and bump
``last_synced_at``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def sync_youtube_channel_videos(
    ctx: dict[str, Any],
    channel_id_str: str,
    max_videos: int = 500,
) -> dict[str, Any]:
    """Pull every video the channel has uploaded, store them in
    ``youtube_channel_videos``.

    Returns ``{"channel_id": str, "synced": int, "shorts": int,
    "longform": int, "error": str | None}`` so callers (the API
    resync endpoint, or the OAuth callback hook) can surface a
    quick summary.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from drevalis.core.config import Settings
    from drevalis.models.youtube_channel import YouTubeChannel, YouTubeChannelVideo
    from drevalis.services.integration_keys import resolve_youtube_credentials
    from drevalis.services.youtube import (
        YouTubeService,
        YouTubeTokenDecryptError,
        YouTubeTokenExpiredError,
    )

    channel_id = UUID(channel_id_str)
    settings = Settings()
    session_factory = ctx["session_factory"]

    log = logger.bind(job="sync_youtube_channel_videos", channel_id=channel_id_str)
    log.info("job_start")

    async with session_factory() as session:
        channel = await session.get(YouTubeChannel, channel_id)
        if channel is None:
            log.warning("channel_not_found")
            return {"channel_id": channel_id_str, "synced": 0, "error": "channel_not_found"}

        yt_client_id, yt_client_secret = await resolve_youtube_credentials(settings, session)
        if not yt_client_id or not yt_client_secret:
            log.warning("youtube_not_configured")
            return {
                "channel_id": channel_id_str,
                "synced": 0,
                "error": "youtube_not_configured",
            }

        svc = YouTubeService(
            client_id=yt_client_id,
            client_secret=yt_client_secret,
            redirect_uri=settings.youtube_redirect_uri,
            encryption_key=settings.encryption_key,
            encryption_keys=settings.get_encryption_keys(),
        )

        try:
            videos = await svc.list_channel_videos(
                access_token_encrypted=channel.access_token_encrypted or "",
                refresh_token_encrypted=channel.refresh_token_encrypted,
                token_expiry=channel.token_expiry,
                max_videos=max_videos,
                # Pin to THIS channel's YouTube ID, not the OAuth token's
                # primary channel. Required for brand-account sub-channels
                # — see service docstring + alpha.42 fix history.
                youtube_channel_id=channel.channel_id,
            )
        except YouTubeTokenDecryptError:
            log.warning("youtube_tokens_undecryptable")
            return {
                "channel_id": channel_id_str,
                "synced": 0,
                "error": "tokens_undecryptable",
            }
        except YouTubeTokenExpiredError:
            log.warning("youtube_token_expired")
            return {
                "channel_id": channel_id_str,
                "synced": 0,
                "error": "token_expired",
            }
        except Exception as exc:
            log.error("youtube_sync_failed", error_type=type(exc).__name__, exc_info=True)
            return {
                "channel_id": channel_id_str,
                "synced": 0,
                "error": f"sync_failed: {type(exc).__name__}",
            }

        # Upsert each video. ``sqlite_insert + on_conflict_do_update`` is
        # SQLite-specific but the desktop port is SQLite-only, so this
        # is the simplest path. For the multi-DB future, swap to a
        # query-then-update or pull in postgres-compatible upsert.
        now = datetime.now(tz=UTC)
        synced = 0
        shorts = 0
        longform = 0
        for v in videos:
            published = v.get("published_at")
            if isinstance(published, str):
                try:
                    published = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except ValueError:
                    published = None
            stmt = sqlite_insert(YouTubeChannelVideo).values(
                channel_id=channel.id,
                youtube_video_id=v["video_id"],
                title=v.get("title") or "",
                description=v.get("description"),
                thumbnail_url=v.get("thumbnail_url"),
                published_at=published,
                duration_seconds=v.get("duration_seconds"),
                is_short=bool(v.get("is_short")),
                privacy_status=v.get("privacy_status"),
                view_count=int(v.get("view_count") or 0),
                like_count=int(v.get("like_count") or 0),
                comment_count=int(v.get("comment_count") or 0),
                last_synced_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["channel_id", "youtube_video_id"],
                set_={
                    "title": stmt.excluded.title,
                    "description": stmt.excluded.description,
                    "thumbnail_url": stmt.excluded.thumbnail_url,
                    "published_at": stmt.excluded.published_at,
                    "duration_seconds": stmt.excluded.duration_seconds,
                    "is_short": stmt.excluded.is_short,
                    "privacy_status": stmt.excluded.privacy_status,
                    "view_count": stmt.excluded.view_count,
                    "like_count": stmt.excluded.like_count,
                    "comment_count": stmt.excluded.comment_count,
                    "last_synced_at": stmt.excluded.last_synced_at,
                },
            )
            await session.execute(stmt)
            synced += 1
            if v.get("is_short"):
                shorts += 1
            else:
                longform += 1
        # ── Reconciliation pass: episode ↔ youtube_video_id auto-link ────
        # For every channel video whose youtube_video_id matches a
        # YouTubeUpload row Drevalis owns, make sure the linked Episode's
        # ``metadata_["youtube_video_url"]`` is populated. This heals
        # episodes that were uploaded before this reconciliation existed
        # (or whose URL got lost in a manual cleanup) without needing
        # the user to click anything.
        from sqlalchemy import select as _select

        from drevalis.models.episode import Episode
        from drevalis.models.youtube_channel import YouTubeUpload

        upload_rows = (
            await session.execute(
                _select(YouTubeUpload.episode_id, YouTubeUpload.youtube_video_id)
                .where(YouTubeUpload.channel_id == channel.id)
                .where(YouTubeUpload.upload_status == "done")
                .where(YouTubeUpload.youtube_video_id.is_not(None))
            )
        ).all()
        reconciled = 0
        for ep_id, vid in upload_rows:
            if not (ep_id and vid):
                continue
            ep = await session.get(Episode, ep_id)
            if ep is None:
                continue
            url = f"https://www.youtube.com/watch?v={vid}"
            md = dict(ep.metadata_ or {})
            if md.get("youtube_video_url") != url:
                md["youtube_video_url"] = url
                md["youtube_video_id"] = vid
                ep.metadata_ = md
                reconciled += 1
        await session.commit()

    log.info(
        "job_complete",
        synced=synced,
        shorts=shorts,
        longform=longform,
        episodes_reconciled=reconciled,
    )

    # Persist a per-channel sync marker in Redis so the API can
    # distinguish "channel was synced but has 0 videos" from
    # "sync never ran". Without this, an empty channel and an
    # unsynced channel look identical to the frontend because
    # ``last_synced_at`` derived from video rows is null in both
    # cases. 30-day TTL is plenty — the worker re-fires on every
    # OAuth callback and manual resync, so the marker refreshes
    # often.
    if ctx.get("redis") is not None:
        try:
            await ctx["redis"].setex(
                f"youtube:last_sync:{channel_id_str}",
                30 * 24 * 60 * 60,
                f"{now.isoformat()}|synced={synced}|shorts={shorts}|longform={longform}",
            )
        except Exception:
            log.debug("ws_sync_marker_failed", exc_info=True)

    # Broadcast a "channel synced" WS event so the frontend can refresh
    # its YouTube section without polling. Best-effort; failure here is
    # cosmetic, the data is already in the DB.
    if ctx.get("redis") is not None:
        import json as _json

        try:
            await ctx["redis"].publish(
                f"youtube:channel:{channel_id_str}",
                _json.dumps(
                    {
                        "event": "channel_videos_synced",
                        "channel_id": channel_id_str,
                        "synced": synced,
                        "shorts": shorts,
                        "longform": longform,
                    }
                ),
            )
        except Exception:
            log.debug("ws_broadcast_failed", exc_info=True)

    return {
        "channel_id": channel_id_str,
        "synced": synced,
        "shorts": shorts,
        "longform": longform,
        "error": None,
    }
