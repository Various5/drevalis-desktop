"""Tests for the remaining mid-coverage repositories.

Targets:
  * ``repositories/scheduled_post.py``  — pending / upcoming / calendar / orphan prune
  * ``repositories/social.py``          — platform + upload + aggregate stats
  * ``repositories/youtube.py``         — channels, uploads, audiobook uploads, playlists
  * ``repositories/media_asset.py``     — episode scoping, scene scoping, bulk deletes

Tests inspect SQL via ``session.execute`` so column drift fails loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from drevalis.repositories.media_asset import MediaAssetRepository
from drevalis.repositories.scheduled_post import ScheduledPostRepository
from drevalis.repositories.social import (
    SocialPlatformRepository,
    SocialUploadRepository,
)
from drevalis.repositories.youtube import (
    YouTubeAudiobookUploadRepository,
    YouTubeChannelRepository,
    YouTubePlaylistRepository,
    YouTubeUploadRepository,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _mock_session(rows: list[Any] | None = None, scalar_one_value: Any = None) -> AsyncMock:
    rows = rows or []
    session = AsyncMock()
    result = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = rows
    result.scalars.return_value = scalars_proxy
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    result.scalar_one.return_value = scalar_one_value if scalar_one_value is not None else 0
    result.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def _multi_session(*results: Any) -> AsyncMock:
    """Session whose ``execute`` returns a different result on each call."""
    session = AsyncMock()
    iterator = iter(results)

    async def _execute(_stmt: Any) -> Any:
        return next(iterator)

    session.execute = AsyncMock(side_effect=_execute)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def _scalars_proxy(rows: list[Any]) -> MagicMock:
    result = MagicMock()
    proxy = MagicMock()
    proxy.all.return_value = rows
    result.scalars.return_value = proxy
    return result


def _last_sql(session: AsyncMock) -> str:
    stmt = session.execute.await_args.args[0]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ══════════════════════════════════════════════════════════════════
# ScheduledPostRepository
# ══════════════════════════════════════════════════════════════════


class TestScheduledPostQueries:
    async def test_get_pending_filters_status_and_time(self) -> None:
        session = _mock_session([])
        repo = ScheduledPostRepository(session)
        cutoff = datetime(2026, 5, 1, tzinfo=UTC)
        await repo.get_pending(cutoff)
        sql = _last_sql(session)
        assert "status = 'scheduled'" in sql
        assert "scheduled_at <= " in sql
        # Order ascending by scheduled_at.
        order = sql.split("ORDER BY")[1].lower()
        assert "desc" not in order

    async def test_get_by_content_filters_both(self) -> None:
        session = _mock_session([])
        repo = ScheduledPostRepository(session)
        cid = uuid4()
        await repo.get_by_content("episode", cid)
        sql = _last_sql(session)
        assert "content_type = 'episode'" in sql
        assert "content_id" in sql
        assert "scheduled_at DESC" in sql

    async def test_get_upcoming_default_limit_20(self) -> None:
        session = _mock_session([])
        repo = ScheduledPostRepository(session)
        await repo.get_upcoming()
        sql = _last_sql(session)
        assert "status = 'scheduled'" in sql
        assert "LIMIT 20" in sql

    async def test_get_calendar_window_filter(self) -> None:
        session = _mock_session([])
        repo = ScheduledPostRepository(session)
        await repo.get_calendar(
            datetime(2026, 5, 1, tzinfo=UTC),
            datetime(2026, 6, 1, tzinfo=UTC),
        )
        sql = _last_sql(session)
        assert "scheduled_at >=" in sql
        assert "scheduled_at <=" in sql


class TestScheduledPostPruneOrphaned:
    async def test_no_orphans_returns_zero_without_delete(self) -> None:
        # First two SELECTs return empty → no DELETE executed.
        session = _multi_session(
            _scalars_proxy([]),  # episode orphans
            _scalars_proxy([]),  # audiobook orphans
        )
        repo = ScheduledPostRepository(session)
        out = await repo.prune_orphaned()
        assert out == 0
        # Only the two SELECTs executed.
        assert session.execute.await_count == 2
        session.commit.assert_not_awaited()

    async def test_orphans_deleted_and_count_returned(self) -> None:
        ep_orphans = [uuid4(), uuid4()]
        ab_orphans = [uuid4()]
        session = _multi_session(
            _scalars_proxy(ep_orphans),
            _scalars_proxy(ab_orphans),
            MagicMock(),  # the DELETE result
        )
        repo = ScheduledPostRepository(session)
        out = await repo.prune_orphaned()
        assert out == 3
        # Three executes: 2 SELECTs + 1 DELETE.
        assert session.execute.await_count == 3
        session.commit.assert_awaited_once()

    async def test_only_episode_orphans(self) -> None:
        session = _multi_session(
            _scalars_proxy([uuid4()]),
            _scalars_proxy([]),
            MagicMock(),
        )
        repo = ScheduledPostRepository(session)
        out = await repo.prune_orphaned()
        assert out == 1


# ══════════════════════════════════════════════════════════════════
# SocialPlatformRepository / SocialUploadRepository
# ══════════════════════════════════════════════════════════════════


class TestSocialPlatformRepo:
    async def test_get_active_by_platform_returns_one(self) -> None:
        row = MagicMock()
        session = _mock_session([row])
        repo = SocialPlatformRepository(session)
        out = await repo.get_active_by_platform("tiktok")
        assert out is row
        sql = _last_sql(session)
        assert "platform = 'tiktok'" in sql
        assert "is_active" in sql
        assert "LIMIT 1" in sql

    async def test_get_all_active_orders_by_platform_then_recent(self) -> None:
        session = _mock_session([])
        repo = SocialPlatformRepository(session)
        await repo.get_all_active()
        sql = _last_sql(session)
        assert "is_active" in sql
        order = sql.split("ORDER BY")[1].lower()
        # platform first, then created_at DESC
        assert order.find("platform") < order.find("created_at")
        assert "desc" in order

    async def test_deactivate_platform_walks_active_rows(self) -> None:
        a = MagicMock(is_active=True)
        b = MagicMock(is_active=True)
        session = _mock_session([a, b])
        repo = SocialPlatformRepository(session)
        await repo.deactivate_platform("instagram")
        # Each row's is_active flipped to False.
        assert a.is_active is False
        assert b.is_active is False
        session.flush.assert_awaited_once()

    async def test_deactivate_platform_no_active_rows_still_flushes(self) -> None:
        session = _mock_session([])
        repo = SocialPlatformRepository(session)
        await repo.deactivate_platform("instagram")
        session.flush.assert_awaited_once()


class TestSocialUploadRepo:
    async def test_get_by_content_filters(self) -> None:
        session = _mock_session([])
        repo = SocialUploadRepository(session)
        await repo.get_by_content("episode", uuid4())
        sql = _last_sql(session)
        assert "content_type = 'episode'" in sql
        assert "episode_id" in sql
        assert "created_at DESC" in sql

    async def test_get_by_platform_default_limit_50(self) -> None:
        session = _mock_session([])
        repo = SocialUploadRepository(session)
        await repo.get_by_platform(uuid4())
        sql = _last_sql(session)
        assert "platform_id" in sql
        assert "LIMIT 50" in sql

    async def test_get_recent_default_limit_50(self) -> None:
        session = _mock_session([])
        repo = SocialUploadRepository(session)
        await repo.get_recent()
        sql = _last_sql(session)
        assert "LIMIT 50" in sql

    async def test_get_platform_stats_returns_dicts(self) -> None:
        # Aggregate with SUM/coalesce — synthesize a fake Row.
        row = MagicMock()
        row.platform = "tiktok"
        row.total_uploads = 10
        row.successful_uploads = 8
        row.total_views = 1000
        row.total_likes = 50
        row.total_comments = 12
        row.total_shares = 3

        session = _mock_session()
        result = MagicMock()
        result.all.return_value = [row]
        session.execute = AsyncMock(return_value=result)

        repo = SocialUploadRepository(session)
        out = await repo.get_platform_stats()
        assert out == [
            {
                "platform": "tiktok",
                "total_uploads": 10,
                "successful_uploads": 8,
                "total_views": 1000,
                "total_likes": 50,
                "total_comments": 12,
                "total_shares": 3,
            }
        ]


# ══════════════════════════════════════════════════════════════════
# YouTube repositories
# ══════════════════════════════════════════════════════════════════


class TestYouTubeChannelRepo:
    async def test_get_active(self) -> None:
        row = MagicMock()
        session = _mock_session([row])
        repo = YouTubeChannelRepository(session)
        out = await repo.get_active()
        assert out is row
        sql = _last_sql(session)
        assert "is_active" in sql
        assert "LIMIT 1" in sql

    async def test_get_active_returns_none_when_empty(self) -> None:
        session = _mock_session([])
        repo = YouTubeChannelRepository(session)
        assert await repo.get_active() is None

    async def test_get_by_channel_id(self) -> None:
        session = _mock_session([])
        repo = YouTubeChannelRepository(session)
        await repo.get_by_channel_id("UCabcDEF123")
        sql = _last_sql(session)
        assert "channel_id = 'UCabcDEF123'" in sql

    async def test_get_all_channels_recent_first(self) -> None:
        session = _mock_session([])
        repo = YouTubeChannelRepository(session)
        await repo.get_all_channels()
        sql = _last_sql(session)
        assert "created_at DESC" in sql

    async def test_deactivate_all(self) -> None:
        a = MagicMock(is_active=True)
        b = MagicMock(is_active=True)
        session = _mock_session([a, b])
        repo = YouTubeChannelRepository(session)
        await repo.deactivate_all()
        assert a.is_active is False
        assert b.is_active is False
        session.flush.assert_awaited_once()


class TestYouTubeUploadRepo:
    async def test_get_by_episode(self) -> None:
        session = _mock_session([])
        repo = YouTubeUploadRepository(session)
        eid = uuid4()
        await repo.get_by_episode(eid)
        sql = _last_sql(session)
        assert "episode_id" in sql
        assert "created_at DESC" in sql

    async def test_get_recent_default_limit_50(self) -> None:
        session = _mock_session([])
        repo = YouTubeUploadRepository(session)
        await repo.get_recent()
        sql = _last_sql(session)
        assert "LIMIT 50" in sql


class TestYouTubeAudiobookUploadRepo:
    async def test_get_by_audiobook(self) -> None:
        session = _mock_session([])
        repo = YouTubeAudiobookUploadRepository(session)
        await repo.get_by_audiobook(uuid4())
        sql = _last_sql(session)
        assert "audiobook_id" in sql
        assert "created_at DESC" in sql


class TestYouTubePlaylistRepo:
    async def test_get_by_channel(self) -> None:
        session = _mock_session([])
        repo = YouTubePlaylistRepository(session)
        await repo.get_by_channel(uuid4())
        sql = _last_sql(session)
        assert "channel_id" in sql

    async def test_get_by_youtube_playlist_id(self) -> None:
        session = _mock_session([])
        repo = YouTubePlaylistRepository(session)
        await repo.get_by_youtube_playlist_id("PLabc123")
        sql = _last_sql(session)
        assert "youtube_playlist_id = 'PLabc123'" in sql


# ══════════════════════════════════════════════════════════════════
# MediaAssetRepository
# ══════════════════════════════════════════════════════════════════


class TestMediaAssetQueries:
    async def test_get_by_episode_orders_chronological(self) -> None:
        session = _mock_session([])
        repo = MediaAssetRepository(session)
        eid = uuid4()
        await repo.get_by_episode(eid)
        sql = _last_sql(session)
        assert "episode_id" in sql
        # Chronological (ascending) — assets render in pipeline-step order.
        order = sql.split("ORDER BY")[1].lower()
        assert "desc" not in order

    async def test_get_by_episode_and_type_filters_both(self) -> None:
        session = _mock_session([])
        repo = MediaAssetRepository(session)
        await repo.get_by_episode_and_type(uuid4(), "thumbnail")
        sql = _last_sql(session)
        assert "asset_type = 'thumbnail'" in sql
        assert "episode_id" in sql

    async def test_get_total_size_bytes_returns_zero_when_empty(self) -> None:
        session = _mock_session(scalar_one_value=None)
        repo = MediaAssetRepository(session)
        out = await repo.get_total_size_bytes()
        assert out == 0

    async def test_get_total_size_bytes_returns_sum(self) -> None:
        session = _mock_session(scalar_one_value=12345)
        repo = MediaAssetRepository(session)
        out = await repo.get_total_size_bytes()
        assert out == 12345
        sql = _last_sql(session)
        assert "sum(" in sql.lower() or "coalesce(" in sql.lower()

    async def test_get_by_episode_and_scene(self) -> None:
        session = _mock_session([])
        repo = MediaAssetRepository(session)
        await repo.get_by_episode_and_scene(uuid4(), 7)
        sql = _last_sql(session)
        assert "episode_id" in sql
        assert "scene_number = 7" in sql


class TestMediaAssetDeletes:
    async def test_delete_by_episode_returns_count(self) -> None:
        # Returning yields 3 row ids → count is 3.
        deleted_ids = [uuid4(), uuid4(), uuid4()]
        session = _mock_session(deleted_ids)
        repo = MediaAssetRepository(session)
        out = await repo.delete_by_episode(uuid4())
        assert out == 3
        session.flush.assert_awaited_once()

    async def test_delete_by_episode_zero_when_nothing_to_delete(self) -> None:
        session = _mock_session([])
        repo = MediaAssetRepository(session)
        out = await repo.delete_by_episode(uuid4())
        assert out == 0

    async def test_delete_by_episode_and_scene_filters_both(self) -> None:
        session = _mock_session([uuid4()])
        repo = MediaAssetRepository(session)
        out = await repo.delete_by_episode_and_scene(uuid4(), 3)
        assert out == 1
        sql = _last_sql(session)
        assert "scene_number = 3" in sql

    async def test_delete_by_episode_and_types_empty_returns_zero(self) -> None:
        # Defensive short-circuit: empty type list must NOT issue
        # ``DELETE FROM media_assets WHERE episode_id = ?``
        # (which would wipe every asset for the episode).
        session = _mock_session([])
        repo = MediaAssetRepository(session)
        out = await repo.delete_by_episode_and_types(uuid4(), [])
        assert out == 0
        session.execute.assert_not_awaited()

    async def test_delete_by_episode_and_types_filters_in(self) -> None:
        session = _mock_session([uuid4(), uuid4()])
        repo = MediaAssetRepository(session)
        out = await repo.delete_by_episode_and_types(uuid4(), ["voiceover", "caption"])
        assert out == 2
        sql = _last_sql(session)
        assert "asset_type" in sql
        assert "'voiceover'" in sql
        assert "'caption'" in sql
