"""Audio mixing helpers — overlay SFX, music beds, master loudnorm.

Extracted from ``_monolith.py`` as part of the round-3 audiobook service
decomposition.  The public surface consumed by ``AudiobookService`` is:

  * ``DUCKING_PRESETS``            — re-exported constants (tests + shims)
  * ``SFX_DUCKING``                — re-exported constant
  * ``DEFAULT_DUCKING_PRESET``     — re-exported constant
  * ``build_music_mix_graph``      — pure filter-complex string builder
  * ``mix_overlay_sfx``            — async, single ffmpeg pass for SFX overlays
  * ``compute_chapter_timings``    — async, pure timing accumulator
  * ``add_music``                  — async, mix single music track under voice
  * ``add_chapter_music``          — async, per-chapter music with crossfades
  * ``apply_master_loudnorm``      — async, EBU R128 two-pass master
  * ``parse_loudnorm_json``        — pure stderr JSON extractor (also on class)

``AudiobookService`` shims in ``_monolith.py`` delegate to these helpers,
passing ``self.ffmpeg``, ``self._settings``, etc. as explicit parameters.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    from drevalis.services.audiobook._monolith import AudioChunk, ChapterTiming

log = structlog.get_logger(__name__)

# ── Music-bed ducking presets (Task 6) ───────────────────────────────────────
DUCKING_PRESETS: dict[str, dict[str, Any]] = {
    "static": {
        "mode": "static",
        "music_db": -22.0,
    },
    "subtle": {
        "mode": "sidechain",
        "music_db": -20.0,
        "threshold": 0.125,
        "ratio": 3,
        "attack": 15,
        "release": 800,
    },
    "normal": {
        "mode": "sidechain",
        "music_db": -18.0,
        "threshold": 0.1,
        "ratio": 4,
        "attack": 10,
        "release": 600,
    },
    "strong": {
        "mode": "sidechain",
        "music_db": -15.0,
        "threshold": 0.1,
        "ratio": 6,
        "attack": 8,
        "release": 400,
    },
    "cinematic": {
        "mode": "sidechain",
        "music_db": -12.0,
        "threshold": 0.08,
        "ratio": 8,
        "attack": 5,
        "release": 350,
    },
}
DEFAULT_DUCKING_PRESET = "static"

# SFX overlay ducking — separate from the music-bed presets above.
SFX_DUCKING: dict[str, float | int] = {
    "threshold": 0.1,
    "ratio": 5,
    "attack": 8,
    "release": 250,
}

# Master pre-loudnorm limiter ceiling.
MASTER_LIMITER_CEILING_DB = -1.0


def build_music_mix_graph(
    *,
    preset: dict[str, Any],
    voice_gain_db: float,
    music_volume_db: float,
    music_pad_ms: int,
) -> str:
    """Build the filter_complex graph for the voice + music master mix.

    ``preset`` is one of the ``DUCKING_PRESETS`` values. ``static`` mode
    skips sidechain compression entirely; sidechain modes apply
    threshold / ratio / attack / release from the preset.
    """
    voice_branch = f"[0:a]volume={voice_gain_db:+.1f}dB[voice]"
    bgm_branch = f"[1:a]apad=whole_dur={music_pad_ms}ms,volume={music_volume_db}dB[bgm]"
    if preset.get("mode") == "static":
        return (
            f"{voice_branch};"
            f"{bgm_branch};"
            "[voice][bgm]amix=inputs=2:duration=longest:dropout_transition=2:normalize=0[mixed];"
            f"[mixed]alimiter=limit={MASTER_LIMITER_CEILING_DB}dB[out]"
        )
    threshold = preset["threshold"]
    ratio = preset["ratio"]
    attack = preset["attack"]
    release = preset["release"]
    return (
        f"{voice_branch};"
        f"{bgm_branch};"
        f"[bgm][voice]sidechaincompress=threshold={threshold}:ratio={ratio}"
        f":attack={attack}:release={release}[ducked];"
        "[voice][ducked]amix=inputs=2:duration=longest:dropout_transition=2:normalize=0[mixed];"
        f"[mixed]alimiter=limit={MASTER_LIMITER_CEILING_DB}dB[out]"
    )


# Loudnorm JSON regex — shared between parse_loudnorm_json and
# AudiobookService._parse_loudnorm_json (which delegates here).
_LOUDNORM_JSON_RE = re.compile(
    r"(\{[^{}]*\"input_i\"[^{}]*\})",
    re.DOTALL,
)


def parse_loudnorm_json(stderr_text: str) -> dict[str, str] | None:
    """Extract loudnorm pass-1 measurements from ffmpeg stderr.

    Returns ``None`` if the JSON block can't be located or is missing any
    required field.
    """
    match = _LOUDNORM_JSON_RE.search(stderr_text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
    required = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    if not required.issubset(data.keys()):
        return None
    return {k: str(data[k]) for k in required}


async def compute_chapter_timings(
    chunks: list[AudioChunk],
    *,
    pauses: tuple[float, float, float],
    ffmpeg_get_duration: Any,
) -> list[ChapterTiming]:
    """Compute chapter start/end times from chunk audio durations.

    ``pauses`` is ``(within_speaker, between_speakers, between_chapters)``
    in seconds. ``ffmpeg_get_duration`` is ``async def (path) -> float``.
    """
    from drevalis.services.audiobook._monolith import ChapterTiming

    pause_within, pause_speaker, pause_chapter = pauses

    chunk_durations: list[float] = []
    for chunk in chunks:
        dur = await ffmpeg_get_duration(chunk.path)
        chunk_durations.append(dur)

    timings: list[ChapterTiming] = []
    current_time = 0.0
    current_chapter = chunks[0].chapter_index if chunks else 0
    chapter_start = 0.0

    for i, (chunk, dur) in enumerate(zip(chunks, chunk_durations, strict=False)):
        if chunk.chapter_index != current_chapter:
            timings.append(
                ChapterTiming(
                    chapter_index=current_chapter,
                    start_seconds=chapter_start,
                    end_seconds=current_time,
                    duration_seconds=current_time - chapter_start,
                )
            )
            chapter_start = current_time + pause_chapter
            current_chapter = chunk.chapter_index

        current_time += dur

        if i < len(chunks) - 1:
            next_chunk = chunks[i + 1]
            if chunk.chapter_index != next_chunk.chapter_index:
                current_time += pause_chapter
            elif chunk.speaker != next_chunk.speaker:
                current_time += pause_speaker
            else:
                current_time += pause_within

    timings.append(
        ChapterTiming(
            chapter_index=current_chapter,
            start_seconds=chapter_start,
            end_seconds=current_time,
            duration_seconds=current_time - chapter_start,
        )
    )
    return timings


async def mix_overlay_sfx(
    base_path: Path,
    chunks_in_order: list[AudioChunk],
    inline_chunks: list[AudioChunk],
    overlays: list[tuple[int, AudioChunk]],
    *,
    pauses: tuple[float, float, float],
    ffmpeg_get_duration: Any,
    cancel_fn: Any = None,
) -> None:
    """Mix overlay SFX onto the inline audiobook base.

    ``pauses`` is ``(within_speaker, between_speakers, between_chapters)``
    in seconds. ``ffmpeg_get_duration`` is ``async def (path) -> float``.
    ``cancel_fn`` is an optional ``async def () -> None``.
    """
    if cancel_fn is not None:
        await cancel_fn()

    pause_within, pause_speaker, pause_chapter = pauses

    orig_to_inline: dict[int, int] = {}
    inline_set: set[int] = set()
    running_inline_idx = 0
    for orig_idx, chunk in enumerate(chunks_in_order):
        if chunk in inline_chunks[running_inline_idx : running_inline_idx + 1]:
            orig_to_inline[orig_idx] = running_inline_idx
            inline_set.add(orig_idx)
            running_inline_idx += 1
            if running_inline_idx >= len(inline_chunks):
                break
    if len(orig_to_inline) != len(inline_chunks):
        orig_to_inline = {}
        inline_set = set()
        j = 0
        for orig_idx, chunk in enumerate(chunks_in_order):
            if j < len(inline_chunks) and chunk is inline_chunks[j]:
                orig_to_inline[orig_idx] = j
                inline_set.add(orig_idx)
                j += 1

    inline_durations: list[float] = []
    for c in inline_chunks:
        inline_durations.append(await ffmpeg_get_duration(c.path))

    def inline_start(i: int) -> float:
        t = 0.0
        for k in range(i):
            t += inline_durations[k]
            a, b = inline_chunks[k], inline_chunks[k + 1]
            if a.chapter_index != b.chapter_index:
                t += pause_chapter
            elif a.speaker != b.speaker:
                t += pause_speaker
            else:
                t += pause_within
        return t

    overlay_plans: list[tuple[Path, float, float, float]] = []
    for orig_idx, sfx_chunk in overlays:
        next_inline_orig: int | None = None
        for j in range(orig_idx + 1, len(chunks_in_order)):
            if j in inline_set:
                next_inline_orig = j
                break
        if next_inline_orig is None:
            start = sum(inline_durations) + sum(
                pause_chapter
                if inline_chunks[k].chapter_index != inline_chunks[k + 1].chapter_index
                else (
                    pause_speaker
                    if inline_chunks[k].speaker != inline_chunks[k + 1].speaker
                    else pause_within
                )
                for k in range(len(inline_chunks) - 1)
            )
        else:
            start = inline_start(orig_to_inline[next_inline_orig])

        sfx_dur = await ffmpeg_get_duration(sfx_chunk.path)
        overlay_plans.append((sfx_chunk.path, start, sfx_dur, float(sfx_chunk.overlay_duck_db)))

    if not overlay_plans:
        return

    tmp_dir = base_path.parent
    mixed = tmp_dir / "_overlay_pass.wav"

    sfx_branches: list[str] = []
    for i, (_path, start_sec, sfx_dur, duck_db) in enumerate(overlay_plans):
        start_ms = max(0, int(start_sec * 1000))
        end_sec = start_sec + sfx_dur
        input_idx = i + 1
        sfx_branches.append(
            f"[{input_idx}:a]adelay={start_ms}|{start_ms},apad,"
            f"atrim=0:{end_sec:.2f},"
            f"volume={duck_db:.1f}dB[sfx{i}]"
        )

    if len(overlay_plans) == 1:
        bus_label = "[sfx0]"
        bus_step = ""
    else:
        sfx_inputs = "".join(f"[sfx{i}]" for i in range(len(overlay_plans)))
        bus_step = (
            f";{sfx_inputs}amix=inputs={len(overlay_plans)}:"
            "duration=longest:dropout_transition=0[sfxbus]"
        )
        bus_label = "[sfxbus]"

    sfx_threshold = SFX_DUCKING["threshold"]
    sfx_ratio = SFX_DUCKING["ratio"]
    sfx_attack = SFX_DUCKING["attack"]
    sfx_release = SFX_DUCKING["release"]
    graph = (
        ";".join(sfx_branches)
        + bus_step
        + f";{bus_label}[0:a]sidechaincompress=threshold={sfx_threshold}"
        f":ratio={sfx_ratio}:attack={sfx_attack}:release={sfx_release}[ducked]"
        + ";[0:a][ducked]amix=inputs=2:duration=longest:"
        "dropout_transition=0[out]"
    )

    cmd = ["ffmpeg", "-y", "-i", str(base_path)]
    for path, _start_sec, _sfx_dur, _duck_db in overlay_plans:
        cmd.extend(["-i", str(path)])
    cmd.extend(
        [
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(mixed),
        ]
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0 or not mixed.exists():
        log.warning(
            "audiobook.overlay_sfx.single_pass_failed",
            overlay_count=len(overlay_plans),
            rc=proc.returncode,
            stderr=err.decode("utf-8", errors="replace")[:300],
        )
        mixed.unlink(missing_ok=True)
        return

    mixed.replace(base_path)
    log.info(
        "audiobook.overlay_sfx.mixed_single_pass",
        overlay_count=len(overlay_plans),
        duck_db=[round(p[3], 1) for p in overlay_plans],
    )


async def add_music(
    audio_path: Path,
    output_path: Path,
    *,
    mood: str,
    volume_db: float,
    duration: float,
    resolve_music_service_fn: Any,
    ffmpeg_get_duration: Any,
    voice_gain_db: float = 0.0,
    ducking_preset: dict[str, Any] | None = None,
    cancel_fn: Any = None,
) -> Path:
    """Mix a single background music track under the voiceover.

    Returns ``audio_path`` unchanged if no music is available.
    ``resolve_music_service_fn`` is ``() -> MusicService | None``.
    ``ffmpeg_get_duration`` is ``async def (path) -> float``.
    """
    if cancel_fn is not None:
        await cancel_fn()
    log.info(
        "audiobook.music.requested",
        mood=mood,
        duration_seconds=duration,
        volume_db=volume_db,
    )
    music_svc = resolve_music_service_fn()
    if music_svc is None:
        return audio_path

    music_path = await music_svc.get_music_for_episode(
        mood=mood,
        target_duration=duration,
        episode_id=uuid4(),
    )
    if not music_path:
        log.warning(
            "audiobook.music.no_track_resolved",
            mood=mood,
            duration_seconds=duration,
            hint=(
                "MusicService returned no track. Either the mood is missing "
                "from the curated library AND no ComfyUI server is registered "
                "for AceStep generation, or the requested duration was 0. "
                "Check Settings → ComfyUI Servers."
            ),
        )
        return audio_path

    log.info(
        "audiobook.music.track_resolved",
        music_path=str(music_path),
        mood=mood,
        volume_db=volume_db,
    )

    try:
        voice_dur_seconds = await ffmpeg_get_duration(audio_path)
    except Exception:
        voice_dur_seconds = duration
    voice_pad_ms = max(0, int(voice_dur_seconds * 1000))

    preset = ducking_preset or DUCKING_PRESETS[DEFAULT_DUCKING_PRESET]
    graph = build_music_mix_graph(
        preset=preset,
        voice_gain_db=voice_gain_db,
        music_volume_db=volume_db,
        music_pad_ms=voice_pad_ms,
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-i",
        str(music_path),
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to mix background music: {stderr_text[:300]}")

    log.info(
        "audiobook.music.mix_done",
        output=str(output_path),
        duration_seconds=duration,
        mood=mood,
    )
    return output_path


async def add_chapter_music(
    audio_path: Path,
    output_path: Path,
    *,
    chapter_timings: list[ChapterTiming],
    chapters: list[dict[str, Any]],
    global_mood: str,
    volume_db: float,
    audiobook_id: Any,
    crossfade_duration: float = 2.0,
    resolve_music_service_fn: Any,
    ffmpeg_get_duration: Any,
    voice_gain_db: float = 0.0,
    ducking_preset: dict[str, Any] | None = None,
    cancel_fn: Any = None,
) -> Path:
    """Generate per-chapter music with crossfades, then mix under voiceover.

    Returns ``audio_path`` unchanged if no music is available.
    """
    if cancel_fn is not None:
        await cancel_fn()
    music_svc = resolve_music_service_fn()
    if music_svc is None:
        return audio_path

    music_dir = audio_path.parent / "music"
    music_dir.mkdir(parents=True, exist_ok=True)

    chapter_music_paths: list[Path | None] = []
    for i, timing in enumerate(chapter_timings):
        if cancel_fn is not None:
            await cancel_fn()
        mood = global_mood
        if i < len(chapters):
            mood = chapters[i].get("music_mood") or global_mood

        target_dur = timing.duration_seconds + crossfade_duration
        music_path = await music_svc.get_music_for_episode(
            mood=mood,
            target_duration=target_dur,
            episode_id=uuid4(),
        )
        if music_path:
            trimmed = music_dir / f"ch{i:03d}_music.wav"
            trim_cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(music_path),
                "-t",
                str(target_dur),
                "-af",
                f"afade=t=out:st={max(0, target_dur - crossfade_duration):.2f}:d={crossfade_duration:.2f}",
                "-c:a",
                "pcm_s16le",
                str(trimmed),
            ]
            proc = await asyncio.create_subprocess_exec(
                *trim_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            chapter_music_paths.append(trimmed if trimmed.exists() else None)

            if i < len(chapters):
                chapters[i]["music_path"] = f"audiobooks/{audiobook_id}/music/ch{i:03d}_music.wav"
        else:
            chapter_music_paths.append(None)

        log.debug(
            "audiobook.chapter_music.generated",
            chapter_index=i,
            mood=mood,
            duration=target_dur,
            available=music_path is not None,
        )

    valid_music = [(i, p) for i, p in enumerate(chapter_music_paths) if p]
    if not valid_music:
        log.info("audiobook.chapter_music.no_music_available")
        return audio_path

    if len(valid_music) == 1:
        combined_music: Path = valid_music[0][1]
    else:
        combined_music = music_dir / "combined_music.wav"
        inputs: list[str] = []
        for _, mp in valid_music:
            inputs.extend(["-i", str(mp)])

        xfd = max(0.05, float(crossfade_duration))
        filter_parts: list[str] = []
        prev = "[0:a]"
        for idx in range(1, len(valid_music)):
            out_label = f"[x{idx}]" if idx < len(valid_music) - 1 else "[out]"
            filter_parts.append(f"{prev}[{idx}:a]acrossfade=d={xfd:.3f}:c1=tri:c2=tri{out_label}")
            prev = out_label
        filter_graph = ";".join(filter_parts)

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filter_graph,
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            str(combined_music),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_b = await proc.communicate()
        if not combined_music.exists() or proc.returncode != 0:
            log.warning(
                "audiobook.chapter_music.crossfade_failed",
                error=stderr_b.decode("utf-8", errors="replace")[:200],
            )
            return audio_path

    try:
        voice_dur_seconds = await ffmpeg_get_duration(audio_path)
    except Exception:
        voice_dur_seconds = sum(t.duration_seconds for t in chapter_timings)
    voice_pad_ms = max(0, int(voice_dur_seconds * 1000))

    preset = ducking_preset or DUCKING_PRESETS[DEFAULT_DUCKING_PRESET]
    graph = build_music_mix_graph(
        preset=preset,
        voice_gain_db=voice_gain_db,
        music_volume_db=volume_db,
        music_pad_ms=voice_pad_ms,
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-i",
        str(combined_music),
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to mix chapter music: {stderr_text[:300]}")

    log.info("audiobook.chapter_music.mix_done", output=str(output_path))
    return output_path


async def apply_master_loudnorm(
    wav_path: Path,
    *,
    target_i: float,
    target_tp: float,
    target_lra: float,
    export_sample_rate: int,
    cancel_fn: Any = None,
) -> None:
    """Master loudnorm pass on *wav_path*. Replaces in place.

    Two-pass when possible (±0.5 LUFS); single-pass fallback when
    pass 1 measurements can't be parsed (~±1 LUFS).
    """
    if cancel_fn is not None:
        await cancel_fn()

    measure_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(wav_path),
        "-af",
        f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json",
        "-f",
        "null",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *measure_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    measurements: dict[str, str] | None = None
    if proc.returncode == 0:
        measurements = parse_loudnorm_json(err.decode("utf-8", errors="replace"))

    out_tmp = wav_path.with_suffix(".master.wav")
    if measurements is not None:
        af = (
            f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}"
            f":measured_I={measurements['input_i']}"
            f":measured_TP={measurements['input_tp']}"
            f":measured_LRA={measurements['input_lra']}"
            f":measured_thresh={measurements['input_thresh']}"
            f":offset={measurements['target_offset']}"
            ":linear=true"
            ":print_format=summary"
        )
    else:
        log.warning(
            "audiobook.master_loudnorm.measure_failed_falling_back_to_single_pass",
            rc=proc.returncode,
        )
        af = f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=summary"

    apply_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(wav_path),
        "-af",
        af,
        "-ar",
        str(export_sample_rate),
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(out_tmp),
    ]
    proc2 = await asyncio.create_subprocess_exec(
        *apply_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err2 = await proc2.communicate()
    if proc2.returncode != 0 or not out_tmp.exists() or out_tmp.stat().st_size < 1024:
        log.warning(
            "audiobook.master_loudnorm.apply_failed",
            rc=proc2.returncode,
            stderr=err2.decode("utf-8", errors="replace")[:200],
        )
        out_tmp.unlink(missing_ok=True)
        return

    try:
        out_tmp.replace(wav_path)
    except OSError as exc:
        log.warning(
            "audiobook.master_loudnorm.replace_failed",
            error=str(exc)[:120],
        )
        out_tmp.unlink(missing_ok=True)
        return

    log.info(
        "audiobook.master_loudnorm.applied",
        target_i=target_i,
        target_tp=target_tp,
        target_lra=target_lra,
        two_pass=measurements is not None,
    )
