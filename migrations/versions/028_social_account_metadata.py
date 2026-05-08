"""Add account_metadata JSONB to social_platforms.

Used by the Instagram uploader to store ``public_video_base_url``
(the HTTPS prefix that replaces the local storage path when handing
a video URL to the Graph API). Generic shape so future platforms can
stash platform-specific knobs without new migrations.

Revision ID: 028
Revises: 027
Create Date: 2026-04-22
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "028"
down_revision: str | None = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_column("social_platforms", "account_metadata"):
        op.add_column(
            "social_platforms",
            sa.Column("account_metadata", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_column("social_platforms", "account_metadata"):
        op.drop_column("social_platforms", "account_metadata")
