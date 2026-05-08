"""Safety-branch tests for ``workers/jobs/audiobook.py``.

The audiobook generation job is a 700+ LOC orchestration that drives
TTS, optional ComfyUI image gen, music, ffmpeg mixing, and finally
captions/video assembly. Unit tests pin the early-exit safety branches
that decide whether to proceed at all:

* `generate_audiobook`: missing audiobook → returns failed dict (NOT
  raise — operator can retry from UI).
* `generate_audiobook`: missing voice profile → updates audiobook
  status='failed' with error_message before returning.
* `generate_audiobook`: preflight error → status='failed' with
  joined error message capped at 2000 chars.
* `regenerate_audiobook_chapter`: missing audiobook → returns failed
  dict.
* `regenerate_audiobook_chapter_image`: missing audiobook → returns
  failed dict.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.audiobook import (
    generate_audiobook,
    regenerate_audiobook_chapter,
    regenerate_audiobook_chapter_image,
)


def _ctx() -> dict[str, Any]:
    session = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    return {
        "session_factory": _sf,
        "redis": AsyncMock(),
        "tts_service": MagicMock(),
        "ffmpeg_service": MagicMock(),
        "comfyui_service": MagicMock(),
        "storage": MagicMock(),
    }


def _ctx_with_session() -> tuple[dict[str, Any], Any]:
    """Like _ctx() but also returns the inner session mock so tests can
    assert update calls."""
    session = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    ctx: dict[str, Any] = {
        "session_factory": _sf,
        "redis": AsyncMock(),
        "tts_service": MagicMock(),
        "ffmpeg_service": MagicMock(),
        "comfyui_service": MagicMock(),
        "storage": MagicMock(),
    }
    return ctx, session


# ── generate_audiobook ─────────────────────────────────────────────


class TestGenerateAudiobookSafetyBranches:
    async def test_missing_audiobook_returns_failed_dict(self) -> None:
        # Pin: a missing audiobook returns a failed dict rather than
        # raising — the worker shouldn't keep retrying for an audiobook
        # that no longer exists in the DB (operator deleted it).
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=None)
        with patch(
            "drevalis.repositories.audiobook.AudiobookRepository",
            return_value=ab_repo,
        ):
            out = await generate_audiobook(_ctx(), str(uuid4()))
        assert out["status"] == "failed"
        assert "not found" in out["error"]

    async def test_missing_voice_profile_updates_status(self) -> None:
        ab = SimpleNamespace(
            id=uuid4(),
            voice_profile_id=uuid4(),  # set but resolves to None below
            text="text",
        )
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=None)
        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.repositories.voice_profile.VoiceProfileRepository",
                return_value=vp_repo,
            ),
        ):
            out = await generate_audiobook(_ctx(), str(uuid4()))
        assert out["status"] == "failed"
        # Pin: status=failed + error_message persisted to the row before
        # returning (so the UI can show the reason).
        ab_repo.update.assert_awaited_once()
        kwargs = ab_repo.update.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert "Voice profile not found" in kwargs["error_message"]

    async def test_missing_voice_profile_id_treated_as_missing(self) -> None:
        # Pin: voice_profile_id=None → vp_repo.get_by_id is NOT called;
        # the route still routes through the "missing voice" branch.
        ab = SimpleNamespace(id=uuid4(), voice_profile_id=None, text="text")
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace())
        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.repositories.voice_profile.VoiceProfileRepository",
                return_value=vp_repo,
            ),
        ):
            out = await generate_audiobook(_ctx(), str(uuid4()))
        assert out["status"] == "failed"
        # voice_profile_id is None → vp_repo.get_by_id is never called.
        vp_repo.get_by_id.assert_not_awaited()

    async def test_preflight_errors_mark_failed_with_capped_message(
        self,
    ) -> None:
        # Build a preflight result with multiple errors. Pin: the route
        # joins them with `; `, prefixes each with the error code, and
        # caps the persisted message at 2000 chars.
        ab = SimpleNamespace(
            id=uuid4(),
            voice_profile_id=uuid4(),
            text="text",
            voice_casting=None,
            music_enabled=False,
            music_mood=None,
            image_generation_enabled=False,
            output_format="audio_only",
        )
        vp = SimpleNamespace(id=uuid4(), provider="piper")
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=vp)

        # Build many errors so the joined message exceeds 2000 chars.
        many_errors = [
            SimpleNamespace(
                severity="error",
                code=f"err_{i}",
                message="x" * 200,
            )
            for i in range(20)
        ]

        ab_service = MagicMock()
        ab_service.preflight = AsyncMock(return_value=many_errors)

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.repositories.voice_profile.VoiceProfileRepository",
                return_value=vp_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
        ):
            out = await generate_audiobook(_ctx(), str(uuid4()))

        assert out["status"] == "failed"
        ab_repo.update.assert_awaited_once()
        kwargs = ab_repo.update.call_args.kwargs
        assert kwargs["status"] == "failed"
        # Pin the 2000-char cap.
        assert len(kwargs["error_message"]) == 2000


# ── regenerate_audiobook_chapter ──────────────────────────────────


class TestRegenerateChapterSafetyBranches:
    async def test_missing_audiobook_returns_failed(self) -> None:
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=None)
        with patch(
            "drevalis.repositories.audiobook.AudiobookRepository",
            return_value=ab_repo,
        ):
            out = await regenerate_audiobook_chapter(_ctx(), str(uuid4()), 0)
        assert out["status"] == "failed"


# ── regenerate_audiobook_chapter_image ────────────────────────────


class TestRegenerateChapterImageSafetyBranches:
    async def test_missing_audiobook_returns_failed(self) -> None:
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=None)
        with patch(
            "drevalis.repositories.audiobook.AudiobookRepository",
            return_value=ab_repo,
        ):
            out = await regenerate_audiobook_chapter_image(_ctx(), str(uuid4()), 0)
        assert out["status"] == "failed"
