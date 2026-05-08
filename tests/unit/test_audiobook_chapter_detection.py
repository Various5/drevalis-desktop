"""Tests for the scored chapter-detection pass (Task 8).

Pre-Task-8 detection was first-pattern-with-≥2-matches-wins; brittle
patterns like a lone roman ``I`` or a sub-section ``## Notes`` could
hijack a real audiobook. Post-Task-8 we score every candidate split
by mean-segment-length / (1 + CV) and only commit when the best
candidate exceeds ``_SCORE_THRESHOLD``.

Adversarial fixtures (called out by the brief):
  * Dialogue containing "Chapter five"
  * Screenplay-style ALL CAPS scene headers
  * Lone ``I`` as a roman numeral
  * ``## Notes`` markdown that isn't a chapter header
"""

from __future__ import annotations

import re

import pytest

from drevalis.services.audiobook._monolith import AudiobookService


def _svc() -> AudiobookService:
    """Bare service instance for parser methods that don't touch I/O."""
    return AudiobookService.__new__(AudiobookService)


# ── _score_chapter_split ─────────────────────────────────────────────────


class TestScoreChapterSplit:
    def test_returns_zero_for_fewer_than_two_matches(self) -> None:
        text = "x" * 5000
        # Empty match list.
        assert AudiobookService._score_chapter_split([], text) == 0
        # Single match.
        m = re.search(r"x", text)
        assert m is not None
        assert AudiobookService._score_chapter_split([m], text) == 0

    def test_returns_zero_when_segment_too_short(self) -> None:
        # Three matches with tiny segments (< 500 chars each).
        text = "## A\n## B\n## C\n" + "x" * 100
        ms = list(re.finditer(r"## .", text))
        assert len(ms) == 3
        assert AudiobookService._score_chapter_split(ms, text) == 0

    def test_higher_mean_yields_higher_score(self) -> None:
        # Two splits with consistent 1000-char segments vs. consistent
        # 2000-char segments — the 2000-char case scores higher.
        # Each `## ` heading needs to be on its own line, so separate
        # bodies with explicit ``\n\n`` newlines for the regex to match.
        text_short = "## A\n\n" + "x" * 1000 + "\n\n## B\n\n" + "x" * 1000
        text_long = "## A\n\n" + "x" * 2000 + "\n\n## B\n\n" + "x" * 2000
        ms_s = list(re.finditer(r"^## ", text_short, re.MULTILINE))
        ms_l = list(re.finditer(r"^## ", text_long, re.MULTILINE))
        score_s = AudiobookService._score_chapter_split(ms_s, text_short)
        score_l = AudiobookService._score_chapter_split(ms_l, text_long)
        assert score_l > score_s
        assert score_s > 0  # sanity — this is a real, scoreable split

    def test_high_cv_penalised(self) -> None:
        # Equal-segment splits beat very uneven splits.
        even = "## A\n\n" + "x" * 1500 + "\n\n## B\n\n" + "x" * 1500
        # Skewed must clear MIN_SEGMENT_CHARS (500) to score above 0,
        # but still be lopsided enough to penalise via CV.
        skewed = "## A\n\n" + "x" * 600 + "\n\n## B\n\n" + "x" * 3000
        ms_e = list(re.finditer(r"^## ", even, re.MULTILINE))
        ms_s = list(re.finditer(r"^## ", skewed, re.MULTILINE))
        score_e = AudiobookService._score_chapter_split(ms_e, even)
        score_s = AudiobookService._score_chapter_split(ms_s, skewed)
        assert score_e > 0
        assert score_s > 0
        assert score_e > score_s


# ── Markdown headings ────────────────────────────────────────────────────


class TestMarkdownDetection:
    def test_two_long_chapters_split(self) -> None:
        text = "## Chapter One\n\n" + "A" * 1500 + "\n\n## Chapter Two\n\n" + "B" * 1500
        chs = _svc()._parse_chapters(text)
        assert [c["title"] for c in chs] == ["Chapter One", "Chapter Two"]

    def test_short_subsection_headers_dont_split(self) -> None:
        # ``## Notes`` followed by tiny content — the "is this really
        # a chapter break" guard rejects via the score threshold.
        text = "## Notes\n\nSee X.\n\n## Other\n\nY."
        chs = _svc()._parse_chapters(text)
        assert len(chs) == 1
        assert chs[0]["title"] == "Full Text"

    def test_introduction_preamble_preserved(self) -> None:
        text = (
            "Once upon a time, there was a preamble that mattered enough\n"
            "to keep around. " + "P" * 1500 + "\n\n"
            "## Chapter One\n\n" + "A" * 1500 + "\n\n"
            "## Chapter Two\n\n" + "B" * 1500
        )
        chs = _svc()._parse_chapters(text)
        assert chs[0]["title"] == "Introduction"
        assert "preamble" in chs[0]["text"]
        assert [c["title"] for c in chs[1:]] == ["Chapter One", "Chapter Two"]


# ── Prose chapter pattern ────────────────────────────────────────────────


class TestProseChapterDetection:
    def test_chapter_n_arabic(self) -> None:
        text = "Chapter 1: Beginning\n\n" + "A" * 1500 + "\n\nChapter 2: Middle\n\n" + "B" * 1500
        chs = _svc()._parse_chapters(text)
        assert len(chs) == 2
        assert chs[0]["title"].lower().startswith("chapter 1")
        assert chs[1]["title"].lower().startswith("chapter 2")

    def test_chapter_word_form(self) -> None:
        text = "Chapter One\n\n" + "A" * 1500 + "\n\nChapter Two\n\n" + "B" * 1500
        chs = _svc()._parse_chapters(text)
        assert len(chs) == 2

    def test_dialogue_with_chapter_word_does_not_split(self) -> None:
        # The phrase "Chapter five was a disaster" is mid-line dialogue
        # — the regex anchors at line start, but more importantly the
        # score for a single-match candidate is 0.
        text = (
            "She paused at the porch. " + "A" * 600 + "\n\n"
            'He nodded. "Chapter five was a disaster," she said.\n\n'
            + "B" * 600
            + "\n\n"
            + "C" * 600
        )
        chs = _svc()._parse_chapters(text)
        assert len(chs) == 1
        assert chs[0]["title"] == "Full Text"


# ── Roman numeral pattern ────────────────────────────────────────────────


class TestRomanNumeralDetection:
    def test_double_letter_romans_split(self) -> None:
        text = "II.\n\n" + "A" * 1500 + "\n\nIII.\n\n" + "B" * 1500
        chs = _svc()._parse_chapters(text)
        assert len(chs) == 2

    def test_lone_capital_i_does_not_split(self) -> None:
        # A single-letter ``I`` on its own line was the false-positive
        # case the brief flagged. Length-2 minimum locks this out.
        text = "I.\n\n" + "A" * 1500 + "\n\nI.\n\n" + "B" * 1500
        chs = _svc()._parse_chapters(text)
        # Should NOT split via roman pattern; falls through to
        # single-chapter or some other pattern. Either way: not 2
        # romans-titled chapters.
        for c in chs:
            assert c["title"] != "I."


# ── All-caps headings ────────────────────────────────────────────────────


class TestAllCapsDetection:
    def test_real_chapter_headers_split(self) -> None:
        text = "THE FIRST ENCOUNTER\n\n" + "A" * 1500 + "\n\nTHE SECOND ENCOUNTER\n\n" + "B" * 1500
        chs = _svc()._parse_chapters(text)
        assert len(chs) == 2
        assert chs[0]["title"] == "THE FIRST ENCOUNTER"

    def test_screenplay_scene_cues_dont_split(self) -> None:
        # Multiple short ALL CAPS scene cues followed by short blocks.
        # Score should be too low (or alpha ratio too low for the
        # cues with periods/dashes).
        text = (
            "INT. KITCHEN — DAY\n\n"
            "She stirs the pot.\n\n"
            "EXT. PORCH — NIGHT\n\n"
            "He lights a cigarette.\n\n"
            "INT. BEDROOM — DAWN\n\n"
            "She sleeps."
        )
        chs = _svc()._parse_chapters(text)
        assert len(chs) == 1, (
            f"screenplay-style scene cues should not split into {len(chs)} chapters"
        )

    def test_low_alpha_ratio_rejected(self) -> None:
        # An all-caps line that's mostly digits + punctuation.
        text = "1234567890 ABC\n\n" + "A" * 1500 + "\n\n9876543210 XYZ\n\n" + "B" * 1500
        chs = _svc()._parse_chapters(text)
        # The "1234..." rows fail the 80% alpha guard. So they don't
        # split via all-caps.
        assert len(chs) == 1


# ── Horizontal-rule fallback ─────────────────────────────────────────────


class TestHorizontalRuleFallback:
    def test_three_dash_separator_splits_into_parts(self) -> None:
        text = "First section.\n---\nSecond section.\n---\nThird section."
        chs = _svc()._parse_chapters(text)
        assert [c["title"] for c in chs] == ["Part 1", "Part 2", "Part 3"]


# ── Single-chapter fallback ──────────────────────────────────────────────


class TestSingleChapterFallback:
    def test_no_markers_yields_full_text(self) -> None:
        chs = _svc()._parse_chapters("Just a plain story with no markers.")
        assert chs == [{"title": "Full Text", "text": "Just a plain story with no markers."}]

    def test_empty_text_yields_full_text_marker(self) -> None:
        chs = _svc()._parse_chapters("")
        assert chs == [{"title": "Full Text", "text": ""}]


# ── Best-candidate selection ─────────────────────────────────────────────


class TestBestCandidateWins:
    """When two patterns both match, the higher score wins. Used to
    be first-match — could let prose chapters override an explicitly
    markdown-formatted audiobook in pathological cases.
    """

    @pytest.mark.parametrize("size", [1500, 2500])
    def test_markdown_beats_unrelated_caps_word(self, size: int) -> None:
        # A long body that incidentally contains an all-caps line near
        # the top — the markdown headings should still win because
        # their score is higher (more even segments).
        body_a = "A" * size
        body_b = "B" * size
        text = "## Chapter One\n\nShe walked. " + body_a + "\n\n## Chapter Two\n\nHe ran. " + body_b
        chs = _svc()._parse_chapters(text)
        assert [c["title"] for c in chs] == ["Chapter One", "Chapter Two"]
