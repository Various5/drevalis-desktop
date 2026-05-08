"""Add scene_mode column to series for image vs video generation.

Revision ID: 004
Revises: 003
Create Date: 2026-03-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "series",
        sa.Column(
            "scene_mode",
            sa.Text(),
            server_default="image",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("series", "scene_mode")
