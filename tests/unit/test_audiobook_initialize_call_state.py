"""Tests for ``AudiobookService._initialize_call_state`` (F-CQ-01 step 2).

The helper does the per-call instance-state wiring at the top of
``generate``: structlog binding, ComfyUI pool refresh, cancellation
checker, and DAG hydration. Misses ship as cross-call state leaks
(an audiobook_id from one call leaking into another's logs) or
cancellation polling not being able to find the audiobook_id.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import structlog

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    CancelChecker,
)


def _make_service(
    *,
    comfyui_service: Any = None,
    db_session: Any = None,
    redis: Any = None,
) -> AudiobookService:
    svc = AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
        comfyui_service=comfyui_service,
        db_session=db_session,
        redis=redis,
    )
    return svc


# ── ContextVar binding ──────────────────────────────────────────────


class TestContextvarsBinding:
    async def test_binds_audiobook_id_and_title(self) -> None:
        svc = _make_service()
        ab_id = uuid4()
        await svc._initialize_call_state(
            audiobook_id=ab_id,
            title="My Book",
            initial_job_state=None,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )
        # Read back the contextvars to confirm both were bound. The
        # underlying logger's getter exposes the merged dict.
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("audiobook_id") == str(ab_id)
        assert ctx.get("title") == "My Book"
        # Cleanup so we don't leak into other tests on the same loop.
        structlog.contextvars.clear_contextvars()


# ── ComfyUI pool refresh ────────────────────────────────────────────


class TestComfyuiPoolRefresh:
    async def test_no_refresh_when_no_comfyui_service(self) -> None:
        # Bare invocation: comfyui_service=None — refresh skipped.
        svc = _make_service(comfyui_service=None, db_session=AsyncMock())
        await svc._initialize_call_state(
            audiobook_id=uuid4(),
            title="X",
            initial_job_state=None,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )
        # Nothing to assert beyond no-raise.

    async def test_no_refresh_when_no_db_session(self) -> None:
        comfyui = MagicMock()
        comfyui._pool.sync_from_db = AsyncMock()
        svc = _make_service(comfyui_service=comfyui, db_session=None)
        await svc._initialize_call_state(
            audiobook_id=uuid4(),
            title="X",
            initial_job_state=None,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )
        comfyui._pool.sync_from_db.assert_not_awaited()

    async def test_refresh_called_when_both_present(self) -> None:
        comfyui = MagicMock()
        comfyui._pool.sync_from_db = AsyncMock()
        db = AsyncMock()
        svc = _make_service(comfyui_service=comfyui, db_session=db)
        await svc._initialize_call_state(
            audiobook_id=uuid4(),
            title="X",
            initial_job_state=None,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )
        comfyui._pool.sync_from_db.assert_awaited_once_with(db)

    async def test_refresh_exception_swallowed(self) -> None:
        # Pool refresh failures are non-fatal: a stale pool is better
        # than failing the whole audiobook generation at the front door.
        comfyui = MagicMock()
        comfyui._pool.sync_from_db = AsyncMock(side_effect=RuntimeError("DB down"))
        svc = _make_service(comfyui_service=comfyui, db_session=AsyncMock())
        # Must not raise.
        await svc._initialize_call_state(
            audiobook_id=uuid4(),
            title="X",
            initial_job_state=None,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )


# ── Audiobook id stash + cancel checker ──────────────────────────────


class TestCancellationWiring:
    async def test_audiobook_id_stashed_on_instance(self) -> None:
        svc = _make_service()
        ab_id = uuid4()
        await svc._initialize_call_state(
            audiobook_id=ab_id,
            title="X",
            initial_job_state=None,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )
        # ``_current_audiobook_id`` is read by per-chunk gather'd
        # coroutines for cancellation polling.
        assert svc._current_audiobook_id == ab_id

    async def test_cancel_checker_built_once_per_call(self) -> None:
        svc = _make_service()
        ab_id = uuid4()
        await svc._initialize_call_state(
            audiobook_id=ab_id,
            title="X",
            initial_job_state=None,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )
        assert isinstance(svc._cancel_checker, CancelChecker)


# ── DAG state + persistence callbacks ────────────────────────────────


class TestJobStateInit:
    async def test_none_initial_state_yields_empty_dict(self) -> None:
        svc = _make_service()
        await svc._initialize_call_state(
            audiobook_id=uuid4(),
            title="X",
            initial_job_state=None,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )
        assert svc._job_state == {}

    async def test_initial_state_hydrated(self) -> None:
        # Worker resumes a partially-completed audiobook by passing
        # the persisted job_state dict back through.
        svc = _make_service()
        prior = {"chapters": {"0": {"tts": "done"}}}
        await svc._initialize_call_state(
            audiobook_id=uuid4(),
            title="X",
            initial_job_state=prior,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )
        assert svc._job_state is prior

    async def test_persistence_callbacks_stored(self) -> None:
        svc = _make_service()
        cb1 = AsyncMock()
        cb2 = AsyncMock()
        await svc._initialize_call_state(
            audiobook_id=uuid4(),
            title="X",
            initial_job_state=None,
            persist_job_state_cb=cb1,
            persist_render_plan_cb=cb2,
        )
        assert svc._persist_job_state_cb is cb1
        assert svc._persist_render_plan_cb is cb2

    async def test_callbacks_default_to_none(self) -> None:
        svc = _make_service()
        await svc._initialize_call_state(
            audiobook_id=uuid4(),
            title="X",
            initial_job_state=None,
            persist_job_state_cb=None,
            persist_render_plan_cb=None,
        )
        assert svc._persist_job_state_cb is None
        assert svc._persist_render_plan_cb is None
