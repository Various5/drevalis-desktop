"""ScheduleService — content scheduling + auto-schedule + diagnostics.

Layering: keeps the route file free of repository imports, raw
``select(ScheduledPost)`` queries, and the auto-schedule orchestration
flow (audit F-A-01).

The service owns four repositories (ScheduledPost, Episode, Series,
YouTubeChannel) because auto-schedule is intrinsically cross-resource —
it walks a series, filters its episodes, resolves a channel, and
inserts posts in a single transaction.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.models.scheduled_post import ScheduledPost
from drevalis.repositories.episode import EpisodeRepository
from drevalis.repositories.scheduled_post import ScheduledPostRepository
from drevalis.repositories.series import SeriesRepository
from drevalis.repositories.youtube import YouTubeChannelRepository
from drevalis.schemas.schedule import (
    AutoScheduleRequest,
    ChannelHealth,
    PlannedSlot,
    RetryFailedRequest,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
    UploadDiagnostic,
)
from drevalis.services.auto_schedule import plan_auto_schedule

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _normalize_to_utc(dt: datetime, tz_name: str) -> datetime:
    """Ensure *dt* is a UTC-aware datetime.

    * Naive ``dt`` is treated as local time in *tz_name*.
    * Aware ``dt`` is converted to UTC (no-op when already UTC).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(UTC)


class ScheduleService:
    def __init__(self, db: AsyncSession, app_timezone: str = "UTC") -> None:
        self._db = db
        self._tz = app_timezone
        self._sched = ScheduledPostRepository(db)
        self._episodes = EpisodeRepository(db)
        self._series = SeriesRepository(db)
        self._channels = YouTubeChannelRepository(db)

    # ── Single-post CRUD ─────────────────────────────────────────────────

    async def create(self, payload: ScheduleCreate) -> ScheduledPost:
        kwargs: dict[str, Any] = {
            "content_type": payload.content_type,
            "content_id": payload.content_id,
            "platform": payload.platform,
            "scheduled_at": _normalize_to_utc(payload.scheduled_at, self._tz),
            "title": payload.title,
            "description": payload.description or None,
            "tags": payload.tags or None,
            "privacy": payload.privacy,
        }
        if payload.youtube_channel_id:
            kwargs["youtube_channel_id"] = payload.youtube_channel_id
        post = await self._sched.create(**kwargs)
        await self._db.commit()
        return post

    async def list_filtered(
        self,
        *,
        status_filter: str | None = None,
        platform: str | None = None,
        limit: int = 50,
    ) -> list[ScheduledPost]:
        posts = await self._sched.get_all(limit=limit)
        if status_filter:
            posts = [p for p in posts if p.status == status_filter]
        if platform:
            posts = [p for p in posts if p.platform == platform]
        return list(posts)

    async def get_calendar(self, start_iso: str, end_iso: str) -> dict[str, list[ScheduledPost]]:
        app_tz = ZoneInfo(self._tz)
        start_dt = datetime.fromisoformat(start_iso).replace(tzinfo=app_tz).astimezone(UTC)
        end_dt = (
            datetime.fromisoformat(end_iso)
            .replace(hour=23, minute=59, second=59, tzinfo=app_tz)
            .astimezone(UTC)
        )
        posts = await self._sched.get_calendar(start_dt, end_dt)

        grouped: dict[str, list[ScheduledPost]] = defaultdict(list)
        for p in posts:
            local = p.scheduled_at.astimezone(app_tz)
            grouped[local.strftime("%Y-%m-%d")].append(p)
        return dict(grouped)

    async def update(self, post_id: UUID, payload: ScheduleUpdate) -> ScheduledPost:
        post = await self._sched.get_by_id(post_id)
        if not post:
            raise NotFoundError("ScheduledPost", post_id)

        # Editable states: ``scheduled`` (normal edit/reschedule) and
        # ``failed`` (reschedule = give it another go). ``publishing``
        # is mid-flight, ``published``/``cancelled`` are terminal — those
        # stay locked. Rescheduling a *failed* post is the documented way
        # to retry it at a new time, so we reset it back to ``scheduled``
        # and clear the stale error here. Without this reset the bulk
        # "Reschedule all" on the calendar silently no-ops on failed
        # posts (the old code raised, so 100+ failed posts never moved).
        if post.status in ("publishing", "published", "cancelled"):
            raise ValidationError(f"Cannot update post with status '{post.status}'")

        updates = payload.model_dump(exclude_unset=True)
        if "scheduled_at" in updates and updates["scheduled_at"] is not None:
            updates["scheduled_at"] = _normalize_to_utc(updates["scheduled_at"], self._tz)

        # Rescheduling (or editing) a failed post implies "try again" —
        # flip it back into the publishable queue and drop the error.
        if post.status == "failed":
            updates["status"] = "scheduled"
            updates["error_message"] = None

        updated = await self._sched.update(post_id, **updates)
        await self._db.commit()
        assert updated is not None
        return updated

    async def publish_now(self, post_id: UUID) -> ScheduledPost:
        """Re-arm a failed/missed post to upload on the next worker tick
        **without** moving it to a future slot.

        The publish cron picks up any ``status='scheduled'`` post whose
        ``scheduled_at <= now`` (it runs every 5 minutes). So "publish
        now" is: clamp ``scheduled_at`` to one minute ago, flip status
        back to ``scheduled``, and clear the error. The very next tick
        uploads it — no slot picking, no waiting for a future date.

        This is what the operator wants for a missed day: "just upload
        the thing, I don't care about the schedule anymore." It does NOT
        bypass the worker's duplicate-check or the platform's daily
        upload cap — if the channel is already at its YouTube quota for
        the day the upload will fail again, which is the correct
        behaviour (better than silently dropping it).
        """
        post = await self._sched.get_by_id(post_id)
        if not post:
            raise NotFoundError("ScheduledPost", post_id)
        if post.status in ("publishing", "published", "cancelled"):
            raise ValidationError(
                f"Cannot publish post with status '{post.status}' now"
            )
        one_min_ago = datetime.now(UTC) - timedelta(minutes=1)
        updated = await self._sched.update(
            post_id,
            status="scheduled",
            scheduled_at=one_min_ago,
            error_message=None,
        )
        await self._db.commit()
        assert updated is not None
        logger.info("schedule.publish_now", post_id=str(post_id))
        return updated

    async def delete(self, post_id: UUID) -> None:
        post = await self._sched.get_by_id(post_id)
        if not post:
            raise NotFoundError("ScheduledPost", post_id)
        if post.status == "published":
            raise ValidationError("Cannot delete a published post")
        await self._sched.delete(post_id)
        await self._db.commit()

    # ── Auto-schedule (cross-resource: series + episodes + channel) ───────

    async def auto_schedule_series(
        self,
        series_id: UUID,
        payload: AutoScheduleRequest,
    ) -> tuple[list[PlannedSlot], list[UUID], bool]:
        """Plan + (optionally) persist an auto-schedule for a series.

        Returns ``(planned_slots, skipped_episode_ids, persisted)``.
        """
        series = await self._series.get_by_id(series_id)
        if not series:
            raise NotFoundError("Series", series_id)

        channel_id = payload.youtube_channel_id or getattr(series, "youtube_channel_id", None)
        if channel_id is None:
            raise ValidationError(
                "Series has no YouTube channel assigned and the request did not "
                "supply ``youtube_channel_id``. Set one before auto-scheduling."
            )
        channel = await self._channels.get_by_id(channel_id)
        if channel is None:
            raise NotFoundError("YouTubeChannel", channel_id)

        review_eps = await self._episodes.get_by_series(
            series_id, status_filter="review", limit=500
        )
        if payload.episode_filter == "all_unuploaded":
            exported_eps = await self._episodes.get_by_series(
                series_id, status_filter="exported", limit=500
            )
            candidates = list(review_eps) + list(exported_eps)
        else:
            candidates = list(review_eps)

        skipped: list[UUID] = []
        fresh: list[Any] = []
        for ep in candidates:
            existing = await self._sched.get_by_content("episode", ep.id)
            has_yt_lock = any(
                p.platform == "youtube" and p.status in ("scheduled", "publishing", "published")
                for p in existing
            )
            if has_yt_lock:
                skipped.append(ep.id)
            else:
                fresh.append(ep)

        fresh.sort(key=lambda e: getattr(e, "created_at", datetime.now(UTC)))
        start_at_utc = _normalize_to_utc(payload.start_at, self._tz)
        slots = plan_auto_schedule(
            episodes=fresh,
            start_at_utc=start_at_utc,
            cadence=payload.cadence,
            every_n=payload.every_n,
            upload_days=channel.upload_days,
            upload_time=channel.upload_time,
            timezone=self._tz,
            youtube_channel_id=channel_id,
            privacy=payload.privacy,
            description_template=payload.description_template,
            tags_template=payload.tags_template,
        )

        planned = [
            PlannedSlot(
                episode_id=s.episode_id,
                episode_title=s.title,
                scheduled_at=s.scheduled_at_utc,
                privacy=s.privacy,
                youtube_channel_id=s.youtube_channel_id,
            )
            for s in slots
        ]

        if payload.dry_run:
            return planned, skipped, False

        for slot in slots:
            await self._sched.create(
                content_type="episode",
                content_id=slot.episode_id,
                platform="youtube",
                scheduled_at=slot.scheduled_at_utc,
                title=slot.title,
                description=slot.description or None,
                tags=slot.tags or None,
                privacy=slot.privacy,
                youtube_channel_id=slot.youtube_channel_id,
            )
        await self._db.commit()

        logger.info(
            "auto_schedule.created",
            series_id=str(series_id),
            cadence=payload.cadence,
            scheduled_count=len(slots),
            skipped_count=len(skipped),
        )
        return planned, skipped, True

    # ── Diagnostics ──────────────────────────────────────────────────────

    async def diagnostics(
        self, within_hours: int = 72
    ) -> tuple[list[ChannelHealth], list[UploadDiagnostic], list[UploadDiagnostic], dict[str, int]]:
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=within_hours)

        channels = await self._channels.get_all()

        channel_healths: list[ChannelHealth] = []
        for ch in channels:
            issues: list[str] = []
            has_access = bool(getattr(ch, "access_token_encrypted", None))
            has_refresh = bool(getattr(ch, "refresh_token_encrypted", None))
            expiry = getattr(ch, "token_expiry", None)
            expired = bool(expiry and expiry <= now)
            if not has_access:
                issues.append("No access token stored — channel needs to be reconnected.")
            if expired and not has_refresh:
                issues.append(
                    "Access token expired and no refresh token — operator must reconnect."
                )
            if not getattr(ch, "upload_days", None):
                issues.append("upload_days unset (defaults to every weekday).")
            if not getattr(ch, "upload_time", None):
                issues.append("upload_time unset (defaults to 09:00).")
            channel_healths.append(
                ChannelHealth(
                    channel_id=ch.id,
                    channel_name=getattr(ch, "channel_name", None) or getattr(ch, "name", None),
                    has_access_token=has_access,
                    has_refresh_token=has_refresh,
                    token_expires_at=expiry,
                    token_expired=expired,
                    can_refresh=has_refresh and has_access,
                    upload_days=getattr(ch, "upload_days", None),
                    upload_time=getattr(ch, "upload_time", None),
                    issues=issues,
                )
            )

        failed_stmt = (
            select(ScheduledPost)
            .where(
                ScheduledPost.status == "failed",
                ScheduledPost.scheduled_at >= cutoff,
            )
            .order_by(ScheduledPost.scheduled_at.desc())
            .limit(50)
        )
        failed_rows = list((await self._db.execute(failed_stmt)).scalars().all())

        overdue_stmt = (
            select(ScheduledPost)
            .where(
                ScheduledPost.status == "scheduled",
                ScheduledPost.scheduled_at <= now - timedelta(minutes=10),
            )
            .order_by(ScheduledPost.scheduled_at)
            .limit(50)
        )
        overdue_rows = list((await self._db.execute(overdue_stmt)).scalars().all())

        def _diag(post: ScheduledPost, kind: str) -> UploadDiagnostic:
            issues: list[str] = []
            if kind == "overdue":
                mins_late = int((now - post.scheduled_at).total_seconds() / 60)
                issues.append(
                    f"Scheduled {mins_late} min ago and still 'scheduled' — "
                    "worker may not be running."
                )
            if post.platform == "youtube" and post.youtube_channel_id is None:
                issues.append(
                    "youtube_channel_id is null on this post — falls back to "
                    "series.youtube_channel_id, which can fail at upload time."
                )
            return UploadDiagnostic(
                post_id=post.id,
                status=post.status,
                scheduled_at=post.scheduled_at,
                title=post.title,
                platform=post.platform,
                error_message=post.error_message,
                issues=issues,
            )

        recent_failed = [_diag(p, "failed") for p in failed_rows]
        overdue = [_diag(p, "overdue") for p in overdue_rows]
        summary: dict[str, int] = {
            "channel_count": len(channel_healths),
            "channels_with_issues": sum(1 for c in channel_healths if c.issues),
            "channels_expired_no_refresh": sum(
                1 for c in channel_healths if c.token_expired and not c.can_refresh
            ),
            "recent_failed_count": len(failed_rows),
            "overdue_count": len(overdue_rows),
        }
        return channel_healths, recent_failed, overdue, summary

    # ── Manual retry ─────────────────────────────────────────────────────

    async def check_duplicate(self, post_id: UUID) -> dict[str, Any]:
        """Pre-flight check for the Calendar's per-post Retry button.

        Returns the same duplicate-detection result the
        ``publish_scheduled_posts`` worker uses internally — so the
        operator sees *before* hitting Retry whether the post would
        upload, get blocked, or auto-link to an existing video.

        Two checks, in order:

        1. ``existing_upload`` — is there already a ``YouTubeUpload``
           row with ``status='done'`` for the same (episode, channel)
           pair? If yes, retrying would safely no-op (worker
           short-circuits and marks the scheduled post as published
           via the existing upload), no YouTube quota burned.

        2. ``title_similar`` — does this title match any video on the
           channel at ≥85% SequenceMatcher ratio? If yes, retry would
           hard-fail with a permanent error. The operator should
           reschedule + edit the title, or set
           ``metadata.skip_duplicate_check``.

        Result shape::

          {
            "post_id": "...",
            "is_duplicate": bool,
            "reason": "existing_upload" | "title_similar" | "none",
            "existing_video_id": "yt-id-or-null",
            "existing_video_url": "https://...",
            "match_title": "Foo",
            "match_ratio": 0.92,   # only for title_similar
            "safe_to_retry": bool, # true when nothing or only existing_upload
          }
        """
        from drevalis.models.scheduled_post import ScheduledPost as _Sched
        from drevalis.models.youtube_channel import YouTubeChannelVideo as _Vid

        post = (
            await self._db.execute(select(_Sched).where(_Sched.id == post_id))
        ).scalar_one_or_none()
        if post is None:
            raise ValueError(f"Scheduled post {post_id} not found")

        # Only meaningful for YouTube — other platforms don't have a
        # ``YouTubeChannelVideo`` table to cross-check against. Return
        # a "no match" result so the UI can render a generic "safe"
        # state without surprising the user with mysterious errors.
        if post.platform != "youtube" or post.youtube_channel_id is None:
            return {
                "post_id": str(post.id),
                "is_duplicate": False,
                "reason": "none",
                "existing_video_id": None,
                "existing_video_url": None,
                "match_title": None,
                "match_ratio": None,
                "safe_to_retry": True,
            }

        # Check 1 — existing done upload for (episode, channel). Mirror
        # the worker's lookup so the answer is consistent with what the
        # worker would actually do at retry time.
        from drevalis.repositories.youtube import YouTubeUploadRepository

        upload_repo = YouTubeUploadRepository(self._db)
        existing = await upload_repo.get_existing_done(post.content_id, post.youtube_channel_id)
        if existing is not None:
            return {
                "post_id": str(post.id),
                "is_duplicate": True,
                "reason": "existing_upload",
                "existing_video_id": existing.youtube_video_id,
                "existing_video_url": (
                    f"https://www.youtube.com/watch?v={existing.youtube_video_id}"
                    if existing.youtube_video_id
                    else None
                ),
                "match_title": None,
                "match_ratio": None,
                # Safe in the sense that retry won't waste quota — the
                # worker will short-circuit and just promote the post
                # to ``published`` linked to the existing upload row.
                "safe_to_retry": True,
            }

        # Check 2 — title-similarity against every video on the channel.
        # Same threshold (0.85) and same SequenceMatcher as the worker.
        if post.title:
            import difflib as _difflib

            ch_vids = list(
                (
                    await self._db.execute(
                        select(_Vid).where(_Vid.channel_id == post.youtube_channel_id)
                    )
                )
                .scalars()
                .all()
            )
            norm = (post.title or "").lower()
            best: tuple[float, str, str] | None = None
            for v in ch_vids:
                r = _difflib.SequenceMatcher(
                    None, norm, (v.title or "").lower()
                ).ratio()
                if r >= 0.85 and (best is None or r > best[0]):
                    best = (r, v.title or "", v.youtube_video_id)
            if best is not None:
                return {
                    "post_id": str(post.id),
                    "is_duplicate": True,
                    "reason": "title_similar",
                    "existing_video_id": best[2],
                    "existing_video_url": (
                        f"https://www.youtube.com/watch?v={best[2]}"
                        if best[2]
                        else None
                    ),
                    "match_title": best[1],
                    "match_ratio": round(best[0], 3),
                    # NOT safe — worker would hard-fail with the same
                    # title-similarity error.
                    "safe_to_retry": False,
                }

        return {
            "post_id": str(post.id),
            "is_duplicate": False,
            "reason": "none",
            "existing_video_id": None,
            "existing_video_url": None,
            "match_title": None,
            "match_ratio": None,
            "safe_to_retry": True,
        }

    async def reschedule_failed(
        self, *, within_hours: int = 720
    ) -> dict[str, Any]:
        """Spread every failed + missed post across the next free slots,
        server-side, in one transaction.

        "Missed" = ``status='scheduled'`` with ``scheduled_at`` more than
        15 minutes in the past (the worker hasn't picked it up). "Failed"
        = ``status='failed'``. Both get walked in chronological order and
        each is assigned the next free slot via ``find_next_free_slot``,
        flushing between iterations so slot N+1 sees slot N as occupied —
        otherwise they'd all pile onto the same slot.

        Why server-side: the calendar's old client-side loop fired two
        round-trips per post (``/next-slot`` + ``/update``). With 100+
        failed posts that's 200+ sequential requests — slow and fragile.
        Doing it here is one request, one transaction.

        Returns ``{"rescheduled": N, "skipped": M, "details": [...]}``.
        """
        from datetime import timedelta as _td

        from drevalis.models.scheduled_post import ScheduledPost as _Sched
        from drevalis.services.schedule_slot import find_next_free_slot

        now = datetime.now(UTC)
        missed_cutoff = now - _td(minutes=15)
        window_cutoff = now - _td(hours=within_hours)

        stmt = (
            select(_Sched)
            .where(
                or_(
                    _Sched.status == "failed",
                    and_(
                        _Sched.status == "scheduled",
                        _Sched.scheduled_at < missed_cutoff,
                    ),
                ),
                _Sched.scheduled_at >= window_cutoff,
            )
            .order_by(_Sched.scheduled_at)
        )
        posts = list((await self._db.execute(stmt)).scalars().all())

        rescheduled = 0
        skipped = 0
        details: list[dict[str, Any]] = []
        for post in posts:
            try:
                slot = await find_next_free_slot(
                    platform=post.platform,
                    channel_id=post.youtube_channel_id,
                    after_utc=now,
                    db=self._db,
                )
                post.scheduled_at = slot
                post.status = "scheduled"
                post.error_message = None
                # Flush (not commit) so the next find_next_free_slot call
                # sees this row's new slot as occupied via _conflicts.
                await self._db.flush()
                rescheduled += 1
                details.append(
                    {"post_id": str(post.id), "scheduled_at": slot.isoformat()}
                )
            except ValueError:
                # No free slot within the lookahead horizon — leave the
                # post as-is and report it.
                skipped += 1

        await self._db.commit()
        logger.info(
            "schedule.reschedule_failed",
            rescheduled=rescheduled,
            skipped=skipped,
            within_hours=within_hours,
        )
        return {"rescheduled": rescheduled, "skipped": skipped, "details": details}

    async def retry_failed(self, payload: RetryFailedRequest) -> tuple[list[UUID], list[UUID]]:
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=payload.within_hours)

        stmt = select(ScheduledPost).where(ScheduledPost.status == "failed")
        if payload.post_ids:
            stmt = stmt.where(ScheduledPost.id.in_(payload.post_ids))
        else:
            stmt = stmt.where(ScheduledPost.scheduled_at >= cutoff)
        rows = list((await self._db.execute(stmt)).scalars().all())

        requeued: list[UUID] = []
        skipped: list[UUID] = []
        for post in rows:
            if post.scheduled_at < cutoff:
                skipped.append(post.id)
                continue
            await self._sched.update(post.id, status="scheduled", error_message=None)
            requeued.append(post.id)
        await self._db.commit()

        logger.info(
            "schedule.retry_failed",
            requeued_count=len(requeued),
            skipped_count=len(skipped),
            within_hours=payload.within_hours,
        )
        return requeued, skipped


def to_response(post: ScheduledPost) -> ScheduleResponse:
    return ScheduleResponse.model_validate(post)
