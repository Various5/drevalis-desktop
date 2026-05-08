"""App-event log reader service.

Parses the structlog JSON log file and surfaces recent warning / error /
critical events to the frontend via ``GET /api/v1/events``.

Design notes
------------
* ``aiofiles`` is used for the async read — already a project dependency,
  so no new packages are introduced.
* The file is read in full and then sliced from the tail. Structlog files
  are typically small (MB range) between rotations; reading in full
  is simpler and cheaper than a seek-and-scan for a 1000-line tail.
* Malformed JSON lines are silently skipped so a partially-written line
  at the end of the file (buffered write interrupted by power loss) does
  not fail the entire call.
* If the log file is not configured or does not exist the service returns
  an empty list — log viewing is best-effort; it must not cause a 500.

Multi-source merge
------------------
When ``LOG_FILE`` resolves to a path inside a directory and that
directory contains other ``*.json`` files, all of them are read and
merged by timestamp before applying the level filter and the tail
limit. The Docker compose stack writes ``/var/log/drevalis/app.json``
and ``/var/log/drevalis/worker.json`` into the same shared bind-mount
volume; this merge surfaces both streams without ever giving the
backend container access to ``/var/run/docker.sock``. Postgres / Redis
container logs stay in their own stdouts (use ``docker logs`` for
those) — the trust boundary stays tight.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import aiofiles
import structlog
from pydantic import BaseModel, ConfigDict

from drevalis.core.config import Settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum structlog integer level for each human-readable severity.
# structlog maps levels to stdlib logging integers:
#   DEBUG=10, INFO=20, WARNING=30, ERROR=40, CRITICAL=50
_LEVEL_INTS: dict[str, int] = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "warn": 30,  # structlog alias
    "error": 40,
    "critical": 50,
}

# Maximum lines to scan from the tail of the file before filtering.
# Prevents runaway memory use on very large, un-rotated log files.
_SCAN_LIMIT = 10_000

# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------


class LogEvent(BaseModel):
    """A single structured log event returned to the client."""

    model_config = ConfigDict(strict=False)

    timestamp: datetime
    level: Literal["warning", "error", "critical"]
    logger: str
    event: str
    context: dict[str, Any]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalise_level(raw: str) -> str:
    """Lower-case and normalise ``warn`` → ``warning``."""
    lowered = raw.lower()
    return "warning" if lowered == "warn" else lowered


def _parse_line(line: str) -> dict[str, Any] | None:
    """Parse a single log line as JSON.

    Returns ``None`` if the line is empty, whitespace-only, or contains
    invalid JSON.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _to_log_event(record: dict[str, Any]) -> LogEvent | None:
    """Convert a parsed JSON dict to a ``LogEvent``.

    Returns ``None`` when the record is missing required fields or the
    level is below warning.
    """
    raw_level = record.get("level", record.get("log_level", ""))
    if not isinstance(raw_level, str) or not raw_level:
        return None

    level_norm = _normalise_level(raw_level)
    if level_norm not in ("warning", "error", "critical"):
        return None

    raw_ts = record.get("timestamp", record.get("ts", ""))
    if not isinstance(raw_ts, str) or not raw_ts:
        return None

    try:
        ts = datetime.fromisoformat(raw_ts)
    except ValueError:
        return None

    raw_logger = record.get("logger", record.get("log", "unknown"))
    event_str = record.get("event", record.get("msg", ""))
    if not isinstance(event_str, str):
        event_str = str(event_str)

    # Everything that is not a top-level structural key becomes context.
    _SKIP_KEYS = {"timestamp", "ts", "level", "log_level", "logger", "log", "event", "msg"}
    context: dict[str, Any] = {k: v for k, v in record.items() if k not in _SKIP_KEYS}

    try:
        return LogEvent(
            timestamp=ts,
            level=level_norm,
            logger=str(raw_logger),
            event=event_str,
            context=context,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_log_path(settings: Settings) -> Path | None:
    """Return the resolved log file path from settings, or ``None``."""
    raw: str | None = getattr(settings, "log_file", None)
    if not raw:
        return None
    return Path(raw)


async def read_recent_events(
    settings: Settings,
    *,
    limit: int = 200,
    min_level: str = "warning",
) -> list[LogEvent]:
    """Read up to *limit* recent log events at or above *min_level*.

    Events are returned newest-first (tail of file → top of list).

    Args:
        settings: Application settings used to locate the log file.
        limit: Maximum number of matching events to return.
        min_level: Minimum severity to include.  One of ``warning``,
            ``error``, or ``critical``.

    Returns:
        A list of ``LogEvent`` objects, newest first.  Empty list when the
        log file is not configured, does not exist, or cannot be read.
    """
    min_int = _LEVEL_INTS.get(min_level.lower(), _LEVEL_INTS["warning"])
    log_path = _resolve_log_path(settings)

    if log_path is None:
        return []

    paths = _resolve_log_paths(log_path)
    if not paths:
        return []

    # Read every source file, parse each line into a ``LogEvent``, then
    # merge by timestamp before applying the limit. Sorting up front
    # gives a deterministic newest-first result regardless of which
    # source is bigger.
    candidates: list[LogEvent] = []
    for path in paths:
        try:
            async with aiofiles.open(path, encoding="utf-8", errors="replace") as fh:
                raw_text = await fh.read()
        except OSError as exc:
            logger.warning("event_log.read_failed", path=str(path), error=str(exc))
            continue

        lines = raw_text.splitlines()
        # Cap scan per file so a single massive log doesn't dominate.
        tail = lines[-_SCAN_LIMIT:] if len(lines) > _SCAN_LIMIT else lines

        for line in tail:
            record = _parse_line(line)
            if record is None:
                continue
            raw_level = record.get("level", record.get("log_level", ""))
            level_int = _LEVEL_INTS.get(_normalise_level(str(raw_level)), -1)
            if level_int < min_int:
                continue
            event = _to_log_event(record)
            if event is not None:
                candidates.append(event)

    # Newest first.
    candidates.sort(key=lambda e: e.timestamp, reverse=True)
    return candidates[:limit]


def _resolve_log_paths(primary: Path) -> list[Path]:
    """Return every JSON log file to merge for the events feed.

    When ``primary`` lives in a directory that holds other ``*.json``
    files (the docker-compose layout writes ``app.json`` and
    ``worker.json`` into the same shared bind-mount volume), all of
    them are merged. Otherwise just ``primary`` if it exists.

    The merge is opt-in by directory shape — single-file installs
    still work unchanged.
    """
    if primary.exists() and primary.is_file():
        parent = primary.parent
        if parent.is_dir():
            siblings = sorted(parent.glob("*.json"))
            if len(siblings) > 1:
                return [p for p in siblings if p.is_file()]
        return [primary]
    return []
