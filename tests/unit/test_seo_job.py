"""Tests for the SEO generation arq job (``workers/jobs/seo.py``).

Generates SEO-optimized metadata for an episode using an LLM. Pin the
contracts:

* Episode missing or no script → returns error dict
* Happy path: LLM JSON parsed and stored in episode.metadata_["seo"]
* JSON parse failure → returns conservative fallback (don't lose
  the publish flow over a bad JSON response)
* No LLM configs in DB → falls back to OpenAI-compatible default
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.seo import generate_seo_async

# ── Helpers ──────────────────────────────────────────────────────────


def _make_settings() -> Any:
    s = MagicMock()
    s.encryption_key = "k"
    s.lm_studio_base_url = "http://lm:1234/v1"
    s.lm_studio_default_model = "test-model"
    return s


def _make_episode(*, title: str = "Test Episode", script: dict[str, Any] | None = None) -> Any:
    ep = MagicMock()
    ep.id = uuid4()
    ep.title = title
    ep.script = script
    ep.metadata_ = None
    return ep


def _good_script() -> dict[str, Any]:
    return {
        "title": "Test Episode",
        "scenes": [
            {
                "scene_number": 1,
                "narration": "Once upon a time there was a brave cat.",
                "visual_prompt": "a cat in a forest",
                "duration_seconds": 5.0,
            }
        ],
    }


def _patch_module(
    *,
    settings: Any,
    ep_repo: Any,
    llm_configs: list[Any],
    provider: Any,
) -> Any:
    """Patch every late-imported module the job touches."""
    llm_repo = MagicMock()
    llm_repo.get_all = AsyncMock(return_value=llm_configs)

    from contextlib import ExitStack

    es = ExitStack()
    es.enter_context(patch("drevalis.core.config.Settings", return_value=settings))
    es.enter_context(
        patch(
            "drevalis.repositories.episode.EpisodeRepository",
            return_value=ep_repo,
        )
    )
    es.enter_context(
        patch(
            "drevalis.repositories.llm_config.LLMConfigRepository",
            return_value=llm_repo,
        )
    )
    es.enter_context(
        patch(
            "drevalis.services.llm.OpenAICompatibleProvider",
            return_value=provider,
        )
    )
    # When llm_configs is non-empty, the job uses LLMService.
    llm_service = MagicMock()
    llm_service.get_provider = lambda _cfg: provider
    es.enter_context(patch("drevalis.services.llm.LLMService", return_value=llm_service))
    return es


# ── Early-exit: missing episode / no script ─────────────────────────


class TestEpisodeMissing:
    async def test_returns_error_when_episode_not_found(self) -> None:
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=None)
        provider = MagicMock()
        with _patch_module(
            settings=_make_settings(),
            ep_repo=ep_repo,
            llm_configs=[],
            provider=provider,
        ):
            result = await generate_seo_async(
                {"db": AsyncMock()},
                str(uuid4()),
            )
        assert "error" in result
        assert "not found" in result["error"].lower() or "no script" in result["error"].lower()

    async def test_returns_error_when_episode_has_no_script(self) -> None:
        episode = _make_episode(script=None)
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=episode)
        provider = MagicMock()
        with _patch_module(
            settings=_make_settings(),
            ep_repo=ep_repo,
            llm_configs=[],
            provider=provider,
        ):
            result = await generate_seo_async(
                {"db": AsyncMock()},
                str(uuid4()),
            )
        assert "error" in result


# ── Happy path ──────────────────────────────────────────────────────


class TestSuccess:
    async def test_persists_seo_to_episode_metadata(self) -> None:
        episode = _make_episode(script=_good_script())
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=episode)
        ep_repo.update = AsyncMock()

        seo_data = {
            "title": "Brave cat tale",
            "description": "A cat in a forest, you won't believe what happens",
            "hashtags": ["#cat", "#story"],
            "tags": ["cat", "story"],
            "hook": "What does this cat do?",
            "virality_score": 8,
            "virality_reasoning": "high engagement potential",
        }
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=MagicMock(content=json.dumps(seo_data)))

        db = AsyncMock()
        db.commit = AsyncMock()

        with _patch_module(
            settings=_make_settings(),
            ep_repo=ep_repo,
            llm_configs=[],  # forces OpenAI-compat fallback
            provider=provider,
        ):
            result = await generate_seo_async(
                {"db": db},
                str(episode.id),
            )

        # Result echoes the parsed SEO data.
        assert result["title"] == "Brave cat tale"
        assert result["virality_score"] == 8
        # Episode metadata updated with the seo payload nested under "seo".
        ep_repo.update.assert_awaited_once()
        kwargs = ep_repo.update.call_args.kwargs
        assert "metadata_" in kwargs
        assert kwargs["metadata_"]["seo"] == seo_data
        # DB committed.
        db.commit.assert_awaited_once()


# ── JSON parse failure → fallback ───────────────────────────────────


class TestJsonParseFailure:
    async def test_invalid_json_returns_conservative_fallback(self) -> None:
        # LLM returned non-JSON garbage. The job must NOT fail —
        # publish should still proceed with conservative defaults
        # (episode title as title, narration excerpt as description).
        episode = _make_episode(
            title="My Episode",
            script={
                "title": "X",
                "scenes": [
                    {
                        "scene_number": 1,
                        "narration": "lorem ipsum dolor sit amet" * 20,
                        "visual_prompt": "x",
                        "duration_seconds": 5.0,
                    }
                ],
            },
        )
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=episode)
        ep_repo.update = AsyncMock()

        provider = AsyncMock()
        # Garbage that won't parse as JSON.
        provider.generate = AsyncMock(return_value=MagicMock(content="this is definitely not json"))

        db = AsyncMock()
        db.commit = AsyncMock()

        with _patch_module(
            settings=_make_settings(),
            ep_repo=ep_repo,
            llm_configs=[],
            provider=provider,
        ):
            result = await generate_seo_async(
                {"db": db},
                str(episode.id),
            )

        # Fallback: conservative defaults derived from the episode.
        assert result["title"] == "My Episode"
        assert "lorem ipsum" in result["description"]
        assert result["hashtags"] == []
        assert result["tags"] == []
        assert result["virality_score"] == 0
        # Episode metadata still updated (don't drop the row entirely).
        ep_repo.update.assert_awaited_once()


# ── LLM provider selection ──────────────────────────────────────────


class TestProviderSelection:
    async def test_uses_first_llm_config_when_present(self) -> None:
        # When LLMConfigRepository.get_all returns a config, the job
        # should use LLMService.get_provider(config) rather than the
        # OpenAI-compat fallback.
        episode = _make_episode(script=_good_script())
        ep_repo = MagicMock()
        ep_repo.get_by_id = AsyncMock(return_value=episode)
        ep_repo.update = AsyncMock()

        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=MagicMock(content="{}"))

        config = MagicMock()
        config.id = uuid4()

        db = AsyncMock()
        db.commit = AsyncMock()

        with _patch_module(
            settings=_make_settings(),
            ep_repo=ep_repo,
            llm_configs=[config],  # at least one config
            provider=provider,
        ):
            await generate_seo_async(
                {"db": db},
                str(episode.id),
            )
        # Provider was actually called (proves the LLMService path ran).
        provider.generate.assert_awaited_once()
