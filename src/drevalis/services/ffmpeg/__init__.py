"""FFmpeg service package — backward-compatible re-exports."""

from drevalis.services.ffmpeg._monolith import (  # noqa: F401
    AUDIO_PRESETS,
    XFADE_TRANSITIONS,
    AssemblyConfig,
    AssemblyResult,
    AudioMixConfig,
    FFmpegService,
    SceneInput,
)

__all__ = [
    "AUDIO_PRESETS",
    "AssemblyConfig",
    "AssemblyResult",
    "AudioMixConfig",
    "FFmpegService",
    "SceneInput",
    "XFADE_TRANSITIONS",
]
