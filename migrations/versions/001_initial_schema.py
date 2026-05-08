"""Initial schema — all tables, constraints, indexes, triggers.

Revision ID: 001
Revises: None
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 0. Trigger function for auto-updating updated_at ──────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ── 1. voice_profiles ─────────────────────────────────────────────
    op.create_table(
        "voice_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.TEXT(), nullable=False),
        sa.Column("provider", sa.TEXT(), nullable=False),
        sa.Column("piper_model_path", sa.TEXT(), nullable=True),
        sa.Column("piper_speaker_id", sa.TEXT(), nullable=True),
        sa.Column("speed", sa.NUMERIC(), server_default="1.0", nullable=False),
        sa.Column("pitch", sa.NUMERIC(), server_default="1.0", nullable=False),
        sa.Column("elevenlabs_voice_id", sa.TEXT(), nullable=True),
        sa.Column("sample_audio_path", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_profiles")),
        sa.UniqueConstraint("name", name=op.f("uq_voice_profiles_name")),
        sa.CheckConstraint("provider IN ('piper', 'elevenlabs')", name=op.f("ck_voice_profiles_provider_valid")),
    )
    op.execute(
        """
        CREATE TRIGGER trg_voice_profiles_updated_at
            BEFORE UPDATE ON voice_profiles
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ── 2. comfyui_servers ────────────────────────────────────────────
    op.create_table(
        "comfyui_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.TEXT(), nullable=False),
        sa.Column("url", sa.TEXT(), nullable=False),
        sa.Column("api_key_encrypted", sa.TEXT(), nullable=True),
        sa.Column("api_key_version", sa.INTEGER(), server_default="1", nullable=False),
        sa.Column("max_concurrent", sa.INTEGER(), server_default="2", nullable=False),
        sa.Column("is_active", sa.BOOLEAN(), server_default="true", nullable=False),
        sa.Column("last_tested_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comfyui_servers")),
        sa.UniqueConstraint("name", name=op.f("uq_comfyui_servers_name")),
    )
    op.execute(
        """
        CREATE TRIGGER trg_comfyui_servers_updated_at
            BEFORE UPDATE ON comfyui_servers
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ── 3. comfyui_workflows ──────────────────────────────────────────
    op.create_table(
        "comfyui_workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.TEXT(), nullable=False),
        sa.Column("description", sa.TEXT(), nullable=True),
        sa.Column("workflow_json_path", sa.TEXT(), nullable=False),
        sa.Column("version", sa.INTEGER(), server_default="1", nullable=False),
        sa.Column("input_mappings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comfyui_workflows")),
        sa.UniqueConstraint("name", name=op.f("uq_comfyui_workflows_name")),
    )
    op.execute(
        """
        CREATE TRIGGER trg_comfyui_workflows_updated_at
            BEFORE UPDATE ON comfyui_workflows
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ── 4. llm_configs ────────────────────────────────────────────────
    op.create_table(
        "llm_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.TEXT(), nullable=False),
        sa.Column("base_url", sa.TEXT(), nullable=False),
        sa.Column("model_name", sa.TEXT(), nullable=False),
        sa.Column("api_key_encrypted", sa.TEXT(), nullable=True),
        sa.Column("api_key_version", sa.INTEGER(), server_default="1", nullable=False),
        sa.Column("max_tokens", sa.INTEGER(), server_default="4096", nullable=False),
        sa.Column("temperature", sa.NUMERIC(), server_default="0.7", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_configs")),
        sa.UniqueConstraint("name", name=op.f("uq_llm_configs_name")),
    )
    op.execute(
        """
        CREATE TRIGGER trg_llm_configs_updated_at
            BEFORE UPDATE ON llm_configs
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ── 5. prompt_templates ───────────────────────────────────────────
    op.create_table(
        "prompt_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.TEXT(), nullable=False),
        sa.Column("template_type", sa.TEXT(), nullable=False),
        sa.Column("system_prompt", sa.TEXT(), nullable=False),
        sa.Column("user_prompt_template", sa.TEXT(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_templates")),
        sa.UniqueConstraint("name", name=op.f("uq_prompt_templates_name")),
        sa.CheckConstraint(
            "template_type IN ('script', 'visual', 'hook', 'hashtag')",
            name=op.f("ck_prompt_templates_template_type_valid"),
        ),
    )
    op.execute(
        """
        CREATE TRIGGER trg_prompt_templates_updated_at
            BEFORE UPDATE ON prompt_templates
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ── 6. series (depends on voice_profiles, comfyui_*, llm_configs, prompt_templates) ──
    op.create_table(
        "series",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.TEXT(), nullable=False),
        sa.Column("description", sa.TEXT(), nullable=True),
        sa.Column("voice_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comfyui_server_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comfyui_workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("llm_config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("script_prompt_template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("visual_prompt_template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("visual_style", sa.TEXT(), nullable=True),
        sa.Column("character_description", sa.TEXT(), nullable=True),
        sa.Column("target_duration_seconds", sa.INTEGER(), nullable=False),
        sa.Column("default_language", sa.TEXT(), server_default="'en-US'", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_series")),
        sa.UniqueConstraint("name", name=op.f("uq_series_name")),
        sa.ForeignKeyConstraint(
            ["voice_profile_id"], ["voice_profiles.id"],
            name=op.f("fk_series_voice_profile_id_voice_profiles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["comfyui_server_id"], ["comfyui_servers.id"],
            name=op.f("fk_series_comfyui_server_id_comfyui_servers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["comfyui_workflow_id"], ["comfyui_workflows.id"],
            name=op.f("fk_series_comfyui_workflow_id_comfyui_workflows"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["llm_config_id"], ["llm_configs.id"],
            name=op.f("fk_series_llm_config_id_llm_configs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["script_prompt_template_id"], ["prompt_templates.id"],
            name=op.f("fk_series_script_prompt_template_id_prompt_templates"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["visual_prompt_template_id"], ["prompt_templates.id"],
            name=op.f("fk_series_visual_prompt_template_id_prompt_templates"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "target_duration_seconds IN (15, 30, 60)",
            name=op.f("ck_series_target_duration_valid"),
        ),
    )
    op.execute(
        """
        CREATE TRIGGER trg_series_updated_at
            BEFORE UPDATE ON series
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ── 7. episodes (depends on series, voice_profiles, llm_configs) ──
    op.create_table(
        "episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.TEXT(), nullable=False),
        sa.Column("topic", sa.TEXT(), nullable=True),
        sa.Column("status", sa.TEXT(), server_default="'draft'", nullable=False),
        sa.Column("script", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("base_path", sa.TEXT(), nullable=True),
        sa.Column("generation_log", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("override_voice_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("override_llm_config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episodes")),
        sa.ForeignKeyConstraint(
            ["series_id"], ["series.id"],
            name=op.f("fk_episodes_series_id_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["override_voice_profile_id"], ["voice_profiles.id"],
            name=op.f("fk_episodes_override_voice_profile_id_voice_profiles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["override_llm_config_id"], ["llm_configs.id"],
            name=op.f("fk_episodes_override_llm_config_id_llm_configs"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'generating', 'review', 'editing', 'exported', 'failed')",
            name=op.f("ck_episodes_status_valid"),
        ),
    )
    op.create_index("ix_episodes_series_id_status", "episodes", ["series_id", "status"])
    op.create_index("ix_episodes_status", "episodes", ["status"])
    op.execute(
        """
        CREATE TRIGGER trg_episodes_updated_at
            BEFORE UPDATE ON episodes
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ── 8. generation_jobs (depends on episodes) ──────────────────────
    op.create_table(
        "generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step", sa.TEXT(), nullable=False),
        sa.Column("status", sa.TEXT(), server_default="'queued'", nullable=False),
        sa.Column("progress_pct", sa.INTEGER(), server_default="0", nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.TEXT(), nullable=True),
        sa.Column("retry_count", sa.INTEGER(), server_default="0", nullable=False),
        sa.Column("worker_id", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generation_jobs")),
        sa.ForeignKeyConstraint(
            ["episode_id"], ["episodes.id"],
            name=op.f("fk_generation_jobs_episode_id_episodes"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "step IN ('script', 'voice', 'scenes', 'captions', 'assembly', 'thumbnail')",
            name=op.f("ck_generation_jobs_step_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name=op.f("ck_generation_jobs_status_valid"),
        ),
    )
    op.create_index("ix_generation_jobs_episode_id", "generation_jobs", ["episode_id"])
    op.create_index("ix_generation_jobs_status", "generation_jobs", ["status"])
    op.execute(
        """
        CREATE TRIGGER trg_generation_jobs_updated_at
            BEFORE UPDATE ON generation_jobs
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # ── 9. media_assets (depends on episodes, generation_jobs) ────────
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_type", sa.TEXT(), nullable=False),
        sa.Column("file_path", sa.TEXT(), nullable=False),
        sa.Column("file_size_bytes", sa.BIGINT(), nullable=True),
        sa.Column("duration_seconds", sa.NUMERIC(), nullable=True),
        sa.Column("scene_number", sa.INTEGER(), nullable=True),
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_assets")),
        sa.ForeignKeyConstraint(
            ["episode_id"], ["episodes.id"],
            name=op.f("fk_media_assets_episode_id_episodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generation_job_id"], ["generation_jobs.id"],
            name=op.f("fk_media_assets_generation_job_id_generation_jobs"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "asset_type IN ('voiceover', 'scene', 'caption', 'video', 'thumbnail', 'temp')",
            name=op.f("ck_media_assets_asset_type_valid"),
        ),
    )
    op.create_index("ix_media_assets_episode_id", "media_assets", ["episode_id"])
    op.create_index("ix_media_assets_episode_id_asset_type", "media_assets", ["episode_id", "asset_type"])


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("media_assets")

    op.execute("DROP TRIGGER IF EXISTS trg_generation_jobs_updated_at ON generation_jobs;")
    op.drop_table("generation_jobs")

    op.execute("DROP TRIGGER IF EXISTS trg_episodes_updated_at ON episodes;")
    op.drop_table("episodes")

    op.execute("DROP TRIGGER IF EXISTS trg_series_updated_at ON series;")
    op.drop_table("series")

    op.execute("DROP TRIGGER IF EXISTS trg_prompt_templates_updated_at ON prompt_templates;")
    op.drop_table("prompt_templates")

    op.execute("DROP TRIGGER IF EXISTS trg_llm_configs_updated_at ON llm_configs;")
    op.drop_table("llm_configs")

    op.execute("DROP TRIGGER IF EXISTS trg_comfyui_workflows_updated_at ON comfyui_workflows;")
    op.drop_table("comfyui_workflows")

    op.execute("DROP TRIGGER IF EXISTS trg_comfyui_servers_updated_at ON comfyui_servers;")
    op.drop_table("comfyui_servers")

    op.execute("DROP TRIGGER IF EXISTS trg_voice_profiles_updated_at ON voice_profiles;")
    op.drop_table("voice_profiles")

    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
