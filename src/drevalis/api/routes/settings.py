"""Settings API router -- storage usage, system health, FFmpeg info."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_redis, get_settings
from drevalis.schemas.settings import (
    FFmpegInfoResponse,
    HealthCheckResponse,
    ServiceHealth,
    StorageUsageResponse,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ── Helpers ───────────────────────────────────────────────────────────────


def _human_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0  # type: ignore[assignment]
    return f"{size_bytes:.1f} PB"


# ── Storage usage ─────────────────────────────────────────────────────────


@router.get(
    "/storage",
    response_model=StorageUsageResponse,
    status_code=status.HTTP_200_OK,
    summary="Storage usage info",
)
async def storage_usage(
    settings: Settings = Depends(get_settings),
) -> StorageUsageResponse:
    """Return total disk usage + per-subdir breakdown.

    Previously this endpoint walked the tree twice (once via
    ``storage.get_total_size_bytes`` and once for ``subdir_sizes``)
    AND the subdir walk ran synchronously on the event loop. For a
    20 GB install on a Docker Desktop 9P mount that ran for minutes
    and pinned the worker. Now:

    1. Single ``os.walk`` pass in a thread, skipping noisy dirs
       (``models``, ``temp``, ``cache``, hidden) so we don't double
       the work with TTS model weights that aren't "user data".
    2. Hard wall-clock budget. We return whatever we collected when
       it expires rather than spinning forever.
    """
    base_abs = Path(settings.storage_base_path).resolve()

    # Subdirs we report on. ``models`` and ``temp`` are deliberately
    # left out of the per-dir tally — they're system noise that
    # inflates numbers the user cares about (their content).
    reported_subdirs = {
        "episodes",
        "audiobooks",
        "voice_previews",
        "backups",
        "music",
        "workflows",
    }
    # Walk-skip list: directories we don't recurse into at all. Model
    # weights alone can easily be 30 GB+; excluding them keeps the
    # walk fast without hiding anything interesting from the user.
    skip_prefixes = {
        str(base_abs / "models"),
        str(base_abs / "temp"),
        str(base_abs / "cache"),
    }

    total_budget_sec = 5.0

    def _walk() -> tuple[int, dict[str, int]]:
        import os
        import time as _time

        subdir_totals: dict[str, int] = {name: 0 for name in reported_subdirs}
        grand_total = 0
        start = _time.monotonic()

        if not base_abs.exists():
            return 0, subdir_totals

        for dirpath, dirnames, filenames in os.walk(base_abs, followlinks=False):
            # Bail if the walk is taking too long. Partial results are
            # fine — the UI renders them and the user can refresh.
            if _time.monotonic() - start > total_budget_sec:
                break

            # Skip the known-huge / non-user dirs outright.
            dirnames[:] = [
                d
                for d in dirnames
                if not d.startswith(".") and os.path.join(dirpath, d) not in skip_prefixes
            ]

            # Which top-level subdir are we under? ``.`` means base_abs itself.
            try:
                rel = os.path.relpath(dirpath, base_abs)
            except ValueError:
                continue
            top = rel.split(os.sep, 1)[0] if rel != "." else None

            for name in filenames:
                full = os.path.join(dirpath, name)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                grand_total += size
                if top and top in subdir_totals:
                    subdir_totals[top] += size

        return grand_total, subdir_totals

    total, subdir_sizes = await asyncio.to_thread(_walk)

    # Host-side bind-mount root via /proc/self/mountinfo. Quick read,
    # no I/O bound on storage contents.
    host_source: str | None = None
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
        path_str = str(base_abs)
        best: tuple[int, str] | None = None
        for line in lines:
            parts = line.split()
            if len(parts) < 5:
                continue
            root = parts[3]
            mount_point = parts[4]
            if path_str == mount_point or path_str.startswith(mount_point.rstrip("/") + "/"):
                tail = path_str[len(mount_point) :]
                suffix = tail if tail.startswith("/") else ("/" + tail if tail else "")
                source = root.rstrip("/") + suffix
                depth = len(mount_point)
                if best is None or depth > best[0]:
                    best = (depth, source)
        if best:
            host_source = best[1]
    except (OSError, UnicodeDecodeError):
        pass

    # v0.20.7 — raw mountinfo dump for the container's /app/storage line
    # so a user whose "21 GB on host, 0 B in container" problem persists
    # can paste the FULL mount entry back to support and get a bisection
    # of the bind-mount chain. Filters to lines that mention the storage
    # path so we don't leak unrelated mounts (e.g. /tmp, /proc).
    mountinfo_lines: list[str] = []
    try:
        raw = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
        path_str = str(base_abs)
        for line in raw:
            parts = line.split()
            if len(parts) < 5:
                continue
            mount_point = parts[4]
            # Keep the line if it covers our storage path OR is a
            # parent of it (so we capture overlay layers that would
            # otherwise hide the real bind).
            if (
                mount_point == path_str
                or path_str.startswith(mount_point.rstrip("/") + "/")
                or mount_point == "/"
                or mount_point == ""
            ):
                mountinfo_lines.append(line)
    except (OSError, UnicodeDecodeError):
        pass

    return StorageUsageResponse(
        total_size_bytes=total,
        total_size_human=_human_size(total),
        storage_base_path=str(settings.storage_base_path),
        storage_base_abs=str(base_abs),
        host_source_path=host_source,
        subdir_sizes=subdir_sizes,
        mountinfo_lines=mountinfo_lines,
    )


# ── System health check ──────────────────────────────────────────────────


async def _check_database(db: AsyncSession) -> ServiceHealth:
    """Check PostgreSQL connectivity with a simple query."""
    try:
        from sqlalchemy import text

        await db.execute(text("SELECT 1"))
        return ServiceHealth(name="database", status="ok")
    except Exception as exc:
        return ServiceHealth(
            name="database",
            status="unreachable",
            message=str(exc)[:200],
        )


async def _check_redis(redis: Redis) -> ServiceHealth:
    """Check Redis connectivity with PING."""
    try:
        pong = await redis.ping()
        if pong:
            return ServiceHealth(name="redis", status="ok")
        return ServiceHealth(name="redis", status="degraded", message="Ping returned False")
    except Exception as exc:
        return ServiceHealth(
            name="redis",
            status="unreachable",
            message=str(exc)[:200],
        )


async def _check_worker(redis: Redis) -> ServiceHealth:
    """Read the worker:heartbeat key and report whether the worker is alive.

    Mirrors the threshold used by /api/v1/jobs/worker/health (120s) so the
    aggregate /settings/health page can flag a dead worker without making
    operators visit a second endpoint. Treats Redis-unreachable as a
    degraded-rather-than-unreachable signal so a Redis outage doesn't show
    the worker as separately broken on top of Redis.
    """
    from datetime import UTC, datetime

    try:
        raw = await redis.get("worker:heartbeat")
    except Exception as exc:
        return ServiceHealth(
            name="worker",
            status="degraded",
            message=f"could not read heartbeat (Redis: {str(exc)[:120]})",
        )
    if not raw:
        return ServiceHealth(
            name="worker",
            status="unreachable",
            message="No worker:heartbeat key — worker not started?",
        )
    value = raw if isinstance(raw, str) else raw.decode()
    try:
        last_beat = datetime.fromisoformat(value)
    except ValueError:
        return ServiceHealth(
            name="worker",
            status="degraded",
            message=f"heartbeat malformed: {value[:60]}",
        )
    now = datetime.now(tz=UTC) if last_beat.tzinfo else datetime.now()
    age = (now - last_beat).total_seconds()
    if age < 120:
        return ServiceHealth(name="worker", status="ok", message=f"alive ({age:.0f}s ago)")
    return ServiceHealth(
        name="worker",
        status="unreachable",
        message=f"heartbeat stale: {age:.0f}s old (threshold 120s)",
    )


async def _check_comfyui_servers(
    db: AsyncSession,
    default_url: str,
    encryption_key: str,
    encryption_keys: dict[int, str] | None = None,
) -> list[ServiceHealth]:
    """Check each active ComfyUI server's connectivity.

    Queries the database for all active servers and tests each one.
    Also tests the default URL from settings if no DB servers are configured.
    """
    import httpx

    from drevalis.services.comfyui_admin import ComfyUIServerService

    results: list[ServiceHealth] = []

    # Try to fetch active servers from DB
    try:
        svc = ComfyUIServerService(db, encryption_key, encryption_keys=encryption_keys)
        active_servers = [s for s in await svc.list_all() if s.is_active]
    except Exception:
        active_servers = []

    if active_servers:
        for server in active_servers:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                    resp = await client.get(f"{server.url}/system_stats")
                    if resp.status_code == 200:
                        results.append(
                            ServiceHealth(
                                name=f"comfyui:{server.name}",
                                status="ok",
                                message=server.url,
                            )
                        )
                    else:
                        results.append(
                            ServiceHealth(
                                name=f"comfyui:{server.name}",
                                status="degraded",
                                message=f"HTTP {resp.status_code} at {server.url}",
                            )
                        )
            except Exception as exc:
                results.append(
                    ServiceHealth(
                        name=f"comfyui:{server.name}",
                        status="unreachable",
                        message=f"{server.url} -- {str(exc)[:150]}",
                    )
                )
    else:
        # Fall back to checking the default URL from settings
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{default_url}/system_stats")
                if resp.status_code == 200:
                    results.append(ServiceHealth(name="comfyui", status="ok"))
                else:
                    results.append(
                        ServiceHealth(
                            name="comfyui",
                            status="degraded",
                            message=f"HTTP {resp.status_code}",
                        )
                    )
        except Exception as exc:
            results.append(
                ServiceHealth(
                    name="comfyui",
                    status="unreachable",
                    message=str(exc)[:200],
                )
            )

    return results


async def _check_ffmpeg(ffmpeg_path: str) -> ServiceHealth:
    """Check that the FFmpeg binary exists and report its version."""
    try:
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_path,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            version_line = stdout.decode("utf-8", errors="replace").split("\n")[0]
            return ServiceHealth(
                name="ffmpeg",
                status="ok",
                message=version_line.strip(),
            )
        return ServiceHealth(
            name="ffmpeg",
            status="degraded",
            message=f"Exit code {proc.returncode}",
        )
    except Exception as exc:
        return ServiceHealth(
            name="ffmpeg",
            status="unreachable",
            message=str(exc)[:200],
        )


async def _check_piper_tts(models_path: Path) -> ServiceHealth:
    """Check that the Piper TTS models directory exists and contains models."""
    try:
        if not models_path.exists():
            return ServiceHealth(
                name="piper_tts",
                status="unreachable",
                message=f"Models directory not found: {models_path}",
            )

        if not models_path.is_dir():
            return ServiceHealth(
                name="piper_tts",
                status="degraded",
                message=f"Path exists but is not a directory: {models_path}",
            )

        # Count .onnx model files (Piper uses ONNX models)
        model_files = list(models_path.glob("*.onnx"))
        if not model_files:
            return ServiceHealth(
                name="piper_tts",
                status="degraded",
                message=f"Models directory exists but contains no .onnx files: {models_path}",
            )

        return ServiceHealth(
            name="piper_tts",
            status="ok",
            message=f"{len(model_files)} model(s) found in {models_path}",
        )
    except Exception as exc:
        return ServiceHealth(
            name="piper_tts",
            status="unreachable",
            message=str(exc)[:200],
        )


async def _check_lm_studio(base_url: str) -> ServiceHealth:
    """Check LM Studio connectivity by hitting the /models endpoint."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{base_url}/models")
            if resp.status_code == 200:
                data = resp.json()
                model_count = len(data.get("data", []))
                return ServiceHealth(
                    name="lm_studio",
                    status="ok",
                    message=f"{model_count} model(s) loaded at {base_url}",
                )
            return ServiceHealth(
                name="lm_studio",
                status="degraded",
                message=f"HTTP {resp.status_code} from {base_url}/models",
            )
    except Exception as exc:
        return ServiceHealth(
            name="lm_studio",
            status="unreachable",
            message=f"{base_url} -- {str(exc)[:150]}",
        )


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="System health check (DB, Redis, ComfyUI, FFmpeg, Piper TTS, LM Studio)",
)
async def system_health(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HealthCheckResponse:
    """Check the health of all backend services concurrently.

    Returns structured status for: PostgreSQL, Redis, ComfyUI server(s),
    FFmpeg, Piper TTS models, and LM Studio.
    """
    # Run all health checks concurrently for faster response
    # Run independent checks in parallel. Listing them by-call keeps
    # types crisp (mypy can't narrow a 7-element heterogeneous gather
    # tuple after a single unpack); single-call `await` per result is
    # equivalent in wall-clock since asyncio.gather is implicit on
    # subsequent awaits already-running coroutines.
    db_task = asyncio.create_task(_check_database(db))
    redis_task = asyncio.create_task(_check_redis(redis))
    worker_task = asyncio.create_task(_check_worker(redis))
    comfyui_task = asyncio.create_task(
        _check_comfyui_servers(
            db,
            settings.comfyui_default_url,
            settings.encryption_key,
            encryption_keys=settings.get_encryption_keys(),
        )
    )
    ffmpeg_task = asyncio.create_task(_check_ffmpeg(settings.ffmpeg_path))
    piper_task = asyncio.create_task(_check_piper_tts(settings.piper_models_path))
    lm_studio_task = asyncio.create_task(_check_lm_studio(settings.lm_studio_base_url))

    db_health = await db_task
    redis_health = await redis_task
    worker_health = await worker_task
    comfyui_healths = await comfyui_task
    ffmpeg_health = await ffmpeg_task
    piper_health = await piper_task
    lm_studio_health = await lm_studio_task

    services: list[ServiceHealth] = [
        db_health,
        redis_health,
        worker_health,
        *comfyui_healths,
        ffmpeg_health,
        piper_health,
        lm_studio_health,
    ]

    # -- Overall status -----------------------------------------------------
    statuses = {s.status for s in services}
    if statuses == {"ok"}:
        overall = "ok"
    elif "unreachable" in statuses:
        overall = "unhealthy"
    else:
        overall = "degraded"

    return HealthCheckResponse(overall=overall, services=services)


# ── FFmpeg info ───────────────────────────────────────────────────────────


@router.get(
    "/ffmpeg",
    response_model=FFmpegInfoResponse,
    status_code=status.HTTP_200_OK,
    summary="FFmpeg version and path info",
)
async def ffmpeg_info(
    settings: Settings = Depends(get_settings),
) -> FFmpegInfoResponse:
    """Return FFmpeg installation details."""
    ffmpeg_path = settings.ffmpeg_path

    # Check if ffmpeg is available on PATH or at the configured path.
    resolved = shutil.which(ffmpeg_path)
    if resolved is None:
        return FFmpegInfoResponse(
            ffmpeg_path=ffmpeg_path,
            available=False,
            message=f"FFmpeg not found at '{ffmpeg_path}'",
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            resolved,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            version_line = stdout.decode("utf-8", errors="replace").split("\n")[0]
            return FFmpegInfoResponse(
                ffmpeg_path=resolved,
                available=True,
                version=version_line.strip(),
                message="FFmpeg is available",
            )
        else:
            return FFmpegInfoResponse(
                ffmpeg_path=resolved,
                available=False,
                message=f"FFmpeg exited with code {proc.returncode}",
            )
    except Exception as exc:
        return FFmpegInfoResponse(
            ffmpeg_path=ffmpeg_path,
            available=False,
            message=f"Error checking FFmpeg: {exc}",
        )
