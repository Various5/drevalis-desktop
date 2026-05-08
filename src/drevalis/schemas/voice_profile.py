"""Pydantic v2 request/response schemas for the VoiceProfile entity."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VoiceProfileCreate(BaseModel):
    """Payload for creating a new voice profile."""

    name: str = Field(..., min_length=1, max_length=255)
    provider: Literal["piper", "elevenlabs", "kokoro", "edge", "comfyui_elevenlabs"]
    piper_model_path: str | None = None
    piper_speaker_id: str | None = None
    speed: float = 1.0
    pitch: float = 1.0
    elevenlabs_voice_id: str | None = None
    kokoro_voice_name: str | None = None
    kokoro_model_path: str | None = None
    edge_voice_id: str | None = None
    gender: str | None = None  # "male" | "female"
    sample_audio_path: str | None = None
    language_code: str | None = Field(
        default=None,
        description="BCP-47 tag, e.g. 'en-US', 'de-DE'. Auto-derived from edge_voice_id when omitted.",
    )


class VoiceProfileUpdate(BaseModel):
    """Payload for updating a voice profile. All fields are optional."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider: Literal["piper", "elevenlabs", "kokoro", "edge", "comfyui_elevenlabs"] | None = None
    piper_model_path: str | None = None
    piper_speaker_id: str | None = None
    speed: float | None = None
    pitch: float | None = None
    elevenlabs_voice_id: str | None = None
    kokoro_voice_name: str | None = None
    kokoro_model_path: str | None = None
    edge_voice_id: str | None = None
    gender: str | None = None
    sample_audio_path: str | None = None
    language_code: str | None = None


class VoiceProfileResponse(BaseModel):
    """Full voice profile response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    provider: str
    piper_model_path: str | None
    piper_speaker_id: str | None
    speed: float
    pitch: float
    elevenlabs_voice_id: str | None
    kokoro_voice_name: str | None
    kokoro_model_path: str | None
    edge_voice_id: str | None
    gender: str | None
    sample_audio_path: str | None
    language_code: str | None = None
    created_at: datetime
    updated_at: datetime


class VoiceTestRequest(BaseModel):
    """Payload for testing a voice profile with sample text."""

    text: str = Field(
        default="Hello, this is a test of the voice profile.",
        min_length=1,
        max_length=1000,
    )


class VoiceTestResponse(BaseModel):
    """Result of a voice profile test."""

    success: bool
    message: str
    audio_path: str | None = None
    duration_seconds: float | None = None


class CloneVoiceRequest(BaseModel):
    """Payload for cloning a voice from an existing audio asset."""

    asset_id: UUID
    display_name: str
    provider: Literal["elevenlabs", "piper", "kokoro"] = "elevenlabs"
    language_code: str | None = None


class CloneVoiceResponse(BaseModel):
    """Result of a voice clone create."""

    voice_profile_id: UUID
    provider: str
    status: str  # "ready" | "pending_training"
    note: str
