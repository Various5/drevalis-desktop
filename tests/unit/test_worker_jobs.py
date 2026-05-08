"""Smoke tests for new arq worker job functions (music, SEO).

Both jobs import their repositories and Settings inside the function
body, so the patches need to target the original module path
(drevalis.repositories.*) rather than the worker module's namespace.
A test-only stub Settings is patched in too — the real Settings class
requires ENCRYPTION_KEY, which we don't want to depend on per-test.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet


def _stub_settings() -> MagicMock:
    """Return a Settings-shape mock with the fields the worker reads."""
    s = MagicMock()
    s.encryption_key = Fernet.generate_key().decode()
    s.storage_base_path = Path("/tmp/drevalis-test")
    s.ffmpeg_path = "ffmpeg"
    s.lm_studio_base_url = "http://localhost:1234/v1"
    s.lm_studio_default_model = "test-model"
    return s


class TestGenerateEpisodeMusicJob:
    """Tests for workers/jobs/music.py::generate_episode_music."""

    async def test_returns_error_when_episode_not_found(self) -> None:
        from drevalis.workers.jobs.music import generate_episode_music

        mock_db = AsyncMock()
        ctx = {"db": mock_db}

        with (
            patch("drevalis.core.config.Settings", return_value=_stub_settings()),
            patch("drevalis.repositories.episode.EpisodeRepository") as MockRepo,
        ):
            MockRepo.return_value.get_by_id = AsyncMock(return_value=None)
            result = await generate_episode_music(ctx, str(uuid4()), "epic", 30.0)

        assert "error" in result
        assert "not found" in result["error"]

    async def test_returns_error_when_no_comfyui_server(self) -> None:
        from drevalis.workers.jobs.music import generate_episode_music

        mock_db = AsyncMock()
        ctx = {"db": mock_db}
        mock_episode = MagicMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_stub_settings()),
            patch("drevalis.repositories.episode.EpisodeRepository") as MockEpRepo,
            patch("drevalis.repositories.comfyui.ComfyUIServerRepository") as MockServerRepo,
        ):
            MockEpRepo.return_value.get_by_id = AsyncMock(return_value=mock_episode)
            MockServerRepo.return_value.get_active_servers = AsyncMock(return_value=[])
            result = await generate_episode_music(ctx, str(uuid4()), "calm", 60.0)

        assert "error" in result
        assert "ComfyUI" in result["error"]


class TestGenerateSeoAsyncJob:
    """Tests for workers/jobs/seo.py::generate_seo_async."""

    async def test_returns_error_when_episode_not_found(self) -> None:
        from drevalis.workers.jobs.seo import generate_seo_async

        mock_db = AsyncMock()
        ctx = {"db": mock_db}

        with (
            patch("drevalis.core.config.Settings", return_value=_stub_settings()),
            patch("drevalis.repositories.episode.EpisodeRepository") as MockRepo,
        ):
            MockRepo.return_value.get_by_id = AsyncMock(return_value=None)
            result = await generate_seo_async(ctx, str(uuid4()))

        assert "error" in result
        assert "not found" in result["error"]

    async def test_returns_error_when_no_script(self) -> None:
        from drevalis.workers.jobs.seo import generate_seo_async

        mock_db = AsyncMock()
        ctx = {"db": mock_db}
        mock_episode = MagicMock()
        mock_episode.script = None

        with (
            patch("drevalis.core.config.Settings", return_value=_stub_settings()),
            patch("drevalis.repositories.episode.EpisodeRepository") as MockRepo,
        ):
            MockRepo.return_value.get_by_id = AsyncMock(return_value=mock_episode)
            result = await generate_seo_async(ctx, str(uuid4()))

        assert "error" in result
        # Production message is "Episode not found or has no script" — both
        # the not-found and no-script branches share that string today.
        assert "script" in result["error"].lower()
