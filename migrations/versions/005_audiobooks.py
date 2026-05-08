"""Create audiobooks table for text-to-audiobook feature.

Revision ID: 005
Revises: 004
Create Date: 2026-03-26
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index, has_table

    if not has_table("audiobooks"):
        op.create_table(
            "audiobooks",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                primary_key=True,
            ),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column(
                "voice_profile_id",
                UUID(as_uuid=True),
                sa.ForeignKey("voice_profiles.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.Text(),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("audio_path", sa.Text(), nullable=True),
            sa.Column("video_path", sa.Text(), nullable=True),
            sa.Column("duration_seconds", sa.Numeric(), nullable=True),
            sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("background_image_path", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "status IN ('draft', 'generating', 'done', 'failed')",
                name="status_valid",
            ),
        )

    # Index on status for filtering generating/done/failed
    if not has_index("audiobooks", "ix_audiobooks_status"):
        op.create_index(
            "ix_audiobooks_status",
            "audiobooks",
            ["status"],
        )

    # Index on voice_profile_id for FK lookups
    if not has_index("audiobooks", "ix_audiobooks_voice_profile_id"):
        op.create_index(
            "ix_audiobooks_voice_profile_id",
            "audiobooks",
            ["voice_profile_id"],
        )

    # Add the updated_at trigger (same pattern as other tables)
    op.execute("""
        CREATE TRIGGER set_audiobooks_updated_at
        BEFORE UPDATE ON audiobooks
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    from migrations._helpers import has_index, has_table

    op.execute("DROP TRIGGER IF EXISTS set_audiobooks_updated_at ON audiobooks;")
    op.drop_index("ix_audiobooks_voice_profile_id", table_name="audiobooks")
    op.drop_index("ix_audiobooks_status", table_name="audiobooks")
    if has_table("audiobooks"):
        op.drop_table("audiobooks")
