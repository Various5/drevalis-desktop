"""Tests for ``api/routes/assets.py``.

Multipart upload + library CRUD + ffprobe-based dimensions extraction.
Pin:

* `_kind_from_mime` maps `image/`, `video/`, `audio/`, falls back to
  `other` for unknown / missing types.
* `_safe_filename` strips path components and bad characters,
  truncates to 120 chars, falls back to `"asset"` when nothing usable
  remains (so we never write an empty filename).
* `_probe_media` returns `(None, None, None)` when ffprobe is missing
  or returns invalid JSON — caller still gets a usable tuple.
* Upload: empty body → 400, oversized → 413, **dedup by SHA-256
  short-circuits the file write** (no bytes touched on disk).
* Get / file / patch / delete map NotFoundError → 404.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse

from drevalis.api.routes.assets import (
    AssetUpdate,
    _kind_from_mime,
    _probe_media,
    _safe_filename,
    _service,
    delete_asset,
    get_asset,
    get_asset_file,
    list_assets,
    update_asset,
    upload_asset,
)
from drevalis.core.exceptions import NotFoundError
from drevalis.services.asset import AssetService


def _settings(tmp_path: Path) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    return s


def _make_asset(**overrides: Any) -> Any:
    a = MagicMock()
    a.id = overrides.get("id", uuid4())
    a.kind = overrides.get("kind", "image")
    a.filename = overrides.get("filename", "test.png")
    a.file_path = overrides.get("file_path", "assets/images/abc/test.png")
    a.file_size_bytes = overrides.get("file_size_bytes", 100)
    a.mime_type = overrides.get("mime_type", "image/png")
    a.hash_sha256 = overrides.get("hash_sha256", "0" * 64)
    a.width = overrides.get("width")
    a.height = overrides.get("height")
    a.duration_seconds = overrides.get("duration_seconds")
    a.tags = overrides.get("tags", [])
    a.description = overrides.get("description")
    a.created_at = overrides.get("created_at", datetime(2026, 1, 1, tzinfo=UTC))
    a.updated_at = overrides.get("updated_at", datetime(2026, 1, 1, tzinfo=UTC))
    return a


def _upload(content: bytes, mime: str = "image/png", filename: str = "x.png") -> Any:
    f = MagicMock(spec=UploadFile)
    f.content_type = mime
    f.filename = filename
    f.read = AsyncMock(return_value=content)
    return f


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service(self, tmp_path: Path) -> None:
        svc = _service(db=AsyncMock(), settings=_settings(tmp_path))
        assert isinstance(svc, AssetService)


# ── _kind_from_mime ────────────────────────────────────────────────


class TestKindFromMime:
    @pytest.mark.parametrize(
        ("mime", "kind"),
        [
            ("image/png", "image"),
            ("image/jpeg", "image"),
            ("video/mp4", "video"),
            ("audio/wav", "audio"),
            ("application/pdf", "other"),
            ("text/plain", "other"),
        ],
    )
    def test_known_prefixes(self, mime: str, kind: str) -> None:
        assert _kind_from_mime(mime) == kind

    def test_none_or_empty(self) -> None:
        assert _kind_from_mime(None) == "other"
        assert _kind_from_mime("") == "other"


# ── _safe_filename ─────────────────────────────────────────────────


class TestSafeFilename:
    def test_strips_path_components(self) -> None:
        # Client sent "../../etc/passwd" — must collapse to just "passwd"
        # so a filesystem-traversal write is impossible.
        assert _safe_filename("../../etc/passwd") == "passwd"

    def test_replaces_bad_characters(self) -> None:
        out = _safe_filename("My Cool File (1).mp4")
        # Spaces / parens replaced; dots and hyphens preserved.
        assert " " not in out
        assert "(" not in out
        assert out.endswith(".mp4")

    def test_truncates_to_120_chars(self) -> None:
        long_name = "a" * 200 + ".mp4"
        assert len(_safe_filename(long_name)) <= 120

    def test_falls_back_to_asset_when_empty(self) -> None:
        # All chars stripped → "asset" fallback so we never write an
        # empty filename to disk.
        assert _safe_filename("///") == "asset"
        assert _safe_filename("") == "asset"


# ── _probe_media ───────────────────────────────────────────────────


class TestProbeMedia:
    async def test_ffprobe_missing_returns_none_tuple(self, tmp_path: Path) -> None:
        # FileNotFoundError fires when the ffprobe binary isn't on PATH.
        with patch(
            "drevalis.api.routes.assets.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError),
        ):
            out = await _probe_media(tmp_path / "x.mp4")
        assert out == (None, None, None)

    async def test_non_zero_returncode_returns_none_tuple(self, tmp_path: Path) -> None:
        proc = MagicMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b""))
        with patch(
            "drevalis.api.routes.assets.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            out = await _probe_media(tmp_path / "x.mp4")
        assert out == (None, None, None)

    async def test_invalid_json_returns_none_tuple(self, tmp_path: Path) -> None:
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"not json", b""))
        with patch(
            "drevalis.api.routes.assets.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            out = await _probe_media(tmp_path / "x.mp4")
        assert out == (None, None, None)

    async def test_video_extracts_dimensions_and_duration(self, tmp_path: Path) -> None:
        payload = json.dumps(
            {
                "streams": [
                    {"codec_type": "video", "width": 1920, "height": 1080},
                ],
                "format": {"duration": "12.5"},
            }
        ).encode()
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(payload, b""))
        with patch(
            "drevalis.api.routes.assets.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            w, h, d = await _probe_media(tmp_path / "x.mp4")
        assert w == 1920
        assert h == 1080
        assert d == pytest.approx(12.5)

    async def test_invalid_duration_falls_back_to_none(self, tmp_path: Path) -> None:
        # Some ffprobe versions emit "N/A" for stream-only files —
        # float() raises and the helper must coerce to None instead of
        # crashing the upload.
        payload = json.dumps(
            {
                "streams": [{"codec_type": "video", "width": 100, "height": 100}],
                "format": {"duration": "N/A"},
            }
        ).encode()
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(payload, b""))
        with patch(
            "drevalis.api.routes.assets.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            _, _, d = await _probe_media(tmp_path / "x.mp4")
        assert d is None


# ── POST /assets ───────────────────────────────────────────────────


class TestUploadAsset:
    async def test_empty_file_400(self, tmp_path: Path) -> None:
        svc = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await upload_asset(
                file=_upload(b""),
                tags=None,
                description=None,
                svc=svc,
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 400

    async def test_oversize_413(self, tmp_path: Path) -> None:
        # Build a 2 GiB + 1 byte payload via patching the constant
        # rather than allocating it for real.
        from drevalis.api.routes import assets as mod

        small_max = 4
        with patch.object(mod, "_MAX_UPLOAD_BYTES", small_max):
            svc = MagicMock()
            with pytest.raises(HTTPException) as exc:
                await upload_asset(
                    file=_upload(b"\x00" * (small_max + 1)),
                    tags=None,
                    description=None,
                    svc=svc,
                    settings=_settings(tmp_path),
                )
        assert exc.value.status_code == 413

    async def test_dedup_short_circuits_file_write(self, tmp_path: Path) -> None:
        # Existing asset with the same hash is returned WITHOUT a new
        # file being written. Pin: nothing under storage/assets/ exists
        # after the call.
        existing = _make_asset()
        svc = MagicMock()
        svc.get_by_hash = AsyncMock(return_value=existing)
        out = await upload_asset(
            file=_upload(b"hello"),
            tags=None,
            description=None,
            svc=svc,
            settings=_settings(tmp_path),
        )
        assert out.id == existing.id
        assert not (tmp_path / "assets").exists()

    async def test_success_writes_file_and_creates_row(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_by_hash = AsyncMock(return_value=None)
        svc.create = AsyncMock(side_effect=lambda **kw: _make_asset(**kw))
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(
            return_value=(
                json.dumps(
                    {"streams": [{"codec_type": "image", "width": 64, "height": 32}]}
                ).encode(),
                b"",
            )
        )
        with patch(
            "drevalis.api.routes.assets.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            out = await upload_asset(
                file=_upload(b"\x89PNG\r\n\x1a\n", mime="image/png"),
                tags="hero, color: red, ",
                description="A test asset",
                svc=svc,
                settings=_settings(tmp_path),
            )
        # File landed under assets/images/<id>/.
        kwargs = svc.create.call_args.kwargs
        assert kwargs["kind"] == "image"
        assert kwargs["file_path"].startswith("assets/images/")
        assert kwargs["hash_sha256"] == hashlib.sha256(b"\x89PNG\r\n\x1a\n").hexdigest()
        # Tags: split on comma, stripped, empty entries dropped.
        assert kwargs["tags"] == ["hero", "color: red"]
        assert kwargs["width"] == 64
        # Disk now holds the bytes at the relative path the route
        # passed to the service.
        assert (tmp_path / kwargs["file_path"]).read_bytes() == b"\x89PNG\r\n\x1a\n"
        assert out.kind == "image"

    async def test_unknown_mime_lands_under_other(self, tmp_path: Path) -> None:
        svc = MagicMock()
        svc.get_by_hash = AsyncMock(return_value=None)
        svc.create = AsyncMock(side_effect=lambda **kw: _make_asset(**kw))
        with patch(
            "drevalis.api.routes.assets.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError),
        ):
            await upload_asset(
                file=_upload(b"hello", mime="application/x-binary", filename="x.bin"),
                tags=None,
                description=None,
                svc=svc,
                settings=_settings(tmp_path),
            )
        kwargs = svc.create.call_args.kwargs
        assert kwargs["kind"] == "other"
        # Path uses bare "other" segment, not "others".
        assert "/other/" in kwargs["file_path"]


# ── GET /assets ────────────────────────────────────────────────────


class TestListAssets:
    async def test_passes_filters(self) -> None:
        svc = MagicMock()
        svc.list_filtered = AsyncMock(return_value=[_make_asset()])
        out = await list_assets(
            kind="image",
            search="hero",
            tag="brand",
            offset=10,
            limit=50,
            svc=svc,
        )
        assert len(out) == 1
        svc.list_filtered.assert_awaited_once_with(
            kind="image", search="hero", tag="brand", offset=10, limit=50
        )


# ── GET /assets/{id} ──────────────────────────────────────────────


class TestGetAsset:
    async def test_success(self) -> None:
        svc = MagicMock()
        a = _make_asset()
        svc.get = AsyncMock(return_value=a)
        out = await get_asset(a.id, svc=svc)
        assert out.id == a.id

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("asset", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_asset(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── GET /assets/{id}/file ──────────────────────────────────────────


class TestGetAssetFile:
    async def test_returns_file_response(self, tmp_path: Path) -> None:
        a = _make_asset(mime_type="image/png")
        f = tmp_path / "x.png"
        f.write_bytes(b"\x89PNG")
        svc = MagicMock()
        svc.get = AsyncMock(return_value=a)
        svc.absolute_file_path = MagicMock(return_value=f)
        out = await get_asset_file(a.id, svc=svc)
        assert isinstance(out, FileResponse)

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("asset", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_asset_file(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_missing_on_disk_404(self, tmp_path: Path) -> None:
        a = _make_asset()
        svc = MagicMock()
        svc.get = AsyncMock(return_value=a)
        # Service points at a path that no longer exists on disk.
        svc.absolute_file_path = MagicMock(return_value=tmp_path / "gone.png")
        with pytest.raises(HTTPException) as exc:
            await get_asset_file(a.id, svc=svc)
        assert exc.value.status_code == 404
        assert "missing on disk" in exc.value.detail


# ── PATCH /assets/{id} ────────────────────────────────────────────


class TestUpdateAsset:
    async def test_strips_whitespace_and_caps_tags(self) -> None:
        svc = MagicMock()
        svc.update_metadata = AsyncMock(return_value=_make_asset())
        body = AssetUpdate(tags=["  a  ", "", "b", " c"], description="x")
        await update_asset(uuid4(), body, svc=svc)
        kwargs = svc.update_metadata.call_args.kwargs
        # Empty entries dropped + whitespace stripped.
        assert kwargs["tags"] == ["a", "b", "c"]
        assert kwargs["description"] == "x"

    async def test_omitted_fields_not_in_changes(self) -> None:
        svc = MagicMock()
        svc.update_metadata = AsyncMock(return_value=_make_asset())
        body = AssetUpdate()  # no fields set
        await update_asset(uuid4(), body, svc=svc)
        kwargs = svc.update_metadata.call_args.kwargs
        assert kwargs == {}

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update_metadata = AsyncMock(side_effect=NotFoundError("asset", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_asset(uuid4(), AssetUpdate(description="x"), svc=svc)
        assert exc.value.status_code == 404


# ── DELETE /assets/{id} ────────────────────────────────────────────


class TestDeleteAsset:
    async def test_delegates_to_service(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_asset(uuid4(), svc=svc)
        svc.delete.assert_awaited_once()
