"""Tests for the editor render's pure per-clip FFmpeg filter builders (ADR 003).

These translate the editor's colour filters + opacity fades into a ``-vf``
chain. Pure string builders — no ffmpeg on PATH needed — so the filtergraph is
verified here and the worker just hands the result to ``trim_video``.
"""

from __future__ import annotations

from drevalis.services.ffmpeg import build_clip_vf, color_eq, fade_chain


class TestColorEq:
    def test_none_when_absent_or_neutral(self) -> None:
        assert color_eq(None) is None
        assert color_eq({}) is None
        assert color_eq({"brightness": 1, "contrast": 1, "saturation": 1}) is None

    def test_brightness_maps_multiplicative_to_additive_clamped(self) -> None:
        # CSS brightness 1.2 → eq additive +0.2
        assert color_eq({"brightness": 1.2}) == "eq=brightness=0.2"
        # clamped to [-1, 1]
        assert color_eq({"brightness": 5}) == "eq=brightness=1"

    def test_contrast_and_saturation_pass_through(self) -> None:
        assert color_eq({"contrast": 1.5}) == "eq=contrast=1.5"
        assert color_eq({"saturation": 0}) == "eq=saturation=0"

    def test_combines_in_order(self) -> None:
        out = color_eq({"brightness": 1.1, "contrast": 1.2, "saturation": 0.5})
        assert out == "eq=brightness=0.1:contrast=1.2:saturation=0.5"


class TestFadeChain:
    def test_empty_without_fades(self) -> None:
        assert fade_chain(None, None, 30, 4.0) == []
        assert fade_chain(0, 0, 30, 4.0) == []

    def test_fade_in_only(self) -> None:
        assert fade_chain(15, 0, 30, 4.0) == ["fade=t=in:st=0:d=0.5"]

    def test_fade_out_timed_to_clip_end(self) -> None:
        # 30-frame fade @ 30fps = 1s, on a 4s clip → starts at 3s
        assert fade_chain(0, 30, 30, 4.0) == ["fade=t=out:st=3:d=1"]

    def test_both(self) -> None:
        assert fade_chain(15, 30, 30, 4.0) == [
            "fade=t=in:st=0:d=0.5",
            "fade=t=out:st=3:d=1",
        ]

    def test_guards_bad_fps(self) -> None:
        assert fade_chain(15, 15, 0, 4.0) == []


class TestBuildClipVf:
    def test_none_when_clip_has_no_effects(self) -> None:
        assert build_clip_vf({"in_s": 0, "out_s": 4}, 30) is None

    def test_combines_eq_then_fades(self) -> None:
        clip = {"in_s": 0.0, "out_s": 4.0, "filters": {"contrast": 1.5}, "fadeInFrames": 15}
        assert build_clip_vf(clip, 30) == "eq=contrast=1.5,fade=t=in:st=0:d=0.5"

    def test_fade_out_uses_source_window_duration(self) -> None:
        # duration = out_s - in_s = 2s; 30f fade @30fps = 1s → st=1
        clip = {"in_s": 1.0, "out_s": 3.0, "fadeOutFrames": 30}
        assert build_clip_vf(clip, 30) == "fade=t=out:st=1:d=1"
