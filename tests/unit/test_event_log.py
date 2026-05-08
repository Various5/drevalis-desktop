"""Unit tests for ``drevalis.services.event_log``.

Coverage targets:
* Empty file → empty list.
* Mixed-severity file → only warning+ returned when min_level=warning.
* Tail behaviour — latest (bottom) lines come back first (index 0).
* Malformed JSON line → skipped, does not crash the whole call.
* ``min_level`` filter respected (info events filtered when min_level=warning).
* Missing log file → empty list (not an exception).
* Unconfigured log file (settings.log_file = None) → empty list.
* ``limit`` is respected — at most N events returned.
* ``critical`` min_level filters out warning/error events.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from drevalis.services.event_log import LogEvent, read_recent_events

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(log_file: str | None) -> Any:
    """Return a minimal MagicMock that satisfies the event_log service."""
    s = MagicMock()
    s.log_file = log_file
    return s


def _json_line(
    *,
    level: str,
    event: str,
    logger_name: str = "test.module",
    ts: str | None = None,
    **extra: Any,
) -> str:
    """Serialise a structlog-style JSON line."""
    record: dict[str, Any] = {
        "level": level,
        "event": event,
        "logger": logger_name,
        "timestamp": ts or datetime.now(UTC).isoformat(),
        **extra,
    }
    return json.dumps(record)


def _write_lines(path: Path, lines: list[str]) -> None:
    """Write log lines to *path*, one per line."""
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReadRecentEventsEmptyFile:
    """Empty or whitespace-only file → empty list."""

    async def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        log_file.write_text("", encoding="utf-8")
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings)

        assert result == []

    async def test_whitespace_only_lines_returns_empty_list(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        log_file.write_text("   \n\n  \t\n", encoding="utf-8")
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings)

        assert result == []


class TestReadRecentEventsMissingFile:
    """Non-existent or unconfigured log file → empty list."""

    async def test_missing_log_file_returns_empty_list(self, tmp_path: Path) -> None:
        settings = _make_settings(str(tmp_path / "does_not_exist.json"))

        result = await read_recent_events(settings)

        assert result == []

    async def test_unconfigured_log_file_returns_empty_list(self) -> None:
        settings = _make_settings(None)

        result = await read_recent_events(settings)

        assert result == []


class TestReadRecentEventsLevelFilter:
    """Only events >= min_level are returned."""

    async def test_only_warning_and_above_by_default(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                _json_line(level="info", event="info_event"),
                _json_line(level="debug", event="debug_event"),
                _json_line(level="warning", event="warning_event"),
                _json_line(level="error", event="error_event"),
                _json_line(level="critical", event="critical_event"),
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings, min_level="warning")

        event_names = {e.event for e in result}
        assert "warning_event" in event_names
        assert "error_event" in event_names
        assert "critical_event" in event_names
        assert "info_event" not in event_names
        assert "debug_event" not in event_names

    async def test_info_events_filtered_when_min_level_warning(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                _json_line(level="info", event="startup_message"),
                _json_line(level="warning", event="disk_low"),
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings, min_level="warning")

        assert len(result) == 1
        assert result[0].event == "disk_low"

    async def test_critical_min_level_filters_warning_and_error(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                _json_line(level="warning", event="warn_event"),
                _json_line(level="error", event="error_event"),
                _json_line(level="critical", event="crit_event"),
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings, min_level="critical")

        assert len(result) == 1
        assert result[0].level == "critical"
        assert result[0].event == "crit_event"

    async def test_error_min_level_includes_error_and_critical(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                _json_line(level="warning", event="warn_event"),
                _json_line(level="error", event="error_event"),
                _json_line(level="critical", event="crit_event"),
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings, min_level="error")

        event_names = {e.event for e in result}
        assert "error_event" in event_names
        assert "crit_event" in event_names
        assert "warn_event" not in event_names


class TestReadRecentEventsTailBehaviour:
    """Latest events (bottom of file) appear first in the result."""

    async def test_newest_event_is_first(self, tmp_path: Path) -> None:
        ts_old = "2026-01-01T00:00:00+00:00"
        ts_new = "2026-06-01T00:00:00+00:00"
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                _json_line(level="error", event="old_error", ts=ts_old),
                _json_line(level="error", event="new_error", ts=ts_new),
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings, min_level="error")

        assert len(result) == 2
        # newest (bottom of file) should be index 0
        assert result[0].event == "new_error"
        assert result[1].event == "old_error"

    async def test_limit_returns_n_most_recent(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        lines = [_json_line(level="error", event=f"error_{i}") for i in range(10)]
        _write_lines(log_file, lines)
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings, limit=3, min_level="error")

        assert len(result) == 3
        # Last written lines = error_9, error_8, error_7
        assert result[0].event == "error_9"
        assert result[1].event == "error_8"
        assert result[2].event == "error_7"


class TestReadRecentEventsMalformedJSON:
    """Malformed JSON lines are silently skipped; valid lines still parsed."""

    async def test_malformed_line_skipped(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                _json_line(level="error", event="good_event"),
                "this is not json {{{",
                _json_line(level="warning", event="another_good_event"),
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings)

        event_names = {e.event for e in result}
        assert "good_event" in event_names
        assert "another_good_event" in event_names
        assert len(result) == 2

    async def test_all_malformed_returns_empty_list(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                "not json",
                "also not json",
                "{broken",
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings)

        assert result == []

    async def test_partial_file_end_line_skipped(self, tmp_path: Path) -> None:
        """A truncated last line (power loss mid-write) must not crash."""
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                _json_line(level="error", event="complete_event"),
                '{"level": "error", "event": "truncat',  # incomplete JSON
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings)

        assert len(result) == 1
        assert result[0].event == "complete_event"


class TestReadRecentEventsReturnShape:
    """The returned ``LogEvent`` objects have the expected field values."""

    async def test_fields_populated_correctly(self, tmp_path: Path) -> None:
        ts = "2026-05-07T12:34:56+00:00"
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                _json_line(
                    level="error",
                    event="db_connection_failed",
                    logger_name="drevalis.core.database",
                    ts=ts,
                    episode_id="abc-123",
                    attempt=3,
                ),
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings)

        assert len(result) == 1
        ev = result[0]
        assert isinstance(ev, LogEvent)
        assert ev.level == "error"
        assert ev.event == "db_connection_failed"
        assert ev.logger == "drevalis.core.database"
        assert ev.timestamp == datetime.fromisoformat(ts)
        # episode_id is context, not a top-level field
        assert ev.context["episode_id"] == "abc-123"
        assert ev.context["attempt"] == 3

    async def test_multi_file_merge_by_timestamp(self, tmp_path: Path) -> None:
        """Multiple ``*.json`` files in the same directory merge by
        timestamp newest-first. Mirrors the docker-compose layout where
        ``app.json`` and ``worker.json`` share a bind-mount volume.
        """
        # App writes one event at T0, worker writes one at T1 > T0.
        app_log = tmp_path / "app.json"
        worker_log = tmp_path / "worker.json"
        _write_lines(
            app_log,
            [
                _json_line(
                    level="error",
                    event="app_event",
                    ts="2026-05-07T10:00:00+00:00",
                ),
            ],
        )
        _write_lines(
            worker_log,
            [
                _json_line(
                    level="error",
                    event="worker_event",
                    ts="2026-05-07T10:30:00+00:00",
                ),
            ],
        )
        # ``LOG_FILE`` is set to one of the two — the merge picks up the
        # sibling automatically.
        settings = _make_settings(str(app_log))

        result = await read_recent_events(settings)

        assert len(result) == 2
        # Newest-first: worker_event (10:30) before app_event (10:00).
        assert result[0].event == "worker_event"
        assert result[1].event == "app_event"

    async def test_context_excludes_structural_keys(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.json"
        _write_lines(
            log_file,
            [
                _json_line(
                    level="warning",
                    event="low_disk",
                    logger_name="drevalis.services.storage",
                    free_bytes=1024,
                ),
            ],
        )
        settings = _make_settings(str(log_file))

        result = await read_recent_events(settings)

        assert len(result) == 1
        ctx = result[0].context
        # Structural keys must NOT appear in context
        assert "level" not in ctx
        assert "event" not in ctx
        assert "logger" not in ctx
        assert "timestamp" not in ctx
        # Domain data must be present
        assert ctx["free_bytes"] == 1024
