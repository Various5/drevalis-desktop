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
from drevalis.services.ffmpeg.clip_filters import (  # noqa: F401
    build_clip_vf,
    color_eq,
    fade_chain,
    transform_filtergraph,
)

__all__ = [
    "AUDIO_PRESETS",
    "AssemblyConfig",
    "AssemblyResult",
    "AudioMixConfig",
    "FFmpegService",
    "SceneInput",
    "XFADE_TRANSITIONS",
    "build_clip_vf",
    "color_eq",
    "fade_chain",
    "transform_filtergraph",
]
