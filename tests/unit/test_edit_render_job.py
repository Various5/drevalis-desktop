"""Tests for the render-from-edit-session worker
(``workers/jobs/edit_render.py``).

Heavy worker that drives FFmpeg from a JSON timeline. Full coverage
requires a working ffmpeg + storage + DB. The unit tests pin the
early-exit branches that handle missing inputs:

* No edit session for episode → no_session
* Edit session exists but episode row missing → episode_missing
* Timeline has no video tracks → empty_timeline
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.edit_render import render_from_edit

# ── Helpers ──────────────────────────────────────────────────────────


def _make_session_factory(session_mock: Any) -> Any:
    class _SF:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return session_mock

        async def __aexit__(self, *_a: Any) -> None:
            return None

    return _SF()


def _make_settings() -> Any:
    return MagicMock()


def _ctx(*, session_factory: Any) -> dict[str, Any]:
    return {
        "session_factory": session_factory,
        "storage": AsyncMock(),
        "ffmpeg_service": AsyncMock(),
    }


def _patch_repos(
    *,
    edit_session: Any,
    episode: Any,
) -> Any:
    """Patch the late-imported repos. Returns an ExitStack of context
    managers that the test enters."""

    edit_repo = MagicMock()
    edit_repo.get_by_episode = AsyncMock(return_value=edit_session)
    ep_repo = MagicMock()
    ep_repo.get_by_id = AsyncMock(return_value=episode)
    asset_repo = MagicMock()

    from contextlib import ExitStack

    es = ExitStack()
    es.enter_context(
        patch(
            "drevalis.repositories.video_edit_session.VideoEditSessionRepository",
            return_value=edit_repo,
        )
    )
    es.enter_context(
        patch(
            "drevalis.repositories.episode.EpisodeRepository",
            return_value=ep_repo,
        )
    )
    es.enter_context(
        patch(
            "drevalis.repositories.media_asset.MediaAssetRepository",
            return_value=asset_repo,
        )
    )
    es.enter_context(patch("drevalis.core.deps.get_settings", return_value=_make_settings()))
    return es


# ── Early-exit: no edit session ─────────────────────────────────────


class TestNoEditSession:
    async def test_returns_no_session_when_edit_repo_returns_none(self) -> None:
        # The episode has never been opened in the editor → no
        # video_edit_sessions row → return ``no_session`` so the
        # caller knows nothing to render.
        session = AsyncMock()
        session.commit = AsyncMock()
        sf = _make_session_factory(session)

        with _patch_repos(edit_session=None, episode=MagicMock()):
            result = await render_from_edit(_ctx(session_factory=sf), str(uuid4()))
        assert result == {"status": "no_session"}


# ── Early-exit: episode missing ─────────────────────────────────────


class TestEpisodeMissing:
    async def test_returns_episode_missing_when_episode_repo_returns_none(
        self,
    ) -> None:
        # Edit session exists but the episode was deleted in the meantime.
        # Don't render — return early.
        edit_session = MagicMock()
        edit_session.timeline = {"tracks": []}

        session = AsyncMock()
        sf = _make_session_factory(session)

        with _patch_repos(edit_session=edit_session, episode=None):
            result = await render_from_edit(_ctx(session_factory=sf), str(uuid4()))
        assert result == {"status": "episode_missing"}


# ── Early-exit: empty timeline ──────────────────────────────────────


class TestEmptyTimeline:
    async def test_returns_empty_when_no_tracks(self) -> None:
        # Edit session exists, episode exists, but timeline.tracks is
        # empty (user opened the editor but never added a clip).
        edit_session = MagicMock()
        edit_session.timeline = {"tracks": []}

        session = AsyncMock()
        sf = _make_session_factory(session)

        with _patch_repos(edit_session=edit_session, episode=MagicMock()):
            result = await render_from_edit(_ctx(session_factory=sf), str(uuid4()))
        assert result == {"status": "empty_timeline"}

    async def test_returns_empty_when_video_track_has_no_clips(self) -> None:
        # The video track exists but has zero clips — same outcome.
        edit_session = MagicMock()
        edit_session.timeline = {"tracks": [{"id": "video", "clips": []}]}

        session = AsyncMock()
        sf = _make_session_factory(session)

        with _patch_repos(edit_session=edit_session, episode=MagicMock()):
            result = await render_from_edit(_ctx(session_factory=sf), str(uuid4()))
        assert result == {"status": "empty_timeline"}

    async def test_returns_empty_when_no_video_track(self) -> None:
        # Timeline has audio + caption tracks but no video. Without
        # video clips there's nothing to assemble.
        edit_session = MagicMock()
        edit_session.timeline = {
            "tracks": [
                {"id": "audio", "clips": [{"asset_path": "x.wav"}]},
                {"id": "captions", "clips": []},
            ]
        }

        session = AsyncMock()
        sf = _make_session_factory(session)

        with _patch_repos(edit_session=edit_session, episode=MagicMock()):
            result = await render_from_edit(_ctx(session_factory=sf), str(uuid4()))
        assert result == {"status": "empty_timeline"}

    async def test_returns_empty_when_timeline_is_none(self) -> None:
        # ``edit_session.timeline = None`` — the schema allows it on
        # freshly-created rows. Treat as empty.
        edit_session = MagicMock()
        edit_session.timeline = None

        session = AsyncMock()
        sf = _make_session_factory(session)

        with _patch_repos(edit_session=edit_session, episode=MagicMock()):
            result = await render_from_edit(_ctx(session_factory=sf), str(uuid4()))
        assert result == {"status": "empty_timeline"}
