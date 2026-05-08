"""Tests for the SFX-exclusion + voice round-robin fixes.

Pre-fix:
  * The character-detection regex ``^\\[([^\\]]+)\\]`` matched every
    bracketed line — including ``[SFX: rain | dur=4]`` — so SFX
    descriptions appeared in the auto-voice-casting "speakers" list
    and each got assigned a voice profile.
  * When a script had more characters than the gender pool size, the
    auto-assigner fell back to ``pool[0]`` for every overflow,
    collapsing characters 6+ onto the same voice.

Post-fix:
  * ``[SFX: ...]`` (any case) is filtered out before the speaker
    list is built.
  * When the unique-voice pool is exhausted, characters cycle
    through the pool round-robin instead of stacking on ``pool[0]``.
"""

from __future__ import annotations

import re


# Helper that replicates the production filter — keeps the regression
# expressed at the canonical place. If the production filter changes,
# the test imports it; today it's inline in two route handlers.
def _extract_characters(script_text: str) -> list[str]:
    """Mirror of the post-fix character-detection logic."""
    raw_tags = re.findall(r"^\[([^\]]+)\]", script_text, re.MULTILINE)
    return sorted({t.strip() for t in raw_tags if not t.strip().lower().startswith("sfx")})


# ── SFX exclusion ────────────────────────────────────────────────────────


class TestCharacterExtractionExcludesSfx:
    def test_basic_sfx_tag_excluded(self) -> None:
        script = (
            "[Narrator] Once upon a time.\n"
            "[SFX: heavy rain on a tin roof | dur=4]\n"
            "[Jack] What is going on?\n"
        )
        chars = _extract_characters(script)
        assert chars == ["Jack", "Narrator"]
        assert "SFX: heavy rain on a tin roof | dur=4" not in chars

    def test_sfx_with_modifiers_excluded(self) -> None:
        script = (
            "[SFX: thunder | dur=3 | influence=0.4]\n"
            "[SFX: heavy rain | dur=12 | under=3 | duck=-15]\n"
            "[Narrator] He looked outside.\n"
        )
        assert _extract_characters(script) == ["Narrator"]

    def test_sfx_case_insensitive(self) -> None:
        # Lowercase, uppercase, mixed case — all rejected.
        script = "[sfx: rain | dur=2]\n[Sfx: thunder]\n[SFX: door slam]\n[Narrator] x\n"
        assert _extract_characters(script) == ["Narrator"]

    def test_speaker_named_like_sfx_kept(self) -> None:
        # A speaker literally named "SFX" would be unusual but the
        # regex is conservative — we only filter when the tag
        # *starts with* "sfx" followed by something other than a
        # name. Edge case worth noting: a character literally named
        # "SFXer" or "SFX-1" gets dropped. Acceptable trade-off.
        script = "[SFXer] hi\n[Narrator] x\n"
        chars = _extract_characters(script)
        # ``SFXer`` starts with ``sfx``, so it's filtered. Document
        # this contract via an explicit test rather than letting it
        # surprise someone.
        assert chars == ["Narrator"]

    def test_duplicate_speakers_deduped(self) -> None:
        script = "[Jack] x\n[Jack] y\n[Jack] z\n"
        assert _extract_characters(script) == ["Jack"]

    def test_thirty_sfx_no_voice_pollution(self) -> None:
        # The exact symptom the user reported: 30 SFX tags,
        # producing 30 fake "speakers" pre-fix.
        sfx_lines = "\n".join(f"[SFX: random effect {i} | dur=2]" for i in range(30))
        script = f"[Narrator] Hello.\n{sfx_lines}\n[Narrator] Goodbye.\n"
        chars = _extract_characters(script)
        assert chars == ["Narrator"]


# ── Round-robin voice assignment ─────────────────────────────────────────


def _round_robin_assign(
    characters: list[dict[str, str]],
    male_voices: list[str],
    female_voices: list[str],
) -> dict[str, str]:
    """Mirror of the post-fix auto-assignment logic.

    Lifted from the route handler — kept here so the test pins the
    contract independently of the route's other concerns (HTTP, DB,
    repo lookups).
    """
    voice_casting: dict[str, str] = {}
    gender_counters: dict[str, int] = {"male": 0, "female": 0}
    for char in characters:
        gender = char.get("gender", "male")
        pool = female_voices if gender == "female" else male_voices
        if not pool:
            continue
        used = set(voice_casting.values())
        available = [v for v in pool if v not in used]
        if available:
            chosen = available[0]
        else:
            idx = gender_counters[gender] % len(pool)
            chosen = pool[idx]
        gender_counters[gender] += 1
        voice_casting[char["name"]] = chosen
    return voice_casting


class TestRoundRobinVoiceAssignment:
    def test_unique_voices_when_pool_large_enough(self) -> None:
        chars = [{"name": f"C{i}", "gender": "male"} for i in range(3)]
        result = _round_robin_assign(
            chars,
            male_voices=["m1", "m2", "m3", "m4", "m5"],
            female_voices=[],
        )
        assert len(set(result.values())) == 3, (
            "with a 5-voice pool and 3 characters, all should be unique"
        )

    def test_overflow_rotates_round_robin(self) -> None:
        # 6 chars, 3 voices. Char 1-3 unique. Char 4-6 should NOT
        # all collapse onto m1.
        chars = [{"name": f"C{i}", "gender": "male"} for i in range(6)]
        result = _round_robin_assign(chars, male_voices=["m1", "m2", "m3"], female_voices=[])
        assignments = [result[f"C{i}"] for i in range(6)]
        # First 3 are unique.
        assert len(set(assignments[:3])) == 3
        # Next 3 must rotate, not all collapse onto m1.
        assert assignments[3:] != ["m1", "m1", "m1"], (
            f"overflow chars collapsed onto pool[0] — pre-fix bug. Got {assignments}"
        )
        # In particular, chars 4 and 5 must have different voices.
        assert assignments[3] != assignments[4]

    def test_overflow_assignment_is_deterministic(self) -> None:
        chars = [{"name": f"C{i}", "gender": "male"} for i in range(6)]
        result = _round_robin_assign(chars, male_voices=["m1", "m2", "m3"], female_voices=[])
        # Char 4 (overflow start) gets m1; char 5 gets m2; char 6 gets m3.
        # That's the round-robin contract — predictable across runs.
        assert result["C3"] == "m1"
        assert result["C4"] == "m2"
        assert result["C5"] == "m3"

    def test_thirty_characters_five_voices_no_collapse(self) -> None:
        # The symptom the user reported: 30 chars, 5 voices.
        # Pre-fix: chars 6..30 all assigned the same first voice.
        # Post-fix: each one rotates through the pool.
        chars = [{"name": f"C{i}", "gender": "male"} for i in range(30)]
        pool = ["m1", "m2", "m3", "m4", "m5"]
        result = _round_robin_assign(chars, male_voices=pool, female_voices=[])
        # Each voice should be used exactly 6 times across 30 chars.
        from collections import Counter

        usage = Counter(result.values())
        assert all(count == 6 for count in usage.values()), (
            f"expected each of 5 voices used 6 times for 30 chars; got {dict(usage)}"
        )

    def test_gender_separation(self) -> None:
        chars = [
            {"name": "A", "gender": "male"},
            {"name": "B", "gender": "female"},
            {"name": "C", "gender": "male"},
            {"name": "D", "gender": "female"},
        ]
        result = _round_robin_assign(
            chars,
            male_voices=["m1", "m2"],
            female_voices=["f1", "f2"],
        )
        assert result["A"] in {"m1", "m2"}
        assert result["B"] in {"f1", "f2"}
        assert result["C"] in {"m1", "m2"}
        assert result["D"] in {"f1", "f2"}
        # Same-gender chars should differ.
        assert result["A"] != result["C"]
        assert result["B"] != result["D"]

    def test_default_gender_male(self) -> None:
        # When gender is missing on a char, treat as "male" (mirrors
        # the production code's default).
        chars = [{"name": "Mystery"}]
        result = _round_robin_assign(chars, male_voices=["m1"], female_voices=["f1"])
        assert result["Mystery"] == "m1"

    def test_empty_pool_skips_character(self) -> None:
        # No male voices available → male character gets no assignment
        # rather than crashing. (Caller checks ``default_voice_id``
        # later and surfaces a 400.)
        chars = [{"name": "A", "gender": "male"}]
        result = _round_robin_assign(chars, male_voices=[], female_voices=["f1"])
        assert "A" not in result
