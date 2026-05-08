"""Pydantic v2 request/response schemas for ComfyUI server and workflow CRUD."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from drevalis.core.validators import validate_safe_url_or_localhost

# ── ComfyUI Server schemas ────────────────────────────────────────────────


class ComfyUIServerCreate(BaseModel):
    """Payload for creating a new ComfyUI server."""

    name: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1)
    api_key: str | None = Field(
        default=None,
        description="Plain-text API key (will be encrypted before storage)",
    )
    max_concurrent: int = Field(default=2, ge=1, le=32)
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        return validate_safe_url_or_localhost(v)


class ComfyUIServerUpdate(BaseModel):
    """Payload for updating a ComfyUI server. All fields are optional."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = None
    api_key: str | None = Field(
        default=None,
        description="New plain-text API key (will be encrypted before storage)",
    )
    max_concurrent: int | None = Field(default=None, ge=1, le=32)
    is_active: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_safe_url_or_localhost(v)
        return v


class ComfyUIServerResponse(BaseModel):
    """Full ComfyUI server response.

    The API key is never exposed; ``has_api_key`` indicates its presence.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    has_api_key: bool
    max_concurrent: int
    is_active: bool
    last_tested_at: datetime | None
    last_test_status: str | None
    created_at: datetime
    updated_at: datetime


class ComfyUIServerTestResponse(BaseModel):
    """Result of a ComfyUI server connection test."""

    success: bool
    message: str
    server_id: UUID


# ── ComfyUI Workflow schemas ──────────────────────────────────────────────


def _validate_workflow_path(path: str) -> str:
    """Validate that workflow_json_path is a safe relative path within workflows/."""
    # Normalize to forward slashes
    normalized = path.replace("\\", "/")

    # Block path traversal
    if ".." in normalized.split("/"):
        raise ValueError("workflow_json_path must not contain '..' segments")

    # Must be a relative path (no leading slash)
    if normalized.startswith("/"):
        raise ValueError("workflow_json_path must be a relative path")

    # Must have .json extension
    if not normalized.lower().endswith(".json"):
        raise ValueError("workflow_json_path must have a .json extension")

    # Must start with 'workflows/' subdirectory
    if not normalized.startswith("workflows/"):
        raise ValueError("workflow_json_path must be within the 'workflows/' directory")

    return normalized


class ComfyUIWorkflowCreate(BaseModel):
    """Payload for creating a new ComfyUI workflow."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    workflow_json_path: str = Field(..., min_length=1)
    version: int = 1
    input_mappings: dict[str, Any] = Field(
        ..., description="WorkflowInputMapping-compatible JSON object"
    )

    @field_validator("workflow_json_path")
    @classmethod
    def validate_workflow_path(cls, v: str) -> str:
        return _validate_workflow_path(v)


class ComfyUIWorkflowUpdate(BaseModel):
    """Payload for updating a ComfyUI workflow. All fields are optional."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    workflow_json_path: str | None = None
    version: int | None = None
    input_mappings: dict[str, Any] | None = None

    @field_validator("workflow_json_path")
    @classmethod
    def validate_workflow_path(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_workflow_path(v)
        return v


class ComfyUIWorkflowResponse(BaseModel):
    """Full ComfyUI workflow response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    workflow_json_path: str
    version: int
    input_mappings: dict[str, Any]
    created_at: datetime
    updated_at: datetime
