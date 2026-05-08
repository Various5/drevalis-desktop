"""Tests for ``render_from_edit`` — full orchestration happy paths.

The earlier suite pinned the early-exit branches (missing session /
episode / empty timeline). This file covers the orchestration body:

* Trim each clip to its (in_s, out_s) window via FFmpegService.
* Skip clips with missing `asset_path` or files that don't exist.
* Skip trimming when out_s <= in_s (image / zero-duration) — copy as-is.
* All clips skipped → `empty_output` status.
* Concat trimmed clips + run optional overlay/envelope passes.
* Proxy mode writes 480p preview.mp4 with a faster preset.
* Final render registers MediaAsset row + updates last_rendered_at.
* Proxy render uses asset_type="video_proxy" (NOT "video") + does NOT
  bump last_rendered_at.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from drevalis.workers.jobs.edit_render import render_from_edit


def _settings(tmp_path: Path) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    s.ffmpeg_path = "ffmpeg"
    return s


def _ctx_with(session: Any, tmp_path: Path) -> dict[str, Any]:
    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    storage = MagicMock()
    storage.base_path = tmp_path

    async def _get_episode_path(_id: Any) -> Path:
        ep_dir = tmp_path / "episodes" / str(_id)
        ep_dir.mkdir(parents=True, exist_ok=True)
        return ep_dir

    storage.get_episode_path = _get_episode_path

    ffmpeg = MagicMock()

    async def _trim(src: Path, dst: Path, **_kwargs: Any) -> None:
        dst.write_bytes(b"trimmed")

    async def _concat(srcs: list[Path], dst: Path) -> None:
        dst.write_bytes(b"concat")

    ffmpeg.trim_video = AsyncMock(side_effect=_trim)
    ffmpeg.concat_videos = AsyncMock(side_effect=_concat)

    return {
        "session_factory": _sf,
        "storage": storage,
        "ffmpeg_service": ffmpeg,
    }


def _patch_repos(*, edit_session: Any, episode: Any, asset_repo: Any) -> Any:
    edit_repo = MagicMock()
    edit_repo.get_by_episode = AsyncMock(return_value=edit_session)
    edit_repo.update = AsyncMock()
    ep_repo = MagicMock()
    ep_repo.get_by_id = AsyncMock(return_value=episode)

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
    return es, edit_repo


def _settings_patch(tmp_path: Path) -> Any:
    return patch(
        "drevalis.core.deps.get_settings",
        return_value=_settings(tmp_path),
    )


def _make_session() -> Any:
    s = AsyncMock()
    s.commit = AsyncMock()
    return s


# ── Happy path: trim → concat → write final_edit.mp4 ─────────────


class TestRenderFromEditHappyPath:
    async def test_full_render_writes_video_asset(self, tmp_path: Path) -> None:
        # Stage 2 source clips on disk so the trim loop has real files
        # to read (ffmpeg.trim_video is stubbed but the existence
        # check fires first).
        src_a = tmp_path / "uploads" / "a.mp4"
        src_a.parent.mkdir(parents=True)
        src_a.write_bytes(b"\x00")
        src_b = tmp_path / "uploads" / "b.mp4"
        src_b.write_bytes(b"\x00")

        timeline = {
            "tracks": [
                {
                    "id": "video",
                    "clips": [
                        {
                            "asset_path": "uploads/a.mp4",
                            "in_s": 1.0,
                            "out_s": 5.0,
                        },
                        {
                            "asset_path": "uploads/b.mp4",
                            "in_s": 0.0,
                            "out_s": 3.0,
                        },
                    ],
                }
            ]
        }

        edit_session = SimpleNamespace(id=uuid4(), timeline=timeline, last_rendered_at=None)
        episode = SimpleNamespace(id=uuid4())
        asset_repo = MagicMock()
        asset_repo.create = AsyncMock()

        ctx = _ctx_with(_make_session(), tmp_path)
        es, edit_repo = _patch_repos(
            edit_session=edit_session, episode=episode, asset_repo=asset_repo
        )

        with es, _settings_patch(tmp_path):
            out = await render_from_edit(ctx, str(episode.id))

        assert out["status"] == "done"
        assert out["output"].endswith("final_edit.mp4")
        # Both clips trimmed.
        assert ctx["ffmpeg_service"].trim_video.await_count == 2
        # Concat ran once.
        ctx["ffmpeg_service"].concat_videos.assert_awaited_once()
        # Final video asset registered.
        asset_repo.create.assert_awaited_once()
        ckwargs = asset_repo.create.call_args.kwargs
        assert ckwargs["asset_type"] == "video"
        # last_rendered_at updated on the edit session.
        edit_repo.update.assert_awaited_once()
        update_kwargs = edit_repo.update.call_args.kwargs
        assert "last_rendered_at" in update_kwargs

    async def test_clip_with_missing_asset_path_skipped(self, tmp_path: Path) -> None:
        # Pin: clip with no `asset_path` skipped without crashing.
        src = tmp_path / "uploads" / "good.mp4"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"\x00")

        timeline = {
            "tracks": [
                {
                    "id": "video",
                    "clips": [
                        {"in_s": 0.0, "out_s": 2.0},  # no asset_path
                        {
                            "asset_path": "uploads/good.mp4",
                            "in_s": 0.0,
                            "out_s": 2.0,
                        },
                    ],
                }
            ]
        }
        edit_session = SimpleNamespace(id=uuid4(), timeline=timeline, last_rendered_at=None)
        episode = SimpleNamespace(id=uuid4())
        asset_repo = MagicMock()
        asset_repo.create = AsyncMock()

        ctx = _ctx_with(_make_session(), tmp_path)
        es, _ = _patch_repos(edit_session=edit_session, episode=episode, asset_repo=asset_repo)
        with es, _settings_patch(tmp_path):
            out = await render_from_edit(ctx, str(episode.id))
        assert out["status"] == "done"
        # Only ONE trim ran (the good clip).
        assert ctx["ffmpeg_service"].trim_video.await_count == 1

    async def test_clip_source_missing_on_disk_skipped(self, tmp_path: Path) -> None:
        # Asset path provided but file doesn't exist on disk →
        # skipped (post-restore where the database row outlived the
        # file).
        timeline = {
            "tracks": [
                {
                    "id": "video",
                    "clips": [
                        {
                            "asset_path": "uploads/missing.mp4",
                            "in_s": 0.0,
                            "out_s": 2.0,
                        },
                    ],
                }
            ]
        }
        edit_session = SimpleNamespace(id=uuid4(), timeline=timeline, last_rendered_at=None)
        episode = SimpleNamespace(id=uuid4())
        asset_repo = MagicMock()
        ctx = _ctx_with(_make_session(), tmp_path)
        es, _ = _patch_repos(edit_session=edit_session, episode=episode, asset_repo=asset_repo)
        with es, _settings_patch(tmp_path):
            out = await render_from_edit(ctx, str(episode.id))
        # All clips skipped → empty_output.
        assert out["status"] == "empty_output"
        assert ctx["ffmpeg_service"].trim_video.await_count == 0

    async def test_zero_duration_clip_copied_not_trimmed(self, tmp_path: Path) -> None:
        # Pin: when out_s <= in_s (zero-duration / image clip), the
        # source is used as-is — ffmpeg concat needs a real video so
        # we don't trim it but we DO include it in the trimmed list.
        src = tmp_path / "uploads" / "img.mp4"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"\x00")

        timeline = {
            "tracks": [
                {
                    "id": "video",
                    "clips": [
                        {
                            "asset_path": "uploads/img.mp4",
                            "in_s": 5.0,
                            "out_s": 5.0,
                        },
                    ],
                }
            ]
        }
        edit_session = SimpleNamespace(id=uuid4(), timeline=timeline, last_rendered_at=None)
        episode = SimpleNamespace(id=uuid4())
        asset_repo = MagicMock()
        asset_repo.create = AsyncMock()
        ctx = _ctx_with(_make_session(), tmp_path)
        es, _ = _patch_repos(edit_session=edit_session, episode=episode, asset_repo=asset_repo)
        with es, _settings_patch(tmp_path):
            out = await render_from_edit(ctx, str(episode.id))
        # No trim for the zero-duration clip; concat still ran.
        assert ctx["ffmpeg_service"].trim_video.await_count == 0
        ctx["ffmpeg_service"].concat_videos.assert_awaited_once()
        assert out["status"] == "done"


# ── Proxy mode ────────────────────────────────────────────────────


class TestProxyMode:
    async def test_proxy_writes_proxy_mp4_with_video_proxy_asset_type(self, tmp_path: Path) -> None:
        # Stage source.
        src = tmp_path / "uploads" / "a.mp4"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"\x00")

        timeline = {
            "tracks": [
                {
                    "id": "video",
                    "clips": [
                        {
                            "asset_path": "uploads/a.mp4",
                            "in_s": 0.0,
                            "out_s": 2.0,
                        },
                    ],
                }
            ]
        }
        edit_session = SimpleNamespace(id=uuid4(), timeline=timeline, last_rendered_at=None)
        episode = SimpleNamespace(id=uuid4())
        asset_repo = MagicMock()
        asset_repo.create = AsyncMock()

        ctx = _ctx_with(_make_session(), tmp_path)
        es, edit_repo = _patch_repos(
            edit_session=edit_session, episode=episode, asset_repo=asset_repo
        )

        # Stub the proxy ffmpeg subprocess so it "succeeds" and writes
        # the proxy.mp4 output file (the route reads its existence).
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))

        async def _fake_exec(*args: Any, **_kwargs: Any) -> Any:
            # Last arg is the proxy output path.
            Path(args[-1]).write_bytes(b"proxy-output")
            return proc

        with es, _settings_patch(tmp_path), patch("asyncio.create_subprocess_exec", _fake_exec):
            out = await render_from_edit(ctx, str(episode.id), proxy=True)

        assert out["status"] == "done"
        assert out["output"].endswith("proxy.mp4")
        # Pin: proxy renders use asset_type="video_proxy" so the UI
        # can pick which to display.
        ckwargs = asset_repo.create.call_args.kwargs
        assert ckwargs["asset_type"] == "video_proxy"
        # Pin: proxy renders DO NOT bump `last_rendered_at` — the
        # editor's "last full render" indicator stays accurate.
        edit_repo.update.assert_not_awaited()

    async def test_proxy_subprocess_failure_raises(self, tmp_path: Path) -> None:
        # Pin: when the proxy ffmpeg invocation returns non-zero, the
        # route raises RuntimeError with the stderr tail. Worker arq
        # retry then kicks in.
        src = tmp_path / "uploads" / "a.mp4"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"\x00")

        timeline = {
            "tracks": [
                {
                    "id": "video",
                    "clips": [
                        {
                            "asset_path": "uploads/a.mp4",
                            "in_s": 0.0,
                            "out_s": 2.0,
                        },
                    ],
                }
            ]
        }
        edit_session = SimpleNamespace(id=uuid4(), timeline=timeline, last_rendered_at=None)
        episode = SimpleNamespace(id=uuid4())
        asset_repo = MagicMock()
        ctx = _ctx_with(_make_session(), tmp_path)
        es, _ = _patch_repos(edit_session=edit_session, episode=episode, asset_repo=asset_repo)

        proc = MagicMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"proxy-error"))

        async def _fake_exec(*_args: Any, **_kwargs: Any) -> Any:
            return proc

        with es, _settings_patch(tmp_path), patch("asyncio.create_subprocess_exec", _fake_exec):
            with pytest.raises(RuntimeError, match="proxy downscale failed"):
                await render_from_edit(ctx, str(episode.id), proxy=True)
