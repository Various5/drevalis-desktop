"""Add jwt_key_version column to license_state for at-rest encryption.

The license JWT is now Fernet-encrypted before storage (rather than kept
as plaintext alongside the Fernet-encrypted OAuth / API-key values). The
new ``jwt_key_version`` column records which encryption key version was
used so that future key rotations can transparently decrypt legacy rows.

Backward compatibility: when ``jwt_key_version`` IS NULL, the repository
treats the ``jwt`` column as legacy plaintext (the value still verifies
with ``verify_jwt`` because the JWT is self-authenticating). The next
write re-encrypts and stamps the version. No data migration needed here.

Revision ID: 017
Revises: 016
Create Date: 2026-04-21
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if not has_column("license_state", "jwt_key_version"):
        op.add_column(
            "license_state",
            sa.Column("jwt_key_version", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    from migrations._helpers import has_column, has_index, has_table

    if has_column("license_state", "jwt_key_version"):
        op.drop_column("license_state", "jwt_key_version")
