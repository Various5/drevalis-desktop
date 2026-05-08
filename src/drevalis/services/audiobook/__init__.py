"""Audiobook service package — backward-compatible re-exports."""

from drevalis.services.audiobook._monolith import (  # noqa: F401
    PAUSE_BETWEEN_CHAPTERS,
    PAUSE_BETWEEN_SPEAKERS,
    PAUSE_WITHIN_SPEAKER,
    AudiobookService,
    AudioChunk,
    ChapterTiming,
)
from drevalis.services.audiobook.job_state import (  # noqa: F401
    STAGES_CHAPTER,
    STAGES_GLOBAL,
    STATES,
    compute_progress_pct,
    init_state,
    is_done,
    set_chapter_stage,
    set_global_stage,
)
from drevalis.services.audiobook.render_plan import (  # noqa: F401
    AudioEvent,
    ChapterMarker,
    RenderPlan,
)

__all__ = [
    "AudiobookService",
    "AudioChunk",
    "ChapterTiming",
    "PAUSE_BETWEEN_CHAPTERS",
    "PAUSE_BETWEEN_SPEAKERS",
    "PAUSE_WITHIN_SPEAKER",
    # Task 11: DAG job state.
    "STAGES_CHAPTER",
    "STAGES_GLOBAL",
    "STATES",
    "compute_progress_pct",
    "init_state",
    "is_done",
    "set_chapter_stage",
    "set_global_stage",
    # Task 13: RenderPlan.
    "AudioEvent",
    "ChapterMarker",
    "RenderPlan",
]
