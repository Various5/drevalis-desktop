"""Asset library + reference-image + per-scene source-asset + video-ingest support.

Phase B of the generation overhaul. Introduces a centralised ``assets``
table that can be referenced anywhere in the app (series for style
references, episodes for scene-level overrides, video ingest for the
raw clip that produced a shorts-pipeline episode).

What this migration does:

- Creates ``assets`` with kind enum (image / video / audio / other),
  sha256 hash dedup, dimensions, duration, tags, optional ``user_id``
  FK.
- Creates ``video_ingest_jobs`` to track the analyze-and-pick flow
  (transcribe → candidate clips → episode seed).
- Adds ``reference_asset_ids`` JSONB to both ``series`` and
  ``episodes`` so ComfyUI IPAdapter workflows can consume a list of
  PNG references per run.

Revision ID: 025
Revises: 024
Create Date: 2026-04-22
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from migrations._helpers import has_index, has_table

    # ── assets table ─────────────────────────────────────────────────
    if not has_table("assets"):
        op.create_table(
            "assets",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("filename", sa.Text(), nullable=False),
            sa.Column("file_path", sa.Text(), nullable=False),
            sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("mime_type", sa.Text(), nullable=True),
            sa.Column("hash_sha256", sa.Text(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column(
                "tags",
                postgresql.ARRAY(sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
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
            sa.CheckConstraint(
                "kind IN ('image', 'video', 'audio', 'other')",
                name="ck_assets_kind_valid",
            ),
            # Dedup: same file content uploaded twice should collapse.
            sa.UniqueConstraint("hash_sha256", name="uq_assets_hash_sha256"),
        )
    if not has_index("assets", "ix_assets_kind"):
        op.create_index("ix_assets_kind", "assets", ["kind"])
    if not has_index("assets", "ix_assets_created_at"):
        op.create_index("ix_assets_created_at", "assets", ["created_at"])
    if not has_index("assets", "ix_assets_tags_gin"):
        op.create_index("ix_assets_tags_gin", "assets", ["tags"], postgresql_using="gin")

    # ── video_ingest_jobs: tracks the upload→transcribe→pick flow ────
    if not has_table("video_ingest_jobs"):
        op.create_table(
            "video_ingest_jobs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "asset_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("assets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.Text(), nullable=False, server_default="'queued'"),
            sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stage", sa.Text(), nullable=True),  # transcribing / analyzing / done
            sa.Column("transcript", sa.JSON(), nullable=True),  # word-level from whisper
            sa.Column(
                "candidate_clips",
                sa.JSON(),
                nullable=True,
            ),  # [{start_s, end_s, title, reason, score}]
            sa.Column("selected_clip_index", sa.Integer(), nullable=True),
            sa.Column(
                "resulting_episode_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("episodes.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
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
            sa.CheckConstraint(
                "status IN ('queued', 'running', 'done', 'failed')",
                name="ck_video_ingest_status_valid",
            ),
        )
    if not has_index("video_ingest_jobs", "ix_video_ingest_status"):
        op.create_index("ix_video_ingest_status", "video_ingest_jobs", ["status"])

    # ── reference_asset_ids on series + episodes (IPAdapter conditioning)
    op.add_column(
        "series",
        sa.Column(
            "reference_asset_ids",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column(
        "episodes",
        sa.Column(
            "reference_asset_ids",
            sa.JSON(),
            nullable=True,
        ),
    )

    # ``video_ingest_source_asset_id`` tracks the raw clip that produced
    # an episode via the video-in pipeline (nullable — most episodes
    # originate from a topic prompt, not an uploaded video).
    op.add_column(
        "episodes",
        sa.Column(
            "video_ingest_source_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    from migrations._helpers import has_index, has_table

    op.drop_column("episodes", "video_ingest_source_asset_id")
    op.drop_column("episodes", "reference_asset_ids")
    op.drop_column("series", "reference_asset_ids")
    op.drop_index("ix_video_ingest_status", table_name="video_ingest_jobs")
    if has_table("video_ingest_jobs"):
        op.drop_table("video_ingest_jobs")
    op.drop_index("ix_assets_tags_gin", table_name="assets")
    op.drop_index("ix_assets_created_at", table_name="assets")
    op.drop_index("ix_assets_kind", table_name="assets")
    if has_table("assets"):
        op.drop_table("assets")
