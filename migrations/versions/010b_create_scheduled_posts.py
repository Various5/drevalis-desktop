"""Create the scheduled_posts table.

Historically, this table was created via ad-hoc SQL on the dev DB and was
never captured in a migration. Migrations 011 and 013 reference it, so a
fresh install's migrations ran until 011 and died with:

    relation "scheduled_posts" does not exist

This migration slots in between 010 and 011 (``revision = '010b'``,
``down_revision = '010'``) so it runs before 011 adds ``youtube_channel_id``.

Existing databases that already have the table (created by hand) are
still fine: after upgrading through 010 they'll attempt to run 010b,
which uses ``IF NOT EXISTS`` semantics (manual check) to avoid a conflict.

Revision ID: 010b
Revises: 010
Create Date: 2026-04-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010b"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scheduled_posts" in inspector.get_table_names():
        # Table already exists (pre-migration hand-created on the dev box).
        # Skip creation; subsequent migrations (011, 013) will still apply
        # their ALTER / CREATE INDEX against the existing rows.
        return

    op.create_table(
        "scheduled_posts",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column(
            "content_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column(
            "scheduled_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column(
            "privacy",
            sa.Text(),
            nullable=False,
            server_default="private",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "published_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("remote_id", sa.Text(), nullable=True),
        sa.Column("remote_url", sa.Text(), nullable=True),
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
            "content_type IN ('episode', 'audiobook')",
            name="sched_content_type_valid",
        ),
        sa.CheckConstraint(
            "platform IN ('youtube', 'tiktok', 'instagram', 'x')",
            name="sched_platform_valid",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'publishing', 'published', 'failed', 'cancelled')",
            name="sched_status_valid",
        ),
        sa.CheckConstraint(
            "privacy IN ('public', 'unlisted', 'private')",
            name="sched_privacy_valid",
        ),
    )
    op.create_index(
        "ix_scheduled_posts_status",
        "scheduled_posts",
        ["status"],
    )
    op.create_index(
        "ix_scheduled_posts_scheduled_at",
        "scheduled_posts",
        ["scheduled_at"],
    )

    # Reuse the shared trigger from migration 001 to maintain updated_at.
    op.execute(
        """
        CREATE TRIGGER trg_scheduled_posts_updated_at
        BEFORE UPDATE ON scheduled_posts
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_scheduled_posts_updated_at ON scheduled_posts")
    op.drop_index("ix_scheduled_posts_scheduled_at", table_name="scheduled_posts")
    op.drop_index("ix_scheduled_posts_status", table_name="scheduled_posts")
    op.drop_table("scheduled_posts")
