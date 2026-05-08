"""arq WorkerSettings for Drevalis.

This module is the arq entry point.  It imports all job functions from
their respective sub-modules and wires them into ``WorkerSettings``.

Usage::

    arq drevalis.workers.settings.WorkerSettings
"""

from __future__ import annotations

from arq import cron, func
from arq.connections import RedisSettings

from drevalis.core.config import Settings
from drevalis.workers.jobs.ab_test_winner import compute_ab_test_winners
from drevalis.workers.jobs.audiobook import (
    generate_ai_audiobook,
    generate_audiobook,
    generate_script_async,
    regenerate_audiobook_chapter,
    regenerate_audiobook_chapter_image,
)
from drevalis.workers.jobs.backup import restore_backup_async, scheduled_backup
from drevalis.workers.jobs.edit_render import render_from_edit

# ---------------------------------------------------------------------------
# Job function imports
# ---------------------------------------------------------------------------
from drevalis.workers.jobs.episode import (
    generate_episode,
    reassemble_episode,
    regenerate_scene,
    regenerate_voice,
    retry_episode_step,
)
from drevalis.workers.jobs.heartbeat import worker_heartbeat
from drevalis.workers.jobs.license_heartbeat import license_heartbeat
from drevalis.workers.jobs.music import generate_episode_music
from drevalis.workers.jobs.prune_scheduled_posts import prune_orphaned_scheduled_posts
from drevalis.workers.jobs.runpod import auto_deploy_runpod_pod
from drevalis.workers.jobs.scheduled import publish_scheduled_posts
from drevalis.workers.jobs.seo import generate_seo_async
from drevalis.workers.jobs.series import generate_series_async
from drevalis.workers.jobs.social import publish_pending_social_uploads
from drevalis.workers.jobs.video_ingest import (
    analyze_video_ingest,
    commit_video_ingest_clip,
)

# ---------------------------------------------------------------------------
# Lifecycle hook imports
# ---------------------------------------------------------------------------
from drevalis.workers.lifecycle import on_job_start, shutdown, startup

# ---------------------------------------------------------------------------
# Redis settings helper
# ---------------------------------------------------------------------------


def _redis_settings_from_config() -> RedisSettings:
    """Parse the application Redis URL into arq ``RedisSettings``."""
    settings = Settings()
    url = settings.redis_url  # e.g. "redis://localhost:6379/0"

    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379

    # Database number from path (e.g. "/0")
    database = 0
    if parsed.path and parsed.path.strip("/"):
        try:
            database = int(parsed.path.strip("/"))
        except ValueError:
            database = 0

    password = parsed.password

    # Modest bump over arq's defaults (1s timeout, 5×1s retries =
    # ~6s) so Redis getting slammed during a fresh boot doesn't
    # immediately crash the worker. Total worst case ~35s — fits
    # comfortably inside the 30s ``start_period`` *plus* a restart
    # cycle if compose chooses to retry. Going much higher just
    # delays the eventual crash without making it less likely.
    return RedisSettings(
        host=host,
        port=port,
        database=database,
        password=password,
        conn_timeout=5,
        conn_retries=5,
        conn_retry_delay=2,
    )


# ---------------------------------------------------------------------------
# arq WorkerSettings
# ---------------------------------------------------------------------------


class WorkerSettings:
    """arq worker configuration.

    Discovered by::

        arq drevalis.workers.settings.WorkerSettings
    """

    # Long-running jobs (pipeline, audiobook generation, music gen) inherit
    # the global ``job_timeout`` below — those legitimately run for hours.
    # Short admin/cron jobs are wrapped with ``func(...)`` so a stuck call
    # can't squat on a worker slot for the full longform window.
    _SHORT_TIMEOUT = 120  # 2 min — heartbeat, scheduled-publish per tick
    _MEDIUM_TIMEOUT = 900  # 15 min — SEO LLM, social-publish batch
    functions = [
        generate_episode,
        generate_audiobook,
        generate_ai_audiobook,
        regenerate_audiobook_chapter,
        regenerate_audiobook_chapter_image,
        retry_episode_step,
        reassemble_episode,
        regenerate_voice,
        regenerate_scene,
        generate_script_async,
        generate_series_async,
        generate_episode_music,
        func(generate_seo_async, timeout=_MEDIUM_TIMEOUT),
        func(publish_scheduled_posts, timeout=_MEDIUM_TIMEOUT),
        func(publish_pending_social_uploads, timeout=_MEDIUM_TIMEOUT),
        func(compute_ab_test_winners, timeout=_MEDIUM_TIMEOUT),
        auto_deploy_runpod_pod,
        func(worker_heartbeat, timeout=_SHORT_TIMEOUT),
        func(license_heartbeat, timeout=_SHORT_TIMEOUT),
        scheduled_backup,
        restore_backup_async,
        analyze_video_ingest,
        commit_video_ingest_clip,
        render_from_edit,
        prune_orphaned_scheduled_posts,
    ]
    cron_jobs = [
        # Check for due scheduled posts every 5 minutes
        cron(publish_scheduled_posts, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        # TikTok / (future) IG / X direct uploads — also every 5 minutes
        cron(publish_pending_social_uploads, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        # Write worker heartbeat every minute so the API can detect dead workers
        cron(worker_heartbeat, minute=set(range(60))),
        # License heartbeat — once per day at 04:17 UTC (off-peak, arbitrary).
        cron(license_heartbeat, hour={4}, minute={17}),
        # A/B winner settle — once per day at 04:31 UTC. Only touches
        # pairs where both episodes have been live on YouTube for 7+
        # days, so it's cheap (no-op until pairs mature).
        cron(compute_ab_test_winners, hour={4}, minute={31}),
        # Nightly full-install backup at 03:00 UTC. The job itself checks
        # backup_auto_enabled and no-ops when disabled, so it's safe to
        # register unconditionally.
        cron(scheduled_backup, hour={3}, minute={0}),
        # Drop scheduled_posts rows whose episode/audiobook was deleted.
        # 03:13 UTC — runs after the backup so the orphan rows are still
        # captured in the nightly snapshot in case rollback is needed.
        cron(prune_orphaned_scheduled_posts, hour={3}, minute={13}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    on_job_start = on_job_start

    redis_settings = _redis_settings_from_config()

    # Concurrency: max 4 episodes generating in parallel
    max_jobs = 8

    # Hard timeout per pipeline run. Long-form episodes legitimately
    # take hours on slow GPU hardware — read the configured ceiling
    # instead of hardcoding the shorts value.
    from drevalis.core.config import Settings as _Settings

    _settings_for_timeout = _Settings()
    job_timeout = int(getattr(_settings_for_timeout, "longform_job_timeout", 14400))

    # Retry configuration
    retry_jobs = True
    max_tries = 3

    # Log results
    keep_result = 3600  # keep results for 1 hour
    keep_result_forever = False
