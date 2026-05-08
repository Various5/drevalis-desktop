"""Pydantic v2 request/response schemas for the PromptTemplate entity."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PromptTemplateCreate(BaseModel):
    """Payload for creating a new prompt template."""

    name: str = Field(..., min_length=1, max_length=255)
    template_type: Literal["script", "visual", "hook", "hashtag"]
    system_prompt: str = Field(..., min_length=1)
    user_prompt_template: str = Field(..., min_length=1)


class PromptTemplateUpdate(BaseModel):
    """Payload for updating a prompt template. All fields are optional."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    template_type: Literal["script", "visual", "hook", "hashtag"] | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None


class PromptTemplateResponse(BaseModel):
    """Full prompt template response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    template_type: str
    system_prompt: str
    user_prompt_template: str
    created_at: datetime
    updated_at: datetime
