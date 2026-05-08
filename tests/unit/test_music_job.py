"""Tests for the AceStep music generation arq job
(``workers/jobs/music.py``).

Heavy worker that drives ComfyUI for up to 10 minutes. Unit tests
pin the safety branches:

* Episode missing → returns error
* No active ComfyUI server → returns error
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.music import generate_episode_music


def _make_settings() -> Any:
    s = MagicMock()
    s.encryption_key = "k"
    s.storage_base_path = MagicMock()
    return s


def _patch_module(*, episode: Any, servers: list[Any]) -> Any:
    ep_repo = MagicMock()
    ep_repo.get_by_id = AsyncMock(return_value=episode)
    server_repo = MagicMock()
    server_repo.get_active_servers = AsyncMock(return_value=servers)

    from contextlib import ExitStack

    es = ExitStack()
    es.enter_context(patch("drevalis.core.config.Settings", return_value=_make_settings()))
    es.enter_context(patch("drevalis.repositories.episode.EpisodeRepository", return_value=ep_repo))
    es.enter_context(
        patch(
            "drevalis.repositories.comfyui.ComfyUIServerRepository",
            return_value=server_repo,
        )
    )
    return es


# ── Episode missing ─────────────────────────────────────────────────


class TestEpisodeMissing:
    async def test_returns_error_when_episode_not_found(self) -> None:
        with _patch_module(episode=None, servers=[]):
            result = await generate_episode_music(
                {"db": AsyncMock()},
                str(uuid4()),
                "epic",
                30.0,
            )
        assert "error" in result
        assert "not found" in result["error"]


# ── No ComfyUI server ───────────────────────────────────────────────


class TestNoComfyuiServer:
    async def test_returns_error_when_no_active_server(self) -> None:
        episode = MagicMock()
        episode.id = uuid4()
        with _patch_module(episode=episode, servers=[]):
            result = await generate_episode_music(
                {"db": AsyncMock()},
                str(episode.id),
                "epic",
                30.0,
            )
        assert "error" in result
        assert "ComfyUI" in result["error"] or "comfyui" in result["error"].lower()
