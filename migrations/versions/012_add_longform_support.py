"""Add long-form video generation support.

- series: content_format, longform config columns
- episodes: content_format, chapters, total_duration_seconds
- generation_jobs: chapter/scene granular tracking
- comfyui_servers: max_concurrent_video_jobs
- comfyui_workflows: content_format

Revision ID: 012
Revises: 011
Create Date: 2026-04-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── series ──────────────────────────────────────────────────────────
    op.add_column("series", sa.Column("content_format", sa.String(20), nullable=False, server_default="shorts"))
    op.add_column("series", sa.Column("target_duration_minutes", sa.INTEGER(), nullable=True))
    op.add_column("series", sa.Column("chapter_enabled", sa.BOOLEAN(), nullable=False, server_default="true"))
    op.add_column("series", sa.Column("scenes_per_chapter", sa.INTEGER(), nullable=False, server_default="8"))
    op.add_column("series", sa.Column("transition_style", sa.String(50), nullable=True))
    op.add_column("series", sa.Column("transition_duration", sa.Float(), nullable=False, server_default="0.5"))
    op.add_column("series", sa.Column("duration_match_strategy", sa.String(20), nullable=False, server_default="hold_frame"))
    op.add_column("series", sa.Column("base_seed", sa.INTEGER(), nullable=True))
    op.add_column("series", sa.Column("intro_template", postgresql.JSONB(), nullable=True))
    op.add_column("series", sa.Column("outro_template", postgresql.JSONB(), nullable=True))
    op.add_column("series", sa.Column("visual_consistency_prompt", sa.TEXT(), nullable=True))
    op.add_column("series", sa.Column("aspect_ratio", sa.String(10), nullable=False, server_default="9:16"))

    # ── episodes ────────────────────────────────────────────────────────
    op.add_column("episodes", sa.Column("content_format", sa.String(20), nullable=False, server_default="shorts"))
    op.add_column("episodes", sa.Column("chapters", postgresql.JSONB(), nullable=True))
    op.add_column("episodes", sa.Column("total_duration_seconds", sa.Float(), nullable=True))

    # ── generation_jobs ─────────────────────────────────────────────────
    op.add_column("generation_jobs", sa.Column("chapter_number", sa.INTEGER(), nullable=True))
    op.add_column("generation_jobs", sa.Column("scene_number", sa.INTEGER(), nullable=True))
    op.add_column("generation_jobs", sa.Column("total_items", sa.INTEGER(), nullable=True))
    op.add_column("generation_jobs", sa.Column("completed_items", sa.INTEGER(), nullable=True))

    # ── comfyui_servers ─────────────────────────────────────────────────
    op.add_column("comfyui_servers", sa.Column("max_concurrent_video_jobs", sa.INTEGER(), nullable=True))

    # ── comfyui_workflows ───────────────────────────────────────────────
    op.add_column("comfyui_workflows", sa.Column("content_format", sa.String(20), nullable=False, server_default="any"))


def downgrade() -> None:
    op.drop_column("comfyui_workflows", "content_format")
    op.drop_column("comfyui_servers", "max_concurrent_video_jobs")
    op.drop_column("generation_jobs", "completed_items")
    op.drop_column("generation_jobs", "total_items")
    op.drop_column("generation_jobs", "scene_number")
    op.drop_column("generation_jobs", "chapter_number")
    op.drop_column("episodes", "total_duration_seconds")
    op.drop_column("episodes", "chapters")
    op.drop_column("episodes", "content_format")
    op.drop_column("series", "aspect_ratio")
    op.drop_column("series", "visual_consistency_prompt")
    op.drop_column("series", "outro_template")
    op.drop_column("series", "intro_template")
    op.drop_column("series", "base_seed")
    op.drop_column("series", "duration_match_strategy")
    op.drop_column("series", "transition_duration")
    op.drop_column("series", "transition_style")
    op.drop_column("series", "scenes_per_chapter")
    op.drop_column("series", "chapter_enabled")
    op.drop_column("series", "target_duration_minutes")
    op.drop_column("series", "content_format")
