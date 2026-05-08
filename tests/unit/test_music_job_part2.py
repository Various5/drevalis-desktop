"""Tests for `workers/jobs/music.py` — happy + error paths after the
existing safety branches.

The first test file pinned: episode missing + no active server.
This file covers the actual generation flow:

* Happy path — prompt queued, history polled, audio downloaded,
  bytes written to ``episodes/{id}/music/{mood}_{seed}.mp3``.
* Workflow error from ComfyUI → returns structured error string.
* Missing audio output (workflow done but no audio produced) →
  returns "produced no audio output" error.
* Polling timeout → returns timeout error.
* `client.close()` always runs in `finally` — even when polling
  errors out.
* `ffmpeg.get_duration` failure swallowed (returned 0.0 duration
  rather than crashing the job).
* `decrypt_value` failure on api_key swallowed (the worker still
  attempts the request without a key).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from drevalis.workers.jobs.music import generate_episode_music


def _ctx(db: Any) -> dict[str, Any]:
    return {"db": db}


def _server(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "url": "http://comfy.test",
        "api_key_encrypted": None,
        "is_active": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _settings(tmp_path: Path) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    s.ffmpeg_path = "ffmpeg"
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    return s


# ── Happy path ─────────────────────────────────────────────────────


class TestMusicGenerationHappy:
    async def test_writes_audio_and_returns_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No-op asyncio.sleep so the polling loop doesn't actually wait.
        async def _no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        db = AsyncMock()
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        srv_repo = MagicMock()
        srv_repo.get_active_servers = AsyncMock(return_value=[_server()])

        client = MagicMock()
        client.queue_prompt = AsyncMock(return_value="prompt-1")
        # First poll returns None, second returns a finished history.
        history_payload: dict[str, Any] = {
            "status": {"status_str": "success"},
            "outputs": {
                "12": {
                    "audio": [
                        {
                            "filename": "audio.flac",
                            "subfolder": "",
                            "type": "output",
                        }
                    ]
                }
            },
        }
        client.get_history = AsyncMock(side_effect=[None, history_payload])
        client.download_image = AsyncMock(return_value=b"\x00\x01\x02fake-audio")
        client.close = AsyncMock()

        # ffmpeg.get_duration succeeds.
        ffmpeg = MagicMock()
        ffmpeg.get_duration = AsyncMock(return_value=42.0)

        ep_id = uuid4()

        with (
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=srv_repo,
            ),
            patch(
                "drevalis.services.comfyui.ComfyUIClient",
                return_value=client,
            ),
            patch(
                "drevalis.core.config.Settings",
                return_value=_settings(tmp_path),
            ),
            patch(
                "drevalis.services.ffmpeg.FFmpegService",
                return_value=ffmpeg,
            ),
        ):
            out = await generate_episode_music(_ctx(db), str(ep_id), "epic", 30.0)

        assert out["mood"] == "epic"
        assert out["duration"] == 42.0
        assert out["path"].startswith(f"episodes/{ep_id}/music/")
        assert out["filename"].startswith("epic_")
        # File on disk has the bytes.
        target = tmp_path / out["path"]
        assert target.exists()
        assert target.read_bytes() == b"\x00\x01\x02fake-audio"
        # Pin: client closed in finally even on success.
        client.close.assert_awaited_once()

    async def test_ffmpeg_duration_failure_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        db = AsyncMock()
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        srv_repo = MagicMock()
        srv_repo.get_active_servers = AsyncMock(return_value=[_server()])

        client = MagicMock()
        client.queue_prompt = AsyncMock(return_value="p1")
        client.get_history = AsyncMock(
            return_value={
                "status": {},
                "outputs": {
                    "9": {
                        "audio": [
                            {
                                "filename": "x.flac",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                },
            }
        )
        client.download_image = AsyncMock(return_value=b"a")
        client.close = AsyncMock()

        ffmpeg = MagicMock()
        ffmpeg.get_duration = AsyncMock(side_effect=ConnectionError("ffmpeg"))

        with (
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=srv_repo,
            ),
            patch(
                "drevalis.services.comfyui.ComfyUIClient",
                return_value=client,
            ),
            patch(
                "drevalis.core.config.Settings",
                return_value=_settings(tmp_path),
            ),
            patch(
                "drevalis.services.ffmpeg.FFmpegService",
                return_value=ffmpeg,
            ),
        ):
            out = await generate_episode_music(_ctx(db), str(uuid4()), "calm", 10.0)
        # Pin: duration falls back to 0.0 instead of raising.
        assert out["duration"] == 0.0


# ── Error paths ───────────────────────────────────────────────────


class TestMusicGenerationErrors:
    async def test_api_key_decrypt_failure_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pin: decrypt failure on the ComfyUI api_key is logged but
        # the worker continues with no key (some ComfyUI deploys
        # don't require auth).
        async def _no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        db = AsyncMock()
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        srv_repo = MagicMock()
        srv_repo.get_active_servers = AsyncMock(return_value=[_server(api_key_encrypted=b"opaque")])

        client = MagicMock()
        client.queue_prompt = AsyncMock(return_value="p1")
        client.get_history = AsyncMock(
            return_value={
                "status": {},
                "outputs": {
                    "9": {
                        "audio": [
                            {
                                "filename": "x.flac",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                },
            }
        )
        client.download_image = AsyncMock(return_value=b"a")
        client.close = AsyncMock()

        ffmpeg = MagicMock()
        ffmpeg.get_duration = AsyncMock(return_value=10.0)

        with (
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=srv_repo,
            ),
            patch(
                "drevalis.services.comfyui.ComfyUIClient",
                return_value=client,
            ),
            patch(
                "drevalis.core.config.Settings",
                return_value=_settings(tmp_path),
            ),
            patch(
                "drevalis.services.ffmpeg.FFmpegService",
                return_value=ffmpeg,
            ),
            patch(
                "drevalis.core.security.decrypt_value",
                side_effect=ValueError("decrypt failed"),
            ),
        ):
            out = await generate_episode_music(_ctx(db), str(uuid4()), "epic", 10.0)
        # Job still completes despite decrypt failure.
        assert "error" not in out
        assert out["filename"].startswith("epic_")

    async def test_workflow_error_returns_structured_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        db = AsyncMock()
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        srv_repo = MagicMock()
        srv_repo.get_active_servers = AsyncMock(return_value=[_server()])

        client = MagicMock()
        client.queue_prompt = AsyncMock(return_value="p1")
        # ComfyUI completed with workflow error.
        client.get_history = AsyncMock(
            return_value={
                "status": {
                    "status_str": "error",
                    "messages": [
                        (
                            "execution_error",
                            {
                                "node_type": "AceStepSampler",
                                "exception_message": "OOM",
                            },
                        )
                    ],
                },
            }
        )
        client.close = AsyncMock()

        with (
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=srv_repo,
            ),
            patch(
                "drevalis.services.comfyui.ComfyUIClient",
                return_value=client,
            ),
            patch(
                "drevalis.core.config.Settings",
                return_value=_settings(tmp_path),
            ),
        ):
            out = await generate_episode_music(_ctx(db), str(uuid4()), "epic", 10.0)
        assert "error" in out
        # Pin: error string surfaces both the node type and exception
        # message so the operator can see exactly which workflow node
        # failed.
        assert "AceStepSampler" in out["error"]
        assert "OOM" in out["error"]
        # Cleanup ran even on workflow error.
        client.close.assert_awaited_once()

    async def test_missing_audio_output_returns_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        db = AsyncMock()
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        srv_repo = MagicMock()
        srv_repo.get_active_servers = AsyncMock(return_value=[_server()])

        client = MagicMock()
        client.queue_prompt = AsyncMock(return_value="p1")
        # Workflow done but outputs contain no audio entry.
        client.get_history = AsyncMock(
            return_value={"status": {}, "outputs": {"5": {"images": []}}}
        )
        client.close = AsyncMock()

        with (
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=srv_repo,
            ),
            patch(
                "drevalis.services.comfyui.ComfyUIClient",
                return_value=client,
            ),
            patch(
                "drevalis.core.config.Settings",
                return_value=_settings(tmp_path),
            ),
        ):
            out = await generate_episode_music(_ctx(db), str(uuid4()), "epic", 10.0)
        assert "error" in out
        assert "no audio output" in out["error"]
        client.close.assert_awaited_once()

    async def test_polling_timeout_returns_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pin: when get_history NEVER resolves (returns None forever),
        # the poll loop bails after 600s of accumulated delay and
        # returns a structured timeout error.
        async def _no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        db = AsyncMock()
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        srv_repo = MagicMock()
        srv_repo.get_active_servers = AsyncMock(return_value=[_server()])

        client = MagicMock()
        client.queue_prompt = AsyncMock(return_value="p1")
        client.get_history = AsyncMock(return_value=None)
        client.close = AsyncMock()

        with (
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
            patch(
                "drevalis.repositories.comfyui.ComfyUIServerRepository",
                return_value=srv_repo,
            ),
            patch(
                "drevalis.services.comfyui.ComfyUIClient",
                return_value=client,
            ),
            patch(
                "drevalis.core.config.Settings",
                return_value=_settings(tmp_path),
            ),
        ):
            out = await generate_episode_music(_ctx(db), str(uuid4()), "epic", 10.0)
        assert "error" in out
        assert "timed out" in out["error"]
        client.close.assert_awaited_once()
