"""Add ``render_plan_json`` JSONB column to audiobooks (Task 13).

Stores a snapshot of the assembled audiobook timeline (events + chapter
markers + LAME priming offset). Task 13's scoped foundation builds the
plan after concat and writes it here as an inspectable artifact; future
passes will rewire concat / captions / track-mix to consume it directly.

Null on existing rows (no plan yet); the next regenerate populates it.

Revision ID: 034
Revises: 033
Create Date: 2026-04-27
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "034"
down_revision: str | None = "033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audiobooks",
        sa.Column(
            "render_plan_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("audiobooks", "render_plan_json")
