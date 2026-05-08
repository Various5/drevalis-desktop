"""Pydantic v2 request/response schemas for the GenerationJob entity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class GenerationJobResponse(BaseModel):
    """Full generation job detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    episode_id: UUID
    step: str
    status: str
    progress_pct: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    retry_count: int
    worker_id: str | None
    created_at: datetime
    updated_at: datetime


class GenerationJobListResponse(BaseModel):
    """Lightweight generation job for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    episode_id: UUID
    step: str
    status: str
    progress_pct: int
    error_message: str | None
    retry_count: int
    created_at: datetime


class GenerationJobExtendedResponse(BaseModel):
    """Extended generation job response with episode and series metadata."""

    id: UUID
    episode_id: UUID
    step: str
    status: str
    progress_pct: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    retry_count: int
    worker_id: str | None
    created_at: datetime
    updated_at: datetime
    episode_title: str | None = None
    series_name: str | None = None
