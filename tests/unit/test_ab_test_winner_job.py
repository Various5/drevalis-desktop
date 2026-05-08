"""Tests for the daily A/B test winner-settlement cron
(``workers/jobs/ab_test_winner.py``).

Settles every pending ABTest pair where both uploads are 7+ days old
by fetching fresh YouTube view counts and recording the winner.
Critical contract pinned here:

* OAuth not configured → safe early-skip with all-zero result
* Maturity gate — pairs younger than 7 days stay pending
* Tie handling — comparison_at set, winner_episode_id stays NULL so
  the job doesn't re-run forever on a tied pair
* Per-test errors don't abort the batch — they're counted and the
  loop continues
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.ab_test_winner import compute_ab_test_winners

# ── Helpers ──────────────────────────────────────────────────────────


def _make_settings(*, oauth: bool = True) -> Any:
    s = MagicMock()
    s.youtube_client_id = "id" if oauth else ""
    s.youtube_client_secret = "secret" if oauth else ""
    s.youtube_redirect_uri = "http://x/cb"
    s.encryption_key = "k"
    return s


def _make_test(
    *,
    test_id: Any = None,
    episode_a_id: Any = None,
    episode_b_id: Any = None,
) -> Any:
    t = MagicMock()
    t.id = test_id or uuid4()
    t.episode_a_id = episode_a_id or uuid4()
    t.episode_b_id = episode_b_id or uuid4()
    t.winner_episode_id = None
    t.comparison_at = None
    return t


def _make_upload(
    *,
    episode_id: Any,
    youtube_video_id: str = "vid-x",
    channel_id: Any = None,
    created_at: datetime | None = None,
) -> Any:
    u = MagicMock()
    u.episode_id = episode_id
    u.youtube_video_id = youtube_video_id
    u.upload_status = "done"
    u.channel_id = channel_id or uuid4()
    u.created_at = created_at or (datetime.now(UTC) - timedelta(days=10))
    return u


def _make_channel() -> Any:
    c = MagicMock()
    c.access_token_encrypted = "enc-token"
    c.refresh_token_encrypted = "enc-refresh"
    c.token_expiry = datetime.now(UTC) + timedelta(hours=1)
    return c


def _scalars_proxy(rows: list[Any]) -> MagicMock:
    """A MagicMock whose .scalars().all() returns ``rows``."""
    result = MagicMock()
    proxy = MagicMock()
    proxy.all.return_value = rows
    result.scalars.return_value = proxy
    return result


def _make_session_factory(
    *,
    pending: list[Any],
    uploads_for_episode: dict[Any, list[Any]] | None = None,
    channel: Any | None = None,
) -> tuple[Any, Any]:
    """Build a session_factory + session pair wired up to return:

    1. ``pending`` for the first execute (the WHERE winner_episode_id IS NULL).
    2. Per-episode uploads from ``uploads_for_episode``.
    3. ``channel`` for ``session.get(YouTubeChannel, ...)``.
    """
    uploads_for_episode = uploads_for_episode or {}
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    # Track the next-execute index. Index 0 is the pending list; each
    # subsequent execute is an upload query for episode_a or _b in
    # iteration order.
    call_order = [_scalars_proxy(pending)]
    for test in pending:
        call_order.append(_scalars_proxy(uploads_for_episode.get(test.episode_a_id, [])))
        call_order.append(_scalars_proxy(uploads_for_episode.get(test.episode_b_id, [])))

    async def _execute(_stmt: Any) -> Any:
        return call_order.pop(0)

    session.execute = AsyncMock(side_effect=_execute)
    session.get = AsyncMock(return_value=channel)

    class _SF:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return session

        async def __aexit__(self, *_a: Any) -> None:
            return None

    return _SF(), session


def _patch_youtube_service(svc_mock: Any) -> Any:
    return patch("drevalis.services.youtube.YouTubeService", return_value=svc_mock)


# ── Skip path: OAuth not configured ─────────────────────────────────


class TestSkipOauthNotConfigured:
    async def test_returns_all_zeros_when_oauth_unset(self) -> None:
        # Even with no OAuth configured, the job still resolves a
        # session_factory at call boundary (eager). We pass one through
        # ctx so the call doesn't trip the global-pool guard.
        settings = _make_settings(oauth=False)
        sf, _ = _make_session_factory(pending=[])
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(MagicMock()),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result == {
            "processed": 0,
            "settled": 0,
            "skipped_not_ready": 0,
            "skipped_missing_upload": 0,
            "errored": 0,
        }


# ── Skip path: missing uploads ──────────────────────────────────────


class TestMissingUploads:
    async def test_no_uploads_for_either_episode(self) -> None:
        test = _make_test()
        sf, _session = _make_session_factory(
            pending=[test],
            uploads_for_episode={
                # Neither episode has uploads → skipped_missing_upload.
            },
        )
        settings = _make_settings()
        svc = MagicMock()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(svc),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result["processed"] == 1
        assert result["skipped_missing_upload"] == 1
        assert result["settled"] == 0

    async def test_only_one_episode_uploaded(self) -> None:
        test = _make_test()
        sf, _ = _make_session_factory(
            pending=[test],
            uploads_for_episode={
                test.episode_a_id: [_make_upload(episode_id=test.episode_a_id)],
                # episode_b_id has no uploads → skipped.
            },
        )
        settings = _make_settings()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(MagicMock()),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result["skipped_missing_upload"] == 1

    async def test_upload_without_youtube_video_id_skipped(self) -> None:
        test = _make_test()
        u_a = _make_upload(episode_id=test.episode_a_id, youtube_video_id="")
        u_b = _make_upload(episode_id=test.episode_b_id)
        sf, _ = _make_session_factory(
            pending=[test],
            uploads_for_episode={
                test.episode_a_id: [u_a],
                test.episode_b_id: [u_b],
            },
        )
        settings = _make_settings()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(MagicMock()),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result["skipped_missing_upload"] == 1


# ── Maturity gate ───────────────────────────────────────────────────


class TestMaturityGate:
    async def test_pair_younger_than_7_days_stays_pending(self) -> None:
        # Most recent upload only 3 days old → skipped_not_ready.
        test = _make_test()
        recent = datetime.now(UTC) - timedelta(days=3)
        old = datetime.now(UTC) - timedelta(days=14)
        sf, _ = _make_session_factory(
            pending=[test],
            uploads_for_episode={
                test.episode_a_id: [
                    _make_upload(episode_id=test.episode_a_id, created_at=old),
                ],
                test.episode_b_id: [
                    _make_upload(episode_id=test.episode_b_id, created_at=recent),
                ],
            },
        )
        settings = _make_settings()
        svc = MagicMock()
        svc.get_video_stats = AsyncMock()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(svc),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result["skipped_not_ready"] == 1
        assert result["settled"] == 0
        # Stats NOT fetched — maturity gate fired before the API call.
        svc.get_video_stats.assert_not_called()

    async def test_pair_exactly_7_days_old_advances_to_stats_fetch(
        self,
    ) -> None:
        # Boundary case: 7 days + a few seconds margin.
        test = _make_test()
        old_enough = datetime.now(UTC) - timedelta(days=7, seconds=10)
        sf, _ = _make_session_factory(
            pending=[test],
            uploads_for_episode={
                test.episode_a_id: [
                    _make_upload(episode_id=test.episode_a_id, created_at=old_enough),
                ],
                test.episode_b_id: [
                    _make_upload(episode_id=test.episode_b_id, created_at=old_enough),
                ],
            },
            channel=_make_channel(),
        )
        settings = _make_settings()
        svc = MagicMock()
        svc.refresh_tokens_if_needed = AsyncMock(return_value=None)
        svc.get_video_stats = AsyncMock(
            return_value=[
                {"video_id": "vid-x", "views": 100},
            ]
        )
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(svc),
        ):
            await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        # Stats fetch ran (maturity gate passed).
        svc.get_video_stats.assert_awaited_once()


# ── Channel resolution ──────────────────────────────────────────────


class TestChannelResolution:
    async def test_missing_channel_marked_errored(self) -> None:
        test = _make_test()
        old = datetime.now(UTC) - timedelta(days=14)
        sf, _ = _make_session_factory(
            pending=[test],
            uploads_for_episode={
                test.episode_a_id: [
                    _make_upload(episode_id=test.episode_a_id, created_at=old),
                ],
                test.episode_b_id: [
                    _make_upload(episode_id=test.episode_b_id, created_at=old),
                ],
            },
            channel=None,  # session.get returns None
        )
        settings = _make_settings()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(MagicMock()),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result["errored"] == 1
        assert result["settled"] == 0

    async def test_channel_without_access_token_marked_errored(self) -> None:
        test = _make_test()
        old = datetime.now(UTC) - timedelta(days=14)
        empty_channel = _make_channel()
        empty_channel.access_token_encrypted = None
        sf, _ = _make_session_factory(
            pending=[test],
            uploads_for_episode={
                test.episode_a_id: [
                    _make_upload(episode_id=test.episode_a_id, created_at=old),
                ],
                test.episode_b_id: [
                    _make_upload(episode_id=test.episode_b_id, created_at=old),
                ],
            },
            channel=empty_channel,
        )
        settings = _make_settings()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(MagicMock()),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result["errored"] == 1


# ── Stats fetch + winner determination ──────────────────────────────


def _make_settled_setup(views_a: int, views_b: int) -> tuple[Any, Any, Any, Any]:
    test = _make_test()
    old = datetime.now(UTC) - timedelta(days=14)
    u_a = _make_upload(
        episode_id=test.episode_a_id,
        youtube_video_id="vid-a",
        created_at=old,
    )
    u_b = _make_upload(
        episode_id=test.episode_b_id,
        youtube_video_id="vid-b",
        created_at=old,
    )
    sf, _session = _make_session_factory(
        pending=[test],
        uploads_for_episode={
            test.episode_a_id: [u_a],
            test.episode_b_id: [u_b],
        },
        channel=_make_channel(),
    )
    svc = MagicMock()
    svc.refresh_tokens_if_needed = AsyncMock(return_value=None)
    svc.get_video_stats = AsyncMock(
        return_value=[
            {"video_id": "vid-a", "views": views_a},
            {"video_id": "vid-b", "views": views_b},
        ]
    )
    return test, sf, svc, _session


class TestWinnerDetermination:
    async def test_a_wins(self) -> None:
        test, sf, svc, _ = _make_settled_setup(views_a=1000, views_b=500)
        settings = _make_settings()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(svc),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result["settled"] == 1
        assert test.winner_episode_id == test.episode_a_id
        assert test.comparison_at is not None

    async def test_b_wins(self) -> None:
        test, sf, svc, _ = _make_settled_setup(views_a=200, views_b=900)
        settings = _make_settings()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(svc),
        ):
            await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert test.winner_episode_id == test.episode_b_id

    async def test_tie_records_comparison_but_leaves_winner_null(self) -> None:
        # Critical: a tie must NOT leave the test in a re-runnable
        # state. ``comparison_at`` is set so the next cron skips it.
        test, sf, svc, _ = _make_settled_setup(views_a=500, views_b=500)
        settings = _make_settings()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(svc),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        # Settled even on tie (job doesn't re-run forever).
        assert result["settled"] == 1
        assert test.comparison_at is not None
        assert test.winner_episode_id is None


# ── Stats fetch failure ─────────────────────────────────────────────


class TestStatsFetchFailure:
    async def test_per_test_error_does_not_abort_batch(self) -> None:
        # Two pending tests; the first errors (API failure), the
        # second settles cleanly. Both must be counted.
        test1 = _make_test()
        test2 = _make_test()
        old = datetime.now(UTC) - timedelta(days=14)
        uploads = {
            test1.episode_a_id: [
                _make_upload(
                    episode_id=test1.episode_a_id,
                    youtube_video_id="t1-a",
                    created_at=old,
                )
            ],
            test1.episode_b_id: [
                _make_upload(
                    episode_id=test1.episode_b_id,
                    youtube_video_id="t1-b",
                    created_at=old,
                )
            ],
            test2.episode_a_id: [
                _make_upload(
                    episode_id=test2.episode_a_id,
                    youtube_video_id="t2-a",
                    created_at=old,
                )
            ],
            test2.episode_b_id: [
                _make_upload(
                    episode_id=test2.episode_b_id,
                    youtube_video_id="t2-b",
                    created_at=old,
                )
            ],
        }
        sf, _ = _make_session_factory(
            pending=[test1, test2],
            uploads_for_episode=uploads,
            channel=_make_channel(),
        )

        # First test: API call raises. Second: succeeds.
        call_count = {"n": 0}

        async def _stats(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("YouTube API 503")
            return [
                {"video_id": "t2-a", "views": 200},
                {"video_id": "t2-b", "views": 100},
            ]

        svc = MagicMock()
        svc.refresh_tokens_if_needed = AsyncMock(return_value=None)
        svc.get_video_stats = AsyncMock(side_effect=_stats)
        settings = _make_settings()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(svc),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result["processed"] == 2
        assert result["errored"] == 1
        assert result["settled"] == 1


# ── No pending tests ────────────────────────────────────────────────


class TestNoPending:
    async def test_empty_pending_returns_zeros(self) -> None:
        sf, _ = _make_session_factory(pending=[])
        settings = _make_settings()
        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            _patch_youtube_service(MagicMock()),
        ):
            result = await compute_ab_test_winners({"settings": settings, "session_factory": sf})
        assert result["processed"] == 0
        assert result["settled"] == 0
