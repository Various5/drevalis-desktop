"""Pydantic v2 response schemas for the Settings / system-health endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class StorageUsageResponse(BaseModel):
    """Storage usage statistics."""

    total_size_bytes: int
    total_size_human: str
    storage_base_path: str
    # Absolute resolved path as the app process sees it — independent
    # of whether ``storage_base_path`` was ``./storage`` or an env
    # override.
    storage_base_abs: str | None = None
    # Host-side root of the bind mount that surfaces at
    # ``storage_base_path`` inside the container. Lets the Settings
    # panel show the user *exactly* where to copy files on their
    # host filesystem. ``None`` when we can't read /proc/self/mountinfo
    # (Windows host, restricted container).
    host_source_path: str | None = None
    # Per-subfolder byte breakdown so the user can see at a glance
    # which trees have content — helps diagnose "I copied 21 GB but
    # the app says 900 KB" scenarios (the files were copied to a
    # different host directory than the compose bind mount reaches).
    subdir_sizes: dict[str, int] = {}
    # v0.20.7 — raw /proc/self/mountinfo lines scoped to the storage
    # bind mount. Paste into a support ticket to diagnose persistent
    # bind-target mismatches after installation.
    mountinfo_lines: list[str] = []


class ServiceHealth(BaseModel):
    """Health status of a single backend service."""

    name: str
    status: str  # "ok" | "degraded" | "unreachable"
    message: str = ""


class HealthCheckResponse(BaseModel):
    """Aggregated system health check result."""

    overall: str  # "ok" | "degraded" | "unhealthy"
    services: list[ServiceHealth]


class FFmpegInfoResponse(BaseModel):
    """FFmpeg installation information."""

    ffmpeg_path: str
    available: bool
    version: str | None = None
    message: str = ""
