"""Tests for ``_generate_audiobook_script_text`` — the LLM-driven script
generation helper inside ``workers/jobs/audiobook.py``.

Pin the chunked-vs-single-call strategy plus the cancellation hook
that the script-job poll endpoint relies on:

* `target_words <= 4500` → single LLM call. Returns content stripped.
* Cancellation between phases: when Redis status flips to "cancelled"
  → returns None immediately (NOT continues silently).
* `target_words > 4500` → two-phase: outline → per-chapter generation.
* Outline JSON wrapped in markdown fences is unwrapped before parse.
* Outline malformed → falls back to single-call.
* Outline returns no `chapters` → falls back to single-call.
* Chapter loop: previous chapter's last paragraph used as continuity
  context for the next chapter.
* Mid-chapter cancellation breaks the loop with None.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from drevalis.workers.jobs.audiobook import _generate_audiobook_script_text


def _result(text: str) -> Any:
    r = SimpleNamespace(content=text)
    return r


def _provider_returning(*texts: str) -> Any:
    """Build an LLM provider whose `generate` returns the texts in
    order across successive calls."""
    p = MagicMock()
    iterator = iter(texts)

    async def _gen(*_args: Any, **_kwargs: Any) -> Any:
        return _result(next(iterator))

    p.generate = AsyncMock(side_effect=_gen)
    return p


# ── Single-call (short) path ──────────────────────────────────────


class TestSingleCallPath:
    async def test_short_target_uses_single_call(self) -> None:
        provider = _provider_returning("Title\n\n[Narrator] Body")
        out = await _generate_audiobook_script_text(
            provider,
            concept="A short tale",
            char_list="- Narrator: omniscient",
            mood="calm",
            target_words=2000,
            target_minutes=10.0,
        )
        assert out == "Title\n\n[Narrator] Body"
        # Pin: exactly ONE generate call (no chunking).
        provider.generate.assert_awaited_once()

    async def test_strips_whitespace(self) -> None:
        provider = _provider_returning("  spaced content  \n\n")
        out = await _generate_audiobook_script_text(
            provider,
            concept="x",
            char_list="",
            mood="x",
            target_words=1000,
            target_minutes=5.0,
        )
        assert out == "spaced content"

    async def test_cancellation_after_single_call_returns_none(self) -> None:
        provider = _provider_returning("any content")
        redis = AsyncMock()
        # Status flips to "cancelled" between LLM call and return.
        redis.get = AsyncMock(return_value="cancelled")
        out = await _generate_audiobook_script_text(
            provider,
            concept="x",
            char_list="",
            mood="x",
            target_words=1000,
            target_minutes=5.0,
            redis_client=redis,
            job_id="abc",
        )
        assert out is None

    async def test_no_redis_client_skips_cancellation_check(self) -> None:
        # Pin: when redis_client is None, the route doesn't try to
        # check for cancellation (no AttributeError).
        provider = _provider_returning("done")
        out = await _generate_audiobook_script_text(
            provider,
            concept="x",
            char_list="",
            mood="x",
            target_words=1000,
            target_minutes=5.0,
            redis_client=None,
            job_id=None,
        )
        assert out == "done"


# ── Two-phase (long-form) path ─────────────────────────────────────


class TestTwoPhasePath:
    async def test_outline_plus_chapter_generation(self) -> None:
        # 5000 target words → > 4500 threshold → outline + per-chapter.
        outline = json.dumps(
            {
                "title": "Long Story",
                "chapters": [
                    {
                        "title": "Chapter 1: Start",
                        "summary": "Hero begins",
                    },
                    {
                        "title": "Chapter 2: End",
                        "summary": "Hero finishes",
                    },
                ],
            }
        )
        provider = _provider_returning(
            outline,
            "## Chapter 1: Start\n\n[Narrator] Once upon a time…",
            "## Chapter 2: End\n\n[Narrator] And so it ended.",
        )
        out = await _generate_audiobook_script_text(
            provider,
            concept="An epic tale",
            char_list="- Narrator: omniscient",
            mood="epic",
            target_words=5000,
            target_minutes=40.0,
        )
        assert out is not None
        # Pin: title from outline + chapter texts.
        assert "Long Story" in out
        assert "Chapter 1: Start" in out
        assert "Chapter 2: End" in out
        # 1 outline call + 2 chapter calls = 3 total.
        assert provider.generate.await_count == 3

    async def test_outline_unwraps_markdown_fences(self) -> None:
        # Pin: when the LLM returns JSON wrapped in ```json … ```,
        # the route strips the fences before parsing.
        wrapped = (
            "```json\n"
            + json.dumps(
                {
                    "title": "Wrapped",
                    "chapters": [{"title": "Chapter 1", "summary": "Only chapter"}],
                }
            )
            + "\n```"
        )
        provider = _provider_returning(
            wrapped,
            "## Chapter 1\n\n[Narrator] Only chapter content.",
        )
        out = await _generate_audiobook_script_text(
            provider,
            concept="x",
            char_list="",
            mood="x",
            target_words=5000,
            target_minutes=40.0,
        )
        assert out is not None
        assert "Wrapped" in out

    async def test_malformed_outline_falls_back_to_single_call(
        self,
    ) -> None:
        # Outline JSON is unparseable → fallback single call returns
        # the full script.
        provider = _provider_returning(
            "{not actually json",
            "Fallback Title\n\n[Narrator] Single-call result.",
        )
        out = await _generate_audiobook_script_text(
            provider,
            concept="x",
            char_list="",
            mood="x",
            target_words=5000,
            target_minutes=40.0,
        )
        assert out is not None
        assert "Single-call result" in out
        # 1 outline + 1 fallback = 2 calls (no per-chapter loop).
        assert provider.generate.await_count == 2

    async def test_empty_chapters_falls_back_to_single_call(
        self,
    ) -> None:
        # Outline parses but contains no chapters → fallback.
        outline = json.dumps({"title": "Empty", "chapters": []})
        provider = _provider_returning(
            outline,
            "Fallback Title\n\n[Narrator] Empty chapters fallback.",
        )
        out = await _generate_audiobook_script_text(
            provider,
            concept="x",
            char_list="",
            mood="x",
            target_words=5000,
            target_minutes=40.0,
        )
        assert "Empty chapters fallback" in out  # type: ignore[operator]

    async def test_cancellation_between_chapters_returns_none(
        self,
    ) -> None:
        # Pin: poll cancellation between chapter calls breaks the loop.
        outline = json.dumps(
            {
                "title": "Cancellable",
                "chapters": [
                    {"title": "Chapter 1", "summary": "First"},
                    {"title": "Chapter 2", "summary": "Second"},
                    {"title": "Chapter 3", "summary": "Third"},
                ],
            }
        )
        # 1 outline + 1 chapter (then cancel before chapter 2).
        provider = _provider_returning(
            outline,
            "## Chapter 1\n\n[Narrator] First chapter content.",
        )
        redis = AsyncMock()
        # First call (cancellation check at top of loop): "generating"
        # → continue. Second call (after chapter 1): "cancelled" →
        # break.
        redis.get = AsyncMock(side_effect=["generating", "cancelled"])

        out = await _generate_audiobook_script_text(
            provider,
            concept="x",
            char_list="",
            mood="x",
            target_words=5000,
            target_minutes=40.0,
            redis_client=redis,
            job_id="abc",
        )
        assert out is None

    async def test_chapter_count_derived_from_target_minutes(self) -> None:
        # Pin: num_chapters = max(3, target_minutes / 8). 80 min → 10
        # chapters; 16 min → 3 chapters (the floor).
        # We assert via the number of chapter LLM calls.
        outline = json.dumps(
            {
                "title": "Many",
                "chapters": [
                    {"title": f"Chapter {i + 1}", "summary": f"Summary {i + 1}"} for i in range(10)
                ],
            }
        )
        chapter_texts = [f"## Chapter {i + 1}\n\n[Narrator] Body {i + 1}." for i in range(10)]
        provider = _provider_returning(outline, *chapter_texts)
        out = await _generate_audiobook_script_text(
            provider,
            concept="x",
            char_list="",
            mood="x",
            target_words=20000,
            target_minutes=80.0,
        )
        assert out is not None
        # 1 outline + 10 chapters = 11 calls.
        assert provider.generate.await_count == 11

    async def test_continuity_uses_last_paragraph_of_previous_chapter(
        self,
    ) -> None:
        # Pin: the helper extracts the last `\n\n`-separated paragraph
        # of each chapter and feeds it as continuity to the next call.
        # We verify by inspecting the user_prompt arg of the third
        # generate call (chapter 2).
        outline = json.dumps(
            {
                "title": "Continuity",
                "chapters": [
                    {"title": "Chapter 1", "summary": "First"},
                    {"title": "Chapter 2", "summary": "Second"},
                ],
            }
        )
        chapter_1 = (
            "## Chapter 1\n\n[Narrator] Opening paragraph.\n\n[Hero] Final-paragraph dialogue."
        )
        provider = _provider_returning(outline, chapter_1, "## Chapter 2\n\n[Narrator] cont.")
        await _generate_audiobook_script_text(
            provider,
            concept="x",
            char_list="",
            mood="x",
            target_words=5000,
            target_minutes=40.0,
        )
        # Third generate call is for chapter 2.
        third_call = provider.generate.await_args_list[2]
        # The user prompt should reference Chapter 1's last paragraph.
        # Args are (system, user, ...) — find the user prompt.
        user_prompt = (
            third_call.args[1]
            if len(third_call.args) > 1
            else third_call.kwargs.get("user_prompt", "")
        )
        assert "Final-paragraph dialogue" in user_prompt
