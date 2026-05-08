"""Tests for ``generate_ai_audiobook`` — the end-to-end LLM-script
+ TTS + music + assembly job that drives ``POST /audiobooks/create-ai``.

This is the deepest worker orchestration in the codebase. We can't
unit-test the inner TTS/ffmpeg/ComfyUI execution, but we CAN pin:

* Resume-from-failure: existing text > 100 chars → skip LLM step
  entirely, jump straight to TTS.
* Script-generation failure (LLM raises) → audiobook marked failed
  with `Script generation failed: ...` (capped at 500 chars).
* Audiobook missing between Step 2 and Step 3 → returns failed
  without crashing.
* Voice profile missing on the (now-loaded) audiobook → failed
  with "No voice profile configured".
* Happy path: AudiobookService.generate's result dict's keys all
  flow through to the final ab_repo.update call (audio/video/mp3
  paths + duration + size + chapters).
* `asyncio.CancelledError` mid-generation → status="failed" with
  "Cancelled by user" + best-effort cancel-flag delete.
* Generic exception during generation → "Audio generation failed:
  …" capped at 500 chars.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.audiobook import generate_ai_audiobook


def _ctx() -> dict[str, Any]:
    redis = AsyncMock()
    redis.delete = AsyncMock()

    return {
        "redis": redis,
        "tts_service": MagicMock(),
        "ffmpeg_service": MagicMock(),
        "comfyui_service": MagicMock(),
        "storage": MagicMock(),
    }


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "concept": "A short tale",
        "target_minutes": 5,
        "mood": "neutral",
        "characters": [{"name": "Narrator", "description": "Omniscient narrator"}],
    }
    base.update(overrides)
    return base


def _ab(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "text": "",
        "voice_profile_id": uuid4(),
        "output_format": "audio_only",
        "cover_image_path": None,
        "voice_casting": None,
        "music_enabled": False,
        "music_mood": None,
        "music_volume_db": -14.0,
        "speed": 1.0,
        "pitch": 1.0,
        "image_generation_enabled": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _factory_returning(*sessions: Any) -> Any:
    """Build a session_factory that yields each given session in turn
    across successive `async with session_factory() as s:` calls."""
    iterator = iter(sessions)

    @asynccontextmanager
    async def _sf() -> Any:
        yield next(iterator)

    return _sf


# ── Resume-from-failure (skip-LLM) path ───────────────────────────


class TestResumeFromFailure:
    async def test_existing_text_skips_llm(self) -> None:
        # Pin: when the audiobook already has > 100 chars of text
        # (the previous attempt completed LLM but failed during TTS),
        # the worker skips the LLM step entirely and goes straight
        # to TTS+assembly.
        ctx = _ctx()
        ab_id = uuid4()

        # Session 1: check_text → returns audiobook with long text.
        # Session 2: TTS step loads audiobook + voice profile.
        ab_with_text = _ab(id=ab_id, text="X" * 200)
        ab_repo_1 = MagicMock()
        ab_repo_1.get_by_id = AsyncMock(return_value=ab_with_text)
        session_1 = AsyncMock()
        session_1.commit = AsyncMock()

        ab_repo_2 = MagicMock()
        ab_repo_2.get_by_id = AsyncMock(return_value=ab_with_text)
        ab_repo_2.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session_2 = AsyncMock()
        session_2.commit = AsyncMock()

        ctx["session_factory"] = _factory_returning(session_1, session_2)

        ab_service = MagicMock()
        ab_service.generate = AsyncMock(
            return_value={
                "audio_rel_path": "audiobooks/x/audio.wav",
                "video_rel_path": None,
                "mp3_rel_path": "audiobooks/x/audio.mp3",
                "duration_seconds": 120.0,
                "file_size_bytes": 5_000_000,
                "chapters": [],
            }
        )
        ab_service._clear_cancel_flag = AsyncMock()

        # The LLM provider construction MUST NOT be invoked.
        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=[ab_repo_1, ab_repo_2],
            ),
            patch(
                "drevalis.repositories.voice_profile.VoiceProfileRepository",
                return_value=vp_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
            patch(
                "drevalis.services.llm.OpenAICompatibleProvider",
                side_effect=AssertionError("LLM must not be called"),
            ),
        ):
            out = await generate_ai_audiobook(ctx, str(ab_id), _payload())
        assert out["status"] == "done"
        assert out["duration"] == 120.0


# ── Script-generation failure ─────────────────────────────────────


class TestScriptGenerationFailure:
    async def test_llm_failure_marks_failed_with_capped_message(
        self,
    ) -> None:
        ctx = _ctx()
        ab_id = uuid4()

        # Session 1 (check_text): returns short-text audiobook (no skip).
        ab_short = _ab(id=ab_id, text="")
        ab_repo_1 = MagicMock()
        ab_repo_1.get_by_id = AsyncMock(return_value=ab_short)
        session_1 = AsyncMock()
        session_1.commit = AsyncMock()

        # Session 2 (LLM repo lookup) — empty configs → fallback to LM
        # Studio default. We don't actually reach the LLM since the
        # script helper raises.
        llm_repo = MagicMock()
        llm_repo.get_all = AsyncMock(return_value=[])
        session_2 = AsyncMock()

        # Session 3 (mark failed).
        ab_repo_3 = MagicMock()
        ab_repo_3.update = AsyncMock()
        session_3 = AsyncMock()
        session_3.commit = AsyncMock()

        ctx["session_factory"] = _factory_returning(session_1, session_2, session_3)

        long_err = "X" * 800

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=[ab_repo_1, ab_repo_3],
            ),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch(
                "drevalis.workers.jobs.audiobook._generate_audiobook_script_text",
                AsyncMock(side_effect=ConnectionError(long_err)),
            ),
        ):
            out = await generate_ai_audiobook(ctx, str(ab_id), _payload())
        assert out["status"] == "failed"
        # Pin: error message stored on the audiobook capped to 500 chars
        # of payload + the "Script generation failed: " prefix.
        ab_repo_3.update.assert_awaited_once()
        kwargs = ab_repo_3.update.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert kwargs["error_message"].startswith("Script generation failed:")
        # The 500-char cap applies to the underlying error string.
        assert "X" * 500 in kwargs["error_message"]
        assert "X" * 501 not in kwargs["error_message"]


# ── Step 2 / Step 3 missing-resource paths ────────────────────────


class TestMissingResource:
    async def test_audiobook_disappears_between_step1_and_step2(
        self,
    ) -> None:
        # Pin: if the operator deletes the audiobook between LLM and
        # text-update, the worker returns failed without crashing.
        ctx = _ctx()
        ab_id = uuid4()

        # Session 1: check_text returns short-text audiobook.
        ab_short = _ab(id=ab_id, text="")
        ab_repo_1 = MagicMock()
        ab_repo_1.get_by_id = AsyncMock(return_value=ab_short)
        session_1 = AsyncMock()

        # Session 2: LLM repo returns no configs.
        llm_repo = MagicMock()
        llm_repo.get_all = AsyncMock(return_value=[])
        session_2 = AsyncMock()

        # Session 3: text-update — but audiobook is GONE.
        ab_repo_3 = MagicMock()
        ab_repo_3.get_by_id = AsyncMock(return_value=None)
        session_3 = AsyncMock()

        ctx["session_factory"] = _factory_returning(session_1, session_2, session_3)

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=[ab_repo_1, ab_repo_3],
            ),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch(
                "drevalis.workers.jobs.audiobook._generate_audiobook_script_text",
                AsyncMock(return_value="Title\n\n## Chapter 1\n[Narrator] hi"),
            ),
        ):
            out = await generate_ai_audiobook(ctx, str(ab_id), _payload())
        assert out["status"] == "failed"

    async def test_voice_profile_missing_before_tts(self) -> None:
        # Existing text path → skip LLM. Then Step 3 loads audiobook +
        # voice_profile — voice is None → mark failed.
        ctx = _ctx()
        ab_id = uuid4()
        ab_with_text = _ab(id=ab_id, text="X" * 200, voice_profile_id=uuid4())

        # Session 1 (check_text).
        ab_repo_1 = MagicMock()
        ab_repo_1.get_by_id = AsyncMock(return_value=ab_with_text)
        session_1 = AsyncMock()

        # Session 2 (TTS step) — voice missing.
        ab_repo_2 = MagicMock()
        ab_repo_2.get_by_id = AsyncMock(return_value=ab_with_text)
        ab_repo_2.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=None)
        session_2 = AsyncMock()
        session_2.commit = AsyncMock()

        ctx["session_factory"] = _factory_returning(session_1, session_2)

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=[ab_repo_1, ab_repo_2],
            ),
            patch(
                "drevalis.repositories.voice_profile.VoiceProfileRepository",
                return_value=vp_repo,
            ),
        ):
            out = await generate_ai_audiobook(ctx, str(ab_id), _payload())
        assert out["status"] == "failed"
        ab_repo_2.update.assert_awaited_once()
        kwargs = ab_repo_2.update.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert "voice profile" in kwargs["error_message"].lower()


# ── Cancellation ──────────────────────────────────────────────────


class TestCancellation:
    async def test_cancelled_error_marks_failed_and_clears_flag(
        self,
    ) -> None:
        ctx = _ctx()
        ab_id = uuid4()
        ab_with_text = _ab(id=ab_id, text="X" * 200)

        # Session 1 (check_text).
        ab_repo_1 = MagicMock()
        ab_repo_1.get_by_id = AsyncMock(return_value=ab_with_text)
        session_1 = AsyncMock()

        # Session 2 (TTS step) — generate raises CancelledError.
        ab_repo_2 = MagicMock()
        ab_repo_2.get_by_id = AsyncMock(return_value=ab_with_text)
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session_2 = AsyncMock()

        # Session 3 (mark failed).
        ab_repo_3 = MagicMock()
        ab_repo_3.update = AsyncMock()
        session_3 = AsyncMock()
        session_3.commit = AsyncMock()

        ctx["session_factory"] = _factory_returning(session_1, session_2, session_3)

        ab_service = MagicMock()
        ab_service.generate = AsyncMock(side_effect=asyncio.CancelledError("user clicked Stop"))

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=[ab_repo_1, ab_repo_2, ab_repo_3],
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
            out = await generate_ai_audiobook(ctx, str(ab_id), _payload())
        assert out["status"] == "cancelled"

        # Pin: the audiobook is marked failed with the cancellation
        # message — the UI surfaces "Cancelled by user" not a generic
        # error.
        ab_repo_3.update.assert_awaited_once()
        kwargs = ab_repo_3.update.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert "Cancelled by user" in kwargs["error_message"]

        # Pin: best-effort cancel-flag delete fires.
        ctx["redis"].delete.assert_awaited_once()
        del_key = ctx["redis"].delete.call_args.args[0]
        assert del_key == f"cancel:audiobook:{ab_id}"

    async def test_redis_delete_failure_swallowed(self) -> None:
        # Pin: when the cancel-flag cleanup raises, the cancellation
        # path STILL returns cleanly.
        ctx = _ctx()
        ctx["redis"].delete = AsyncMock(side_effect=ConnectionError("redis down"))
        ab_id = uuid4()
        ab_with_text = _ab(id=ab_id, text="X" * 200)

        ab_repo_1 = MagicMock()
        ab_repo_1.get_by_id = AsyncMock(return_value=ab_with_text)
        session_1 = AsyncMock()
        ab_repo_2 = MagicMock()
        ab_repo_2.get_by_id = AsyncMock(return_value=ab_with_text)
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session_2 = AsyncMock()
        ab_repo_3 = MagicMock()
        ab_repo_3.update = AsyncMock()
        session_3 = AsyncMock()
        session_3.commit = AsyncMock()
        ctx["session_factory"] = _factory_returning(session_1, session_2, session_3)

        ab_service = MagicMock()
        ab_service.generate = AsyncMock(side_effect=asyncio.CancelledError())

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=[ab_repo_1, ab_repo_2, ab_repo_3],
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
            out = await generate_ai_audiobook(ctx, str(ab_id), _payload())
        # Cancellation path completes despite redis failure.
        assert out["status"] == "cancelled"


# ── Audio generation failure ──────────────────────────────────────


class TestAudioGenerationFailure:
    async def test_generate_failure_marks_failed_with_capped_message(
        self,
    ) -> None:
        ctx = _ctx()
        ab_id = uuid4()
        ab_with_text = _ab(id=ab_id, text="X" * 200)

        ab_repo_1 = MagicMock()
        ab_repo_1.get_by_id = AsyncMock(return_value=ab_with_text)
        session_1 = AsyncMock()

        ab_repo_2 = MagicMock()
        ab_repo_2.get_by_id = AsyncMock(return_value=ab_with_text)
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session_2 = AsyncMock()

        ab_repo_3 = MagicMock()
        ab_repo_3.update = AsyncMock()
        session_3 = AsyncMock()
        session_3.commit = AsyncMock()

        ctx["session_factory"] = _factory_returning(session_1, session_2, session_3)

        long_err = "X" * 800
        ab_service = MagicMock()
        ab_service.generate = AsyncMock(side_effect=RuntimeError(long_err))

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=[ab_repo_1, ab_repo_2, ab_repo_3],
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
            out = await generate_ai_audiobook(ctx, str(ab_id), _payload())
        assert out["status"] == "failed"
        ab_repo_3.update.assert_awaited_once()
        kwargs = ab_repo_3.update.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert kwargs["error_message"].startswith("Audio generation failed:")
        # 500-char cap on the underlying error.
        assert "X" * 500 in kwargs["error_message"]


# ── Happy path persistence ────────────────────────────────────────


class TestHappyPathPersistence:
    async def test_generate_result_keys_flow_to_update(self) -> None:
        # Pin: every key in the AudiobookService.generate result dict
        # is mirrored into the final ab_repo.update call so the row
        # is fully populated when the UI polls "done".
        ctx = _ctx()
        ab_id = uuid4()
        ab_with_text = _ab(id=ab_id, text="X" * 200)

        ab_repo_1 = MagicMock()
        ab_repo_1.get_by_id = AsyncMock(return_value=ab_with_text)
        session_1 = AsyncMock()

        ab_repo_2 = MagicMock()
        ab_repo_2.get_by_id = AsyncMock(return_value=ab_with_text)
        ab_repo_2.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session_2 = AsyncMock()
        session_2.commit = AsyncMock()

        ctx["session_factory"] = _factory_returning(session_1, session_2)

        ab_service = MagicMock()
        gen_result = {
            "audio_rel_path": "audiobooks/x/audio.wav",
            "video_rel_path": "audiobooks/x/video.mp4",
            "mp3_rel_path": "audiobooks/x/audio.mp3",
            "duration_seconds": 600.0,
            "file_size_bytes": 50_000_000,
            "chapters": [{"title": "Ch 1", "start_s": 0.0}],
        }
        ab_service.generate = AsyncMock(return_value=gen_result)
        ab_service._clear_cancel_flag = AsyncMock()

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=[ab_repo_1, ab_repo_2],
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
            out = await generate_ai_audiobook(ctx, str(ab_id), _payload())
        assert out["status"] == "done"
        assert out["duration"] == 600.0

        # All gen_result keys propagated.
        ab_repo_2.update.assert_awaited_once()
        kwargs = ab_repo_2.update.call_args.kwargs
        assert kwargs["status"] == "done"
        assert kwargs["audio_path"] == gen_result["audio_rel_path"]
        assert kwargs["video_path"] == gen_result["video_rel_path"]
        assert kwargs["mp3_path"] == gen_result["mp3_rel_path"]
        assert kwargs["duration_seconds"] == 600.0
        assert kwargs["file_size_bytes"] == 50_000_000
        assert kwargs["chapters"] == [{"title": "Ch 1", "start_s": 0.0}]
        # error_message cleared on success.
        assert kwargs["error_message"] is None
        # Cancel flag cleaned up.
        ab_service._clear_cancel_flag.assert_awaited_once()
