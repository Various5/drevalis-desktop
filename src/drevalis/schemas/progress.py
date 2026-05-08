"""Pydantic schemas for real-time progress updates over WebSocket.

The WebSocket endpoint streams ProgressMessage objects to connected
clients so the UI can render live progress bars and status changes
during episode generation.

Example messages::

    # Step started
    {
        "episode_id": "a1b2c3d4-...",
        "job_id": "e5f6a7b8-...",
        "step": "scenes",
        "status": "running",
        "progress_pct": 0,
        "message": "Generating scene images..."
    }

    # Progress update
    {
        "episode_id": "a1b2c3d4-...",
        "job_id": "e5f6a7b8-...",
        "step": "scenes",
        "status": "running",
        "progress_pct": 40,
        "detail": {"scene_number": 2, "total_scenes": 5},
        "message": "Rendering scene 2 of 5"
    }

    # Step completed
    {
        "episode_id": "a1b2c3d4-...",
        "job_id": "e5f6a7b8-...",
        "step": "scenes",
        "status": "done",
        "progress_pct": 100,
        "message": "All scenes generated."
    }

    # Step failed
    {
        "episode_id": "a1b2c3d4-...",
        "job_id": "e5f6a7b8-...",
        "step": "scenes",
        "status": "failed",
        "progress_pct": 40,
        "message": "ComfyUI connection timed out",
        "error": "ConnectionError: ..."
    }
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProgressMessage(BaseModel):
    """WebSocket message representing a generation-job progress update.

    Sent from the backend to the frontend over WS whenever a
    GenerationJob changes status or increments progress.
    """

    episode_id: str = Field(..., description="UUID of the episode being generated")
    job_id: str = Field(..., description="UUID of the GenerationJob")
    step: Literal["script", "voice", "scenes", "captions", "assembly", "thumbnail"] = Field(
        ..., description="Pipeline step this message relates to"
    )
    status: Literal["queued", "running", "done", "failed", "warning"] = Field(
        ...,
        description=(
            "Current status of the job. ``warning`` is emitted by the "
            "post-step quality gates (script-content / voice / scenes) "
            "when a non-blocking issue is found — generation continues "
            "but the operator sees a flag in the activity monitor."
        ),
    )
    progress_pct: int = Field(..., ge=0, le=100, description="Progress percentage 0-100")
    message: str = Field(default="", description="Human-readable status message")
    error: str | None = Field(default=None, description="Error details when status is 'failed'")
    detail: dict[str, Any] | None = Field(
        default=None,
        description="Arbitrary extra data (e.g. scene_number, total_scenes)",
    )
