"""Audiobook metadata helpers — LAME priming offset and ID3 tagging.

``id3.py`` owns the mutagen-touching layer (``write_audiobook_id3``).
This module wraps it with the LAME priming-offset computation so CHAP
frames land within ±5 ms of audible chapter boundaries instead of ±50 ms.

Extracted from ``_run_mp3_export_phase`` in ``_monolith.py`` (Task 13).
``AudiobookService`` delegates to ``_apply_lame_priming_and_tag`` via a
delegation shim so the surrounding DAG-state logic stays in the monolith.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from drevalis.services.audiobook.render_plan import RenderPlan
    from drevalis.services.ffmpeg import FFmpegService

log = structlog.get_logger(__name__)


async def _apply_lame_priming_and_tag(
    *,
    final_audio: Path,
    mp3_abs: Path,
    ffmpeg: FFmpegService,
    render_plan: RenderPlan,
    title: str,
    chapters: list[dict[str, Any]],
    cover_abs: Path | None,
    audiobook_id: UUID,
) -> int:
    """Compute the LAME priming offset and write ID3 + CHAP frames.

    The LAME encoder prepends ~26 ms of silence to the MP3 stream; CHAP
    frames written without compensation drift relative to audible audio
    by that amount. This function:

    1. Probes both ``final_audio`` (WAV) and ``mp3_abs`` (MP3) durations.
    2. Computes ``priming_offset_ms = round((mp3_dur - wav_dur) * 1000)``.
    3. Calls ``render_plan.apply_priming_offset(priming_offset_ms)`` to
       shift every chapter marker by the offset.
    4. Calls ``write_audiobook_id3`` with the shifted chapter list.

    Returns the computed ``priming_offset_ms`` so the caller can include
    it in log lines.

    Any exception raised here propagates to the caller, which is expected
    to catch it and mark the ``id3_tags`` DAG stage as failed (the MP3
    file is already on disk and playable at that point).
    """
    from drevalis.services.audiobook.id3 import write_audiobook_id3

    # Task 13: LAME priming offset. The encoder prepends
    # ~26 ms of silence to the MP3 stream; CHAP frames
    # written without compensation drift relative to the
    # audible audio by that amount. Probe both files,
    # take the difference, shift the plan's chapter
    # timestamps by it. Within ±5 ms of audible
    # boundaries instead of ±50 ms.
    priming_offset_ms = 0
    try:
        wav_dur = await ffmpeg.get_duration(final_audio)
        mp3_dur = await ffmpeg.get_duration(mp3_abs)
        if wav_dur > 0 and mp3_dur > 0:
            priming_offset_ms = int(round((mp3_dur - wav_dur) * 1000))
    except Exception:
        priming_offset_ms = 0

    shifted_plan = render_plan.apply_priming_offset(priming_offset_ms)
    # Build chapter dicts in the shape ``write_audiobook_id3``
    # expects (start_seconds / end_seconds / title), but
    # source the timestamps from the priming-adjusted plan.
    id3_chapters: list[dict[str, Any]] = []
    for marker in shifted_plan.chapters:
        id3_chapters.append(
            {
                "title": marker.title,
                "start_seconds": marker.start_ms / 1000.0,
                "end_seconds": marker.end_ms / 1000.0,
            }
        )

    await write_audiobook_id3(
        mp3_abs,
        title=title,
        album=title,
        chapters=id3_chapters or (chapters if isinstance(chapters, list) else None),
        cover_path=cover_abs,
    )
    log.info(
        "audiobook.generate.id3_tagged",
        audiobook_id=str(audiobook_id),
        priming_offset_ms=priming_offset_ms,
    )
    return priming_offset_ms
