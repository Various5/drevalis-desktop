"""Add gender column to voice_profiles.

Revision ID: 008
Revises: 007
Create Date: 2026-03-26
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_column("voice_profiles", "gender"):
        op.add_column("voice_profiles", sa.Column("gender", sa.Text(), nullable=True))


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_column("voice_profiles", "gender"):
        op.drop_column("voice_profiles", "gender")
