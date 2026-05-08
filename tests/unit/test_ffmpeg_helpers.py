"""Tests for FFmpegService pure helpers (F-Tst-03 follow-up).

The existing ``test_ffmpeg.py`` covers ``_build_assembly_command`` and
the concat-file format. This module covers the remaining pure builders
that don't need ffmpeg on PATH:

  * ``_build_audio_filtergraph`` — voice / music / sidechain / limiter
    branches; the chain that decides what the final mastered audio
    sounds like.
  * ``_build_watermark_filter`` — None paths, position map, opacity
    clamping, paths-with-colons escaping.
  * ``_resolve_xfade_transition`` — random / variety / literal / fallback.
  * ``_is_image`` — extension recognition.
  * ``_build_video_concat_command`` — smoke for argv shape + captions
    + music wiring (concat-video-clips path used by the long-form
    Wan-2.6 video pipeline).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from drevalis.services.ffmpeg import (
    AssemblyConfig,
    AudioMixConfig,
    FFmpegService,
)
from drevalis.services.ffmpeg._monolith import XFADE_TRANSITIONS


@pytest.fixture
def svc() -> FFmpegService:
    return FFmpegService()


# ── _build_audio_filtergraph ─────────────────────────────────────────


class TestBuildAudioFiltergraph:
    def test_voice_only_no_music_no_filters(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(
            voice_normalize=False,
            voice_compressor=False,
            voice_eq=False,
            master_limiter=False,
        )
        segments, out_label = svc._build_audio_filtergraph("1:a", None, cfg)
        # No EQ / compressor / loudnorm / limiter — single passthrough segment.
        assert len(segments) == 1
        assert "acopy" in segments[0]
        assert out_label == "vo_processed"

    def test_voice_filters_emit_chain(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(
            voice_normalize=True,
            voice_compressor=True,
            voice_eq=True,
            master_limiter=False,
        )
        segments, _ = svc._build_audio_filtergraph("1:a", None, cfg)
        chain = segments[0]
        assert "highpass=f=80" in chain
        assert "equalizer=f=3000" in chain
        assert "acompressor" in chain
        assert "loudnorm=I=-14.0" in chain

    def test_master_limiter_emits_alimiter_segment(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(
            voice_normalize=False,
            voice_compressor=False,
            voice_eq=False,
            master_limiter=True,
            master_true_peak=-1.0,
        )
        segments, out_label = svc._build_audio_filtergraph("1:a", None, cfg)
        assert any("alimiter=limit=" in s for s in segments)
        assert out_label == "amaster"

    def test_master_limiter_off_returns_pre_limiter_label(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(
            voice_normalize=False,
            voice_compressor=False,
            voice_eq=False,
            master_limiter=False,
        )
        _, out_label = svc._build_audio_filtergraph("1:a", None, cfg)
        assert out_label != "amaster"
        assert out_label == "vo_processed"

    def test_music_branch_emits_sidechain_and_amix(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig()
        segments, out_label = svc._build_audio_filtergraph("1:a", "2:a", cfg)
        joined = ";".join(segments)
        assert "asplit=2[vo_sc][vo_mix]" in joined
        assert "sidechaincompress" in joined
        assert "amix=inputs=2" in joined
        # Limiter on by default → final label is amaster.
        assert out_label == "amaster"

    def test_music_volume_db_passed_through(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(music_volume_db=-21.0)
        segments, _ = svc._build_audio_filtergraph("1:a", "2:a", cfg)
        joined = ";".join(segments)
        assert "volume=-21.0dB" in joined

    def test_music_reverb_emits_aecho(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(music_reverb=True, music_reverb_delay=50, music_reverb_decay=0.5)
        segments, _ = svc._build_audio_filtergraph("1:a", "2:a", cfg)
        joined = ";".join(segments)
        assert "aecho=0.8:0.8:50:0.5" in joined

    def test_music_reverb_disabled_omits_aecho(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(music_reverb=False)
        segments, _ = svc._build_audio_filtergraph("1:a", "2:a", cfg)
        assert all("aecho" not in s for s in segments)

    def test_music_low_pass_emits_lowpass(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(music_low_pass=8000)
        segments, _ = svc._build_audio_filtergraph("1:a", "2:a", cfg)
        joined = ";".join(segments)
        assert "lowpass=f=8000" in joined

    def test_music_low_pass_zero_omits_lowpass(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(music_low_pass=0)
        segments, _ = svc._build_audio_filtergraph("1:a", "2:a", cfg)
        assert all("lowpass" not in s for s in segments)

    def test_sidechain_uses_configured_ratio(self, svc: FFmpegService) -> None:
        cfg = AudioMixConfig(duck_ratio=4.5, duck_threshold=0.07)
        segments, _ = svc._build_audio_filtergraph("1:a", "2:a", cfg)
        joined = ";".join(segments)
        assert "ratio=4.5" in joined
        assert "threshold=0.07" in joined

    def test_voice_label_brackets_omitted_in_input(self, svc: FFmpegService) -> None:
        # The contract: caller passes "1:a" (no brackets); the builder
        # is responsible for bracketing it. A double-bracket regression
        # would produce ``[[1:a]]`` — guard against that.
        cfg = AudioMixConfig(voice_eq=False, voice_compressor=False, voice_normalize=False)
        segments, _ = svc._build_audio_filtergraph("3:a", None, cfg)
        assert "[3:a]" in segments[0]
        assert "[[" not in segments[0]


# ── _build_watermark_filter ──────────────────────────────────────────


class TestBuildWatermarkFilter:
    def test_no_watermark_path_returns_none(self) -> None:
        cfg = AssemblyConfig()
        assert FFmpegService._build_watermark_filter(cfg, "in", "out") is None

    def test_missing_watermark_file_returns_none(self, tmp_path: Path) -> None:
        cfg = AssemblyConfig(watermark_path=str(tmp_path / "nope.png"))
        assert FFmpegService._build_watermark_filter(cfg, "in", "out") is None

    def test_existing_watermark_returns_filter(self, tmp_path: Path) -> None:
        wm = tmp_path / "logo.png"
        wm.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        cfg = AssemblyConfig(watermark_path=str(wm))
        out = FFmpegService._build_watermark_filter(cfg, "vin", "vout")
        assert out is not None
        assert "movie=" in out
        assert "[vin][wm_overlay]overlay=" in out
        assert "[vout]" in out

    def test_default_corner_is_bottom_right(self, tmp_path: Path) -> None:
        wm = tmp_path / "logo.png"
        wm.write_bytes(b"\x00" * 200)
        cfg = AssemblyConfig(watermark_path=str(wm))  # default position
        out = FFmpegService._build_watermark_filter(cfg, "vin", "vout")
        assert out is not None
        # bottom-right uses W-w / H-h coordinates.
        assert "W-w-" in out and "H-h-" in out

    @pytest.mark.parametrize(
        ("corner", "expected_x_token", "expected_y_token"),
        [
            ("bottom-right", "W-w", "H-h"),
            ("bottom-left", ":H-h", "H-h"),  # x is the margin literal
            ("top-right", "W-w", ":30"),
            ("top-left", ":30", ":30"),
        ],
    )
    def test_position_map(
        self,
        tmp_path: Path,
        corner: str,
        expected_x_token: str,
        expected_y_token: str,
    ) -> None:
        wm = tmp_path / "logo.png"
        wm.write_bytes(b"\x00" * 100)
        cfg = AssemblyConfig(watermark_path=str(wm), watermark_position=corner)
        out = FFmpegService._build_watermark_filter(cfg, "in", "out")
        assert out is not None
        assert expected_x_token in out
        assert expected_y_token in out

    def test_unknown_corner_falls_back_to_bottom_right(self, tmp_path: Path) -> None:
        wm = tmp_path / "logo.png"
        wm.write_bytes(b"\x00" * 100)
        cfg = AssemblyConfig(watermark_path=str(wm), watermark_position="middle")
        out = FFmpegService._build_watermark_filter(cfg, "in", "out")
        assert out is not None
        assert "W-w-" in out and "H-h-" in out

    def test_opacity_clamped(self, tmp_path: Path) -> None:
        wm = tmp_path / "logo.png"
        wm.write_bytes(b"\x00" * 100)
        # Above 1.0 → clamped to 1.0
        cfg = AssemblyConfig(watermark_path=str(wm), watermark_opacity=2.5)
        out = FFmpegService._build_watermark_filter(cfg, "in", "out")
        assert out is not None
        assert "aa=1.0000" in out

    def test_opacity_clamped_negative(self, tmp_path: Path) -> None:
        wm = tmp_path / "logo.png"
        wm.write_bytes(b"\x00" * 100)
        cfg = AssemblyConfig(watermark_path=str(wm), watermark_opacity=-0.3)
        out = FFmpegService._build_watermark_filter(cfg, "in", "out")
        assert out is not None
        assert "aa=0.0000" in out

    def test_path_colons_escaped_in_movie_arg(self, tmp_path: Path) -> None:
        wm = tmp_path / "logo.png"
        wm.write_bytes(b"\x00" * 100)
        cfg = AssemblyConfig(watermark_path=str(wm))
        out = FFmpegService._build_watermark_filter(cfg, "in", "out")
        assert out is not None
        # The movie= path argument must escape every ``:`` as ``\:``
        # so ffmpeg's option parser doesn't treat the drive-letter
        # colon (``C:``) as a key=value separator.
        movie_arg = out.split("movie='", 1)[1].split("'", 1)[0]
        # Either no colon (Linux temp path) or every colon escaped.
        assert ":" not in movie_arg or "\\:" in movie_arg
        # And no raw backslash separators — ffmpeg movie= filter
        # requires forward slashes regardless of platform.
        assert "\\\\" not in movie_arg


# ── _resolve_xfade_transition ────────────────────────────────────────


class TestResolveXfadeTransition:
    def test_fade_returns_fade(self) -> None:
        assert FFmpegService._resolve_xfade_transition(0, "fade", None) == "fade"

    def test_random_returns_value_from_pool(self) -> None:
        out = FFmpegService._resolve_xfade_transition(7, "random", base_seed=42)
        assert out in XFADE_TRANSITIONS

    def test_random_is_deterministic_with_seed(self) -> None:
        a = FFmpegService._resolve_xfade_transition(3, "random", base_seed=99)
        b = FFmpegService._resolve_xfade_transition(3, "random", base_seed=99)
        assert a == b

    def test_random_differs_between_seeds(self) -> None:
        # Pin two seeds that don't accidentally collide. With 12
        # transitions the chance of equal output across two seeds is
        # 1/12; using two adjacent indices and different seeds keeps
        # this stable.
        results = {
            FFmpegService._resolve_xfade_transition(i, "random", base_seed=s)
            for i in range(5)
            for s in (1, 999)
        }
        # Should hit more than one transition value across the matrix.
        assert len(results) > 1

    def test_variety_round_robins_through_pool(self) -> None:
        seq = [FFmpegService._resolve_xfade_transition(i, "variety", None) for i in range(13)]
        # First entry of round 2 (idx=12) must equal idx=0.
        assert seq[12] == seq[0]
        # All values are in the canonical pool.
        assert all(s in XFADE_TRANSITIONS for s in seq)

    def test_literal_transition_passes_through(self) -> None:
        assert FFmpegService._resolve_xfade_transition(0, "wipeleft", None) == "wipeleft"

    def test_unknown_token_falls_back_to_fade(self) -> None:
        assert FFmpegService._resolve_xfade_transition(0, "swirlblast", None) == "fade"


# ── _is_image ────────────────────────────────────────────────────────


class TestIsImage:
    @pytest.mark.parametrize(
        "filename",
        ["x.png", "x.jpg", "x.JPEG", "x.webp", "x.bmp", "x.tiff", "x.tif"],
    )
    def test_recognised_image_extensions(self, filename: str) -> None:
        assert FFmpegService._is_image(Path(filename)) is True

    @pytest.mark.parametrize(
        "filename",
        ["x.mp4", "x.mov", "x.wav", "x.txt", "x", "x.gif"],  # gif intentionally excluded
    )
    def test_non_image_extensions(self, filename: str) -> None:
        assert FFmpegService._is_image(Path(filename)) is False

    def test_extension_match_is_case_insensitive(self) -> None:
        assert FFmpegService._is_image(Path("LOGO.PNG")) is True
        assert FFmpegService._is_image(Path("photo.JpG")) is True


# ── _build_video_concat_command ──────────────────────────────────────


class TestBuildVideoConcatCommand:
    def test_basic_invocation_shape(self, svc: FFmpegService) -> None:
        cmd = svc._build_video_concat_command(
            concat_file=Path("/tmp/clips.txt"),
            voiceover_path=Path("/tmp/vo.wav"),
            output_path=Path("/tmp/out.mp4"),
            captions_path=None,
            background_music_path=None,
            audio_mix_config=AudioMixConfig(
                voice_normalize=False, voice_compressor=False, voice_eq=False
            ),
            config=AssemblyConfig(),
        )
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        # concat demuxer over the clip list
        assert "concat" in cmd
        # Voiceover input present
        assert any(str(Path("/tmp/vo.wav")) == p for p in cmd)
        # Output last
        assert cmd[-1] == str(Path("/tmp/out.mp4"))

    def test_captions_burn_in_emitted_in_filter_complex(self, svc: FFmpegService) -> None:
        cmd = svc._build_video_concat_command(
            concat_file=Path("/tmp/clips.txt"),
            voiceover_path=Path("/tmp/vo.wav"),
            output_path=Path("/tmp/out.mp4"),
            captions_path=Path("/tmp/cap.ass"),
            background_music_path=None,
            audio_mix_config=AudioMixConfig(),
            config=AssemblyConfig(),
        )
        fc = cmd[cmd.index("-filter_complex") + 1]
        assert "subtitles=" in fc

    def test_music_input_added(self, svc: FFmpegService) -> None:
        cmd = svc._build_video_concat_command(
            concat_file=Path("/tmp/clips.txt"),
            voiceover_path=Path("/tmp/vo.wav"),
            output_path=Path("/tmp/out.mp4"),
            captions_path=None,
            background_music_path=Path("/tmp/bgm.mp3"),
            audio_mix_config=AudioMixConfig(),
            config=AssemblyConfig(),
        )
        # Music file appears as one of the -i args.
        assert any(str(Path("/tmp/bgm.mp3")) == p for p in cmd)
        # Filter complex carries the sidechain mix.
        fc = cmd[cmd.index("-filter_complex") + 1]
        assert "sidechaincompress" in fc

    def test_video_codec_and_preset_propagated(self, svc: FFmpegService) -> None:
        cfg = AssemblyConfig(video_codec="libx265", preset="slow", video_bitrate="6M")
        cmd = svc._build_video_concat_command(
            concat_file=Path("/tmp/clips.txt"),
            voiceover_path=Path("/tmp/vo.wav"),
            output_path=Path("/tmp/out.mp4"),
            captions_path=None,
            background_music_path=None,
            audio_mix_config=AudioMixConfig(),
            config=cfg,
        )
        assert "libx265" in cmd
        assert "slow" in cmd
        assert "6M" in cmd
