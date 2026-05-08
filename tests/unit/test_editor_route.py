"""Tests for ``api/routes/editor.py``.

Thin router over ``EditorService``. Pin the layering contract:
``NotFoundError`` → 404 across get/save/render/captions/preview;
``ValidationError`` → 400 on waveform; ``WaveformRenderError`` → 500;
the ``video_edit_sessions does not exist`` migration-missing branch
surfaces a structured 500 hint pointing at alembic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from drevalis.api.routes.editor import (
    CaptionWord,
    CaptionWordsPayload,
    TimelineUpdate,
    _service,
    enqueue_preview,
    get_captions,
    get_editor_session,
    get_waveform,
    put_captions,
    render_editor_session,
    save_editor_session,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.services.editor import EditorService, WaveformRenderError


def _make_session(**overrides: Any) -> Any:
    s = MagicMock()
    s.id = overrides.get("id", uuid4())
    s.episode_id = overrides.get("episode_id", uuid4())
    s.version = overrides.get("version", 1)
    s.timeline = overrides.get("timeline", {"tracks": []})
    s.last_render_job_id = overrides.get("last_render_job_id")
    s.last_rendered_at = overrides.get("last_rendered_at")
    return s


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service_bound_to_session_path_and_ffmpeg(self) -> None:
        db = AsyncMock()
        settings = MagicMock()
        settings.storage_base_path = MagicMock()
        settings.ffmpeg_path = "ffmpeg"
        svc = _service(db=db, settings=settings)
        assert isinstance(svc, EditorService)


# ── GET /editor ─────────────────────────────────────────────────────


class TestGetEditorSession:
    async def test_returns_session_with_final_path(self) -> None:
        svc = MagicMock()
        s = _make_session()
        svc.get_or_create = AsyncMock(return_value=(s, "/storage/episodes/x.mp4"))
        out = await get_editor_session(s.episode_id, svc=svc)
        assert out.episode_id == s.episode_id
        assert out.final_video_path == "/storage/episodes/x.mp4"

    async def test_episode_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get_or_create = AsyncMock(side_effect=NotFoundError("episode", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_editor_session(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_missing_table_surfaces_migration_hint(self) -> None:
        # SQLAlchemy raises with the message ``relation "video_edit_sessions"
        # does not exist`` when migration 026 is missing. The router has a
        # specific branch that converts that to a structured 500 with an
        # alembic hint — pin it so a future generic-exception cleanup
        # doesn't drop the breadcrumb.
        svc = MagicMock()
        svc.get_or_create = AsyncMock(
            side_effect=RuntimeError('relation "video_edit_sessions" does not exist')
        )
        with pytest.raises(HTTPException) as exc:
            await get_editor_session(uuid4(), svc=svc)
        assert exc.value.status_code == 500
        detail = exc.value.detail
        assert isinstance(detail, dict)
        assert detail["error"] == "migration_missing"
        assert detail["missing_table"] == "video_edit_sessions"

    async def test_other_unexpected_error_surfaces_generic_500(self) -> None:
        svc = MagicMock()
        svc.get_or_create = AsyncMock(side_effect=RuntimeError("kaboom"))
        with pytest.raises(HTTPException) as exc:
            await get_editor_session(uuid4(), svc=svc)
        assert exc.value.status_code == 500
        detail = exc.value.detail
        assert isinstance(detail, dict)
        assert detail["error"] == "session_lookup_failed"
        assert "RuntimeError" in detail["reason"]


# ── PUT /editor ─────────────────────────────────────────────────────


class TestSaveEditorSession:
    async def test_overwrites_timeline(self) -> None:
        svc = MagicMock()
        s = _make_session(version=2)
        svc.save = AsyncMock(return_value=(s, None))
        body = TimelineUpdate(timeline={"tracks": [{"id": "v"}]})
        out = await save_editor_session(s.episode_id, body, svc=svc)
        assert out.version == 2
        svc.save.assert_awaited_once_with(s.episode_id, body.timeline)


# ── POST /editor/render + /preview ──────────────────────────────────


class TestRender:
    async def test_render_success(self) -> None:
        svc = MagicMock()
        svc.enqueue_render = AsyncMock()
        out = await render_editor_session(uuid4(), svc=svc)
        assert out == {"status": "enqueued"}

    async def test_render_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.enqueue_render = AsyncMock(side_effect=NotFoundError("edit_session", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await render_editor_session(uuid4(), svc=svc)
        assert exc.value.status_code == 404


class TestPreview:
    async def test_preview_success(self) -> None:
        svc = MagicMock()
        svc.enqueue_preview = AsyncMock()
        out = await enqueue_preview(uuid4(), svc=svc)
        assert out == {"status": "enqueued"}

    async def test_preview_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.enqueue_preview = AsyncMock(side_effect=NotFoundError("edit_session", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await enqueue_preview(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── GET / PUT /editor/captions ──────────────────────────────────────


class TestCaptions:
    async def test_get_returns_payload(self) -> None:
        svc = MagicMock()
        svc.get_captions = AsyncMock(
            return_value=[{"word": "hi", "start_seconds": 0.0, "end_seconds": 0.4}]
        )
        out = await get_captions(uuid4(), svc=svc)
        assert len(out.words) == 1
        assert out.words[0].word == "hi"

    async def test_get_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get_captions = AsyncMock(side_effect=NotFoundError("episode", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_captions(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_put_returns_payload(self) -> None:
        svc = MagicMock()
        svc.put_captions = AsyncMock()
        body = CaptionWordsPayload(
            words=[CaptionWord(word="x", start_seconds=0.0, end_seconds=0.2)]
        )
        out = await put_captions(uuid4(), body, svc=svc)
        assert out is body
        svc.put_captions.assert_awaited_once()

    async def test_put_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.put_captions = AsyncMock(side_effect=NotFoundError("episode", uuid4()))
        body = CaptionWordsPayload(words=[])
        with pytest.raises(HTTPException) as exc:
            await put_captions(uuid4(), body, svc=svc)
        assert exc.value.status_code == 404


# ── GET /editor/waveform ────────────────────────────────────────────


class TestGetWaveform:
    async def test_returns_file_response(self, tmp_path: Any) -> None:
        png = tmp_path / "wave.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        svc = MagicMock()
        svc.render_waveform = AsyncMock(return_value=png)
        out = await get_waveform(uuid4(), track="voice", svc=svc)
        assert isinstance(out, FileResponse)

    async def test_validation_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.render_waveform = AsyncMock(side_effect=ValidationError("unknown track"))
        with pytest.raises(HTTPException) as exc:
            await get_waveform(uuid4(), track="bogus", svc=svc)
        assert exc.value.status_code == 400

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.render_waveform = AsyncMock(side_effect=NotFoundError("audio_asset", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_waveform(uuid4(), track="music", svc=svc)
        assert exc.value.status_code == 404

    async def test_render_error_maps_to_500(self) -> None:
        svc = MagicMock()
        svc.render_waveform = AsyncMock(side_effect=WaveformRenderError("ffmpeg crashed"))
        with pytest.raises(HTTPException) as exc:
            await get_waveform(uuid4(), track="voice", svc=svc)
        assert exc.value.status_code == 500
