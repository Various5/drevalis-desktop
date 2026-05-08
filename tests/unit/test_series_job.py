"""Tests for the AI-generate-series arq job (workers/jobs/series.py).

The job orchestrates: cancellation check → LLM call (with JSON
retry) → series row insert → episode rows insert → Redis result
write. Each phase has its own failure mode pinned here.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.series import generate_series_async

# ── Helpers ──────────────────────────────────────────────────────────


def _make_session_factory(session_mock: Any) -> Any:
    class _SF:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return session_mock

        async def __aexit__(self, *_args: Any) -> None:
            return None

    return _SF()


def _make_settings() -> Any:
    s = MagicMock()
    s.encryption_key = "x"
    s.lm_studio_base_url = "http://lm:1234/v1"
    s.lm_studio_default_model = "test-model"
    return s


def _make_redis(initial_status: str | None = None) -> Any:
    """Build a Redis mock whose GET on the job-status key returns
    *initial_status* the FIRST time and ``None`` thereafter — so we can
    pin the cancellation-check branches without race trickery.
    """
    redis = AsyncMock()
    call_count = {"n": 0}

    async def _get(key: str) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 1 and initial_status is not None:
            return initial_status
        return None

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock()
    return redis


def _llm_response(payload: dict[str, Any] | str) -> Any:
    response = MagicMock()
    if isinstance(payload, str):
        response.content = payload
    else:
        response.content = json.dumps(payload)
    return response


def _good_payload() -> dict[str, Any]:
    return {
        "idea": "cooking experiments",
        "episode_count": 3,
        "target_duration_seconds": 30,
    }


def _good_llm_data() -> dict[str, Any]:
    return {
        "name": "Cooking Experiments",
        "description": "fun lab-style cooking",
        "visual_style": "warm bokeh, golden lighting",
        "character_description": "tall chef, red apron",
        "episodes": [
            {"title": "Egg whisperer", "topic": "perfect scrambled eggs"},
            {"title": "Salt math", "topic": "the science of seasoning"},
            {"title": "Knife dance", "topic": "speed mince"},
        ],
    }


def _patch_module(
    *,
    series_repo: Any,
    episode_repo: Any,
    provider: Any,
    settings: Any,
) -> Any:
    """Patch every late-imported module the job references."""

    def _patches() -> list[Any]:
        return [
            patch("drevalis.core.config.Settings", return_value=settings),
            patch(
                "drevalis.repositories.series.SeriesRepository",
                return_value=series_repo,
            ),
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=episode_repo,
            ),
            patch(
                "drevalis.services.llm.OpenAICompatibleProvider",
                return_value=provider,
            ),
        ]

    from contextlib import ExitStack

    es = ExitStack()
    for cm in _patches():
        es.enter_context(cm)
    return es


# ── Cancellation branches ────────────────────────────────────────────


class TestCancellation:
    async def test_cancelled_before_llm_call_returns_cancelled(self) -> None:
        # ``script_job:{job_id}:status`` already says "cancelled" before
        # the job even runs. Job must return immediately without calling
        # the LLM or hitting the DB.
        redis = _make_redis(initial_status="cancelled")
        provider = AsyncMock()
        provider.generate = AsyncMock()  # not called

        session = AsyncMock()
        with _patch_module(
            series_repo=AsyncMock(),
            episode_repo=AsyncMock(),
            provider=provider,
            settings=_make_settings(),
        ):
            result = await generate_series_async(
                {"redis": redis, "session_factory": _make_session_factory(session)},
                "job-1",
                _good_payload(),
            )

        assert result == {"status": "cancelled"}
        provider.generate.assert_not_called()


# ── Success path ─────────────────────────────────────────────────────


class TestSuccess:
    async def test_happy_path_creates_series_and_episodes(self) -> None:
        redis = _make_redis()
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=_llm_response(_good_llm_data()))

        new_series = MagicMock()
        new_series.id = uuid4()
        new_series.name = "Cooking Experiments"

        series_repo = MagicMock()
        series_repo.create = AsyncMock(return_value=new_series)

        episode_repo = MagicMock()
        ep_calls: list[dict[str, Any]] = []

        async def _create_ep(**kwargs: Any) -> Any:
            ep_calls.append(kwargs)
            ep = MagicMock()
            ep.title = kwargs["title"]
            ep.topic = kwargs["topic"]
            return ep

        episode_repo.create = AsyncMock(side_effect=_create_ep)

        session = AsyncMock()
        session.commit = AsyncMock()

        with _patch_module(
            series_repo=series_repo,
            episode_repo=episode_repo,
            provider=provider,
            settings=_make_settings(),
        ):
            result = await generate_series_async(
                {"redis": redis, "session_factory": _make_session_factory(session)},
                "job-1",
                _good_payload(),
            )

        assert result == {"status": "done"}
        # Series row inserted with LLM-supplied fields.
        series_repo.create.assert_awaited_once()
        kwargs = series_repo.create.call_args.kwargs
        assert kwargs["name"] == "Cooking Experiments"
        assert kwargs["visual_style"] == "warm bokeh, golden lighting"
        # Three episodes inserted.
        assert len(ep_calls) == 3
        assert ep_calls[0]["title"] == "Egg whisperer"
        # Result + status keys set in Redis.
        set_keys = [c.args[0] for c in redis.set.call_args_list]
        assert any("script_job:job-1:result" in k for k in set_keys)
        assert any("script_job:job-1:status" in k for k in set_keys)
        # Status set to "done".
        done_call = next(c for c in redis.set.call_args_list if "status" in c.args[0])
        assert done_call.args[1] == "done"
        # DB committed.
        session.commit.assert_awaited_once()

    async def test_episode_count_caps_llm_overshoot(self) -> None:
        # If the LLM hands back more episodes than requested, only the
        # first ``episode_count`` are persisted.
        redis = _make_redis()
        big_data = _good_llm_data()
        big_data["episodes"] = [{"title": f"E{i}", "topic": f"t{i}"} for i in range(20)]
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=_llm_response(big_data))

        series_repo = MagicMock()
        new_series = MagicMock()
        new_series.id = uuid4()
        new_series.name = big_data["name"]
        series_repo.create = AsyncMock(return_value=new_series)

        ep_calls: list[Any] = []
        episode_repo = MagicMock()

        async def _ep(**kwargs: Any) -> Any:
            ep_calls.append(kwargs)
            ep = MagicMock()
            ep.title = kwargs["title"]
            ep.topic = kwargs["topic"]
            return ep

        episode_repo.create = AsyncMock(side_effect=_ep)

        session = AsyncMock()

        with _patch_module(
            series_repo=series_repo,
            episode_repo=episode_repo,
            provider=provider,
            settings=_make_settings(),
        ):
            await generate_series_async(
                {"redis": redis, "session_factory": _make_session_factory(session)},
                "job-1",
                {**_good_payload(), "episode_count": 5},
            )

        # Capped at 5, not 20.
        assert len(ep_calls) == 5

    async def test_long_series_name_truncated_to_255(self) -> None:
        redis = _make_redis()
        data = _good_llm_data()
        data["name"] = "X" * 400
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=_llm_response(data))

        series_repo = MagicMock()
        new_series = MagicMock()
        new_series.id = uuid4()
        new_series.name = "X" * 255
        series_repo.create = AsyncMock(return_value=new_series)

        episode_repo = MagicMock()
        episode_repo.create = AsyncMock(return_value=MagicMock(title="t", topic=""))

        session = AsyncMock()

        with _patch_module(
            series_repo=series_repo,
            episode_repo=episode_repo,
            provider=provider,
            settings=_make_settings(),
        ):
            await generate_series_async(
                {"redis": redis, "session_factory": _make_session_factory(session)},
                "job-1",
                _good_payload(),
            )

        kwargs = series_repo.create.call_args.kwargs
        assert len(kwargs["name"]) == 255


# ── LLM JSON-retry branches ──────────────────────────────────────────


class TestJsonRetry:
    async def test_invalid_json_retries_up_to_3_times_then_fails(self) -> None:
        # The retry loop runs ``max_retries + 1`` = 3 attempts. If every
        # attempt returns malformed JSON, the job fails with the
        # underlying parse error.
        redis = _make_redis()
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=_llm_response("not json at all"))

        session = AsyncMock()

        with _patch_module(
            series_repo=AsyncMock(),
            episode_repo=AsyncMock(),
            provider=provider,
            settings=_make_settings(),
        ):
            result = await generate_series_async(
                {"redis": redis, "session_factory": _make_session_factory(session)},
                "job-1",
                _good_payload(),
            )

        assert result["status"] == "failed"
        assert provider.generate.await_count == 3
        # Failure status written to Redis.
        status_calls = [c for c in redis.set.call_args_list if "status" in c.args[0]]
        assert any(c.args[1] == "failed" for c in status_calls)

    async def test_recovers_on_second_attempt(self) -> None:
        redis = _make_redis()
        responses = [
            _llm_response("garbage"),
            _llm_response(_good_llm_data()),
        ]
        provider = AsyncMock()
        provider.generate = AsyncMock(side_effect=responses)

        new_series = MagicMock()
        new_series.id = uuid4()
        new_series.name = "Cooking Experiments"

        series_repo = MagicMock()
        series_repo.create = AsyncMock(return_value=new_series)
        episode_repo = MagicMock()
        episode_repo.create = AsyncMock(return_value=MagicMock(title="t", topic=""))
        session = AsyncMock()

        with _patch_module(
            series_repo=series_repo,
            episode_repo=episode_repo,
            provider=provider,
            settings=_make_settings(),
        ):
            result = await generate_series_async(
                {"redis": redis, "session_factory": _make_session_factory(session)},
                "job-1",
                _good_payload(),
            )

        assert result["status"] == "done"
        assert provider.generate.await_count == 2

    async def test_response_missing_required_keys_treated_as_invalid(self) -> None:
        # LLM returns valid JSON but without the contract-required keys.
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=_llm_response({"unrelated": "x"}))

        with _patch_module(
            series_repo=AsyncMock(),
            episode_repo=AsyncMock(),
            provider=provider,
            settings=_make_settings(),
        ):
            result = await generate_series_async(
                {
                    "redis": _make_redis(),
                    "session_factory": _make_session_factory(AsyncMock()),
                },
                "job-1",
                _good_payload(),
            )
        assert result["status"] == "failed"


# ── Outer exception handling ────────────────────────────────────────


class TestExceptionHandling:
    async def test_unexpected_exception_writes_failed_status(self) -> None:
        redis = _make_redis()
        provider = AsyncMock()
        provider.generate = AsyncMock(side_effect=RuntimeError("LM Studio down"))

        session = AsyncMock()

        with _patch_module(
            series_repo=AsyncMock(),
            episode_repo=AsyncMock(),
            provider=provider,
            settings=_make_settings(),
        ):
            result = await generate_series_async(
                {"redis": redis, "session_factory": _make_session_factory(session)},
                "job-1",
                _good_payload(),
            )

        assert result["status"] == "failed"
        assert "LM Studio down" in result.get("error", "")
        # Error stored in Redis for the polling UI.
        error_calls = [c for c in redis.set.call_args_list if "error" in c.args[0]]
        assert error_calls
        assert "LM Studio down" in error_calls[0].args[1]
