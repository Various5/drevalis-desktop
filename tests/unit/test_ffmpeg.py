"""Tests for FFmpegService -- command builder and assembly config."""

from __future__ import annotations

from pathlib import Path

import pytest

from drevalis.services.ffmpeg import (
    AssemblyConfig,
    AudioMixConfig,
    FFmpegService,
    SceneInput,
)


@pytest.fixture
def scenes() -> list[SceneInput]:
    """Return a list of SceneInput objects for testing."""
    return [
        SceneInput(image_path=Path("/tmp/scene_001.png"), duration_seconds=5.0),
        SceneInput(image_path=Path("/tmp/scene_002.png"), duration_seconds=6.0),
        SceneInput(image_path=Path("/tmp/scene_003.png"), duration_seconds=4.0),
    ]


class TestBuildAssemblyCommand:
    """Test the pure _build_assembly_command method."""

    def test_build_assembly_command_basic(
        self, ffmpeg_service: FFmpegService, scenes: list[SceneInput]
    ) -> None:
        """No music, no captions -- simplest case."""
        config = AssemblyConfig()
        # Voice mastering on by default but irrelevant here — basic test
        # asserts on inputs/outputs only.
        audio = AudioMixConfig(voice_normalize=False, voice_compressor=False, voice_eq=False)
        cmd = ffmpeg_service._build_assembly_command(
            concat_file=Path("/tmp/concat.txt"),
            voiceover_path=Path("/tmp/voiceover.wav"),
            output_path=Path("/tmp/output.mp4"),
            captions_path=None,
            background_music_path=None,
            audio_mix_config=audio,
            config=config,
        )

        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd

        # Concat demuxer input
        assert "-f" in cmd
        concat_idx = cmd.index("-f")
        assert cmd[concat_idx + 1] == "concat"

        # Voiceover input
        assert str(Path("/tmp/voiceover.wav")) in cmd

        # Current builder always uses -filter_complex (the legacy -vf
        # path was removed when the audio mastering chain landed; even
        # the no-music case now needs at least the [vo_processed] label
        # so the audio map points at a labelled stream).
        assert "-filter_complex" in cmd
        fc_value = cmd[cmd.index("-filter_complex") + 1]
        assert "scale=1080:1920" in fc_value
        assert "[vout]" in fc_value

        # Map labels rather than raw stream selectors.
        assert "[vout]" in cmd
        assert any("[vo_processed]" in part or "1:a" in part for part in cmd)

        # Output encoding
        assert "-c:v" in cmd
        assert "libx264" in cmd
        assert str(Path("/tmp/output.mp4")) in cmd

    def test_build_assembly_command_with_captions(self, ffmpeg_service: FFmpegService) -> None:
        """Captions path should produce a subtitles filter."""
        config = AssemblyConfig()
        audio = AudioMixConfig(voice_normalize=False, voice_compressor=False, voice_eq=False)
        cmd = ffmpeg_service._build_assembly_command(
            concat_file=Path("/tmp/concat.txt"),
            voiceover_path=Path("/tmp/voiceover.wav"),
            output_path=Path("/tmp/output.mp4"),
            captions_path=Path("/tmp/captions.ass"),
            background_music_path=None,
            audio_mix_config=audio,
            config=config,
        )

        # Subtitles filter is composed inside -filter_complex now.
        fc_value = cmd[cmd.index("-filter_complex") + 1]
        assert "subtitles=" in fc_value

    def test_build_assembly_command_with_music(self, ffmpeg_service: FFmpegService) -> None:
        """Background music should trigger filter_complex with audio mixing."""
        config = AssemblyConfig()
        audio = AudioMixConfig(
            music_volume_db=-15.0,
            voice_normalize=False,
            voice_compressor=False,
            voice_eq=False,
            master_limiter=False,
        )
        cmd = ffmpeg_service._build_assembly_command(
            concat_file=Path("/tmp/concat.txt"),
            voiceover_path=Path("/tmp/voiceover.wav"),
            output_path=Path("/tmp/output.mp4"),
            captions_path=None,
            background_music_path=Path("/tmp/music.mp3"),
            audio_mix_config=audio,
            config=config,
        )

        assert "-filter_complex" in cmd
        fc_idx = cmd.index("-filter_complex")
        fc_value = cmd[fc_idx + 1]

        # Audio mixing with volume adjustment + sidechain duck.
        assert "volume=-15" in fc_value
        assert "sidechaincompress" in fc_value or "amix" in fc_value

        # Music input present.
        assert str(Path("/tmp/music.mp3")) in cmd

        # Output mapping via filter labels. Current builder labels the
        # final mixed audio [amixed]; older versions used [aout].
        # Accept any [a*] label that's referenced by a -map.
        assert "[vout]" in cmd
        map_indices = [i for i, p in enumerate(cmd) if p == "-map"]
        audio_map_label = cmd[map_indices[1] + 1]
        assert audio_map_label.startswith("[a") or audio_map_label.endswith("]")

    def test_build_assembly_command_full(self, ffmpeg_service: FFmpegService) -> None:
        """Captions + music together."""
        config = AssemblyConfig(
            width=720,
            height=1280,
            fps=24,
            video_codec="libx265",
            preset="fast",
        )
        audio = AudioMixConfig(
            music_volume_db=-10.0,
            voice_normalize=False,
            voice_compressor=False,
            voice_eq=False,
            master_limiter=False,
        )
        cmd = ffmpeg_service._build_assembly_command(
            concat_file=Path("/tmp/concat.txt"),
            voiceover_path=Path("/tmp/voiceover.wav"),
            output_path=Path("/tmp/output.mp4"),
            captions_path=Path("/tmp/captions.ass"),
            background_music_path=Path("/tmp/music.mp3"),
            audio_mix_config=audio,
            config=config,
        )

        assert "-filter_complex" in cmd
        fc_idx = cmd.index("-filter_complex")
        fc_value = cmd[fc_idx + 1]

        # Video filters should include scaling, padding, fps, format, and subtitles
        assert "scale=720:1280" in fc_value
        assert "pad=720:1280" in fc_value
        assert "fps=24" in fc_value
        assert "subtitles=" in fc_value

        # Audio mixing
        assert "amix" in fc_value

        # Encoding with custom config
        assert "libx265" in cmd
        assert "fast" in cmd


class TestCreateConcatFileFormat:
    """Test the concat-demuxer file content."""

    async def test_create_concat_file_format(
        self, ffmpeg_service: FFmpegService, tmp_path: Path
    ) -> None:
        scenes = [
            SceneInput(image_path=Path("/images/scene_001.png"), duration_seconds=5.0),
            SceneInput(image_path=Path("/images/scene_002.png"), duration_seconds=3.5),
        ]

        concat_file = await ffmpeg_service._create_concat_file(scenes, tmp_path)
        assert concat_file.exists()
        content = concat_file.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        # 2 scenes x 2 lines each + 1 trailing repeated last entry = 5 lines
        assert len(lines) == 5

        # First scene
        assert "file " in lines[0]
        assert "scene_001.png" in lines[0]
        assert lines[1] == "duration 5.0"

        # Second scene
        assert "scene_002.png" in lines[2]
        assert lines[3] == "duration 3.5"

        # Last image repeated (FFmpeg concat demuxer requirement)
        assert "scene_002.png" in lines[4]

    async def test_create_concat_file_single_scene(
        self, ffmpeg_service: FFmpegService, tmp_path: Path
    ) -> None:
        scenes = [
            SceneInput(image_path=Path("/images/only.png"), duration_seconds=10.0),
        ]
        concat_file = await ffmpeg_service._create_concat_file(scenes, tmp_path)
        content = concat_file.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        # 1 scene x 2 lines + 1 trailing repeat = 3 lines
        assert len(lines) == 3
        assert "duration 10.0" in lines[1]


class TestAssemblyConfigDefaults:
    """Test AssemblyConfig default values."""

    def test_assembly_config_defaults(self) -> None:
        config = AssemblyConfig()

        assert config.width == 1080
        assert config.height == 1920
        assert config.fps == 30
        assert config.video_codec == "libx264"
        assert config.audio_codec == "aac"
        assert config.audio_bitrate == "192k"
        assert config.video_bitrate == "4M"
        assert config.pixel_format == "yuv420p"
        assert config.preset == "medium"

    def test_assembly_config_custom(self) -> None:
        config = AssemblyConfig(
            width=720,
            height=1280,
            fps=60,
            video_codec="libx265",
            preset="ultrafast",
        )
        assert config.width == 720
        assert config.height == 1280
        assert config.fps == 60
        assert config.video_codec == "libx265"
        assert config.preset == "ultrafast"
