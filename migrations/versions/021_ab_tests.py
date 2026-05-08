"""Add ab_tests table.

Links two episodes that belong to the same series into a paired A/B
test. A worker job (future) compares their YouTube view counts 7 days
after the later upload and fills in ``winner_episode_id``.

Revision ID: 021
Revises: 020
Create Date: 2026-04-22
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index, has_table

    if not has_table("ab_tests"):
        op.create_table(
            "ab_tests",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "series_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("series.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "episode_a_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("episodes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "episode_b_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("episodes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("variant_label", sa.Text(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "winner_episode_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("episodes.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("comparison_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
            sa.CheckConstraint(
                "episode_a_id <> episode_b_id",
                name="ck_ab_tests_distinct_episodes",
            ),
        )
    if not has_index("ab_tests", "ix_ab_tests_series_id"):
        op.create_index(
            "ix_ab_tests_series_id",
            "ab_tests",
            ["series_id"],
        )


def downgrade() -> None:
    from migrations._helpers import has_index, has_table

    op.drop_index("ix_ab_tests_series_id", table_name="ab_tests")
    if has_table("ab_tests"):
        op.drop_table("ab_tests")
