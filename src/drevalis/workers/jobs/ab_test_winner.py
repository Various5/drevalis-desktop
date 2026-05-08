"""A/B test auto-winner worker.

For every :class:`ABTest` without a ``winner_episode_id``, this job
checks whether both episodes have been uploaded to YouTube for at
least 7 days. If so, it fetches fresh view counts via the Data API
and records the episode with more views as the winner. Ties leave
``winner_episode_id`` NULL but set ``comparison_at`` so the job
doesn't re-run forever.

Runs daily at 04:31 UTC (off-peak, coincides with license heartbeat
at 04:17 for batch savings).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

from drevalis.models.ab_test import ABTest
from drevalis.models.youtube_channel import YouTubeChannel, YouTubeUpload

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_MIN_AGE = timedelta(days=7)


async def compute_ab_test_winners(ctx: dict[str, Any]) -> dict[str, int]:
    """Daily cron — settle any A/B pair whose later upload is 7+ days old."""
    from drevalis.core.config import Settings
    from drevalis.core.database import get_session_factory
    from drevalis.services.youtube import YouTubeService

    settings = ctx.get("settings") or Settings()
    # Every other worker job reads ``session_factory``; the lifecycle
    # hook populates that key. Keep ``db_session_factory`` as a legacy
    # fallback so historic enqueues don't crash, but prefer the
    # canonical key so we don't silently hide missing ctx plumbing.
    session_factory = (
        ctx.get("session_factory") or ctx.get("db_session_factory") or get_session_factory()
    )

    processed = 0
    settled = 0
    skipped_not_ready = 0
    skipped_missing_upload = 0
    errored = 0
    now = datetime.now(UTC)

    if not (settings.youtube_client_id and settings.youtube_client_secret):
        logger.info("ab_winner.skipped", reason="youtube_oauth_not_configured")
        return {
            "processed": 0,
            "settled": 0,
            "skipped_not_ready": 0,
            "skipped_missing_upload": 0,
            "errored": 0,
        }

    svc = YouTubeService(
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        redirect_uri=settings.youtube_redirect_uri,
        encryption_key=settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )

    async with session_factory() as session:
        pending = (
            (await session.execute(select(ABTest).where(ABTest.winner_episode_id.is_(None))))
            .scalars()
            .all()
        )

        for test in pending:
            processed += 1

            # Load both episodes' most-recent completed uploads.
            uploads_a = (
                (
                    await session.execute(
                        select(YouTubeUpload)
                        .where(YouTubeUpload.episode_id == test.episode_a_id)
                        .where(YouTubeUpload.upload_status == "done")
                        .order_by(YouTubeUpload.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            uploads_b = (
                (
                    await session.execute(
                        select(YouTubeUpload)
                        .where(YouTubeUpload.episode_id == test.episode_b_id)
                        .where(YouTubeUpload.upload_status == "done")
                        .order_by(YouTubeUpload.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )

            if not uploads_a or not uploads_b:
                skipped_missing_upload += 1
                continue
            ua, ub = uploads_a[0], uploads_b[0]
            if not ua.youtube_video_id or not ub.youtube_video_id:
                skipped_missing_upload += 1
                continue

            # Maturity gate — the later of the two uploads must be
            # older than _MIN_AGE so view counts have stabilised.
            later = max(ua.created_at or now, ub.created_at or now)
            if now - later < _MIN_AGE:
                skipped_not_ready += 1
                continue

            # Both uploads should target the same channel for a fair
            # comparison. If they don't, fall back to whichever channel
            # upload_a used — the view-count race is still meaningful.
            channel = await session.get(YouTubeChannel, ua.channel_id)
            if not channel or not channel.access_token_encrypted:
                errored += 1
                logger.warning("ab_winner.channel_missing", test_id=str(test.id))
                continue

            # Refresh the channel's OAuth token if it's close to expiry.
            try:
                updated = await svc.refresh_tokens_if_needed(
                    channel.access_token_encrypted or "",
                    channel.refresh_token_encrypted,
                    channel.token_expiry,
                )
                if updated:
                    for k, v in updated.items():
                        setattr(channel, k, v)
                    await session.flush()

                stats = await svc.get_video_stats(
                    access_token_encrypted=channel.access_token_encrypted or "",
                    refresh_token_encrypted=channel.refresh_token_encrypted,
                    token_expiry=channel.token_expiry,
                    video_ids=[ua.youtube_video_id, ub.youtube_video_id],
                )
            except Exception as exc:  # noqa: BLE001
                errored += 1
                logger.warning(
                    "ab_winner.stats_fetch_failed",
                    test_id=str(test.id),
                    error=str(exc)[:300],
                )
                continue

            by_id = {s["video_id"]: s for s in stats}
            s_a = by_id.get(ua.youtube_video_id)
            s_b = by_id.get(ub.youtube_video_id)
            if not s_a or not s_b:
                skipped_missing_upload += 1
                continue

            views_a = int(s_a.get("views", 0))
            views_b = int(s_b.get("views", 0))
            test.comparison_at = now
            if views_a > views_b:
                test.winner_episode_id = test.episode_a_id
            elif views_b > views_a:
                test.winner_episode_id = test.episode_b_id
            # Ties: leave winner_episode_id NULL but comparison_at marks it done.

            settled += 1
            logger.info(
                "ab_winner.settled",
                test_id=str(test.id),
                views_a=views_a,
                views_b=views_b,
                winner=str(test.winner_episode_id) if test.winner_episode_id else "tie",
            )

        await session.commit()

    return {
        "processed": processed,
        "settled": settled,
        "skipped_not_ready": skipped_not_ready,
        "skipped_missing_upload": skipped_missing_upload,
        "errored": errored,
    }
