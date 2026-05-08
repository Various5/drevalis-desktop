"""Per-user UI preferences JSONB column.

Adds ``users.preferences`` JSONB to persist client-side preferences
across browsers/devices. Backend doesn't validate the shape — clients
write what they need and tolerate missing keys. Top-level keys are
namespaced by feature (``dashboard_layout``, ``theme``,
``calendar_view``, …).

Default ``'{}'::jsonb`` server-side so legacy rows behave as "no
preferences set" without a manual backfill.

Revision ID: 047
Revises: 046
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "047"
down_revision: str | None = "046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "preferences",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "preferences")
