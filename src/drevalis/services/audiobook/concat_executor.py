"""Audio concatenation helpers.

Extracted from ``_monolith.py`` as part of the round-3 audiobook service
decomposition.  The public surface consumed by ``AudiobookService`` is:

  * ``probe_audio_format``      — ffprobe-based stream-format inspection (pure)
  * ``is_overlay_sfx``          — predicate on AudioChunk (pure)
  * ``apply_clip_override``     — per-clip gain/mute substitution (async)
  * ``concatenate_with_context``— full concat pass with silence + overlay SFX

``AudiobookService`` shims in ``_monolith.py`` delegate to these helpers,
passing ``self.ffmpeg``, ``self._pauses()``, etc. as explicit parameters.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from drevalis.services.audiobook._monolith import AudioChunk, ChapterTiming

log = structlog.get_logger(__name__)


async def probe_audio_format(path: Path) -> tuple[int, int, str, str] | None:
    """Return ``(sample_rate, channels, codec_name, sample_fmt)`` or None.

    ``None`` on ffprobe failure / missing audio stream / unparseable
    JSON. Callers treat any ``None`` as "not uniform" and fall back
    to the re-encode concat path.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels,codec_name,sample_fmt",
        "-of",
        "json",
        str(path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        data = json.loads(out.decode("utf-8", errors="replace"))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return None
    streams = data.get("streams") or []
    if not streams:
        return None
    s = streams[0]
    try:
        sample_rate = int(s["sample_rate"])
        channels = int(s["channels"])
        codec_name = str(s["codec_name"])
        sample_fmt = str(s.get("sample_fmt") or "")
    except (KeyError, ValueError, TypeError):
        return None
    return sample_rate, channels, codec_name, sample_fmt


def is_overlay_sfx(chunk: AudioChunk) -> bool:
    """Return True when *chunk* is a SFX overlay (not inline timeline)."""
    return chunk.speaker == "__SFX__" and (
        chunk.overlay_voice_blocks is not None or chunk.overlay_seconds is not None
    )


async def apply_clip_override(
    chunk: AudioChunk,
    *,
    clip_overrides: dict[str, dict[str, Any]],
    adjusted_dir: Path,
    ffmpeg_get_duration: Any,
    strip_hash_fn: Any,
) -> Path | None:
    """Apply per-clip gain or mute override from the editor.

    ``clip_overrides`` maps stable clip id → ``{gain_db, mute}``.
    ``adjusted_dir`` is the scratch directory for adjusted WAV copies.
    ``ffmpeg_get_duration`` is ``async def (path) -> float``.
    ``strip_hash_fn`` is ``(stem: str) -> str``.

    Returns the effective path to use in the concat list:
    - the original path when no override applies
    - a silence file of matching duration when muted
    - a gain-adjusted copy when ``gain_db`` is non-trivial
    - ``None`` when the chunk should be dropped entirely (muted + zero-dur)
    """
    stable_id = strip_hash_fn(chunk.path.stem)
    override = clip_overrides.get(stable_id)
    if not override:
        return chunk.path
    if override.get("mute"):
        try:
            dur = await ffmpeg_get_duration(chunk.path)
        except Exception:
            dur = 0.0
        if dur <= 0:
            return None
        sil = adjusted_dir / f"{stable_id}_muted.wav"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            f"{dur:.3f}",
            "-c:a",
            "pcm_s16le",
            str(sil),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return sil if sil.exists() else chunk.path
    gain_db = float(override.get("gain_db", 0.0) or 0.0)
    if abs(gain_db) < 0.01:
        return chunk.path
    adjusted = adjusted_dir / f"{stable_id}_g{int(gain_db * 10):+d}.wav"
    if not adjusted.exists():
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(chunk.path),
            "-af",
            f"volume={gain_db:+.2f}dB",
            "-c:a",
            "pcm_s16le",
            str(adjusted),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            log.warning(
                "audiobook.clip_override.failed",
                clip_id=chunk.path.stem,
                gain_db=gain_db,
                stderr=err.decode("utf-8", errors="replace")[:200],
            )
            return chunk.path
    return adjusted


async def concatenate_with_context(
    chunks: list[AudioChunk],
    output: Path,
    *,
    pauses: tuple[float, float, float],
    clip_overrides: dict[str, dict[str, Any]],
    ffmpeg_get_duration: Any,
    strip_hash_fn: Any,
    compute_chapter_timings_fn: Any,
    mix_overlay_sfx_fn: Any,
    dag_global_fn: Any,
) -> list[ChapterTiming]:
    """Concatenate WAV files with context-aware silence gaps.

    Parameters
    ----------
    chunks:
        Ordered list of ``AudioChunk`` instances to concatenate.
    output:
        Destination WAV path.
    pauses:
        ``(within_speaker, between_speakers, between_chapters)`` in seconds.
    clip_overrides:
        Per-clip ``{stable_id: {gain_db, mute}}`` from the editor's
        ``track_mix.clips`` dict.
    ffmpeg_get_duration:
        ``async def (path: Path) -> float`` — from ``FFmpegService``.
    strip_hash_fn:
        ``(stem: str) -> str`` — strips the trailing ``_<12hex>`` from a
        chunk filename stem so overrides survive cache busts.
    compute_chapter_timings_fn:
        ``async def (inline_chunks: list[AudioChunk]) -> list[ChapterTiming]``.
    mix_overlay_sfx_fn:
        ``async def (base_path, chunks_in_order, inline_chunks, overlays) -> None``.
    dag_global_fn:
        ``async def (stage: str, value: str) -> None`` — DAG state writer.

    Returns
    -------
    list[ChapterTiming]
    """
    if not chunks:
        raise RuntimeError("No audio chunks to concatenate")

    pause_within, pause_speaker, pause_chapter = pauses

    # Partition: inline vs overlay-SFX.
    inline_chunks: list[AudioChunk] = []
    overlays: list[tuple[int, AudioChunk]] = []
    for orig_idx, chunk in enumerate(chunks):
        if is_overlay_sfx(chunk):
            overlays.append((orig_idx, chunk))
        else:
            inline_chunks.append(chunk)

    if not inline_chunks:
        inline_chunks = list(chunks)
        overlays = []

    concat_list = output.parent / "_concat_list.txt"

    # Pre-generate silence files for each duration.
    silence_files: dict[float, Path] = {}
    for dur in (pause_within, pause_speaker, pause_chapter):
        sil_path = output.parent / f"_silence_{int(dur * 1000)}ms.wav"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            str(dur),
            str(sil_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"Failed to generate silence: {stderr_text[:300]}")
        silence_files[dur] = sil_path

    adjusted_dir = output.parent / "_adjusted"
    if clip_overrides:
        adjusted_dir.mkdir(parents=True, exist_ok=True)

    # Build concat list with context-aware silence.
    ordered_paths: list[Path] = []
    for i, chunk in enumerate(inline_chunks):
        effective_path = await apply_clip_override(
            chunk,
            clip_overrides=clip_overrides,
            adjusted_dir=adjusted_dir,
            ffmpeg_get_duration=ffmpeg_get_duration,
            strip_hash_fn=strip_hash_fn,
        )
        if effective_path is None:
            continue
        ordered_paths.append(effective_path)

        if i < len(inline_chunks) - 1:
            next_chunk = inline_chunks[i + 1]
            if chunk.chapter_index != next_chunk.chapter_index:
                pause = pause_chapter
            elif chunk.speaker != next_chunk.speaker:
                pause = pause_speaker
            else:
                pause = pause_within
            ordered_paths.append(silence_files[pause])

    lines = [f"file '{str(p).replace(chr(92), '/')}'" for p in ordered_paths]
    concat_list.write_text("\n".join(lines), encoding="utf-8")

    # Task 7: probe every input for stream-copy eligibility.
    formats = await asyncio.gather(
        *(probe_audio_format(p) for p in ordered_paths),
        return_exceptions=False,
    )
    uniform = (
        len(formats) > 0 and all(f is not None for f in formats) and len({f for f in formats}) == 1
    )

    if uniform:
        log.info(
            "audiobook.concat.stream_copy",
            chunk_count=len(ordered_paths),
            format=formats[0],
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output),
        ]
    else:
        mixed_summary = sorted({f for f in formats if f is not None})
        log.info(
            "audiobook.concat.reencode",
            chunk_count=len(ordered_paths),
            distinct_formats=len(mixed_summary),
            formats=mixed_summary,
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-sample_fmt",
            "s16",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 and uniform:
        log.warning(
            "audiobook.concat.stream_copy_failed_retrying_reencode",
            stderr=stderr.decode("utf-8", errors="replace")[:200],
        )
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-sample_fmt",
            "s16",
            "-c:a",
            "pcm_s16le",
            str(output),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to concatenate chunks: {stderr_text[:300]}")

    chapter_timings: list[ChapterTiming] = await compute_chapter_timings_fn(inline_chunks)

    # Overlay SFX pass.
    if overlays:
        await dag_global_fn("overlay_sfx", "in_progress")
        try:
            await mix_overlay_sfx_fn(
                base_path=output,
                chunks_in_order=chunks,
                inline_chunks=inline_chunks,
                overlays=overlays,
            )
            await dag_global_fn("overlay_sfx", "done")
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "audiobook.overlay_sfx.mix_failed",
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
            await dag_global_fn("overlay_sfx", "failed")
    else:
        await dag_global_fn("overlay_sfx", "skipped")

    # Cleanup temp files.
    concat_list.unlink(missing_ok=True)
    for sil in silence_files.values():
        sil.unlink(missing_ok=True)

    return chapter_timings
