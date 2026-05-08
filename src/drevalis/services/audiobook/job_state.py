"""Per-stage DAG job state for audiobook generation (Task 11).

The audiobook row's ``status`` column is a coarse 4-value enum
(``draft / generating / done / failed``). It can't tell you *which*
stage failed or how much work survived a partial run. Task 11 adds a
finer-grained ``job_state`` JSONB column with one entry per pipeline
stage.

Schema::

    {
      "chapters": {
        "0": {"tts": "done", "image": "done", "music": "pending"},
        "1": {"tts": "done", "image": "pending", "music": "pending"},
        ...
      },
      "concat":      "pending",
      "overlay_sfx": "pending",
      "master_mix":  "pending",
      "captions":    "pending",
      "mp3_export":  "pending",
      "id3_tags":    "pending",
      "mp4_export":  "pending"
    }

State transitions::

    pending     ──▶ in_progress ──▶ done
                       │              ▲
                       ▼              │
                    failed ───────────┘   (retry path)

* ``done``        — already produced; skip on retry.
* ``failed``      — re-run on retry.
* ``in_progress`` — treat as crash-recovery: re-run.
* ``skipped``     — stage genuinely doesn't apply (e.g. ``mp4_export``
                    when ``output_format == "audio_only"``); progress
                    counter excludes it.
* ``pending``     — has not started yet.

The chunk-cache fast path (Task 1) is orthogonal: even when the DAG
says ``tts`` is pending, individual chunks may already be on disk and
get reused. The DAG is a coarser short-circuit on top of that.
"""

from __future__ import annotations

from typing import Any, Literal

State = Literal["pending", "in_progress", "done", "failed", "skipped"]

STATES: tuple[State, ...] = (
    "pending",
    "in_progress",
    "done",
    "failed",
    "skipped",
)

# Per-chapter stages.
STAGES_CHAPTER: tuple[str, ...] = ("tts", "image", "music")

# Global (audiobook-level) stages, in roughly the order they execute.
STAGES_GLOBAL: tuple[str, ...] = (
    "concat",
    "overlay_sfx",
    "master_mix",
    "captions",
    "mp3_export",
    "id3_tags",
    "mp4_export",
)


def init_state(num_chapters: int) -> dict[str, Any]:
    """Return a fresh ``pending``-everywhere DAG for *num_chapters*."""
    return {
        "chapters": {
            str(i): {stage: "pending" for stage in STAGES_CHAPTER} for i in range(num_chapters)
        },
        **{stage: "pending" for stage in STAGES_GLOBAL},
    }


def _normalise(state: dict[str, Any] | None, num_chapters: int) -> dict[str, Any]:
    """Coerce *state* into a well-formed DAG with *num_chapters* slots.

    Missing or wrong-shaped state falls back to a fresh ``init_state``.
    A state that has chapters but the wrong count gets resized — extra
    chapters trimmed, missing chapters added as all-pending. Global
    stages with unknown names are dropped; missing globals added.
    """
    if not state or not isinstance(state, dict):
        return init_state(num_chapters)

    new_chapters: dict[str, dict[str, str]] = {}
    existing_chapters = state.get("chapters") or {}
    for i in range(num_chapters):
        key = str(i)
        existing = existing_chapters.get(key) or {}
        new_chapters[key] = {
            stage: existing.get(stage, "pending") if existing.get(stage) in STATES else "pending"
            for stage in STAGES_CHAPTER
        }

    out: dict[str, Any] = {"chapters": new_chapters}
    for stage in STAGES_GLOBAL:
        val = state.get(stage)
        out[stage] = val if val in STATES else "pending"
    return out


def set_chapter_stage(
    state: dict[str, Any],
    chapter_index: int,
    stage: str,
    value: State,
) -> None:
    """Mutate *state* in place. Raises ``ValueError`` on bad inputs."""
    if value not in STATES:
        raise ValueError(f"unknown state: {value!r}")
    if stage not in STAGES_CHAPTER:
        raise ValueError(f"unknown chapter stage: {stage!r}")
    chapters = state.setdefault("chapters", {})
    key = str(chapter_index)
    chapter = chapters.setdefault(key, {s: "pending" for s in STAGES_CHAPTER})
    chapter[stage] = value


def set_global_stage(state: dict[str, Any], stage: str, value: State) -> None:
    """Mutate *state* in place. Raises ``ValueError`` on bad inputs."""
    if value not in STATES:
        raise ValueError(f"unknown state: {value!r}")
    if stage not in STAGES_GLOBAL:
        raise ValueError(f"unknown global stage: {stage!r}")
    state[stage] = value


def is_done(state: dict[str, Any], stage: str, chapter_index: int | None = None) -> bool:
    """``True`` iff the named stage is already ``done`` (skip on retry)."""
    if chapter_index is None:
        return bool(state.get(stage) == "done")
    chapters = state.get("chapters") or {}
    chapter = chapters.get(str(chapter_index)) or {}
    return bool(chapter.get(stage) == "done")


def compute_progress_pct(state: dict[str, Any]) -> int:
    """Estimated progress percentage from the DAG.

    ``skipped`` units count toward neither the numerator nor the
    denominator — they're stages that genuinely don't apply (e.g.
    ``mp4_export`` for audio-only audiobooks). ``in_progress``
    counts as a half unit so the bar moves visibly when long stages
    start.
    """
    chapters = state.get("chapters") or {}
    units_total = 0.0
    units_done = 0.0
    for chapter in chapters.values():
        for stage in STAGES_CHAPTER:
            v = chapter.get(stage, "pending")
            if v == "skipped":
                continue
            units_total += 1
            if v == "done":
                units_done += 1
            elif v == "in_progress":
                units_done += 0.5
    for stage in STAGES_GLOBAL:
        v = state.get(stage, "pending")
        if v == "skipped":
            continue
        units_total += 1
        if v == "done":
            units_done += 1
        elif v == "in_progress":
            units_done += 0.5
    if units_total == 0:
        return 100
    return int(units_done / units_total * 100)
