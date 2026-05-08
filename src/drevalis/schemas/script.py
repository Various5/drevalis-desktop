"""Pydantic schemas for the Episode.script JSONB field.

The script column on the episodes table stores structured scene data
produced by the LLM script-generation step.  These schemas are used
to validate incoming JSON before it is persisted, and to deserialize
the JSONB back into typed Python objects when read.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SceneScript(BaseModel):
    """A single scene within a short-form video script.

    Accepts common LLM field name variations via the pre-validator.
    """

    scene_number: int = Field(default=0, ge=0, description="1-based scene index")
    narration: str = Field(..., min_length=1, description="Voice-over text for this scene")
    visual_prompt: str = Field(
        ...,
        min_length=1,
        description="Image-generation prompt describing the visual for this scene",
    )
    duration_seconds: float = Field(
        ..., gt=0, description="Target duration of this scene in seconds"
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="3-5 key words for animated overlay",
    )
    # Phase B: user-provided asset to use in place of the generated visual.
    # When set, the scenes step copies the asset's file into this scene's
    # slot and skips the ComfyUI generation for this scene entirely.
    source_asset_id: str | None = Field(
        default=None,
        description="UUID of an Asset to use directly as this scene's visual.",
    )
    # If ``source_asset_id`` points at a video, these trim the source
    # to a specific window (seconds from the start of the source clip).
    clip_start_s: float | None = Field(
        default=None, ge=0, description="Trim start within the source asset (seconds)."
    )
    clip_end_s: float | None = Field(
        default=None, ge=0, description="Trim end within the source asset (seconds)."
    )

    # Phase E: optional video asset that drives motion for this scene
    # when using a video-to-video workflow (Wan 2.6, AnimateDiff, etc).
    # Workflows without a motion-reference input ignore it.
    motion_reference_asset_id: str | None = Field(
        default=None,
        description="UUID of a video Asset used as motion reference.",
    )

    # Phase C: per-scene generation overrides. Any of these set means
    # "differ from the series default for this scene only". The pipeline
    # treats missing fields as "use series-level defaults".
    style_override: str | None = Field(
        default=None,
        description="Prompt fragment prepended to ``visual_prompt`` for this scene only.",
    )
    negative_prompt_override: str | None = Field(
        default=None,
        description="Per-scene negative prompt that replaces the series default.",
    )
    seed: int | None = Field(
        default=None,
        description="ComfyUI seed for deterministic regeneration of this scene.",
    )
    voice_emotion: str | None = Field(
        default=None,
        description="Tag for TTS engines that support style conditioning "
        "(e.g. 'excited', 'calm', 'sad').",
    )
    voice_profile_id_override: str | None = Field(
        default=None,
        description="UUID of a VoiceProfile to use for this scene only "
        "(overrides series + episode voice).",
    )
    aspect_crop: str | None = Field(
        default=None,
        description='Per-scene crop hint for multi-aspect workflows: "center", '
        '"top", "bottom", or "face".',
    )

    # Phase 2.10: TTS-formatted narration. ``narration`` is what the
    # frontend editor shows; ``narration_tts`` (when set) is the
    # provider-massaged variant the TTS step actually feeds to the
    # synthesiser. Numbers spelled out, acronyms expanded, parentheticals
    # split — provider-specific so the rules live next to each TTS class.
    # When None, callers fall back to ``narration``.
    narration_tts: str | None = Field(
        default=None,
        description=(
            "Optional TTS-massaged variant of ``narration`` (numbers spelled out, "
            "acronyms expanded, parentheticals split). Populated by the script step "
            "after refinement; consumed by ``TTSService.generate_voiceover``. When "
            "absent, the synthesiser uses ``narration`` directly."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, data: dict) -> dict:  # type: ignore[type-arg]
        """Accept common LLM naming variations."""
        if not isinstance(data, dict):
            return data
        # text -> narration
        if "narration" not in data and "text" in data:
            data["narration"] = data.pop("text")
        # scene_prompt -> visual_prompt
        if "visual_prompt" not in data and "scene_prompt" in data:
            data["visual_prompt"] = data.pop("scene_prompt")
        # duration_hint -> duration_seconds
        if "duration_seconds" not in data and "duration_hint" in data:
            data["duration_seconds"] = data.pop("duration_hint")
        if "duration_seconds" not in data and "duration" in data:
            data["duration_seconds"] = data.pop("duration")
        # key_words -> keywords
        if "keywords" not in data and "key_words" in data:
            data["keywords"] = data.pop("key_words")
        return data


class EpisodeScript(BaseModel):
    """Full script payload stored in episodes.script JSONB column.

    Validated before INSERT/UPDATE to guarantee structural integrity.
    Accepts common LLM naming variations via pre-validator.
    """

    title: str = Field(..., min_length=1, description="Episode title")
    hook: str = Field(default="", description="Opening hook line to grab attention")
    scenes: list[SceneScript] = Field(..., min_length=1, description="Ordered list of scenes")
    outro: str = Field(default="", description="Closing line / call-to-action")
    total_duration_seconds: float = Field(default=0, ge=0, description="Sum of all scene durations")
    language: str = Field(default="en-US", description="BCP-47 language tag for the script")
    # Extra fields the LLM might generate (stored but not required)
    description: str = Field(default="", description="YouTube description")
    hashtags: list[str] = Field(default_factory=list, description="Hashtags")
    thumbnail_prompt: str = Field(
        default="",
        description="Image generation prompt for the episode thumbnail",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, data: dict) -> dict:  # type: ignore[type-arg]
        """Accept common LLM naming variations."""
        if not isinstance(data, dict):
            return data
        # segments -> scenes
        if "scenes" not in data and "segments" in data:
            data["scenes"] = data.pop("segments")
        # Auto-number scenes if missing scene_number
        if "scenes" in data and isinstance(data["scenes"], list):
            for i, scene in enumerate(data["scenes"]):
                if isinstance(scene, dict) and "scene_number" not in scene:
                    scene["scene_number"] = i + 1
        # Calculate total_duration if missing
        if "total_duration_seconds" not in data and "scenes" in data:
            total = 0.0
            for scene in data.get("scenes", []):
                if isinstance(scene, dict):
                    d = (
                        scene.get("duration_seconds")
                        or scene.get("duration_hint")
                        or scene.get("duration")
                        or 0
                    )
                    total += float(d)
            data["total_duration_seconds"] = total
        return data
