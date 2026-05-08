"""Index ``scheduled_posts.youtube_channel_id`` so SET NULL cascades stay fast.

When a YouTube channel is deleted, Postgres has to find every
scheduled_posts row referencing it to apply the SET NULL rule. Without
an index that's a sequential scan; with the index it's a single
range-scan.

Revision ID: 038
Revises: 037
Create Date: 2026-04-29
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "038"
down_revision: str | None = "037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index

    if not has_index("scheduled_posts", "ix_scheduled_posts_youtube_channel_id"):
        op.create_index(
            "ix_scheduled_posts_youtube_channel_id",
            "scheduled_posts",
            ["youtube_channel_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_scheduled_posts_youtube_channel_id",
        table_name="scheduled_posts",
    )
