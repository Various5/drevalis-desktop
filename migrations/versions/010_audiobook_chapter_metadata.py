"""Add image_generation_enabled to audiobooks for per-chapter image generation.

Revision ID: 010
Revises: 009
Create Date: 2026-03-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audiobooks",
        sa.Column(
            "image_generation_enabled",
            sa.BOOLEAN(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("audiobooks", "image_generation_enabled")
