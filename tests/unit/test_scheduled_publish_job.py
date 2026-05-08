"""Tests for the publish-scheduled-posts cron
(``workers/jobs/scheduled.py``).

Critical contracts pinned:

* cron_lock guards the entry — non-owner returns immediately
* No pending posts → zero result dict
* Non-YouTube platform → marked failed with clear message
* YouTube without creds / channel / video asset → marked failed
* Per-post exception is caught, status=failed, batch continues
* "Other platforms not implemented" branch still bumps the failed
  counter so the cron owner sees something happened
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.scheduled import publish_scheduled_posts

# ── Helpers ──────────────────────────────────────────────────────────


def _make_settings() -> Any:
    s = MagicMock()
    s.youtube_client_id = "id"
    s.youtube_client_secret = "secret"
    s.youtube_redirect_uri = "http://x/cb"
    s.encryption_key = "k"
    s.storage_base_path = "/tmp/storage"
    return s


def _make_post(
    *,
    platform: str = "youtube",
    content_type: str = "episode",
    youtube_channel_id: Any = None,
    title: str = "Test Post",
) -> Any:
    p = MagicMock()
    p.id = uuid4()
    p.platform = platform
    p.content_type = content_type
    p.content_id = uuid4()
    p.youtube_channel_id = youtube_channel_id
    p.title = title
    p.description = ""
    p.tags = ""
    p.privacy = "public"
    return p


def _make_session_factory(session_mock: Any) -> Any:
    class _SF:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return session_mock

        async def __aexit__(self, *_a: Any) -> None:
            return None

    return _SF()


def _make_session(pending: list[Any]) -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


def _patch_repo(repo_path: str, repo_mock: Any) -> Any:
    return patch(repo_path, return_value=repo_mock)


def _patch_module() -> Any:
    """No-op: settings/repos are imported inside the function so each
    test patches what it needs explicitly."""
    return patch("drevalis.core.config.Settings")


# ── cron_lock guard ─────────────────────────────────────────────────


class TestCronLockGuard:
    async def test_skipped_when_not_cron_owner(self) -> None:
        # Two workers tick simultaneously; one wins the lock, the
        # other returns the skip sentinel without doing any DB work.
        # Simulate by having cron_lock yield False (lock held by other).
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _losing_lock(ctx: Any, name: str, *, ttl_s: int) -> Any:
            yield False

        with patch("drevalis.workers.cron_lock.cron_lock", side_effect=_losing_lock):
            # Re-import the function so it picks up the patched lock.
            result = await publish_scheduled_posts({"redis": AsyncMock()})

        assert result == {"status": "skipped_not_cron_owner"}


# ── Empty-pending path ──────────────────────────────────────────────


class TestEmptyPending:
    async def test_no_pending_posts_returns_zeros(self) -> None:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _winning_lock(ctx: Any, name: str, *, ttl_s: int) -> Any:
            yield True

        repo = MagicMock()
        repo.get_pending = AsyncMock(return_value=[])

        session = _make_session(pending=[])
        with (
            patch("drevalis.workers.cron_lock.cron_lock", side_effect=_winning_lock),
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.repositories.scheduled_post.ScheduledPostRepository",
                return_value=repo,
            ),
        ):
            result = await publish_scheduled_posts(
                {
                    "session_factory": _make_session_factory(session),
                    "redis": AsyncMock(),
                }
            )
        assert result == {"published": 0, "failed": 0, "pending_checked": 0}


# ── Non-YouTube platform branch ─────────────────────────────────────


class TestNonYouTubePlatform:
    async def test_unknown_platform_marked_failed(self) -> None:
        # Pin: a platform string that isn't in the supported set
        # (youtube / tiktok / instagram / facebook / x) fails fast with
        # a clear "Unknown platform" message rather than silently
        # dropping or attempting an undefined upload.
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _winning_lock(ctx: Any, name: str, *, ttl_s: int) -> Any:
            yield True

        post = _make_post(platform="myspace")  # Genuinely unknown.
        repo = MagicMock()
        repo.get_pending = AsyncMock(return_value=[post])
        repo.update = AsyncMock()

        session = _make_session(pending=[post])
        with (
            patch("drevalis.workers.cron_lock.cron_lock", side_effect=_winning_lock),
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.repositories.scheduled_post.ScheduledPostRepository",
                return_value=repo,
            ),
        ):
            result = await publish_scheduled_posts(
                {
                    "session_factory": _make_session_factory(session),
                    "redis": AsyncMock(),
                }
            )
        assert result["failed"] == 1
        assert result["published"] == 0
        update_calls = repo.update.call_args_list
        last_kwargs = update_calls[-1].kwargs
        assert last_kwargs["status"] == "failed"
        assert "myspace" in last_kwargs["error_message"]
        assert "Unknown platform" in last_kwargs["error_message"]

    async def test_social_platform_creates_social_upload_row(self) -> None:
        # Pin: a scheduled instagram post that comes due hands off to
        # the social-uploads pipeline by creating a SocialUpload row;
        # the ScheduledPost flips to ``published`` with the new row's
        # id stashed in ``remote_id`` for correlation.
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        from unittest.mock import call

        @asynccontextmanager
        async def _winning_lock(ctx: Any, name: str, *, ttl_s: int) -> Any:
            yield True

        post = _make_post(platform="instagram")
        repo = MagicMock()
        repo.get_pending = AsyncMock(return_value=[post])
        repo.update = AsyncMock()

        # Active social platform connection exists.
        platform_row = SimpleNamespace(id=uuid4(), platform="instagram", is_active=True)

        # Build a session that:
        #   - Returns the scheduled post for get_pending
        #   - Returns the active social platform when queried
        session = _make_session(pending=[post])
        # The social-platform query is the second SELECT. _make_session
        # cycles through pending; we override execute to dispatch.
        original_execute = session.execute

        async def _execute(stmt: Any) -> Any:
            stmt_str = str(stmt)
            if "social_platforms" in stmt_str:
                r = MagicMock()
                r.scalar_one_or_none = MagicMock(return_value=platform_row)
                return r
            return await original_execute(stmt)

        session.execute = _execute  # type: ignore[assignment]

        # Video asset present.
        asset_repo_mock = MagicMock()
        asset_repo_mock.get_by_episode_and_type = AsyncMock(
            return_value=[SimpleNamespace(file_path="episodes/x/output/final.mp4")]
        )

        with (
            patch("drevalis.workers.cron_lock.cron_lock", side_effect=_winning_lock),
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.repositories.scheduled_post.ScheduledPostRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.repositories.media_asset.MediaAssetRepository",
                return_value=asset_repo_mock,
            ),
        ):
            result = await publish_scheduled_posts(
                {
                    "session_factory": _make_session_factory(session),
                    "redis": AsyncMock(),
                }
            )

        assert result["published"] == 1
        assert result["failed"] == 0
        # Repo.update called with status=published + remote_id storing
        # the SocialUpload id.
        update_kwargs = repo.update.call_args_list[-1].kwargs
        assert update_kwargs["status"] == "published"
        assert update_kwargs["remote_id"].startswith("social_upload:")
        # session.add was called with a SocialUpload row.
        from drevalis.models.social_platform import SocialUpload as _SU

        added = [c.args[0] for c in session.add.call_args_list]
        assert any(isinstance(a, _SU) for a in added)
        social_row = next(a for a in added if isinstance(a, _SU))
        assert social_row.platform_id == platform_row.id
        assert social_row.episode_id == post.content_id
        assert social_row.upload_status == "pending"
        # Stop the unused-import warning.
        _ = call

    async def test_social_platform_no_active_connection_fails(self) -> None:
        # Pin: a scheduled tiktok post with no active SocialPlatform
        # row fails fast with an actionable message rather than
        # creating an orphan SocialUpload row that would just bounce
        # in the social cron.
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _winning_lock(ctx: Any, name: str, *, ttl_s: int) -> Any:
            yield True

        post = _make_post(platform="tiktok")
        repo = MagicMock()
        repo.get_pending = AsyncMock(return_value=[post])
        repo.update = AsyncMock()

        session = _make_session(pending=[post])
        original_execute = session.execute

        async def _execute(stmt: Any) -> Any:
            stmt_str = str(stmt)
            if "social_platforms" in stmt_str:
                r = MagicMock()
                r.scalar_one_or_none = MagicMock(return_value=None)
                return r
            return await original_execute(stmt)

        session.execute = _execute  # type: ignore[assignment]

        with (
            patch("drevalis.workers.cron_lock.cron_lock", side_effect=_winning_lock),
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.repositories.scheduled_post.ScheduledPostRepository",
                return_value=repo,
            ),
        ):
            result = await publish_scheduled_posts(
                {
                    "session_factory": _make_session_factory(session),
                    "redis": AsyncMock(),
                }
            )
        assert result["failed"] == 1
        last_kwargs = repo.update.call_args_list[-1].kwargs
        assert last_kwargs["status"] == "failed"
        assert "No active tiktok connection" in last_kwargs["error_message"]


# ── YouTube failure paths ───────────────────────────────────────────


class TestYouTubeMissingCredentials:
    async def test_missing_creds_marks_post_failed(self) -> None:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _winning_lock(ctx: Any, name: str, *, ttl_s: int) -> Any:
            yield True

        post = _make_post(platform="youtube")
        repo = MagicMock()
        repo.get_pending = AsyncMock(return_value=[post])
        repo.update = AsyncMock()
        session = _make_session(pending=[post])

        async def _no_creds(*args: Any, **kw: Any) -> tuple[None, None]:
            return None, None

        with (
            patch("drevalis.workers.cron_lock.cron_lock", side_effect=_winning_lock),
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.repositories.scheduled_post.ScheduledPostRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.services.integration_keys.resolve_youtube_credentials",
                side_effect=_no_creds,
            ),
        ):
            result = await publish_scheduled_posts(
                {
                    "session_factory": _make_session_factory(session),
                    "redis": AsyncMock(),
                }
            )

        assert result["failed"] == 1
        # The error message points at the right config knobs.
        last = repo.update.call_args_list[-1].kwargs
        assert last["status"] == "failed"
        assert "YouTube not configured" in last["error_message"]


class TestYouTubeMissingChannel:
    async def test_no_channel_marks_post_failed(self) -> None:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _winning_lock(ctx: Any, name: str, *, ttl_s: int) -> Any:
            yield True

        post = _make_post(platform="youtube", youtube_channel_id=None)
        repo = MagicMock()
        repo.get_pending = AsyncMock(return_value=[post])
        repo.update = AsyncMock()
        session = _make_session(pending=[post])

        # Episode + series have no youtube_channel_id either.
        episode = MagicMock()
        episode.series_id = uuid4()
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=episode)
        series = MagicMock()
        series.youtube_channel_id = None
        series_repo = MagicMock()
        series_repo.get_by_id = AsyncMock(return_value=series)
        ch_repo = MagicMock()
        ch_repo.get_by_id = AsyncMock(return_value=None)

        async def _good_creds(*a: Any, **kw: Any) -> tuple[str, str]:
            return "id", "secret"

        with (
            patch("drevalis.workers.cron_lock.cron_lock", side_effect=_winning_lock),
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.repositories.scheduled_post.ScheduledPostRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.services.integration_keys.resolve_youtube_credentials",
                side_effect=_good_creds,
            ),
            patch(
                "drevalis.repositories.youtube.YouTubeChannelRepository",
                return_value=ch_repo,
            ),
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.series.SeriesRepository",
                return_value=series_repo,
            ),
            patch("drevalis.services.youtube.YouTubeService", return_value=MagicMock()),
        ):
            result = await publish_scheduled_posts(
                {
                    "session_factory": _make_session_factory(session),
                    "redis": AsyncMock(),
                }
            )

        assert result["failed"] == 1
        last = repo.update.call_args_list[-1].kwargs
        assert "No YouTube channel assigned" in last["error_message"]


# ── Per-post error containment ──────────────────────────────────────


class TestErrorContainment:
    async def test_first_post_fails_second_still_processes(self) -> None:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _winning_lock(ctx: Any, name: str, *, ttl_s: int) -> Any:
            yield True

        post1 = _make_post(platform="instagram")  # always fails
        post2 = _make_post(platform="instagram")  # also fails
        repo = MagicMock()
        repo.get_pending = AsyncMock(return_value=[post1, post2])
        repo.update = AsyncMock()
        session = _make_session(pending=[post1, post2])

        with (
            patch("drevalis.workers.cron_lock.cron_lock", side_effect=_winning_lock),
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.repositories.scheduled_post.ScheduledPostRepository",
                return_value=repo,
            ),
        ):
            result = await publish_scheduled_posts(
                {
                    "session_factory": _make_session_factory(session),
                    "redis": AsyncMock(),
                }
            )

        # Both posts processed (even though both fail).
        assert result["pending_checked"] == 2
        assert result["failed"] == 2

    async def test_per_post_exception_does_not_abort_batch(self) -> None:
        # First post raises a non-platform exception (e.g. transient
        # DB error during the publishing→failed transition).
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _winning_lock(ctx: Any, name: str, *, ttl_s: int) -> Any:
            yield True

        post1 = _make_post(platform="youtube")
        post2 = _make_post(platform="instagram")  # this one runs cleanly

        repo = MagicMock()
        repo.get_pending = AsyncMock(return_value=[post1, post2])
        # ``update`` raises on first call (post1 status=publishing
        # transition), succeeds on later calls.
        update_count = {"n": 0}

        async def _update(*args: Any, **kw: Any) -> None:
            update_count["n"] += 1
            if update_count["n"] == 1:
                raise RuntimeError("DB hiccup")
            return None

        repo.update = AsyncMock(side_effect=_update)
        session = _make_session(pending=[post1, post2])

        with (
            patch("drevalis.workers.cron_lock.cron_lock", side_effect=_winning_lock),
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.repositories.scheduled_post.ScheduledPostRepository",
                return_value=repo,
            ),
        ):
            result = await publish_scheduled_posts(
                {
                    "session_factory": _make_session_factory(session),
                    "redis": AsyncMock(),
                }
            )

        # Both posts counted as failed; batch did not abort.
        assert result["pending_checked"] == 2
        assert result["failed"] == 2
        # No published posts (both failed).
        assert result["published"] == 0
