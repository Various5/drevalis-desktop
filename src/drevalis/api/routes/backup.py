"""Backup + restore API routes.

Endpoints
---------
- ``GET  /api/v1/backup``             list archives in BACKUP_DIRECTORY
- ``POST /api/v1/backup``             create a new archive, return metadata
- ``GET  /api/v1/backup/{filename}``  download an existing archive
- ``DEL  /api/v1/backup/{filename}``  delete an archive
- ``POST /api/v1/backup/restore``     upload an archive and restore it

The restore endpoint is destructive: it truncates every user table and
overwrites storage files. The frontend gates it behind a typed-confirm
dialog; the backend still demands ``X-Confirm-Restore: i-understand`` on
every call so a bug in the UI can't wipe the DB.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession  # runtime import — required

# for FastAPI to resolve ``Annotated[AsyncSession, Depends(get_db)]``
# into a dependency instead of a query parameter. ``from __future__
# import annotations`` turns annotations into strings, so the
# previous TYPE_CHECKING-only import made FastAPI fall back to
# treating ``db`` as a query param, producing 422 on every request.
from drevalis.core.cache_keys import STORAGE_PROBE_CACHE_KEY
from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_redis, get_settings
from drevalis.services.backup import BackupService
from drevalis.services.media_repair import repair_media_links

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/backup", tags=["backup"])

# Storage probe is expensive (samples media_assets across 5 asset types
# + reads first byte of each file). Caching for 5 min keeps the Backup
# tab snappy after the first hit; the operator can hit refresh with
# ``?force=true`` to recompute. The cache key lives in
# ``core/cache_keys`` so the worker that runs a restore can bust it
# from the other side without an api → workers import.
_STORAGE_PROBE_CACHE_KEY = STORAGE_PROBE_CACHE_KEY
_STORAGE_PROBE_CACHE_TTL_S = 300


def _service(settings: Settings) -> BackupService:
    from drevalis.services.updates import _resolve_current_version

    return BackupService(
        storage_base_path=settings.storage_base_path,
        backup_directory=settings.backup_directory,
        encryption_key=settings.encryption_key,
        app_version=_resolve_current_version(),
    )


def _safe_backup_path(settings: Settings, filename: str) -> Path:
    """Resolve *filename* inside the configured backup directory.

    Refuses anything containing path separators or resolving outside the
    directory (CVE-class path-traversal guard on a user-provided name).
    """
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid filename",
        )
    root = settings.backup_directory.resolve()
    candidate = (root / filename).resolve()
    if not str(candidate).startswith(str(root)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filename escapes backup directory",
        )
    return candidate


# ── List ─────────────────────────────────────────────────────────────────


@router.get("", summary="List existing backup archives")
async def list_backups(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    svc = _service(settings)
    backup_dir_abs = settings.backup_directory.resolve()
    host_source = _detect_host_source(backup_dir_abs)
    # When the backup dir resolves inside the bind-mounted storage_base,
    # try to also give the caller an absolute container path so the UI can
    # render both the container-side and host-side locations.
    return {
        "backup_directory": str(settings.backup_directory),
        "backup_directory_abs": str(backup_dir_abs),
        # Host path as reported by ``/proc/self/mountinfo``. On Docker
        # Desktop for Windows/macOS this is the Linux-VM label (e.g.
        # ``/project/storage/backups``) — still useful because the UI
        # can translate that to ``%USERPROFILE%\Drevalis\storage\backups``
        # in the explanation text. None on Windows hosts / restricted
        # containers where mountinfo isn't readable.
        "backup_directory_host_source": host_source,
        "retention": settings.backup_retention,
        "auto_enabled": settings.backup_auto_enabled,
        "archives": svc.list_backups(),
    }


# ── Create ───────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a new backup")
async def create_backup(
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Settings = Depends(get_settings),
    include_media: bool = True,
) -> dict[str, object]:
    svc = _service(settings)
    try:
        archive = await svc.create_backup(db, include_media=include_media)
    except Exception as exc:  # noqa: BLE001 - surface to UI
        logger.error("backup_create_failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"backup failed: {exc}",
        ) from exc
    # Prune old archives per retention policy so disk usage stays bounded.
    removed = svc.prune(settings.backup_retention)
    return {
        "filename": archive.name,
        "size_bytes": archive.stat().st_size,
        "pruned": removed,
    }


# ── Download ─────────────────────────────────────────────────────────────


@router.get("/{filename}", summary="Download an archive")
async def download_backup(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    path = _safe_backup_path(settings, filename)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backup not found")
    return FileResponse(
        path,
        media_type="application/gzip",
        filename=filename,
    )


# ── Delete ───────────────────────────────────────────────────────────────


@router.delete(
    "/{filename}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an archive",
)
async def delete_backup(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> None:
    path = _safe_backup_path(settings, filename)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backup not found")
    path.unlink()


async def _seed_restore_status(job_id: str) -> None:
    """Write a placeholder ``queued`` status before the worker picks up.

    The frontend polls ``GET /restore-status/{job_id}`` every 2s and treats
    a missing Redis key as ``unknown`` (terminal — clears localStorage and
    surfaces a toast). Without this seed there is a race window between
    ``enqueue_job`` returning and the worker writing its first
    ``starting`` status; if the first poll lands inside that window the
    UI bails out instantly even though the restore is healthy.

    Seeding ``queued`` here turns that into a normal queued → running →
    done flow with no UI flicker. TTL matches the worker's status TTL
    (1h) so a never-picked-up job still self-cleans.
    """
    import json as _json

    from redis.asyncio import Redis

    from drevalis.core.redis import get_pool

    redis = Redis(connection_pool=get_pool())
    try:
        await redis.set(
            f"backup:restore:{job_id}",
            _json.dumps(
                {
                    "status": "queued",
                    "stage": "queued",
                    "progress_pct": 0,
                    "message": "Waiting for worker to pick up the restore job…",
                }
            ),
            ex=3600,
        )
    finally:
        await redis.aclose()


# ── Restore (destructive) ────────────────────────────────────────────────


@router.post(
    "/restore",
    summary="Restore from an uploaded archive (DESTRUCTIVE)",
    description=(
        "Truncates all user tables and overwrites storage files with the "
        "contents of the uploaded archive. Must include the header "
        "`X-Confirm-Restore: i-understand` to succeed."
    ),
)
async def restore_backup(
    file: UploadFile = File(...),
    confirm: str = Header(..., alias="X-Confirm-Restore"),
    allow_key_mismatch: bool = False,
    restore_db: bool = True,
    restore_media: bool = True,
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Upload an archive and enqueue a background restore job.

    The multipart upload streams to a temp file synchronously (the
    HTTP body has to fully arrive before we can enqueue), then a
    background ``restore_backup_async`` job does the heavy work. The
    response carries a ``job_id`` that the UI polls at
    ``GET /api/v1/backup/restore-status/{job_id}`` for stage +
    progress_pct, so a 21GB+ restore doesn't sit on a single HTTP
    connection while extracting + truncating + reinserting + copying.
    """
    if confirm != "i-understand":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing or invalid X-Confirm-Restore header",
        )
    if not file.filename or not file.filename.endswith(".tar.gz"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expected a .tar.gz archive",
        )

    import tempfile
    from uuid import uuid4

    from drevalis.core.redis import get_arq_pool

    job_id = str(uuid4())
    await _seed_restore_status(job_id)

    # Land the upload in BACKUP_DIRECTORY rather than /tmp so worker +
    # API share the same path even when /tmp is per-container scratch.
    settings.backup_directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        suffix=".tar.gz",
        prefix=f"restore-{job_id}-",
        dir=str(settings.backup_directory),
    )
    import os as _os

    _os.close(fd)
    tmp = Path(tmp_str)

    try:
        with tmp.open("wb") as f:
            while chunk := await file.read(4 * 1024 * 1024):
                f.write(chunk)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    arq = get_arq_pool()
    await arq.enqueue_job(
        "restore_backup_async",
        job_id,
        str(tmp),
        allow_key_mismatch=allow_key_mismatch,
        restore_db=restore_db,
        restore_media=restore_media,
        delete_archive_when_done=True,
    )
    logger.info(
        "restore_enqueued",
        job_id=job_id,
        archive_path=str(tmp),
        size_mb=round(tmp.stat().st_size / (1024 * 1024), 1),
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "message": (
            f"Restore enqueued. Poll GET /api/v1/backup/restore-status/{job_id} for progress."
        ),
    }


@router.post(
    "/restore-existing/{filename}",
    summary="Restore from an archive already in BACKUP_DIRECTORY (no upload)",
    description=(
        "Skips the multi-GB upload path entirely. The archive must already "
        "exist in BACKUP_DIRECTORY (e.g. placed via docker cp or a host "
        "bind-mount). Same X-Confirm-Restore + restore_db / restore_media "
        "flags as POST /restore. The original archive is kept on disk."
    ),
)
async def restore_from_existing(
    filename: str,
    confirm: str = Header(..., alias="X-Confirm-Restore"),
    allow_key_mismatch: bool = False,
    restore_db: bool = True,
    restore_media: bool = True,
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Enqueue a restore against an existing archive in BACKUP_DIRECTORY.

    Why this exists: a 22GB browser upload through nginx / Docker /
    Cloudflare hits proxy timeouts long before the body finishes, and
    a single navigation in the operator's browser tab kills the XHR.
    Operators with multi-GB archives place the file via
    ``docker cp drevalis-app-1:/app/storage/backups/<name>.tar.gz``
    or directly into the host-mounted ``BACKUP_DIRECTORY``, then pick
    it from the dropdown — zero upload, instant enqueue.
    """
    if confirm != "i-understand":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing or invalid X-Confirm-Restore header",
        )

    archive_path = _safe_backup_path(settings, filename)
    if not archive_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"backup not found in BACKUP_DIRECTORY: {filename}",
        )
    if not filename.endswith(".tar.gz"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expected a .tar.gz archive",
        )

    from uuid import uuid4

    from drevalis.core.redis import get_arq_pool

    job_id = str(uuid4())
    await _seed_restore_status(job_id)
    arq = get_arq_pool()
    await arq.enqueue_job(
        "restore_backup_async",
        job_id,
        str(archive_path),
        allow_key_mismatch=allow_key_mismatch,
        restore_db=restore_db,
        restore_media=restore_media,
        delete_archive_when_done=False,
    )
    logger.info(
        "restore_existing_enqueued",
        job_id=job_id,
        archive=filename,
        size_mb=round(archive_path.stat().st_size / (1024 * 1024), 1),
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "filename": filename,
        "message": (
            f"Restore enqueued from existing archive. Poll "
            f"GET /api/v1/backup/restore-status/{job_id} for progress."
        ),
    }


@router.get(
    "/restore-status/{job_id}",
    summary="Poll the status of an in-flight restore job",
)
async def get_restore_status(job_id: str) -> dict[str, Any]:
    """Return the latest progress payload written by the worker.

    Possible ``status`` values: ``queued`` (job submitted but worker
    hasn't started), ``running`` (in-flight; ``stage`` and
    ``progress_pct`` populated), ``done``, ``failed``, or ``unknown``
    (TTL expired or job_id never existed).
    """
    import json

    from redis.asyncio import Redis

    from drevalis.core.redis import get_pool

    redis = Redis(connection_pool=get_pool())
    try:
        raw = await redis.get(f"backup:restore:{job_id}")
    finally:
        await redis.aclose()

    if raw is None:
        return {
            "job_id": job_id,
            "status": "unknown",
            "message": (
                "No status for this job_id (TTL expired, never existed, "
                "or worker hasn't picked it up yet)."
            ),
        }
    text = raw if isinstance(raw, str) else raw.decode()
    payload: dict[str, Any] = json.loads(text)
    payload["job_id"] = job_id
    return payload


def _detect_mount_fs(path: Path) -> str | None:
    """Return the filesystem type backing *path* (``ext4``, ``cifs``,
    ``nfs``, ``overlay`` …) by reading ``/proc/mounts`` — or ``None``
    when that isn't readable (Windows, restricted containers).
    """
    try:
        mounts = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    path_str = str(path)
    best: tuple[int, str] | None = None
    for line in mounts:
        parts = line.split()
        if len(parts) < 3:
            continue
        mount_point = parts[1]
        fs_type = parts[2]
        if path_str == mount_point or path_str.startswith(mount_point.rstrip("/") + "/"):
            depth = len(mount_point)
            if best is None or depth > best[0]:
                best = (depth, fs_type)
    return best[1] if best else None


def _detect_host_source(path: Path) -> str | None:
    """Return the host path that ``path`` maps back to via Docker's
    bind-mount — read from ``/proc/self/mountinfo``. Answers the
    question "I'm inside the container at ``/app/storage``; where is
    that on my actual hard disk?". Returns ``None`` when we can't
    read mountinfo (Windows host, restricted container).

    mountinfo line shape (simplified)::

        36 35 253:0 /data /app/storage rw,relatime shared:1 - ext4 /dev/sda1 rw
                     ^^^^^ ^^^^^^^^^^^                     ^^^ ^^^^^^^^^^^
                     root  mount point                     fs  source

    field[3] is the path *within* the source filesystem that was
    mounted (for a bind mount, this is the host-side absolute path
    when the namespace lets us see it). On Docker Desktop for
    Windows / macOS this is the path inside the Linux VM, not the
    host Windows / macOS path — so we surface it with a caveat in
    the hint text.
    """
    try:
        raw = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    path_str = str(path)
    best: tuple[int, str] | None = None
    for line in raw:
        parts = line.split()
        # Need at least ``id parent_id major:minor root mount_point opts``
        if len(parts) < 5:
            continue
        root = parts[3]
        mount_point = parts[4]
        if path_str == mount_point or path_str.startswith(mount_point.rstrip("/") + "/"):
            # For paths deeper than the mount point, append the remainder.
            tail = path_str[len(mount_point) :]
            source = root.rstrip("/") + (
                tail if tail.startswith("/") else "/" + tail if tail else ""
            )
            depth = len(mount_point)
            if best is None or depth > best[0]:
                best = (depth, source)
    return best[1] if best else None


# ── Storage probe (diagnose "can't see videos / images") ─────────────────


@router.get(
    "/storage-probe",
    summary="Probe the storage mount + serve path for common post-restore issues",
)
async def storage_probe(
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
    force: Annotated[
        bool,
        Query(description="Bypass the 5-minute cache and recompute now."),
    ] = False,
) -> dict[str, object]:
    """Return a focused diagnostic for each of: does the app see the
    right ``storage_base_path``? are the files readable by the Python
    process that's going to serve them? is the storage directory a
    symlink (StaticFiles mounts are ``follow_symlink=False``)? does
    the auth middleware guard ``/storage/*``?

    The frontend's Backup section renders the output as a checklist
    so the user can tell at a glance which layer is broken.

    Result is cached in Redis for 5 minutes so repeat loads of the
    Backup tab are instant — the probe walks media_assets and reads
    the first byte of each sample file, which is multi-second on
    installs with millions of assets. Pass ``?force=true`` to
    recompute on demand.
    """
    # Try the cache first unless the operator asked for a fresh
    # compute. Redis hiccups fall through to a live recompute.
    if not force:
        try:
            cached = await redis.get(_STORAGE_PROBE_CACHE_KEY)
        except Exception:
            cached = None
        if cached:
            try:
                payload: dict[str, Any] = json.loads(
                    cached if isinstance(cached, str) else cached.decode()
                )
                payload["cached"] = True
                return payload
            except (json.JSONDecodeError, ValueError):
                # Malformed cache — drop it and recompute below.
                pass

    report = await _compute_storage_probe_report(db, settings)
    report["cached"] = False
    report["cached_at"] = datetime.now(tz=UTC).isoformat()

    # Best-effort cache write. A Redis hiccup here just means the
    # next request will recompute — better than 500ing the response.
    try:
        await redis.setex(
            _STORAGE_PROBE_CACHE_KEY,
            _STORAGE_PROBE_CACHE_TTL_S,
            json.dumps(report),
        )
    except Exception:
        logger.debug("storage_probe.cache_write_failed", exc_info=True)
    return report


async def _compute_storage_probe_report(db: AsyncSession, settings: Settings) -> dict[str, Any]:
    """Walk the storage tree + sample media_assets to build the probe
    report. Pulled out of the route handler so the route can cache
    the result without duplicating the diagnostic logic."""
    import os

    from sqlalchemy import func, select

    from drevalis.models.media_asset import MediaAsset

    storage_base = settings.storage_base_path.resolve()
    episodes_dir = (storage_base / "episodes").resolve()
    audiobooks_dir = (storage_base / "audiobooks").resolve()

    # Shallow listing of whatever the container actually sees at the
    # top level of storage_base. The user's most common confusion is
    # "I copied 20 GB into the host directory, why does the app show
    # nothing?" — when the bind source actually points somewhere else.
    # Showing the real entries side-by-side with what they expect
    # collapses that debugging session to a single glance.
    top_level_entries: list[dict[str, Any]] = []
    total_visible_bytes = 0
    total_visible_count = 0
    if storage_base.exists() and storage_base.is_dir():
        try:
            for child in sorted(storage_base.iterdir(), key=lambda p: p.name.lower())[:50]:
                info: dict[str, Any] = {"name": child.name}
                try:
                    if child.is_file():
                        info["kind"] = "file"
                        info["size_bytes"] = child.stat().st_size
                        total_visible_bytes += info["size_bytes"]
                        total_visible_count += 1
                    elif child.is_dir():
                        # Shallow child count — avoid walking 20 GB just
                        # to show a dashboard. Truthful but bounded.
                        subcount = 0
                        for _ in child.iterdir():
                            subcount += 1
                            if subcount >= 1000:
                                break
                        info["kind"] = "dir"
                        info["child_count"] = subcount
                        info["child_count_capped"] = subcount >= 1000
                        total_visible_count += subcount
                    else:
                        info["kind"] = "other"
                except OSError as exc:
                    info["error"] = str(exc)[:120]
                top_level_entries.append(info)
        except OSError as exc:
            top_level_entries.append({"error": f"iterdir: {exc}"})

    report: dict[str, Any] = {
        "storage_base_path": str(storage_base),
        "storage_base_exists": storage_base.exists(),
        "storage_base_is_symlink": storage_base.is_symlink(),
        "episodes_dir_exists": episodes_dir.exists(),
        "episodes_dir_is_symlink": episodes_dir.is_symlink(),
        "audiobooks_dir_exists": audiobooks_dir.exists(),
        "api_auth_token_configured": bool(settings.api_auth_token),
        "api_auth_blocks_storage": bool(settings.api_auth_token),
        "process_uid": None,
        "process_gid": None,
        "mount_fs": _detect_mount_fs(storage_base),
        "host_source_path": _detect_host_source(storage_base),
        "top_level_entries": top_level_entries,
        "total_visible_bytes": total_visible_bytes,
        "total_visible_count": total_visible_count,
    }
    # ``os.getuid`` / ``os.getgid`` only exist on POSIX. On Windows the
    # probe simply omits those fields.
    report["process_uid"] = getattr(os, "getuid", lambda: None)()
    report["process_gid"] = getattr(os, "getgid", lambda: None)()

    # Pull a representative sample of media_assets across types so the
    # probe covers video / image / caption / audio. For each row
    # actually attempt a read of the first byte — that's what
    # StaticFiles.send_file does under the hood, and it's the only
    # way to know whether the container user can actually serve the
    # file.
    sample_types = ["video", "thumbnail", "scene", "caption", "voiceover"]
    samples: list[dict[str, Any]] = []
    for asset_type in sample_types:
        rows = (
            (
                await db.execute(
                    select(MediaAsset)
                    .where(MediaAsset.asset_type == asset_type)
                    .order_by(func.random())
                    .limit(1)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            fp = row.file_path or ""
            abs_p = (storage_base / fp).resolve() if fp else None
            entry: dict[str, Any] = {
                "asset_type": asset_type,
                "file_path": fp,
                "episode_id": str(row.episode_id) if row.episode_id else None,
                "abs_path": str(abs_p) if abs_p else None,
                "exists": False,
                "readable": False,
                "is_symlink": False,
                "size_bytes": None,
                "url_served_at": f"/storage/{fp}" if fp else None,
                "error": None,
            }
            if abs_p and abs_p.exists():
                entry["exists"] = True
                entry["is_symlink"] = abs_p.is_symlink()
                try:
                    entry["size_bytes"] = abs_p.stat().st_size
                except OSError as exc:
                    entry["error"] = f"stat: {exc}"
                try:
                    with abs_p.open("rb") as f:
                        _ = f.read(1)
                    entry["readable"] = True
                except OSError as exc:
                    entry["error"] = f"read: {exc}"
            samples.append(entry)

    report["samples"] = samples
    report["hints"] = _storage_probe_hints(report)
    return report


def _storage_probe_hints(report: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    if not report.get("storage_base_exists"):
        hints.append(
            "The storage_base_path doesn't exist inside the app container. "
            "Check your Docker volume mount — the host path with your media "
            "must map to this path inside the container."
        )
    if report.get("api_auth_token_configured"):
        hints.append(
            "API_AUTH_TOKEN is set. Browser <video> / <img> tags can't send "
            "Bearer headers, so every /storage/* request gets blocked by "
            "the auth middleware. Either unset API_AUTH_TOKEN or move the "
            "media behind a signed-URL scheme."
        )
    if report.get("storage_base_is_symlink") or report.get("episodes_dir_is_symlink"):
        hints.append(
            "storage_base_path or storage/episodes/ is a symlink. FastAPI "
            "StaticFiles is mounted with follow_symlink=False so symlinked "
            "directories return 404. Replace the symlink with the real "
            "directory (or its contents)."
        )
    samples = report.get("samples") or []
    exists_but_unreadable = [s for s in samples if s["exists"] and not s["readable"]]
    if exists_but_unreadable:
        hints.append(
            f"{len(exists_but_unreadable)} of {len(samples)} probe files exist "
            "but aren't readable by the app process — a permission problem. "
            f"Inside the container run ``chown -R {report.get('process_uid')}:"
            f"{report.get('process_gid')} /app/storage`` (or the equivalent "
            "host-side chown on the mapped directory)."
        )
    samples_with_symlink = [s for s in samples if s["is_symlink"]]
    if samples_with_symlink:
        hints.append(
            f"{len(samples_with_symlink)} sample files are symlinks. "
            "StaticFiles is mounted with follow_symlink=False — serve "
            "real files, or flip the mount to follow_symlinks=True "
            "(weighs the path-traversal trade-off yourself)."
        )
    host_source = report.get("host_source_path")
    if host_source:
        looks_vm_internal = (
            host_source.startswith("/project/")
            or host_source.startswith("/run/desktop/")
            or host_source.startswith("/var/lib/docker/")
            or host_source.startswith("/mnt/host_mnt/")
        )
        if looks_vm_internal:
            hints.append(
                f"The container's /app/storage is bind-mounted from "
                f"``{host_source}`` — that's Docker Desktop's Linux-VM "
                f"label for the compose file's parent directory on your "
                f"real filesystem. On Windows it's the same folder as "
                f"``%USERPROFILE%\\Drevalis\\storage\\`` (or wherever "
                f"``docker-compose.yml`` lives + ``\\storage\\``); on "
                f"macOS it's ``~/Drevalis/storage/`` by the same logic. "
                f"If you copied files into that Windows/macOS folder "
                f"but the app still shows no content, the running "
                f"containers were likely started from a different "
                f"directory. Close any other Drevalis stacks, open a "
                f"terminal in ``%USERPROFILE%\\Drevalis\\``, run "
                f"``docker compose down`` then ``docker compose up -d`` "
                f"from THAT folder."
            )
        else:
            hints.append(
                f"The container's /app/storage is bind-mounted from the "
                f"host at ``{host_source}`` — your media files must live "
                f"under that directory."
            )
        hints.append(
            "Sanity check from your host terminal: ``docker inspect -f "
            '\'{{range .Mounts}}{{if eq .Destination "/app/storage"}}'
            "{{.Source}}{{end}}{{end}}' $(docker ps -q --filter "
            "'name=app')`` — that prints the exact host source path "
            "Docker recorded when the container was created."
        )

    # "I see only 0-1 files under /app/storage even though I put 20 GB on
    # disk" — by far the most common post-rough-restore story. Call it out
    # directly instead of leaving the user to infer it from byte counts.
    entries = report.get("top_level_entries") or []
    visible_count = int(report.get("total_visible_count") or 0)
    visible_bytes = int(report.get("total_visible_bytes") or 0)
    non_backup_entries = [
        e for e in entries if isinstance(e, dict) and e.get("name") not in {"backups", None}
    ]
    empty_non_backup = (
        all(
            (e.get("kind") == "dir" and (e.get("child_count") or 0) == 0)
            or (e.get("kind") == "file" and (e.get("size_bytes") or 0) == 0)
            for e in non_backup_entries
        )
        if non_backup_entries
        else True
    )
    if entries and visible_count <= 2 and empty_non_backup:
        hints.append(
            "The container can only see 0–1 files under /app/storage. "
            "Everything else in your storage/ directory on the host is NOT "
            "reaching the container — almost certainly because the running "
            "containers were started from a different directory than the "
            "one you copied files into. Run the ``docker inspect`` command "
            "below to see the actual host source Docker recorded when "
            "this container was created, then relaunch compose from the "
            "directory that holds your 20+ GB of media."
        )
    elif visible_count > 0 and visible_bytes < 1_000_000 and non_backup_entries:
        # Non-empty but suspiciously small (< 1 MB). Surface the count so
        # the user can eyeball it against what they expect.
        hints.append(
            f"Container sees {visible_count} entries totalling "
            f"{visible_bytes} bytes at /app/storage — if that's much less "
            "than what you copied on the host, the bind source is pointing "
            "to a different directory than you expect."
        )

    if not hints:
        hints.append(
            "No obvious storage-serving problem detected. If videos still "
            "don't play, open browser DevTools → Network and look at the "
            "actual HTTP status of the /storage/... request; share that "
            "status + response headers."
        )
    return hints


# ── Repair media links (after a rough restore or manual copy) ────────────


@router.post(
    "/repair-media",
    summary="Relink media_assets rows to files on disk",
    description=(
        "Walks every media_assets row and, for those whose file_path no "
        "longer resolves, tries to locate the matching file on disk under "
        "storage/episodes/ and updates the row. Use after restoring a DB "
        "backup into a directory structure that doesn't match the original "
        "storage layout, or after manually copying media. Non-destructive: "
        "only updates rows whose current path is broken."
    ),
)
async def repair_media(
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, object]:
    # No request body is accepted or required — all deps are dependency-
    # injected. Switched to Annotated+Depends for all so FastAPI never
    # tries to treat one as a query/body parameter (that was producing
    # a spurious 422 when the frontend fired POST with no body).
    try:
        report = await repair_media_links(db, settings.storage_base_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("media_repair_failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"media repair failed: {exc}",
        ) from exc
    # Bust the storage_probe cache so the Backup tab immediately reflects
    # the post-repair file_path state rather than the pre-repair snapshot
    # cached for up to 5 minutes. Only on the success path — if
    # repair_media_links raised, the storage state is unchanged and the
    # existing cache is still accurate. Best-effort: a Redis hiccup here
    # just means the cache expires naturally at its TTL.
    try:
        await redis.delete(_STORAGE_PROBE_CACHE_KEY)
    except Exception:  # noqa: BLE001
        logger.debug("storage_probe_cache_bust_failed", exc_info=True)
    return report.to_dict()


# ── Nightly cron hook (called by the arq worker) ─────────────────────────


async def run_scheduled_backup(
    db: AsyncSession,
    settings: Settings,
) -> Path | None:
    """Invoked by the arq cron when BACKUP_AUTO_ENABLED is True."""
    if not settings.backup_auto_enabled:
        return None
    svc = _service(settings)
    archive = await svc.create_backup(db)
    svc.prune(settings.backup_retention)
    return archive


# placate static analysis — shutil is imported but only used indirectly.
_ = shutil
