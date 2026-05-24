"""Daily purge of long-trashed episodes.

Episodes are soft-deleted (``deleted_at`` set) so a delete is undoable; the
rows + their storage dirs would otherwise accumulate forever. This job
permanently removes episodes that have sat in the trash longer than the
retention window, freeing disk + keeping the table lean. Runs at 03:20 UTC —
after the nightly backup (03:00) so a snapshot still captures the row in case
the user wants it back, and after the scheduled-post prune (03:13).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# How long a trashed episode is kept before permanent removal.
TRASH_RETENTION_DAYS = 30


async def purge_trashed_episodes(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hard-delete episodes trashed more than ``TRASH_RETENTION_DAYS`` ago,
    cleaning up each one's storage directory."""
    from drevalis.core.deps import get_settings
    from drevalis.repositories.episode import EpisodeRepository
    from drevalis.services.storage import LocalStorage

    log = logger.bind(job="purge_trashed_episodes")
    log.info("job_start")

    settings = get_settings()
    storage: LocalStorage = ctx.get("storage") or LocalStorage(settings.storage_base_path)
    cutoff = datetime.now(tz=UTC) - timedelta(days=TRASH_RETENTION_DAYS)

    purged = 0
    async with ctx["session_factory"]() as session:
        repo = EpisodeRepository(session)
        stale = await repo.list_trashed_before(cutoff)
        for episode in stale:
            episode_id = episode.id
            # Best-effort storage cleanup — a missing/locked dir shouldn't
            # block removing the row (otherwise the same row retries nightly).
            try:
                await storage.delete_episode_dir(episode_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("purge_storage_cleanup_failed", episode_id=str(episode_id), error=str(exc))
            await repo.purge(episode_id)
            purged += 1
        if purged:
            await session.commit()

    if purged:
        log.info("trashed_episodes_purged", purged=purged, retention_days=TRASH_RETENTION_DAYS)
    else:
        log.debug("no_stale_trash")
    return {"purged": purged}
