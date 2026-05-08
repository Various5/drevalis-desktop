"""Add per-job LLM token counters.

Makes the Usage dashboard able to report real token spend instead of
showing "not yet instrumented". Columns default to 0 so existing rows
stay consistent, and they're nullable='false' so aggregation queries
don't have to COALESCE.

Revision ID: 022
Revises: 021
Create Date: 2026-04-22
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_column("generation_jobs", "tokens_prompt"):
        op.add_column(
            "generation_jobs",
            sa.Column(
                "tokens_prompt",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if not has_column("generation_jobs", "tokens_completion"):
        op.add_column(
            "generation_jobs",
            sa.Column(
                "tokens_completion",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_column("generation_jobs", "tokens_completion"):
        op.drop_column("generation_jobs", "tokens_completion")
    if has_column("generation_jobs", "tokens_prompt"):
        op.drop_column("generation_jobs", "tokens_prompt")
