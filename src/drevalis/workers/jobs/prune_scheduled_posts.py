"""Daily prune of orphaned ``scheduled_posts`` rows.

``ScheduledPost.content_id`` is a polymorphic UUID with no FK (audit
F-DB-09). When a referenced episode or audiobook is deleted, its
scheduled-post rows survive the CASCADE — and the publish cron then
keeps trying to upload content that no longer exists, racking up
upload errors and confusing the calendar UI.

This job walks the pending + scheduled rows once per day and drops
the ones whose parent content row has been deleted. Runs at 03:13
UTC, after the nightly backup, so a backup taken before the prune
still contains the orphaned rows in case the user wants to roll back.
"""

from __future__ import annotations

from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def prune_orphaned_scheduled_posts(ctx: dict[str, Any]) -> dict[str, Any]:
    """Drop scheduled posts whose referenced episode/audiobook is gone."""
    from drevalis.repositories.scheduled_post import ScheduledPostRepository

    session_factory = ctx["session_factory"]
    log = logger.bind(job="prune_orphaned_scheduled_posts")
    log.info("job_start")

    async with session_factory() as session:
        repo = ScheduledPostRepository(session)
        deleted = await repo.prune_orphaned()

    if deleted:
        log.info("orphans_pruned", deleted=deleted)
    else:
        log.debug("no_orphans")
    return {"deleted": deleted}
