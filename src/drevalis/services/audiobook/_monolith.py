"""Audiobook generation service -- text-to-audiobook with chapters, multi-voice,
background music, output formats, and audio controls.

Converts long-form text into a single WAV audiobook by splitting on sentence
boundaries, generating TTS for each chunk, and concatenating with
context-aware silence gaps.  Supports:

- **Chapters**: Text split by ``## headers`` or ``---`` separators.
- **Multi-voice**: ``[Speaker]`` tagged blocks mapped to voice profiles.
- **Per-chapter images**: AI-generated chapter illustrations via ComfyUI.
- **Per-chapter music**: Different mood-based music per chapter with crossfades.
- **Output formats**: ``audio_only`` (WAV + MP3), ``audio_image`` (MP4 with cover),
  ``audio_video`` (MP4 with dark background or chapter images).
- **Audio controls**: Per-audiobook speed and pitch overrides.

TODO(refactor): Task 13 envisions extracting this monolith into stage modules.
The render_plan.py module landed in the scoped foundation; the rest is
deferred. Planned extraction map (each commit moves ONE block):

  * ``chaptering.py``     ← _CHAPTER_PATTERN_*, _score_chapter_split,
                            _filter_*_matches, _parse_chapters
  * ``script_tags.py``    ← _parse_voice_blocks, the [SFX:] modifier parser
  * ``chunking.py``       ← _split_text, _split_long_sentence,
                            _repair_bracket_splits, CHUNK_LIMITS,
                            _chunk_limit
  * ``tts_render.py``     ← _safety_filter_chunk,
                            _synthesize_chunk_with_retry,
                            _generate_single_voice, _generate_multi_voice,
                            _generate_silence, PROVIDER_CONCURRENCY,
                            _PROVIDER_SEMAPHORES
  * ``plan_builder.py``   ← already extracted (render_plan.py)
  * ``concat_executor.py``← _concatenate_with_context, _is_overlay_sfx,
                            _probe_audio_format, _apply_clip_override
                            (currently a closure)
  * ``mix_executor.py``   ← _mix_overlay_sfx, _add_music, _add_chapter_music,
                            _apply_master_loudnorm, DUCKING_PRESETS,
                            SFX_DUCKING, _build_music_mix_graph
  * ``image_gen.py``      ← _generate_chapter_images, _generate_title_card
  * ``music_gen.py``      ← _resolve_music_service, render_music_preview
  * ``video_render.py``   ← _create_audiobook_video,
                            _create_chapter_aware_video
  * ``metadata.py``       ← Task 13's LAME priming + write_audiobook_id3
                            wrapping (id3.py stays as the mutagen-touching
                            module)
  * ``captions.py``       ← the captions-from-audio block in generate(),
                            with the future ASS-from-RenderPlan rewiring
  * ``job_state.py``      ← already extracted (Task 11)

Once every module above is populated, _monolith.py becomes a thin
backwards-compat shim and ultimately gets deleted. The render_plan.py
data structures are the seam those modules will share.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from drevalis.schemas.audiobook import AudiobookSettings
from drevalis.services.audiobook import job_state as _js
from drevalis.services.audiobook.captions import (
    run_captions_phase as _cap_run_captions_phase,
)
from drevalis.services.audiobook.chaptering import (
    _CHAPTER_PATTERN_ALLCAPS,
    _CHAPTER_PATTERN_MARKDOWN,
    _CHAPTER_PATTERN_PROSE,
    _CHAPTER_PATTERN_ROMAN,
    _MIN_SEGMENT_CHARS,
    _SCORE_THRESHOLD,
    _filter_allcaps_matches,
    _filter_markdown_matches,
    _parse_chapters,
    _score_chapter_split,
)
from drevalis.services.audiobook.chunking import (
    CHUNK_LIMITS,  # noqa: F401 — re-exported; tests import from _monolith
    _chunk_limit,  # noqa: F401 — used via shims in tts_render.py
    _repair_bracket_splits,
    _split_long_sentence,
    _split_text,
)
from drevalis.services.audiobook.concat_executor import (
    concatenate_with_context as _concat_concatenate_with_context,
)
from drevalis.services.audiobook.concat_executor import (
    is_overlay_sfx as _concat_is_overlay_sfx,
)
from drevalis.services.audiobook.concat_executor import (
    probe_audio_format as _concat_probe_audio_format,
)
from drevalis.services.audiobook.image_gen import (
    _generate_chapter_images,
    _generate_title_card,
)
from drevalis.services.audiobook.metadata import _apply_lame_priming_and_tag
from drevalis.services.audiobook.mix_executor import (
    DEFAULT_DUCKING_PRESET,  # noqa: F401 — re-exported; tests/callers import from _monolith
    DUCKING_PRESETS,  # noqa: F401 — re-exported; tests/callers import from _monolith
    MASTER_LIMITER_CEILING_DB,  # noqa: F401 — re-exported
    SFX_DUCKING,  # noqa: F401 — re-exported; tests/callers import from _monolith
)
from drevalis.services.audiobook.mix_executor import (
    add_chapter_music as _mix_add_chapter_music,
)
from drevalis.services.audiobook.mix_executor import (
    add_music as _mix_add_music,
)
from drevalis.services.audiobook.mix_executor import (
    apply_master_loudnorm as _mix_apply_master_loudnorm,
)
from drevalis.services.audiobook.mix_executor import (
    build_music_mix_graph as _mix_build_music_mix_graph,
)
from drevalis.services.audiobook.mix_executor import (
    compute_chapter_timings as _mix_compute_chapter_timings,
)
from drevalis.services.audiobook.mix_executor import (
    mix_overlay_sfx as _mix_mix_overlay_sfx,
)
from drevalis.services.audiobook.mix_executor import (
    parse_loudnorm_json as _mix_parse_loudnorm_json,
)
from drevalis.services.audiobook.music_gen import (
    _resolve_music_service,
)
from drevalis.services.audiobook.music_gen import (
    render_music_preview as _render_music_preview_fn,
)
from drevalis.services.audiobook.render_plan import RenderPlan
from drevalis.services.audiobook.script_tags import _parse_voice_blocks
from drevalis.services.audiobook.tts_render import (
    _PROVIDER_SEMAPHORES,  # noqa: F401 — re-exported; tests import from _monolith
    PROVIDER_CONCURRENCY,  # noqa: F401 — re-exported; tests import from _monolith
    _provider_concurrency,  # noqa: F401 — re-exported; tests import from _monolith
)
from drevalis.services.audiobook.tts_render import (
    _provider_semaphore as _get_provider_semaphore,  # noqa: F401 — re-exported alias
)
from drevalis.services.audiobook.tts_render import (
    generate_multi_voice as _tts_generate_multi_voice,
)
from drevalis.services.audiobook.tts_render import (
    generate_silence as _tts_generate_silence,
)
from drevalis.services.audiobook.tts_render import (
    generate_single_voice as _tts_generate_single_voice,
)
from drevalis.services.audiobook.tts_render import (
    safety_filter_chunk as _tts_safety_filter_chunk,
)
from drevalis.services.audiobook.tts_render import (
    synthesize_chunk_with_retry as _tts_synthesize_chunk_with_retry,
)
from drevalis.services.audiobook.versions import AUDIO_PIPELINE_VERSION
from drevalis.services.audiobook.video_render import (
    create_audiobook_video as _vr_create_audiobook_video,
)
from drevalis.services.audiobook.video_render import (
    create_chapter_aware_video as _vr_create_chapter_aware_video,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.models.voice_profile import VoiceProfile
    from drevalis.services.comfyui import ComfyUIService
    from drevalis.services.ffmpeg import FFmpegService
    from drevalis.services.storage import StorageBackend
    from drevalis.services.tts import TTSService

log = structlog.get_logger(__name__)

# ── Context-aware pause durations (seconds) ──────────────────────────────────
PAUSE_WITHIN_SPEAKER = 0.15  # 150 ms between chunks of the same speaker
PAUSE_BETWEEN_SPEAKERS = 0.4  # 400 ms between different speakers
PAUSE_BETWEEN_CHAPTERS = 1.2  # 1.2 s between chapters

# ── Silence-trim policy (Task 2) ─────────────────────────────────────────────
# The MP3 export filter chain used to run ``silenceremove`` at both ends, which
# also removed intentional dramatic pauses *inside* the audiobook (the filter
# matches anything below the threshold for the configured duration, not just
# at the boundaries). It also drifted CHAP frame timestamps relative to the
# encoded stream and broke ASS caption sync.
#
# Defaults below preserve every internal pause and skip leading/trailing
# trimming entirely. When ``TRIM_LEADING_TRAILING_SILENCE`` is flipped on
# (Task 9 will wire this through the settings object), the trim runs on the
# WAV BEFORE chapter timings and captions are produced, and the recorded
# leading offset is propagated through both so audible boundaries still
# match CHAP frames within ±50 ms.
TRIM_LEADING_TRAILING_SILENCE = False
PRESERVE_INTERNAL_PAUSES = True

# ── Loudness strategy (Task 3) ───────────────────────────────────────────────
# Single audible loudnorm pass, performed at the master stage with EBU R128's
# two-pass measure-then-apply algorithm. Per-chunk loudnorm is gone — running
# integrated-loudness on sub-second audio doesn't converge and only produced
# inter-sentence loudness jitter when chained with the master pass. Per-chunk
# work is now peak safety only (highpass + alimiter).
#
# MP3 export no longer carries its own loudnorm; the WAV the encoder reads is
# already mastered. End-to-end this means: the audiobook is loudnorm'd exactly
# once, at the right time, against integrated content rather than fragments.
#
# Defaults below are the narrative preset. Task 9 will route platform-specific
# overrides (-16 LUFS / LRA 11 for podcast, -14 LUFS for streaming, -20 LUFS /
# LRA 18 for ACX) through the settings object.
LOUDNESS_TARGET_LUFS = -18.0
TRUE_PEAK_DBFS = -2.0
LOUDNESS_LRA = 14.0

# ── Music-bed ducking presets (Task 6) ───────────────────────────────────────
# DUCKING_PRESETS, DEFAULT_DUCKING_PRESET, SFX_DUCKING, MASTER_LIMITER_CEILING_DB
# now live in mix_executor.py and are re-imported above (with noqa: F401 so
# existing callers that do ``from _monolith import DUCKING_PRESETS`` still work).


def _build_music_mix_graph(
    *,
    preset: dict[str, Any],
    voice_gain_db: float,
    music_volume_db: float,
    music_pad_ms: int,
) -> str:
    """Delegation shim — see ``mix_executor.build_music_mix_graph``."""
    return _mix_build_music_mix_graph(
        preset=preset,
        voice_gain_db=voice_gain_db,
        music_volume_db=music_volume_db,
        music_pad_ms=music_pad_ms,
    )


def _mp3_encoder_args(mode: str) -> list[str]:
    """Return the libmp3lame encoder argv tail for *mode*.

    Recognised modes (Task 9): ``cbr_128``, ``cbr_192``, ``cbr_256``,
    ``vbr_v0``, ``vbr_v2``. Unknown modes fall back to CBR 192 kbps —
    the pre-Task-9 default — so a mistyped mode never fails the
    audiobook.
    """
    if mode.startswith("cbr_"):
        bitrate = mode.split("_", 1)[1]
        return ["-codec:a", "libmp3lame", "-b:a", f"{bitrate}k"]
    if mode == "vbr_v0":
        return ["-codec:a", "libmp3lame", "-q:a", "0"]
    if mode == "vbr_v2":
        return ["-codec:a", "libmp3lame", "-q:a", "2"]
    log.warning("audiobook.mp3_encoder.unknown_mode_falling_back", mode=mode)
    return ["-codec:a", "libmp3lame", "-b:a", "192k"]


def _resolve_ducking_preset(name: str | None) -> dict[str, Any]:
    """Look up *name* in ``DUCKING_PRESETS`` (case-insensitive).

    Unknown names log a warning and fall back to the default
    ``static`` preset so an upstream typo can't fail generation.
    """
    if name is None:
        return DUCKING_PRESETS[DEFAULT_DUCKING_PRESET]
    key = name.strip().lower()
    if key in DUCKING_PRESETS:
        return DUCKING_PRESETS[key]
    log.warning(
        "audiobook.ducking.unknown_preset_falling_back",
        requested=name,
        fallback=DEFAULT_DUCKING_PRESET,
        known=sorted(DUCKING_PRESETS.keys()),
    )
    return DUCKING_PRESETS[DEFAULT_DUCKING_PRESET]


# ── Per-provider chunk size (Task 12) ────────────────────────────────────────
# CHUNK_LIMITS and _chunk_limit now live in chunking.py; imported above.
# _PROVIDER_CONCURRENCY, _PROVIDER_SEMAPHORES, _provider_concurrency, and
# _get_provider_semaphore now live in tts_render.py (imported above).
# _PROVIDER_CONCURRENCY is re-exported from tts_render as PROVIDER_CONCURRENCY;
# _PROVIDER_SEMAPHORES and _get_provider_semaphore are re-imported above.


class CancelChecker:
    """Debounced Redis poller for the audiobook cancel flag (Task 10).

    Pre-Task-10, polls happened only at chapter boundaries — a long-form
    chapter with hundreds of chunks running in parallel could drag a
    Cancel click out for minutes while the in-flight gather drained.
    The new design polls Redis at every reasonable seam (TTS attempts,
    ffmpeg invocations, image / music generation) but caps the actual
    Redis traffic to one GET per second per checker; intermediate calls
    are no-ops.

    Failures from Redis (network blip, broken pool) are swallowed —
    cancellation is a UX feature, not a correctness one, and a Redis
    outage shouldn't fail the audiobook.
    """

    __slots__ = ("_redis", "_key", "_last_check")

    def __init__(self, redis: Any, audiobook_id: UUID) -> None:
        self._redis = redis
        self._key = f"cancel:audiobook:{audiobook_id}"
        self._last_check = 0.0

    async def check(self) -> None:
        now = time.monotonic()
        if now - self._last_check < 1.0:
            return
        self._last_check = now
        if self._redis is None:
            return
        try:
            flag = await self._redis.get(self._key)
        except Exception:
            return
        if flag:
            raise asyncio.CancelledError(f"audiobook cancelled by user (key={self._key})")


@dataclass
class AudioChunk:
    """An audio chunk with metadata for context-aware concatenation."""

    path: Path
    chapter_index: int
    speaker: str
    block_index: int
    chunk_index: int
    # SFX overlay metadata — populated only when this chunk is an
    # SFX clip with an ``under=...`` modifier. The concatenator
    # treats overlay SFX as a sidechain layer on subsequent voice
    # chunks instead of an inline chunk in the timeline.
    overlay_voice_blocks: int | None = None
    overlay_seconds: float | None = None
    overlay_duck_db: float = -12.0


@dataclass
class ChapterTiming:
    """Timing information for a chapter in the concatenated audio."""

    chapter_index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float


# ── Hash-keyed chunk cache ────────────────────────────────────────────────
#
# Chunk filenames embed a 12-hex-char content hash so changing any input
# that influences the rendered audio (voice profile, provider, speed,
# pitch, pipeline version, …) produces a new filename and forces re-render.
# The hash sits at the END of the stem so the chapter / chunk index prefix
# remains a stable, human-readable handle for the editor.

# Matches a trailing ``_<12 hex>`` suffix on a chunk stem.
_CHUNK_HASH_SUFFIX_RE = re.compile(r"_(?P<h>[0-9a-f]{12})$")


def _chunk_cache_hash(
    *,
    text: str,
    speaker_id: str,
    voice_profile_id: str,
    provider: str,
    model: str,
    speed: float,
    pitch: float,
    sample_rate: int,
) -> str:
    """Return the 12-hex-char cache hash for a TTS chunk.

    The set of inputs is the contract: any field that can change the
    bytes ffmpeg ultimately writes for this chunk MUST be in here. If a
    new input is added, also bump ``AUDIO_PIPELINE_VERSION`` so existing
    caches are invalidated cleanly even when the new field defaults match
    the old behaviour.
    """
    payload = json.dumps(
        {
            "text": text,
            "speaker_id": speaker_id,
            "voice_profile_id": voice_profile_id,
            "provider": provider,
            "model": model,
            "speed": float(speed),
            "pitch": float(pitch),
            "sample_rate": int(sample_rate),
            "pipeline_version": AUDIO_PIPELINE_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def _strip_chunk_hash(stem: str) -> str:
    """Return the editor-facing stable id for a chunk file stem.

    ``ch003_chunk_0007_a1b2c3d4e5f6`` → ``ch003_chunk_0007``.
    Stems without a recognised hash suffix are returned unchanged, so
    legacy index-only filenames keep working through the migration.
    """
    return _CHUNK_HASH_SUFFIX_RE.sub("", stem)


def _provider_identity(provider: Any, voice_profile: Any) -> tuple[str, str]:
    """Best-effort ``(provider_name, model_id)`` for cache hashing.

    Providers don't share a strict interface for these attributes; we
    pull whatever is available without forcing every TTSProvider impl
    to grow new public surface. Fallbacks are stable strings so the
    hash is still deterministic across runs.
    """
    provider_name = (
        getattr(provider, "name", None)
        or getattr(provider, "provider_name", None)
        or type(provider).__name__
    )
    model = (
        getattr(voice_profile, "model_name", None)
        or getattr(voice_profile, "model", None)
        or getattr(voice_profile, "voice_id", None)
        or ""
    )
    return str(provider_name), str(model)


class AudiobookService:
    """High-level service for generating audiobooks from text."""

    # Per-call state attributes are populated by ``_initialize_call_state``
    # at the top of ``generate``. Declared at class scope so mypy can
    # type-check helper methods that read them (``_dag_chapter`` etc.)
    # without having to follow every ``generate`` code path.
    _job_state: dict[str, Any]

    def __init__(
        self,
        tts_service: TTSService,
        ffmpeg_service: FFmpegService,
        storage: StorageBackend,
        db_session: AsyncSession | None = None,
        comfyui_service: ComfyUIService | None = None,
        redis: Redis | None = None,
    ) -> None:
        self.tts = tts_service
        self.ffmpeg = ffmpeg_service
        self.storage = storage
        self.db_session = db_session
        self.comfyui_service = comfyui_service
        self.redis = redis

    # ══════════════════════════════════════════════════════════════════════
    # Cancellation
    # ══════════════════════════════════════════════════════════════════════
    #
    # Mirrors the episode pipeline's pattern: the API endpoint sets
    # ``cancel:audiobook:{id}`` in Redis with a short TTL; long-running
    # steps inside ``generate()`` poll this between chapters and raise
    # ``asyncio.CancelledError`` on a hit. The flag is cleared once
    # the audiobook reaches a terminal status so a subsequent
    # generation of the same audiobook doesn't see the stale signal.

    async def _check_cancelled(self, audiobook_id: UUID) -> None:
        """Raise ``CancelledError`` if a cancel flag is set for this audiobook.

        Chapter-boundary entry point — kept for legacy callers that
        don't have a ``CancelChecker`` (one-shot regeneration jobs that
        instantiate the service outside ``generate``).
        """
        if not self.redis:
            return
        try:
            flag = await self.redis.get(f"cancel:audiobook:{audiobook_id}")
        except Exception:
            return
        if flag:
            log.info("audiobook.generate.cancelled_by_user", audiobook_id=str(audiobook_id))
            raise asyncio.CancelledError(f"Audiobook {audiobook_id} cancelled by user")

    async def _cancel(self) -> None:
        """Debounced cancel poll — fires at every reasonable seam.

        Reads ``self._cancel_checker`` (set in ``generate``); no-op
        when unset so deeper helpers called outside ``generate``
        (e.g. the regenerate-image one-shot job) don't break.
        """
        checker = getattr(self, "_cancel_checker", None)
        if checker is None:
            return
        await checker.check()

    # ══════════════════════════════════════════════════════════════════════
    # DAG job state mutation helpers (Task 11)
    # ══════════════════════════════════════════════════════════════════════

    async def _dag_chapter(self, chapter_index: int, stage: str, value: _js.State) -> None:
        """Mutate the chapter stage and fire the persist callback."""
        if not getattr(self, "_job_state", None):
            return
        _js.set_chapter_stage(self._job_state, chapter_index, stage, value)
        await self._persist_dag()

    async def _dag_global(self, stage: str, value: _js.State) -> None:
        """Mutate a global stage and fire the persist callback."""
        if not getattr(self, "_job_state", None):
            return
        _js.set_global_stage(self._job_state, stage, value)
        await self._persist_dag()

    async def _persist_dag(self) -> None:
        """Push the current DAG to the worker's persistence callback.

        Failures from the callback are logged + swallowed — the DAG is
        a recovery aid, not a correctness one. We never want a Postgres
        blip during the persist to fail the whole audiobook.
        """
        cb = getattr(self, "_persist_job_state_cb", None)
        if cb is None:
            return
        try:
            res = cb(dict(self._job_state))
            if asyncio.iscoroutine(res):
                await res
        except Exception as exc:  # noqa: BLE001
            log.warning("audiobook.job_state.persist_failed", error=str(exc)[:200])

    def _dag_chapter_done(self, chapter_index: int, stage: str) -> bool:
        """``True`` iff the chapter stage is already ``done`` (skip)."""
        if not getattr(self, "_job_state", None):
            return False
        return _js.is_done(self._job_state, stage, chapter_index)

    def _dag_global_done(self, stage: str) -> bool:
        if not getattr(self, "_job_state", None):
            return False
        return _js.is_done(self._job_state, stage)

    async def _persist_render_plan(self, plan: RenderPlan) -> None:
        """Push the current ``RenderPlan`` to the worker's persist callback.

        Failures are logged + swallowed — the plan is an inspectable
        artifact, not a correctness one. A Postgres blip during the
        persist must not fail the whole audiobook.
        """
        cb = getattr(self, "_persist_render_plan_cb", None)
        if cb is None:
            return
        try:
            res = cb(plan.to_dict())
            if asyncio.iscoroutine(res):
                await res
        except Exception as exc:  # noqa: BLE001
            log.warning("audiobook.render_plan.persist_failed", error=str(exc)[:200])

    async def _clear_cancel_flag(self, audiobook_id: UUID) -> None:
        if not self.redis:
            return
        try:
            await self.redis.delete(f"cancel:audiobook:{audiobook_id}")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════
    # Progress broadcasting
    # ══════════════════════════════════════════════════════════════════════

    async def _broadcast_progress(
        self,
        audiobook_id: UUID,
        step: str,
        progress_pct: int,
        message: str = "",
    ) -> None:
        """Publish a progress update via Redis pub/sub."""
        if not self.redis:
            return
        import json as _json

        channel = f"progress:audiobook:{audiobook_id}"
        payload = _json.dumps(
            {
                "audiobook_id": str(audiobook_id),
                "step": step,
                "progress_pct": progress_pct,
                "message": message,
            }
        )
        try:
            await self.redis.publish(channel, payload)
        except Exception:
            pass  # non-critical

    # ══════════════════════════════════════════════════════════════════════
    # Per-chapter fast path — invalidate only the chunk cache for one
    # chapter so the next ``generate`` call re-TTSes just that chapter
    # while reusing every other chapter's cached WAVs.
    # ══════════════════════════════════════════════════════════════════════

    async def invalidate_chapter_chunks(
        self,
        audiobook_id: UUID,
        chapter_index: int,
    ) -> int:
        """Delete the on-disk chunk cache for ``chapter_index``.

        Returns the number of WAVs deleted. A subsequent call to
        :meth:`generate` will re-synthesise only those chunks (the
        existing per-chunk ``if chunk_path.exists()`` cache skips every
        unaffected chapter) and re-concatenate the whole audiobook.
        """
        from pathlib import Path

        # StorageBackend is a Protocol that doesn't declare ``base_path``
        # (it's on the LocalStorage concrete impl). Resolve via
        # ``resolve_path`` which every implementation provides and which
        # returns an absolute Path under the storage root.
        rel_dir = f"audiobooks/{audiobook_id}"
        output_dir = Path(self.storage.resolve_path(rel_dir))
        if not output_dir.exists():
            return 0

        # Match both single-voice (``ch003_chunk_*``) and multi-voice
        # block-style (``ch003_block_*_chunk_*``) chunks. The previous
        # implementation only cleared single-voice files, so a per-
        # chapter regenerate of a multi-voice audiobook silently
        # reused stale block chunks.
        deleted = 0
        single_prefix = f"ch{int(chapter_index):03d}_chunk_"
        block_prefix = f"ch{int(chapter_index):03d}_block_"
        for child in output_dir.iterdir():
            if child.suffix != ".wav":
                continue
            if child.name.startswith(single_prefix) or child.name.startswith(block_prefix):
                try:
                    child.unlink()
                    deleted += 1
                except OSError:
                    pass
        log.info(
            "audiobook.chapter_chunks_invalidated",
            audiobook_id=str(audiobook_id),
            chapter_index=chapter_index,
            deleted=deleted,
        )
        return deleted

    # ══════════════════════════════════════════════════════════════════════
    # Legacy chunk cache purge (one-shot, idempotent)
    # ══════════════════════════════════════════════════════════════════════
    #
    # Pre-hash chunk filenames had no content key, so a voice / speed /
    # pipeline change silently reused stale audio. On first generation
    # after upgrade we walk the audiobook output dir once and delete any
    # chunk file that doesn't carry the new ``_<12hex>`` suffix. The
    # next ``generate`` call re-renders those chunks under the new
    # naming scheme. Idempotent: subsequent runs find nothing to do.

    _LEGACY_SINGLE_RE = re.compile(r"^ch\d{3}_chunk_\d{4}\.wav$")
    _LEGACY_BLOCK_RE = re.compile(r"^ch\d{3}_block_\d{4}_chunk_\d{4}\.wav$")

    async def _purge_legacy_chunks(self, output_dir: Path) -> int:
        """Delete pre-hash chunk files in *output_dir*. Returns the count."""
        if not output_dir.exists():
            return 0
        deleted = 0
        for child in output_dir.iterdir():
            if not child.is_file():
                continue
            if self._LEGACY_SINGLE_RE.match(child.name) or self._LEGACY_BLOCK_RE.match(child.name):
                try:
                    child.unlink()
                    deleted += 1
                except OSError:
                    pass
        if deleted:
            log.info(
                "audiobook.cache.legacy_format_purged",
                output_dir=str(output_dir),
                deleted=deleted,
                pipeline_version=AUDIO_PIPELINE_VERSION,
            )
        return deleted

    # ══════════════════════════════════════════════════════════════════════
    # Clip listing — used by the Audiobook Editor (v0.25.0)
    # ══════════════════════════════════════════════════════════════════════
    #
    # Walks the audiobook's storage dir and emits a structured list
    # of every cached audio clip the editor can address. Filenames
    # are deterministic (see ``_generate_single_voice``,
    # ``_generate_multi_voice``, ``_generate_sfx_chunk``,
    # ``_add_chapter_music``) so we can derive stable, URL-safe
    # clip IDs without persisting a separate registry.

    # Hash suffix is optional so legacy index-only files (created before
    # the hash-keyed cache) still surface in the editor during the
    # migration window. The editor's clip_id is the stem with any
    # trailing ``_<12hex>`` stripped — see ``_strip_chunk_hash`` — so
    # per-clip overrides survive a cache bust caused by a voice change.
    _CLIP_PATTERNS: tuple[tuple[str, str], ...] = (
        # single-voice voice chunks: ch003_chunk_0007[_<hash12>].wav
        ("voice_single", r"^ch(?P<ch>\d{3})_chunk_(?P<i>\d{4})(?:_[0-9a-f]{12})?\.wav$"),
        # multi-voice voice chunks: ch003_block_0002_chunk_0007[_<hash12>].wav
        (
            "voice_multi",
            r"^ch(?P<ch>\d{3})_block_(?P<b>\d{4})_chunk_(?P<j>\d{4})(?:_[0-9a-f]{12})?\.wav$",
        ),
        # SFX: ch003_sfx_0002.wav (no hash — SFX cache key is just
        # the script position; description changes require an explicit
        # regenerate today, same as before).
        ("sfx", r"^ch(?P<ch>\d{3})_sfx_(?P<b>\d{4})\.wav$"),
    )

    async def list_clips(self, audiobook_id: UUID) -> dict[str, Any]:
        """Return all addressable clips for the audiobook + persisted overrides.

        Output shape::

            {
              "tracks": {
                "voice": [Clip, ...],
                "sfx":   [Clip, ...],
                "music": [Clip, ...]
              },
              "overrides": { "<clip_id>": {gain_db, mute}, ... }
            }

        Each ``Clip`` carries ``id`` (URL-safe), ``kind``, ``chapter``,
        ``filename``, ``duration_seconds``, ``url`` (under /storage),
        and ``label`` (display string).
        """
        from re import compile as _re_compile

        rel_dir = f"audiobooks/{audiobook_id}"
        abs_dir = Path(self.storage.resolve_path(rel_dir))
        result: dict[str, Any] = {
            "tracks": {"voice": [], "sfx": [], "music": []},
            "overrides": {},
        }
        if not abs_dir.exists():
            return result

        compiled = [(kind, _re_compile(pat)) for kind, pat in self._CLIP_PATTERNS]

        async def _emit(track: str, path: Path, kind: str, label: str, chapter: int) -> None:
            try:
                duration = await self.ffmpeg.get_duration(path)
            except Exception:
                duration = 0.0
            # Strip the optional hash suffix so the clip_id is stable
            # across cache busts (voice profile / speed / pipeline
            # version changes). track_mix.clips overrides keyed off
            # this id continue to apply to whichever rendered version
            # is currently on disk.
            clip_id = _strip_chunk_hash(path.stem)
            result["tracks"][track].append(
                {
                    "id": clip_id,
                    "kind": kind,
                    "chapter": chapter,
                    "filename": path.name,
                    "duration_seconds": round(duration, 3),
                    "url": f"/storage/{rel_dir}/{path.name}",
                    "label": label,
                }
            )

        # Voice + SFX clips live directly under the audiobook dir.
        for child in sorted(abs_dir.iterdir()):
            if not child.is_file() or child.suffix != ".wav":
                continue
            for kind, regex in compiled:
                m = regex.match(child.name)
                if not m:
                    continue
                ch = int(m.group("ch"))
                if kind == "voice_single":
                    label = f"Ch {ch + 1} · chunk {int(m.group('i')) + 1}"
                    await _emit("voice", child, kind, label, ch)
                elif kind == "voice_multi":
                    label = (
                        f"Ch {ch + 1} · block {int(m.group('b')) + 1}"
                        f" · chunk {int(m.group('j')) + 1}"
                    )
                    await _emit("voice", child, kind, label, ch)
                elif kind == "sfx":
                    label = f"Ch {ch + 1} · SFX {int(m.group('b')) + 1}"
                    await _emit("sfx", child, kind, label, ch)
                break

        # Per-chapter music tracks are written to ``music/``.
        music_dir = abs_dir / "music"
        if music_dir.exists():
            music_re = _re_compile(r"^ch(?P<ch>\d{3})_music\.wav$")
            for child in sorted(music_dir.iterdir()):
                m = music_re.match(child.name)
                if not m:
                    continue
                ch = int(m.group("ch"))
                # Use a path-aware id so it doesn't collide with voice clip stems.
                try:
                    duration = await self.ffmpeg.get_duration(child)
                except Exception:
                    duration = 0.0
                result["tracks"]["music"].append(
                    {
                        "id": f"music_{child.stem}",
                        "kind": "music",
                        "chapter": ch,
                        "filename": child.name,
                        "duration_seconds": round(duration, 3),
                        "url": f"/storage/{rel_dir}/music/{child.name}",
                        "label": f"Ch {ch + 1} · music",
                    }
                )

        # Sort each track by chapter then filename for stable display.
        for tk in result["tracks"].values():
            tk.sort(key=lambda c: (c["chapter"], c["filename"]))

        return result

    # ══════════════════════════════════════════════════════════════════════
    # TTS chunk synthesis with retry + loudnorm
    # ══════════════════════════════════════════════════════════════════════

    async def _synthesize_chunk_with_retry(
        self,
        provider: Any,
        text: str,
        voice_id: str,
        chunk_path: Path,
        *,
        speed: float,
        pitch: float,
        max_attempts: int = 3,
    ) -> bool:
        """Delegation shim — see ``tts_render.synthesize_chunk_with_retry``.

        Per-chunk retry isolates a single transient failure (cloud
        TTS 5xx, ComfyUI queue eviction, brief network blip) from
        torpedoing the whole chapter, which previously meant losing
        199 successful chunks because chunk 200 hit a one-off blip.

        After a successful synth, we run ffmpeg ``loudnorm`` to
        EBU R128 ``I=-16 LUFS / TP=-1.5`` on the chunk in place.
        Multi-voice audiobooks otherwise have a noticeable
        chunk-to-chunk loudness wobble: each provider hands back
        audio at its own default level (Edge ≈ -22 LUFS, ElevenLabs
        ≈ -16, Piper varies by voice). Normalising per-chunk
        flattens that into a uniform broadcast level before concat.

        Returns True if a real audio file landed on disk; False if we
        exhausted retries (caller is expected to fall back to
        ``_generate_silence`` so the timing structure stays intact).
        """
        return await _tts_synthesize_chunk_with_retry(
            provider,
            text,
            voice_id,
            chunk_path,
            speed=speed,
            pitch=pitch,
            max_attempts=max_attempts,
            cancel_fn=self._cancel,
        )

    async def _safety_filter_chunk(self, chunk_path: Path) -> None:
        """Delegation shim — see ``tts_render.safety_filter_chunk``."""
        await _tts_safety_filter_chunk(chunk_path)

    # ══════════════════════════════════════════════════════════════════════
    # Sound effects ([SFX: ...] tag handling)
    # ══════════════════════════════════════════════════════════════════════

    def _resolve_sfx_provider(self) -> Any | None:
        """Build a ComfyUIElevenLabsSoundEffectsProvider on the
        first registered ComfyUI server, or ``None`` if no server
        is available. SFX blocks gracefully degrade to silence in
        that case so the audiobook still completes.
        """
        if self.comfyui_service is None:
            return None
        try:
            servers = getattr(self.comfyui_service._pool, "_servers", {})
            if not servers:
                return None
            first_id = next(iter(servers))
            client = servers[first_id][0]
            base_url = getattr(client, "base_url", None)
            api_key = getattr(client, "api_key", None)
            if not base_url:
                return None
        except Exception as exc:
            log.warning("audiobook.sfx.provider_resolve_failed", error=str(exc)[:120])
            return None

        from drevalis.services.tts import ComfyUIElevenLabsSoundEffectsProvider

        return ComfyUIElevenLabsSoundEffectsProvider(
            comfyui_base_url=base_url,
            comfyui_api_key=api_key,
        )

    async def _generate_sfx_chunk(
        self,
        block: dict[str, Any],
        output_dir: Path,
        chapter_index: int,
        block_index: int,
    ) -> AudioChunk | None:
        """Generate a single SFX chunk for a parsed [SFX:] block.

        Returns the AudioChunk on success, or None if the SFX
        provider isn't available / the call failed (the chapter
        still completes — SFX is enrichment, not a hard requirement).
        """
        description = block.get("description", "").strip()
        if not description:
            return None
        duration = float(block.get("duration", 4.0) or 4.0)
        loop = bool(block.get("loop", False))
        prompt_influence = block.get("prompt_influence")

        # Cache by chapter + block index so a retry doesn't re-pay
        # the SFX cost.
        chunk_path = output_dir / f"ch{chapter_index:03d}_sfx_{block_index:04d}.wav"
        if chunk_path.exists() and chunk_path.stat().st_size > 100:
            log.info(
                "audiobook.sfx.cached",
                chapter_index=chapter_index,
                block_index=block_index,
                description=description[:80],
            )
        else:
            provider = self._resolve_sfx_provider()
            if provider is None:
                log.warning(
                    "audiobook.sfx.no_provider",
                    description=description[:80],
                    hint="No ComfyUI server registered; SFX will be silent.",
                )
                await self._generate_silence(chunk_path, duration=duration)
            else:
                try:
                    log.info(
                        "audiobook.sfx.generate.start",
                        description=description[:120],
                        duration=duration,
                    )
                    await provider.synthesize_sfx(
                        description=description,
                        duration=duration,
                        output_path=chunk_path,
                        loop=loop,
                        prompt_influence=prompt_influence,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "audiobook.sfx.generate.failed",
                        description=description[:120],
                        error=f"{type(exc).__name__}: {str(exc)[:200]}",
                    )
                    await self._generate_silence(chunk_path, duration=duration)

        if not chunk_path.exists():
            return None
        return AudioChunk(
            path=chunk_path,
            chapter_index=chapter_index,
            speaker="__SFX__",
            block_index=block_index,
            chunk_index=0,
            overlay_voice_blocks=block.get("under_voice_blocks"),
            overlay_seconds=block.get("under_seconds"),
            overlay_duck_db=float(block.get("duck_db", -12.0) or -12.0),
        )

    # ══════════════════════════════════════════════════════════════════════
    # Preflight
    # ══════════════════════════════════════════════════════════════════════

    @dataclass
    class PreflightWarning:
        code: str
        message: str
        severity: str  # "info" | "warning" | "error"

    async def preflight(
        self,
        text: str,
        voice_profile: Any | None,
        *,
        voice_casting: dict[str, str] | None = None,
        music_enabled: bool = False,
        music_mood: str | None = None,
        per_chapter_music: bool = False,
        image_generation_enabled: bool = False,
        output_format: str = "audio_only",
    ) -> list[AudiobookService.PreflightWarning]:
        """Validate inputs cheaply and return any blockers / hints.

        Runs in <1s and surfaces every condition that would otherwise
        only trip the user up 30+ minutes into a real generation
        (missing voice profiles, empty / untagged text, ComfyUI not
        wired up when image gen or AceStep music is on, etc.).

        Severity ``error`` items will block ``generate``; the worker
        layer can choose to refuse-with-message rather than starting.
        """
        warnings: list[AudiobookService.PreflightWarning] = []
        W = AudiobookService.PreflightWarning

        # --- Text shape ----------------------------------------------------
        if not text or not text.strip():
            warnings.append(W("empty_text", "Audiobook text is empty.", "error"))
            return warnings  # everything else depends on text
        if len(text.strip()) < 80:
            warnings.append(
                W(
                    "very_short_text",
                    f"Text is only {len(text.strip())} chars. Generation will work but the result will be a few seconds long.",
                    "warning",
                )
            )

        # --- Voice profile -------------------------------------------------
        if voice_profile is None:
            warnings.append(
                W(
                    "no_voice_profile",
                    "No voice profile is assigned. Pick one in the audiobook settings before generating.",
                    "error",
                )
            )

        # --- Voice casting / [Speaker] tags --------------------------------
        speaker_tags = re.findall(r"\[([^\]]+)\]", text)
        unique_speakers = sorted(set(speaker_tags))
        if voice_casting and unique_speakers:
            missing = [s for s in unique_speakers if s not in voice_casting]
            if missing:
                warnings.append(
                    W(
                        "voice_casting_missing",
                        f"voice_casting has no entry for: {', '.join(missing)}. These speakers will fall back to the default voice.",
                        "warning",
                    )
                )

        # --- Music ---------------------------------------------------------
        if music_enabled:
            if not music_mood and not per_chapter_music:
                warnings.append(
                    W(
                        "music_no_mood",
                        "music_enabled is true but no music_mood is set and per_chapter_music is off.",
                        "warning",
                    )
                )
            # If AceStep (ComfyUI) is the only way to fulfil this mood,
            # warn when no ComfyUI server is registered.
            if not self.comfyui_service or not getattr(self.comfyui_service._pool, "_servers", {}):
                warnings.append(
                    W(
                        "music_no_comfyui",
                        "Music is enabled but no ComfyUI server is registered for AceStep generation. The curated library will be tried first; missing moods will be silent.",
                        "info",
                    )
                )

        # --- Image generation ---------------------------------------------
        if image_generation_enabled:
            if not self.comfyui_service or not getattr(self.comfyui_service._pool, "_servers", {}):
                warnings.append(
                    W(
                        "images_no_comfyui",
                        "image_generation_enabled is true but no ComfyUI server is registered. Chapter images will fall back to title cards.",
                        "warning",
                    )
                )

        # --- Output format vs assets --------------------------------------
        if output_format not in ("audio_only", "audio_image", "audio_video"):
            warnings.append(
                W(
                    "unknown_output_format",
                    f"Unknown output_format {output_format!r} — falling back to audio_only.",
                    "warning",
                )
            )

        log.info(
            "audiobook.preflight",
            warning_count=len(warnings),
            errors=[w.code for w in warnings if w.severity == "error"],
            warnings=[w.code for w in warnings if w.severity == "warning"],
            info=[w.code for w in warnings if w.severity == "info"],
        )
        return warnings

    # ══════════════════════════════════════════════════════════════════════
    # Main generation entry point
    # ══════════════════════════════════════════════════════════════════════

    async def _finalize_generate_result(
        self,
        *,
        audiobook_id: UUID,
        audio_rel_path: str,
        video_rel_path: str | None,
        mp3_rel_path: str | None,
        captions_ass_rel: str | None,
        captions_srt_rel: str | None,
        duration: float,
        file_size: int,
        chapters: list[dict[str, Any]],
        all_chunks: list[AudioChunk],
    ) -> dict[str, Any]:
        """Final 100% progress broadcast + result-dict assembly.

        Builds the dict the worker uses to update the DB and the route
        uses to render the response. The ``_chunk_paths`` key is
        intentionally prefixed with an underscore — it's an internal
        handoff for **deferred chunk cleanup AFTER a successful DB
        commit**. Cleaning up before commit would lose chunks on a
        retry; cleaning up here at the end of ``generate`` would lose
        them on a worker crash between this return and the commit.

        Pulled out of ``generate`` (F-CQ-01 step 13, the final phase).
        """
        await self._broadcast_progress(audiobook_id, "done", 100, "Complete!")

        log.info(
            "audiobook.generate.done",
            audiobook_id=str(audiobook_id),
            duration_seconds=duration,
            file_size_bytes=file_size,
            has_video=video_rel_path is not None,
            has_mp3=mp3_rel_path is not None,
            chapter_count=len(chapters),
        )

        return {
            "audio_rel_path": audio_rel_path,
            "video_rel_path": video_rel_path,
            "mp3_rel_path": mp3_rel_path,
            "captions_ass_rel_path": captions_ass_rel,
            "captions_srt_rel_path": captions_srt_rel,
            "duration_seconds": duration,
            "file_size_bytes": file_size,
            "chapters": chapters,
            "_chunk_paths": [c.path for c in all_chunks],
        }

    async def _run_video_phase(
        self,
        *,
        audiobook_id: UUID,
        abs_dir: Path,
        final_audio: Path,
        duration: float,
        chapters: list[dict[str, Any]],
        chapter_timings: list[ChapterTiming],
        chapter_image_paths: list[Path],
        captions_ass_path: Path | None,
        output_format: str,
        video_width: int,
        video_height: int,
        cover_image_path: str | None,
        background_image_path: str | None,
    ) -> str | None:
        """Assemble the final MP4 (chapter-aware Ken Burns OR single-image).

        Skipped entirely (returns ``None``) for ``audio_only`` output.

        For ``audio_image`` / ``audio_video``, two paths:

        - **Chapter-aware**: when one image per chapter is available
          (``len(chapter_image_paths) == len(chapters)``), uses
          ``_create_chapter_aware_video`` with Ken Burns crossfades.
        - **Single-image fallback**: resolves cover_image_path or
          background_image_path under storage. If neither resolves to
          an existing file (or sanitisation fails), generates a
          synthetic title card from the first chapter's title.

        DAG ``mp4_export`` flips ``in_progress`` → ``done`` regardless
        of which path runs (any unhandled exception will propagate up
        to the caller, which is intentional — a broken video phase is
        the only legitimately fatal phase, since the audio + MP3 are
        already on disk for the operator to recover).

        Returns the storage-relative MP4 path on success, ``None`` for
        audio-only output.

        Pulled out of ``generate`` (F-CQ-01 step 12).
        """
        await self._check_cancelled(audiobook_id)
        await self._broadcast_progress(audiobook_id, "assembly", 90, "Assembling video...")

        if output_format not in ("audio_image", "audio_video"):
            return None

        await self._dag_global("mp4_export", "in_progress")
        video_path = abs_dir / "audiobook.mp4"

        # Check if we have chapter images for chapter-aware assembly
        if chapter_image_paths and len(chapter_image_paths) == len(chapters):
            # Chapter-aware video with Ken Burns transitions
            await self._create_chapter_aware_video(
                audio_path=final_audio,
                output_path=video_path,
                chapter_timings=chapter_timings,
                chapter_image_paths=chapter_image_paths,
                captions_path=captions_ass_path,
                width=video_width,
                height=video_height,
                background_music_path=None,  # already mixed into audio
                audiobook_id=audiobook_id,
            )
            log.info(
                "audiobook.generate.chapter_video_done",
                audiobook_id=str(audiobook_id),
            )
        else:
            # Fallback: single-image video (existing behaviour)
            resolved_cover = self._resolve_video_cover(
                cover_image_path=cover_image_path,
                background_image_path=background_image_path,
            )
            if not resolved_cover or not Path(resolved_cover).exists():
                title_for_card = chapters[0]["title"] if chapters else "Audiobook"
                resolved_cover = str(
                    await self._generate_title_card(
                        abs_dir,
                        title_for_card,
                        width=video_width,
                        height=video_height,
                    )
                )
            await self._create_audiobook_video(
                audio_path=final_audio,
                output_path=video_path,
                cover_image_path=resolved_cover,
                duration=duration,
                captions_path=captions_ass_path,
                with_waveform=output_format == "audio_video",
                width=video_width,
                height=video_height,
                audiobook_id=audiobook_id,
            )
            log.info(
                "audiobook.generate.video_done",
                audiobook_id=str(audiobook_id),
            )
        await self._dag_global("mp4_export", "done")
        return f"audiobooks/{audiobook_id}/audiobook.mp4"

    def _resolve_video_cover(
        self,
        *,
        cover_image_path: str | None,
        background_image_path: str | None,
    ) -> str | None:
        """Resolve the user-supplied cover/background image to an
        absolute path under storage.

        Tries ``cover_image_path`` first, then falls back to
        ``background_image_path``. Sanitisation failures (path
        traversal, outside storage root) are logged at WARNING and
        treated as "no cover supplied" — the caller falls through to
        the synthetic title card generator.

        Returns ``None`` when neither input resolves cleanly. The
        caller still needs to verify the resolved path actually
        exists on disk.
        """
        resolved_cover: str | None = None
        if cover_image_path:
            try:
                resolved_cover = str(self.storage.resolve_path(cover_image_path))
            except Exception:
                # User-supplied path failed sanitisation or is
                # outside the storage root — log so they see why
                # the auto-generated title card replaced their art.
                log.warning(
                    "audiobook.cover_image_resolve_failed",
                    path=cover_image_path,
                    exc_info=True,
                )
        if not resolved_cover and background_image_path:
            try:
                resolved_cover = str(self.storage.resolve_path(background_image_path))
            except Exception:
                log.warning(
                    "audiobook.background_image_resolve_failed",
                    path=background_image_path,
                    exc_info=True,
                )
        return resolved_cover

    async def _run_mp3_export_phase(
        self,
        *,
        audiobook_id: UUID,
        final_audio: Path,
        chapters: list[dict[str, Any]],
        title: str,
        cover_image_path: str | None,
    ) -> str | None:
        """Convert WAV → MP3 with ID3 tags + CHAP frames.

        Two nested non-fatal blocks:

        - **Outer (mp3_export)**: ffmpeg WAV→MP3 conversion. Failure
          flips DAG ``mp3_export`` → failed and returns ``None`` (the
          caller's ``mp3_rel_path`` stays None and the audiobook ships
          with WAV only).
        - **Inner (id3_tags)**: write ID3 + CHAP frames using mutagen.
          Failure flips DAG ``id3_tags`` → failed but does NOT abort
          the export (the MP3 file is on disk and playable; only the
          metadata is missing).

        The LAME priming offset is computed from the WAV vs MP3
        duration delta and applied to the RenderPlan's chapter
        markers via ``apply_priming_offset``. This keeps CHAP frames
        within ±5 ms of audible chapter boundaries instead of ±50 ms.

        Returns the storage-relative MP3 path on success, or ``None``
        when the conversion failed.

        Pulled out of ``generate`` (F-CQ-01 step 11).
        """
        mp3_rel_path: str | None = None
        try:
            await self._dag_global("mp3_export", "in_progress")
            await self._convert_to_mp3(final_audio)
            mp3_rel_path = f"audiobooks/{audiobook_id}/audiobook.mp3"
            await self._dag_global("mp3_export", "done")
            log.info(
                "audiobook.generate.mp3_done",
                audiobook_id=str(audiobook_id),
            )

            # Best-effort ID3 + chapters. Failing here should not fail
            # the whole generation - the MP3 itself is already on disk
            # and playable. Distribution platforms (Audible, Apple Books,
            # Google Play Books) use these tags to show titles, cover
            # art, and chapter navigation.
            try:
                await self._dag_global("id3_tags", "in_progress")
                mp3_abs = final_audio.with_suffix(".mp3")
                cover_abs: Path | None = None
                if cover_image_path:
                    maybe_cover = self.storage.resolve_path(cover_image_path)
                    if maybe_cover.exists():
                        cover_abs = maybe_cover

                # Delegation: LAME priming offset computation + ID3
                # tagging lives in metadata._apply_lame_priming_and_tag.
                await _apply_lame_priming_and_tag(
                    final_audio=final_audio,
                    mp3_abs=mp3_abs,
                    ffmpeg=self.ffmpeg,
                    render_plan=self._render_plan,
                    title=title,
                    chapters=chapters,
                    cover_abs=cover_abs,
                    audiobook_id=audiobook_id,
                )
                await self._dag_global("id3_tags", "done")
            except Exception as id3_exc:
                log.warning(
                    "audiobook.generate.id3_failed",
                    audiobook_id=str(audiobook_id),
                    error=str(id3_exc),
                )
                await self._dag_global("id3_tags", "failed")
        except Exception as exc:
            log.warning(
                "audiobook.generate.mp3_failed",
                audiobook_id=str(audiobook_id),
                error=str(exc),
            )
            await self._dag_global("mp3_export", "failed")
        return mp3_rel_path

    async def _run_captions_phase(
        self,
        *,
        audiobook_id: UUID,
        abs_dir: Path,
        final_audio: Path,
        caption_style_preset: str | None,
        video_width: int,
        video_height: int,
    ) -> tuple[Path | None, str | None, str | None]:
        """Delegation shim — see ``captions.run_captions_phase``."""
        return await _cap_run_captions_phase(
            audiobook_id=audiobook_id,
            abs_dir=abs_dir,
            final_audio=final_audio,
            caption_style_preset=caption_style_preset,
            video_width=video_width,
            video_height=video_height,
            check_cancelled_fn=self._check_cancelled,
            broadcast_progress_fn=self._broadcast_progress,
            dag_global_fn=self._dag_global,
        )

    async def _run_master_mix_phase(
        self,
        *,
        audiobook_id: UUID,
        final_audio: Path,
    ) -> None:
        """Apply master loudnorm to ``final_audio``.

        Single audible-loudness pass. Runs AFTER music mixing so it
        integrates over the actual final content, and BEFORE captions
        ASR + MP3 export so both consume the already-mastered WAV.

        Failures are non-fatal (warning is logged inside
        ``_apply_master_loudnorm``); the un-mastered audiobook is still
        produced — the user gets working output even when the loudnorm
        ffmpeg pass blows up. Cancellation is honoured immediately
        before the master pass.

        Pulled out of ``generate`` (F-CQ-01 step 9).
        """
        await self._check_cancelled(audiobook_id)
        await self._dag_global("master_mix", "in_progress")
        await self._apply_master_loudnorm(final_audio)
        await self._dag_global("master_mix", "done")

    async def _run_music_phase(
        self,
        *,
        chapters: list[dict[str, Any]],
        abs_dir: Path,
        audiobook_id: UUID,
        final_audio: Path,
        chapter_timings: list[ChapterTiming],
        duration: float,
        file_size: int,
        music_enabled: bool,
        music_mood: str | None,
        music_volume_db: float,
        per_chapter_music: bool,
    ) -> int:
        """Mix per-chapter or global background music onto ``final_audio``.

        Skipped when music is disabled OR no music_mood was supplied
        AND per_chapter_music is False.

        Per-chapter music takes precedence when ``per_chapter_music``
        is True AND chapter_timings exist (without timings the
        per-chapter crossfade can't be placed). Otherwise falls back to
        the global ``_add_music`` path.

        On a successful mix, the output WAV swaps into ``final_audio``
        via the safe-rename pattern (backup → rename mixed → drop
        backup; on failure → restore backup, re-raise). Returns the
        post-swap file_size, or the original file_size when no mix
        ran.

        On any failure, every chapter's DAG ``music`` is flipped to
        ``failed`` and the exception is swallowed — the audiobook
        still completes with the un-music-mixed audio.

        Pulled out of ``generate`` (F-CQ-01 step 8). The two-branch
        backup-rename pattern is collapsed into ``_swap_in_mixed_audio``.
        """
        if not (music_enabled and (music_mood or per_chapter_music)):
            return file_size

        await self._check_cancelled(audiobook_id)
        await self._broadcast_progress(audiobook_id, "music", 70, "Adding background music...")
        for ch_idx in range(len(chapters)):
            await self._dag_chapter(ch_idx, "music", "in_progress")
        try:
            music_output = abs_dir / "audiobook_with_music.wav"
            if per_chapter_music and chapter_timings:
                # Per-chapter music with crossfades
                mixed_path = await self._add_chapter_music(
                    audio_path=final_audio,
                    output_path=music_output,
                    chapter_timings=chapter_timings,
                    chapters=chapters,
                    global_mood=music_mood or "calm",
                    volume_db=music_volume_db,
                    audiobook_id=audiobook_id,
                )
                file_size = self._swap_in_mixed_audio(
                    final_audio=final_audio,
                    mixed_path=mixed_path,
                    file_size=file_size,
                    log_event="audiobook.generate.chapter_music_mixed",
                    audiobook_id=audiobook_id,
                )
            elif music_mood:
                # Global music (existing behaviour)
                mixed_path = await self._add_music(
                    audio_path=final_audio,
                    output_path=music_output,
                    mood=music_mood,
                    volume_db=music_volume_db,
                    duration=duration,
                )
                file_size = self._swap_in_mixed_audio(
                    final_audio=final_audio,
                    mixed_path=mixed_path,
                    file_size=file_size,
                    log_event="audiobook.generate.music_mixed",
                    audiobook_id=audiobook_id,
                )
            for ch_idx in range(len(chapters)):
                await self._dag_chapter(ch_idx, "music", "done")
        except Exception as exc:
            log.warning(
                "audiobook.generate.music_failed",
                audiobook_id=str(audiobook_id),
                error=str(exc),
            )
            for ch_idx in range(len(chapters)):
                await self._dag_chapter(ch_idx, "music", "failed")
        return file_size

    @staticmethod
    def _swap_in_mixed_audio(
        *,
        final_audio: Path,
        mixed_path: Path,
        file_size: int,
        log_event: str,
        audiobook_id: UUID,
    ) -> int:
        """Atomically swap ``mixed_path`` into ``final_audio``.

        Backup the existing WAV, rename the mixed output over it, drop
        the backup. On failure, restore the backup and re-raise so
        callers' ``except`` blocks see the original error.

        Returns the post-swap ``file_size`` (or the original if the
        mixer returned the same path → no swap needed).
        """
        if mixed_path == final_audio:
            return file_size
        backup = final_audio.with_suffix(".wav.bak")
        final_audio.rename(backup)
        try:
            mixed_path.rename(final_audio)
            backup.unlink(missing_ok=True)
        except Exception:
            backup.rename(final_audio)
            raise
        new_size = final_audio.stat().st_size
        log.info(log_event, audiobook_id=str(audiobook_id))
        return new_size

    async def _run_image_phase(
        self,
        *,
        chapters: list[dict[str, Any]],
        abs_dir: Path,
        audiobook_id: UUID,
        output_format: str,
        image_generation_enabled: bool,
        video_width: int,
        video_height: int,
    ) -> list[Path]:
        """Generate one image per chapter via ComfyUI when enabled.

        Skipped entirely (returns ``[]``) when image generation is
        disabled or the output format has no place to display an image
        (``audio_only``). Otherwise:

        - Broadcasts ``images`` stage at 55% and flips every chapter's
          DAG ``image`` to ``in_progress``.
        - Calls ``_generate_chapter_images`` to render the actual PNGs.
        - On success: writes ``image_path`` into each chapter dict and
          flips DAG to ``done``.
        - On any failure: catches, logs a warning, flips every chapter's
          DAG ``image`` to ``failed`` (the audiobook still completes —
          missing chapter images are non-fatal).

        Pulled out of ``generate`` (F-CQ-01 step 7).
        """
        chapter_image_paths: list[Path] = []
        if not (image_generation_enabled and output_format in ("audio_image", "audio_video")):
            return chapter_image_paths

        await self._broadcast_progress(audiobook_id, "images", 55, "Generating chapter images...")
        for ch_idx in range(len(chapters)):
            await self._dag_chapter(ch_idx, "image", "in_progress")
        try:
            chapter_image_paths = await self._generate_chapter_images(
                chapters=chapters,
                output_dir=abs_dir,
                audiobook_id=audiobook_id,
                video_width=video_width,
                video_height=video_height,
            )
            # Store image paths in chapter metadata
            for i, img_path in enumerate(chapter_image_paths):
                if i < len(chapters):
                    chapters[i]["image_path"] = f"audiobooks/{audiobook_id}/images/ch{i:03d}.png"
                await self._dag_chapter(i, "image", "done")
            log.info(
                "audiobook.generate.images_done",
                audiobook_id=str(audiobook_id),
                image_count=len(chapter_image_paths),
            )
        except Exception as exc:
            log.warning(
                "audiobook.generate.images_failed",
                audiobook_id=str(audiobook_id),
                error=str(exc),
                exc_info=True,
            )
            for ch_idx in range(len(chapters)):
                await self._dag_chapter(ch_idx, "image", "failed")
        return chapter_image_paths

    async def _run_concat_phase(
        self,
        *,
        all_chunks: list[AudioChunk],
        abs_dir: Path,
        audiobook_id: UUID,
        chapters: list[dict[str, Any]],
    ) -> tuple[Path, list[ChapterTiming]]:
        """Concatenate per-chapter chunks, build the RenderPlan, and
        optionally trim leading silence.

        Returns:
            ``(final_audio_path, chapter_timings)``. The chapters list
            is mutated in-place — each chapter dict gets ``start_seconds``,
            ``end_seconds``, ``duration_seconds`` populated from the
            timings (rounded to 3 decimal places).

        Side effects:
            - Cancellation check at the top of the phase.
            - Progress broadcast at 50% (mixing).
            - DAG ``concat`` transitions: ``in_progress`` → ``done``.
            - ``self._render_plan`` populated; persistence callback fired.
            - When ``self._settings.trim_leading_trailing_silence`` is True,
              shifts every chapter timing by the trimmed offset.

        Pulled out of ``generate`` (F-CQ-01 step 6).
        """
        # 3. Concatenate all chunks with context-aware silence gaps
        await self._check_cancelled(audiobook_id)
        await self._broadcast_progress(audiobook_id, "mixing", 50, "Concatenating audio...")
        final_audio = abs_dir / "audiobook.wav"
        await self._dag_global("concat", "in_progress")
        chapter_timings = await self._concatenate_with_context(all_chunks, final_audio)
        await self._dag_global("concat", "done")

        # Task 13: build the RenderPlan from concat outputs. Inline-only
        # AudioChunk list (overlay SFX excluded — they don't appear on
        # the inline timeline). Chunk durations probed via the FFmpeg
        # service so each event carries a real ``duration_ms`` value.
        # The plan is persisted as an inspectable artifact and
        # consumed by ``list_clips`` + the ID3 CHAP writer; future
        # tasks will rewire concat / captions / track-mix to drive
        # off it directly.
        inline_only = [c for c in all_chunks if not self._is_overlay_sfx(c)]
        chunk_durations: dict[str, float] = {}
        for c in inline_only:
            try:
                chunk_durations[c.path.stem] = await self.ffmpeg.get_duration(c.path)
            except Exception:
                chunk_durations[c.path.stem] = 0.0
        render_plan: RenderPlan = RenderPlan.from_pipeline_outputs(
            audiobook_id=audiobook_id,
            inline_chunks=inline_only,
            chapter_timings=chapter_timings,
            chapters=chapters,
            chunk_durations_seconds=chunk_durations,
        )
        self._render_plan = render_plan
        await self._persist_render_plan(render_plan)

        # 3b. Optional leading/trailing silence trim — runs BEFORE captions,
        # MP3 export, and timing persistence so CHAP frames + ASS captions
        # stay locked to audible boundaries within ±50 ms. Off by default;
        # Task 9 routes the toggle through ``self._settings``.
        if self._settings.trim_leading_trailing_silence:
            leading_offset = await self._trim_silence_in_place(final_audio)
            if leading_offset > 0:
                chapter_timings = self._shift_chapter_timings(chapter_timings, leading_offset)

        # Store timing metadata in chapters
        for timing in chapter_timings:
            if timing.chapter_index < len(chapters):
                chapters[timing.chapter_index]["start_seconds"] = round(timing.start_seconds, 3)
                chapters[timing.chapter_index]["end_seconds"] = round(timing.end_seconds, 3)
                chapters[timing.chapter_index]["duration_seconds"] = round(
                    timing.duration_seconds, 3
                )

        return final_audio, chapter_timings

    async def _run_tts_phase(
        self,
        *,
        chapters: list[dict[str, Any]],
        abs_dir: Path,
        audiobook_id: UUID,
        voice_profile: VoiceProfile,
        voice_casting: dict[str, str] | None,
        speed: float,
        pitch: float,
    ) -> list[AudioChunk]:
        """Render TTS for every chapter and return the concat-input list.

        Honours cancellation between chapters, broadcasts progress
        (5%-50% range — TTS is the bulk of the wall-clock for most
        audiobooks), and routes through ``_generate_multi_voice`` when
        either ``voice_casting`` is non-empty AND there are multiple
        speaker blocks, OR the chapter contains ``[SFX:]`` blocks
        (sequential order matters in either case). Single-speaker
        chapters take the simpler ``_generate_single_voice`` path.

        Pulled out of ``generate`` (F-CQ-01 step 5) — by far the
        biggest single phase, ~75 lines lifted.
        """
        all_chunks: list[AudioChunk] = []
        total_chapters = len(chapters)
        for ch_idx, chapter in enumerate(chapters):
            # Honour the user's Cancel button between chapters. The
            # in-flight TTS / ComfyUI calls aren't interruptible, but
            # we won't queue another chapter once the flag is set.
            await self._check_cancelled(audiobook_id)

            chapter_text = chapter["text"]
            voice_blocks = self._parse_voice_blocks(chapter_text)

            # Task 11: skip TTS work entirely if this chapter is
            # already ``done`` in the DAG. The chunk-cache fast path
            # (Task 1) is the per-chunk equivalent — they coexist.
            tts_already_done = self._dag_chapter_done(ch_idx, "tts")

            pct = 5 + int((ch_idx / total_chapters) * 45)
            await self._broadcast_progress(
                audiobook_id,
                "tts",
                pct,
                f"Generating speech for chapter {ch_idx + 1}/{total_chapters}...",
            )

            await self._dag_chapter(ch_idx, "tts", "in_progress")

            has_sfx = any(b.get("kind") == "sfx" for b in voice_blocks)
            multi_voice_active = bool(voice_casting) and len(voice_blocks) > 1
            if multi_voice_active or has_sfx:
                # SFX blocks must preserve sequential order with voice
                # blocks, so route through the multi-voice path even
                # when only one speaker exists. The voice-casting map
                # may be empty in that case — _generate_multi_voice
                # falls back to ``default_voice_profile`` per block.
                log.info(
                    "audiobook.generate.multi_voice",
                    audiobook_id=str(audiobook_id),
                    chapter=ch_idx,
                    speakers=[b.get("speaker", "SFX") for b in voice_blocks],
                    sfx_count=sum(1 for b in voice_blocks if b.get("kind") == "sfx"),
                )
                chunks = await self._generate_multi_voice(
                    blocks=voice_blocks,
                    voice_casting=voice_casting or {},
                    default_voice_profile=voice_profile,
                    output_dir=abs_dir,
                    chapter_index=ch_idx,
                    speed=speed,
                    pitch=pitch,
                )
            else:
                plain_text = chapter_text
                if voice_blocks and len(voice_blocks) == 1:
                    plain_text = voice_blocks[0]["text"]

                chunks = await self._generate_single_voice(
                    text=plain_text,
                    voice_profile=voice_profile,
                    output_dir=abs_dir,
                    chapter_index=ch_idx,
                    speed=speed,
                    pitch=pitch,
                )

            all_chunks.extend(chunks)
            await self._dag_chapter(ch_idx, "tts", "done")
            log.debug(
                "audiobook.generate.chapter_done",
                audiobook_id=str(audiobook_id),
                chapter_index=ch_idx,
                chunks=len(chunks),
                tts_already_done=tts_already_done,
            )
        return all_chunks

    async def _reshape_dag_for_chapters(
        self,
        *,
        chapters: list[dict[str, Any]],
        image_generation_enabled: bool,
        output_format: str,
        music_enabled: bool,
        chapter_moods: list[str] | None,
    ) -> None:
        """Reshape the persisted DAG to fit the parsed chapter count
        and mark inapplicable stages as ``skipped`` so the progress
        percentage stays honest.

        Also applies ``chapter_moods[i]`` to each chapter's
        ``music_mood`` slot when supplied (the per-chapter override
        for the global ``music_mood`` arg).

        Pulled out of ``generate`` (F-CQ-01 step 4) so the
        orchestrator stays focused on phase sequencing.
        """
        # Task 11: reshape the DAG to fit the parsed chapter count.
        # Stages that don't apply for this audiobook get marked
        # ``skipped`` up front so the progress percentage is honest.
        self._job_state = _js._normalise(self._job_state, len(chapters))
        if not image_generation_enabled or output_format == "audio_only":
            for ch_key in list(self._job_state["chapters"].keys()):
                self._job_state["chapters"][ch_key]["image"] = "skipped"
        if not music_enabled:
            for ch_key in list(self._job_state["chapters"].keys()):
                self._job_state["chapters"][ch_key]["music"] = "skipped"
        if output_format == "audio_only":
            self._job_state["mp4_export"] = "skipped"
        await self._persist_dag()

        # Apply chapter_moods to chapter metadata
        if chapter_moods:
            for i, chapter in enumerate(chapters):
                if i < len(chapter_moods) and chapter_moods[i]:
                    chapter["music_mood"] = chapter_moods[i]

    @staticmethod
    def _resolve_output_format(output_format: str, generate_video: bool) -> str:
        """Resolve the legacy ``generate_video`` flag.

        Older callers passed ``generate_video=True`` separately from
        ``output_format``. The newer contract is a single
        ``output_format`` value with ``audio_video`` covering the
        old "audio + video" case. This helper bridges the two without
        breaking either form.
        """
        if generate_video and output_format == "audio_only":
            return "audio_video"
        return output_format

    @staticmethod
    def _resolve_video_dims(video_orientation: str) -> tuple[int, int]:
        """Map ``video_orientation`` to ``(width, height)``.

        ``"vertical"`` → 1080 × 1920 (Shorts/TikTok). Anything else
        (including ``"landscape"`` and any unexpected value) →
        1920 × 1080. The default-to-landscape fallback prevents a
        typoed orientation from silently producing a 0×0 video.
        """
        if video_orientation == "vertical":
            return 1080, 1920
        return 1920, 1080

    async def _initialize_call_state(
        self,
        *,
        audiobook_id: UUID,
        title: str,
        initial_job_state: dict[str, Any] | None,
        persist_job_state_cb: Any | None,
        persist_render_plan_cb: Any | None,
    ) -> None:
        """Wire up per-call instance state at the top of ``generate``.

        Side effects:
        - Binds ``audiobook_id`` + ``title`` into the structlog
          contextvars so every helper's log line carries them.
        - Refreshes the ComfyUI server pool from the DB so retries
          always see current servers.
        - Stashes ``audiobook_id`` on the instance for cancellation
          polling inside ``asyncio.gather``'d coroutines.
        - Builds a single ``CancelChecker`` so the 1-second debounce
          survives across helpers rather than resetting per-helper.
        - Hydrates ``self._job_state`` from the worker's persisted
          blob, plus the two persistence callbacks.

        Pulled out of ``generate`` (F-CQ-01 step 2) so the orchestrator
        stays focused on phase sequencing.
        """
        structlog.contextvars.bind_contextvars(
            audiobook_id=str(audiobook_id),
            title=title,
        )

        # Refresh ComfyUI pool from DB so retries always use current servers
        if self.comfyui_service and self.db_session:
            try:
                await self.comfyui_service._pool.sync_from_db(self.db_session)
            except Exception:
                log.warning("audiobook.comfyui_pool_refresh_failed", exc_info=True)

        # Stash audiobook_id on the instance so cancellation polling
        # (Task 4) inside per-chunk gather'd coroutines can reach it
        # without changing helper signatures.
        self._current_audiobook_id = audiobook_id

        # Task 10: debounced cancel poller. Built once per generate
        # call so the 1-second debounce survives across all helpers
        # rather than resetting per-helper.
        self._cancel_checker = CancelChecker(self.redis, audiobook_id)

        # Task 11: per-stage DAG. Hydrated from the worker's persisted
        # blob (``audiobook.job_state``); we reshape to fit the actual
        # parsed chapter count once parsing has run. The persistence
        # callback is invoked after every state transition so a worker
        # crash leaves the DAG at the last successful step.
        self._job_state = initial_job_state or {}
        self._persist_job_state_cb = persist_job_state_cb
        # Task 13: parallel callback for the render_plan_json column.
        self._persist_render_plan_cb = persist_render_plan_cb

    def _apply_settings_and_mix(
        self,
        *,
        audiobook_settings: AudiobookSettings | None,
        ducking_preset: str | None,
        track_mix: dict[str, Any] | None,
        music_volume_db: float,
    ) -> float:
        """Resolve ``audiobook_settings`` + unpack ``track_mix``.

        Mutates the per-call instance state (``self._settings``,
        ``self._ducking_preset``, ``self._track_mix_full``, the six
        gain/mute fields) and returns the (possibly user-gain-adjusted)
        ``music_volume_db`` so the caller can keep using a local var.

        Pulled out of ``generate`` (F-CQ-01) so the orchestrator stays
        focused on phase sequencing rather than instance-state setup.
        """
        # Task 9: ``audiobook_settings`` is the single source of truth.
        # If the caller supplies a settings object, every downstream
        # consumer reads from it; otherwise we fall back to the
        # narrative-default ``AudiobookSettings()`` so existing call
        # sites behave exactly as before. The legacy ``ducking_preset``
        # kwarg from Task 6 still works — when settings is None we
        # build a settings instance carrying that preset.
        if audiobook_settings is None:
            base = AudiobookSettings()
            if ducking_preset is not None:
                base = base.model_copy(update={"ducking_preset": ducking_preset})
            self._settings = base
        else:
            self._settings = audiobook_settings
        # Backwards-compat: the Task-6 dict-shaped preset still feeds
        # ``_build_music_mix_graph``. Sync from settings.
        self._ducking_preset = _resolve_ducking_preset(self._settings.ducking_preset)

        # Stash track_mix on the instance so the mix filter chains
        # (in ``_add_music`` / ``_add_chapter_music``) can read user
        # gain offsets without threading them through every helper.
        # Default = passthrough.
        mix = track_mix or {}
        # Stash the full mix dict so the concat path can read
        # ``track_mix.clips`` per-clip overrides without changing
        # signatures down the call stack.
        self._track_mix_full = mix
        self._voice_gain_db = float(mix.get("voice_db", 0.0) or 0.0)
        self._music_gain_db = float(mix.get("music_db", 0.0) or 0.0)
        self._sfx_gain_db = float(mix.get("sfx_db", 0.0) or 0.0)
        self._voice_muted = bool(mix.get("voice_mute", False))
        self._music_muted = bool(mix.get("music_mute", False))
        self._sfx_muted = bool(mix.get("sfx_mute", False))
        # Music user gain stacks on top of the per-call ``volume_db``
        # arg (which already represents the music bed level), so a
        # +3 dB user gain on top of -14 dB call value = -11 dB.
        if self._music_gain_db:
            music_volume_db = music_volume_db + self._music_gain_db
        return music_volume_db

    async def generate(
        self,
        audiobook_id: UUID,
        text: str,
        voice_profile: VoiceProfile,
        *,
        title: str = "Audiobook",
        generate_video: bool = False,
        background_image_path: str | None = None,
        output_format: str = "audio_only",
        cover_image_path: str | None = None,
        voice_casting: dict[str, str] | None = None,
        music_enabled: bool = False,
        music_mood: str | None = None,
        music_volume_db: float = -14.0,
        speed: float = 1.0,
        pitch: float = 1.0,
        video_orientation: str = "landscape",
        caption_style_preset: str | None = None,
        image_generation_enabled: bool = False,
        per_chapter_music: bool = False,
        chapter_moods: list[str] | None = None,
        track_mix: dict[str, Any] | None = None,
        ducking_preset: str | None = None,
        audiobook_settings: AudiobookSettings | None = None,
        initial_job_state: dict[str, Any] | None = None,
        persist_job_state_cb: Any | None = None,
        persist_render_plan_cb: Any | None = None,
    ) -> dict[str, Any]:
        """Generate an audiobook from text.

        Steps:
        1. Parse chapters from text (## headers or --- separators).
        2. Parse voice blocks ([Speaker] tags) for multi-voice.
        3. Generate TTS for each block with the appropriate voice.
        4. Concatenate chunks with context-aware silence gaps.
        5. Optionally generate per-chapter images via ComfyUI.
        6. Optionally add background music (global or per-chapter).
        7. Generate captions, convert to MP3.
        8. Create video (chapter-aware with Ken Burns or single-image fallback).
        9. Clean up intermediate files.

        Returns
        -------
        dict with keys: audio_rel_path, video_rel_path, mp3_rel_path,
                        duration_seconds, file_size_bytes, chapters
        """
        # Bind audiobook_id at the call boundary so every log line
        # produced by helpers further down — including module-level
        # `log = structlog.get_logger(__name__)` callers — carries the
        # id without each helper having to take or rebind it. Cleared
        # in the matching finally so other tasks running on this loop
        # don't inherit the binding.
        # F-CQ-01 step 2: per-call instance state init (log binding,
        # ComfyUI pool refresh, cancel checker, DAG state) extracted
        # into ``_initialize_call_state`` so this orchestrator stays
        # focused on phase sequencing.
        await self._initialize_call_state(
            audiobook_id=audiobook_id,
            title=title,
            initial_job_state=initial_job_state,
            persist_job_state_cb=persist_job_state_cb,
            persist_render_plan_cb=persist_render_plan_cb,
        )

        # F-CQ-01 step 1: settings + track_mix unpacking extracted into
        # ``_apply_settings_and_mix`` so this orchestrator stays focused
        # on phase sequencing rather than per-instance state setup.
        music_volume_db = self._apply_settings_and_mix(
            audiobook_settings=audiobook_settings,
            ducking_preset=ducking_preset,
            track_mix=track_mix,
            music_volume_db=music_volume_db,
        )

        # F-CQ-01 step 3: pure resolution helpers — output_format
        # legacy compat + video dimensions from orientation.
        output_format = self._resolve_output_format(output_format, generate_video)
        video_width, video_height = self._resolve_video_dims(video_orientation)

        output_dir = Path(f"audiobooks/{audiobook_id}")
        abs_dir = self.storage.resolve_path(str(output_dir))
        abs_dir.mkdir(parents=True, exist_ok=True)

        # One-shot purge of pre-hash chunk filenames. Cheap on a clean
        # audiobook (single iterdir + zero unlinks); meaningful only on
        # the first generation after the upgrade to AUDIO_PIPELINE_VERSION
        # >= 2. See ``_purge_legacy_chunks``.
        await self._purge_legacy_chunks(abs_dir)

        log.info(
            "audiobook.generate.start",
            audiobook_id=str(audiobook_id),
            text_length=len(text),
            provider=voice_profile.provider,
            output_format=output_format,
            music_enabled=music_enabled,
            has_voice_casting=voice_casting is not None,
            video_orientation=video_orientation,
            caption_style_preset=caption_style_preset,
            image_generation_enabled=image_generation_enabled,
            per_chapter_music=per_chapter_music,
        )

        await self._broadcast_progress(audiobook_id, "parsing", 0, "Parsing chapters...")

        # 1. Parse chapters
        chapters = self._parse_chapters(text)
        log.info(
            "audiobook.generate.chapters_parsed",
            audiobook_id=str(audiobook_id),
            chapter_count=len(chapters),
            chapter_titles=[ch["title"] for ch in chapters],
        )

        # F-CQ-01 step 4: DAG reshape + chapter_moods application
        # extracted into ``_reshape_dag_for_chapters``.
        await self._reshape_dag_for_chapters(
            chapters=chapters,
            image_generation_enabled=image_generation_enabled,
            output_format=output_format,
            music_enabled=music_enabled,
            chapter_moods=chapter_moods,
        )

        # F-CQ-01 step 5: per-chapter TTS loop extracted into
        # ``_run_tts_phase`` so this orchestrator stays focused on
        # phase sequencing.
        all_chunks = await self._run_tts_phase(
            chapters=chapters,
            abs_dir=abs_dir,
            audiobook_id=audiobook_id,
            voice_profile=voice_profile,
            voice_casting=voice_casting,
            speed=speed,
            pitch=pitch,
        )

        # F-CQ-01 step 6: concat + RenderPlan + silence trim + chapter
        # timing storage extracted into ``_run_concat_phase``.
        final_audio, chapter_timings = await self._run_concat_phase(
            all_chunks=all_chunks,
            abs_dir=abs_dir,
            audiobook_id=audiobook_id,
            chapters=chapters,
        )

        # 4. Get duration and file size
        duration = await self.ffmpeg.get_duration(final_audio)
        file_size = final_audio.stat().st_size

        # F-CQ-01 step 7: per-chapter image generation extracted
        # into ``_run_image_phase``.
        chapter_image_paths = await self._run_image_phase(
            chapters=chapters,
            abs_dir=abs_dir,
            audiobook_id=audiobook_id,
            output_format=output_format,
            image_generation_enabled=image_generation_enabled,
            video_width=video_width,
            video_height=video_height,
        )

        # F-CQ-01 step 8: music mixing (per-chapter or global) extracted
        # into ``_run_music_phase``.
        file_size = await self._run_music_phase(
            chapters=chapters,
            abs_dir=abs_dir,
            audiobook_id=audiobook_id,
            final_audio=final_audio,
            chapter_timings=chapter_timings,
            duration=duration,
            file_size=file_size,
            music_enabled=music_enabled,
            music_mood=music_mood,
            music_volume_db=music_volume_db,
            per_chapter_music=per_chapter_music,
        )

        # F-CQ-01 step 9: master loudnorm phase extracted into
        # ``_run_master_mix_phase``.
        await self._run_master_mix_phase(
            audiobook_id=audiobook_id,
            final_audio=final_audio,
        )

        # F-CQ-01 step 10: captions phase extracted into
        # ``_run_captions_phase``.
        captions_ass_path, captions_ass_rel, captions_srt_rel = await self._run_captions_phase(
            audiobook_id=audiobook_id,
            abs_dir=abs_dir,
            final_audio=final_audio,
            caption_style_preset=caption_style_preset,
            video_width=video_width,
            video_height=video_height,
        )

        audio_rel_path = f"audiobooks/{audiobook_id}/audiobook.wav"
        video_rel_path: str | None = None

        # F-CQ-01 step 11: MP3 export + ID3 + CHAP frames + LAME
        # priming offset extracted into ``_run_mp3_export_phase``.
        mp3_rel_path = await self._run_mp3_export_phase(
            audiobook_id=audiobook_id,
            final_audio=final_audio,
            chapters=chapters,
            title=title,
            cover_image_path=cover_image_path,
        )

        # F-CQ-01 step 12: video assembly phase (chapter-aware vs
        # single-image fallback) extracted into ``_run_video_phase``.
        video_rel_path = await self._run_video_phase(
            audiobook_id=audiobook_id,
            abs_dir=abs_dir,
            final_audio=final_audio,
            duration=duration,
            chapters=chapters,
            chapter_timings=chapter_timings,
            chapter_image_paths=chapter_image_paths,
            captions_ass_path=captions_ass_path,
            output_format=output_format,
            video_width=video_width,
            video_height=video_height,
            cover_image_path=cover_image_path,
            background_image_path=background_image_path,
        )

        # F-CQ-01 step 13: final 100%-progress broadcast + result-dict
        # assembly extracted into ``_finalize_generate_result``.
        return await self._finalize_generate_result(
            audiobook_id=audiobook_id,
            audio_rel_path=audio_rel_path,
            video_rel_path=video_rel_path,
            mp3_rel_path=mp3_rel_path,
            captions_ass_rel=captions_ass_rel,
            captions_srt_rel=captions_srt_rel,
            duration=duration,
            file_size=file_size,
            chapters=chapters,
            all_chunks=all_chunks,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Chapter parsing — delegated to chaptering.py
    # ══════════════════════════════════════════════════════════════════════

    # Class-level aliases keep ``AudiobookService._CHAPTER_PATTERN_*``,
    # ``AudiobookService._SCORE_THRESHOLD``, etc. working for any callers
    # that reached them through the class. The canonical definitions live
    # in ``chaptering.py``.
    _CHAPTER_PATTERN_MARKDOWN = _CHAPTER_PATTERN_MARKDOWN
    _CHAPTER_PATTERN_PROSE = _CHAPTER_PATTERN_PROSE
    _CHAPTER_PATTERN_ROMAN = _CHAPTER_PATTERN_ROMAN
    _CHAPTER_PATTERN_ALLCAPS = _CHAPTER_PATTERN_ALLCAPS
    _SCORE_THRESHOLD = _SCORE_THRESHOLD
    _MIN_SEGMENT_CHARS = _MIN_SEGMENT_CHARS

    _score_chapter_split = staticmethod(_score_chapter_split)
    _filter_markdown_matches = staticmethod(_filter_markdown_matches)
    _filter_allcaps_matches = staticmethod(_filter_allcaps_matches)

    def _parse_chapters(self, text: str) -> list[dict[str, Any]]:
        return _parse_chapters(text)

    # ══════════════════════════════════════════════════════════════════════
    # Voice block parsing — delegated to script_tags.py
    # ══════════════════════════════════════════════════════════════════════

    def _parse_voice_blocks(self, text: str) -> list[dict[str, Any]]:
        return _parse_voice_blocks(text)

    # ══════════════════════════════════════════════════════════════════════
    # TTS generation (returns AudioChunk list)
    # ══════════════════════════════════════════════════════════════════════

    async def _generate_silence(self, output_path: Path, duration: float = 0.5) -> None:
        """Delegation shim — see ``tts_render.generate_silence``."""
        await _tts_generate_silence(output_path, duration)

    async def _generate_single_voice(
        self,
        text: str,
        voice_profile: VoiceProfile,
        output_dir: Path,
        chapter_index: int,
        speed: float,
        pitch: float,
    ) -> list[AudioChunk]:
        """Generate TTS for a single voice, splitting text into chunks.

        Task 4: chunks render concurrently up to the per-provider cap
        from ``PROVIDER_CONCURRENCY``. Cache hits short-circuit before
        the semaphore so they don't burn a slot.
        """
        return await _tts_generate_single_voice(
            tts_service=self.tts,
            text=text,
            voice_profile=voice_profile,
            output_dir=output_dir,
            chapter_index=chapter_index,
            speed=speed,
            pitch=pitch,
            cancel_fn=self._cancel,
        )

    async def _generate_multi_voice(
        self,
        blocks: list[dict[str, str]],
        voice_casting: dict[str, str],
        default_voice_profile: VoiceProfile,
        output_dir: Path,
        chapter_index: int,
        speed: float,
        pitch: float,
    ) -> list[AudioChunk]:
        """Generate TTS for each speaker block with their assigned voice.

        Falls back to the default voice profile for speakers not in the
        casting map.
        """
        return await _tts_generate_multi_voice(
            tts_service=self.tts,
            blocks=blocks,
            voice_casting=voice_casting,
            default_voice_profile=default_voice_profile,
            output_dir=output_dir,
            chapter_index=chapter_index,
            speed=speed,
            pitch=pitch,
            cancel_fn=self._cancel,
            get_voice_profile_fn=self._get_voice_profile,
            generate_sfx_chunk_fn=self._generate_sfx_chunk,
        )

    async def _get_voice_profile(self, voice_profile_id: str) -> VoiceProfile | None:
        """Load a voice profile by ID from the database."""
        if self.db_session is None:
            log.warning(
                "audiobook.get_voice_profile.no_session",
                voice_profile_id=voice_profile_id,
            )
            return None

        try:
            import uuid as _uuid

            from drevalis.repositories.voice_profile import VoiceProfileRepository

            vp_repo = VoiceProfileRepository(self.db_session)
            parsed_id = _uuid.UUID(voice_profile_id)
            return await vp_repo.get_by_id(parsed_id)
        except Exception as exc:
            log.warning(
                "audiobook.get_voice_profile.failed",
                voice_profile_id=voice_profile_id,
                error=str(exc),
            )
            return None

    # ══════════════════════════════════════════════════════════════════════
    # Text splitting — delegated to chunking.py
    # ══════════════════════════════════════════════════════════════════════

    def _split_text(self, text: str, max_chars: int) -> list[str]:
        return _split_text(text, max_chars)

    _split_long_sentence = staticmethod(_split_long_sentence)
    _repair_bracket_splits = staticmethod(_repair_bracket_splits)

    # ══════════════════════════════════════════════════════════════════════
    # Context-aware audio concatenation
    # ══════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # Audio format probe (Task 7)
    # ══════════════════════════════════════════════════════════════════════
    #
    # Concat used to always re-encode to canonical 44.1 kHz stereo s16le.
    # That's safe but wasteful when every input chunk is already
    # uniform — Piper / Kokoro / Edge all land at 24 kHz mono after the
    # Task-3 ``_safety_filter_chunk`` pass, so the demuxer's stream-copy
    # path produces the same audio in a fraction of the I/O cost.

    @staticmethod
    @staticmethod
    async def _probe_audio_format(path: Path) -> tuple[int, int, str, str] | None:
        """Delegation shim — see ``concat_executor.probe_audio_format``."""
        return await _concat_probe_audio_format(path)

    def _pauses(self) -> tuple[float, float, float]:
        """Return ``(within_speaker, between_speakers, between_chapters)``
        in seconds, sourced from ``self._settings`` when available.

        Pre-Task-9 callers (and tests that build a service without
        going through ``generate``) get the module-level defaults.
        """
        settings = getattr(self, "_settings", None) or AudiobookSettings()
        return (
            settings.intra_speaker_silence_ms / 1000.0,
            settings.speaker_change_silence_ms / 1000.0,
            settings.chapter_silence_ms / 1000.0,
        )

    def _is_overlay_sfx(self, chunk: AudioChunk) -> bool:
        """Delegation shim — see ``concat_executor.is_overlay_sfx``."""
        return _concat_is_overlay_sfx(chunk)

    async def _concatenate_with_context(
        self, chunks: list[AudioChunk], output: Path
    ) -> list[ChapterTiming]:
        """Concatenate WAV files with context-aware silence gaps.

        Pause durations vary based on context:
        - Between chapters: 1.2 s
        - Between speakers: 400 ms
        - Within same speaker: 150 ms

        SFX chunks marked with overlay metadata
        (``[SFX: ... | under=...]``) are NOT placed in the inline
        timeline — they are mixed under subsequent voice chunks in
        a second pass with sidechain ducking.

        Returns chapter timing metadata.
        """
        clip_overrides: dict[str, Any] = {}
        try:
            mix = getattr(self, "_track_mix_full", None) or {}
            clip_overrides = dict(mix.get("clips") or {})
        except Exception:
            clip_overrides = {}

        return await _concat_concatenate_with_context(
            chunks,
            output,
            pauses=self._pauses(),
            clip_overrides=clip_overrides,
            ffmpeg_get_duration=self.ffmpeg.get_duration,
            strip_hash_fn=_strip_chunk_hash,
            compute_chapter_timings_fn=self._compute_chapter_timings,
            mix_overlay_sfx_fn=self._mix_overlay_sfx,
            dag_global_fn=self._dag_global,
        )

    async def _mix_overlay_sfx(
        self,
        base_path: Path,
        chunks_in_order: list[AudioChunk],
        inline_chunks: list[AudioChunk],
        overlays: list[tuple[int, AudioChunk]],
    ) -> None:
        """Delegation shim — see ``mix_executor.mix_overlay_sfx``."""
        await _mix_mix_overlay_sfx(
            base_path,
            chunks_in_order,
            inline_chunks,
            overlays,
            pauses=self._pauses(),
            ffmpeg_get_duration=self.ffmpeg.get_duration,
            cancel_fn=self._cancel,
        )

    async def _compute_chapter_timings(self, chunks: list[AudioChunk]) -> list[ChapterTiming]:
        """Delegation shim — see ``mix_executor.compute_chapter_timings``."""
        return await _mix_compute_chapter_timings(
            chunks,
            pauses=self._pauses(),
            ffmpeg_get_duration=self.ffmpeg.get_duration,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Per-chapter image generation  (logic lives in image_gen.py)
    # ══════════════════════════════════════════════════════════════════════

    async def _generate_chapter_images(
        self,
        chapters: list[dict[str, Any]],
        output_dir: Path,
        audiobook_id: UUID,
        video_width: int,
        video_height: int,
        chapter_indices: list[int] | None = None,
    ) -> list[Path]:
        """Delegation shim — see ``image_gen._generate_chapter_images``."""
        return await _generate_chapter_images(
            comfyui_service=self.comfyui_service,
            cancel_fn=self._cancel,
            title_card_fn=self._generate_title_card,
            chapters=chapters,
            output_dir=output_dir,
            audiobook_id=audiobook_id,
            video_width=video_width,
            video_height=video_height,
            chapter_indices=chapter_indices,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Background music
    # ══════════════════════════════════════════════════════════════════════

    def _resolve_music_service(self) -> Any | None:
        """Delegation shim — see ``music_gen._resolve_music_service``."""
        return _resolve_music_service(self.storage, self.comfyui_service)

    async def _add_music(
        self,
        audio_path: Path,
        output_path: Path,
        mood: str,
        volume_db: float,
        duration: float,
    ) -> Path:
        """Delegation shim — see ``mix_executor.add_music``."""
        return await _mix_add_music(
            audio_path,
            output_path,
            mood=mood,
            volume_db=volume_db,
            duration=duration,
            resolve_music_service_fn=self._resolve_music_service,
            ffmpeg_get_duration=self.ffmpeg.get_duration,
            voice_gain_db=float(getattr(self, "_voice_gain_db", 0.0) or 0.0),
            ducking_preset=getattr(self, "_ducking_preset", None),
            cancel_fn=self._cancel,
        )

    async def render_music_preview(
        self,
        audiobook_id: UUID,
        mood: str,
        volume_db: float = -14.0,
        seconds: float = 30.0,
    ) -> Path:
        """Delegation shim — see ``music_gen.render_music_preview``."""
        return await _render_music_preview_fn(
            audiobook_id=audiobook_id,
            mood=mood,
            storage=self.storage,
            add_music_fn=self._add_music,
            volume_db=volume_db,
            seconds=seconds,
        )

    async def _add_chapter_music(
        self,
        audio_path: Path,
        output_path: Path,
        chapter_timings: list[ChapterTiming],
        chapters: list[dict[str, Any]],
        global_mood: str,
        volume_db: float,
        audiobook_id: UUID,
        crossfade_duration: float = 2.0,
    ) -> Path:
        """Delegation shim — see ``mix_executor.add_chapter_music``."""
        return await _mix_add_chapter_music(
            audio_path,
            output_path,
            chapter_timings=chapter_timings,
            chapters=chapters,
            global_mood=global_mood,
            volume_db=volume_db,
            audiobook_id=audiobook_id,
            crossfade_duration=crossfade_duration,
            resolve_music_service_fn=self._resolve_music_service,
            ffmpeg_get_duration=self.ffmpeg.get_duration,
            voice_gain_db=float(getattr(self, "_voice_gain_db", 0.0) or 0.0),
            ducking_preset=getattr(self, "_ducking_preset", None),
            cancel_fn=self._cancel,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Optional leading/trailing silence trim (Task 2)
    # ══════════════════════════════════════════════════════════════════════
    #
    # Runs on the concatenated WAV BEFORE chapter timings, captions, and
    # MP3 export are produced. Returns the leading-silence offset in
    # seconds so callers can subtract it from any timing data computed
    # earlier in the pipeline. Off by default (PRESERVE_INTERNAL_PAUSES).
    #
    # Implementation: probe the original WAV duration, then run an
    # anchored silenceremove pass that only strips the leading and
    # trailing edges. Compare durations to recover the leading offset.
    # We can't directly read silenceremove's offset from stderr — ffmpeg
    # only emits an unparseable summary — so we infer it from a second
    # probe that strips trailing silence only (areverse + silenceremove +
    # areverse). Two ffmpeg passes total; cheap on a single audiobook.

    async def _trim_silence_in_place(self, wav_path: Path) -> float:
        """Trim leading + trailing silence from *wav_path* in place.

        Returns the leading-silence offset (seconds) that was removed,
        so callers can shift any chapter timings or caption timestamps
        that were computed against the un-trimmed WAV. Returns 0.0 if
        the trim failed (left the original file untouched).
        """
        try:
            original_duration = await self.ffmpeg.get_duration(wav_path)
        except Exception:
            return 0.0

        # Pass 1: trailing-only trim (reverse, strip leading-as-trailing,
        # reverse back). The resulting duration tells us how much
        # trailing silence the original had.
        trailing_only = wav_path.with_suffix(".trail.wav")
        cmd_trailing = [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-af",
            "areverse,"
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-40dB,"
            "areverse",
            "-c:a",
            "pcm_s16le",
            str(trailing_only),
        ]
        proc1 = await asyncio.create_subprocess_exec(
            *cmd_trailing,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc1.communicate()
        if proc1.returncode != 0 or not trailing_only.exists():
            return 0.0

        # Pass 2: full leading + trailing trim. Compare the duration
        # difference between (trailing-only) and (both) to recover the
        # leading offset.
        both = wav_path.with_suffix(".trim.wav")
        cmd_both = [
            "ffmpeg",
            "-y",
            "-i",
            str(trailing_only),
            "-af",
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-40dB",
            "-c:a",
            "pcm_s16le",
            str(both),
        ]
        proc2 = await asyncio.create_subprocess_exec(
            *cmd_both,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc2.communicate()
        if proc2.returncode != 0 or not both.exists():
            trailing_only.unlink(missing_ok=True)
            return 0.0

        try:
            trailing_only_dur = await self.ffmpeg.get_duration(trailing_only)
            trimmed_dur = await self.ffmpeg.get_duration(both)
        except Exception:
            trailing_only.unlink(missing_ok=True)
            both.unlink(missing_ok=True)
            return 0.0

        leading_offset = max(0.0, trailing_only_dur - trimmed_dur)
        # Replace the original WAV with the fully trimmed copy.
        try:
            both.replace(wav_path)
        except OSError:
            trailing_only.unlink(missing_ok=True)
            both.unlink(missing_ok=True)
            return 0.0
        trailing_only.unlink(missing_ok=True)

        log.info(
            "audiobook.silence_trim.applied",
            original_duration=round(original_duration, 3),
            trimmed_duration=round(trimmed_dur, 3),
            leading_offset=round(leading_offset, 3),
            trailing_offset=round(original_duration - trailing_only_dur, 3),
        )
        return leading_offset

    @staticmethod
    def _shift_chapter_timings(
        timings: list[ChapterTiming], offset_seconds: float
    ) -> list[ChapterTiming]:
        """Subtract *offset_seconds* from every chapter start/end so the
        timings still match the audible boundaries after a leading-trim.
        """
        if offset_seconds <= 0:
            return timings
        shifted: list[ChapterTiming] = []
        for t in timings:
            new_start = max(0.0, t.start_seconds - offset_seconds)
            new_end = max(new_start, t.end_seconds - offset_seconds)
            shifted.append(
                ChapterTiming(
                    chapter_index=t.chapter_index,
                    start_seconds=new_start,
                    end_seconds=new_end,
                    duration_seconds=new_end - new_start,
                )
            )
        return shifted

    # ══════════════════════════════════════════════════════════════════════
    # Master loudnorm (Task 3)
    # ══════════════════════════════════════════════════════════════════════
    #
    # Runs once on the fully-mixed WAV, after voice + SFX + music are
    # combined and before captions / MP3 / video. EBU R128 two-pass
    # measure-then-apply: pass 1 measures the integrated loudness, pass 2
    # applies the corrected gain with ``linear=true`` so the algorithm
    # converges to the target on a single application.
    #
    # If pass 1's stderr can't be parsed (ffmpeg version mismatch, audio
    # too short for the measurement window, etc.) we fall back to a
    # single-pass loudnorm — within ~±1 LUFS instead of ±0.5, but still
    # produces a usable mastered file rather than failing the audiobook.

    @classmethod
    def _parse_loudnorm_json(cls, stderr_text: str) -> dict[str, str] | None:
        """Delegation shim — see ``mix_executor.parse_loudnorm_json``."""
        return _mix_parse_loudnorm_json(stderr_text)

    async def _apply_master_loudnorm(self, wav_path: Path) -> None:
        """Delegation shim — see ``mix_executor.apply_master_loudnorm``."""
        settings = getattr(self, "_settings", None) or AudiobookSettings()
        await _mix_apply_master_loudnorm(
            wav_path,
            target_i=settings.loudness_target_lufs,
            target_tp=settings.true_peak_dbfs,
            target_lra=settings.loudness_lra,
            export_sample_rate=settings.sample_rate,
            cancel_fn=self._cancel,
        )

    # ══════════════════════════════════════════════════════════════════════
    # MP3 conversion
    # ══════════════════════════════════════════════════════════════════════

    async def _convert_to_mp3(self, wav_path: Path) -> Path:
        """Convert a WAV file to MP3 using the configured encoder mode.

        Task 2 removed ``silenceremove`` from the export chain so
        internal pauses survive. Task 3 removed ``loudnorm`` — the
        single audible loudnorm pass runs once at the master stage
        before this encoder call. Task 9 makes the encoder mode
        configurable: ``cbr_128 / cbr_192 / cbr_256 / vbr_v0 / vbr_v2``.
        """
        mp3_path = wav_path.with_suffix(".mp3")
        settings = getattr(self, "_settings", None) or AudiobookSettings()
        encoder_args = _mp3_encoder_args(settings.mp3_mode)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            *encoder_args,
            str(mp3_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            # Task 3: previously a retry-without-filters fallback ran here
            # to defend against ffmpeg loudnorm-version incompatibilities.
            # The encoder no longer applies any filter, so the primary
            # command IS the raw fallback — there's nothing left to fall
            # back to.
            raise RuntimeError(
                f"Failed to convert to MP3: {stderr.decode('utf-8', 'replace')[:300]}"
            )

        log.debug("audiobook.mp3_conversion_done", path=str(mp3_path))
        return mp3_path

    # ══════════════════════════════════════════════════════════════════════
    # Video creation
    # ══════════════════════════════════════════════════════════════════════

    async def _generate_title_card(
        self,
        output_dir: Path,
        title: str,
        width: int = 1920,
        height: int = 1080,
    ) -> Path:
        """Delegation shim — see ``image_gen._generate_title_card``."""
        return await _generate_title_card(output_dir, title, width=width, height=height)

    async def _create_chapter_aware_video(
        self,
        audio_path: Path,
        output_path: Path,
        chapter_timings: list[ChapterTiming],
        chapter_image_paths: list[Path],
        captions_path: Path | None = None,
        width: int = 1920,
        height: int = 1080,
        background_music_path: Path | None = None,
        audiobook_id: UUID | None = None,
    ) -> None:
        """Delegation shim — see ``video_render.create_chapter_aware_video``."""
        await _vr_create_chapter_aware_video(
            audio_path,
            output_path,
            chapter_timings=chapter_timings,
            chapter_image_paths=chapter_image_paths,
            captions_path=captions_path,
            width=width,
            height=height,
            background_music_path=background_music_path,
            audiobook_id=audiobook_id,
            ffmpeg_assemble_video=self.ffmpeg.assemble_video,
            broadcast_progress_fn=self._broadcast_progress,
        )

    async def _create_audiobook_video(
        self,
        audio_path: Path,
        output_path: Path,
        cover_image_path: str | None,
        duration: float,
        captions_path: Path | None = None,
        with_waveform: bool = True,
        width: int = 1920,
        audiobook_id: UUID | None = None,
        height: int = 1080,
    ) -> None:
        """Delegation shim — see ``video_render.create_audiobook_video``."""
        await _vr_create_audiobook_video(
            audio_path,
            output_path,
            cover_image_path=cover_image_path,
            duration=duration,
            captions_path=captions_path,
            with_waveform=with_waveform,
            width=width,
            height=height,
            audiobook_id=audiobook_id,
            settings=getattr(self, "_settings", None),
            cancel_fn=self._cancel,
            broadcast_progress_fn=self._broadcast_progress,
        )
