"""ABTestService — pair-management for A/B test rows.

Layering: keeps the route file free of repository + ORM imports
(audit F-A-01). The service owns the cross-resource validation
(both episodes exist, both belong to the named series) plus the
side-by-side YouTube-stats lookup that the detail endpoint surfaces.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.models.ab_test import ABTest
from drevalis.models.episode import Episode
from drevalis.repositories.youtube import YouTubeUploadRepository


class ABTestService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._uploads = YouTubeUploadRepository(db)

    async def list_all(self, series_id: UUID | None = None) -> list[ABTest]:
        q = select(ABTest).order_by(ABTest.created_at.desc())
        if series_id is not None:
            q = q.where(ABTest.series_id == series_id)
        rows = (await self._db.execute(q)).scalars().all()
        return list(rows)

    async def get(self, test_id: UUID) -> ABTest:
        test = await self._db.get(ABTest, test_id)
        if not test:
            raise NotFoundError("ab_test", test_id)
        return test

    async def create(
        self,
        *,
        series_id: UUID,
        episode_a_id: UUID,
        episode_b_id: UUID,
        variant_label: str,
        notes: str | None,
    ) -> ABTest:
        if episode_a_id == episode_b_id:
            raise ValidationError("An A/B test needs two different episodes.")

        # Verify both episodes exist and share the named series.
        ep_rows = await self._db.execute(
            select(Episode).where(Episode.id.in_([episode_a_id, episode_b_id]))
        )
        eps = {e.id: e for e in ep_rows.scalars().all()}
        if len(eps) != 2:
            raise NotFoundError("episode pair", f"{episode_a_id} / {episode_b_id}")
        if eps[episode_a_id].series_id != series_id:
            raise ValidationError("episode_a does not belong to the specified series.")
        if eps[episode_b_id].series_id != series_id:
            raise ValidationError("episode_b does not belong to the specified series.")

        test = ABTest(
            series_id=series_id,
            episode_a_id=episode_a_id,
            episode_b_id=episode_b_id,
            variant_label=variant_label,
            notes=notes,
        )
        self._db.add(test)
        await self._db.commit()
        await self._db.refresh(test)
        return test

    async def delete(self, test_id: UUID) -> None:
        """Idempotent delete (matches previous in-route 204 behaviour)."""
        test = await self._db.get(ABTest, test_id)
        if not test:
            return
        await self._db.delete(test)
        await self._db.commit()

    async def stats_for_pair(self, test: ABTest) -> dict[UUID, dict[str, Any]]:
        """Return side-by-side stats for both episodes in the pair.

        Reads view/like/comment counts from our local YouTubeUpload
        rows (populated by upload + periodic refresh) — no live YouTube
        Data API call.
        """
        out: dict[UUID, dict[str, Any]] = {}
        for ep_id in (test.episode_a_id, test.episode_b_id):
            ep = await self._db.get(Episode, ep_id)
            if ep is None:
                continue
            uploads = await self._uploads.get_by_episode(ep_id)
            last = uploads[-1] if uploads else None
            out[ep_id] = {
                "episode_id": ep_id,
                "title": ep.title,
                "status": ep.status,
                "youtube_video_id": last.youtube_video_id if last else None,
                "youtube_url": last.youtube_url if last else None,
                "youtube_views": getattr(last, "view_count", None) if last else None,
                "youtube_likes": getattr(last, "like_count", None) if last else None,
                "youtube_comments": getattr(last, "comment_count", None) if last else None,
            }
        return out
