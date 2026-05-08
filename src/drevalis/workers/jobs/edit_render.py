"""Render-from-edit-session worker.

Reads a ``video_edit_sessions.timeline`` JSON and drives FFmpeg to
produce a new ``video`` asset for the episode. Pragmatic first pass:

1. For each video-track clip, trim the source file to (in_s, out_s)
   via ``FFmpegService.trim_video``.
2. Concat all trimmed clips in timeline order via
   ``FFmpegService.concat_videos``.
3. Overlay captions ASS file on top when present.
4. Mix voice (+ optional music with sidechain ducking) via the
   standard AudioMixConfig path on ``assemble_video``.
5. Write ``episodes/{id}/output/final_edit.mp4`` and insert a new
   ``MediaAsset(type="video")`` row.

Overlays + advanced effects are scoped out of this first revision —
the frontend produces them, and the render pass ignores non-video
tracks it doesn't recognise. Future revs expand the filtergraph.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def render_from_edit(
    ctx: dict[str, Any], episode_id: str, proxy: bool = False
) -> dict[str, Any]:
    """Produce an MP4 from the episode's edit session.

    When ``proxy=True`` the output is 480p with faster preset — this is
    the "preview" flow the editor uses so users can scrub with overlays
    mixed in without waiting for the full-quality render.
    """
    from drevalis.core.deps import get_settings
    from drevalis.repositories.episode import EpisodeRepository
    from drevalis.repositories.media_asset import MediaAssetRepository
    from drevalis.repositories.video_edit_session import VideoEditSessionRepository
    from drevalis.services.ffmpeg import FFmpegService
    from drevalis.services.storage import LocalStorage

    log = logger.bind(episode_id=episode_id, job="render_from_edit", proxy=proxy)
    log.info("render_from_edit_start")

    settings = get_settings()
    session_factory = ctx["session_factory"]
    storage: LocalStorage = ctx["storage"]
    ffmpeg: FFmpegService = ctx["ffmpeg_service"]

    parsed_id = uuid.UUID(episode_id)

    async with session_factory() as session:
        ep_repo = EpisodeRepository(session)
        edit_repo = VideoEditSessionRepository(session)
        asset_repo = MediaAssetRepository(session)

        edit_session = await edit_repo.get_by_episode(parsed_id)
        if edit_session is None:
            log.warning("no_edit_session")
            return {"status": "no_session"}
        episode = await ep_repo.get_by_id(parsed_id)
        if episode is None:
            log.warning("episode_missing")
            return {"status": "episode_missing"}

        timeline = edit_session.timeline or {}
        tracks: list[dict[str, Any]] = timeline.get("tracks") or []
        video_track = next((t for t in tracks if t.get("id") == "video"), None)
        if not video_track or not video_track.get("clips"):
            log.warning("no_video_clips")
            return {"status": "empty_timeline"}

        episode_path = await storage.get_episode_path(parsed_id)
        work_dir = episode_path / "edit_tmp"
        work_dir.mkdir(parents=True, exist_ok=True)
        output_dir = episode_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. Trim each clip to its (in_s, out_s) window ────────────
        trimmed_paths: list[Path] = []
        for i, clip in enumerate(video_track["clips"]):
            asset_path = clip.get("asset_path")
            if not asset_path:
                continue
            src = Path(settings.storage_base_path) / asset_path
            if not src.exists():
                log.warning("clip_source_missing", index=i, path=str(src))
                continue
            in_s = float(clip.get("in_s") or 0.0)
            out_s = float(clip.get("out_s") or 0.0)
            dest = work_dir / f"clip_{i:03d}.mp4"
            if out_s > in_s:
                await ffmpeg.trim_video(src, dest, start_seconds=in_s, end_seconds=out_s)
                trimmed_paths.append(dest)
            else:
                # Image or zero-duration — copy as-is; ffmpeg concat
                # needs a real video later.
                trimmed_paths.append(src)

        if not trimmed_paths:
            log.warning("no_trimmed_clips")
            return {"status": "empty_output"}

        # ── 2. Concat into one video ─────────────────────────────────
        intermediate = work_dir / "stitched.mp4"
        await ffmpeg.concat_videos(trimmed_paths, intermediate)

        # ── 2a. Apply overlay objects (text / shape / image) ─────────
        overlay_track = next((t for t in tracks if t.get("id") == "overlay"), None)
        if overlay_track and overlay_track.get("clips"):
            with_overlays = work_dir / "overlaid.mp4"
            await _apply_overlays(
                ffmpeg_path=settings.ffmpeg_path,
                input_path=intermediate,
                output_path=with_overlays,
                overlays=overlay_track["clips"],
                storage_base=Path(settings.storage_base_path),
            )
            intermediate = with_overlays

        # ── 2b. Apply per-track audio envelopes (volume automation) ──
        envelopes = _collect_audio_envelopes(tracks)
        if envelopes:
            with_env = work_dir / "enveloped.mp4"
            await _apply_audio_envelopes(
                ffmpeg_path=settings.ffmpeg_path,
                input_path=intermediate,
                output_path=with_env,
                envelopes=envelopes,
            )
            intermediate = with_env

        # ── 3. Final output. Proxy path downscales to 480 wide and
        #     writes proxy.mp4 next to the high-quality final_edit.mp4.
        if proxy:
            final_out = output_dir / "proxy.mp4"
            if final_out.exists():
                final_out.unlink()
            # Downscale + faster preset in one FFmpeg pass.
            proxy_cmd = [
                settings.ffmpeg_path,
                "-y",
                "-i",
                str(intermediate),
                "-vf",
                "scale=-2:480",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-b:v",
                "900k",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(final_out),
            ]
            proc = await asyncio.create_subprocess_exec(
                *proxy_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"proxy downscale failed: {err.decode(errors='replace')[:400]}")
        else:
            final_out = output_dir / "final_edit.mp4"
            if final_out.exists():
                final_out.unlink()
            intermediate.replace(final_out)

        # Register the new asset. Keep the old one — the UI can show
        # both in "Previous renders" if needed. Proxy preview uses a
        # distinct asset_type so the UI can choose which to display.
        rel = final_out.relative_to(Path(storage.base_path)).as_posix()
        await asset_repo.create(
            episode_id=parsed_id,
            asset_type="video_proxy" if proxy else "video",
            file_path=rel,
            file_size_bytes=final_out.stat().st_size,
        )
        if not proxy:
            await edit_repo.update(
                edit_session.id,
                last_rendered_at=datetime.now(tz=UTC),
            )
        await session.commit()

    log.info("render_from_edit_done", output=str(final_out))
    return {"episode_id": episode_id, "status": "done", "output": rel}


# ── Overlay rendering ────────────────────────────────────────────────


def _escape_drawtext(text: str) -> str:
    """Escape single quotes, colons, backslashes, percent for drawtext."""
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def _color_to_ffmpeg(color: str | None, default: str = "white") -> str:
    """Accept '#RRGGBB', 'white', 'rgba(r,g,b,a)'. Pass through to FFmpeg."""
    if not color:
        return default
    c = color.strip()
    if c.startswith("#") and len(c) == 7:
        return f"0x{c[1:]}"
    return c


def _build_overlay_filters(
    overlays: list[dict[str, Any]], storage_base: Path
) -> tuple[list[str], list[tuple[int, Path]]]:
    """Compose a list of filterchain fragments that can be chained by
    comma onto the main video stream, plus a list of extra input paths
    needed (``(input_index, path)`` tuples) for image overlays.

    ``in_label`` / ``out_label`` are wired by the caller so the
    fragments can be concatenated into one filter_complex.
    """
    fragments: list[str] = []
    extra_inputs: list[tuple[int, Path]] = []
    next_input_idx = 1  # 0 = the stitched base video

    for o in overlays:
        kind = o.get("kind")
        start_s = float(o.get("start_s") or 0.0)
        end_s = float(o.get("end_s") or start_s + 1.0)
        enable = f"between(t,{start_s:.3f},{end_s:.3f})"
        x = o.get("x", "(w-text_w)/2")  # ffmpeg expressions accepted
        y = o.get("y", "h-200")
        if kind == "text":
            text = _escape_drawtext(str(o.get("text") or ""))
            size = int(o.get("font_size") or 56)
            color = _color_to_ffmpeg(o.get("color"), "white")
            box = "1" if o.get("box") else "0"
            box_color = _color_to_ffmpeg(o.get("box_color"), "black@0.6")
            fragments.append(
                f"drawtext=text='{text}':fontsize={size}:fontcolor={color}"
                f":x={x}:y={y}:box={box}:boxcolor={box_color}:boxborderw=20"
                f":enable='{enable}'"
            )
        elif kind == "shape" and (o.get("shape") == "rect" or not o.get("shape")):
            w = o.get("w", 200)
            h = o.get("h", 60)
            color = _color_to_ffmpeg(o.get("color"), "white@0.5")
            fragments.append(
                f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill:enable='{enable}'"
            )
        elif kind == "image":
            path = o.get("asset_path")
            if not path:
                continue
            abs_path = storage_base / path
            if not abs_path.exists():
                continue
            extra_inputs.append((next_input_idx, abs_path))
            fragments.append(
                f"[{next_input_idx}:v]format=rgba,setpts=PTS-STARTPTS[ovl{next_input_idx}]"
            )
            fragments.append(f"overlay=x={x}:y={y}:enable='{enable}':shortest=0")
            next_input_idx += 1
    return fragments, extra_inputs


async def _apply_overlays(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    overlays: list[dict[str, Any]],
    storage_base: Path,
) -> None:
    """Run one FFmpeg pass adding drawtext / drawbox / overlay filters.

    Keeps audio untouched (``-c:a copy``). Re-encodes video — drawtext
    needs a pixel-aware codec.
    """
    # Separate image overlays (need extra -i inputs) from pure filters.
    # For this first pass we keep it straightforward: run drawtext /
    # drawbox in a single -vf chain, and overlay= as a separate pass per
    # image overlay. That keeps the graph readable and avoids cross-
    # contamination of enable='…' expressions.
    drawtext_parts: list[str] = []
    image_overlays: list[dict[str, Any]] = []
    for o in overlays:
        if o.get("kind") in ("text", "shape"):
            f, _extras = _build_overlay_filters([o], storage_base)
            drawtext_parts.extend(f)
        elif o.get("kind") == "image":
            image_overlays.append(o)

    cur_in = input_path

    if drawtext_parts:
        pass1 = output_path.with_name(output_path.stem + "_p1.mp4")
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            str(cur_in),
            "-vf",
            ",".join(drawtext_parts),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-b:v",
            "4M",
            "-c:a",
            "copy",
            str(pass1),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"overlay drawtext failed: {err.decode(errors='replace')[:400]}")
        cur_in = pass1

    for o in image_overlays:
        path = o.get("asset_path")
        if not path:
            continue
        abs_path = storage_base / path
        if not abs_path.exists():
            continue
        start_s = float(o.get("start_s") or 0.0)
        end_s = float(o.get("end_s") or start_s + 1.0)
        x = o.get("x", "(W-w)/2")
        y = o.get("y", "H/2")
        pass_out = output_path.with_name(output_path.stem + f"_img{image_overlays.index(o)}.mp4")
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            str(cur_in),
            "-i",
            str(abs_path),
            "-filter_complex",
            f"[1:v]format=rgba[ovl];[0:v][ovl]overlay=x={x}:y={y}"
            f":enable='between(t,{start_s:.3f},{end_s:.3f})'[out]",
            "-map",
            "[out]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-b:v",
            "4M",
            "-c:a",
            "copy",
            str(pass_out),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"overlay image failed: {err.decode(errors='replace')[:400]}")
        cur_in = pass_out

    # Final move.
    if cur_in != output_path:
        if output_path.exists():
            output_path.unlink()
        cur_in.replace(output_path)


# ── Audio envelope rendering ────────────────────────────────────────


def _collect_audio_envelopes(
    tracks: list[dict[str, Any]],
) -> list[tuple[float, float]]:
    """Extract ``envelope`` keyframes from any audio track clip.

    Returns a flat list of ``(t, gain_db)`` tuples — the first audio
    track with an envelope wins (multi-track independent envelopes
    would require a proper filter_complex and are deferred).
    """
    for t in tracks:
        if t.get("kind") != "audio":
            continue
        for c in t.get("clips") or []:
            env = c.get("envelope") or []
            if len(env) >= 2:
                return [(float(a), float(b)) for a, b in env]
    return []


async def _apply_audio_envelopes(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    envelopes: list[tuple[float, float]],
) -> None:
    """Apply a piecewise linear volume envelope to the audio stream.

    Uses FFmpeg ``volume=eval=frame:volume=<expr>`` with nested
    ``if(between(...))`` fragments. For each pair of adjacent points
    the gain is linearly interpolated. Points are in seconds /
    decibels; gain is converted to linear amplitude at render time.
    """
    # Build the piecewise expression.
    if not envelopes:
        return
    points = sorted(envelopes, key=lambda p: p[0])
    segments: list[str] = []
    for i in range(len(points) - 1):
        t0, db0 = points[i]
        t1, db1 = points[i + 1]
        if t1 <= t0:
            continue
        # linear interp of dB, converted to amplitude: 10^(db/20)
        # gain(t) = 10^((db0 + (t-t0)/(t1-t0) * (db1-db0)) / 20)
        seg = (
            f"if(between(t,{t0:.3f},{t1:.3f}),"
            f"pow(10,({db0:.3f}+(t-{t0:.3f})/({t1 - t0:.3f})*({db1 - db0:.3f}))/20)"
        )
        segments.append(seg)
    # Tail: after the last point the gain stays at the last dB.
    tail_t, tail_db = points[-1]
    tail = f"if(gte(t,{tail_t:.3f}),pow(10,{tail_db:.3f}/20)"
    # Head: before the first point, gain = first dB.
    head_t, head_db = points[0]
    head = f"if(lt(t,{head_t:.3f}),pow(10,{head_db:.3f}/20),"
    expr = head + ",".join(segments) + tail + "," + ")" * (len(segments) + 1)

    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-af",
        f"volume=eval=frame:volume='{expr}'",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    import asyncio as _asyncio

    proc = await _asyncio.create_subprocess_exec(
        *cmd,
        stdout=_asyncio.subprocess.DEVNULL,
        stderr=_asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"envelope render failed: {err.decode(errors='replace')[:400]}")
