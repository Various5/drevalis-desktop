"""RenderPlan — single source of truth for the assembled audiobook timeline.

Task 13 (scoped foundation): provides the data structures and a builder
that consume the existing pipeline outputs (chunks + chapter timings)
and produce a normalised, inspectable timeline. Subsystems
(concat, captions, CHAP frames, editor, track-mix) will eventually
consume the plan rather than re-deriving timing from raw chunks. For
this commit, the plan is built alongside the existing pipeline as an
inspectable artifact and consumed by:

  * ``AudiobookService.list_clips`` for stable editor clip IDs.
  * ``write_audiobook_id3`` for CHAP frame timestamps (with LAME
    priming offset applied).

Future passes will rewire ``_concatenate_with_context``, the ASS
captions writer, and the track-mix gain/mute application to consume
the plan directly. The data structures here are designed to support
all of those use cases without further redesign.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import UUID

EventKind = Literal["voice", "sfx", "music", "silence"]


@dataclass(frozen=True)
class AudioEvent:
    """One placement on the audiobook timeline.

    Frozen so the plan is safe to share between subsystems without
    accidental mutation. Anything that needs to override (e.g. apply a
    track-mix gain) does so by reading the event and producing a
    derivative WAV — never by mutating the plan.

    ``clip_id`` is the hash-stripped stem from Task 1
    (``ch003_chunk_0007``) so per-clip overrides survive cache busts
    caused by voice / speed / pipeline-version changes.
    """

    kind: EventKind
    chapter_idx: int
    start_ms: int  # absolute, from start of the audiobook
    duration_ms: int

    # Optional / kind-specific fields.
    block_idx: int | None = None
    speaker_id: str | None = None
    source_path: str | None = None
    gain_db: float = 0.0
    mute: bool = False
    ducking_group: str | None = None
    clip_id: str | None = None
    caption_text: str | None = None


@dataclass(frozen=True)
class ChapterMarker:
    """One chapter's audible boundary on the timeline."""

    chapter_idx: int
    title: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


@dataclass(frozen=True)
class RenderPlan:
    """Single source of truth for the assembled audiobook."""

    audiobook_id: str
    events: tuple[AudioEvent, ...]
    chapters: tuple[ChapterMarker, ...]
    total_duration_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── Construction ─────────────────────────────────────────────────

    @classmethod
    def from_pipeline_outputs(
        cls,
        *,
        audiobook_id: UUID | str,
        inline_chunks: list[Any],
        chapter_timings: list[Any],
        chapters: list[dict[str, Any]],
        chunk_durations_seconds: dict[str, float] | None = None,
    ) -> RenderPlan:
        """Build a plan from the existing pipeline's outputs.

        ``inline_chunks`` is a list of ``AudioChunk`` (the post-overlay-
        partition chunk list — voice + sequential SFX in script order).
        ``chapter_timings`` is the list of ``ChapterTiming`` produced
        by ``_compute_chapter_timings``. ``chapters`` is the parsed
        chapter dicts (with title + body text).
        ``chunk_durations_seconds`` optionally maps the chunk's stem
        to its duration; when omitted, every event reports
        ``duration_ms=0`` (callers that care should pre-probe).

        We deliberately don't reach into the AudioChunk dataclass shape
        beyond ``.path``, ``.speaker``, ``.chapter_index``,
        ``.block_index``, ``.chunk_index``, and the overlay metadata —
        keeps this module decoupled from the monolith.
        """
        from drevalis.services.audiobook._monolith import _strip_chunk_hash

        durations = chunk_durations_seconds or {}
        events: list[AudioEvent] = []
        cursor_ms = 0
        for chunk in inline_chunks:
            stem = chunk.path.stem
            stable_id = _strip_chunk_hash(stem)
            duration_seconds = durations.get(stem) or durations.get(stable_id) or 0.0
            duration_ms = int(round(duration_seconds * 1000))
            kind: EventKind = "sfx" if chunk.speaker == "__SFX__" else "voice"
            events.append(
                AudioEvent(
                    kind=kind,
                    chapter_idx=chunk.chapter_index,
                    block_idx=chunk.block_index,
                    speaker_id=chunk.speaker if kind == "voice" else None,
                    source_path=str(chunk.path),
                    start_ms=cursor_ms,
                    duration_ms=duration_ms,
                    clip_id=stable_id,
                )
            )
            cursor_ms += duration_ms

        chapter_markers: list[ChapterMarker] = []
        for timing in chapter_timings:
            idx = timing.chapter_index
            title = chapters[idx]["title"] if 0 <= idx < len(chapters) else f"Chapter {idx + 1}"
            chapter_markers.append(
                ChapterMarker(
                    chapter_idx=idx,
                    title=str(title)[:120],
                    start_ms=int(round(timing.start_seconds * 1000)),
                    end_ms=int(round(timing.end_seconds * 1000)),
                )
            )

        total_ms = chapter_markers[-1].end_ms if chapter_markers else cursor_ms

        return cls(
            audiobook_id=str(audiobook_id),
            events=tuple(events),
            chapters=tuple(chapter_markers),
            total_duration_ms=total_ms,
        )

    # ── Queries ──────────────────────────────────────────────────────

    def clip_ids(self) -> list[str]:
        """Stable, hash-stripped clip IDs in timeline order.

        ``list_clips`` and the editor consume this list so per-clip
        gain/mute overrides line up with the rendered audio without
        requiring callers to re-derive IDs from filenames.
        """
        return [e.clip_id for e in self.events if e.clip_id]

    def chapter_timestamps_ms(self) -> list[tuple[int, int, str]]:
        """Return ``[(start_ms, end_ms, title), ...]`` for CHAP frames.

        The ID3 writer applies any encoder priming offset on top of
        these values — see ``apply_priming_offset``.
        """
        return [(c.start_ms, c.end_ms, c.title) for c in self.chapters]

    def apply_priming_offset(self, offset_ms: int) -> RenderPlan:
        """Return a new plan with every chapter's start/end shifted.

        LAME's CBR encoder typically prepends ~26 ms of silence for
        bitstream priming, so the encoded MP3 is *longer* than the
        source WAV. CHAP frames written without compensation drift by
        that amount. Callers measure the offset post-encode (ffprobe
        of the MP3 minus the WAV duration) and call this to produce a
        plan whose chapter timestamps match the encoded stream.
        """
        if offset_ms == 0:
            return self
        shifted = tuple(
            ChapterMarker(
                chapter_idx=c.chapter_idx,
                title=c.title,
                start_ms=max(0, c.start_ms + offset_ms),
                end_ms=max(0, c.end_ms + offset_ms),
            )
            for c in self.chapters
        )
        return RenderPlan(
            audiobook_id=self.audiobook_id,
            events=self.events,
            chapters=shifted,
            total_duration_ms=self.total_duration_ms + offset_ms,
            metadata={**self.metadata, "lame_priming_offset_ms": offset_ms},
        )

    # ── Serialisation ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable shape for the ``render_plan_json`` column."""
        return {
            "audiobook_id": self.audiobook_id,
            "events": [asdict(e) for e in self.events],
            "chapters": [asdict(c) for c in self.chapters],
            "total_duration_ms": self.total_duration_ms,
            "metadata": self.metadata,
        }
