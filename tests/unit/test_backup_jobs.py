"""Tests for the backup arq jobs (workers/jobs/backup.py).

Covers ``scheduled_backup`` (the 03:00 UTC cron) and
``restore_backup_async`` (the user-triggered destructive restore).
Restore in particular has the v0.29.8 invariant that it MUST use
``ctx['redis']`` (the worker's own pool) rather than calling
``get_pool()`` — a regression there caused real production downtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from drevalis.services.backup import BackupError
from drevalis.workers.jobs.backup import restore_backup_async, scheduled_backup

# ── Helpers ──────────────────────────────────────────────────────────


def _make_session_factory(session_mock: Any) -> Any:
    class _SF:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return session_mock

        async def __aexit__(self, *_args: Any) -> None:
            return None

    return _SF()


def _make_settings(
    *,
    auto_enabled: bool = True,
    storage_base: Path = Path("/tmp/storage"),
    backup_dir: Path = Path("/tmp/backups"),
    encryption_key: str = "k",
    retention: int = 7,
) -> Any:
    s = MagicMock()
    s.backup_auto_enabled = auto_enabled
    s.storage_base_path = storage_base
    s.backup_directory = backup_dir
    s.encryption_key = encryption_key
    s.backup_retention = retention
    return s


# ── scheduled_backup ─────────────────────────────────────────────────


class TestScheduledBackup:
    async def test_returns_skipped_when_auto_disabled(self) -> None:
        settings = _make_settings(auto_enabled=False)
        with patch("drevalis.core.config.Settings", return_value=settings):
            result = await scheduled_backup({})
        assert result == {"skipped": "disabled"}

    async def test_success_returns_archive_metadata(self, tmp_path: Path) -> None:
        # Synthesize an archive file so the job's stat() call works.
        archive = tmp_path / "drevalis-backup-2026-05-01.tar.gz"
        archive.write_bytes(b"\x00" * 4096)

        settings = _make_settings()
        svc_mock = MagicMock()
        svc_mock.create_backup = AsyncMock(return_value=archive)
        svc_mock.prune = MagicMock(return_value=["drevalis-backup-old.tar.gz"])

        session = AsyncMock()
        session_factory = _make_session_factory(session)

        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch(
                "drevalis.services.backup.BackupService",
                return_value=svc_mock,
            ),
        ):
            result = await scheduled_backup({"session_factory": session_factory})

        assert result["status"] == "ok"
        assert result["archive"] == archive.name
        assert result["size_bytes"] == 4096
        assert result["pruned"] == ["drevalis-backup-old.tar.gz"]

    async def test_exception_returns_failed_with_truncated_error(self) -> None:
        settings = _make_settings()
        svc_mock = MagicMock()
        svc_mock.create_backup = AsyncMock(side_effect=RuntimeError("disk full: " + "x" * 500))
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=settings),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch(
                "drevalis.services.backup.BackupService",
                return_value=svc_mock,
            ),
        ):
            result = await scheduled_backup({"session_factory": _make_session_factory(session)})

        assert result["status"] == "failed"
        # Error truncated to 200 chars (DB-friendly).
        assert len(result["error"]) <= 200
        assert "disk full" in result["error"]


# ── restore_backup_async ─────────────────────────────────────────────


class _RecordingRedis:
    """Minimal stand-in for the arq Redis pool that records SETs + DELs."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any], int | None]] = []
        self.deletes: list[str] = []

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            payload = {"raw": value}
        self.writes.append((key, payload, ex))

    async def delete(self, *keys: str) -> int:
        self.deletes.extend(keys)
        return len(keys)


class TestRestoreBackupAsync:
    def _ctx(self, redis: _RecordingRedis, session: Any) -> dict[str, Any]:
        return {
            "redis": redis,
            "session_factory": _make_session_factory(session),
        }

    async def test_uses_ctx_redis_not_global_pool(self, tmp_path: Path) -> None:
        # v0.29.8 hotfix invariant: the job MUST read Redis from
        # ``ctx['redis']`` (the worker's pool) rather than calling
        # ``get_pool()`` — the latter raised "Redis connection pool is
        # not initialised" at the worker's first restore attempt.
        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()

        svc = MagicMock()
        svc.restore_backup = AsyncMock(
            return_value={
                "rows_inserted": {"episodes": 5, "series": 1},
                "storage_paths_restored": ["episodes/", "audiobooks/"],
            }
        )
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            result = await restore_backup_async(
                self._ctx(redis, session),
                "job-1",
                str(archive),
            )

        assert result["status"] == "done"
        # Initial "starting" status + final "done" status both written
        # via the captured ctx redis (proves no global-pool fallback).
        statuses = [w[1].get("status") for w in redis.writes]
        assert "running" in statuses
        assert "done" in statuses

    async def test_progress_callback_threaded_into_service(self, tmp_path: Path) -> None:
        # The route gives the user a progress bar by polling the Redis
        # status key; the job's progress_cb must write to that key on
        # every stage transition the BackupService emits.
        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()
        captured_cb: list[Any] = []

        async def _fake_restore(
            session: Any,
            archive_path: Path,
            *,
            progress_cb: Any,
            **_kwargs: Any,
        ) -> dict[str, Any]:
            captured_cb.append(progress_cb)
            await progress_cb("extract", 25, "Extracting archive...")
            await progress_cb("rows", 60, "Inserting rows...")
            return {"rows_inserted": {}, "storage_paths_restored": []}

        svc = MagicMock()
        svc.restore_backup = AsyncMock(side_effect=_fake_restore)
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            await restore_backup_async(self._ctx(redis, session), "job-1", str(archive))

        # Service got a non-None callable.
        assert captured_cb and captured_cb[0] is not None
        # Each stage produced a "running" status with the percentage.
        running_writes = [w for w in redis.writes if w[1].get("status") == "running"]
        # Initial "starting" + 2 progress callbacks = 3 running writes.
        assert len(running_writes) >= 3

    async def test_backup_error_writes_failed_status(self, tmp_path: Path) -> None:
        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()
        svc = MagicMock()
        svc.restore_backup = AsyncMock(side_effect=BackupError("invalid manifest"))
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            result = await restore_backup_async(self._ctx(redis, session), "job-1", str(archive))

        assert result["status"] == "failed"
        assert "invalid manifest" in result["error"]
        # Failed status visible in Redis for the polling UI.
        failed = [w for w in redis.writes if w[1].get("status") == "failed"]
        assert len(failed) == 1
        assert "invalid manifest" in failed[0][1]["message"]

    async def test_unexpected_exception_truncated_to_500(self, tmp_path: Path) -> None:
        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()
        svc = MagicMock()
        svc.restore_backup = AsyncMock(side_effect=RuntimeError("boom: " + "x" * 1000))
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            result = await restore_backup_async(self._ctx(redis, session), "job-1", str(archive))

        assert result["status"] == "failed"
        # Error in the response is the raw exception string (Python
        # str(exc) doesn't truncate; only the Redis payload uses 500).
        assert "boom" in result["error"]
        # Redis ``error`` key truncated.
        failed = [w for w in redis.writes if w[1].get("status") == "failed"]
        assert len(failed) == 1
        assert len(failed[0][1]["error"]) <= 500

    async def test_archive_deleted_when_flag_true(self, tmp_path: Path) -> None:
        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()
        svc = MagicMock()
        svc.restore_backup = AsyncMock(
            return_value={"rows_inserted": {}, "storage_paths_restored": []}
        )
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            await restore_backup_async(
                self._ctx(redis, session),
                "job-1",
                str(archive),
                delete_archive_when_done=True,
            )

        assert archive.exists() is False

    async def test_archive_kept_when_flag_false(self, tmp_path: Path) -> None:
        # The "restore from existing archive" path passes
        # ``delete_archive_when_done=False`` so the operator can retry
        # the same restore without re-uploading 22GB.
        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()
        svc = MagicMock()
        svc.restore_backup = AsyncMock(
            return_value={"rows_inserted": {}, "storage_paths_restored": []}
        )
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            await restore_backup_async(
                self._ctx(redis, session),
                "job-1",
                str(archive),
                delete_archive_when_done=False,
            )

        assert archive.exists() is True

    async def test_archive_deleted_even_on_failure(self, tmp_path: Path) -> None:
        # Defensive: when the upload temp file is being processed
        # (delete_when_done=True), the temp file should be cleaned up
        # even when the restore itself raises so we don't accumulate
        # multi-GB junk in BACKUP_DIRECTORY.
        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()
        svc = MagicMock()
        svc.restore_backup = AsyncMock(side_effect=RuntimeError("boom"))
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            await restore_backup_async(
                self._ctx(redis, session),
                "job-1",
                str(archive),
                delete_archive_when_done=True,
            )

        assert archive.exists() is False

    async def test_passes_flags_through_to_service(self, tmp_path: Path) -> None:
        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()
        svc = MagicMock()
        svc.restore_backup = AsyncMock(
            return_value={"rows_inserted": {}, "storage_paths_restored": []}
        )
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            await restore_backup_async(
                self._ctx(redis, session),
                "job-1",
                str(archive),
                allow_key_mismatch=True,
                restore_db=False,
                restore_media=True,
            )

        kwargs = svc.restore_backup.call_args.kwargs
        assert kwargs["allow_key_mismatch"] is True
        assert kwargs["restore_db"] is False
        assert kwargs["restore_media"] is True

    async def test_storage_probe_cache_busted_on_success(self, tmp_path: Path) -> None:
        # Pin: a successful restore busts the storage_probe cache so the
        # next Backup-tab load reflects live post-restore state instead
        # of the pre-restore snapshot the route may have cached up to
        # 5 minutes earlier.
        from drevalis.core.cache_keys import STORAGE_PROBE_CACHE_KEY

        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()
        svc = MagicMock()
        svc.restore_backup = AsyncMock(
            return_value={"rows_inserted": {}, "storage_paths_restored": []}
        )
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            await restore_backup_async(self._ctx(redis, session), "job-1", str(archive))

        assert STORAGE_PROBE_CACHE_KEY in redis.deletes

    async def test_storage_probe_cache_busted_on_failure(self, tmp_path: Path) -> None:
        # Pin: a failed restore can leave storage in a partial state —
        # the operator needs fresh signal on the Backup tab even more
        # than after a clean restore. So the cache bust runs in the
        # ``finally`` block, not just the success path.
        from drevalis.core.cache_keys import STORAGE_PROBE_CACHE_KEY

        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)
        redis = _RecordingRedis()
        svc = MagicMock()
        svc.restore_backup = AsyncMock(side_effect=RuntimeError("boom"))
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            await restore_backup_async(self._ctx(redis, session), "job-1", str(archive))

        assert STORAGE_PROBE_CACHE_KEY in redis.deletes

    async def test_cache_bust_failure_swallowed(self, tmp_path: Path) -> None:
        # Pin: a Redis hiccup on the cache-bust path doesn't 500 the
        # job — the cache will expire on its own within 5 min anyway.
        archive = tmp_path / "snap.tar.gz"
        archive.write_bytes(b"\x00" * 100)

        class _FailingDeleteRedis(_RecordingRedis):
            async def delete(self, *keys: str) -> int:
                raise ConnectionError("redis down")

        redis = _FailingDeleteRedis()
        svc = MagicMock()
        svc.restore_backup = AsyncMock(
            return_value={"rows_inserted": {}, "storage_paths_restored": []}
        )
        session = AsyncMock()

        with (
            patch("drevalis.core.config.Settings", return_value=_make_settings()),
            patch(
                "drevalis.services.updates._resolve_current_version",
                return_value="0.29.99",
            ),
            patch("drevalis.services.backup.BackupService", return_value=svc),
        ):
            # Must not raise.
            result = await restore_backup_async(self._ctx(redis, session), "job-1", str(archive))

        assert result["status"] == "done"
