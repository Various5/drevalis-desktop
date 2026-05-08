"""Tests for ``generate_script_async`` — the arq job that wraps
``_generate_audiobook_script_text`` with DB lookup, Redis status
persistence, and exception capture.

Pin:

* Early cancellation (status flips before LLM starts) → returns
  cancelled WITHOUT calling the LLM.
* LLM provider chosen from the first DB LLMConfig; falls back to
  the LM Studio default URL when no configs are registered.
* Encrypted API key decrypted before passing to provider.
* `_generate_audiobook_script_text` returns None (cancelled mid-LLM)
  → returns cancelled without writing the result.
* Happy path persists `script_job:{id}:result` (JSON) and
  `script_job:{id}:status` = "done" with 1h TTL.
* Title, chapters, characters, word_count, estimated_minutes all
  parsed from the script text. SFX tags filtered from characters.
* Any exception inside the body → status="failed" + error_message
  persisted with 500-char cap. Returns status=failed.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.audiobook import generate_script_async


def _ctx() -> tuple[dict[str, Any], Any, Any]:
    """Build a worker ctx with redis + a session-factory whose
    LLMConfigRepository.get_all returns whatever the test patches."""
    redis = AsyncMock()
    session = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    return {"redis": redis, "session_factory": _sf}, redis, session


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "concept": "A short tale about a dragon",
        "target_minutes": 10,
        "mood": "epic",
        "characters": [
            {"name": "Narrator", "description": "Omniscient narrator"},
            {"name": "Bram", "description": "Hero"},
        ],
    }
    base.update(overrides)
    return base


# ── Early cancellation ─────────────────────────────────────────────


class TestEarlyCancellation:
    async def test_status_cancelled_short_circuits_no_llm_call(self) -> None:
        ctx, redis, _ = _ctx()
        # Initial status check returns "cancelled" → bail without
        # constructing an LLM provider.
        redis.get = AsyncMock(return_value="cancelled")

        with patch(
            "drevalis.repositories.llm_config.LLMConfigRepository",
            side_effect=AssertionError("must not be reached"),
        ):
            out = await generate_script_async(ctx, "abc", _payload())
        assert out == {"status": "cancelled"}


# ── LLM provider resolution ────────────────────────────────────────


class TestProviderResolution:
    async def test_db_config_used_when_present(self) -> None:
        ctx, redis, _ = _ctx()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        cfg = SimpleNamespace(
            id=uuid4(),
            base_url="http://my-llm:1234/v1",
            model_name="qwen2.5-7b",
            api_key_encrypted=b"opaque",
        )
        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[cfg])

        with (
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.core.security.decrypt_value",
                return_value="real-key",
            ),
            patch(
                "drevalis.workers.jobs.audiobook._generate_audiobook_script_text",
                AsyncMock(return_value="Title\n\n## Chapter 1\n[Narrator] hi"),
            ),
            patch(
                "drevalis.services.llm.OpenAICompatibleProvider",
            ) as provider_class,
        ):
            await generate_script_async(ctx, "abc", _payload())

        # Provider built with DB config's URL + model + decrypted key.
        provider_class.assert_called_once()
        kwargs = provider_class.call_args.kwargs
        assert kwargs["base_url"] == "http://my-llm:1234/v1"
        assert kwargs["model"] == "qwen2.5-7b"
        assert kwargs["api_key"] == "real-key"

    async def test_no_db_configs_falls_back_to_lm_studio_default(
        self,
    ) -> None:
        ctx, redis, _ = _ctx()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[])

        settings_obj = MagicMock()
        settings_obj.lm_studio_base_url = "http://lmstudio:1234/v1"
        settings_obj.lm_studio_default_model = "default-model"
        import base64

        settings_obj.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()

        with (
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=repo,
            ),
            patch("drevalis.core.config.Settings", return_value=settings_obj),
            patch(
                "drevalis.workers.jobs.audiobook._generate_audiobook_script_text",
                AsyncMock(return_value="Title\n\n## Chapter 1\n[Narrator] hi"),
            ),
            patch(
                "drevalis.services.llm.OpenAICompatibleProvider",
            ) as provider_class,
        ):
            await generate_script_async(ctx, "abc", _payload())

        # Pin: only TWO `Settings()` invocations happen — but the
        # constructor was passed the LM Studio default URL + model.
        kwargs = provider_class.call_args.kwargs
        assert kwargs["base_url"] == "http://lmstudio:1234/v1"
        assert kwargs["model"] == "default-model"


# ── Mid-LLM cancellation ──────────────────────────────────────────


class TestMidLLMCancellation:
    async def test_returns_cancelled_when_helper_returns_none(
        self,
    ) -> None:
        ctx, redis, _ = _ctx()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[])

        with (
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.workers.jobs.audiobook._generate_audiobook_script_text",
                AsyncMock(return_value=None),  # cancelled mid-LLM
            ),
        ):
            out = await generate_script_async(ctx, "abc", _payload())
        assert out == {"status": "cancelled"}
        # Pin: when cancelled mid-LLM, the result key is NOT written.
        # (status="done" would clobber the wizard's UI.)
        keys_set = {c.args[0] for c in redis.set.await_args_list}
        assert "script_job:abc:result" not in keys_set
        assert "script_job:abc:status" not in keys_set


# ── Happy path ────────────────────────────────────────────────────


class TestHappyPath:
    async def test_persists_result_and_status_with_ttl(self) -> None:
        ctx, redis, _ = _ctx()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[])

        # Realistic script with title, chapters, mixed [Speaker] tags
        # including [SFX: ...] which MUST be filtered out.
        script = (
            "The Last Dragon\n\n"
            "## Chapter 1: Awakening\n\n"
            "[Narrator] The cave was silent.\n\n"
            "[Bram] Hello?\n\n"
            "[SFX: rumble | dur=3]\n\n"
            "## Chapter 2: Flight\n\n"
            "[Narrator] He spread his wings.\n\n"
            "[Sfx: thunder]\n"  # case-insensitive sfx filter
        )

        with (
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.workers.jobs.audiobook._generate_audiobook_script_text",
                AsyncMock(return_value=script),
            ),
        ):
            out = await generate_script_async(ctx, "abc", _payload())

        assert out == {"status": "done"}

        # Pin: redis.set called for both `:result` and `:status`.
        set_calls = {c.args[0]: c for c in redis.set.await_args_list}
        assert "script_job:abc:result" in set_calls
        assert "script_job:abc:status" in set_calls
        # Both with 1h TTL.
        assert set_calls["script_job:abc:result"].kwargs["ex"] == 3600
        assert set_calls["script_job:abc:status"].kwargs["ex"] == 3600

        # Result payload parsed correctly.
        result_json = set_calls["script_job:abc:result"].args[1]
        result = json.loads(result_json)
        assert result["title"] == "The Last Dragon"
        # Pin: chapters extracted via `## ` prefix.
        assert result["chapters"] == [
            "Chapter 1: Awakening",
            "Chapter 2: Flight",
        ]
        # Pin: SFX tags filtered (case-insensitive); only real
        # speakers retained.
        assert "Narrator" in result["characters"]
        assert "Bram" in result["characters"]
        assert all(not c.lower().startswith("sfx") for c in result["characters"])
        # Word count + estimated_minutes derived from script text.
        assert result["word_count"] > 0
        assert result["estimated_minutes"] == round(result["word_count"] / 150, 1)

    async def test_empty_script_yields_untitled(self) -> None:
        ctx, redis, _ = _ctx()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        repo = MagicMock()
        repo.get_all = AsyncMock(return_value=[])

        with (
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=repo,
            ),
            patch(
                "drevalis.workers.jobs.audiobook._generate_audiobook_script_text",
                AsyncMock(return_value=""),
            ),
        ):
            out = await generate_script_async(ctx, "abc", _payload())
        # Pin: empty script still goes "done" (the worker doesn't
        # second-guess the LLM); title falls back to "" or "Untitled".
        assert out["status"] == "done"


# ── Failure path ──────────────────────────────────────────────────


class TestFailurePath:
    async def test_exception_persists_failed_status(self) -> None:
        ctx, redis, _ = _ctx()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        repo = MagicMock()
        repo.get_all = AsyncMock(side_effect=ConnectionError("DB down"))

        with patch(
            "drevalis.repositories.llm_config.LLMConfigRepository",
            return_value=repo,
        ):
            out = await generate_script_async(ctx, "abc", _payload())

        assert out["status"] == "failed"
        assert "DB down" in out["error"]

        # Pin: error + status keys written with 1h TTL.
        set_calls = {c.args[0]: c for c in redis.set.await_args_list}
        assert "script_job:abc:error" in set_calls
        assert "script_job:abc:status" in set_calls
        assert set_calls["script_job:abc:status"].args[1] == "failed"
        # Error message persisted.
        assert "DB down" in set_calls["script_job:abc:error"].args[1]

    async def test_error_message_capped_at_500_chars(self) -> None:
        ctx, redis, _ = _ctx()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        long_error = "X" * 1000
        repo = MagicMock()
        repo.get_all = AsyncMock(side_effect=RuntimeError(long_error))

        with patch(
            "drevalis.repositories.llm_config.LLMConfigRepository",
            return_value=repo,
        ):
            await generate_script_async(ctx, "abc", _payload())

        set_calls = {c.args[0]: c for c in redis.set.await_args_list}
        persisted_error = set_calls["script_job:abc:error"].args[1]
        # Pin: persisted error message capped at 500 chars so it fits
        # the Redis key payload + UI display without truncation
        # ambiguity.
        assert len(persisted_error) == 500
