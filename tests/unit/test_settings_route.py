"""Tests for ``api/routes/settings.py``.

Storage / health / ffmpeg-info surface. Pin:

* `_human_size` formats bytes through PB.
* `storage_usage`: skips noisy dirs (`models`, `temp`, `cache`,
  hidden), bails when budget exceeded (returns partial), aggregates
  per-subdir.
* `_check_*` helpers return structured ServiceHealth with the right
  status (`ok`/`degraded`/`unreachable`).
* `system_health` overall status: all-ok → ok; any-unreachable →
  unhealthy; otherwise degraded.
* `ffmpeg_info`: missing binary on PATH → `available=False` without
  attempting subprocess.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from drevalis.api.routes.settings import (
    _check_comfyui_servers,
    _check_database,
    _check_ffmpeg,
    _check_lm_studio,
    _check_piper_tts,
    _check_redis,
    _check_worker,
    _human_size,
    ffmpeg_info,
    storage_usage,
    system_health,
)


def _settings(tmp_path: Path) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    s.ffmpeg_path = "ffmpeg"
    s.piper_models_path = tmp_path / "models" / "piper"
    s.lm_studio_base_url = "http://localhost:1234/v1"
    s.comfyui_default_url = "http://localhost:8188"
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    return s


# ── _human_size ────────────────────────────────────────────────────


class TestHumanSize:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            (0, "0.0 B"),
            (1023, "1023.0 B"),
            (1024, "1.0 KB"),
            (1024 * 1024, "1.0 MB"),
            (1024**3, "1.0 GB"),
            (1024**4, "1.0 TB"),
            (1024**5, "1.0 PB"),
            (1024**6, "1024.0 PB"),  # falls past TB scale
        ],
    )
    def test_formats_bytes(self, size: int, expected: str) -> None:
        assert _human_size(size) == expected


# ── storage_usage ──────────────────────────────────────────────────


class TestStorageUsage:
    async def test_missing_base_returns_zero(self, tmp_path: Path) -> None:
        # Storage path doesn't exist — pin: returns zero, doesn't
        # crash on the os.walk.
        non_existent = tmp_path / "no-storage"
        s = MagicMock()
        s.storage_base_path = non_existent
        out = await storage_usage(settings=s)
        assert out.total_size_bytes == 0
        assert out.total_size_human == "0.0 B"

    async def test_aggregates_subdirs(self, tmp_path: Path) -> None:
        # Build a small tree the walker can sum.
        (tmp_path / "episodes" / "x").mkdir(parents=True)
        (tmp_path / "episodes" / "x" / "out.mp4").write_bytes(b"a" * 100)
        (tmp_path / "audiobooks").mkdir()
        (tmp_path / "audiobooks" / "ab.mp3").write_bytes(b"a" * 50)
        (tmp_path / "music").mkdir()
        (tmp_path / "music" / "track.mp3").write_bytes(b"a" * 25)
        # `models` is in the skip list — its bytes must NOT count.
        (tmp_path / "models").mkdir()
        (tmp_path / "models" / "huge.onnx").write_bytes(b"a" * 10000)

        out = await storage_usage(settings=_settings(tmp_path))

        assert out.total_size_bytes == 175  # 100 + 50 + 25, models excluded
        assert out.subdir_sizes["episodes"] == 100
        assert out.subdir_sizes["audiobooks"] == 50
        assert out.subdir_sizes["music"] == 25
        # The skip-list dir doesn't get a tally row at all.
        assert "models" not in out.subdir_sizes

    async def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        # Hidden dirs (.git, .cache) should NOT be walked. Pin: a 1 GB
        # file in .git wouldn't show up in any subdir total.
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "junk").write_bytes(b"a" * 5000)
        (tmp_path / "episodes").mkdir()
        (tmp_path / "episodes" / "ok.mp4").write_bytes(b"a" * 10)
        out = await storage_usage(settings=_settings(tmp_path))
        # Total reflects only the non-hidden tree.
        assert out.total_size_bytes == 10

    async def test_unreadable_file_skipped_not_crashed(self, tmp_path: Path) -> None:
        # If `os.path.getsize` raises, the walker continues — pin: the
        # rest of the tree is still summed.
        (tmp_path / "episodes").mkdir()
        good = tmp_path / "episodes" / "ok.mp4"
        good.write_bytes(b"a" * 10)
        bad = tmp_path / "episodes" / "broken.mp4"
        bad.write_bytes(b"x")

        real_getsize = __import__("os").path.getsize

        def _getsize(p: str) -> int:
            if p.endswith("broken.mp4"):
                raise OSError("permission denied")
            return real_getsize(p)

        with patch("os.path.getsize", side_effect=_getsize):
            out = await storage_usage(settings=_settings(tmp_path))
        # Good file's bytes still counted.
        assert out.total_size_bytes == 10


# ── storage_usage: /proc/self/mountinfo parsing ────────────────────


class TestStorageMountinfo:
    async def test_host_source_resolved_from_mountinfo(self, tmp_path: Path) -> None:
        # Build a fake /proc/self/mountinfo entry that maps host
        # /srv/data/storage → tmp_path inside the container. Pin: the
        # route's deepest-mount-wins logic surfaces /srv/data/storage.
        path_str = str(tmp_path.resolve())
        line = f"100 99 0:0 /srv/data/storage {path_str} rw,relatime shared:1 - ext4 /dev/x rw"
        line_root = "1 0 0:0 / / rw - tmpfs tmpfs rw"
        fake_content = f"{line_root}\n{line}\n"

        original_read_text = Path.read_text

        def _fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            # Match by basename so the test works on Windows where
            # str(Path("/proc/self/mountinfo")) returns "\\proc\\self\\...".
            if self.name == "mountinfo" and "proc" in self.as_posix():
                return fake_content
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", _fake_read_text):
            out = await storage_usage(settings=_settings(tmp_path))

        assert out.host_source_path == "/srv/data/storage"
        # mountinfo_lines includes only the entries that cover our path
        # (root + the storage mount).
        assert any("/srv/data/storage" in ln for ln in out.mountinfo_lines)

    async def test_unreadable_mountinfo_falls_back_to_none(self, tmp_path: Path) -> None:
        # /proc/self/mountinfo missing (Windows host) — pin: the route
        # returns None for host_source_path without crashing.
        original_read_text = Path.read_text

        def _fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name == "mountinfo" and "proc" in self.as_posix():
                raise OSError("no such file")
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", _fake_read_text):
            out = await storage_usage(settings=_settings(tmp_path))
        assert out.host_source_path is None
        assert out.mountinfo_lines == []


# ── _check_comfyui_servers ─────────────────────────────────────────


class TestCheckComfyuiServers:
    async def test_falls_back_to_default_url_when_no_db_servers(self) -> None:
        import httpx

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"system": {}})

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        # ComfyUIServerService.list_all returns nothing → fallback path.
        admin_svc = MagicMock()
        admin_svc.list_all = AsyncMock(return_value=[])
        with (
            patch(
                "drevalis.services.comfyui_admin.ComfyUIServerService",
                return_value=admin_svc,
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await _check_comfyui_servers(AsyncMock(), "http://localhost:8188", "key")
        assert len(out) == 1
        assert out[0].name == "comfyui"
        assert out[0].status == "ok"

    async def test_default_url_unreachable_marked(self) -> None:
        import httpx

        def _h(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns")

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        admin_svc = MagicMock()
        admin_svc.list_all = AsyncMock(return_value=[])
        with (
            patch(
                "drevalis.services.comfyui_admin.ComfyUIServerService",
                return_value=admin_svc,
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await _check_comfyui_servers(AsyncMock(), "http://localhost:8188", "key")
        assert out[0].status == "unreachable"

    async def test_default_url_non_200_marked_degraded(self) -> None:
        import httpx

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        admin_svc = MagicMock()
        admin_svc.list_all = AsyncMock(return_value=[])
        with (
            patch(
                "drevalis.services.comfyui_admin.ComfyUIServerService",
                return_value=admin_svc,
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await _check_comfyui_servers(AsyncMock(), "http://localhost:8188", "key")
        assert out[0].status == "degraded"

    async def test_active_servers_each_checked(self) -> None:
        import httpx

        def _h(request: httpx.Request) -> httpx.Response:
            # Server 1 ok, server 2 returns 500.
            if "8188" in str(request.url):
                return httpx.Response(200, json={})
            return httpx.Response(500)

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        s1 = MagicMock()
        s1.is_active = True
        s1.name = "primary"
        s1.url = "http://localhost:8188"
        s2 = MagicMock()
        s2.is_active = True
        s2.name = "backup"
        s2.url = "http://localhost:8189"
        admin_svc = MagicMock()
        admin_svc.list_all = AsyncMock(return_value=[s1, s2])
        with (
            patch(
                "drevalis.services.comfyui_admin.ComfyUIServerService",
                return_value=admin_svc,
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await _check_comfyui_servers(AsyncMock(), "http://default:8188", "key")
        # Both servers were tested.
        names = {h.name for h in out}
        assert names == {"comfyui:primary", "comfyui:backup"}
        # Status reflects per-server results.
        primary = next(h for h in out if h.name == "comfyui:primary")
        backup = next(h for h in out if h.name == "comfyui:backup")
        assert primary.status == "ok"
        assert backup.status == "degraded"

    async def test_active_server_connection_error_unreachable(self) -> None:
        import httpx

        def _h(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns")

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        s1 = MagicMock()
        s1.is_active = True
        s1.name = "primary"
        s1.url = "http://localhost:8188"
        admin_svc = MagicMock()
        admin_svc.list_all = AsyncMock(return_value=[s1])
        with (
            patch(
                "drevalis.services.comfyui_admin.ComfyUIServerService",
                return_value=admin_svc,
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await _check_comfyui_servers(AsyncMock(), "http://default:8188", "key")
        assert out[0].status == "unreachable"

    async def test_db_lookup_failure_falls_back_to_default_url(self) -> None:
        # If the DB lookup itself raises, the route still produces a
        # health entry by hitting the default URL.
        import httpx

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with (
            patch(
                "drevalis.services.comfyui_admin.ComfyUIServerService",
                side_effect=RuntimeError("db down"),
            ),
            patch("httpx.AsyncClient", side_effect=_patched),
        ):
            out = await _check_comfyui_servers(AsyncMock(), "http://localhost:8188", "key")
        assert len(out) == 1
        assert out[0].status == "ok"


# ── _check_database ────────────────────────────────────────────────


class TestCheckDatabase:
    async def test_ok_when_query_succeeds(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock()
        out = await _check_database(db)
        assert out.status == "ok"

    async def test_unreachable_when_execute_raises(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=ConnectionError("postgres down"))
        out = await _check_database(db)
        assert out.status == "unreachable"
        assert "postgres down" in out.message


# ── _check_redis ───────────────────────────────────────────────────


class TestCheckRedis:
    async def test_ok_when_ping_truthy(self) -> None:
        redis = AsyncMock()
        redis.ping = AsyncMock(return_value=True)
        out = await _check_redis(redis)
        assert out.status == "ok"

    async def test_degraded_when_ping_falsy(self) -> None:
        redis = AsyncMock()
        redis.ping = AsyncMock(return_value=False)
        out = await _check_redis(redis)
        assert out.status == "degraded"

    async def test_unreachable_on_exception(self) -> None:
        redis = AsyncMock()
        redis.ping = AsyncMock(side_effect=ConnectionError("redis down"))
        out = await _check_redis(redis)
        assert out.status == "unreachable"


# ── _check_worker ──────────────────────────────────────────────────


class TestCheckWorker:
    async def test_redis_get_failure_degraded(self) -> None:
        # Pin: when Redis itself is broken, worker shows DEGRADED so the
        # operator sees one root-cause (Redis) instead of two errors.
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("dns"))
        out = await _check_worker(redis)
        assert out.status == "degraded"

    async def test_no_heartbeat_unreachable(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        out = await _check_worker(redis)
        assert out.status == "unreachable"
        assert "not started" in out.message

    async def test_malformed_heartbeat_degraded(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"not-an-iso-timestamp")
        out = await _check_worker(redis)
        assert out.status == "degraded"
        assert "malformed" in out.message

    async def test_recent_heartbeat_ok(self) -> None:
        recent = (datetime.now(tz=UTC) - timedelta(seconds=10)).isoformat()
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=recent.encode())
        out = await _check_worker(redis)
        assert out.status == "ok"
        assert "alive" in out.message

    async def test_stale_heartbeat_unreachable(self) -> None:
        # 200s old — past the 120s threshold → unreachable.
        stale = (datetime.now(tz=UTC) - timedelta(seconds=200)).isoformat()
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=stale.encode())
        out = await _check_worker(redis)
        assert out.status == "unreachable"
        assert "stale" in out.message

    async def test_naive_heartbeat_handled(self) -> None:
        # ISO timestamp without tzinfo — pin: route falls back to
        # naive `datetime.now()` rather than crashing on subtract.
        naive = datetime.now().isoformat()
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=naive.encode())
        out = await _check_worker(redis)
        assert out.status == "ok"

    async def test_heartbeat_string_value_handled(self) -> None:
        recent = (datetime.now(tz=UTC) - timedelta(seconds=5)).isoformat()
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=recent)  # str, not bytes
        out = await _check_worker(redis)
        assert out.status == "ok"


# ── _check_ffmpeg ──────────────────────────────────────────────────


class TestCheckFfmpeg:
    async def test_ok_when_returncode_zero(self) -> None:
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ffmpeg version 6.0\nbuilt with...", b""))
        with patch(
            "drevalis.api.routes.settings.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            out = await _check_ffmpeg("ffmpeg")
        assert out.status == "ok"
        assert "6.0" in out.message

    async def test_degraded_on_non_zero(self) -> None:
        proc = MagicMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b""))
        with patch(
            "drevalis.api.routes.settings.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            out = await _check_ffmpeg("ffmpeg")
        assert out.status == "degraded"

    async def test_unreachable_on_exception(self) -> None:
        with patch(
            "drevalis.api.routes.settings.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError("ffmpeg")),
        ):
            out = await _check_ffmpeg("ffmpeg")
        assert out.status == "unreachable"


# ── _check_piper_tts ───────────────────────────────────────────────


class TestCheckPiperTTS:
    async def test_unreachable_when_dir_missing(self, tmp_path: Path) -> None:
        out = await _check_piper_tts(tmp_path / "no-such-dir")
        assert out.status == "unreachable"

    async def test_degraded_when_path_is_file(self, tmp_path: Path) -> None:
        f = tmp_path / "models"
        f.write_bytes(b"x")
        out = await _check_piper_tts(f)
        assert out.status == "degraded"

    async def test_degraded_when_no_onnx_files(self, tmp_path: Path) -> None:
        out = await _check_piper_tts(tmp_path)
        assert out.status == "degraded"
        assert ".onnx" in out.message

    async def test_ok_when_models_present(self, tmp_path: Path) -> None:
        (tmp_path / "voice.onnx").write_bytes(b"x")
        (tmp_path / "voice2.onnx").write_bytes(b"y")
        out = await _check_piper_tts(tmp_path)
        assert out.status == "ok"
        assert "2 model" in out.message

    async def test_unreachable_on_exception(self) -> None:
        # Force `models_path.exists()` to raise — must surface as
        # unreachable rather than 500.
        bad_path = MagicMock()
        bad_path.exists = MagicMock(side_effect=OSError("permission denied"))
        out = await _check_piper_tts(bad_path)
        assert out.status == "unreachable"


# ── _check_lm_studio ───────────────────────────────────────────────


class TestCheckLMStudio:
    async def test_ok_when_200_with_model_count(self) -> None:
        import httpx

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "qwen"}, {"id": "llama"}]})

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await _check_lm_studio("http://localhost:1234/v1")
        assert out.status == "ok"
        assert "2 model" in out.message

    async def test_degraded_on_non_200(self) -> None:
        import httpx

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await _check_lm_studio("http://localhost:1234/v1")
        assert out.status == "degraded"

    async def test_unreachable_on_connect_error(self) -> None:
        import httpx

        def _h(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns")

        real = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await _check_lm_studio("http://localhost:1234/v1")
        assert out.status == "unreachable"


# ── system_health (composite) ──────────────────────────────────────


class TestSystemHealth:
    async def test_overall_ok_when_all_ok(self, tmp_path: Path) -> None:
        # All checks return ok → overall=ok.
        from drevalis.schemas.settings import ServiceHealth

        ok = ServiceHealth(name="x", status="ok")
        with (
            patch(
                "drevalis.api.routes.settings._check_database",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_redis",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_worker",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_comfyui_servers",
                AsyncMock(return_value=[ok]),
            ),
            patch(
                "drevalis.api.routes.settings._check_ffmpeg",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_piper_tts",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_lm_studio",
                AsyncMock(return_value=ok),
            ),
        ):
            out = await system_health(
                db=AsyncMock(), redis=AsyncMock(), settings=_settings(tmp_path)
            )
        assert out.overall == "ok"

    async def test_overall_unhealthy_when_any_unreachable(self, tmp_path: Path) -> None:
        from drevalis.schemas.settings import ServiceHealth

        ok = ServiceHealth(name="x", status="ok")
        unreachable = ServiceHealth(name="x", status="unreachable")
        with (
            patch(
                "drevalis.api.routes.settings._check_database",
                AsyncMock(return_value=unreachable),
            ),
            patch(
                "drevalis.api.routes.settings._check_redis",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_worker",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_comfyui_servers",
                AsyncMock(return_value=[ok]),
            ),
            patch(
                "drevalis.api.routes.settings._check_ffmpeg",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_piper_tts",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_lm_studio",
                AsyncMock(return_value=ok),
            ),
        ):
            out = await system_health(
                db=AsyncMock(), redis=AsyncMock(), settings=_settings(tmp_path)
            )
        assert out.overall == "unhealthy"

    async def test_overall_degraded_when_only_degraded(self, tmp_path: Path) -> None:
        from drevalis.schemas.settings import ServiceHealth

        ok = ServiceHealth(name="x", status="ok")
        degraded = ServiceHealth(name="x", status="degraded")
        with (
            patch(
                "drevalis.api.routes.settings._check_database",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_redis",
                AsyncMock(return_value=degraded),
            ),
            patch(
                "drevalis.api.routes.settings._check_worker",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_comfyui_servers",
                AsyncMock(return_value=[ok]),
            ),
            patch(
                "drevalis.api.routes.settings._check_ffmpeg",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_piper_tts",
                AsyncMock(return_value=ok),
            ),
            patch(
                "drevalis.api.routes.settings._check_lm_studio",
                AsyncMock(return_value=ok),
            ),
        ):
            out = await system_health(
                db=AsyncMock(), redis=AsyncMock(), settings=_settings(tmp_path)
            )
        assert out.overall == "degraded"


# ── ffmpeg_info ────────────────────────────────────────────────────


class TestFfmpegInfo:
    async def test_not_on_path_returns_unavailable(self, tmp_path: Path) -> None:
        with patch("shutil.which", return_value=None):
            out = await ffmpeg_info(settings=_settings(tmp_path))
        assert out.available is False
        assert "not found" in out.message

    async def test_success_returns_version(self, tmp_path: Path) -> None:
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ffmpeg version 6.1.1\nbuilt", b""))
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "drevalis.api.routes.settings.asyncio.create_subprocess_exec",
                AsyncMock(return_value=proc),
            ),
        ):
            out = await ffmpeg_info(settings=_settings(tmp_path))
        assert out.available is True
        assert "6.1.1" in (out.version or "")

    async def test_non_zero_returncode_unavailable(self, tmp_path: Path) -> None:
        proc = MagicMock()
        proc.returncode = 2
        proc.communicate = AsyncMock(return_value=(b"", b""))
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "drevalis.api.routes.settings.asyncio.create_subprocess_exec",
                AsyncMock(return_value=proc),
            ),
        ):
            out = await ffmpeg_info(settings=_settings(tmp_path))
        assert out.available is False
        assert "exit" in out.message.lower()

    async def test_subprocess_exception_unavailable(self, tmp_path: Path) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "drevalis.api.routes.settings.asyncio.create_subprocess_exec",
                AsyncMock(side_effect=OSError("boom")),
            ),
        ):
            out = await ffmpeg_info(settings=_settings(tmp_path))
        assert out.available is False
        assert "Error checking" in out.message


# Silence unused-import noise.
_ = asyncio
