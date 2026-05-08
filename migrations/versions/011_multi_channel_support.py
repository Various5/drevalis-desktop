"""Add multi-channel upload support.

- youtube_channels: add upload_days (JSONB), upload_time (TEXT)
- series: add youtube_channel_id FK
- audiobooks: add youtube_channel_id FK
- scheduled_posts: add youtube_channel_id FK

Revision ID: 011
Revises: 010
Create Date: 2026-04-02
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011"
down_revision: str | None = "010b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    # youtube_channels: scheduling fields
    if not has_column("youtube_channels", "upload_days"):
        op.add_column(
            "youtube_channels",
            sa.Column("upload_days", postgresql.JSONB(), nullable=True),
        )
    if not has_column("youtube_channels", "upload_time"):
        op.add_column(
            "youtube_channels",
            sa.Column("upload_time", sa.TEXT(), nullable=True),
        )

    # series: channel assignment
    if not has_column("series", "youtube_channel_id"):
        op.add_column(
            "series",
            sa.Column(
                "youtube_channel_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("youtube_channels.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # audiobooks: channel assignment
    if not has_column("audiobooks", "youtube_channel_id"):
        op.add_column(
            "audiobooks",
            sa.Column(
                "youtube_channel_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("youtube_channels.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # scheduled_posts: channel assignment
    if not has_column("scheduled_posts", "youtube_channel_id"):
        op.add_column(
            "scheduled_posts",
            sa.Column(
                "youtube_channel_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("youtube_channels.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_column("scheduled_posts", "youtube_channel_id"):
        op.drop_column("scheduled_posts", "youtube_channel_id")
    if has_column("audiobooks", "youtube_channel_id"):
        op.drop_column("audiobooks", "youtube_channel_id")
    if has_column("series", "youtube_channel_id"):
        op.drop_column("series", "youtube_channel_id")
    if has_column("youtube_channels", "upload_time"):
        op.drop_column("youtube_channels", "upload_time")
    if has_column("youtube_channels", "upload_days"):
        op.drop_column("youtube_channels", "upload_days")
