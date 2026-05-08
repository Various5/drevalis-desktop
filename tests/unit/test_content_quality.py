"""Unit tests for the script-content quality gate (Phase 2.7).

Covers banned-vocabulary detection, specificity heuristics, sentence-
length distribution, opening-repetition, and listicle markers. The gate
itself is sync logic wrapped in an async signature, so we exercise it
synchronously via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio

from drevalis.schemas.script import EpisodeScript
from drevalis.services.quality_gates import check_script_content


def _build_script(*scenes: dict[str, object]) -> EpisodeScript:
    return EpisodeScript.model_validate(
        {
            "title": "Test",
            "scenes": list(scenes),
            "total_duration_seconds": float(len(scenes) * 5),
        }
    )


def _scene(narration: str, scene_number: int = 1) -> dict[str, object]:
    return {
        "scene_number": scene_number,
        "narration": narration,
        "visual_prompt": "wide shot, golden hour, brass sextant on stained linen",
        "duration_seconds": 5.0,
    }


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class TestBannedVocab:
    def test_clean_narration_passes(self) -> None:
        script = _build_script(
            _scene("In 1947 a teenager named Jonathan James broke into NASA.", 1),
            _scene("He stole 1.7 million dollars worth of source code.", 2),
        )
        report = _run(check_script_content(script))
        assert report.passed is True, report.issues
        assert report.gate == "script_content"

    def test_global_banned_word_flags_scene(self) -> None:
        script = _build_script(
            _scene("In 1947 we delve into a NASA hack worth $1.7M.", 1),
        )
        report = _run(check_script_content(script))
        assert report.passed is False
        assert any("banned word 'delve'" in i for i in report.issues)

    def test_banned_phrase_flags(self) -> None:
        script = _build_script(
            _scene("In 1947 a NASA hack happened. In conclusion the kid won.", 1),
        )
        report = _run(check_script_content(script))
        assert any("in conclusion" in i for i in report.issues)

    def test_extra_forbidden_words_from_tone_profile(self) -> None:
        script = _build_script(
            _scene("In 1947 the NASA hacker said it was literally easy.", 1),
        )
        tone = {"forbidden_words": ["literally"]}
        report = _run(check_script_content(script, tone))
        assert any("'literally'" in i for i in report.issues)


class TestSpecificity:
    def test_proper_noun_passes(self) -> None:
        script = _build_script(
            _scene("Jonathan James broke into NASA at fifteen.", 1),
        )
        report = _run(check_script_content(script))
        # Sentence length is fine; proper noun present → passes.
        assert report.passed is True, report.issues

    def test_digit_passes(self) -> None:
        script = _build_script(
            _scene("A teenager broke into NASA in 1947.", 1),
        )
        report = _run(check_script_content(script))
        assert report.passed is True, report.issues

    def test_generic_narration_fails_specificity(self) -> None:
        script = _build_script(
            _scene("a teenager broke into a network and stole some software.", 1),
        )
        report = _run(check_script_content(script))
        assert any("no concrete fact" in i for i in report.issues)


class TestSentenceLength:
    def test_sentence_over_hard_cap_flags(self) -> None:
        # 23 words — over the default cap of 18+4=22 hard cap.
        very_long = (
            "In 1947 the teenager Jonathan James walked into NASA's network "
            "and quietly downloaded the source code, then he ran outside, "
            "ate lunch, and went home."
        )
        script = _build_script(_scene(very_long, 1))
        report = _run(check_script_content(script))
        assert any("hard cap" in i for i in report.issues)

    def test_tone_profile_max_sentence_words_tightens_cap(self) -> None:
        # Sentence is 8 words — passes default cap, but profile sets max=4
        # so hard cap becomes 8; exactly-equal sentence should not flag,
        # but 9 should.
        script = _build_script(
            _scene("Jonathan James broke into NASA in 1947 alone.", 1),
        )
        tone = {"max_sentence_words": 4}
        report = _run(check_script_content(script, tone))
        # 8 words exactly equals hard cap (4+4) — passes the per-sentence
        # check, but average-cap (avg > 4) flags.
        assert any("average sentence length" in i for i in report.issues)


class TestOpeningRepetition:
    def test_same_first_three_words_flags(self) -> None:
        # Both openings: "In 1947 NASA …" — first three lowercased
        # word-stems collide.
        s1 = _scene("In 1947 NASA's youngest hacker made history.", 1)
        s2 = _scene("In 1947 NASAs response hid what happened.", 2)
        script = _build_script(s1, s2)
        report = _run(check_script_content(script))
        # The third token after stripping apostrophes is "nasas" in both
        # — proves the normalisation actually compares word stems.
        assert any("same 3 words" in i for i in report.issues)

    def test_distinct_openings_pass(self) -> None:
        s1 = _scene("Jonathan James, fifteen, walked past NASA's locks.", 1)
        s2 = _scene("In 1947 Congress demanded answers from NASA.", 2)
        script = _build_script(s1, s2)
        report = _run(check_script_content(script))
        assert not any("same 3 words" in i for i in report.issues)


class TestListicle:
    def test_listicle_marker_flags_when_disallowed(self) -> None:
        script = _build_script(
            _scene("Number 1: NASA's source code was 1.7 million dollars.", 1),
        )
        report = _run(check_script_content(script))
        assert any("listicle marker" in i for i in report.issues)

    def test_listicle_marker_allowed_via_tone_profile(self) -> None:
        script = _build_script(
            _scene("Number 1: NASA's source code was 1.7 million dollars.", 1),
        )
        tone = {"allow_listicle": True}
        report = _run(check_script_content(script, tone))
        assert not any("listicle marker" in i for i in report.issues)


class TestEmptyScript:
    def test_no_scenes_fails(self) -> None:
        # Pydantic min_length=1 rejects empty scenes; build manually
        # via construct() to bypass.
        broken = EpisodeScript.model_construct(title="x", scenes=[], total_duration_seconds=0.0)
        report = _run(check_script_content(broken))
        assert report.passed is False
        assert any("no scenes" in i for i in report.issues)
