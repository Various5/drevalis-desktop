"""Pydantic v2 request/response schemas for the LLMConfig entity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from drevalis.core.validators import validate_safe_url_or_localhost


class LLMConfigCreate(BaseModel):
    """Payload for creating a new LLM configuration."""

    name: str = Field(..., min_length=1, max_length=255)
    base_url: str = Field(..., min_length=1)
    model_name: str = Field(..., min_length=1)
    api_key: str | None = Field(
        default=None,
        description="Plain-text API key (will be encrypted before storage)",
    )
    max_tokens: int = 4096
    temperature: float = 0.7

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        return validate_safe_url_or_localhost(v)


class LLMConfigUpdate(BaseModel):
    """Payload for updating an LLM configuration. All fields are optional."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = Field(
        default=None,
        description="New plain-text API key (will be encrypted before storage)",
    )
    max_tokens: int | None = None
    temperature: float | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_safe_url_or_localhost(v)
        return v


class LLMConfigResponse(BaseModel):
    """Full LLM config response.

    Note: api_key_encrypted is never exposed -- the field ``has_api_key``
    indicates whether an API key is stored.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    base_url: str
    model_name: str
    has_api_key: bool
    max_tokens: int
    temperature: float
    created_at: datetime
    updated_at: datetime


class LLMTestRequest(BaseModel):
    """Payload for testing an LLM configuration."""

    prompt: str = Field(
        default="Say hello in one sentence.",
        min_length=1,
        max_length=2000,
    )


class LLMTestResponse(BaseModel):
    """Result of an LLM test."""

    success: bool
    message: str
    response_text: str | None = None
    model: str | None = None
    tokens_used: int | None = None
