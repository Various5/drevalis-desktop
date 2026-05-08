"""Audiobook video rendering helpers.

Extracted from ``_monolith.py`` as part of the round-3 audiobook service
decomposition.  The public surface consumed by ``AudiobookService`` is:

  * ``create_audiobook_video``       — single-image / dark-bg MP4 with optional
                                       waveform and burned-in captions
  * ``create_chapter_aware_video``   — per-chapter Ken Burns MP4 via
                                       ``FFmpegService.assemble_video``

``AudiobookService`` shims in ``_monolith.py`` delegate to these helpers,
passing ``self.ffmpeg``, ``self._settings``, etc. as explicit parameters.
"""

from __future__ import annotations

import asyncio
import re as _re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from drevalis.schemas.audiobook import AudiobookSettings
    from drevalis.services.audiobook._monolith import ChapterTiming

log = structlog.get_logger(__name__)


async def create_chapter_aware_video(
    audio_path: Path,
    output_path: Path,
    *,
    chapter_timings: list[ChapterTiming],
    chapter_image_paths: list[Path],
    captions_path: Path | None = None,
    width: int = 1920,
    height: int = 1080,
    background_music_path: Path | None = None,
    audiobook_id: UUID | None = None,
    ffmpeg_assemble_video: Any,
    broadcast_progress_fn: Any = None,
) -> None:
    """Create a video with Ken Burns transitions between chapter images.

    Reuses ``FFmpegService.assemble_video()`` which already handles
    zoompan, xfade, audio mastering, and subtitle burn-in.

    Parameters
    ----------
    ffmpeg_assemble_video:
        Bound method ``FFmpegService.assemble_video``.
    broadcast_progress_fn:
        ``async def (audiobook_id, stage, pct, msg) -> None`` or ``None``.
    """
    from drevalis.services.ffmpeg import (
        AssemblyConfig,
        AudioMixConfig,
        SceneInput,
    )

    scenes = [
        SceneInput(
            image_path=img_path,
            duration_seconds=timing.duration_seconds,
        )
        for img_path, timing in zip(chapter_image_paths, chapter_timings, strict=False)
    ]

    config = AssemblyConfig(
        width=width,
        height=height,
        fps=25,
        ken_burns_enabled=True,
        transition_duration=1.0,
    )

    audio_config = AudioMixConfig(
        voice_normalize=False,  # already mixed
        voice_compressor=False,
        voice_eq=False,
    )

    async def _on_encode_progress(pct: float) -> None:
        if audiobook_id and broadcast_progress_fn is not None:
            encode_pct = 90 + int(pct * 0.09)  # map 0-100% to 90-99%
            await broadcast_progress_fn(
                audiobook_id,
                "assembly",
                encode_pct,
                f"Encoding video... {int(pct)}%",
            )

    await ffmpeg_assemble_video(
        scenes=scenes,
        voiceover_path=audio_path,
        output_path=output_path,
        captions_path=captions_path,
        background_music_path=background_music_path,
        audio_config=audio_config,
        config=config,
        on_progress=_on_encode_progress,
    )

    log.info(
        "audiobook.chapter_video.done",
        output=str(output_path),
        chapters=len(scenes),
    )


async def create_audiobook_video(
    audio_path: Path,
    output_path: Path,
    *,
    cover_image_path: str | None,
    duration: float,
    captions_path: Path | None = None,
    with_waveform: bool = True,
    width: int = 1920,
    height: int = 1080,
    audiobook_id: UUID | None = None,
    settings: AudiobookSettings | None = None,
    cancel_fn: Any = None,
    broadcast_progress_fn: Any = None,
) -> None:
    """Create a single-image audiobook video.

    Falls back to a dark background when *cover_image_path* is absent or
    non-existent. Optionally overlays a waveform and burns in ASS captions.

    Parameters
    ----------
    settings:
        ``AudiobookSettings`` instance for video codec / CRF / preset.
        When ``None``, module-level defaults are used.
    cancel_fn:
        ``async def () -> None`` — raises ``asyncio.CancelledError`` when
        the audiobook has been cancelled, or ``None`` to skip checks.
    broadcast_progress_fn:
        ``async def (audiobook_id, stage, pct, msg) -> None`` or ``None``.
    """
    if cancel_fn is not None:
        await cancel_fn()

    from drevalis.schemas.audiobook import AudiobookSettings as _AudiobookSettings

    effective_settings = settings or _AudiobookSettings()

    PIPE = asyncio.subprocess.PIPE
    filter_parts: list[str] = []

    has_cover = bool(cover_image_path and Path(cover_image_path).exists())
    audio_input_idx = 1 if has_cover else 0

    if has_cover:
        frames = max(1, int(duration * 25))
        filter_parts.append(
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='1.0+0.0003*on':d={frames}:s={width}x{height}:fps=25,"
            "format=yuv420p[bg]"
        )
    else:
        filter_parts.append(
            f"color=c=0x0f0f1a:s={width}x{height}:d={duration}:r=25,format=yuv420p[bg]"
        )

    if with_waveform:
        waveform_h = max(80, round(height * 0.14 / 2) * 2)
        waveform_margin = round(waveform_h * 0.2)
        filter_parts.append(
            f"[{audio_input_idx}:a]showwaves=s={width}x{waveform_h}:mode=cline"
            f":colors=white@0.3:rate=25[waves]"
        )
        filter_parts.append(f"[bg][waves]overlay=0:H-{waveform_h + waveform_margin}[v]")
        video_label = "v"
    else:
        video_label = "bg"

    if captions_path and captions_path.exists():
        escaped = str(captions_path).replace("\\", "/").replace(":", "\\:")
        filter_parts.append(f"[{video_label}]subtitles='{escaped}'[vout]")
        output_label = "vout"
    else:
        output_label = video_label

    input_args: list[str] = ["-y"]
    if has_cover:
        input_args.extend(["-loop", "1", "-i", str(cover_image_path)])
    input_args.extend(["-i", str(audio_path)])

    cmd = [
        "ffmpeg",
        *input_args,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        f"[{output_label}]",
        "-map",
        f"{audio_input_idx}:a",
        "-c:v",
        effective_settings.video_codec,
        "-crf",
        str(effective_settings.video_crf),
        "-preset",
        effective_settings.video_preset,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        str(duration),
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)

    # Stream stderr for progress tracking.
    stderr_lines: list[str] = []
    last_pct = -1
    assert proc.stderr is not None  # PIPE'd above; mypy can't narrow
    while True:
        line = await proc.stderr.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").strip()
        stderr_lines.append(text)
        if audiobook_id and broadcast_progress_fn is not None and duration > 10:
            m = _re.search(r"time=(\d+):(\d+):(\d+\.\d+)", text)
            if m:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                pct = min(99, int(t / duration * 100))
                if pct > last_pct + 2:
                    last_pct = pct
                    await broadcast_progress_fn(
                        audiobook_id,
                        "assembly",
                        90 + int(pct * 0.09),
                        f"Encoding video... {pct}%",
                    )

    await proc.wait()
    if proc.returncode != 0:
        stderr_text = "\n".join(stderr_lines)
        raise RuntimeError(f"Failed to create audiobook video: {stderr_text[-300:]}")
