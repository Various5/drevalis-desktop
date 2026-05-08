"""ComfyUIServer and ComfyUIWorkflow ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BOOLEAN, INTEGER, TEXT, TIMESTAMP, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .series import Series


class ComfyUIServer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered ComfyUI server instance.

    api_key_encrypted stores the Fernet-encrypted API key; api_key_version
    tracks the encryption key version to support key rotation.
    """

    __tablename__ = "comfyui_servers"

    name: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    url: Mapped[str] = mapped_column(TEXT, nullable=False)

    # Fernet-encrypted API key + key-rotation version
    api_key_encrypted: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    api_key_version: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="1")

    max_concurrent: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="2")
    is_active: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, server_default="true")
    max_concurrent_video_jobs: Mapped[int | None] = mapped_column(INTEGER, nullable=True)

    # Health-check tracking
    last_tested_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────
    series: Mapped[list[Series]] = relationship(
        back_populates="comfyui_server",
        foreign_keys="Series.comfyui_server_id",
    )


class ComfyUIWorkflow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A versioned ComfyUI workflow template.

    workflow_json_path points to the workflow JSON file on disk.
    input_mappings is a JSONB column validated through the
    WorkflowInputMapping Pydantic schema.
    """

    __tablename__ = "comfyui_workflows"

    name: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    workflow_json_path: Mapped[str] = mapped_column(TEXT, nullable=False)
    version: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="1")
    input_mappings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_format: Mapped[str] = mapped_column(String(20), nullable=False, server_default="'any'")

    # ── Relationships ──────────────────────────────────────────────────
    series: Mapped[list[Series]] = relationship(
        back_populates="comfyui_workflow",
        foreign_keys="Series.comfyui_workflow_id",
    )
