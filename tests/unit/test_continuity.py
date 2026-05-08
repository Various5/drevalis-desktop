"""Tests for the LLM-driven continuity checker (services/continuity.py).

The checker runs a pre-flight LLM pass on an episode's scene list and
returns a list of ``ContinuityIssue`` to be rendered between scene
cards. Misses here either flood the UI with false positives or silently
swallow real LLM responses, so each parsing branch is pinned.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from drevalis.schemas.script import EpisodeScript, SceneScript
from drevalis.services.continuity import ContinuityIssue, check_continuity


def _scene(n: int, narration: str = "x", visual: str = "y", dur: float = 3.0) -> SceneScript:
    return SceneScript(
        scene_number=n,
        narration=narration,
        visual_prompt=visual,
        duration_seconds=dur,
    )


def _script(n_scenes: int) -> EpisodeScript:
    return EpisodeScript(
        title="t",
        scenes=[_scene(i + 1) for i in range(n_scenes)],
    )


def _llm_with_response(payload: Any) -> tuple[Any, AsyncMock]:
    """Build a stub llm_service whose provider returns *payload* as content."""
    response = AsyncMock()
    response.content = json.dumps(payload) if not isinstance(payload, str) else payload
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value=response)
    llm_service = AsyncMock()
    llm_service.get_provider = lambda _cfg: provider
    return llm_service, provider


# ── ContinuityIssue ──────────────────────────────────────────────────


class TestContinuityIssue:
    def test_to_dict_round_trip(self) -> None:
        issue = ContinuityIssue(
            from_scene=1,
            to_scene=2,
            severity="warn",
            issue="POV jump",
            suggestion="reframe",
        )
        assert issue.to_dict() == {
            "from_scene": 1,
            "to_scene": 2,
            "severity": "warn",
            "issue": "POV jump",
            "suggestion": "reframe",
        }

    def test_frozen_dataclass(self) -> None:
        issue = ContinuityIssue(1, 2, "warn", "x", "y")
        with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError or AttributeError
            issue.severity = "fail"  # type: ignore[misc]


# ── check_continuity ─────────────────────────────────────────────────


class TestCheckContinuity:
    async def test_single_scene_short_circuits_with_no_llm_call(self) -> None:
        script = _script(1)
        llm_service, provider = _llm_with_response({"issues": []})
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert result == []
        provider.generate.assert_not_called()

    async def test_zero_scenes_returns_empty(self) -> None:
        # EpisodeScript requires min_length=1, so build directly.
        script = EpisodeScript.model_construct(title="t", scenes=[])
        llm_service, _ = _llm_with_response({"issues": []})
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert result == []

    async def test_well_formed_response_parsed(self) -> None:
        script = _script(3)
        llm_service, _ = _llm_with_response(
            {
                "issues": [
                    {
                        "from_scene": 1,
                        "to_scene": 2,
                        "severity": "warn",
                        "issue": "tense jump",
                        "suggestion": "rewrite",
                    },
                    {
                        "from_scene": 2,
                        "to_scene": 3,
                        "severity": "fail",
                        "issue": "POV flip",
                        "suggestion": "narrator only",
                    },
                ]
            }
        )
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert len(result) == 2
        assert result[0].from_scene == 1
        assert result[0].severity == "warn"
        assert result[1].severity == "fail"

    async def test_provider_exception_returns_empty(self) -> None:
        script = _script(2)
        provider = AsyncMock()
        provider.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
        llm_service = AsyncMock()
        llm_service.get_provider = lambda _cfg: provider
        # Best-effort pre-flight: any error is swallowed.
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert result == []

    async def test_non_json_response_returns_empty(self) -> None:
        script = _script(2)
        llm_service, _ = _llm_with_response("not a json blob at all")
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert result == []

    async def test_response_capped_at_20_issues(self) -> None:
        script = _script(2)
        many = {
            "issues": [
                {"from_scene": 1, "to_scene": 2, "severity": "warn", "issue": f"#{i}"}
                for i in range(40)
            ]
        }
        llm_service, _ = _llm_with_response(many)
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert len(result) == 20

    async def test_invalid_severity_normalized_to_warn(self) -> None:
        script = _script(2)
        llm_service, _ = _llm_with_response(
            {
                "issues": [
                    {
                        "from_scene": 1,
                        "to_scene": 2,
                        "severity": "BLOCKER",  # not in allowed set
                        "issue": "x",
                    }
                ]
            }
        )
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert result[0].severity == "warn"

    async def test_severity_lowercased(self) -> None:
        script = _script(2)
        llm_service, _ = _llm_with_response(
            {"issues": [{"from_scene": 1, "to_scene": 2, "severity": "FAIL", "issue": "x"}]}
        )
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert result[0].severity == "fail"

    async def test_missing_from_scene_dropped_silently(self) -> None:
        script = _script(2)
        llm_service, _ = _llm_with_response(
            {
                "issues": [
                    {"to_scene": 2, "severity": "warn", "issue": "no from"},
                    {
                        "from_scene": 1,
                        "to_scene": 2,
                        "severity": "warn",
                        "issue": "good",
                    },
                ]
            }
        )
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        # Only the well-formed entry survives.
        assert len(result) == 1
        assert result[0].issue == "good"

    async def test_non_int_scene_number_dropped(self) -> None:
        script = _script(2)
        llm_service, _ = _llm_with_response(
            {
                "issues": [
                    {
                        "from_scene": "bad",
                        "to_scene": 2,
                        "severity": "warn",
                        "issue": "x",
                    },
                ]
            }
        )
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert result == []

    async def test_long_strings_truncated_to_240_chars(self) -> None:
        script = _script(2)
        llm_service, _ = _llm_with_response(
            {
                "issues": [
                    {
                        "from_scene": 1,
                        "to_scene": 2,
                        "severity": "warn",
                        "issue": "x" * 500,
                        "suggestion": "y" * 500,
                    }
                ]
            }
        )
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert len(result[0].issue) == 240
        assert len(result[0].suggestion) == 240

    async def test_missing_issues_key_returns_empty(self) -> None:
        script = _script(2)
        llm_service, _ = _llm_with_response({"unrelated_key": []})
        result = await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        assert result == []

    async def test_passes_json_mode_to_provider(self) -> None:
        script = _script(2)
        llm_service, provider = _llm_with_response({"issues": []})
        await check_continuity(script=script, llm_service=llm_service, llm_config=object())
        # The contract: continuity uses json_mode + low temperature so
        # the response is parseable and stable across calls.
        kwargs = provider.generate.call_args.kwargs
        assert kwargs.get("json_mode") is True
        assert kwargs.get("temperature", 1.0) <= 0.5
