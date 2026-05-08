"""Music-video content-format service.

The long-standing ``shorts`` / ``longform`` pipeline produces *narrated*
video — an LLM writes a script, TTS voices it, ComfyUI generates scenes,
FFmpeg composites everything. Music videos flip that: the **backing
track is the content**, scenes are visual choreography cut to the
beats.

High-level flow (shorts + long-form share it; ``target_duration_seconds``
is the only delta):

    1. LLM generates a **song plan** — title, artist persona, mood,
       genre, structure (intro / verse / chorus / bridge / outro), with
       lyrics + a per-section visual prompt. ← v0.27.x: implemented.
    2. Backing track render. Today: routes through the existing
       MusicService for an instrumental bed (library or AceStep).
       Vocals via ACE Step v3 / ElevenLabs Music are a follow-up.
    3. Beat / onset detection on the rendered audio. ← v0.27.x:
       implemented (librosa, optional).
    4. Scene boundaries cut to bars; one scene per ``scenes_per_section``
       slot. ← v0.27.x: improved (``slice_scenes_to_beats``).
    5. ComfyUI generates each scene image/video using the song mood
       as a style anchor.
    6. FFmpeg composites: burned-in lyric captions synced to section
       times, optional beat-cut transitions.

This file is the service layer. Pipeline branching (don't fall through
to the longform path when ``content_format == 'music_video'``) lands
in a follow-up commit so the existing fallback stays as a safety net
while the new pieces are tested in isolation.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from drevalis.services.llm import LLMProvider

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ── Data structures ───────────────────────────────────────────────────────


@dataclass
class SongSection:
    """One block of the song (verse / chorus / etc.)."""

    name: str  # intro | verse1 | chorus | bridge | outro
    lyrics: str
    duration_seconds: float
    visual_prompt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SongStructure:
    """LLM-generated song plan used by the music-video pipeline."""

    title: str
    artist_persona: str
    genre: str
    mood: str
    key_bpm: tuple[str, int]  # e.g. ("C minor", 128)
    sections: list[SongSection] = field(default_factory=list)

    @property
    def total_duration_seconds(self) -> float:
        return sum(s.duration_seconds for s in self.sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist_persona": self.artist_persona,
            "genre": self.genre,
            "mood": self.mood,
            "key_bpm": list(self.key_bpm),
            "sections": [s.to_dict() for s in self.sections],
        }


# ── LLM song-plan ────────────────────────────────────────────────────────


_SYSTEM_PROMPT = (
    "You are a songwriter and music-video director. Given a topic and a "
    "target duration, produce a structured song plan: title, artist "
    "persona, genre, mood, key/BPM estimate, and sections. Each section "
    "must include name, lyrics, approximate duration in seconds, and a "
    "visual_prompt for the music-video shot. Match the total duration "
    "within ±10%. Return ONLY valid JSON matching the schema; no "
    "commentary, no markdown fences."
)

_JSON_SCHEMA = (
    "{\n"
    '  "title": "Story Title",\n'
    '  "artist_persona": "Synth-pop duo, breathy vocals",\n'
    '  "genre": "synth-pop",\n'
    '  "mood": "dreamy, nostalgic",\n'
    '  "key": "C minor",\n'
    '  "bpm": 120,\n'
    '  "sections": [\n'
    "    {\n"
    '      "name": "intro",\n'
    '      "lyrics": "(instrumental)",\n'
    '      "duration_seconds": 8,\n'
    '      "visual_prompt": "Wide neon-lit cityscape at dusk, drone shot"\n'
    "    },\n"
    "    {\n"
    '      "name": "verse1",\n'
    '      "lyrics": "Two-line lyric here\\nSecond line",\n'
    '      "duration_seconds": 24,\n'
    '      "visual_prompt": "Singer walking through rainy street, slow-mo"\n'
    "    }\n"
    "  ]\n"
    "}"
)


def _coerce_song_structure(raw: dict[str, Any]) -> SongStructure:
    """Turn the LLM's parsed JSON into a validated ``SongStructure``.

    Defensive: missing fields fall back to sensible defaults instead
    of raising, so a slightly-off LLM response doesn't fail the whole
    music-video generation.
    """
    title = str(raw.get("title") or "Untitled")[:120]
    artist = str(raw.get("artist_persona") or "Unknown artist")[:120]
    genre = str(raw.get("genre") or "synth-pop")
    mood = str(raw.get("mood") or "cinematic")

    key = str(raw.get("key") or "C major")
    try:
        bpm = int(raw.get("bpm") or 120)
    except (TypeError, ValueError):
        bpm = 120
    bpm = max(40, min(220, bpm))

    sections_raw = raw.get("sections") or []
    sections: list[SongSection] = []
    for s in sections_raw:
        if not isinstance(s, dict):
            continue
        try:
            dur = float(s.get("duration_seconds") or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        if dur <= 0.0:
            continue
        sections.append(
            SongSection(
                name=str(s.get("name") or "section")[:40],
                lyrics=str(s.get("lyrics") or "").strip(),
                duration_seconds=max(2.0, min(120.0, dur)),
                visual_prompt=str(s.get("visual_prompt") or "")[:400],
            )
        )

    return SongStructure(
        title=title,
        artist_persona=artist,
        genre=genre,
        mood=mood,
        key_bpm=(key, bpm),
        sections=sections,
    )


def _extract_json_block(content: str) -> dict[str, Any] | None:
    """Locate + parse a JSON object from an LLM response.

    Tolerates markdown fences (``  ```json`` … ``  ```  ``) and trailing
    chatter the model occasionally adds. Returns None on hard failure.
    """
    # Strip code fences first.
    text = content.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    # Find the first ``{`` … last ``}`` slice — handles trailing prose.
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last <= first:
        return None
    candidate = text[first : last + 1]
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None


async def plan_song(
    provider: LLMProvider,
    topic: str,
    target_duration_seconds: float,
    *,
    genre_hint: str | None = None,
    mood_hint: str | None = None,
) -> SongStructure:
    """Ask the LLM for a structured song plan.

    The provider is ``LLMProvider`` (any ``OpenAICompatible`` /
    ``Anthropic`` / ``LLMPool``) so the music-video pipeline reuses
    the same auth / failover machinery the rest of the app does.

    Defensive: if the LLM returns malformed JSON, returns an
    instrumental-only plan so callers can still render *something*
    rather than failing the whole episode.
    """
    target_minutes = round(target_duration_seconds / 60, 1)
    user_prompt = (
        f"Topic: {topic}\n"
        f"Target duration: {target_duration_seconds:.0f} seconds "
        f"(~{target_minutes} minutes).\n"
        + (f"Genre hint: {genre_hint}\n" if genre_hint else "")
        + (f"Mood hint: {mood_hint}\n" if mood_hint else "")
        + f"\nReturn JSON matching this schema EXACTLY:\n{_JSON_SCHEMA}\n"
    )

    try:
        result = await provider.generate(
            _SYSTEM_PROMPT,
            user_prompt,
            temperature=0.85,
            max_tokens=2500,
            json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "music_video.plan_song.llm_failed",
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
        return _instrumental_fallback(topic, target_duration_seconds, genre_hint, mood_hint)

    parsed = _extract_json_block(result.content)
    if parsed is None:
        logger.warning(
            "music_video.plan_song.json_parse_failed",
            preview=result.content[:200],
        )
        return _instrumental_fallback(topic, target_duration_seconds, genre_hint, mood_hint)

    plan = _coerce_song_structure(parsed)
    if not plan.sections:
        logger.warning("music_video.plan_song.empty_sections")
        return _instrumental_fallback(topic, target_duration_seconds, genre_hint, mood_hint)

    logger.info(
        "music_video.plan_song.done",
        title=plan.title,
        section_count=len(plan.sections),
        total_seconds=plan.total_duration_seconds,
    )
    return plan


def _instrumental_fallback(
    topic: str,
    target_duration_seconds: float,
    genre_hint: str | None,
    mood_hint: str | None,
) -> SongStructure:
    """Single-section instrumental plan when the LLM call fails.

    Keeps the music-video pipeline progressing rather than blowing up
    the whole episode. The orchestrator will produce an instrumental
    track + scenes — no lyric burn-in (sections list has only an
    intro), but the user gets a valid music video.
    """
    return SongStructure(
        title=topic[:60] or "Untitled",
        artist_persona="Drevalis instrumental",
        genre=genre_hint or "ambient",
        mood=mood_hint or "cinematic",
        key_bpm=("C minor", 120),
        sections=[
            SongSection(
                name="intro",
                lyrics="(instrumental)",
                duration_seconds=max(15.0, target_duration_seconds),
                visual_prompt=(
                    f"Cinematic music-video shot, {mood_hint or 'cinematic'} "
                    f"mood, {genre_hint or 'ambient'} genre, topic: {topic}"
                ),
            )
        ],
    )


# ── Beat detection ────────────────────────────────────────────────────────


def detect_beats(audio_path: Path) -> tuple[list[float], float]:
    """Return ``(beat_times_seconds, bpm)`` for the audio at *audio_path*.

    Uses ``librosa`` (optional dep, ``pip install '.[music_video]'``).
    Returns ``([], 0.0)`` when:
      * librosa isn't installed (orchestrator falls back to evenly-
        spaced scene cuts),
      * the audio fails to load,
      * the beat tracker returns no beats (e.g. a near-silent track).

    The orchestrator MUST handle the empty-result case gracefully —
    the music-video pipeline should never hard-fail because beat
    detection couldn't find a tempo.
    """
    try:
        import librosa  # type: ignore[import-not-found]
    except ImportError:
        logger.info("music_video.detect_beats.librosa_unavailable")
        return [], 0.0

    if not audio_path.exists():
        logger.warning("music_video.detect_beats.file_not_found", path=str(audio_path))
        return [], 0.0

    try:
        y, sr = librosa.load(str(audio_path), sr=None, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        # ``tempo`` can be a numpy 0-d array; coerce to Python float.
        bpm = float(tempo) if tempo is not None else 0.0
        return [float(t) for t in beat_times], bpm
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "music_video.detect_beats.failed",
            path=str(audio_path),
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
        return [], 0.0


# ── Scene-to-beat slicing ────────────────────────────────────────────────


def slice_scenes_to_beats(
    beats: list[float],
    sections: list[SongSection],
    *,
    scenes_per_section: int = 4,
) -> list[tuple[float, float, str]]:
    """Return a list of ``(start, end, visual_prompt)`` scene slots.

    For each section we pick scene boundaries on actual beats when
    enough beats fall inside the section's time range; otherwise we
    fall back to evenly-spaced cuts so the output never drops below
    ``scenes_per_section`` scenes per section.

    The downstream pipeline can enrich each scene's prompt with the
    specific lyric line covered for tighter visual-vocal alignment;
    the prompt returned here is the section-level fallback.
    """
    if not sections:
        return []

    slots: list[tuple[float, float, str]] = []
    cursor = 0.0
    for sec in sections:
        sec_end = cursor + sec.duration_seconds
        scenes_per_section = max(1, scenes_per_section)
        # Beats falling inside [cursor, sec_end). Good for sections with
        # several beats; we slice the section into ``scenes_per_section``
        # equal-beat-count chunks.
        sec_beats = [b for b in beats if cursor <= b < sec_end]
        if len(sec_beats) >= scenes_per_section + 1:
            # Pick beat-aligned boundaries: take every Nth beat.
            step = max(1, len(sec_beats) // scenes_per_section)
            for i in range(scenes_per_section):
                start_idx = i * step
                end_idx = (i + 1) * step
                start = sec_beats[start_idx] if start_idx < len(sec_beats) else cursor
                end = sec_beats[end_idx] if end_idx < len(sec_beats) else sec_end
                # Last slot stretches to the section end so we never
                # leave a sliver of audio uncovered by visuals.
                if i == scenes_per_section - 1:
                    end = sec_end
                slots.append((start, end, sec.visual_prompt))
        else:
            # Not enough beats to slice on — evenly space.
            step_s = sec.duration_seconds / scenes_per_section
            for i in range(scenes_per_section):
                slots.append(
                    (
                        cursor + i * step_s,
                        cursor + (i + 1) * step_s,
                        sec.visual_prompt,
                    )
                )
        cursor = sec_end
    return slots


# ── Render-song stub (vocals deferred) ───────────────────────────────────


async def render_song(
    structure: SongStructure,  # noqa: ARG001
    output_path: Path,  # noqa: ARG001
    comfyui_service: Any,  # noqa: ARG001
    provider_preference: str = "acestep",  # noqa: ARG001
) -> dict[str, Any]:
    """Render the full song with vocals to *output_path*.

    Vocals via ACE Step v3 / ElevenLabs Music / Suno is a follow-up
    commit. For now the orchestrator should call ``MusicService.
    get_music_for_episode`` directly to produce an instrumental
    backing track at the section's mood.

    Raises ``NotImplementedError`` so callers explicitly catch and
    fall back to the instrumental path rather than silently producing
    a vocal-less song.
    """
    raise NotImplementedError(
        "music_video.render_song: vocals (ACE Step v3 / ElevenLabs Music / "
        "Suno) not yet wired. Use MusicService for an instrumental backing "
        "track and burn lyric captions over the scenes instead."
    )


__all__ = [
    "SongStructure",
    "SongSection",
    "plan_song",
    "render_song",
    "detect_beats",
    "slice_scenes_to_beats",
]
