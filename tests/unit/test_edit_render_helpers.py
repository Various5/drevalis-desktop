"""Unit tests for the pure helpers in ``workers/jobs/edit_render.py``.

The full `render_from_edit` orchestration drives FFmpeg subprocess
work and warrants integration testing — the helpers below are pure
string/list manipulation and worth unit-pinning.

* `_escape_drawtext` escapes the four FFmpeg-meaningful characters
  (``\\``, ``:``, ``'``, ``%``) so user-provided overlay text can't
  break the filtergraph.
* `_color_to_ffmpeg` maps `#RRGGBB` → `0xRRGGBB`, passes through
  named colors and `rgba(...)` strings, falls back to a default
  when the input is None or empty.
* `_build_overlay_filters` produces:
  - `drawtext=` for kind=`"text"` with size/color/box defaults.
  - `drawbox=` for kind=`"shape"`.
  - Two-fragment image overlay (`[N:v]format=rgba` + `overlay=`)
    that increments the input index. Skips images with missing
    asset_path or files that don't exist on disk.
* `_collect_audio_envelopes` returns the first audio track's
  envelope; tracks of other kinds are skipped; `[]` returned when
  no track has a usable envelope (≥ 2 keyframes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from drevalis.workers.jobs.edit_render import (
    _build_overlay_filters,
    _collect_audio_envelopes,
    _color_to_ffmpeg,
    _escape_drawtext,
)

# ── _escape_drawtext ───────────────────────────────────────────────


class TestEscapeDrawtext:
    def test_escapes_all_four_metacharacters(self) -> None:
        # Pin the exact escape sequence — drawtext is fussy about
        # backslashes.
        out = _escape_drawtext("foo:bar's 100% \\done")
        assert "\\\\" in out  # literal backslash
        assert "\\:" in out
        assert "\\'" in out
        assert "\\%" in out

    def test_plain_text_unchanged(self) -> None:
        assert _escape_drawtext("Hello world") == "Hello world"


# ── _color_to_ffmpeg ───────────────────────────────────────────────


class TestColorToFfmpeg:
    def test_hex_to_0x(self) -> None:
        assert _color_to_ffmpeg("#FFAA00") == "0xFFAA00"

    def test_named_color_passes_through(self) -> None:
        assert _color_to_ffmpeg("red") == "red"

    def test_rgba_string_passes_through(self) -> None:
        # Pin: `rgba(...)` and `name@alpha` syntaxes go untouched so
        # FFmpeg's own parser handles them.
        assert _color_to_ffmpeg("white@0.5") == "white@0.5"

    def test_none_returns_default(self) -> None:
        assert _color_to_ffmpeg(None) == "white"
        assert _color_to_ffmpeg("") == "white"

    def test_custom_default(self) -> None:
        assert _color_to_ffmpeg(None, default="black@0.6") == "black@0.6"

    def test_short_hex_not_treated_as_hex(self) -> None:
        # Only `#RRGGBB` (7 chars) gets the `0x` prefix; `#RGB` is
        # passed through (FFmpeg won't handle it but at least we don't
        # silently lose data).
        assert _color_to_ffmpeg("#FFF") == "#FFF"


# ── _build_overlay_filters ─────────────────────────────────────────


class TestBuildOverlayFilters:
    def test_text_overlay_uses_defaults_and_enable_window(self, tmp_path: Path) -> None:
        overlays: list[dict[str, Any]] = [
            {
                "kind": "text",
                "text": "Hello",
                "start_s": 0.0,
                "end_s": 5.0,
            }
        ]
        fragments, extras = _build_overlay_filters(overlays, tmp_path)
        assert len(fragments) == 1
        f = fragments[0]
        assert "drawtext=text='Hello'" in f
        assert "fontsize=56" in f  # default
        assert "fontcolor=white" in f  # default
        assert "box=0" in f  # default
        # Pin the enable expression — FFmpeg semantics for time-windowed
        # overlays.
        assert "enable='between(t,0.000,5.000)'" in f
        assert extras == []

    def test_text_overlay_with_box_and_custom_color(self, tmp_path: Path) -> None:
        overlays: list[dict[str, Any]] = [
            {
                "kind": "text",
                "text": "Hi",
                "start_s": 1.0,
                "end_s": 2.0,
                "font_size": 80,
                "color": "#FF0000",
                "box": True,
                "box_color": "black@0.8",
            }
        ]
        fragments, _ = _build_overlay_filters(overlays, tmp_path)
        f = fragments[0]
        assert "fontsize=80" in f
        assert "fontcolor=0xFF0000" in f
        assert "box=1" in f
        assert "boxcolor=black@0.8" in f

    def test_shape_rect_emits_drawbox(self, tmp_path: Path) -> None:
        overlays: list[dict[str, Any]] = [
            {
                "kind": "shape",
                "shape": "rect",
                "start_s": 0.0,
                "end_s": 3.0,
                "x": 100,
                "y": 200,
                "w": 400,
                "h": 50,
                "color": "#00FF00",
            }
        ]
        fragments, extras = _build_overlay_filters(overlays, tmp_path)
        assert len(fragments) == 1
        assert "drawbox=" in fragments[0]
        assert "w=400" in fragments[0]
        assert "h=50" in fragments[0]
        assert "color=0x00FF00" in fragments[0]
        assert extras == []

    def test_shape_default_kind_treated_as_rect(self, tmp_path: Path) -> None:
        # Pin: a `kind=shape` entry without an explicit `shape` field
        # is treated as a rectangle (the v1 default), NOT silently
        # dropped.
        overlays: list[dict[str, Any]] = [{"kind": "shape", "start_s": 0, "end_s": 1}]
        fragments, _ = _build_overlay_filters(overlays, tmp_path)
        assert len(fragments) == 1
        assert "drawbox=" in fragments[0]

    def test_image_overlay_emits_two_fragments_and_extra_input(self, tmp_path: Path) -> None:
        # Stage a real image file the resolver will find.
        img = tmp_path / "logo.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        overlays: list[dict[str, Any]] = [
            {
                "kind": "image",
                "asset_path": "logo.png",
                "start_s": 0.0,
                "end_s": 4.0,
            }
        ]
        fragments, extras = _build_overlay_filters(overlays, tmp_path)
        # Pin: TWO fragments per image overlay — the format/setpts
        # prep pass and the actual `overlay=` pass.
        assert len(fragments) == 2
        assert "format=rgba" in fragments[0]
        assert "setpts=PTS-STARTPTS" in fragments[0]
        assert fragments[1].startswith("overlay=")
        # One extra input registered, indexed starting at 1
        # (index 0 is the base stitched video).
        assert len(extras) == 1
        assert extras[0][0] == 1
        assert extras[0][1] == img

    def test_image_overlay_missing_asset_path_skipped(self, tmp_path: Path) -> None:
        overlays: list[dict[str, Any]] = [{"kind": "image", "start_s": 0, "end_s": 1}]
        fragments, extras = _build_overlay_filters(overlays, tmp_path)
        assert fragments == []
        assert extras == []

    def test_image_overlay_file_missing_on_disk_skipped(self, tmp_path: Path) -> None:
        # Asset path provided, but the file doesn't exist (post-restore).
        overlays: list[dict[str, Any]] = [
            {
                "kind": "image",
                "asset_path": "nonexistent.png",
                "start_s": 0,
                "end_s": 1,
            }
        ]
        fragments, extras = _build_overlay_filters(overlays, tmp_path)
        assert fragments == []
        assert extras == []

    def test_input_index_increments_across_multiple_images(self, tmp_path: Path) -> None:
        a = tmp_path / "a.png"
        a.write_bytes(b"\x89PNG")
        b = tmp_path / "b.png"
        b.write_bytes(b"\x89PNG")

        overlays: list[dict[str, Any]] = [
            {
                "kind": "image",
                "asset_path": "a.png",
                "start_s": 0,
                "end_s": 2,
            },
            {
                "kind": "image",
                "asset_path": "b.png",
                "start_s": 2,
                "end_s": 5,
            },
        ]
        fragments, extras = _build_overlay_filters(overlays, tmp_path)
        # Two image overlays → 4 fragments (2 each) + 2 extra inputs.
        assert len(fragments) == 4
        assert [e[0] for e in extras] == [1, 2]

    def test_unknown_kind_skipped(self, tmp_path: Path) -> None:
        overlays: list[dict[str, Any]] = [{"kind": "lottie", "start_s": 0, "end_s": 1}]
        fragments, extras = _build_overlay_filters(overlays, tmp_path)
        # Unknown kinds are silently skipped — the route ignores
        # tracks it doesn't recognise so future timeline shapes don't
        # crash existing renders.
        assert fragments == []
        assert extras == []

    def test_default_end_s_is_one_second_after_start(self, tmp_path: Path) -> None:
        # Pin: when `end_s` is missing, the helper defaults it to
        # `start_s + 1`. Without this, a malformed overlay would emit
        # a degenerate `between(t, 5, 5)` enable expression.
        overlays: list[dict[str, Any]] = [
            {
                "kind": "text",
                "text": "x",
                "start_s": 5.0,
            }
        ]
        fragments, _ = _build_overlay_filters(overlays, tmp_path)
        # Resulting enable window is 5.000 → 6.000.
        assert "enable='between(t,5.000,6.000)'" in fragments[0]


# ── _collect_audio_envelopes ───────────────────────────────────────


class TestCollectAudioEnvelopes:
    def test_no_audio_tracks_returns_empty(self) -> None:
        tracks = [{"id": "video", "kind": "video", "clips": []}]
        assert _collect_audio_envelopes(tracks) == []

    def test_audio_track_without_envelope_returns_empty(self) -> None:
        tracks = [
            {
                "id": "voice",
                "kind": "audio",
                "clips": [{"asset_path": "x.wav"}],
            }
        ]
        assert _collect_audio_envelopes(tracks) == []

    def test_envelope_with_one_point_ignored(self) -> None:
        # Pin: a single keyframe isn't a piecewise function — needs ≥ 2.
        tracks = [
            {
                "id": "voice",
                "kind": "audio",
                "clips": [{"envelope": [[0.0, 0.0]]}],
            }
        ]
        assert _collect_audio_envelopes(tracks) == []

    def test_first_usable_envelope_wins(self) -> None:
        # Pin: when multiple audio tracks have envelopes, the FIRST one
        # is returned. Multi-track independent envelopes are out of
        # scope (would need filter_complex).
        tracks = [
            {
                "id": "voice",
                "kind": "audio",
                "clips": [{"envelope": [[0.0, 0.0], [10.0, -6.0]]}],
            },
            {
                "id": "music",
                "kind": "audio",
                "clips": [{"envelope": [[0.0, -14.0], [10.0, -20.0]]}],
            },
        ]
        out = _collect_audio_envelopes(tracks)
        # Voice envelope returned (first audio track), not music.
        assert out == [(0.0, 0.0), (10.0, -6.0)]

    def test_int_keyframes_coerced_to_float(self) -> None:
        # Defensive: timeline JSON often contains ints; pin coercion.
        tracks = [
            {
                "id": "voice",
                "kind": "audio",
                "clips": [{"envelope": [[0, -10], [5, -3]]}],
            }
        ]
        out = _collect_audio_envelopes(tracks)
        assert out == [(0.0, -10.0), (5.0, -3.0)]
        assert all(isinstance(p[0], float) for p in out)
