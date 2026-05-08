"""Support diagnostics bundle builder.

Assembles a ZIP in memory containing redacted configuration, recent logs,
system info, health snapshot, and the current Alembic revision. The bundle
is designed to give a support engineer enough context to triage an issue
without exposing any secrets or credentials.

Public surface
--------------
``build_bundle(settings, db)`` — async; returns ``(bytes, size_int)``.
"""

from __future__ import annotations

import io
import json
import platform
import re
import shutil
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.core.config import Settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

# Field name patterns whose values must be replaced. Matched
# case-insensitively against the lowercased field name.
_REDACTED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"encryption_key", re.IGNORECASE),
    re.compile(r".+_key$", re.IGNORECASE),
    re.compile(r".+_secret$", re.IGNORECASE),
    re.compile(r".+_token$", re.IGNORECASE),
    re.compile(r".+_password$", re.IGNORECASE),
    re.compile(r"^database_url$", re.IGNORECASE),
)

_REDACTED_MARKER = "***REDACTED***"
_DB_URL_RE = re.compile(
    r"((?:postgresql|postgres|asyncpg)[^/]*://)[^:@]*:[^@]*@(.*)",
    re.IGNORECASE,
)


def _should_redact(field_name: str) -> bool:
    """Return True when *field_name* matches any secret pattern."""
    return any(p.fullmatch(field_name) for p in _REDACTED_PATTERNS)


def _redact_db_url(url: str) -> str:
    """Replace the user:password portion of a database URL with ``***``."""
    m = _DB_URL_RE.match(url)
    if m:
        return f"{m.group(1)}user:***@{m.group(2)}"
    return _REDACTED_MARKER


def redact_settings(settings: Settings) -> dict[str, object]:
    """Return a redacted, JSON-safe ``model_dump`` of *settings*.

    Rules
    -----
    * ``database_url``: preserve the host/port/db portion so support can
      see where the app points; replace user:password with ``***``.
    * Any field whose name matches ``*_KEY``, ``*_SECRET``, ``*_TOKEN``,
      ``*_PASSWORD``, or ``encryption_key`` exactly: replace with
      ``"***REDACTED***"``.
    * Pydantic private attributes (``PrivateAttr``) are excluded from
      ``model_dump()`` by default and therefore never appear here.
    """
    try:
        raw: dict[str, object] = settings.model_dump()
    except Exception:
        # Defensive: if model_dump() fails (e.g. custom validator side effects)
        # walk available public attributes manually.
        raw = {
            k: getattr(settings, k, None)
            for k in dir(settings)
            if not k.startswith("_") and not callable(getattr(settings, k, None))
        }

    result: dict[str, object] = {}
    for name, value in raw.items():
        if name == "database_url":
            result[name] = _redact_db_url(str(value)) if value else value
        elif _should_redact(name):
            result[name] = _REDACTED_MARKER
        else:
            # Convert Path objects to strings so json.dumps is clean.
            result[name] = str(value) if isinstance(value, Path) else value
    return result


# ---------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------


def _resolve_version() -> tuple[str, str]:
    """Return ``(version, git_sha)`` from the installed package metadata.

    Priority:
    1. ``APP_VERSION`` env var (set by the release workflow).
    2. ``importlib.metadata.version("drevalis")``.
    3. ``"0.0.0-dev"`` sentinel.

    Git SHA is read from the ``APP_GIT_SHA`` env var injected at image
    build time. Falls back to ``"unknown"``.
    """
    import os

    env_ver = os.environ.get("APP_VERSION", "").strip()
    if env_ver:
        version = env_ver
    else:
        try:
            from importlib.metadata import version as _v

            version = _v("drevalis")
        except Exception:
            version = "0.0.0-dev"

    git_sha = os.environ.get("APP_GIT_SHA", "unknown").strip() or "unknown"
    return version, git_sha


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------


async def _collect_system_info(settings: Settings) -> dict[str, object]:
    """Return Python version, platform, ffmpeg availability, and disk space."""
    import asyncio

    ffmpeg_path: str = getattr(settings, "ffmpeg_path", "ffmpeg")
    ffmpeg_available: bool = shutil.which(ffmpeg_path) is not None
    ffmpeg_version: str | None = None

    if ffmpeg_available:
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_path,
                "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                ffmpeg_version = stdout.decode("utf-8", errors="replace").split("\n")[0].strip()
        except Exception:
            pass

    storage_base: Path = Path(getattr(settings, "storage_base_path", "./storage")).resolve()

    disk_free_bytes: int | None = None
    try:
        usage = shutil.disk_usage(str(storage_base) if storage_base.exists() else ".")
        disk_free_bytes = usage.free
    except Exception:
        pass

    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "platform_machine": platform.machine(),
        "ffmpeg_available": ffmpeg_available,
        "ffmpeg_version": ffmpeg_version,
        "storage_base_path": str(storage_base),
        "disk_free_bytes": disk_free_bytes,
    }


# ---------------------------------------------------------------------------
# Recent logs
# ---------------------------------------------------------------------------

_LOG_TAIL_LINES = 1000


def _collect_recent_logs(settings: Settings) -> str:
    """Return the last ``_LOG_TAIL_LINES`` lines from the structured log file.

    Returns a placeholder when no log file path is configured or the file
    is inaccessible.
    """
    log_file: str | None = getattr(settings, "log_file", None)
    if not log_file:
        return "no log file configured"

    log_path = Path(log_file)
    if not log_path.exists():
        return f"log file not found: {log_file}"

    try:
        # Read the whole file; for support bundles the file is bounded by
        # log rotation and reading 1000 lines from the end is cheap enough
        # for any sane log size. Avoids a reverse-seek dance.
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-_LOG_TAIL_LINES:]
        return "\n".join(tail)
    except OSError as exc:
        return f"could not read log file: {exc}"


# ---------------------------------------------------------------------------
# DB revision
# ---------------------------------------------------------------------------


async def _collect_db_revision(db: AsyncSession) -> str:
    """Read the current Alembic head from ``alembic_version`` table."""
    from sqlalchemy import text

    try:
        result = await db.execute(text("SELECT version_num FROM alembic_version"))
        rows = result.fetchall()
        if not rows:
            return "no alembic_version rows found"
        return "\n".join(str(row[0]) for row in rows)
    except Exception as exc:
        return f"could not read alembic_version: {exc}"


# ---------------------------------------------------------------------------
# Health snapshot
# ---------------------------------------------------------------------------


async def _collect_health(settings: Settings, db: AsyncSession) -> dict[str, object]:
    """Collect a lightweight health snapshot using the settings-route helpers.

    Imports lazily so the diagnostics service has no hard coupling to the
    routes layer — ``api/routes/settings.py`` is itself importable without
    starting FastAPI, so this is acceptable from a dependency perspective.
    """
    from drevalis.api.routes.settings import (
        _check_database,
        _check_ffmpeg,
        _check_piper_tts,
    )

    db_health = await _check_database(db)
    ffmpeg_path: str = getattr(settings, "ffmpeg_path", "ffmpeg")
    ffmpeg_health = await _check_ffmpeg(ffmpeg_path)
    piper_path: Path = Path(getattr(settings, "piper_models_path", "./storage/models/piper"))
    piper_health = await _check_piper_tts(piper_path)

    services = [db_health, ffmpeg_health, piper_health]
    statuses = {s.status for s in services}
    if statuses == {"ok"}:
        overall = "ok"
    elif "unreachable" in statuses:
        overall = "unhealthy"
    else:
        overall = "degraded"

    return {
        "overall": overall,
        "services": [s.model_dump() for s in services],
    }


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------

_MANIFEST_TEMPLATE = """\
Drevalis Creator Studio — Support Diagnostics Bundle
=====================================================
Version      : {version}
Git SHA      : {git_sha}
Bundle UTC   : {bundle_utc}
Platform     : {platform_str}
Python       : {python_version}
"""


async def build_bundle(settings: Settings, db: AsyncSession) -> tuple[bytes, int]:
    """Assemble an in-memory ZIP containing all diagnostics artifacts.

    Returns
    -------
    (zip_bytes, size_in_bytes)
        ``zip_bytes`` is the raw ZIP content ready to stream as
        ``application/zip``. ``size_in_bytes`` is ``len(zip_bytes)`` and
        is returned so the caller can log it without recomputing.

    The function runs several async sub-tasks concurrently where possible
    and falls back gracefully on any individual failure rather than
    aborting the whole bundle.
    """
    import asyncio

    version, git_sha = _resolve_version()
    bundle_utc = datetime.now(tz=UTC).isoformat()

    # Run the DB-dependent tasks together; system-info is pure async I/O.
    db_rev_task = asyncio.create_task(_collect_db_revision(db))
    health_task = asyncio.create_task(_collect_health(settings, db))
    system_task = asyncio.create_task(_collect_system_info(settings))

    db_revision = await db_rev_task
    health = await health_task
    system_info = await system_task

    redacted_config = redact_settings(settings)
    recent_logs = _collect_recent_logs(settings)

    manifest = _MANIFEST_TEMPLATE.format(
        version=version,
        git_sha=git_sha,
        bundle_utc=bundle_utc,
        platform_str=platform.platform(),
        python_version=sys.version.split("\n")[0],
    )

    version_obj: dict[str, object] = {"version": version, "git_sha": git_sha}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("MANIFEST.txt", manifest)
        zf.writestr("version.json", json.dumps(version_obj, indent=2))
        zf.writestr("config.json", json.dumps(redacted_config, indent=2, default=str))
        zf.writestr("health.json", json.dumps(health, indent=2, default=str))
        zf.writestr("recent_logs.txt", recent_logs)
        zf.writestr("system.json", json.dumps(system_info, indent=2, default=str))
        zf.writestr("db_revision.txt", db_revision)

    zip_bytes = buf.getvalue()
    size = len(zip_bytes)

    logger.info(
        "diagnostics_bundle_built",
        version=version,
        git_sha=git_sha,
        size_bytes=size,
    )

    return zip_bytes, size
