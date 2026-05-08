"""Add ``job_state`` JSONB column to audiobooks (Task 11).

Stores the fine-grained DAG of per-stage states for the audiobook
generation pipeline. Null means "no DAG yet" — the service builds a
fresh ``init_state(num_chapters)`` on first generate. Existing rows
keep their current behaviour (everything runs from scratch on retry,
which is what the pre-Task-11 pipeline did anyway).

Revision ID: 033
Revises: 032
Create Date: 2026-04-27
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "033"
down_revision: str | None = "032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audiobooks",
        sa.Column(
            "job_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("audiobooks", "job_state")
