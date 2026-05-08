"""Scheduled-post arq job function.

Jobs
----
- ``publish_scheduled_posts`` -- periodic cron job that publishes due posts.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def publish_scheduled_posts(ctx: dict[str, Any]) -> dict[str, Any]:
    """Periodic job: check for scheduled posts that are due and publish them.

    Runs every 5 minutes via arq cron. YouTube posts are uploaded inline using
    the channel's OAuth tokens; non-YouTube platforms (TikTok / Instagram /
    Facebook / X) are handed off as ``SocialUpload`` rows for the social cron
    to publish on its next tick.

    Guarded by :func:`cron_lock` — in a multi-worker deployment, only one
    instance actually runs each 5-minute tick. Without this, two workers
    firing at the same timestamp would race YouTube uploads and could
    publish the same scheduled post twice.
    """
    import asyncio as _asyncio
    from datetime import datetime
    from pathlib import Path

    from drevalis.workers.cron_lock import cron_lock

    async with cron_lock(ctx, "publish_scheduled_posts", ttl_s=280) as owner:
        if not owner:
            return {"status": "skipped_not_cron_owner"}
        return await _publish_scheduled_posts_locked(ctx, _asyncio, datetime, Path)


async def _publish_scheduled_posts_locked(
    ctx: dict[str, Any],
    _asyncio: Any,
    datetime: Any,
    Path: Any,
) -> dict[str, Any]:

    from drevalis.core.config import Settings
    from drevalis.repositories.episode import EpisodeRepository
    from drevalis.repositories.media_asset import MediaAssetRepository
    from drevalis.repositories.scheduled_post import ScheduledPostRepository
    from drevalis.repositories.series import SeriesRepository
    from drevalis.repositories.youtube import (
        YouTubeChannelRepository,
        YouTubeUploadRepository,
    )
    from drevalis.services.youtube import YouTubeService

    log = logger.bind(job="publish_scheduled_posts")
    log.info("job_start")

    settings = Settings()
    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        repo = ScheduledPostRepository(session)
        pending = await repo.get_pending(before=datetime.now(UTC))

        published = 0
        failed = 0

        for post in pending:
            try:
                await repo.update(post.id, status="publishing")
                await session.commit()

                if post.platform == "youtube":
                    # ── Actual YouTube upload ────────────────────────
                    # Resolve creds via the shared helper that checks
                    # both env (``YOUTUBE_CLIENT_ID`` / ``_SECRET``)
                    # AND the api_keys DB store. Pre-v0.28.1 this
                    # path read only from ``settings``, so creds saved
                    # via Settings → API Keys were ignored at publish
                    # time and every upload failed with "not configured"
                    # even though the integration page said the keys
                    # were stored.
                    from drevalis.services.integration_keys import (
                        resolve_youtube_credentials,
                    )

                    yt_client_id, yt_client_secret = await resolve_youtube_credentials(
                        settings, session
                    )
                    if not yt_client_id or not yt_client_secret:
                        raise RuntimeError(
                            "YouTube not configured (missing client_id/secret). "
                            "Set YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET in .env, "
                            "or save them via Settings → API Keys."
                        )

                    svc = YouTubeService(
                        client_id=yt_client_id,
                        client_secret=yt_client_secret,
                        redirect_uri=settings.youtube_redirect_uri,
                        encryption_key=settings.encryption_key,
                        encryption_keys=settings.get_encryption_keys(),
                    )

                    # Resolve YouTube channel: per-post override first, then
                    # the series' assigned channel. No "active channel"
                    # fallback — multi-channel contract requires the
                    # operator to declare the target explicitly so uploads
                    # never silently land on the wrong channel.
                    ch_repo = YouTubeChannelRepository(session)
                    channel = None
                    if post.youtube_channel_id:
                        channel = await ch_repo.get_by_id(post.youtube_channel_id)
                    if channel is None:
                        ep_repo = EpisodeRepository(session)
                        episode = await ep_repo.get_by_id(post.content_id)
                        if episode:
                            series = await SeriesRepository(session).get_by_id(episode.series_id)
                            series_channel_id = getattr(series, "youtube_channel_id", None)
                            if series and series_channel_id:
                                channel = await ch_repo.get_by_id(series_channel_id)
                    if channel is None:
                        raise RuntimeError(
                            "No YouTube channel assigned: set youtube_channel_id on "
                            "the scheduled post or on the episode's series."
                        )

                    # Refresh tokens once up-front; the per-attempt loop below
                    # also refreshes before each retry so a 401 mid-upload
                    # doesn't cascade through all attempts.
                    updated = await svc.refresh_tokens_if_needed(
                        channel.access_token_encrypted or "",
                        channel.refresh_token_encrypted,
                        channel.token_expiry,
                    )
                    if updated:
                        for k, v in updated.items():
                            setattr(channel, k, v)
                        await session.flush()

                    # Skip if this episode is already published on this
                    # channel. The cron can fire late (5 min granularity)
                    # and overlap with a manual upload, or a previous tick
                    # may have succeeded server-side after a transient
                    # local error — re-uploading would duplicate the
                    # video on YouTube.
                    upload_repo_pre = YouTubeUploadRepository(session)
                    existing = await upload_repo_pre.get_existing_done(post.content_id, channel.id)
                    if existing is not None and post.content_type == "episode":
                        log.info(
                            "scheduled_post_skip_duplicate",
                            episode_id=str(post.content_id),
                            channel_id=str(channel.id),
                            existing_upload_id=str(existing.id),
                            existing_video_id=existing.youtube_video_id,
                        )
                        await repo.update(
                            post.id,
                            status="published",
                            published_at=datetime.now(UTC),
                            remote_id=existing.youtube_video_id,
                            remote_url=existing.youtube_url,
                            error_message=(
                                "Episode was already published on this channel — "
                                "scheduled post reconciled to existing upload."
                            ),
                        )
                        continue

                    # Find video file
                    asset_repo = MediaAssetRepository(session)
                    video_assets = await asset_repo.get_by_episode_and_type(
                        post.content_id, "video"
                    )
                    if not video_assets:
                        raise RuntimeError(f"No video asset for episode {post.content_id}")
                    video_path = Path(settings.storage_base_path) / video_assets[-1].file_path
                    if not video_path.exists():
                        raise RuntimeError(f"Video file not found: {video_path}")

                    # Find thumbnail
                    thumb_path = None
                    thumb_assets = await asset_repo.get_by_episode_and_type(
                        post.content_id, "thumbnail"
                    )
                    if thumb_assets:
                        candidate = Path(settings.storage_base_path) / thumb_assets[-1].file_path
                        if candidate.exists():
                            thumb_path = candidate

                    # Upload with retry. Refresh tokens on each attempt —
                    # a multi-minute upload can exhaust the 1h access token
                    # between attempts #2 and #3, so re-using the original
                    # refreshed token would 401 on subsequent retries.
                    result = None
                    for attempt in range(3):
                        try:
                            refreshed = await svc.refresh_tokens_if_needed(
                                channel.access_token_encrypted or "",
                                channel.refresh_token_encrypted,
                                channel.token_expiry,
                            )
                            if refreshed:
                                for k, v in refreshed.items():
                                    setattr(channel, k, v)
                                await session.flush()
                                await session.commit()

                            result = await svc.upload_video(
                                access_token_encrypted=channel.access_token_encrypted or "",
                                refresh_token_encrypted=channel.refresh_token_encrypted,
                                token_expiry=channel.token_expiry,
                                video_path=video_path,
                                title=post.title[:100],
                                description=post.description or "",
                                tags=post.tags.split(",") if post.tags else [],
                                privacy_status=post.privacy or "public",
                                thumbnail_path=thumb_path,
                            )
                            break
                        except Exception as upload_exc:
                            if attempt < 2:
                                log.warning(
                                    "upload_retry", attempt=attempt + 1, error=str(upload_exc)[:100]
                                )
                                await _asyncio.sleep(10 * (attempt + 1))
                            else:
                                raise

                    await repo.update(
                        post.id,
                        status="published",
                        published_at=datetime.now(UTC),
                        remote_id=result["video_id"] if result else None,
                        remote_url=result["url"] if result else None,
                    )

                    # Also create a youtube_uploads record so the Uploads tab
                    # reflects scheduled uploads alongside manual ones.
                    if result and post.content_type == "episode":
                        upload_repo = YouTubeUploadRepository(session)
                        await upload_repo.create(
                            episode_id=post.content_id,
                            channel_id=channel.id,
                            youtube_video_id=result["video_id"],
                            youtube_url=result["url"],
                            title=post.title[:100],
                            description=post.description or "",
                            privacy_status=post.privacy or "public",
                            upload_status="done",
                        )

                    await session.commit()
                    published += 1
                    log.info(
                        "post_published_youtube",
                        post_id=str(post.id),
                        video_id=result.get("video_id") if result else None,
                    )

                    # Broadcast so the frontend refreshes episode list/
                    # detail without a manual F5 - previously a scheduled
                    # publish happening at 2am left the UI showing stale
                    # status indefinitely.
                    if post.content_type == "episode" and ctx.get("redis") is not None:
                        import json as _json

                        try:
                            await ctx["redis"].publish(
                                f"progress:{post.content_id}",
                                _json.dumps(
                                    {
                                        "episode_id": str(post.content_id),
                                        "step": "publish",
                                        "status": "published",
                                        "progress_pct": 100,
                                        "message": "Scheduled upload complete",
                                        "detail": {
                                            "remote_url": result["url"] if result else None,
                                            "video_id": result.get("video_id") if result else None,
                                        },
                                    }
                                ),
                            )
                        except Exception:
                            log.debug("progress_broadcast_failed", exc_info=True)
                elif post.platform in ("tiktok", "instagram", "facebook", "x"):
                    # ── Hand off to the social-uploads pipeline ──────────
                    # We don't duplicate the per-platform uploaders here.
                    # Instead, create a ``SocialUpload`` row pointing at
                    # the same episode + platform; the existing
                    # ``publish_pending_social_uploads`` cron picks it up
                    # on its next 5-min tick and runs the real upload.
                    # The scheduled-post status flips to ``published``
                    # because the *scheduling* step is done — the actual
                    # upload's status lives on the SocialUpload row, which
                    # the operator can monitor in the Social tab.
                    from sqlalchemy import select as _select

                    from drevalis.models.social_platform import (
                        SocialPlatform,
                        SocialUpload,
                    )

                    # Resolve the active platform connection. A scheduled
                    # post for a platform with no connection (or the
                    # operator disconnected after scheduling) fails fast
                    # rather than silently dropping.
                    plat_q = await session.execute(
                        _select(SocialPlatform)
                        .where(SocialPlatform.platform == post.platform)
                        .where(SocialPlatform.is_active.is_(True))
                        .limit(1)
                    )
                    platform_row = plat_q.scalar_one_or_none()
                    if platform_row is None:
                        raise RuntimeError(
                            f"No active {post.platform} connection. "
                            f"Reconnect via Settings → Social → {post.platform.title()}."
                        )

                    if post.content_type != "episode":
                        raise RuntimeError(
                            f"Only episode content is supported for {post.platform} "
                            f"scheduled posts (got '{post.content_type}')."
                        )

                    # Sanity-check the video asset exists; the social
                    # cron will check again before uploading, but
                    # surfacing a missing-video failure here gives the
                    # operator the failure on the ScheduledPost row
                    # instead of a delayed SocialUpload-row failure.
                    asset_repo = MediaAssetRepository(session)
                    video_assets = await asset_repo.get_by_episode_and_type(
                        post.content_id, "video"
                    )
                    if not video_assets:
                        raise RuntimeError(f"No video asset for episode {post.content_id}")

                    upload_row = SocialUpload(
                        platform_id=platform_row.id,
                        episode_id=post.content_id,
                        content_type="episode",
                        title=post.title[:280],
                        description=post.description or "",
                        hashtags=getattr(post, "tags", None) or "",
                        upload_status="pending",
                    )
                    session.add(upload_row)
                    await session.flush()

                    await repo.update(
                        post.id,
                        status="published",
                        published_at=datetime.now(UTC),
                        # Stash the SocialUpload id so the UI / operator
                        # can correlate this scheduled-post row with the
                        # actual upload attempt living on the social tab.
                        remote_id=f"social_upload:{upload_row.id}",
                    )
                    await session.commit()
                    published += 1
                    log.info(
                        "post_published_social",
                        post_id=str(post.id),
                        platform=post.platform,
                        social_upload_id=str(upload_row.id),
                    )

                    if ctx.get("redis") is not None:
                        import json as _json

                        try:
                            await ctx["redis"].publish(
                                f"progress:{post.content_id}",
                                _json.dumps(
                                    {
                                        "episode_id": str(post.content_id),
                                        "step": "publish",
                                        "status": "queued",
                                        "progress_pct": 50,
                                        "message": (
                                            f"Queued {post.platform} upload — "
                                            "the social cron will publish on "
                                            "its next 5-min tick."
                                        ),
                                        "detail": {
                                            "platform": post.platform,
                                            "social_upload_id": str(upload_row.id),
                                        },
                                    }
                                ),
                            )
                        except Exception:
                            log.debug("progress_broadcast_failed", exc_info=True)
                else:
                    # Truly unknown platform — mark failed.
                    await repo.update(
                        post.id,
                        status="failed",
                        error_message=(
                            f"Unknown platform '{post.platform}'. "
                            "Supported: youtube, tiktok, instagram, facebook, x."
                        ),
                    )
                    await session.commit()
                    failed += 1

            except Exception as exc:
                log.error("post_publish_failed", post_id=str(post.id), error=str(exc)[:200])
                try:
                    await repo.update(
                        post.id,
                        status="failed",
                        error_message=str(exc)[:500],
                    )
                    await session.commit()
                except Exception as nested:
                    # Failure-recording itself failed. Don't silently
                    # swallow — at worst the row stays in 'publishing'
                    # but the operator needs to see the DB error.
                    log.exception(
                        "post_fail_record_failed",
                        post_id=str(post.id),
                        nested_error=str(nested)[:200],
                    )
                failed += 1

    log.info("job_complete", published=published, failed=failed, pending_checked=len(pending))
    return {"published": published, "failed": failed, "pending_checked": len(pending)}
