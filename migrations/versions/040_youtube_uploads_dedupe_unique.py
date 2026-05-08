"""Partial unique index on ``youtube_uploads(episode_id, channel_id)``
for ``upload_status='done'`` so the database refuses duplicate publishes.

Application-level guards exist in YouTubeAdminService.create_upload_row
and in workers/jobs/scheduled.publish_scheduled_posts, but a unique
index is the last line of defence: a manual SQL insert, a race between
two cron workers, or a future code path can no longer accidentally land
a second ``done`` row for the same (episode, channel) pair.

The index is partial because failed/uploading rows are valid history
and may legitimately repeat (a previous failure followed by a manual
retry must be representable as two rows).

Revision ID: 040
Revises: 039
Create Date: 2026-05-04
"""

from collections.abc import Sequence
from typing import Union

from alembic import op
from sqlalchemy import text

revision: str = "040"
down_revision: str | None = "039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pre-emptively neutralise existing duplicates so the index can be
    # created. Earliest ``done`` row per (episode, channel) wins; the
    # rest are demoted to ``failed`` with an audit note. Operators can
    # then run POST /api/v1/youtube/uploads/dedupe to also delete the
    # videos on YouTube itself.
    op.execute(
        text(
            """
            WITH ranked AS (
              SELECT id,
                     ROW_NUMBER() OVER (
                       PARTITION BY episode_id, channel_id
                       ORDER BY created_at ASC, id ASC
                     ) AS rn
              FROM youtube_uploads
              WHERE upload_status = 'done'
            )
            UPDATE youtube_uploads u
            SET    upload_status = 'failed',
                   error_message = COALESCE(u.error_message, '') ||
                                   ' [migration 040: demoted as duplicate]'
            FROM   ranked r
            WHERE  u.id = r.id AND r.rn > 1;
            """
        )
    )

    op.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
              ux_youtube_uploads_done_per_episode_channel
            ON youtube_uploads (episode_id, channel_id)
            WHERE upload_status = 'done';
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            "DROP INDEX IF EXISTS ux_youtube_uploads_done_per_episode_channel;"
        )
    )
