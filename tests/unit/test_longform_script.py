"""Tests for LongFormScriptService — chunked LLM script generation.

The service implements a 3-phase flow:
1. ``_generate_outline`` (one LLM call → outline JSON)
2. ``_generate_chapter_scenes`` (one LLM call per chapter → scene list)
3. ``generate`` orchestrates both, splices results, builds the
   EpisodeScript-compatible payload + chapter metadata.

All tests use an ``AsyncMock`` provider returning canned JSON so
``LongFormScriptService.generate`` runs end-to-end without any
network or model dependency. Reasonable assertions cover:

- Chapter-count auto-calculation when caller passes ``None``
- Outline + chapter call ordering
- Continuity context ("previous_last_scene") wired into chapter 2+
- Scene renumbering across chapter boundaries
- chapters JSONB metadata shape (title / scene-range / mood)
- Visual-consistency prefix prepended to every scene's ``visual_prompt``
- ``_parse_json`` corner cases (markdown fences, embedded prose,
  array-vs-object root, total failure → ValueError)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from drevalis.services.llm import LLMResult
from drevalis.services.longform_script import LongFormScriptService


def _llm_result(payload: Any) -> LLMResult:
    """Wrap a JSON-serialisable payload in an LLMResult."""
    return LLMResult(
        content=json.dumps(payload),
        model="test-model",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )


def _outline(chapter_count: int = 3, scenes_per_chapter: int = 4) -> dict[str, Any]:
    """Build a canned outline with N chapters."""
    return {
        "title": "How Tardigrades Survive Space",
        "hook": "Did you know microscopic creatures can survive the vacuum of space?",
        "description": "A deep dive into tardigrades — nature's most extreme survivors.",
        "hashtags": ["#tardigrades", "#science", "#space"],
        "outro": "Subscribe for more nature mysteries.",
        "chapters": [
            {
                "title": f"Chapter {i + 1}",
                "summary": f"Summary of chapter {i + 1}",
                "key_points": [f"point-{i}-a", f"point-{i}-b"],
                "target_scene_count": scenes_per_chapter,
                "mood": ["epic", "calm", "tense", "mysterious"][i % 4],
                "visual_prompt_hint": f"Visual hint {i + 1}",
            }
            for i in range(chapter_count)
        ],
    }


def _scenes_for_chapter(start_number: int, count: int) -> list[dict[str, Any]]:
    """Build canned scene list for one chapter."""
    return [
        {
            "scene_number": start_number + i,
            "narration": (f"Scene {start_number + i} narration. " * 3).strip(),
            "visual_prompt": f"Visual {start_number + i}: detailed shot",
            "duration_seconds": 10.0,
            "keywords": [f"kw{start_number + i}-a", f"kw{start_number + i}-b"],
        }
        for i in range(count)
    ]


class TestGenerate:
    """End-to-end ``generate()`` flow."""

    async def test_generate_calls_outline_then_one_chapter_per_outline(self) -> None:
        """generate() must issue exactly N+1 LLM calls (1 outline + N chapters)."""
        outline = _outline(chapter_count=3, scenes_per_chapter=4)
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[
                _llm_result(outline),
                _llm_result(_scenes_for_chapter(1, 4)),
                _llm_result(_scenes_for_chapter(5, 4)),
                _llm_result(_scenes_for_chapter(9, 4)),
            ]
        )

        svc = LongFormScriptService(provider=provider)
        result = await svc.generate(
            topic="Tardigrades in space",
            series_description="Edu-content for curious people",
            target_duration_minutes=24,
            chapter_count=3,
            scenes_per_chapter=4,
        )

        assert provider.generate.call_count == 4  # 1 outline + 3 chapters
        assert result["title"] == "How Tardigrades Survive Space"
        assert len(result["chapters"]) == 3
        assert len(result["script"]["scenes"]) == 12

    async def test_chapter_count_auto_derived_from_target_duration(self) -> None:
        """When chapter_count is None, the service uses ``max(3, mins // 8)``."""
        outline = _outline(chapter_count=5, scenes_per_chapter=4)
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[_llm_result(outline)]
            + [_llm_result(_scenes_for_chapter(1 + 4 * i, 4)) for i in range(5)],
        )

        svc = LongFormScriptService(provider=provider)
        # 40 mins // 8 = 5 chapters expected. The outline mock returns
        # 5 chapters, so the resulting flow must run exactly 5 chapter
        # calls (= 6 total LLM calls).
        await svc.generate(topic="x", series_description="y", target_duration_minutes=40)
        assert provider.generate.call_count == 6  # 1 outline + 5 chapters

    async def test_chapter_count_auto_floor_is_3(self) -> None:
        """Even tiny target_duration_minutes must produce at least 3 chapters."""
        outline = _outline(chapter_count=3, scenes_per_chapter=4)
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[_llm_result(outline)]
            + [_llm_result(_scenes_for_chapter(1 + 4 * i, 4)) for i in range(3)],
        )

        svc = LongFormScriptService(provider=provider)
        await svc.generate(topic="x", series_description="y", target_duration_minutes=1)
        # 1 // 8 == 0; floor is 3 → 1 outline + 3 chapter calls = 4 total.
        assert provider.generate.call_count == 4

    async def test_scene_renumbering_across_chapters(self) -> None:
        """Scenes must be renumbered 1..N globally regardless of what the
        LLM emitted per chapter."""
        outline = _outline(chapter_count=2, scenes_per_chapter=3)
        # Both chapters return scenes numbered 1,2,3 — service must
        # renumber the second chapter to 4,5,6.
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[
                _llm_result(outline),
                _llm_result(_scenes_for_chapter(1, 3)),  # 1, 2, 3
                _llm_result(_scenes_for_chapter(1, 3)),  # 1, 2, 3 again
            ]
        )

        svc = LongFormScriptService(provider=provider)
        result = await svc.generate(
            topic="x",
            series_description="y",
            target_duration_minutes=16,
            chapter_count=2,
            scenes_per_chapter=3,
        )
        scene_numbers = [s["scene_number"] for s in result["script"]["scenes"]]
        assert scene_numbers == [1, 2, 3, 4, 5, 6]

    async def test_chapter_metadata_records_scene_indices(self) -> None:
        """``chapters`` JSONB should record each chapter's scene index range
        + title + mood for the per-chapter music + crossfade pipeline."""
        outline = _outline(chapter_count=2, scenes_per_chapter=4)
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[
                _llm_result(outline),
                _llm_result(_scenes_for_chapter(1, 4)),
                _llm_result(_scenes_for_chapter(5, 4)),
            ]
        )

        svc = LongFormScriptService(provider=provider)
        result = await svc.generate(
            topic="x",
            series_description="y",
            target_duration_minutes=20,
            chapter_count=2,
            scenes_per_chapter=4,
        )
        chapters = result["chapters"]
        assert len(chapters) == 2
        assert chapters[0]["title"] == "Chapter 1"
        assert chapters[0]["scenes"] == [1, 2, 3, 4]
        assert chapters[0]["mood"] == "epic"
        assert chapters[0]["music_mood"] == "epic"
        assert chapters[1]["scenes"] == [5, 6, 7, 8]
        assert chapters[1]["mood"] == "calm"

    async def test_continuity_context_passed_to_subsequent_chapters(self) -> None:
        """Chapter 2's prompt must mention the previous chapter's narration
        ending so the LLM has context to continue from."""
        outline = _outline(chapter_count=2, scenes_per_chapter=2)
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[
                _llm_result(outline),
                _llm_result(_scenes_for_chapter(1, 2)),
                _llm_result(_scenes_for_chapter(3, 2)),
            ]
        )

        svc = LongFormScriptService(provider=provider)
        await svc.generate(
            topic="x",
            series_description="y",
            target_duration_minutes=12,
            chapter_count=2,
            scenes_per_chapter=2,
        )

        # Chapter 1 prompt should NOT mention "previous chapter ended with"
        ch1_user_prompt = provider.generate.call_args_list[1].args[1]
        assert "previous chapter ended with" not in ch1_user_prompt

        # Chapter 2 prompt MUST include the continuity hint.
        ch2_user_prompt = provider.generate.call_args_list[2].args[1]
        assert "previous chapter ended with" in ch2_user_prompt

    async def test_visual_consistency_prefix_applied_to_every_scene(self) -> None:
        """When visual_consistency_prompt is configured, every scene's
        visual_prompt must start with that prefix."""
        outline = _outline(chapter_count=2, scenes_per_chapter=2)
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[
                _llm_result(outline),
                _llm_result(_scenes_for_chapter(1, 2)),
                _llm_result(_scenes_for_chapter(3, 2)),
            ]
        )

        svc = LongFormScriptService(
            provider=provider,
            visual_consistency_prompt="cinematic 4k, golden hour",
        )
        result = await svc.generate(
            topic="x",
            series_description="y",
            target_duration_minutes=12,
            chapter_count=2,
            scenes_per_chapter=2,
        )
        for scene in result["script"]["scenes"]:
            assert scene["visual_prompt"].startswith("cinematic 4k, golden hour, ")

    async def test_chapter_handles_dict_with_scenes_key(self) -> None:
        """Some LLMs wrap the scene array in a ``{"scenes": [...]}`` envelope
        instead of returning the bare list — the service should accept both."""
        outline = _outline(chapter_count=1, scenes_per_chapter=2)
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[
                _llm_result(outline),
                _llm_result({"scenes": _scenes_for_chapter(1, 2)}),
            ]
        )
        svc = LongFormScriptService(provider=provider)
        result = await svc.generate(
            topic="x",
            series_description="y",
            target_duration_minutes=8,
            chapter_count=1,
            scenes_per_chapter=2,
        )
        assert len(result["script"]["scenes"]) == 2

    async def test_chapter_falls_back_to_empty_on_unexpected_shape(self) -> None:
        """When the LLM returns a non-list / non-dict shape, the chapter
        is silently emitted as zero scenes — generation continues."""
        outline = _outline(chapter_count=1, scenes_per_chapter=2)
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[
                _llm_result(outline),
                _llm_result("just a bare string"),
            ]
        )
        svc = LongFormScriptService(provider=provider)
        result = await svc.generate(
            topic="x",
            series_description="y",
            target_duration_minutes=8,
            chapter_count=1,
            scenes_per_chapter=2,
        )
        assert result["script"]["scenes"] == []

    async def test_outline_non_dict_raises(self) -> None:
        """Phase-1 returning a non-dict (e.g. a bare list) is a hard fail —
        retrying via LLMPool is the right move, not silently building an
        empty episode."""
        provider = AsyncMock()
        # Phase 1 returns an array — outline parser expects a dict.
        provider.generate = AsyncMock(
            side_effect=[_llm_result([1, 2, 3])],
        )
        svc = LongFormScriptService(provider=provider)
        with pytest.raises(ValueError, match="Expected JSON object"):
            await svc.generate(
                topic="x",
                series_description="y",
                target_duration_minutes=24,
                chapter_count=3,
                scenes_per_chapter=4,
            )

    async def test_total_duration_seconds_is_sum_of_scenes(self) -> None:
        outline = _outline(chapter_count=2, scenes_per_chapter=2)
        scenes_a = [{"narration": "a", "visual_prompt": "a", "duration_seconds": 7.5}] * 2
        scenes_b = [{"narration": "b", "visual_prompt": "b", "duration_seconds": 12.0}] * 2
        provider = AsyncMock()
        provider.generate = AsyncMock(
            side_effect=[
                _llm_result(outline),
                _llm_result(scenes_a),
                _llm_result(scenes_b),
            ]
        )
        svc = LongFormScriptService(provider=provider)
        result = await svc.generate(
            topic="x",
            series_description="y",
            target_duration_minutes=12,
            chapter_count=2,
            scenes_per_chapter=2,
        )
        # 2 * 7.5 + 2 * 12.0 = 39.0
        assert result["script"]["total_duration_seconds"] == 39.0


# ── _parse_json corner cases ─────────────────────────────────────────────


class TestParseJson:
    """Static helper; no async, no mocks."""

    def test_plain_object(self) -> None:
        result = LongFormScriptService._parse_json('{"k": 1}')
        assert result == {"k": 1}

    def test_plain_array(self) -> None:
        result = LongFormScriptService._parse_json("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_markdown_fenced_with_json_label(self) -> None:
        result = LongFormScriptService._parse_json('```json\n{"k": "v"}\n```')
        assert result == {"k": "v"}

    def test_markdown_fenced_no_label(self) -> None:
        result = LongFormScriptService._parse_json("```\n[1, 2]\n```")
        assert result == [1, 2]

    def test_object_embedded_in_prose(self) -> None:
        text = 'Here is the JSON: {"title": "X"} hope that helps.'
        result = LongFormScriptService._parse_json(text)
        assert result == {"title": "X"}

    def test_array_embedded_in_prose(self) -> None:
        text = "The scenes are: [1, 2, 3] — that's all."
        result = LongFormScriptService._parse_json(text)
        assert result == [1, 2, 3]

    def test_unparseable_raises(self) -> None:
        with pytest.raises(ValueError, match="did not return parseable JSON"):
            LongFormScriptService._parse_json("totally not json at all")
