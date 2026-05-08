"""Character / style locks on series — Phase E foundation.

Both columns are JSONB so workflows can add fields without schema churn:

- ``character_lock``: ``{"asset_ids": [...], "strength": 0.75, "lora": "..."}``
  — the scenes step passes these to ComfyUI as the ``character_lock``
  named input. IPAdapter-FaceID workflows consume it; other workflows
  ignore it.
- ``style_lock``: ``{"asset_ids": [...], "strength": 0.5, "lora": "..."}``
  — style-reference variant, same pattern but maps to the workflow's
  ``style_lock`` input.

Scene-level override: ``episodes.script.scenes[n].character_asset_id``
already exists via the Phase B ``reference_asset_ids`` plumbing — this
migration just adds the series-level defaults.

Revision ID: 027
Revises: 026
Create Date: 2026-04-22
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "027"
down_revision: str | None = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_column("series", "character_lock"):
        op.add_column("series", sa.Column("character_lock", sa.JSON(), nullable=True))
    if not has_column("series", "style_lock"):
        op.add_column("series", sa.Column("style_lock", sa.JSON(), nullable=True))


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_column("series", "style_lock"):
        op.drop_column("series", "style_lock")
    if has_column("series", "character_lock"):
        op.drop_column("series", "character_lock")
