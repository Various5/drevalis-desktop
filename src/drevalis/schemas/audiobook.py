"""Pydantic v2 request/response schemas for the Audiobook entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── AudiobookSettings (Task 9) ────────────────────────────────────────────
#
# Single source of truth for every audio knob we expose: loudness target,
# MP3 encode mode, video codec / CRF, ducking preset, silence gaps, etc.
# Defaults match the post-Task-1-through-8 narrative profile, so a request
# that omits the settings block behaves identically to today.
#
# The API accepts a ``preset`` (resolves against ``PLATFORM_PRESETS``) plus
# optional ``settings_override`` that merges on top. The merged result is
# stored on the audiobook row as JSONB and read back by the worker.


class AudiobookSettings(BaseModel):
    """Per-audiobook audio + video knobs."""

    model_config = ConfigDict(extra="forbid")

    # Loudness
    loudness_target_lufs: float = -18.0
    loudness_lra: float = 14.0
    true_peak_dbfs: float = -2.0

    # Audio export
    sample_rate: int = Field(default=44100, ge=8000, le=192000)
    mp3_mode: Literal["cbr_128", "cbr_192", "cbr_256", "vbr_v0", "vbr_v2"] = "vbr_v0"

    # Video export
    video_codec: Literal["libx264", "libx265"] = "libx264"
    video_crf: int = Field(default=21, ge=0, le=51)
    video_preset: Literal["fast", "medium", "slow"] = "medium"
    video_resolution: Literal["1920x1080", "1080x1920"] = "1920x1080"
    ken_burns: bool = True
    waveform: bool = True
    caption_mode: Literal["none", "bottom", "karaoke"] = "bottom"

    # Mixing
    ducking_preset: Literal["static", "subtle", "normal", "strong", "cinematic"] = "static"
    music_static_gain_db: float = -22.0

    # Silence
    chapter_silence_ms: int = Field(default=1200, ge=0, le=60000)
    speaker_change_silence_ms: int = Field(default=400, ge=0, le=10000)
    intra_speaker_silence_ms: int = Field(default=150, ge=0, le=10000)
    trim_leading_trailing_silence: bool = False


# Platform presets — exact deltas from the brief.
PLATFORM_PRESETS: dict[str, AudiobookSettings] = {
    "narrative": AudiobookSettings(),
    "podcast": AudiobookSettings(
        loudness_target_lufs=-16.0,
        loudness_lra=11.0,
        ducking_preset="normal",
        mp3_mode="vbr_v0",
    ),
    "streaming": AudiobookSettings(
        loudness_target_lufs=-14.0,
        loudness_lra=11.0,
        true_peak_dbfs=-1.0,
        mp3_mode="vbr_v0",
        sample_rate=48000,
    ),
    "acx": AudiobookSettings(
        loudness_target_lufs=-20.0,
        loudness_lra=18.0,
        true_peak_dbfs=-3.0,
        mp3_mode="cbr_192",
        sample_rate=44100,
    ),
}
DEFAULT_PLATFORM_PRESET = "narrative"


def resolve_audiobook_settings(
    preset: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> AudiobookSettings:
    """Merge a platform preset + caller overrides into a final settings.

    Unknown ``preset`` names fall back to ``narrative`` (no exception
    so an upstream typo can't fail generation). ``overrides`` is a
    dict of ``AudiobookSettings`` field names; unknown fields raise via
    ``model_config["extra"] = "forbid"``.
    """
    base = PLATFORM_PRESETS.get(
        (preset or DEFAULT_PLATFORM_PRESET).strip().lower(),
        PLATFORM_PRESETS[DEFAULT_PLATFORM_PRESET],
    )
    if not overrides:
        return base
    # Merge as a dict and validate so ``extra="forbid"`` rejects
    # unknown field names. ``model_copy(update=...)`` would silently
    # set them.
    merged_data = {**base.model_dump(), **overrides}
    return AudiobookSettings.model_validate(merged_data)


class ChapterMetadata(BaseModel):
    """Per-chapter metadata within the chapters JSONB.

    All new fields are optional for backwards compatibility with
    existing audiobooks that only have ``title`` and ``text``.
    """

    title: str
    text: str
    music_mood: str | None = None
    music_path: str | None = None
    image_path: str | None = None
    visual_prompt: str | None = None
    audio_path: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    duration_seconds: float | None = None


class AudiobookCreate(BaseModel):
    """Payload for creating a new audiobook."""

    title: str = Field(..., min_length=1, max_length=500)
    text: str = Field(..., min_length=1, description="Full text content to convert to audio")
    voice_profile_id: UUID
    generate_video: bool = Field(
        default=False,
        description="Also create an MP4 video with static background + audio (legacy, prefer output_format)",
    )
    background_image_path: str | None = Field(
        default=None,
        description="Path to a background image for video generation (relative to storage)",
    )
    output_format: str = Field(
        default="audio_only",
        description="Output format: audio_only | audio_image | audio_video",
    )
    cover_image_path: str | None = Field(
        default=None,
        description="Path to a cover image for audio_image output format (relative to storage)",
    )
    voice_casting: dict[str, str] | None = Field(
        default=None,
        description='Voice casting map: {"Speaker": "voice_profile_id"}',
    )
    music_enabled: bool = Field(
        default=False,
        description="Enable background music mixing",
    )
    music_mood: str | None = Field(
        default=None,
        description="Mood keyword for background music selection (e.g. calm, dramatic, upbeat)",
    )
    music_volume_db: float = Field(
        default=-14.0,
        description="Background music volume in dB (negative = quieter)",
    )
    speed: float = Field(
        default=1.0,
        ge=0.25,
        le=4.0,
        description="Speech speed multiplier",
    )
    pitch: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Speech pitch multiplier",
    )
    video_orientation: str = Field(
        default="landscape",
        description="Video orientation for MP4 output: landscape (1920x1080) or vertical (1080x1920)",
    )
    caption_style_preset: str | None = Field(
        default=None,
        description="Caption style preset name (e.g. youtube_highlight, karaoke, tiktok_pop, minimal, classic)",
    )
    image_generation_enabled: bool = Field(
        default=False,
        description="Generate per-chapter images via ComfyUI",
    )
    per_chapter_music: bool = Field(
        default=False,
        description="Use different music moods per chapter instead of global music",
    )
    chapter_moods: list[str] | None = Field(
        default=None,
        description="Per-chapter mood overrides (indexed by chapter order)",
    )
    youtube_channel_id: UUID | None = Field(
        default=None,
        description="YouTube channel to upload to",
    )
    preset: str | None = Field(
        default=None,
        description=(
            "Platform preset name (narrative / podcast / streaming / acx). "
            "Resolved against PLATFORM_PRESETS at create time and persisted "
            "as the audiobook's ``settings_json``."
        ),
    )
    settings_override: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional overrides applied on top of ``preset``. Field names "
            "must match ``AudiobookSettings``; unknown fields are rejected."
        ),
    )


class AudiobookUpdate(BaseModel):
    """Payload for updating an audiobook. All fields are optional."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    status: Literal["draft", "generating", "done", "failed"] | None = None
    output_format: str | None = Field(
        default=None,
        description="Output format: audio_only | audio_image | audio_video",
    )
    music_enabled: bool | None = None
    music_mood: str | None = None
    speed: float | None = Field(default=None, ge=0.25, le=4.0)
    pitch: float | None = Field(default=None, ge=0.5, le=2.0)
    video_orientation: str | None = Field(
        default=None,
        description="Video orientation: landscape (1920x1080) or vertical (1080x1920)",
    )
    caption_style_preset: str | None = Field(
        default=None,
        description="Caption style preset name",
    )
    image_generation_enabled: bool | None = None
    per_chapter_music: bool | None = None
    chapter_moods: list[str] | None = None
    youtube_channel_id: UUID | None = None


class AudiobookResponse(BaseModel):
    """Full audiobook response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    text: str
    voice_profile_id: UUID | None
    status: str
    output_format: str
    cover_image_path: str | None
    chapters: Any | None
    voice_casting: Any | None
    music_enabled: bool
    music_mood: str | None
    music_volume_db: float
    speed: float
    pitch: float
    audio_path: str | None
    video_path: str | None
    mp3_path: str | None
    duration_seconds: float | None
    file_size_bytes: int | None
    error_message: str | None
    background_image_path: str | None
    video_orientation: str
    caption_style_preset: str | None
    image_generation_enabled: bool
    youtube_channel_id: UUID | None = None
    # Per-track gain offsets + per-clip overrides; see Audiobook
    # ORM model docstring for the schema.
    track_mix: Any | None = None
    # Resolved AudiobookSettings (Task 9). Null means "narrative defaults".
    settings_json: Any | None = None
    created_at: datetime
    updated_at: datetime


class AudiobookListResponse(BaseModel):
    """Lightweight audiobook response for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: str
    output_format: str
    duration_seconds: float | None
    voice_profile_id: UUID | None
    created_at: datetime
