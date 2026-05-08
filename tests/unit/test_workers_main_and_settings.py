"""Tests for ``workers/__main__.py`` (Redis preflight) and
``workers/settings.py`` (arq config).

Pin:

* `_redis_host_port` parses the env URL with sensible defaults.
* `_wait_for_redis` succeeds when the host is reachable; loops with
  backoff on `gaierror`; raises `SystemExit(1)` after the deadline
  with a multi-line operator-friendly message.
* `_redis_settings_from_config` parses the URL into arq RedisSettings
  with the conn-timeout/retries headroom over arq's defaults.
* `WorkerSettings` carries every job function + cron schedule the
  spec lists; `max_jobs` honoured; `keep_result` 1h.
"""

from __future__ import annotations

import socket
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from drevalis.workers.__main__ import _redis_host_port, _wait_for_redis
from drevalis.workers.settings import (
    WorkerSettings,
    _redis_settings_from_config,
)

# ── _redis_host_port ───────────────────────────────────────────────


class TestRedisHostPort:
    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert _redis_host_port() == ("redis", 6379)

    def test_parses_full_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://my-redis:6380/3")
        assert _redis_host_port() == ("my-redis", 6380)

    def test_falls_back_to_redis_when_no_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://")
        host, port = _redis_host_port()
        # Defaults preserved.
        assert host == "redis"
        assert port == 6379


# ── _wait_for_redis ────────────────────────────────────────────────


class TestWaitForRedis:
    async def test_first_attempt_succeeds(self) -> None:
        # Stub asyncio.open_connection to "succeed" — return mock
        # reader/writer pair.
        async def _fake_open(host: str, port: int) -> Any:
            reader = MagicMock()
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            return reader, writer

        async def _fake_wait_for(coro: Any, *, timeout: float) -> Any:
            return await coro

        with (
            patch(
                "drevalis.workers.__main__.asyncio.open_connection",
                _fake_open,
            ),
            patch(
                "drevalis.workers.__main__.asyncio.wait_for",
                _fake_wait_for,
            ),
        ):
            # Must not raise / sys.exit.
            await _wait_for_redis("localhost", 6379, total_seconds=1.0)

    async def test_writer_close_failure_swallowed(self) -> None:
        # Pin: writer.wait_closed raises → preflight still returns ok
        # (we just want the connection to have been established).
        async def _fake_open(host: str, port: int) -> Any:
            reader = MagicMock()
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock(side_effect=OSError("close failed"))
            return reader, writer

        async def _fake_wait_for(coro: Any, *, timeout: float) -> Any:
            return await coro

        with (
            patch(
                "drevalis.workers.__main__.asyncio.open_connection",
                _fake_open,
            ),
            patch(
                "drevalis.workers.__main__.asyncio.wait_for",
                _fake_wait_for,
            ),
        ):
            await _wait_for_redis("localhost", 6379, total_seconds=1.0)

    async def test_dns_failure_then_success(self) -> None:
        # First attempt raises gaierror, second attempt succeeds.
        # Pin: the loop logs a "DNS lookup failed" warning and retries.
        attempts = {"n": 0}

        async def _fake_open(host: str, port: int) -> Any:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise socket.gaierror(-5, "DNS NX")
            reader = MagicMock()
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            return reader, writer

        async def _fake_wait_for(coro: Any, *, timeout: float) -> Any:
            return await coro

        async def _no_sleep(_seconds: float) -> None:
            return None

        with (
            patch(
                "drevalis.workers.__main__.asyncio.open_connection",
                _fake_open,
            ),
            patch(
                "drevalis.workers.__main__.asyncio.wait_for",
                _fake_wait_for,
            ),
            patch(
                "drevalis.workers.__main__.asyncio.sleep",
                _no_sleep,
            ),
        ):
            await _wait_for_redis("localhost", 6379, total_seconds=10.0)
        assert attempts["n"] == 2

    async def test_persistent_failure_exits_with_message(self) -> None:
        # All attempts fail (DNS NX). Pin: after the deadline,
        # `sys.exit(1)` is called and a multi-line operator-friendly
        # message is written to stderr.
        async def _always_fail(host: str, port: int) -> Any:
            raise socket.gaierror(-5, "DNS NX")

        async def _fake_wait_for(coro: Any, *, timeout: float) -> Any:
            return await coro

        async def _no_sleep(_seconds: float) -> None:
            return None

        captured: list[str] = []

        def _capture_write(msg: str) -> None:
            captured.append(msg)

        with (
            patch(
                "drevalis.workers.__main__.asyncio.open_connection",
                _always_fail,
            ),
            patch(
                "drevalis.workers.__main__.asyncio.wait_for",
                _fake_wait_for,
            ),
            patch(
                "drevalis.workers.__main__.asyncio.sleep",
                _no_sleep,
            ),
            patch.object(sys.stderr, "write", _capture_write),
        ):
            with pytest.raises(SystemExit) as exc:
                await _wait_for_redis(
                    "nonexistent",
                    6379,
                    total_seconds=0.01,  # immediate deadline
                    initial_delay=0.001,
                    max_delay=0.001,
                )
        assert exc.value.code == 1
        # The stderr message includes the operator hints.
        msg_text = " ".join(captured)
        assert "FATAL" in msg_text
        assert "docker compose ps redis" in msg_text
        assert "docker compose logs redis" in msg_text

    async def test_connect_timeout_classified_distinctly(self) -> None:
        # Pin: `OSError` / `TimeoutError` produces a different log
        # message than `gaierror` so a real misconfig is obvious.
        async def _always_timeout(host: str, port: int) -> Any:
            raise TimeoutError("connect timed out")

        async def _fake_wait_for(coro: Any, *, timeout: float) -> Any:
            return await coro

        async def _no_sleep(_seconds: float) -> None:
            return None

        captured: list[str] = []

        with (
            patch(
                "drevalis.workers.__main__.asyncio.open_connection",
                _always_timeout,
            ),
            patch(
                "drevalis.workers.__main__.asyncio.wait_for",
                _fake_wait_for,
            ),
            patch(
                "drevalis.workers.__main__.asyncio.sleep",
                _no_sleep,
            ),
            patch.object(sys.stderr, "write", lambda m: captured.append(m)),
        ):
            with pytest.raises(SystemExit):
                await _wait_for_redis(
                    "localhost",
                    6379,
                    total_seconds=0.01,
                    initial_delay=0.001,
                    max_delay=0.001,
                )
        msg_text = " ".join(captured)
        # Different error class surfaced in the failure message.
        assert "TimeoutError" in msg_text


# ── _redis_settings_from_config ────────────────────────────────────


class TestRedisSettingsFromConfig:
    def test_parses_full_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Build a Settings with a non-default redis URL.
        import base64

        monkeypatch.setenv(
            "ENCRYPTION_KEY",
            base64.urlsafe_b64encode(b"\x00" * 32).decode(),
        )
        monkeypatch.setenv("REDIS_URL", "redis://:secret@my-redis:6380/3")
        out = _redis_settings_from_config()
        assert out.host == "my-redis"
        assert out.port == 6380
        assert out.database == 3
        assert out.password == "secret"

    def test_invalid_database_falls_back_to_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: a non-numeric path segment doesn't crash settings build —
        # falls back to db=0.
        import base64

        monkeypatch.setenv(
            "ENCRYPTION_KEY",
            base64.urlsafe_b64encode(b"\x00" * 32).decode(),
        )
        monkeypatch.setenv("REDIS_URL", "redis://r:6379/notanint")
        out = _redis_settings_from_config()
        assert out.database == 0

    def test_no_path_yields_db_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import base64

        monkeypatch.setenv(
            "ENCRYPTION_KEY",
            base64.urlsafe_b64encode(b"\x00" * 32).decode(),
        )
        monkeypatch.setenv("REDIS_URL", "redis://r:6379")
        out = _redis_settings_from_config()
        assert out.database == 0

    def test_retry_headroom_over_arq_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: conn_timeout=5, conn_retries=5, conn_retry_delay=2.
        # Arq's defaults are smaller — ours give a fresh boot ~35s of
        # Redis-not-yet-up tolerance.
        import base64

        monkeypatch.setenv(
            "ENCRYPTION_KEY",
            base64.urlsafe_b64encode(b"\x00" * 32).decode(),
        )
        monkeypatch.setenv("REDIS_URL", "redis://r:6379/0")
        out = _redis_settings_from_config()
        assert out.conn_timeout == 5
        assert out.conn_retries == 5
        assert out.conn_retry_delay == 2


# ── WorkerSettings class ───────────────────────────────────────────


class TestWorkerSettings:
    def test_includes_every_documented_job(self) -> None:
        # Sanity check: the function list contains all the workers we
        # ship. Drift here means a job got registered without docs or
        # vice versa.
        # arq's `func(...)` wrapper returns a Function-like object;
        # raw functions appear by name. Build a set of either-or.
        names: set[str] = set()
        for fn in WorkerSettings.functions:
            n = getattr(fn, "name", None) or getattr(fn, "__name__", None)
            if n:
                names.add(n)

        # Documented in CLAUDE.md.
        expected_subset = {
            "generate_episode",
            "generate_audiobook",
            "regenerate_audiobook_chapter",
            "regenerate_audiobook_chapter_image",
            "retry_episode_step",
            "reassemble_episode",
            "regenerate_voice",
            "regenerate_scene",
            "generate_script_async",
            "generate_series_async",
            "generate_episode_music",
            "generate_seo_async",
            "publish_scheduled_posts",
            "publish_pending_social_uploads",
            "compute_ab_test_winners",
            "auto_deploy_runpod_pod",
            "worker_heartbeat",
            "license_heartbeat",
            "scheduled_backup",
            "restore_backup_async",
            "analyze_video_ingest",
            "commit_video_ingest_clip",
            "render_from_edit",
        }
        missing = expected_subset - names
        assert not missing, f"missing job functions: {missing}"

    def test_max_jobs_is_8(self) -> None:
        # Pin from CLAUDE.md: max 4 episodes in parallel, 8 total slots.
        assert WorkerSettings.max_jobs == 8

    def test_retry_config(self) -> None:
        assert WorkerSettings.retry_jobs is True
        assert WorkerSettings.max_tries == 3

    def test_keep_result_1_hour(self) -> None:
        assert WorkerSettings.keep_result == 3600
        assert WorkerSettings.keep_result_forever is False

    def test_lifecycle_hooks_wired(self) -> None:
        from drevalis.workers.lifecycle import on_job_start, shutdown, startup

        assert WorkerSettings.on_startup is startup
        assert WorkerSettings.on_shutdown is shutdown
        assert WorkerSettings.on_job_start is on_job_start

    def test_cron_jobs_present(self) -> None:
        # 7 cron entries documented (publish-posts every 5min, social
        # publish every 5min, heartbeat every min, license heartbeat
        # daily, ab winner daily, nightly backup, prune scheduled posts).
        assert len(WorkerSettings.cron_jobs) == 7

    def test_job_timeout_uses_longform_setting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The class is built at import time, so this is just a smoke
        # check: the value must be a positive int (default 14400 = 4h).
        assert isinstance(WorkerSettings.job_timeout, int)
        assert WorkerSettings.job_timeout > 0
