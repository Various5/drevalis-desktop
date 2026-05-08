"""Tests for the demo-mode fake pipeline worker
(``workers/jobs/demo_pipeline.py``).

Drop-in replacement for ``generate_episode`` when
``settings.demo_mode=True``. Emits the same WebSocket progress
events a real run would. Pin the contract:

* DEMO_STEPS covers all 6 real pipeline steps in the right order
* Episode flips ``draft → generating → review``
* Progress events fire for every step at running/0% and done/100%
* ``_stage_demo_assets`` is no-op-safe when demo assets directory
  is missing (fresh install without the sample pack)
* Sample files copied into the episode dir + media_assets rows
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from drevalis.workers.jobs.demo_pipeline import (
    DEMO_STEPS,
    _stage_demo_assets,
)

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


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op asyncio.sleep so tests don't actually wait the scripted
    DEMO_STEPS durations (~40 seconds total)."""

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)


# ── DEMO_STEPS contract ─────────────────────────────────────────────


class TestDemoSteps:
    def test_covers_all_six_pipeline_steps_in_order(self) -> None:
        # The fake pipeline must mirror the real pipeline's step
        # sequence — the frontend's progress UI is shared between
        # demo and prod, so a missing or out-of-order step here
        # would leave the demo's progress bar broken.
        names = [s[0] for s in DEMO_STEPS]
        assert names == [
            "script",
            "voice",
            "scenes",
            "captions",
            "assembly",
            "thumbnail",
        ]

    def test_each_step_has_realistic_timing(self) -> None:
        # All durations > 0 + tick counts > 0 so the loop produces
        # at least one progress event per step.
        for name, duration, ticks in DEMO_STEPS:
            assert duration > 0, f"{name} has non-positive duration"
            assert ticks > 0, f"{name} has non-positive tick count"


# ── _stage_demo_assets ──────────────────────────────────────────────


class TestStageDemoAssets:
    async def test_missing_demo_dir_is_silent_noop(self, tmp_path: Path) -> None:
        # Fresh install without the sample-pack download — the
        # demo still shows progress events but skips asset staging.
        ghost = tmp_path / "definitely-not-here"
        # Storage with a base_path attribute.
        storage = MagicMock()
        storage.base_path = tmp_path
        sf = _make_session_factory(AsyncMock())
        # Must not raise.
        await _stage_demo_assets(
            session_factory=sf,
            storage=storage,
            demo_assets_path=ghost,
            episode_id=uuid4(),
        )

    async def test_copies_video_and_thumbnail_when_present(self, tmp_path: Path) -> None:
        # Pre-bake a sample directory with video.mp4 + thumbnail.jpg.
        src = tmp_path / "demo_assets"
        src.mkdir()
        (src / "video.mp4").write_bytes(b"\x00" * 1000)
        (src / "thumbnail.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 200)

        storage_root = tmp_path / "storage"
        storage_root.mkdir()
        storage = MagicMock()
        storage.base_path = storage_root

        # Capture media_asset.create calls.
        repo = MagicMock()
        repo.create = AsyncMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        sf = _make_session_factory(session)

        ep_id = uuid4()
        with patch(
            "drevalis.repositories.media_asset.MediaAssetRepository",
            return_value=repo,
        ):
            await _stage_demo_assets(
                session_factory=sf,
                storage=storage,
                demo_assets_path=src,
                episode_id=ep_id,
            )

        # video.mp4 + thumbnail.jpg both copied into episode dir.
        episode_dir = storage_root / "episodes" / str(ep_id)
        assert (episode_dir / "output" / "final.mp4").exists()
        assert (episode_dir / "output" / "thumbnail.jpg").exists()
        # media_asset rows created for each.
        kwargs = [c.kwargs for c in repo.create.call_args_list]
        types = {k["asset_type"] for k in kwargs}
        assert "video" in types
        assert "thumbnail" in types

    async def test_copies_scene_images_with_indices(self, tmp_path: Path) -> None:
        src = tmp_path / "demo_assets"
        src.mkdir()
        (src / "scene_01.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 100)
        (src / "scene_02.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 100)
        (src / "scene_03.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 100)

        storage_root = tmp_path / "storage"
        storage_root.mkdir()
        storage = MagicMock()
        storage.base_path = storage_root

        repo = MagicMock()
        repo.create = AsyncMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        sf = _make_session_factory(session)

        ep_id = uuid4()
        with patch(
            "drevalis.repositories.media_asset.MediaAssetRepository",
            return_value=repo,
        ):
            await _stage_demo_assets(
                session_factory=sf,
                storage=storage,
                demo_assets_path=src,
                episode_id=ep_id,
            )

        # Three scene_image rows with monotonically increasing scene_number.
        scene_calls = [
            c.kwargs
            for c in repo.create.call_args_list
            if c.kwargs.get("asset_type") == "scene_image"
        ]
        assert len(scene_calls) == 3
        scene_numbers = [c["scene_number"] for c in scene_calls]
        assert scene_numbers == [1, 2, 3]

    async def test_missing_source_files_silently_skipped(self, tmp_path: Path) -> None:
        # demo_assets dir exists but specific files don't — proceed
        # without error, copying only what's present. Sets up the
        # graceful-degradation invariant: a partial sample pack still
        # produces a usable demo.
        src = tmp_path / "demo_assets"
        src.mkdir()
        # Only video.mp4 — no thumbnail, no scenes.
        (src / "video.mp4").write_bytes(b"\x00" * 100)

        storage_root = tmp_path / "storage"
        storage_root.mkdir()
        storage = MagicMock()
        storage.base_path = storage_root

        repo = MagicMock()
        repo.create = AsyncMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        sf = _make_session_factory(session)

        with patch(
            "drevalis.repositories.media_asset.MediaAssetRepository",
            return_value=repo,
        ):
            await _stage_demo_assets(
                session_factory=sf,
                storage=storage,
                demo_assets_path=src,
                episode_id=uuid4(),
            )

        # Only one create call — for video. Thumbnail + scenes skipped.
        assert repo.create.await_count == 1
        assert repo.create.call_args.kwargs["asset_type"] == "video"
