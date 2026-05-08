"""Add YouTube channels and uploads tables.

Revision ID: 007
Revises: 006
Create Date: 2026-03-26
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index, has_table

    # ── 1. youtube_channels ────────────────────────────────────────────
    if not has_table("youtube_channels"):
        op.create_table(
            "youtube_channels",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("channel_id", sa.TEXT(), nullable=False),
            sa.Column("channel_name", sa.TEXT(), nullable=False),
            sa.Column("access_token_encrypted", sa.TEXT(), nullable=True),
            sa.Column("refresh_token_encrypted", sa.TEXT(), nullable=True),
            sa.Column(
                "token_key_version",
                sa.INTEGER(),
                server_default="1",
                nullable=False,
            ),
            sa.Column(
                "token_expiry",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "is_active",
                sa.BOOLEAN(),
                server_default="true",
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_youtube_channels")),
            sa.UniqueConstraint("channel_id", name=op.f("uq_youtube_channels_channel_id")),
        )
    if not has_index("youtube_channels", "ix_youtube_channels_channel_id"):
        op.create_index(
            "ix_youtube_channels_channel_id",
            "youtube_channels",
            ["channel_id"],
            unique=True,
        )
    op.execute(
        """
        CREATE TRIGGER trg_youtube_channels_updated_at
            BEFORE UPDATE ON youtube_channels
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ── 2. youtube_uploads ─────────────────────────────────────────────
    if not has_table("youtube_uploads"):
        op.create_table(
            "youtube_uploads",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "episode_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column(
                "channel_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("youtube_video_id", sa.TEXT(), nullable=True),
            sa.Column("youtube_url", sa.TEXT(), nullable=True),
            sa.Column("title", sa.TEXT(), nullable=False),
            sa.Column("description", sa.TEXT(), nullable=True),
            sa.Column(
                "privacy_status",
                sa.TEXT(),
                server_default="'private'",
                nullable=False,
            ),
            sa.Column(
                "upload_status",
                sa.TEXT(),
                server_default="'pending'",
                nullable=False,
            ),
            sa.Column("error_message", sa.TEXT(), nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_youtube_uploads")),
            sa.ForeignKeyConstraint(
                ["episode_id"],
                ["episodes.id"],
                name=op.f("fk_youtube_uploads_episode_id_episodes"),
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["channel_id"],
                ["youtube_channels.id"],
                name=op.f("fk_youtube_uploads_channel_id_youtube_channels"),
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(
                "upload_status IN ('pending', 'uploading', 'done', 'failed')",
                name=op.f("ck_youtube_uploads_upload_status_valid"),
            ),
            sa.CheckConstraint(
                "privacy_status IN ('public', 'unlisted', 'private')",
                name=op.f("ck_youtube_uploads_privacy_status_valid"),
            ),
        )
    if not has_index("youtube_uploads", "ix_youtube_uploads_episode_id"):
        op.create_index(
            "ix_youtube_uploads_episode_id",
            "youtube_uploads",
            ["episode_id"],
        )
    if not has_index("youtube_uploads", "ix_youtube_uploads_channel_id"):
        op.create_index(
            "ix_youtube_uploads_channel_id",
            "youtube_uploads",
            ["channel_id"],
        )
    op.execute(
        """
        CREATE TRIGGER trg_youtube_uploads_updated_at
            BEFORE UPDATE ON youtube_uploads
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    from migrations._helpers import has_index, has_table

    op.execute("DROP TRIGGER IF EXISTS trg_youtube_uploads_updated_at ON youtube_uploads;")
    if has_table("youtube_uploads"):
        op.drop_table("youtube_uploads")

    op.execute("DROP TRIGGER IF EXISTS trg_youtube_channels_updated_at ON youtube_channels;")
    if has_table("youtube_channels"):
        op.drop_table("youtube_channels")
