"""Pure FFmpeg per-clip filter builders for the editor render (ADR 003).

Translate the editor's per-clip visual properties — colour filters and opacity
fades, stored on the edit-timeline clip as extra keys by the frontend bridge —
into an FFmpeg ``-vf`` chain. Pure + unit-tested so the filtergraph is verified
without running FFmpeg; ``render_from_edit`` passes the result to ``trim_video``.

A clip with no editor effects yields ``None`` so its render path is unchanged.

Transform (scale / position / rotation) and transform keyframes are a further
increment: they need canvas compositing and time-varying expressions.
"""

from __future__ import annotations

import math
from typing import Any


def _fmt(n: float) -> str:
    """Compact fixed-point — avoids sci-notation / trailing noise in filters."""
    return f"{n:.4f}".rstrip("0").rstrip(".") or "0"


def _sample_keyframes(kfs: list[dict[str, Any]], frame: float) -> float | None:
    """Python mirror of the frontend's keyframe sampling (linear, holds ends)."""
    if not kfs:
        return None
    first = kfs[0]
    if frame <= first["frame"]:
        return float(first["value"])
    last = kfs[-1]
    if frame >= last["frame"]:
        return float(last["value"])
    for a, b in zip(kfs, kfs[1:]):
        if a["frame"] <= frame <= b["frame"]:
            span = b["frame"] - a["frame"]
            if span == 0:
                return float(b["value"])
            return float(a["value"]) + (float(b["value"]) - float(a["value"])) * (frame - a["frame"]) / span
    return float(last["value"])


def _lerp_expr(kfs: list[dict[str, Any]] | None, fps: float, default: float) -> str:
    """An FFmpeg expression in ``t`` (seconds) for a (possibly keyframed) value:
    piecewise-linear between keyframes, holding the first/last value at the ends.
    Keyframe frames are clip-relative; after trimming, the clip's ``t`` starts at 0.
    """
    if not kfs:
        return _fmt(default)
    if len(kfs) == 1:
        return _fmt(float(kfs[0]["value"]))
    pts = [(float(k["frame"]) / fps, float(k["value"])) for k in kfs]
    expr = _fmt(pts[-1][1])  # hold the last value
    for i in range(len(pts) - 2, -1, -1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        seg = f"({_fmt(v0)}+({_fmt(v1 - v0)})*(t-{_fmt(t0)})/({_fmt(t1 - t0)}))"
        expr = f"if(lt(t,{_fmt(t1)}),{seg},{expr})"
    # hold the first value before the first keyframe
    return f"if(lt(t,{_fmt(pts[0][0])}),{_fmt(pts[0][1])},{expr})"


def color_eq(filters: dict[str, Any] | None) -> str | None:
    """An ``eq`` filter from the editor's colour filters, or None if all neutral.

    CSS-style values (1 = unchanged) map to FFmpeg ``eq``:
      - brightness: CSS multiplicative (~1) → eq additive ``b - 1``, clamped [-1, 1]
        (an approximation — eq has no multiplicative brightness)
      - contrast / saturation: passed through (eq 1 = unchanged)
    """
    if not filters:
        return None
    parts: list[str] = []
    b = filters.get("brightness")
    c = filters.get("contrast")
    s = filters.get("saturation")
    if isinstance(b, (int, float)) and b != 1:
        parts.append(f"brightness={_fmt(max(-1.0, min(1.0, b - 1)))}")
    if isinstance(c, (int, float)) and c != 1:
        parts.append(f"contrast={_fmt(c)}")
    if isinstance(s, (int, float)) and s != 1:
        parts.append(f"saturation={_fmt(s)}")
    return f"eq={':'.join(parts)}" if parts else None


def fade_chain(
    fade_in_frames: float | None,
    fade_out_frames: float | None,
    fps: float,
    clip_duration_s: float,
) -> list[str]:
    """``fade`` filters for opacity in/out, timed to the clip's rendered duration."""
    out: list[str] = []
    if fps <= 0:
        return out
    if fade_in_frames and fade_in_frames > 0:
        out.append(f"fade=t=in:st=0:d={_fmt(fade_in_frames / fps)}")
    if fade_out_frames and fade_out_frames > 0:
        d = fade_out_frames / fps
        st = max(0.0, clip_duration_s - d)
        out.append(f"fade=t=out:st={_fmt(st)}:d={_fmt(d)}")
    return out


def build_clip_vf(clip: dict[str, Any], fps: float) -> str | None:
    """Per-clip ``-vf`` chain (colour grade + fades), or None when the clip has
    no editor effects — so an unaffected clip's render is byte-for-byte unchanged.
    """
    chain: list[str] = []

    eq = color_eq(clip.get("filters"))
    if eq:
        chain.append(eq)

    in_s = float(clip.get("in_s") or 0.0)
    out_s = float(clip.get("out_s") or 0.0)
    duration = max(0.0, out_s - in_s)
    chain += fade_chain(clip.get("fadeInFrames"), clip.get("fadeOutFrames"), fps, duration)

    return ",".join(chain) if chain else None


def transform_filtergraph(clip: dict[str, Any], fps: float) -> tuple[str, str] | None:
    """A ``-filter_complex`` body that scales / positions / rotates the clip over
    a black canvas of its own size, or None when the transform is identity.

    Uses only relative refs (overlay's ``W/H/w/h``) so no probed dimensions are
    needed. Position and rotation may be **keyframed** (as ``t`` expressions);
    scale is sampled at the clip start (the ``scale`` filter can't animate), and
    transform opacity is left to the fade path. Returns ``(body, out_label)``.
    """
    t = clip.get("transform") or {}
    kf = clip.get("transformKeyframes") or {}
    scale_kf = kf.get("scale")
    x_kf = kf.get("x")
    y_kf = kf.get("y")
    rot_kf = kf.get("rotation")

    scale = float(t.get("scale", 1) or 1)
    x = float(t.get("x", 0) or 0)
    y = float(t.get("y", 0) or 0)
    rot = float(t.get("rotation", 0) or 0)

    # Scale can't animate in the `scale` filter — hold the clip-start value.
    if scale_kf:
        sampled = _sample_keyframes(scale_kf, 0)
        if sampled is not None:
            scale = sampled

    keyframed = bool(scale_kf or x_kf or y_kf or rot_kf)
    if not keyframed and scale == 1 and x == 0 and y == 0 and rot == 0:
        return None

    if rot_kf:
        rot_a = f"({_lerp_expr(rot_kf, fps, rot)})*PI/180"
    else:
        rot_a = _fmt(rot * math.pi / 180)

    x_expr = _lerp_expr(x_kf, fps, x) if x_kf else _fmt(x)
    y_expr = _lerp_expr(y_kf, fps, y) if y_kf else _fmt(y)
    s = _fmt(scale)

    # Single quotes protect the commas inside if()/expressions from FFmpeg's
    # filtergraph comma separators.
    body = (
        "[0:v]split=2[base][fg];"
        "[base]drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill[bg];"
        f"[fg]scale=iw*{s}:ih*{s},rotate=a='{rot_a}':fillcolor=black[rot];"
        f"[bg][rot]overlay=x='(W-w)/2+({x_expr})*W':y='(H-h)/2+({y_expr})*H'[vout]"
    )
    return body, "[vout]"


__all__ = ["color_eq", "fade_chain", "build_clip_vf", "transform_filtergraph"]
