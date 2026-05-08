"""Tests for ``api/routes/episodes/_monolith.py`` — CRUD + generation
control + script edits.

Pin the service-exception → HTTP-status mapping that the UI depends on:

* ``EpisodeNotFoundError`` → 404 across every endpoint.
* ``EpisodeInvalidStatusError`` → **409** with the current status in
  the detail (only `draft`/`failed` can regen — message tells user why).
* ``ConcurrencyCapReachedError`` → **429** Too Many Requests.
* ``NoFailedJobError`` → 409 (retry endpoint, no failures to retry).
* ``ScriptValidationError`` → 422.
* ``SceneNotFoundError`` → 404 with the scene number in the detail.

Quota check on `generate_episode` runs BEFORE the service call —
ensures Pro/Studio paywall fires even on episodes the user owns.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.episodes._monolith import (
    _episode_service,
    _episode_to_list,
    _episode_to_response,
    bulk_generate,
    create_episode,
    delete_episode,
    delete_scene,
    generate_episode,
    get_episode,
    get_episode_script,
    list_episodes,
    list_recent_episodes,
    merge_scenes,
    reorder_scenes,
    retry_episode,
    retry_episode_step,
    split_scene,
    update_episode,
    update_episode_script,
    update_scene,
)
from drevalis.schemas.episode import (
    BulkGenerateRequest,
    EpisodeCreate,
    EpisodeUpdate,
    GenerateRequest,
    ScriptUpdate,
)
from drevalis.services.episode import (
    ConcurrencyCapReachedError,
    EpisodeInvalidStatusError,
    EpisodeNoScriptError,
    EpisodeNotFoundError,
    EpisodeService,
    NoFailedJobError,
    SceneNotFoundError,
    ScriptValidationError,
)


def _settings(tmp_path: Any = None) -> Any:
    s = MagicMock()
    s.max_concurrent_generations = 4
    s.storage_base_path = tmp_path or "/tmp"
    return s


def _make_episode(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "series_id": uuid4(),
        "title": "Hook A",
        "topic": "intro",
        "status": "draft",
        "script": None,
        "base_path": None,
        "generation_log": None,
        "metadata_": None,
        "override_voice_profile_id": None,
        "override_llm_config_id": None,
        "override_caption_style": None,
        "content_format": "shorts",
        "chapters": None,
        "total_duration_seconds": None,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
        "media_assets": [],
        "generation_jobs": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── _episode_service factory ───────────────────────────────────────


class TestServiceFactory:
    def test_returns_service(self) -> None:
        svc = _episode_service(db=AsyncMock())
        assert isinstance(svc, EpisodeService)


# ── _episode_to_response / _episode_to_list ────────────────────────


class TestSerializers:
    def test_to_response_preserves_id(self) -> None:
        ep = _make_episode()
        out = _episode_to_response(ep)
        assert out.id == ep.id

    def test_to_list_lightweight_shape(self) -> None:
        ep = _make_episode()
        out = _episode_to_list(ep)
        assert out.id == ep.id
        assert out.title == "Hook A"


# ── GET /recent ────────────────────────────────────────────────────


class TestListRecent:
    async def test_returns_list(self) -> None:
        svc = MagicMock()
        svc.list_recent = AsyncMock(return_value=[_make_episode(), _make_episode()])
        out = await list_recent_episodes(limit=10, svc=svc)
        assert len(out) == 2
        svc.list_recent.assert_awaited_once_with(10)


# ── GET / ──────────────────────────────────────────────────────────


class TestList:
    async def test_passes_filters(self) -> None:
        svc = MagicMock()
        svc.list_filtered = AsyncMock(return_value=[_make_episode()])
        sid = uuid4()
        await list_episodes(
            series_id=sid,
            status_filter="draft",
            offset=10,
            limit=25,
            svc=svc,
        )
        svc.list_filtered.assert_awaited_once_with(
            series_id=sid, status_filter="draft", offset=10, limit=25
        )


# ── POST / ─────────────────────────────────────────────────────────


class TestCreate:
    async def test_create_returns_response(self) -> None:
        svc = MagicMock()
        ep = _make_episode(title="X")
        svc.create = AsyncMock(return_value=ep)
        out = await create_episode(EpisodeCreate(series_id=ep.series_id, title="X"), svc=svc)
        assert out.title == "X"


# ── POST /bulk-generate ────────────────────────────────────────────


class TestBulkGenerate:
    async def test_returns_counts(self) -> None:
        svc = MagicMock()
        a, b, c = uuid4(), uuid4(), uuid4()
        svc.bulk_generate = AsyncMock(return_value=([a, b], [c]))
        out = await bulk_generate(
            BulkGenerateRequest(episode_ids=[a, b, c]),
            svc=svc,
            settings=_settings(),
        )
        assert out.queued == 2
        assert out.skipped == 1
        assert out.total == 3
        assert out.queued_ids == [a, b]
        assert out.skipped_ids == [c]


# ── GET /{episode_id} ──────────────────────────────────────────────


class TestGetEpisode:
    async def test_success(self) -> None:
        svc = MagicMock()
        ep = _make_episode()
        svc.get_with_assets_or_raise = AsyncMock(return_value=ep)
        out = await get_episode(ep.id, svc=svc)
        assert out.id == ep.id

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get_with_assets_or_raise = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_episode(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── PUT /{id} ──────────────────────────────────────────────────────


class TestUpdate:
    async def test_success(self) -> None:
        svc = MagicMock()
        ep = _make_episode(title="renamed")
        svc.update = AsyncMock(return_value=ep)
        out = await update_episode(ep.id, EpisodeUpdate(title="renamed"), svc=svc)
        assert out.title == "renamed"
        # exclude_unset semantics.
        kwargs = svc.update.call_args.args[1]
        assert kwargs == {"title": "renamed"}

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_episode(uuid4(), EpisodeUpdate(title="x"), svc=svc)
        assert exc.value.status_code == 404

    async def test_script_validation_422(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ScriptValidationError("bad shape"))
        with pytest.raises(HTTPException) as exc:
            await update_episode(uuid4(), EpisodeUpdate(title="x"), svc=svc)
        assert exc.value.status_code == 422


# ── DELETE /{id} ───────────────────────────────────────────────────


class TestDelete:
    async def test_delegates_to_service_with_storage_callback(self, tmp_path: Any) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_episode(uuid4(), settings=_settings(tmp_path), svc=svc)
        svc.delete.assert_awaited_once()
        # Storage callback wired through.
        kwargs = svc.delete.call_args.kwargs
        assert "storage_delete_dir" in kwargs

    async def test_not_found_404(self, tmp_path: Any) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_episode(uuid4(), settings=_settings(tmp_path), svc=svc)
        assert exc.value.status_code == 404


# ── POST /{id}/generate ────────────────────────────────────────────


class TestGenerateEpisode:
    async def test_quota_check_runs_before_service(self) -> None:
        # Pin: quota gate fires first so Pro/Studio paywall can deny
        # before we burn cycles on the service call.
        svc = MagicMock()
        svc.generate = AsyncMock(return_value=[uuid4()])
        quota = AsyncMock()
        # Build a redis async-generator that yields once.
        from contextlib import asynccontextmanager  # noqa: F401

        async def _redis_gen() -> Any:
            yield AsyncMock()

        with (
            patch(
                "drevalis.core.license.quota.check_and_increment_episode_quota",
                quota,
            ),
            patch("drevalis.core.redis.get_redis", return_value=_redis_gen()),
        ):
            await generate_episode(
                uuid4(),
                payload=GenerateRequest(),
                settings=_settings(),
                svc=svc,
            )
        quota.assert_awaited_once()

    async def test_success_returns_job_ids(self) -> None:
        svc = MagicMock()
        a, b = uuid4(), uuid4()
        svc.generate = AsyncMock(return_value=[a, b])

        async def _redis_gen() -> Any:
            yield AsyncMock()

        with (
            patch(
                "drevalis.core.license.quota.check_and_increment_episode_quota",
                AsyncMock(),
            ),
            patch("drevalis.core.redis.get_redis", return_value=_redis_gen()),
        ):
            out = await generate_episode(
                uuid4(),
                payload=None,
                settings=_settings(),
                svc=svc,
            )
        assert out.job_ids == [a, b]
        # No payload → no requested_steps passed.
        assert svc.generate.call_args.args[1] is None

    async def test_passes_requested_steps_when_payload_supplied(self) -> None:
        svc = MagicMock()
        svc.generate = AsyncMock(return_value=[])

        async def _redis_gen() -> Any:
            yield AsyncMock()

        with (
            patch(
                "drevalis.core.license.quota.check_and_increment_episode_quota",
                AsyncMock(),
            ),
            patch("drevalis.core.redis.get_redis", return_value=_redis_gen()),
        ):
            await generate_episode(
                uuid4(),
                payload=GenerateRequest(steps=["voice", "scenes"]),
                settings=_settings(),
                svc=svc,
            )
        called_steps = svc.generate.call_args.args[1]
        assert called_steps == ["voice", "scenes"]

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.generate = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))

        async def _redis_gen() -> Any:
            yield AsyncMock()

        with (
            patch(
                "drevalis.core.license.quota.check_and_increment_episode_quota",
                AsyncMock(),
            ),
            patch("drevalis.core.redis.get_redis", return_value=_redis_gen()),
        ):
            with pytest.raises(HTTPException) as exc:
                await generate_episode(uuid4(), payload=None, settings=_settings(), svc=svc)
        assert exc.value.status_code == 404

    async def test_invalid_status_409_with_current_status(self) -> None:
        # Pin the actual error message: "Episode is in 'X' status..." so
        # the UI can surface the current status to the user.
        svc = MagicMock()
        svc.generate = AsyncMock(
            side_effect=EpisodeInvalidStatusError(
                episode_id=uuid4(),
                current_status="exported",
                allowed=["draft", "failed"],
            )
        )

        async def _redis_gen() -> Any:
            yield AsyncMock()

        with (
            patch(
                "drevalis.core.license.quota.check_and_increment_episode_quota",
                AsyncMock(),
            ),
            patch("drevalis.core.redis.get_redis", return_value=_redis_gen()),
        ):
            with pytest.raises(HTTPException) as exc:
                await generate_episode(uuid4(), payload=None, settings=_settings(), svc=svc)
        assert exc.value.status_code == 409
        assert "exported" in exc.value.detail
        assert "draft" in exc.value.detail or "failed" in exc.value.detail

    async def test_concurrency_cap_429(self) -> None:
        svc = MagicMock()
        svc.generate = AsyncMock(side_effect=ConcurrencyCapReachedError("4/4 generations active"))

        async def _redis_gen() -> Any:
            yield AsyncMock()

        with (
            patch(
                "drevalis.core.license.quota.check_and_increment_episode_quota",
                AsyncMock(),
            ),
            patch("drevalis.core.redis.get_redis", return_value=_redis_gen()),
        ):
            with pytest.raises(HTTPException) as exc:
                await generate_episode(uuid4(), payload=None, settings=_settings(), svc=svc)
        assert exc.value.status_code == 429


# ── POST /{id}/retry ───────────────────────────────────────────────


class TestRetry:
    async def test_success(self) -> None:
        svc = MagicMock()
        jid = uuid4()
        svc.retry_first_failed = AsyncMock(return_value=(jid, "voice"))
        out = await retry_episode(uuid4(), settings=_settings(), svc=svc)
        assert out.job_id == jid
        assert out.step == "voice"

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.retry_first_failed = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await retry_episode(uuid4(), settings=_settings(), svc=svc)
        assert exc.value.status_code == 404

    async def test_concurrency_cap_429(self) -> None:
        svc = MagicMock()
        svc.retry_first_failed = AsyncMock(side_effect=ConcurrencyCapReachedError("cap"))
        with pytest.raises(HTTPException) as exc:
            await retry_episode(uuid4(), settings=_settings(), svc=svc)
        assert exc.value.status_code == 429

    async def test_no_failed_jobs_409(self) -> None:
        # Pin: 409 (Conflict) — episode exists but there's nothing to
        # retry. Distinct from 404 (episode missing).
        svc = MagicMock()
        svc.retry_first_failed = AsyncMock(side_effect=NoFailedJobError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await retry_episode(uuid4(), settings=_settings(), svc=svc)
        assert exc.value.status_code == 409


class TestRetryStep:
    async def test_success(self) -> None:
        svc = MagicMock()
        jid = uuid4()
        svc.retry_step = AsyncMock(return_value=jid)
        out = await retry_episode_step(uuid4(), step="voice", settings=_settings(), svc=svc)
        assert out.job_id == jid
        assert out.step == "voice"

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.retry_step = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await retry_episode_step(uuid4(), step="voice", settings=_settings(), svc=svc)
        assert exc.value.status_code == 404

    async def test_concurrency_429(self) -> None:
        svc = MagicMock()
        svc.retry_step = AsyncMock(side_effect=ConcurrencyCapReachedError("x"))
        with pytest.raises(HTTPException) as exc:
            await retry_episode_step(uuid4(), step="voice", settings=_settings(), svc=svc)
        assert exc.value.status_code == 429


# ── GET /{id}/script ───────────────────────────────────────────────


class TestGetScript:
    async def test_returns_script(self) -> None:
        svc = MagicMock()
        svc.get_script = AsyncMock(return_value={"scenes": []})
        out = await get_episode_script(uuid4(), svc=svc)
        assert out == {"scenes": []}

    async def test_returns_none_for_unscripted_episode(self) -> None:
        svc = MagicMock()
        svc.get_script = AsyncMock(return_value=None)
        out = await get_episode_script(uuid4(), svc=svc)
        assert out is None

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get_script = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_episode_script(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── PUT /{id}/script ───────────────────────────────────────────────


class TestUpdateScript:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.update_script = AsyncMock(return_value={"scenes": []})
        out = await update_episode_script(uuid4(), ScriptUpdate(script={"scenes": []}), svc=svc)
        assert out == {"scenes": []}

    async def test_validation_422(self) -> None:
        svc = MagicMock()
        svc.update_script = AsyncMock(side_effect=ScriptValidationError("missing keys"))
        with pytest.raises(HTTPException) as exc:
            await update_episode_script(uuid4(), ScriptUpdate(script={}), svc=svc)
        assert exc.value.status_code == 422

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update_script = AsyncMock(side_effect=EpisodeNotFoundError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_episode_script(uuid4(), ScriptUpdate(script={}), svc=svc)
        assert exc.value.status_code == 404


# ── PUT /{id}/scenes/{n} ───────────────────────────────────────────


class TestUpdateScene:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.update_scene = AsyncMock(return_value={"scene_number": 1})
        out = await update_scene(uuid4(), 1, {"narration": "new"}, svc=svc)
        assert out["scene"]["scene_number"] == 1

    async def test_no_script_404(self) -> None:
        svc = MagicMock()
        svc.update_scene = AsyncMock(side_effect=EpisodeNoScriptError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_scene(uuid4(), 1, {}, svc=svc)
        assert exc.value.status_code == 404

    async def test_scene_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update_scene = AsyncMock(side_effect=SceneNotFoundError(99))
        with pytest.raises(HTTPException) as exc:
            await update_scene(uuid4(), 99, {}, svc=svc)
        assert exc.value.status_code == 404
        assert "99" in exc.value.detail


# ── DELETE /{id}/scenes/{n} ────────────────────────────────────────


class TestDeleteScene:
    async def test_success_returns_remaining_count(self) -> None:
        svc = MagicMock()
        svc.delete_scene = AsyncMock(return_value=(5, 3))
        out = await delete_scene(uuid4(), 2, svc=svc)
        assert out["remaining_scenes"] == 5
        assert out["media_assets_deleted"] == 3

    async def test_no_script_404(self) -> None:
        svc = MagicMock()
        svc.delete_scene = AsyncMock(side_effect=EpisodeNoScriptError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_scene(uuid4(), 1, svc=svc)
        assert exc.value.status_code == 404

    async def test_scene_not_found_404(self) -> None:
        svc = MagicMock()
        svc.delete_scene = AsyncMock(side_effect=SceneNotFoundError(99))
        with pytest.raises(HTTPException) as exc:
            await delete_scene(uuid4(), 99, svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_422(self) -> None:
        svc = MagicMock()
        svc.delete_scene = AsyncMock(side_effect=ScriptValidationError("would leave 0 scenes"))
        with pytest.raises(HTTPException) as exc:
            await delete_scene(uuid4(), 1, svc=svc)
        assert exc.value.status_code == 422


# ── POST /{id}/scenes/reorder ──────────────────────────────────────


class TestReorderScenes:
    async def test_missing_order_422(self) -> None:
        svc = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await reorder_scenes(uuid4(), {}, svc=svc)
        assert exc.value.status_code == 422

    async def test_non_list_order_422(self) -> None:
        svc = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await reorder_scenes(uuid4(), {"order": "bogus"}, svc=svc)
        assert exc.value.status_code == 422

    async def test_success(self) -> None:
        svc = MagicMock()
        svc.reorder_scenes = AsyncMock(return_value=[3, 1, 2])
        out = await reorder_scenes(uuid4(), {"order": [3, 1, 2]}, svc=svc)
        assert out["order"] == [3, 1, 2]

    async def test_validation_422(self) -> None:
        svc = MagicMock()
        svc.reorder_scenes = AsyncMock(side_effect=ScriptValidationError("dup scene"))
        with pytest.raises(HTTPException) as exc:
            await reorder_scenes(uuid4(), {"order": [1, 1, 2]}, svc=svc)
        assert exc.value.status_code == 422

    async def test_no_script_404(self) -> None:
        svc = MagicMock()
        svc.reorder_scenes = AsyncMock(side_effect=EpisodeNoScriptError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await reorder_scenes(uuid4(), {"order": [1]}, svc=svc)
        assert exc.value.status_code == 404


# ── POST /{id}/scenes/{n}/split + /merge ───────────────────────────


class TestSplitMerge:
    async def test_split_success(self) -> None:
        svc = MagicMock()
        svc.split_scene = AsyncMock(return_value=6)
        out = await split_scene(uuid4(), 1, {"char_offset": 50}, svc=svc)
        assert out["total_scenes"] == 6
        # int coercion happened.
        called_offset = svc.split_scene.call_args.args[2]
        assert called_offset == 50

    async def test_split_omit_char_offset_passes_none(self) -> None:
        svc = MagicMock()
        svc.split_scene = AsyncMock(return_value=6)
        await split_scene(uuid4(), 1, {}, svc=svc)
        assert svc.split_scene.call_args.args[2] is None

    async def test_split_scene_not_found_404(self) -> None:
        svc = MagicMock()
        svc.split_scene = AsyncMock(side_effect=SceneNotFoundError(1))
        with pytest.raises(HTTPException) as exc:
            await split_scene(uuid4(), 1, {}, svc=svc)
        assert exc.value.status_code == 404

    async def test_split_validation_422(self) -> None:
        svc = MagicMock()
        svc.split_scene = AsyncMock(side_effect=ScriptValidationError("char_offset out of range"))
        with pytest.raises(HTTPException) as exc:
            await split_scene(uuid4(), 1, {"char_offset": 9999}, svc=svc)
        assert exc.value.status_code == 422

    async def test_split_no_script_404(self) -> None:
        svc = MagicMock()
        svc.split_scene = AsyncMock(side_effect=EpisodeNoScriptError(uuid4()))
        with pytest.raises(HTTPException) as exc:
            await split_scene(uuid4(), 1, {}, svc=svc)
        assert exc.value.status_code == 404

    async def test_merge_success(self) -> None:
        svc = MagicMock()
        svc.merge_scenes = AsyncMock(return_value=4)
        out = await merge_scenes(uuid4(), {"scene_number": 2}, svc=svc)
        assert out["total_scenes"] == 4
