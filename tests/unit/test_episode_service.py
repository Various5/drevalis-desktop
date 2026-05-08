"""Tests for EpisodeService — domain logic extracted from route handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from drevalis.services.episode import (
    EpisodeInvalidStatusError,
    EpisodeNoScriptError,
    EpisodeNotFoundError,
    EpisodeService,
)


@pytest.fixture
def mock_db():
    """Mock async database session."""
    return AsyncMock()


@pytest.fixture
def service(mock_db):
    """EpisodeService with mocked DB."""
    return EpisodeService(mock_db)


# ── get_or_raise ──────────────────────────────────────────────────────


class TestGetOrRaise:
    async def test_returns_episode_when_found(self, service):
        episode_id = uuid4()
        mock_episode = MagicMock()
        mock_episode.id = episode_id
        service._ep_repo.get_by_id = AsyncMock(return_value=mock_episode)

        result = await service.get_or_raise(episode_id)

        assert result is mock_episode
        service._ep_repo.get_by_id.assert_awaited_once_with(episode_id)

    async def test_raises_not_found_when_missing(self, service):
        episode_id = uuid4()
        service._ep_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(EpisodeNotFoundError) as exc_info:
            await service.get_or_raise(episode_id)

        assert exc_info.value.episode_id == episode_id
        assert str(episode_id) in str(exc_info.value)


# ── get_with_script_or_raise ──────────────────────────────────────────


class TestGetWithScriptOrRaise:
    async def test_returns_episode_and_script_when_both_exist(self, service):
        episode_id = uuid4()
        mock_episode = MagicMock()
        mock_episode.id = episode_id
        mock_episode.script = {
            "title": "Test",
            "hook": "",
            "scenes": [
                {
                    "scene_number": 1,
                    "narration": "Hello world",
                    "visual_prompt": "test",
                    "duration_seconds": 10,
                    "keywords": ["test"],
                }
            ],
            "outro": "",
        }
        service._ep_repo.get_by_id = AsyncMock(return_value=mock_episode)

        episode, script = await service.get_with_script_or_raise(episode_id)

        assert episode is mock_episode
        assert script.title == "Test"
        assert len(script.scenes) == 1

    async def test_raises_no_script_when_script_is_none(self, service):
        episode_id = uuid4()
        mock_episode = MagicMock()
        mock_episode.id = episode_id
        mock_episode.script = None
        service._ep_repo.get_by_id = AsyncMock(return_value=mock_episode)

        with pytest.raises(EpisodeNoScriptError) as exc_info:
            await service.get_with_script_or_raise(episode_id)

        assert exc_info.value.episode_id == episode_id

    async def test_raises_not_found_when_episode_missing(self, service):
        episode_id = uuid4()
        service._ep_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(EpisodeNotFoundError):
            await service.get_with_script_or_raise(episode_id)


# ── require_status ────────────────────────────────────────────────────


class TestRequireStatus:
    def test_passes_when_status_allowed(self, service):
        episode = MagicMock()
        episode.status = "draft"

        # Should not raise
        service.require_status(episode, ["draft", "failed"])

    def test_raises_when_status_not_allowed(self, service):
        episode = MagicMock()
        episode.id = uuid4()
        episode.status = "generating"

        with pytest.raises(EpisodeInvalidStatusError) as exc_info:
            service.require_status(episode, ["draft", "failed"])

        assert exc_info.value.current_status == "generating"
        assert exc_info.value.allowed == ["draft", "failed"]


# ── create_reassembly_jobs ────────────────────────────────────────────


class TestCreateReassemblyJobs:
    async def test_creates_default_steps(self, service):
        episode_id = uuid4()
        mock_job = MagicMock()
        service._job_repo.create = AsyncMock(return_value=mock_job)

        jobs = await service.create_reassembly_jobs(episode_id)

        assert len(jobs) == 3
        calls = service._job_repo.create.call_args_list
        steps = [c.kwargs["step"] for c in calls]
        assert steps == ["captions", "assembly", "thumbnail"]

    async def test_creates_custom_steps(self, service):
        episode_id = uuid4()
        mock_job = MagicMock()
        service._job_repo.create = AsyncMock(return_value=mock_job)

        jobs = await service.create_reassembly_jobs(episode_id, steps=["voice", "scenes"])

        assert len(jobs) == 2
        calls = service._job_repo.create.call_args_list
        steps = [c.kwargs["step"] for c in calls]
        assert steps == ["voice", "scenes"]
