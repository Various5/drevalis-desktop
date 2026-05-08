"""Add 'facebook' to social_platforms.platform and scheduled_posts.platform
check constraints.

Drevalis already supports tiktok / instagram / x via Graph-like APIs;
Facebook pages share the Meta Graph API with Instagram so the upload
path is nearly identical. This migration only widens the allowed set —
existing rows are untouched.

Caveat: the social_platforms constraint was introduced in 016 with an
explicit ``name="ck_social_platforms_platform_valid"`` AND the Base
metadata has a naming_convention prefix of ``ck_%(table_name)s_`` —
so the real name in the DB is the doubly-prefixed
``ck_social_platforms_ck_social_platforms_platform_valid``. We find
the actual constraint name at runtime so we don't have to care which
legacy form each install carries.

Revision ID: 030
Revises: 029
Create Date: 2026-04-22
"""

from collections.abc import Sequence
from typing import Union

from alembic import op
from sqlalchemy import text

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _find_check_constraint(table: str, needle: str) -> str | None:
    """Return the actual name of a check constraint whose name *contains*
    ``needle`` on ``table``; None if no such constraint exists.

    ``::regclass`` confuses SQLAlchemy's ``:param`` parser, so we use the
    ``CAST(... AS regclass)`` form and only parametrise values.
    """
    bind = op.get_bind()
    row = bind.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = CAST(:t AS regclass) "
            "AND contype = 'c' "
            "AND conname LIKE :pat "
            "LIMIT 1"
        ),
        {"t": table, "pat": f"%{needle}%"},
    ).fetchone()
    return row[0] if row else None


def upgrade() -> None:
    # social_platforms — include 'facebook'.
    existing = _find_check_constraint("social_platforms", "platform_valid")
    if existing:
        op.execute(f'ALTER TABLE social_platforms DROP CONSTRAINT "{existing}"')
    op.execute(
        "ALTER TABLE social_platforms "
        "ADD CONSTRAINT ck_social_platforms_platform_valid "
        "CHECK (platform IN ('tiktok', 'instagram', 'x', 'facebook'))"
    )

    # scheduled_posts — include 'facebook'.
    existing = _find_check_constraint("scheduled_posts", "sched_platform_valid")
    if existing:
        op.execute(f'ALTER TABLE scheduled_posts DROP CONSTRAINT "{existing}"')
    op.execute(
        "ALTER TABLE scheduled_posts "
        "ADD CONSTRAINT ck_scheduled_posts_sched_platform_valid "
        "CHECK (platform IN ('youtube', 'tiktok', 'instagram', 'x', 'facebook'))"
    )


def downgrade() -> None:
    existing = _find_check_constraint("social_platforms", "platform_valid")
    if existing:
        op.execute(f'ALTER TABLE social_platforms DROP CONSTRAINT "{existing}"')
    op.execute(
        "ALTER TABLE social_platforms "
        "ADD CONSTRAINT ck_social_platforms_platform_valid "
        "CHECK (platform IN ('tiktok', 'instagram', 'x'))"
    )

    existing = _find_check_constraint("scheduled_posts", "sched_platform_valid")
    if existing:
        op.execute(f'ALTER TABLE scheduled_posts DROP CONSTRAINT "{existing}"')
    op.execute(
        "ALTER TABLE scheduled_posts "
        "ADD CONSTRAINT ck_scheduled_posts_sched_platform_valid "
        "CHECK (platform IN ('youtube', 'tiktok', 'instagram', 'x'))"
    )
