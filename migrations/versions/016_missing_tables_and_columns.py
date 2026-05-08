"""Add tables + columns that were missing from migrations.

Historically these were hand-created on the dev DB but never captured in
a migration:

- social_platforms + social_uploads (TikTok / Instagram / X integration)
- video_templates (reusable video composition presets)
- youtube_playlists + youtube_audiobook_uploads
- audiobooks.video_orientation, audiobooks.caption_style_preset
- episodes.override_caption_style

Fresh installs died at runtime with "column episodes.override_caption_style
does not exist" (and similar). This migration makes every path idempotent
with an inspector check so dev DBs that already have these tables are
no-op on upgrade.

Revision ID: 016
Revises: 015
Create Date: 2026-04-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(table)]
    return column in cols


def upgrade() -> None:
    # ── social_platforms ───────────────────────────────────────────────
    if not _has_table("social_platforms"):
        op.create_table(
            "social_platforms",
            sa.Column("platform", sa.Text(), nullable=False),
            sa.Column("account_name", sa.Text(), nullable=True),
            sa.Column("account_id", sa.Text(), nullable=True),
            sa.Column("access_token_encrypted", sa.Text(), nullable=True),
            sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
            sa.Column(
                "token_key_version",
                sa.Integer(),
                server_default=sa.text("1"),
                nullable=False,
            ),
            sa.Column("token_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column(
                "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
            ),
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "platform IN ('tiktok', 'instagram', 'x')",
                name="ck_social_platforms_platform_valid",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_social_platforms"),
        )
        op.create_index(
            "ix_social_platforms_platform", "social_platforms", ["platform"]
        )
        op.create_index(
            "ix_social_platforms_platform_account",
            "social_platforms",
            ["platform", "account_id"],
            unique=True,
        )

    # ── social_uploads ─────────────────────────────────────────────────
    if not _has_table("social_uploads"):
        op.create_table(
            "social_uploads",
            sa.Column("platform_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "content_type",
                sa.Text(),
                server_default=sa.text("'episode'"),
                nullable=False,
            ),
            sa.Column("platform_content_id", sa.Text(), nullable=True),
            sa.Column("platform_url", sa.Text(), nullable=True),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("hashtags", sa.Text(), nullable=True),
            sa.Column(
                "upload_status",
                sa.Text(),
                server_default=sa.text("'pending'"),
                nullable=False,
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("likes", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("comments", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column("shares", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "content_type IN ('episode', 'audiobook')",
                name="ck_social_uploads_content_type_valid",
            ),
            sa.CheckConstraint(
                "upload_status IN ('pending', 'uploading', 'done', 'failed')",
                name="ck_social_uploads_upload_status_valid",
            ),
            sa.ForeignKeyConstraint(
                ["episode_id"],
                ["episodes.id"],
                name="fk_social_uploads_episode_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["platform_id"],
                ["social_platforms.id"],
                name="fk_social_uploads_platform_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_social_uploads"),
        )
        op.create_index(
            "ix_social_uploads_content_type", "social_uploads", ["content_type"]
        )
        op.create_index(
            "ix_social_uploads_episode_id", "social_uploads", ["episode_id"]
        )
        op.create_index(
            "ix_social_uploads_platform_id", "social_uploads", ["platform_id"]
        )

    # ── video_templates ────────────────────────────────────────────────
    if not _has_table("video_templates"):
        op.create_table(
            "video_templates",
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("voice_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("visual_style", sa.Text(), nullable=True),
            sa.Column("scene_mode", sa.Text(), nullable=True),
            sa.Column("caption_style_preset", sa.Text(), nullable=True),
            sa.Column(
                "music_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
            ),
            sa.Column("music_mood", sa.Text(), nullable=True),
            sa.Column(
                "music_volume_db",
                sa.Float(),
                server_default=sa.text("-14.0"),
                nullable=False,
            ),
            sa.Column("audio_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "target_duration_seconds",
                sa.Integer(),
                server_default=sa.text("30"),
                nullable=False,
            ),
            sa.Column("times_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column(
                "is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False
            ),
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["voice_profile_id"],
                ["voice_profiles.id"],
                name="fk_video_templates_voice_profile_id",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_video_templates"),
        )

    # ── youtube_playlists ──────────────────────────────────────────────
    if not _has_table("youtube_playlists"):
        op.create_table(
            "youtube_playlists",
            sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("youtube_playlist_id", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "privacy_status",
                sa.Text(),
                server_default=sa.text("'private'"),
                nullable=False,
            ),
            sa.Column(
                "item_count", sa.Integer(), server_default=sa.text("0"), nullable=False
            ),
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "privacy_status IN ('public', 'unlisted', 'private')",
                name="ck_youtube_playlists_privacy_status_valid",
            ),
            sa.ForeignKeyConstraint(
                ["channel_id"],
                ["youtube_channels.id"],
                name="fk_youtube_playlists_channel_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_youtube_playlists"),
        )
        op.create_index(
            "ix_youtube_playlists_channel_id", "youtube_playlists", ["channel_id"]
        )
        op.create_index(
            "ix_youtube_playlists_youtube_playlist_id",
            "youtube_playlists",
            ["youtube_playlist_id"],
        )

    # ── youtube_audiobook_uploads ──────────────────────────────────────
    if not _has_table("youtube_audiobook_uploads"):
        op.create_table(
            "youtube_audiobook_uploads",
            sa.Column("audiobook_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("youtube_video_id", sa.Text(), nullable=True),
            sa.Column("youtube_url", sa.Text(), nullable=True),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column(
                "privacy_status",
                sa.Text(),
                server_default=sa.text("'private'"),
                nullable=False,
            ),
            sa.Column(
                "upload_status",
                sa.Text(),
                server_default=sa.text("'pending'"),
                nullable=False,
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("playlist_id", sa.Text(), nullable=True),
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "privacy_status IN ('public', 'unlisted', 'private')",
                name="ck_youtube_audiobook_uploads_privacy_status_valid",
            ),
            sa.CheckConstraint(
                "upload_status IN ('pending', 'uploading', 'done', 'failed')",
                name="ck_youtube_audiobook_uploads_upload_status_valid",
            ),
            sa.ForeignKeyConstraint(
                ["audiobook_id"],
                ["audiobooks.id"],
                name="fk_youtube_audiobook_uploads_audiobook_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["channel_id"],
                ["youtube_channels.id"],
                name="fk_youtube_audiobook_uploads_channel_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_youtube_audiobook_uploads"),
        )
        op.create_index(
            "ix_youtube_audiobook_uploads_audiobook_id",
            "youtube_audiobook_uploads",
            ["audiobook_id"],
        )
        op.create_index(
            "ix_youtube_audiobook_uploads_channel_id",
            "youtube_audiobook_uploads",
            ["channel_id"],
        )

    # ── audiobooks column adds ─────────────────────────────────────────
    if not _has_column("audiobooks", "video_orientation"):
        op.add_column(
            "audiobooks",
            sa.Column(
                "video_orientation",
                sa.Text(),
                server_default="landscape",
                nullable=False,
            ),
        )
    if not _has_column("audiobooks", "caption_style_preset"):
        op.add_column(
            "audiobooks", sa.Column("caption_style_preset", sa.Text(), nullable=True)
        )

    # ── episodes column add ────────────────────────────────────────────
    if not _has_column("episodes", "override_caption_style"):
        op.add_column(
            "episodes", sa.Column("override_caption_style", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    # Columns — safe to drop unconditionally (they were always added here)
    if _has_column("episodes", "override_caption_style"):
        op.drop_column("episodes", "override_caption_style")
    if _has_column("audiobooks", "caption_style_preset"):
        op.drop_column("audiobooks", "caption_style_preset")
    if _has_column("audiobooks", "video_orientation"):
        op.drop_column("audiobooks", "video_orientation")

    # Tables
    for t in (
        "social_uploads",
        "social_platforms",
        "youtube_audiobook_uploads",
        "youtube_playlists",
        "video_templates",
    ):
        if _has_table(t):
            op.drop_table(t)
