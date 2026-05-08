"""Tests for the daily scheduled-post orphan-prune job
(workers/jobs/prune_scheduled_posts.py).

Without this prune, deleting an episode/audiobook leaves its
scheduled-post rows behind (no FK on the polymorphic content_id),
and the publish cron keeps trying to upload non-existent content.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from drevalis.workers.jobs.prune_scheduled_posts import (
    prune_orphaned_scheduled_posts,
)


def _make_session_factory(session_mock: Any) -> Any:
    """Build an async-context-manager-style session factory."""

    class _SessionFactory:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return session_mock

        async def __aexit__(self, *_args: Any) -> None:
            return None

    return _SessionFactory()


class TestPruneOrphanedScheduledPosts:
    async def test_calls_repo_prune_orphaned(self) -> None:
        # The job is a thin wrapper around
        # ``ScheduledPostRepository.prune_orphaned``. Pin that the
        # repo method is invoked exactly once.
        session = AsyncMock()
        session_factory = _make_session_factory(session)

        repo_mock = AsyncMock()
        repo_mock.prune_orphaned = AsyncMock(return_value=0)

        with patch(
            "drevalis.repositories.scheduled_post.ScheduledPostRepository",
            return_value=repo_mock,
        ) as ctor:
            result = await prune_orphaned_scheduled_posts({"session_factory": session_factory})

        # Constructor called once with the session.
        assert ctor.call_count == 1
        # prune_orphaned called once.
        repo_mock.prune_orphaned.assert_awaited_once()
        # Result echoes the deleted count.
        assert result == {"deleted": 0}

    async def test_returns_deleted_count(self) -> None:
        session = AsyncMock()
        session_factory = _make_session_factory(session)
        repo_mock = AsyncMock()
        repo_mock.prune_orphaned = AsyncMock(return_value=7)

        with patch(
            "drevalis.repositories.scheduled_post.ScheduledPostRepository",
            return_value=repo_mock,
        ):
            result = await prune_orphaned_scheduled_posts({"session_factory": session_factory})

        assert result == {"deleted": 7}

    async def test_session_factory_used_as_async_context(self) -> None:
        # Pin that the job opens a fresh session via the factory's
        # async-context interface (matches arq's ctx['session_factory']).
        enter_called = False
        exit_called = False

        class _SF:
            def __call__(self) -> Any:
                return self

            async def __aenter__(self) -> Any:
                nonlocal enter_called
                enter_called = True
                return AsyncMock()

            async def __aexit__(self, *_args: Any) -> None:
                nonlocal exit_called
                exit_called = True
                return None

        repo_mock = AsyncMock()
        repo_mock.prune_orphaned = AsyncMock(return_value=0)

        with patch(
            "drevalis.repositories.scheduled_post.ScheduledPostRepository",
            return_value=repo_mock,
        ):
            await prune_orphaned_scheduled_posts({"session_factory": _SF()})

        assert enter_called is True
        assert exit_called is True

    async def test_zero_deleted_takes_debug_branch(self) -> None:
        # Zero-deleted log line is at DEBUG (vs INFO when something
        # was actually pruned). Pin via repo invocation only — log
        # level branch is exercised but isn't asserted here directly.
        session = AsyncMock()
        session_factory = _make_session_factory(session)
        repo_mock = AsyncMock()
        repo_mock.prune_orphaned = AsyncMock(return_value=0)

        with patch(
            "drevalis.repositories.scheduled_post.ScheduledPostRepository",
            return_value=repo_mock,
        ):
            result = await prune_orphaned_scheduled_posts({"session_factory": session_factory})
        assert result == {"deleted": 0}

    async def test_nonzero_deleted_takes_info_branch(self) -> None:
        session = AsyncMock()
        session_factory = _make_session_factory(session)
        repo_mock = AsyncMock()
        repo_mock.prune_orphaned = AsyncMock(return_value=42)

        with patch(
            "drevalis.repositories.scheduled_post.ScheduledPostRepository",
            return_value=repo_mock,
        ):
            result = await prune_orphaned_scheduled_posts({"session_factory": session_factory})
        assert result == {"deleted": 42}
