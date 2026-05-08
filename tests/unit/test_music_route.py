"""Tests for ``api/routes/music.py``.

Custom-music upload + sidecar metadata management. Pin:

* `_safe_filename` strips path components, rejects empty / dotfile
  names with 400, replaces bad chars, truncates to 160.
* Upload: missing filename → 400, bad extension → 415, oversize →
  413 with the partial file deleted (no orphan disk garbage).
* PUT writes a JSON sidecar; explicit `None` field clears that
  override (so callers can revert to series defaults); empty meta
  removes the sidecar entirely.
* List skips non-allowed extensions and non-files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from drevalis.api.routes.music import (
    CustomTrackUpdate,
    _safe_filename,
    delete_custom_track,
    list_custom_tracks,
    update_custom_track,
    upload_custom_track,
)


def _settings(tmp_path: Path) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    return s


def _upload(content: bytes, filename: str = "track.mp3") -> Any:
    f = MagicMock(spec=UploadFile)
    f.filename = filename
    chunks = [content[i : i + 64 * 1024] for i in range(0, len(content), 64 * 1024)] + [b""]

    async def _read(_size: int = 0) -> bytes:
        return chunks.pop(0) if chunks else b""

    f.read = AsyncMock(side_effect=_read)
    return f


# ── _safe_filename ─────────────────────────────────────────────────


class TestSafeFilename:
    def test_strips_path_components(self) -> None:
        assert _safe_filename("../../etc/track.mp3") == "track.mp3"

    def test_replaces_bad_characters(self) -> None:
        out = _safe_filename("Track Name (1).mp3")
        assert " " not in out
        assert "(" not in out
        assert out.endswith(".mp3")

    def test_truncates_to_160(self) -> None:
        long_name = "a" * 200 + ".mp3"
        assert len(_safe_filename(long_name)) <= 160

    def test_dotfile_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _safe_filename(".hidden")
        assert exc.value.status_code == 400

    def test_empty_after_strip_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _safe_filename("")
        assert exc.value.status_code == 400


# ── GET /custom ────────────────────────────────────────────────────


class TestListCustomTracks:
    async def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        out = await list_custom_tracks(settings=_settings(tmp_path))
        assert out == []

    async def test_skips_non_audio_files(self, tmp_path: Path) -> None:
        root = tmp_path / "music" / "custom"
        root.mkdir(parents=True)
        (root / "track.mp3").write_bytes(b"audio")
        (root / "notes.txt").write_text("not audio")
        # Sidecars look like .json — also must be skipped.
        (root / "track.mp3.json").write_text("{}")
        out = await list_custom_tracks(settings=_settings(tmp_path))
        assert [t.filename for t in out] == ["track.mp3"]

    async def test_loads_sidecar_metadata(self, tmp_path: Path) -> None:
        root = tmp_path / "music" / "custom"
        root.mkdir(parents=True)
        (root / "epic.wav").write_bytes(b"audio")
        (root / "epic.wav.json").write_text(
            json.dumps({"music_volume_db": -10.0, "fade_in_seconds": 0.5})
        )
        out = await list_custom_tracks(settings=_settings(tmp_path))
        assert len(out) == 1
        assert out[0].music_volume_db == -10.0
        assert out[0].fade_in_seconds == 0.5

    async def test_unreadable_sidecar_falls_back_to_no_meta(self, tmp_path: Path) -> None:
        root = tmp_path / "music" / "custom"
        root.mkdir(parents=True)
        (root / "epic.wav").write_bytes(b"audio")
        (root / "epic.wav.json").write_text("{ not json")
        out = await list_custom_tracks(settings=_settings(tmp_path))
        assert out[0].music_volume_db is None

    async def test_sidecar_with_non_dict_root_ignored(self, tmp_path: Path) -> None:
        # Defensive: a sidecar containing a JSON list (or other non-dict)
        # would crash a naive .get() — pin: helper falls back to {}.
        root = tmp_path / "music" / "custom"
        root.mkdir(parents=True)
        (root / "epic.wav").write_bytes(b"audio")
        (root / "epic.wav.json").write_text("[1, 2, 3]")
        out = await list_custom_tracks(settings=_settings(tmp_path))
        assert out[0].music_volume_db is None


# ── POST /custom ───────────────────────────────────────────────────


class TestUploadCustomTrack:
    async def test_missing_filename_400(self, tmp_path: Path) -> None:
        f = MagicMock(spec=UploadFile)
        f.filename = None
        with pytest.raises(HTTPException) as exc:
            await upload_custom_track(file=f, settings=_settings(tmp_path))
        assert exc.value.status_code == 400

    async def test_bad_extension_415(self, tmp_path: Path) -> None:
        with pytest.raises(HTTPException) as exc:
            await upload_custom_track(
                file=_upload(b"data", filename="track.exe"),
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 415
        assert exc.value.detail["error"] == "unsupported_audio_type"

    async def test_no_extension_415(self, tmp_path: Path) -> None:
        with pytest.raises(HTTPException) as exc:
            await upload_custom_track(
                file=_upload(b"data", filename="track"),
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 415
        assert exc.value.detail["received"] == "(none)"

    async def test_oversize_413_deletes_partial_file(self, tmp_path: Path) -> None:
        # Patch the cap to a tiny value so we can trigger oversize
        # cheaply — 100 bytes vs the real 25 MB.
        # Use object patching via context manager.
        from unittest.mock import patch as _patch  # noqa: PLC0415

        from drevalis.api.routes import music as mod

        big = b"x" * 200
        with _patch.object(mod, "_MAX_UPLOAD_BYTES", 100):
            with pytest.raises(HTTPException) as exc:
                await upload_custom_track(
                    file=_upload(big, filename="big.mp3"),
                    settings=_settings(tmp_path),
                )
        assert exc.value.status_code == 413
        # Pin: the partial write was deleted (no orphan).
        assert not (tmp_path / "music" / "custom" / "big.mp3").exists()

    async def test_success_writes_file_and_returns_meta(self, tmp_path: Path) -> None:
        out = await upload_custom_track(
            file=_upload(b"\x00\x01\x02data", filename="cool.mp3"),
            settings=_settings(tmp_path),
        )
        assert out.filename == "cool.mp3"
        assert out.size_bytes > 0
        assert out.music_volume_db is None
        # File on disk has the bytes.
        assert (tmp_path / "music" / "custom" / "cool.mp3").read_bytes() == b"\x00\x01\x02data"

    async def test_overwrite_silent_on_re_upload(self, tmp_path: Path) -> None:
        # First upload.
        await upload_custom_track(
            file=_upload(b"old", filename="track.mp3"),
            settings=_settings(tmp_path),
        )
        # Second upload of the same name → silent overwrite.
        await upload_custom_track(
            file=_upload(b"newer", filename="track.mp3"),
            settings=_settings(tmp_path),
        )
        assert (tmp_path / "music" / "custom" / "track.mp3").read_bytes() == b"newer"


# ── PUT /custom/{filename} ─────────────────────────────────────────


class TestUpdateCustomTrack:
    async def test_track_not_found_404(self, tmp_path: Path) -> None:
        with pytest.raises(HTTPException) as exc:
            await update_custom_track(
                filename="missing.mp3",
                body=CustomTrackUpdate(music_volume_db=-12.0),
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 404

    async def test_writes_sidecar_with_provided_fields(self, tmp_path: Path) -> None:
        root = tmp_path / "music" / "custom"
        root.mkdir(parents=True)
        (root / "epic.wav").write_bytes(b"audio")
        out = await update_custom_track(
            filename="epic.wav",
            body=CustomTrackUpdate(music_volume_db=-12.0, fade_in_seconds=1.0),
            settings=_settings(tmp_path),
        )
        assert out.music_volume_db == -12.0
        sidecar = (root / "epic.wav.json").read_text()
        data = json.loads(sidecar)
        assert data["music_volume_db"] == -12.0
        assert data["fade_in_seconds"] == 1.0

    async def test_explicit_none_clears_override(self, tmp_path: Path) -> None:
        # Pre-existing sidecar with an override; PUT sends
        # music_volume_db=None to clear it.
        root = tmp_path / "music" / "custom"
        root.mkdir(parents=True)
        (root / "epic.wav").write_bytes(b"audio")
        (root / "epic.wav.json").write_text(
            json.dumps({"music_volume_db": -10.0, "fade_in_seconds": 0.5})
        )
        out = await update_custom_track(
            filename="epic.wav",
            body=CustomTrackUpdate(music_volume_db=None),
            settings=_settings(tmp_path),
        )
        assert out.music_volume_db is None  # cleared
        # Other fields preserved.
        assert out.fade_in_seconds == 0.5

    async def test_empty_meta_removes_sidecar(self, tmp_path: Path) -> None:
        # All fields cleared → sidecar file is deleted (avoids stale
        # empty {} files cluttering the music dir).
        root = tmp_path / "music" / "custom"
        root.mkdir(parents=True)
        (root / "epic.wav").write_bytes(b"audio")
        (root / "epic.wav.json").write_text(json.dumps({"music_volume_db": -10.0}))
        await update_custom_track(
            filename="epic.wav",
            body=CustomTrackUpdate(music_volume_db=None),
            settings=_settings(tmp_path),
        )
        assert not (root / "epic.wav.json").exists()


# ── DELETE /custom/{filename} ──────────────────────────────────────


class TestDeleteCustomTrack:
    async def test_deletes_track_and_sidecar(self, tmp_path: Path) -> None:
        root = tmp_path / "music" / "custom"
        root.mkdir(parents=True)
        (root / "epic.wav").write_bytes(b"audio")
        (root / "epic.wav.json").write_text("{}")
        await delete_custom_track(filename="epic.wav", settings=_settings(tmp_path))
        assert not (root / "epic.wav").exists()
        assert not (root / "epic.wav.json").exists()

    async def test_missing_track_silent_204(self, tmp_path: Path) -> None:
        # No track on disk — DELETE is idempotent. Pin: returns None
        # (204) without raising.
        out = await delete_custom_track(filename="never.mp3", settings=_settings(tmp_path))
        assert out is None
