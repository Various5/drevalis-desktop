"""Tests for the per-stage DAG job state (Task 11)."""

from __future__ import annotations

import pytest

from drevalis.services.audiobook.job_state import (
    STAGES_CHAPTER,
    STAGES_GLOBAL,
    STATES,
    _normalise,
    compute_progress_pct,
    init_state,
    is_done,
    set_chapter_stage,
    set_global_stage,
)

# ── init_state ────────────────────────────────────────────────────────────


class TestInitState:
    def test_zero_chapters_has_no_chapter_entries(self) -> None:
        s = init_state(0)
        assert s["chapters"] == {}
        for stage in STAGES_GLOBAL:
            assert s[stage] == "pending"

    def test_three_chapters_three_stages(self) -> None:
        s = init_state(3)
        assert sorted(s["chapters"].keys()) == ["0", "1", "2"]
        for ch in s["chapters"].values():
            assert sorted(ch.keys()) == sorted(STAGES_CHAPTER)
            assert all(v == "pending" for v in ch.values())

    def test_state_has_every_global_stage(self) -> None:
        s = init_state(0)
        # Global keys + chapters key — no extras.
        expected = {"chapters", *STAGES_GLOBAL}
        assert set(s.keys()) == expected


# ── set_chapter_stage / set_global_stage ─────────────────────────────────


class TestStateMutators:
    def test_set_chapter_stage_mutates_only_target(self) -> None:
        s = init_state(2)
        set_chapter_stage(s, 0, "tts", "done")
        assert s["chapters"]["0"]["tts"] == "done"
        assert s["chapters"]["0"]["image"] == "pending"
        assert s["chapters"]["1"]["tts"] == "pending"

    def test_set_global_stage_mutates_only_target(self) -> None:
        s = init_state(1)
        set_global_stage(s, "concat", "done")
        assert s["concat"] == "done"
        assert s["master_mix"] == "pending"

    def test_unknown_chapter_stage_raises(self) -> None:
        s = init_state(1)
        with pytest.raises(ValueError):
            set_chapter_stage(s, 0, "not_a_stage", "done")  # type: ignore[arg-type]

    def test_unknown_global_stage_raises(self) -> None:
        s = init_state(1)
        with pytest.raises(ValueError):
            set_global_stage(s, "not_a_stage", "done")  # type: ignore[arg-type]

    def test_unknown_state_value_raises(self) -> None:
        s = init_state(1)
        with pytest.raises(ValueError):
            set_chapter_stage(s, 0, "tts", "completed")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            set_global_stage(s, "concat", "completed")  # type: ignore[arg-type]


# ── is_done ───────────────────────────────────────────────────────────────


class TestIsDone:
    def test_chapter_stage_done(self) -> None:
        s = init_state(2)
        assert is_done(s, "tts", chapter_index=0) is False
        set_chapter_stage(s, 0, "tts", "done")
        assert is_done(s, "tts", chapter_index=0) is True
        # Sibling chapter still pending.
        assert is_done(s, "tts", chapter_index=1) is False

    def test_global_stage_done(self) -> None:
        s = init_state(1)
        assert is_done(s, "concat") is False
        set_global_stage(s, "concat", "done")
        assert is_done(s, "concat") is True

    def test_in_progress_is_not_done(self) -> None:
        s = init_state(1)
        set_chapter_stage(s, 0, "tts", "in_progress")
        assert is_done(s, "tts", chapter_index=0) is False
        set_global_stage(s, "concat", "failed")
        assert is_done(s, "concat") is False


# ── compute_progress_pct ─────────────────────────────────────────────────


class TestComputeProgressPct:
    def test_empty_dag_zero_percent(self) -> None:
        s = init_state(2)
        assert compute_progress_pct(s) == 0

    def test_all_done_one_hundred(self) -> None:
        s = init_state(2)
        for ch_idx in range(2):
            for stage in STAGES_CHAPTER:
                set_chapter_stage(s, ch_idx, stage, "done")
        for stage in STAGES_GLOBAL:
            set_global_stage(s, stage, "done")
        assert compute_progress_pct(s) == 100

    def test_skipped_excluded_from_denominator(self) -> None:
        # 1 chapter, 3 chapter stages, 7 global stages = 10 units.
        # If we mark mp4_export skipped, denominator drops to 9.
        s = init_state(1)
        set_global_stage(s, "mp4_export", "skipped")
        # Mark everything else done.
        for stage in STAGES_CHAPTER:
            set_chapter_stage(s, 0, stage, "done")
        for stage in STAGES_GLOBAL:
            if stage != "mp4_export":
                set_global_stage(s, stage, "done")
        assert compute_progress_pct(s) == 100

    def test_in_progress_counts_as_half(self) -> None:
        # Single chapter, 3 chapter stages, 7 globals = 10 units.
        # Mark one stage in_progress; expect ~5%.
        s = init_state(1)
        set_chapter_stage(s, 0, "tts", "in_progress")
        # 0.5 / 10 = 5.
        assert compute_progress_pct(s) == 5

    def test_partial_done_proportional(self) -> None:
        # 2 chapters × 3 stages + 7 globals = 13 units.
        # Mark 2 chapter TTS done + concat done = 3 done units.
        # Expect 3 / 13 ≈ 23%.
        s = init_state(2)
        set_chapter_stage(s, 0, "tts", "done")
        set_chapter_stage(s, 1, "tts", "done")
        set_global_stage(s, "concat", "done")
        pct = compute_progress_pct(s)
        assert 22 <= pct <= 24

    def test_zero_total_units_returns_100(self) -> None:
        # A degenerate state with everything skipped.
        s = init_state(1)
        for stage in STAGES_CHAPTER:
            set_chapter_stage(s, 0, stage, "skipped")
        for stage in STAGES_GLOBAL:
            set_global_stage(s, stage, "skipped")
        assert compute_progress_pct(s) == 100


# ── _normalise ────────────────────────────────────────────────────────────


class TestNormalise:
    def test_none_returns_fresh_state(self) -> None:
        s = _normalise(None, num_chapters=2)
        assert sorted(s["chapters"].keys()) == ["0", "1"]
        assert s["concat"] == "pending"

    def test_resizes_chapter_count(self) -> None:
        # Old state has 5 chapters; reshape to 3.
        old = init_state(5)
        for ch_idx in range(5):
            set_chapter_stage(old, ch_idx, "tts", "done")
        new = _normalise(old, num_chapters=3)
        assert sorted(new["chapters"].keys()) == ["0", "1", "2"]
        for ch_idx in range(3):
            assert new["chapters"][str(ch_idx)]["tts"] == "done"

    def test_pads_chapter_count_with_pending(self) -> None:
        old = init_state(1)
        set_chapter_stage(old, 0, "tts", "done")
        new = _normalise(old, num_chapters=3)
        assert new["chapters"]["0"]["tts"] == "done"
        assert new["chapters"]["1"]["tts"] == "pending"
        assert new["chapters"]["2"]["tts"] == "pending"

    def test_unknown_state_value_coerced_to_pending(self) -> None:
        bad = {
            "chapters": {"0": {"tts": "completed", "image": "done", "music": "pending"}},
            "concat": "completed",
            **{stage: "pending" for stage in STAGES_GLOBAL if stage != "concat"},
        }
        new = _normalise(bad, num_chapters=1)
        assert new["chapters"]["0"]["tts"] == "pending"
        assert new["chapters"]["0"]["image"] == "done"  # valid value preserved
        assert new["concat"] == "pending"


# ── State invariants ─────────────────────────────────────────────────────


class TestStateInvariants:
    def test_states_tuple_has_expected_values(self) -> None:
        assert set(STATES) == {"pending", "in_progress", "done", "failed", "skipped"}

    def test_chapter_stages_match_brief(self) -> None:
        # Brief specified per-chapter: tts, image, music. (concat + sfx
        # in the brief are global stages in our pipeline; they live in
        # STAGES_GLOBAL.)
        assert set(STAGES_CHAPTER) == {"tts", "image", "music"}

    def test_global_stages_match_brief(self) -> None:
        assert set(STAGES_GLOBAL) == {
            "concat",
            "overlay_sfx",
            "master_mix",
            "captions",
            "mp3_export",
            "id3_tags",
            "mp4_export",
        }
