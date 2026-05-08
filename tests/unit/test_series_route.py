"""Tests for ``api/routes/series.py``.

Series CRUD + AI generation (sync + async). Pin:

* `update_series`: NotFoundError → 404, ValidationError → 422,
  **SeriesFieldLockedError → 409 with structured detail** including
  `locked_fields` and `non_draft_episode_count` so the UI can render
  "Duplicate the series; you can't change content_format after the
  first episode is past draft".
* `generate_sync`: ValidationError (LLM upstream) → 502; NotFound
  (LLM config missing) → 404.
* Async generate: writes initial Redis status + input + enqueues the
  arq job; status endpoint surfaces `done` with parsed result, or
  `failed` with the error message.
* `cancel_series_generate_job`: 404 when key absent, sets cancelled
  status when present.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.series import (
    AddEpisodesRequest,
    SeriesGenerateRequest,
    _service,
    add_episodes_ai,
    cancel_series_generate_job,
    create_series,
    delete_series,
    generate_series,
    generate_series_sync,
    get_series,
    get_series_generate_job,
    list_series,
    suggest_trending_topics,
    update_series,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.series import SeriesCreate, SeriesUpdate
from drevalis.services.series import SeriesFieldLockedError, SeriesService


def _settings() -> Any:
    s = MagicMock()
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    return s


def _make_series(**overrides: Any) -> Any:
    """Build a series-shaped object with every SeriesResponse field set
    to a valid type so ``model_validate(...)`` doesn't trip on stray
    MagicMock children."""
    from types import SimpleNamespace

    base: dict[str, Any] = {
        "id": uuid4(),
        "name": "Test Series",
        "description": None,
        "voice_profile_id": None,
        "comfyui_server_id": None,
        "comfyui_workflow_id": None,
        "llm_config_id": None,
        "script_prompt_template_id": None,
        "visual_prompt_template_id": None,
        "visual_style": "",
        "character_description": "",
        "target_duration_seconds": 30,
        "default_language": "en-US",
        "caption_style": None,
        "negative_prompt": None,
        "scene_mode": "image",
        "video_comfyui_workflow_id": None,
        "music_mood": None,
        "music_volume_db": -14.0,
        "music_enabled": True,
        "youtube_channel_id": None,
        "content_format": "shorts",
        "target_duration_minutes": None,
        "chapter_enabled": True,
        "scenes_per_chapter": 8,
        "transition_style": None,
        "transition_duration": 0.5,
        "duration_match_strategy": "hold_frame",
        "base_seed": None,
        "intro_template": None,
        "outro_template": None,
        "visual_consistency_prompt": None,
        "aspect_ratio": "9:16",
        "thumbnail_mode": "smart_frame",
        "thumbnail_comfyui_workflow_id": None,
        "music_bpm": None,
        "music_key": None,
        "audio_preset": None,
        "video_clip_duration": 5,
        "reference_asset_ids": None,
        "character_lock": None,
        "style_lock": None,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_episode(title: str = "Ep 1", topic: str | None = "topic") -> Any:
    e = MagicMock()
    e.title = title
    e.topic = topic
    return e


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service(self) -> None:
        svc = _service(db=AsyncMock(), settings=_settings())
        assert isinstance(svc, SeriesService)


# ── POST /generate (async) ─────────────────────────────────────────


class TestGenerateAsync:
    async def test_seeds_redis_and_enqueues(self) -> None:
        # Pin: route writes the `script_job:<id>:status` and `:input`
        # keys before the GET endpoint can be polled, so the UI never
        # sees a "job not found" race window between enqueue and the
        # worker's first write.
        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.aclose = AsyncMock()
        arq = MagicMock()
        arq.enqueue_job = AsyncMock()

        with (
            patch("drevalis.api.routes.series.Redis", return_value=redis),
            patch("drevalis.api.routes.series.get_pool", return_value=MagicMock()),
            patch("drevalis.api.routes.series.get_arq_pool", return_value=arq),
        ):
            out = await generate_series(
                payload=SeriesGenerateRequest(
                    idea="A series about retro gaming history",
                    episode_count=10,
                )
            )

        assert out.status == "generating"
        assert out.job_id  # uuid string
        # Both writes happened with TTLs.
        status_call, input_call = redis.set.await_args_list
        assert status_call.args[1] == "generating"
        assert status_call.kwargs["ex"] == 3600
        # Input payload includes the idea so the cancel UI can show
        # what's being generated.
        input_payload = json.loads(input_call.args[1])
        assert input_payload["type"] == "series"
        assert "retro" in input_payload["idea"]
        # arq job enqueued with the same job_id.
        arq.enqueue_job.assert_awaited_once()
        args = arq.enqueue_job.call_args.args
        assert args[0] == "generate_series_async"
        assert args[1] == out.job_id

    async def test_redis_aclose_in_finally_even_on_arq_failure(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.aclose = AsyncMock()
        arq = MagicMock()
        arq.enqueue_job = AsyncMock(side_effect=ConnectionError("redis pool out"))

        with (
            patch("drevalis.api.routes.series.Redis", return_value=redis),
            patch("drevalis.api.routes.series.get_pool", return_value=MagicMock()),
            patch("drevalis.api.routes.series.get_arq_pool", return_value=arq),
        ):
            with pytest.raises(ConnectionError):
                await generate_series(payload=SeriesGenerateRequest(idea="bla bla bla bla bla"))
        # Cleanup MUST run even if enqueue raised.
        redis.aclose.assert_awaited_once()


# ── GET /generate-job/{id} ─────────────────────────────────────────


class TestGetJobStatus:
    async def test_404_when_status_missing(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.api.routes.series.Redis", return_value=redis),
            patch("drevalis.api.routes.series.get_pool", return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_series_generate_job("missing-job-id")
        assert exc.value.status_code == 404
        # aclose still runs even on raise.
        redis.aclose.assert_awaited_once()

    async def test_done_returns_parsed_result(self) -> None:
        redis = AsyncMock()
        # First call: status. Second call: result.
        sid = uuid4()
        result_payload = {
            "series_id": str(sid),
            "series_name": "Retro Hour",
            "episode_count": 2,
            "episodes": [
                {"title": "Ep1", "topic": "Atari"},
                {"title": "Ep2", "topic": "NES"},
            ],
        }
        redis.get = AsyncMock(side_effect=[b"done", json.dumps(result_payload).encode()])
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.api.routes.series.Redis", return_value=redis),
            patch("drevalis.api.routes.series.get_pool", return_value=MagicMock()),
        ):
            out = await get_series_generate_job("abc")
        assert out.status == "done"
        assert out.result is not None
        assert out.result.series_name == "Retro Hour"

    async def test_failed_returns_error(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=[b"failed", b"LLM upstream timeout"])
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.api.routes.series.Redis", return_value=redis),
            patch("drevalis.api.routes.series.get_pool", return_value=MagicMock()),
        ):
            out = await get_series_generate_job("abc")
        assert out.status == "failed"
        assert out.error == "LLM upstream timeout"

    async def test_string_status_payload_handled(self) -> None:
        # Some redis client configs decode automatically — pin: route
        # accepts both bytes AND str without crashing.
        redis = AsyncMock()
        redis.get = AsyncMock(return_value="generating")
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.api.routes.series.Redis", return_value=redis),
            patch("drevalis.api.routes.series.get_pool", return_value=MagicMock()),
        ):
            out = await get_series_generate_job("abc")
        assert out.status == "generating"
        assert out.result is None


# ── POST /generate-job/{id}/cancel ────────────────────────────────


class TestCancelJob:
    async def test_404_when_job_missing(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.api.routes.series.Redis", return_value=redis),
            patch("drevalis.api.routes.series.get_pool", return_value=MagicMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await cancel_series_generate_job("nope")
        assert exc.value.status_code == 404

    async def test_existing_job_set_cancelled(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"generating")
        redis.set = AsyncMock()
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.api.routes.series.Redis", return_value=redis),
            patch("drevalis.api.routes.series.get_pool", return_value=MagicMock()),
        ):
            out = await cancel_series_generate_job("abc")
        assert out["message"] == "Cancelled"
        # The status key was set to "cancelled" with a TTL.
        redis.set.assert_awaited_once()
        args, kwargs = redis.set.await_args
        assert args[1] == "cancelled"
        assert kwargs["ex"] == 3600


# ── POST /generate-sync ────────────────────────────────────────────


class TestGenerateSync:
    async def test_success_returns_episode_list(self) -> None:
        svc = MagicMock()
        s = _make_series(name="Retro")
        svc.generate_series_sync = AsyncMock(
            return_value=(s, [_make_episode("E1", "atari"), _make_episode("E2", None)])
        )
        out = await generate_series_sync(
            payload=SeriesGenerateRequest(idea="A retro gaming series, please ten episodes"),
            svc=svc,
        )
        assert out.episode_count == 2
        # None topic coerced to "" for the response model.
        assert out.episodes[1].topic == ""

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.generate_series_sync = AsyncMock(side_effect=NotFoundError("llm_config", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await generate_series_sync(
                payload=SeriesGenerateRequest(idea="long enough idea string"),
                svc=svc,
            )
        assert exc.value.status_code == 404

    async def test_validation_error_maps_to_502(self) -> None:
        # ValidationError on this surface means the LLM returned an
        # unparseable response. 502 Bad Gateway is the right code: WE
        # didn't fail, our upstream did.
        svc = MagicMock()
        svc.generate_series_sync = AsyncMock(
            side_effect=ValidationError("LLM returned malformed JSON")
        )
        with pytest.raises(HTTPException) as exc:
            await generate_series_sync(
                payload=SeriesGenerateRequest(idea="long enough idea string"),
                svc=svc,
            )
        assert exc.value.status_code == 502


# ── List / Create / Get / Delete ──────────────────────────────────


class TestCrud:
    async def test_list_attaches_episode_count(self) -> None:
        svc = MagicMock()
        a, b = _make_series(name="A"), _make_series(name="B")
        svc.list_with_episode_counts = AsyncMock(return_value=[(a, 5), (b, 0)])
        out = await list_series(svc=svc)
        assert [s.episode_count for s in out] == [5, 0]

    async def test_create(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(return_value=_make_series(name="X"))
        out = await create_series(SeriesCreate(name="X"), svc=svc)
        assert out.name == "X"

    async def test_get_success(self) -> None:
        svc = MagicMock()
        s = _make_series()
        svc.get_with_relations = AsyncMock(return_value=s)
        out = await get_series(s.id, svc=svc)
        assert out.id == s.id

    async def test_get_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get_with_relations = AsyncMock(side_effect=NotFoundError("series", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_series(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_delete_success(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_series(uuid4(), svc=svc)
        svc.delete.assert_awaited_once()

    async def test_delete_not_found_404(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("series", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_series(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── PUT /{id} (update) ────────────────────────────────────────────


class TestUpdateSeries:
    async def test_success(self) -> None:
        svc = MagicMock()
        s = _make_series(name="renamed")
        svc.update = AsyncMock(return_value=s)
        out = await update_series(s.id, SeriesUpdate(name="renamed"), svc=svc)
        assert out.name == "renamed"
        # exclude_unset semantics: only `name` reaches the service.
        kwargs = svc.update.call_args.args[1]
        assert kwargs == {"name": "renamed"}

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=NotFoundError("series", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_series(uuid4(), SeriesUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_422(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ValidationError("bad value"))
        with pytest.raises(HTTPException) as exc:
            await update_series(uuid4(), SeriesUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 422

    async def test_field_locked_409_with_structured_detail(self) -> None:
        # Pin: changing content_format / aspect_ratio after the series
        # has non-draft episodes → 409 carrying ``locked_fields`` and
        # ``non_draft_episode_count`` so the UI can render "Duplicate
        # the series; X episode(s) past draft" precisely.
        svc = MagicMock()
        svc.update = AsyncMock(
            side_effect=SeriesFieldLockedError(
                locked_fields=["content_format", "aspect_ratio"],
                non_draft_episode_count=3,
            )
        )
        with pytest.raises(HTTPException) as exc:
            await update_series(uuid4(), SeriesUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 409
        detail = exc.value.detail
        assert detail["error"] == "series_field_locked"
        assert detail["locked_fields"] == ["content_format", "aspect_ratio"]
        assert detail["non_draft_episode_count"] == 3


# ── POST /{id}/add-episodes ───────────────────────────────────────


class TestAddEpisodesAI:
    async def test_success(self) -> None:
        svc = MagicMock()
        ids = [uuid4(), uuid4()]
        svc.add_episodes_ai = AsyncMock(return_value=(ids, [{"title": "E1"}, {"title": "E2"}]))
        out = await add_episodes_ai(uuid4(), AddEpisodesRequest(count=2), svc=svc)
        assert "Created 2" in out["message"]
        assert out["episode_ids"] == ids

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.add_episodes_ai = AsyncMock(side_effect=NotFoundError("series", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await add_episodes_ai(uuid4(), AddEpisodesRequest(count=2), svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_error_502(self) -> None:
        # LLM upstream returned junk — 502 Bad Gateway, not 400.
        svc = MagicMock()
        svc.add_episodes_ai = AsyncMock(side_effect=ValidationError("LLM returned malformed JSON"))
        with pytest.raises(HTTPException) as exc:
            await add_episodes_ai(uuid4(), AddEpisodesRequest(count=2), svc=svc)
        assert exc.value.status_code == 502


# ── POST /{id}/trending-topics ────────────────────────────────────


class TestTrendingTopics:
    async def test_success(self) -> None:
        svc = MagicMock()
        sid = uuid4()
        svc.suggest_trending_topics = AsyncMock(return_value=["Topic A", "Topic B"])
        out = await suggest_trending_topics(sid, svc=svc)
        assert out["series_id"] == str(sid)
        assert out["topics"] == ["Topic A", "Topic B"]

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.suggest_trending_topics = AsyncMock(side_effect=NotFoundError("series", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await suggest_trending_topics(uuid4(), svc=svc)
        assert exc.value.status_code == 404
