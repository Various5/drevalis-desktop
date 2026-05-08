"""Unit tests for the shared SEO prompt module.

Verifies the system-prompt rule blocks stay in sync with the script
gate's banned vocabulary, and that ``build_seo_user_prompt`` carries
the script's existing description forward as a "preferred draft" so
the SEO call doesn't discard the script step's vetted output.
"""

from __future__ import annotations

from drevalis.services.seo_prompts import (
    BANNED_VOCAB_BLOCK,
    SEO_SYSTEM_PROMPT,
    build_seo_user_prompt,
)


class TestSystemPrompt:
    def test_includes_banned_vocab_block(self) -> None:
        assert "delve" in SEO_SYSTEM_PROMPT
        assert "tapestry" in SEO_SYSTEM_PROMPT
        assert BANNED_VOCAB_BLOCK in SEO_SYSTEM_PROMPT

    def test_forbids_in_this_video_opener(self) -> None:
        assert "In this video" in SEO_SYSTEM_PROMPT

    def test_includes_hashtag_rules(self) -> None:
        # The shared rule set forbids the same three hashtags as the
        # longform sanitiser.
        assert "#viral" in SEO_SYSTEM_PROMPT
        assert "#fyp" in SEO_SYSTEM_PROMPT
        assert "#subscribe" in SEO_SYSTEM_PROMPT


class TestBuildSeoUserPrompt:
    def test_carries_existing_description_forward(self) -> None:
        out = build_seo_user_prompt(
            title="The teenager who hacked NASA",
            narration="In 1947 a fifteen-year-old broke into NASA.",
            script_description="A 1947 break-in. NASA's youngest hacker walked off with 1.7 million dollars of code.",
        )
        assert "Existing description draft" in out
        assert "1.7 million dollars" in out

    def test_omits_section_when_no_existing_description(self) -> None:
        out = build_seo_user_prompt(
            title="The teenager who hacked NASA",
            narration="In 1947 a fifteen-year-old broke into NASA.",
            script_description="",
        )
        assert "Existing description draft" not in out

    def test_falls_back_to_title_on_empty_narration(self) -> None:
        out = build_seo_user_prompt(
            title="The teenager who hacked NASA",
            narration="",
        )
        # Narration line still renders (with the title as fallback body)
        # so we never ship a literal empty user message.
        assert "The teenager who hacked NASA" in out

    def test_truncates_narration_at_1000_chars(self) -> None:
        long_narration = "x " * 800  # 1600 chars total
        out = build_seo_user_prompt(
            title="t",
            narration=long_narration,
        )
        # Single-character body + "Narration: " prefix etc — total stays bounded.
        assert len(out) < 1300
