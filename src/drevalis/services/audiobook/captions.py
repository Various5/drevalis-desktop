"""Audiobook captions generation helper.

Extracted from ``_monolith.py`` as part of the round-3 audiobook service
decomposition.  The public surface consumed by ``AudiobookService`` is:

  * ``run_captions_phase`` — ASR-driven ASS + SRT captions from the
                             mastered audio WAV, with DAG journal hooks.

``AudiobookService`` shims in ``_monolith.py`` delegate to this helper,
passing ``self._check_cancelled``, ``self._broadcast_progress``,
``self._dag_global`` as explicit parameters.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)


async def run_captions_phase(
    *,
    audiobook_id: UUID,
    abs_dir: Path,
    final_audio: Path,
    caption_style_preset: str | None,
    video_width: int,
    video_height: int,
    check_cancelled_fn: Any,
    broadcast_progress_fn: Any,
    dag_global_fn: Any,
) -> tuple[Path | None, str | None, str | None]:
    """Generate ASS + SRT captions from the mastered audio.

    Returns ``(ass_path, ass_rel, srt_rel)``. The .ass path is an
    absolute filesystem path used downstream by the video assembly
    step; the rel paths are storage-relative for API responses.

    Three terminal states distinguished:

    - **success**: full captions written, DAG ``captions`` -> done.
    - **skipped**: faster-whisper not installed (optional dep);
      DAG ``captions`` -> skipped, all return values ``None`` so
      downstream video creation falls through to the no-captions
      path.
    - **failed**: any other exception during ASR; logged at
      ERROR with full traceback, DAG ``captions`` -> failed,
      return values ``None`` (audiobook still completes).

    Parameters
    ----------
    check_cancelled_fn:
        ``async def (audiobook_id: UUID) -> None`` — raises
        ``asyncio.CancelledError`` when cancelled.
    broadcast_progress_fn:
        ``async def (audiobook_id, stage, pct, msg) -> None``.
    dag_global_fn:
        ``async def (stage: str, state: str) -> None`` — journals
        DAG stage transitions.
    """
    await check_cancelled_fn(audiobook_id)
    await broadcast_progress_fn(audiobook_id, "captions", 85, "Generating captions...")
    await dag_global_fn("captions", "in_progress")

    captions_ass_path: Path | None = None
    captions_ass_rel: str | None = None
    captions_srt_rel: str | None = None

    try:
        from drevalis.services.captions import CaptionService, CaptionStyle

        caption_service = CaptionService()
        caption_dir = abs_dir / "captions"
        caption_dir.mkdir(parents=True, exist_ok=True)

        effective_preset = caption_style_preset or "youtube_highlight"
        caption_style = CaptionStyle(
            preset=effective_preset,
            font_name="Impact",
            font_size=60,
            primary_color="#FFFFFF",
            highlight_color="#FFD700",
            outline_color="#000000",
            outline_width=5,
            position="bottom",
            margin_v=100,
            words_per_line=4,
            uppercase=True,
            play_res_x=video_width,
            play_res_y=video_height,
        )

        caption_result = await caption_service.generate_from_audio(
            audio_path=final_audio,
            output_dir=caption_dir,
            language="en",
            style=caption_style,
        )
        captions_ass_path = Path(caption_result.ass_path)
        captions_ass_rel = f"audiobooks/{audiobook_id}/captions/captions.ass"
        captions_srt_rel = f"audiobooks/{audiobook_id}/captions/captions.srt"

        log.info(
            "audiobook.generate.captions_done",
            audiobook_id=str(audiobook_id),
            caption_count=len(caption_result.captions),
        )
        await dag_global_fn("captions", "done")
    except ImportError:
        log.warning(
            "audiobook.generate.captions_skipped",
            audiobook_id=str(audiobook_id),
            reason="faster-whisper not installed",
        )
        await dag_global_fn("captions", "skipped")
    except Exception as exc:
        log.error(
            "audiobook.generate.captions_failed",
            audiobook_id=str(audiobook_id),
            error=str(exc),
            exc_info=True,
        )
        await dag_global_fn("captions", "failed")

    return captions_ass_path, captions_ass_rel, captions_srt_rel
