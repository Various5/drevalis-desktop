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

from typing import Any


def _fmt(n: float) -> str:
    """Compact fixed-point — avoids sci-notation / trailing noise in filters."""
    return f"{n:.4f}".rstrip("0").rstrip(".") or "0"


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


__all__ = ["color_eq", "fade_chain", "build_clip_vf"]
