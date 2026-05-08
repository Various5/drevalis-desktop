"""Scheduled backup arq job.

Runs once per day at 03:00 UTC when ``BACKUP_AUTO_ENABLED=true``. Creates
a tarball in ``BACKUP_DIRECTORY`` and prunes older archives beyond
``BACKUP_RETENTION``. Failures are logged but not fatal - the worker
keeps running; the user sees the most recent successful archive in the
Settings / Backup tab.
"""

from __future__ import annotations

from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def scheduled_backup(ctx: dict[str, Any]) -> dict[str, Any]:
    from drevalis.core.config import Settings
    from drevalis.services.updates import _resolve_current_version

    settings = Settings()
    if not settings.backup_auto_enabled:
        logger.debug("scheduled_backup_disabled")
        return {"skipped": "disabled"}

    session_factory = ctx["session_factory"]

    from drevalis.services.backup import BackupService

    svc = BackupService(
        storage_base_path=settings.storage_base_path,
        backup_directory=settings.backup_directory,
        encryption_key=settings.encryption_key,
        app_version=_resolve_current_version(),
    )

    try:
        async with session_factory() as session:
            archive = await svc.create_backup(session)
        removed = svc.prune(settings.backup_retention)
        logger.info(
            "scheduled_backup_ok",
            archive=archive.name,
            size_bytes=archive.stat().st_size,
            pruned=len(removed),
        )
        return {
            "status": "ok",
            "archive": archive.name,
            "size_bytes": archive.stat().st_size,
            "pruned": removed,
        }
    except Exception as exc:  # noqa: BLE001 - background job; log + move on
        logger.error("scheduled_backup_failed", error=str(exc)[:200], exc_info=True)
        return {"status": "failed", "error": str(exc)[:200]}


# ── Restore (manual, kicked off from Settings → Backup → Restore) ──────


async def restore_backup_async(
    ctx: dict[str, Any],
    job_id: str,
    archive_path: str,
    *,
    allow_key_mismatch: bool = False,
    restore_db: bool = True,
    restore_media: bool = True,
    delete_archive_when_done: bool = True,
) -> dict[str, Any]:
    """Restore a previously-uploaded or pre-existing archive.

    Two call paths:

    1. **Browser upload** — the route streams the multipart body to a
       temp file under BACKUP_DIRECTORY and enqueues this job with
       ``delete_archive_when_done=True`` (default). The temp file is
       removed in the ``finally`` block whether the restore succeeded
       or not.
    2. **From-existing archive** (multi-GB-friendly path) — the route
       resolves a filename already in BACKUP_DIRECTORY and enqueues
       with ``delete_archive_when_done=False``. The original archive
       is kept so the operator can retry the same restore without
       re-uploading the 22GB body.

    Progress + final status are written to Redis at
    ``backup:restore:{job_id}`` so the UI can poll without a long-lived
    HTTP connection.
    """
    import json as _json
    from pathlib import Path

    from drevalis.core.config import Settings
    from drevalis.services.backup import BackupError, BackupService
    from drevalis.services.updates import _resolve_current_version

    structlog.contextvars.bind_contextvars(restore_job_id=job_id)
    logger.info("restore_backup_async.start", archive=archive_path)

    settings = Settings()
    # Use the worker's arq Redis pool from ctx — the API-side
    # ``get_pool()`` isn't initialised in the worker process, so a
    # naive ``Redis(connection_pool=get_pool())`` raises
    # "Redis connection pool is not initialised" at the first set().
    redis = ctx["redis"]
    status_key = f"backup:restore:{job_id}"

    async def _write_status(payload: dict[str, Any]) -> None:
        # 1h TTL — UI typically polls within 30s of completion; the key
        # cleans itself up so a forgotten job doesn't haunt Redis.
        await redis.set(status_key, _json.dumps(payload), ex=3600)

    async def _progress(stage: str, pct: int, message: str) -> None:
        await _write_status(
            {
                "status": "running",
                "stage": stage,
                "progress_pct": pct,
                "message": message,
            }
        )

    archive = Path(archive_path)
    session_factory = ctx["session_factory"]

    try:
        await _write_status(
            {
                "status": "running",
                "stage": "starting",
                "progress_pct": 0,
                "message": "Restore starting…",
            }
        )

        svc = BackupService(
            storage_base_path=settings.storage_base_path,
            backup_directory=settings.backup_directory,
            encryption_key=settings.encryption_key,
            app_version=_resolve_current_version(),
        )

        async with session_factory() as session:
            result = await svc.restore_backup(
                session,
                archive,
                allow_key_mismatch=allow_key_mismatch,
                restore_db=restore_db,
                restore_media=restore_media,
                progress_cb=_progress,
            )

        rows_total = sum(result.get("rows_inserted", {}).values())
        storage_count = len(result.get("storage_paths_restored", []))
        await _write_status(
            {
                "status": "done",
                "stage": "done",
                "progress_pct": 100,
                "message": (f"Restored {rows_total} rows + {storage_count} storage dirs."),
                "result": result,
            }
        )
        logger.info(
            "restore_backup_async.done",
            rows=rows_total,
            storage_dirs=storage_count,
        )
        return {"status": "done", "result": result}

    except BackupError as exc:
        await _write_status(
            {
                "status": "failed",
                "stage": "failed",
                "progress_pct": 0,
                "message": str(exc),
                "error": str(exc),
            }
        )
        logger.warning("restore_backup_async.invalid", error=str(exc))
        return {"status": "failed", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        await _write_status(
            {
                "status": "failed",
                "stage": "failed",
                "progress_pct": 0,
                "message": f"Restore failed: {exc}",
                "error": str(exc)[:500],
            }
        )
        logger.error("restore_backup_async.failed", error=str(exc)[:200], exc_info=True)
        return {"status": "failed", "error": str(exc)[:500]}
    finally:
        if delete_archive_when_done:
            try:
                archive.unlink(missing_ok=True)
            except OSError:
                logger.debug("restore_archive_cleanup_failed", path=str(archive))
        # Bust the storage_probe cache so the next Backup-tab load shows
        # live post-restore state rather than the pre-restore snapshot
        # the route may have cached up to 5 minutes earlier. We do this
        # whether the restore succeeded or failed — a partially-applied
        # restore can leave the storage tree in a state the operator
        # needs fresh signal on. Best-effort: a Redis hiccup here just
        # means the cache expires naturally.
        from drevalis.core.cache_keys import STORAGE_PROBE_CACHE_KEY

        try:
            await redis.delete(STORAGE_PROBE_CACHE_KEY)
        except Exception:
            logger.debug("storage_probe_cache_bust_failed", exc_info=True)
        # ``redis`` is the worker's shared arq pool (ctx["redis"]) — do
        # NOT close it here; arq owns the lifecycle.
