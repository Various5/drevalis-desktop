"""Tests for ``generate_audiobook`` — happy path + outcome branches.

The earlier `test_audiobook_worker_job.py` pinned the safety-branch
exits (missing audiobook / voice / preflight errors). This file
covers the actual generation orchestration after preflight passes:

* `audiobook.settings_json` parsed via `AudiobookSettings`; invalid
  JSON falls back to None (and logs a warning) without crashing.
* DAG persist callback writes `job_state` to the audiobook row.
* RenderPlan persist callback writes `render_plan_json`.
* Happy path: result keys flow through to `ab_repo.update(status=done,
  ...)`; `_clear_cancel_flag` invoked.
* `asyncio.CancelledError` mid-generation → status=failed +
  "Cancelled by user" + cancel-flag cleared. Status='cancelled' in
  the return dict (NOT failed) so the route distinguishes them.
* Generic exception → status=failed + error_message capped at 2000.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.audiobook import generate_audiobook


def _ctx() -> dict[str, Any]:
    redis = AsyncMock()
    return {
        "redis": redis,
        "tts_service": MagicMock(),
        "ffmpeg_service": MagicMock(),
        "comfyui_service": MagicMock(),
        "storage": MagicMock(),
    }


def _ab(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "title": "Test Book",
        "text": "Some text" * 50,
        "voice_profile_id": uuid4(),
        "background_image_path": None,
        "output_format": "audio_only",
        "cover_image_path": None,
        "voice_casting": None,
        "music_enabled": False,
        "music_mood": None,
        "music_volume_db": -14.0,
        "speed": 1.0,
        "pitch": 1.0,
        "video_orientation": "landscape",
        "caption_style_preset": None,
        "image_generation_enabled": False,
        "track_mix": None,
        "settings_json": None,
        "job_state": None,
        "render_plan_json": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _factory_with(session: Any) -> Any:
    """Single-session factory — `generate_audiobook` only opens one
    long-lived session."""

    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    return _sf


def _gen_result() -> dict[str, Any]:
    return {
        "audio_rel_path": "audiobooks/x/audio.wav",
        "video_rel_path": None,
        "mp3_rel_path": "audiobooks/x/audio.mp3",
        "duration_seconds": 180.0,
        "file_size_bytes": 7_500_000,
        "chapters": [{"title": "Ch 1", "start_s": 0.0}],
    }


# ── Happy path ────────────────────────────────────────────────────


class TestHappyPath:
    async def test_persists_result_and_clears_cancel_flag(self) -> None:
        ab = _ab()
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session = AsyncMock()
        session.commit = AsyncMock()

        ab_service = MagicMock()
        ab_service.preflight = AsyncMock(return_value=[])
        ab_service.generate = AsyncMock(return_value=_gen_result())
        ab_service._clear_cancel_flag = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)

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
            out = await generate_audiobook(ctx, str(ab.id))

        assert out["status"] == "success"
        assert out["duration"] == 180.0
        # All result keys propagated.
        ab_repo.update.assert_awaited()
        kwargs = ab_repo.update.call_args.kwargs
        assert kwargs["status"] == "done"
        assert kwargs["audio_path"] == "audiobooks/x/audio.wav"
        assert kwargs["mp3_path"] == "audiobooks/x/audio.mp3"
        assert kwargs["duration_seconds"] == 180.0
        assert kwargs["error_message"] is None
        # Cancel flag cleared after success.
        ab_service._clear_cancel_flag.assert_awaited_once()


# ── settings_json parsing ─────────────────────────────────────────


class TestSettingsJsonParsing:
    async def test_invalid_settings_json_falls_back_to_none(self) -> None:
        # Pin: a malformed settings_json blob is logged-and-swallowed;
        # the service still runs with `audiobook_settings=None`
        # (narrative defaults).
        ab = _ab(settings_json={"unknown_key_value": "garbage"})
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session = AsyncMock()
        session.commit = AsyncMock()

        ab_service = MagicMock()
        ab_service.preflight = AsyncMock(return_value=[])
        ab_service.generate = AsyncMock(return_value=_gen_result())
        ab_service._clear_cancel_flag = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)

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
            patch(
                "drevalis.schemas.audiobook.AudiobookSettings.model_validate",
                side_effect=ValueError("bad settings_json"),
            ),
        ):
            out = await generate_audiobook(ctx, str(ab.id))

        assert out["status"] == "success"
        # generate() was invoked with audiobook_settings=None.
        gen_kwargs = ab_service.generate.call_args.kwargs
        assert gen_kwargs["audiobook_settings"] is None


# ── Cancellation mid-generation ──────────────────────────────────


class TestCancellation:
    async def test_cancelled_error_marks_failed_with_clean_message(
        self,
    ) -> None:
        ab = _ab()
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session = AsyncMock()
        session.commit = AsyncMock()

        ab_service = MagicMock()
        ab_service.preflight = AsyncMock(return_value=[])
        ab_service.generate = AsyncMock(side_effect=asyncio.CancelledError())
        ab_service._clear_cancel_flag = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)

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
            out = await generate_audiobook(ctx, str(ab.id))

        # Pin: return dict says "cancelled" — the route distinguishes
        # cancellation from a generic failure even though the DB row
        # is marked failed (audiobook status enum has no "cancelled").
        assert out["status"] == "cancelled"

        # Pin: DB row marked failed with the user-facing reason.
        update_calls = [c for c in ab_repo.update.await_args_list]
        # Last update is the cancellation-handler write.
        last_kwargs = update_calls[-1].kwargs
        assert last_kwargs["status"] == "failed"
        assert last_kwargs["error_message"] == "Cancelled by user"
        # Cancel flag cleared even on cancellation.
        ab_service._clear_cancel_flag.assert_awaited_once()


# ── Generic exception path ───────────────────────────────────────


class TestGenericException:
    async def test_exception_marks_failed_with_2000_char_cap(self) -> None:
        ab = _ab()
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session = AsyncMock()
        session.commit = AsyncMock()

        ab_service = MagicMock()
        ab_service.preflight = AsyncMock(return_value=[])
        long_err = "Y" * 5000
        ab_service.generate = AsyncMock(side_effect=RuntimeError(long_err))
        ab_service._clear_cancel_flag = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)

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
            out = await generate_audiobook(ctx, str(ab.id))

        assert out["status"] == "failed"
        last_kwargs = ab_repo.update.await_args_list[-1].kwargs
        # 2000-char cap on the persisted error_message (audiobook
        # column is wider than the script-job 500 cap).
        assert len(last_kwargs["error_message"]) == 2000
        ab_service._clear_cancel_flag.assert_awaited_once()


# ── DAG / RenderPlan persist callbacks ────────────────────────────


class TestPersistCallbacks:
    async def test_dag_persist_callback_writes_job_state(self) -> None:
        # Pin: the persist_job_state_cb passed to
        # AudiobookService.generate writes job_state via a NEW
        # session (so retries don't lock the long-running session).
        ab = _ab()
        ab_repo_main = MagicMock()
        ab_repo_main.get_by_id = AsyncMock(return_value=ab)
        ab_repo_main.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

        # Two sessions: the long-running one for generate(), plus
        # the persist callback's transient session.
        main_session = AsyncMock()
        main_session.commit = AsyncMock()
        persist_session = AsyncMock()
        persist_session.commit = AsyncMock()

        # Persist callback uses a NEW AudiobookRepository.
        persist_repo = MagicMock()
        persist_repo.update = AsyncMock()

        repos = iter([ab_repo_main, persist_repo])

        # Multi-session factory: main session first, persist session
        # second when the callback fires.
        sessions = iter([main_session, persist_session])

        @asynccontextmanager
        async def _sf() -> Any:
            yield next(sessions)

        captured_cb: dict[str, Any] = {}

        async def _fake_generate(**kwargs: Any) -> dict[str, Any]:
            # Capture the persist callback so the test can fire it.
            captured_cb["dag"] = kwargs["persist_job_state_cb"]
            captured_cb["render_plan"] = kwargs["persist_render_plan_cb"]
            return _gen_result()

        ab_service = MagicMock()
        ab_service.preflight = AsyncMock(return_value=[])
        ab_service.generate = AsyncMock(side_effect=_fake_generate)
        ab_service._clear_cancel_flag = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _sf

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=lambda _s: next(repos),
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
            await generate_audiobook(ctx, str(ab.id))

        # Now manually fire the captured DAG callback to exercise its
        # body. (In real life the service fires it after every stage.)
        dag_blob = {"stage": "tts", "status": "done"}
        await captured_cb["dag"](dag_blob)
        # Pin: persist_repo.update was called with job_state=dag_blob.
        persist_repo.update.assert_awaited_once()
        kwargs = persist_repo.update.call_args.kwargs
        assert kwargs["job_state"] == dag_blob
        persist_session.commit.assert_awaited()

    async def test_persist_callback_failure_swallowed(self) -> None:
        # Pin: a persist failure in the DAG callback doesn't propagate
        # — the service keeps running (we lose the resume hint, but
        # that's better than crashing the whole job).
        ab = _ab()
        ab_repo_main = MagicMock()
        ab_repo_main.get_by_id = AsyncMock(return_value=ab)
        ab_repo_main.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

        main_session = AsyncMock()
        main_session.commit = AsyncMock()
        persist_session = AsyncMock()
        persist_session.commit = AsyncMock(side_effect=ConnectionError("DB blip"))

        persist_repo = MagicMock()
        persist_repo.update = AsyncMock(side_effect=ConnectionError("DB blip"))
        repos = iter([ab_repo_main, persist_repo])
        sessions = iter([main_session, persist_session])

        @asynccontextmanager
        async def _sf() -> Any:
            yield next(sessions)

        captured_cb: dict[str, Any] = {}

        async def _fake_generate(**kwargs: Any) -> dict[str, Any]:
            captured_cb["dag"] = kwargs["persist_job_state_cb"]
            return _gen_result()

        ab_service = MagicMock()
        ab_service.preflight = AsyncMock(return_value=[])
        ab_service.generate = AsyncMock(side_effect=_fake_generate)
        ab_service._clear_cancel_flag = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _sf

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                side_effect=lambda _s: next(repos),
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
            await generate_audiobook(ctx, str(ab.id))

        # Fire the DAG callback — must NOT raise.
        await captured_cb["dag"]({"stage": "tts"})
