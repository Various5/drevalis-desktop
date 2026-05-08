"""Character packs — named bundles of character_lock + style_lock.

A user builds one once (pick references + tune strengths + set LoRA),
saves it as a pack, then applies it to future series in one click.

Revision ID: 029
Revises: 028
Create Date: 2026-04-22
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "029"
down_revision: str | None = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_table("character_packs"):
        op.create_table(
            "character_packs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("thumbnail_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("character_lock", sa.JSON(), nullable=True),
            sa.Column("style_lock", sa.JSON(), nullable=True),
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
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_table("character_packs"):
        op.drop_table("character_packs")
