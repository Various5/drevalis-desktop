"""Add ``series.tone_profile`` JSONB column.

Drives the script step's voice profile, banned-vocabulary list, and
sentence-length cap. Validated at the API boundary by
``schemas.series.ToneProfile``; nullable here so callers can clear it
back to "no profile" by sending ``null``.

Existing rows backfill to ``{}`` via the server default — the script
step treats an empty / null tone_profile the same way (neutral
narration, default cap).

Revision ID: 041
Revises: 040
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "041"
down_revision: str | None = "040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column

    if not has_column("series", "tone_profile"):
        op.add_column(
            "series",
            sa.Column(
                "tone_profile",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    from migrations._helpers import has_column

    if has_column("series", "tone_profile"):
        op.drop_column("series", "tone_profile")
