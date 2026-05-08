"""Video edit sessions — persistent state for the in-browser editor.

One row per episode edit session. The timeline JSON contains every
scene / overlay / caption / audio decision the user has made. When
the user hits "Render", a worker reads this row and drives FFmpeg
from it — producing a new ``video`` asset that replaces the previous
``final.mp4``.

Versioning: bumped each time the schema shape changes. The render
worker checks the version and refuses to run against something it
doesn't understand.

Revision ID: 026
Revises: 025
Create Date: 2026-04-22
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "026"
down_revision: str | None = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index, has_table

    if has_table("video_edit_sessions"):
        return
    op.create_table(
        "video_edit_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,  # one session per episode — render re-opens it
        ),
        # Schema version — bump when the JSON shape changes breakingly.
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        # Timeline shape:
        # {
        #   "duration_s": 42.7,
        #   "tracks": [
        #     {"id": "video", "kind": "video", "clips": [
        #        {"id": "...", "scene_number": 1, "source": "scene" | "asset",
        #         "asset_id": "...", "in_s": 0.0, "out_s": 4.0,
        #         "start_s": 0.0, "end_s": 4.0, "speed": 1.0}
        #     ]},
        #     {"id": "voice", "kind": "audio", "clips": [...]},
        #     {"id": "music", "kind": "audio", "clips": [...]},
        #     {"id": "overlay", "kind": "overlay", "clips": [...]}
        #   ]
        # }
        sa.Column("timeline", postgresql.JSONB(), nullable=False, server_default="{}"),
        # Rendered output metadata (filled by the render worker).
        sa.Column("last_render_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_rendered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    if not has_index("video_edit_sessions", "ix_video_edit_sessions_episode"):
        op.create_index(
            "ix_video_edit_sessions_episode", "video_edit_sessions", ["episode_id"], unique=True
        )


def downgrade() -> None:
    from migrations._helpers import has_index, has_table

    if has_index("video_edit_sessions", "ix_video_edit_sessions_episode"):
        op.drop_index("ix_video_edit_sessions_episode", table_name="video_edit_sessions")
    if has_table("video_edit_sessions"):
        op.drop_table("video_edit_sessions")
