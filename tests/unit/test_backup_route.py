"""Tests for ``api/routes/backup.py``.

Backup CRUD, restore enqueue, restore-status polling, scheduled cron
hook. Pin:

* `_safe_backup_path` rejects path-traversal attempts (slash/backslash
  in name, leading dot, resolving outside the backup root).
* `_seed_restore_status` writes the placeholder ``queued`` payload
  BEFORE the worker picks up — this is the v0.29.11 hotfix invariant.
* `restore_backup` and `restore_from_existing` reject missing
  X-Confirm-Restore header, reject non-tar.gz uploads, write the
  multipart stream to the backup dir, and enqueue with the
  ``delete_archive_when_done`` flag set correctly per endpoint.
* `get_restore_status`: Redis miss → ``unknown`` (terminal),
  Redis hit → parsed payload with `job_id` injected.
* `run_scheduled_backup` no-ops when `BACKUP_AUTO_ENABLED=false`,
  invokes the service when true.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from drevalis.api.routes.backup import (
    _detect_host_source,
    _detect_mount_fs,
    _safe_backup_path,
    _seed_restore_status,
    _service,
    create_backup,
    delete_backup,
    download_backup,
    get_restore_status,
    list_backups,
    repair_media,
    restore_backup,
    restore_from_existing,
    run_scheduled_backup,
)


def _settings(tmp_path: Path) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    s.backup_directory = tmp_path / "backups"
    s.backup_retention = 7
    s.backup_auto_enabled = False
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    return s


def _upload(content: bytes, filename: str = "x.tar.gz") -> Any:
    f = MagicMock(spec=UploadFile)
    f.filename = filename
    chunks = [content[i : i + 4 * 1024 * 1024] for i in range(0, len(content), 4 * 1024 * 1024)] + [
        b""
    ]

    async def _read(_size: int = 0) -> bytes:
        return chunks.pop(0) if chunks else b""

    f.read = AsyncMock(side_effect=_read)
    return f


# ── _service factory ───────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_backup_service(self, tmp_path: Path) -> None:
        from drevalis.services.backup import BackupService

        with patch(
            "drevalis.services.updates._resolve_current_version",
            return_value="0.29.74",
        ):
            svc = _service(_settings(tmp_path))
        assert isinstance(svc, BackupService)


# ── _safe_backup_path ──────────────────────────────────────────────


class TestSafeBackupPath:
    def test_slash_in_name_rejected(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        with pytest.raises(HTTPException) as exc:
            _safe_backup_path(s, "../etc/passwd")
        assert exc.value.status_code == 400

    def test_backslash_in_name_rejected(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        with pytest.raises(HTTPException) as exc:
            _safe_backup_path(s, "..\\etc\\passwd")
        assert exc.value.status_code == 400

    def test_dotfile_rejected(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        with pytest.raises(HTTPException) as exc:
            _safe_backup_path(s, ".secret")
        assert exc.value.status_code == 400

    def test_legal_name_accepted(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        out = _safe_backup_path(s, "backup-2026-05-02.tar.gz")
        assert out.parent == s.backup_directory.resolve()


# ── _seed_restore_status ───────────────────────────────────────────


class TestSeedRestoreStatus:
    async def test_writes_queued_payload_with_ttl(self) -> None:
        # Pin the v0.29.11 hotfix: the placeholder lands in Redis BEFORE
        # the worker writes its first status, so a frontend poll inside
        # the race window sees ``queued`` instead of ``unknown``.
        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.core.redis.get_pool", return_value=MagicMock()),
            patch("redis.asyncio.Redis", return_value=redis),
        ):
            await _seed_restore_status("job-123")

        redis.set.assert_awaited_once()
        args, kwargs = redis.set.await_args
        # Redis key is namespaced.
        assert args[0] == "backup:restore:job-123"
        payload = json.loads(args[1])
        assert payload["status"] == "queued"
        assert payload["stage"] == "queued"
        assert payload["progress_pct"] == 0
        # 1-hour TTL matches worker.
        assert kwargs["ex"] == 3600
        # aclose runs in finally.
        redis.aclose.assert_awaited_once()


# ── GET / list ─────────────────────────────────────────────────────


class TestListBackups:
    async def test_returns_archives_and_settings_meta(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        with (
            patch(
                "drevalis.api.routes.backup._service",
                return_value=MagicMock(list_backups=MagicMock(return_value=[{"name": "a.tar.gz"}])),
            ),
            patch(
                "drevalis.api.routes.backup._detect_host_source",
                return_value="/srv/storage/backups",
            ),
        ):
            out = await list_backups(settings=s)
        assert out["retention"] == 7
        assert out["auto_enabled"] is False
        assert out["archives"] == [{"name": "a.tar.gz"}]
        assert out["backup_directory_host_source"] == "/srv/storage/backups"


# ── POST / create ──────────────────────────────────────────────────


class TestCreateBackup:
    async def test_success_returns_metadata_and_prunes(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        archive = s.backup_directory / "backup.tar.gz"
        archive.write_bytes(b"fake-archive")

        svc = MagicMock()
        svc.create_backup = AsyncMock(return_value=archive)
        svc.prune = MagicMock(return_value=2)
        with patch("drevalis.api.routes.backup._service", return_value=svc):
            out = await create_backup(db=AsyncMock(), settings=s, include_media=True)
        assert out["filename"] == "backup.tar.gz"
        assert out["size_bytes"] > 0
        assert out["pruned"] == 2
        svc.prune.assert_called_once_with(7)

    async def test_service_failure_maps_to_500(self, tmp_path: Path) -> None:
        # BLE001 in the route — anything raised by the service must
        # surface as 500 with the message in the detail.
        s = _settings(tmp_path)
        svc = MagicMock()
        svc.create_backup = AsyncMock(side_effect=RuntimeError("disk full"))
        with patch("drevalis.api.routes.backup._service", return_value=svc):
            with pytest.raises(HTTPException) as exc:
                await create_backup(db=AsyncMock(), settings=s, include_media=True)
        assert exc.value.status_code == 500
        assert "disk full" in exc.value.detail


# ── GET /{filename} download ───────────────────────────────────────


class TestDownloadBackup:
    async def test_returns_file_response(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        archive = s.backup_directory / "x.tar.gz"
        archive.write_bytes(b"fake")
        out = await download_backup(filename="x.tar.gz", settings=s)
        assert Path(str(out.path)) == archive
        assert out.media_type == "application/gzip"

    async def test_404_when_missing(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        with pytest.raises(HTTPException) as exc:
            await download_backup(filename="missing.tar.gz", settings=s)
        assert exc.value.status_code == 404

    async def test_traversal_rejected_in_filename(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        with pytest.raises(HTTPException) as exc:
            await download_backup(filename="../../etc/passwd", settings=s)
        assert exc.value.status_code == 400


# ── DELETE /{filename} ─────────────────────────────────────────────


class TestDeleteBackup:
    async def test_deletes_existing_archive(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        archive = s.backup_directory / "x.tar.gz"
        archive.write_bytes(b"fake")
        await delete_backup(filename="x.tar.gz", settings=s)
        assert not archive.exists()

    async def test_404_when_missing(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        with pytest.raises(HTTPException) as exc:
            await delete_backup(filename="missing.tar.gz", settings=s)
        assert exc.value.status_code == 404


# ── POST /restore (multipart) ──────────────────────────────────────


class TestRestoreBackup:
    async def test_missing_confirm_header_400(self, tmp_path: Path) -> None:
        with pytest.raises(HTTPException) as exc:
            await restore_backup(
                file=_upload(b"data"),
                confirm="",
                allow_key_mismatch=False,
                restore_db=True,
                restore_media=True,
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 400

    async def test_wrong_confirm_value_400(self, tmp_path: Path) -> None:
        with pytest.raises(HTTPException) as exc:
            await restore_backup(
                file=_upload(b"data"),
                confirm="yes",
                allow_key_mismatch=False,
                restore_db=True,
                restore_media=True,
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 400

    async def test_non_tar_gz_400(self, tmp_path: Path) -> None:
        with pytest.raises(HTTPException) as exc:
            await restore_backup(
                file=_upload(b"data", filename="x.zip"),
                confirm="i-understand",
                allow_key_mismatch=False,
                restore_db=True,
                restore_media=True,
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 400

    async def test_missing_filename_400(self, tmp_path: Path) -> None:
        f = MagicMock(spec=UploadFile)
        f.filename = None
        with pytest.raises(HTTPException) as exc:
            await restore_backup(
                file=f,
                confirm="i-understand",
                allow_key_mismatch=False,
                restore_db=True,
                restore_media=True,
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 400

    async def test_success_writes_archive_and_enqueues(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        arq = MagicMock()
        arq.enqueue_job = AsyncMock()

        with (
            patch("drevalis.api.routes.backup._seed_restore_status", AsyncMock()),
            patch("drevalis.core.redis.get_arq_pool", return_value=arq),
        ):
            out = await restore_backup(
                file=_upload(b"\x1f\x8b" + b"fake-tar-gz", filename="x.tar.gz"),
                confirm="i-understand",
                allow_key_mismatch=True,
                restore_db=True,
                restore_media=False,
                settings=s,
            )

        assert out["status"] == "queued"
        # The temp archive landed under the backup dir, not /tmp.
        assert s.backup_directory.exists()
        # arq enqueue ran with the v0.29.11-correct kwargs:
        arq.enqueue_job.assert_awaited_once()
        kwargs = arq.enqueue_job.call_args.kwargs
        assert kwargs["allow_key_mismatch"] is True
        assert kwargs["restore_db"] is True
        assert kwargs["restore_media"] is False
        # Pin: uploaded archive is deleted when worker is done.
        assert kwargs["delete_archive_when_done"] is True


# ── POST /restore-existing/{filename} ──────────────────────────────


class TestRestoreFromExisting:
    async def test_missing_confirm_400(self, tmp_path: Path) -> None:
        with pytest.raises(HTTPException) as exc:
            await restore_from_existing(
                filename="x.tar.gz",
                confirm="",
                allow_key_mismatch=False,
                restore_db=True,
                restore_media=True,
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 400

    async def test_archive_not_found_404(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        with pytest.raises(HTTPException) as exc:
            await restore_from_existing(
                filename="missing.tar.gz",
                confirm="i-understand",
                allow_key_mismatch=False,
                restore_db=True,
                restore_media=True,
                settings=s,
            )
        assert exc.value.status_code == 404

    async def test_non_tar_gz_400(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        # File exists but wrong extension.
        (s.backup_directory / "x.zip").write_bytes(b"junk")
        with pytest.raises(HTTPException) as exc:
            await restore_from_existing(
                filename="x.zip",
                confirm="i-understand",
                allow_key_mismatch=False,
                restore_db=True,
                restore_media=True,
                settings=s,
            )
        assert exc.value.status_code == 400

    async def test_success_keeps_archive_on_disk(self, tmp_path: Path) -> None:
        # Pin: existing-archive restore sets
        # delete_archive_when_done=False so the operator keeps the
        # source they manually placed via docker cp.
        s = _settings(tmp_path)
        s.backup_directory.mkdir(parents=True)
        archive = s.backup_directory / "exists.tar.gz"
        archive.write_bytes(b"fake")

        arq = MagicMock()
        arq.enqueue_job = AsyncMock()
        with (
            patch("drevalis.api.routes.backup._seed_restore_status", AsyncMock()),
            patch("drevalis.core.redis.get_arq_pool", return_value=arq),
        ):
            out = await restore_from_existing(
                filename="exists.tar.gz",
                confirm="i-understand",
                allow_key_mismatch=False,
                restore_db=True,
                restore_media=True,
                settings=s,
            )

        assert out["filename"] == "exists.tar.gz"
        kwargs = arq.enqueue_job.call_args.kwargs
        assert kwargs["delete_archive_when_done"] is False
        # Archive still on disk.
        assert archive.exists()


# ── GET /restore-status/{job_id} ──────────────────────────────────


class TestGetRestoreStatus:
    async def test_unknown_when_redis_miss(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.core.redis.get_pool", return_value=MagicMock()),
            patch("redis.asyncio.Redis", return_value=redis),
        ):
            out = await get_restore_status("missing-job")
        assert out["status"] == "unknown"
        assert out["job_id"] == "missing-job"

    async def test_returns_parsed_payload_with_job_id(self) -> None:
        payload = {
            "status": "running",
            "stage": "extracting",
            "progress_pct": 42,
            "message": "Extracting archive...",
        }
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps(payload).encode())
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.core.redis.get_pool", return_value=MagicMock()),
            patch("redis.asyncio.Redis", return_value=redis),
        ):
            out = await get_restore_status("abc")
        assert out["status"] == "running"
        assert out["progress_pct"] == 42
        assert out["job_id"] == "abc"

    async def test_str_payload_handled(self) -> None:
        # Some redis configs auto-decode — pin: route accepts str too.
        payload = {"status": "done", "progress_pct": 100}
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps(payload))
        redis.aclose = AsyncMock()
        with (
            patch("drevalis.core.redis.get_pool", return_value=MagicMock()),
            patch("redis.asyncio.Redis", return_value=redis),
        ):
            out = await get_restore_status("abc")
        assert out["status"] == "done"


# ── _detect_mount_fs / _detect_host_source ────────────────────────


class TestDetectHelpers:
    def test_mount_fs_unreadable_returns_none(self, tmp_path: Path) -> None:
        original_read_text = Path.read_text

        def _fake(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name == "mounts" and "proc" in self.as_posix():
                raise OSError("nope")
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", _fake):
            assert _detect_mount_fs(tmp_path) is None

    def test_host_source_unreadable_returns_none(self, tmp_path: Path) -> None:
        original_read_text = Path.read_text

        def _fake(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name == "mountinfo" and "proc" in self.as_posix():
                raise OSError("nope")
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", _fake):
            assert _detect_host_source(tmp_path) is None

    def test_mount_fs_resolves_deepest_match(self, tmp_path: Path) -> None:
        path_str = str(tmp_path.resolve())
        line_root = "/dev/root / ext4 rw 0 0"
        line_deep = f"/dev/sdb {path_str} cifs rw 0 0"
        original_read_text = Path.read_text

        def _fake(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name == "mounts" and "proc" in self.as_posix():
                return f"{line_root}\n{line_deep}\n"
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", _fake):
            assert _detect_mount_fs(tmp_path) == "cifs"

    def test_host_source_resolves_exact_mount(self, tmp_path: Path) -> None:
        # Pin the simple case: path == mount_point. Avoiding the tail
        # branch here because the path-with-tail branch uses POSIX-only
        # ``startswith(mount + "/")`` which isn't reachable on Windows
        # tmp_path strings (backslashes).
        path_str = str(tmp_path.resolve())
        line = f"100 99 0:0 /srv/data {path_str} rw - ext4 /dev/x rw"
        original_read_text = Path.read_text

        def _fake(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name == "mountinfo" and "proc" in self.as_posix():
                return line + "\n"
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", _fake):
            out = _detect_host_source(Path(path_str))
        assert out == "/srv/data"


# ── repair_media ───────────────────────────────────────────────────


class TestRepairMedia:
    async def test_success_returns_report(self, tmp_path: Path) -> None:
        report = MagicMock()
        report.to_dict = MagicMock(return_value={"updated": 5, "still_missing": 0})
        redis = AsyncMock()
        redis.delete = AsyncMock()
        with patch(
            "drevalis.api.routes.backup.repair_media_links",
            AsyncMock(return_value=report),
        ):
            out = await repair_media(db=AsyncMock(), settings=_settings(tmp_path), redis=redis)
        assert out == {"updated": 5, "still_missing": 0}

    async def test_failure_maps_to_500(self, tmp_path: Path) -> None:
        redis = AsyncMock()
        redis.delete = AsyncMock()
        with patch(
            "drevalis.api.routes.backup.repair_media_links",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            with pytest.raises(HTTPException) as exc:
                await repair_media(db=AsyncMock(), settings=_settings(tmp_path), redis=redis)
        assert exc.value.status_code == 500
        assert "boom" in exc.value.detail
        # Cache bust must NOT run on the failure path — storage state is
        # unchanged, and the existing cache is still accurate.
        redis.delete.assert_not_awaited()

    async def test_success_busts_storage_probe_cache(self, tmp_path: Path) -> None:
        # Pin: a successful repair rewrites media_assets.file_path rows that
        # the probe samples; the cache must be invalidated immediately so
        # the Backup tab reflects post-repair state rather than a stale
        # pre-repair snapshot cached for up to 5 minutes.
        from drevalis.core.cache_keys import STORAGE_PROBE_CACHE_KEY

        report = MagicMock()
        report.to_dict = MagicMock(return_value={"relinked": 3})
        redis = AsyncMock()
        redis.delete = AsyncMock()
        with patch(
            "drevalis.api.routes.backup.repair_media_links",
            AsyncMock(return_value=report),
        ):
            await repair_media(db=AsyncMock(), settings=_settings(tmp_path), redis=redis)
        redis.delete.assert_awaited_once_with(STORAGE_PROBE_CACHE_KEY)

    async def test_redis_failure_on_bust_does_not_500(self, tmp_path: Path) -> None:
        # Pin: a Redis error during the best-effort cache bust must not
        # propagate to the caller. The repair itself succeeded; the operator
        # gets the correct report and the cache expires naturally at TTL.
        report = MagicMock()
        report.to_dict = MagicMock(return_value={"relinked": 1})
        redis = AsyncMock()
        redis.delete = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch(
            "drevalis.api.routes.backup.repair_media_links",
            AsyncMock(return_value=report),
        ):
            # Must not raise — Redis failure on bust path is swallowed.
            out = await repair_media(db=AsyncMock(), settings=_settings(tmp_path), redis=redis)
        assert out == {"relinked": 1}


# ── run_scheduled_backup (cron hook) ──────────────────────────────


class TestScheduledBackup:
    async def test_no_op_when_disabled(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_auto_enabled = False
        out = await run_scheduled_backup(db=AsyncMock(), settings=s)
        assert out is None

    async def test_runs_when_enabled(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        s.backup_auto_enabled = True
        s.backup_directory.mkdir(parents=True)
        archive = s.backup_directory / "auto.tar.gz"
        archive.write_bytes(b"fake")

        svc = MagicMock()
        svc.create_backup = AsyncMock(return_value=archive)
        svc.prune = MagicMock(return_value=0)
        with patch("drevalis.api.routes.backup._service", return_value=svc):
            out = await run_scheduled_backup(db=AsyncMock(), settings=s)
        assert out == archive
        svc.prune.assert_called_once_with(7)
