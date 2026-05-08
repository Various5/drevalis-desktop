"""Unit tests for ``drevalis.services.diagnostics``.

Pin:

* ``redact_settings`` drops encryption_key, *_KEY, *_SECRET, *_TOKEN,
  *_PASSWORD fields and replaces their values with ``***REDACTED***``.
* ``database_url`` is replaced with the user:password scrubbed form, NOT
  ``***REDACTED***``, so support can still see the host/port/db.
* The in-memory ZIP built by ``build_bundle`` contains every expected
  entry (MANIFEST.txt, version.json, config.json, health.json,
  recent_logs.txt, system.json, db_revision.txt).
* ``redact_settings`` is pure / synchronous — can be tested without an
  event loop.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from drevalis.services.diagnostics import (
    _REDACTED_MARKER,
    build_bundle,
    redact_settings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FERNET_KEY = base64.urlsafe_b64encode(b"\x00" * 32).decode()


def _make_settings(**overrides: object) -> Any:
    """Return a minimal MagicMock that looks enough like ``Settings``."""
    s = MagicMock()
    s.encryption_key = _FERNET_KEY
    s.database_url = "postgresql+asyncpg://drevalis:s3cr3t@localhost:5432/drevalis"
    s.anthropic_api_key = "sk-ant-123"
    s.youtube_client_secret = "yt-secret"
    s.api_auth_token = "tok-abcdef"
    s.runpod_api_key = "rpk-xyz"
    s.tiktok_client_secret = "tiktok-secret"
    s.redis_url = "redis://localhost:6379/0"
    s.debug = False
    s.storage_base_path = Path("./storage")
    s.ffmpeg_path = "ffmpeg"
    s.piper_models_path = Path("./storage/models/piper")
    s.log_file = None  # no log file by default

    # model_dump returns a representative flat dict
    s.model_dump.return_value = {
        "encryption_key": s.encryption_key,
        "database_url": s.database_url,
        "anthropic_api_key": s.anthropic_api_key,
        "youtube_client_secret": s.youtube_client_secret,
        "api_auth_token": s.api_auth_token,
        "runpod_api_key": s.runpod_api_key,
        "tiktok_client_secret": s.tiktok_client_secret,
        "redis_url": s.redis_url,
        "debug": s.debug,
        "storage_base_path": s.storage_base_path,
    }
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# redact_settings — synchronous, no I/O
# ---------------------------------------------------------------------------


class TestRedactSettings:
    def test_encryption_key_is_redacted(self) -> None:
        s = _make_settings()
        result = redact_settings(s)
        assert result["encryption_key"] == _REDACTED_MARKER

    def test_secret_suffix_is_redacted(self) -> None:
        s = _make_settings()
        result = redact_settings(s)
        assert result["youtube_client_secret"] == _REDACTED_MARKER
        assert result["tiktok_client_secret"] == _REDACTED_MARKER

    def test_token_suffix_is_redacted(self) -> None:
        s = _make_settings()
        result = redact_settings(s)
        assert result["api_auth_token"] == _REDACTED_MARKER

    def test_key_suffix_is_redacted(self) -> None:
        s = _make_settings()
        result = redact_settings(s)
        assert result["runpod_api_key"] == _REDACTED_MARKER
        # anthropic_api_key ends in "_key"
        assert result["anthropic_api_key"] == _REDACTED_MARKER

    def test_database_url_host_preserved(self) -> None:
        """database_url is partially redacted, not fully wiped.

        Support needs to see the host so they can rule out connection /
        network errors. The password must never appear.
        """
        s = _make_settings()
        result = redact_settings(s)
        db_val = str(result["database_url"])
        assert "s3cr3t" not in db_val, "password leaked in database_url"
        assert "localhost" in db_val, "host must be preserved"
        assert "5432" in db_val, "port must be preserved"
        assert "drevalis" in db_val, "database name must be preserved"

    def test_safe_fields_are_preserved(self) -> None:
        s = _make_settings()
        result = redact_settings(s)
        assert result["debug"] is False
        assert result["redis_url"] == "redis://localhost:6379/0"

    def test_returns_dict_str_object(self) -> None:
        s = _make_settings()
        result = redact_settings(s)
        assert isinstance(result, dict)
        for k in result:
            assert isinstance(k, str)


# ---------------------------------------------------------------------------
# build_bundle — async, needs mocked DB + helpers
# ---------------------------------------------------------------------------


class TestBuildBundle:
    """Pin that the ZIP returned by ``build_bundle`` contains all required
    entries and that the config.json within it has secrets redacted."""

    _EXPECTED_ENTRIES: frozenset[str] = frozenset(
        {
            "MANIFEST.txt",
            "version.json",
            "config.json",
            "health.json",
            "recent_logs.txt",
            "system.json",
            "db_revision.txt",
        }
    )

    def _make_db(self) -> AsyncMock:
        """Return an async DB mock that yields a fake alembic_version row."""
        db = AsyncMock()
        row = MagicMock()
        row.__getitem__ = MagicMock(return_value="abc123def456")
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [row]
        db.execute.return_value = result_mock
        return db

    async def test_zip_contains_all_entries(self, tmp_path: Path) -> None:
        s = _make_settings(storage_base_path=tmp_path)
        db = self._make_db()

        _ok_db = MagicMock(
            status="ok", model_dump=lambda: {"name": "database", "status": "ok", "message": ""}
        )
        _ok_ff = MagicMock(
            status="ok", model_dump=lambda: {"name": "ffmpeg", "status": "ok", "message": ""}
        )
        _ok_pi = MagicMock(
            status="ok", model_dump=lambda: {"name": "piper_tts", "status": "ok", "message": ""}
        )

        with (
            patch(
                "drevalis.api.routes.settings._check_database",
                new_callable=AsyncMock,
                return_value=_ok_db,
            ),
            patch(
                "drevalis.api.routes.settings._check_ffmpeg",
                new_callable=AsyncMock,
                return_value=_ok_ff,
            ),
            patch(
                "drevalis.api.routes.settings._check_piper_tts",
                new_callable=AsyncMock,
                return_value=_ok_pi,
            ),
        ):
            zip_bytes, size = await build_bundle(settings=s, db=db)

        assert size == len(zip_bytes)
        assert size > 0

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())

        assert names == self._EXPECTED_ENTRIES

    async def test_config_json_redacts_secrets(self, tmp_path: Path) -> None:
        s = _make_settings(storage_base_path=tmp_path)
        db = self._make_db()

        _ok_db = MagicMock(
            status="ok", model_dump=lambda: {"name": "database", "status": "ok", "message": ""}
        )
        _ok_ff = MagicMock(
            status="ok", model_dump=lambda: {"name": "ffmpeg", "status": "ok", "message": ""}
        )
        _ok_pi = MagicMock(
            status="ok", model_dump=lambda: {"name": "piper_tts", "status": "ok", "message": ""}
        )

        with (
            patch(
                "drevalis.api.routes.settings._check_database",
                new_callable=AsyncMock,
                return_value=_ok_db,
            ),
            patch(
                "drevalis.api.routes.settings._check_ffmpeg",
                new_callable=AsyncMock,
                return_value=_ok_ff,
            ),
            patch(
                "drevalis.api.routes.settings._check_piper_tts",
                new_callable=AsyncMock,
                return_value=_ok_pi,
            ),
        ):
            zip_bytes, _ = await build_bundle(settings=s, db=db)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            config = json.loads(zf.read("config.json").decode())

        # Secrets must be redacted
        assert config["encryption_key"] == _REDACTED_MARKER
        assert config["api_auth_token"] == _REDACTED_MARKER
        assert config["runpod_api_key"] == _REDACTED_MARKER

        # Database URL must be scrubbed but host preserved
        db_val = str(config["database_url"])
        assert "s3cr3t" not in db_val
        assert "localhost" in db_val

    async def test_manifest_contains_version_and_sha(self, tmp_path: Path) -> None:
        s = _make_settings(storage_base_path=tmp_path)
        db = self._make_db()

        _ok_db = MagicMock(
            status="ok", model_dump=lambda: {"name": "database", "status": "ok", "message": ""}
        )
        _ok_ff = MagicMock(
            status="ok", model_dump=lambda: {"name": "ffmpeg", "status": "ok", "message": ""}
        )
        _ok_pi = MagicMock(
            status="ok", model_dump=lambda: {"name": "piper_tts", "status": "ok", "message": ""}
        )

        with (
            patch(
                "drevalis.services.diagnostics._resolve_version", return_value=("9.9.9", "deadbeef")
            ),
            patch(
                "drevalis.api.routes.settings._check_database",
                new_callable=AsyncMock,
                return_value=_ok_db,
            ),
            patch(
                "drevalis.api.routes.settings._check_ffmpeg",
                new_callable=AsyncMock,
                return_value=_ok_ff,
            ),
            patch(
                "drevalis.api.routes.settings._check_piper_tts",
                new_callable=AsyncMock,
                return_value=_ok_pi,
            ),
        ):
            zip_bytes, _ = await build_bundle(settings=s, db=db)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            manifest = zf.read("MANIFEST.txt").decode()
            version_json = json.loads(zf.read("version.json").decode())

        assert "9.9.9" in manifest
        assert "deadbeef" in manifest
        assert version_json["version"] == "9.9.9"
        assert version_json["git_sha"] == "deadbeef"
