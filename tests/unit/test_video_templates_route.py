"""Tests for ``api/routes/video_templates.py``.

Thin router over ``VideoTemplateService``. Pin layered status mapping
+ the apply / from-series convenience endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.video_templates import (
    _service,
    apply_template_to_series,
    create_template_from_series,
    create_video_template,
    delete_video_template,
    get_video_template,
    list_video_templates,
    update_video_template,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.video_template import (
    VideoTemplateCreate,
    VideoTemplateUpdate,
)
from drevalis.services.video_template import VideoTemplateService


def _make_template(**overrides: Any) -> Any:
    t = MagicMock()
    t.id = overrides.get("id", uuid4())
    t.name = overrides.get("name", "Cinematic")
    t.description = overrides.get("description")
    t.voice_profile_id = overrides.get("voice_profile_id")
    t.visual_style = overrides.get("visual_style")
    t.scene_mode = overrides.get("scene_mode")
    t.caption_style_preset = overrides.get("caption_style_preset")
    t.music_enabled = overrides.get("music_enabled", True)
    t.music_mood = overrides.get("music_mood")
    t.music_volume_db = overrides.get("music_volume_db", -14.0)
    t.audio_settings = overrides.get("audio_settings")
    t.target_duration_seconds = overrides.get("target_duration_seconds", 30)
    t.times_used = overrides.get("times_used", 0)
    t.is_default = overrides.get("is_default", False)
    t.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    t.updated_at = overrides.get("updated_at", datetime(2026, 1, 1))
    return t


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service(self) -> None:
        svc = _service(db=AsyncMock())
        assert isinstance(svc, VideoTemplateService)


# ── GET / ───────────────────────────────────────────────────────────


class TestList:
    async def test_returns_response_models(self) -> None:
        svc = MagicMock()
        svc.list_all = AsyncMock(return_value=[_make_template(), _make_template()])
        out = await list_video_templates(svc=svc)
        assert len(out) == 2


# ── POST / ──────────────────────────────────────────────────────────


class TestCreate:
    async def test_returns_response(self) -> None:
        svc = MagicMock()
        t = _make_template(name="Mech")
        svc.create = AsyncMock(return_value=t)
        out = await create_video_template(VideoTemplateCreate(name="Mech"), svc=svc)
        assert out.name == "Mech"


# ── GET /{id} ───────────────────────────────────────────────────────


class TestGet:
    async def test_success(self) -> None:
        svc = MagicMock()
        t = _make_template()
        svc.get = AsyncMock(return_value=t)
        out = await get_video_template(t.id, svc=svc)
        assert out.id == t.id

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("video_template", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_video_template(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── PUT /{id} ───────────────────────────────────────────────────────


class TestUpdate:
    async def test_success(self) -> None:
        svc = MagicMock()
        t = _make_template(name="renamed")
        svc.update = AsyncMock(return_value=t)
        out = await update_video_template(t.id, VideoTemplateUpdate(name="renamed"), svc=svc)
        assert out.name == "renamed"
        # exclude_unset semantics: only provided fields go to the service.
        kwargs = svc.update.call_args.kwargs
        assert kwargs == {"name": "renamed"}

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=NotFoundError("video_template", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_video_template(uuid4(), VideoTemplateUpdate(), svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_error_maps_to_422(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ValidationError("bad target duration"))
        with pytest.raises(HTTPException) as exc:
            await update_video_template(uuid4(), VideoTemplateUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 422


# ── DELETE /{id} ────────────────────────────────────────────────────


class TestDelete:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_video_template(uuid4(), svc=svc)
        svc.delete.assert_awaited_once()

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("video_template", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_video_template(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── POST /{id}/apply/{series_id} ────────────────────────────────────


class TestApplyTemplateToSeries:
    async def test_success_reports_applied_fields(self) -> None:
        svc = MagicMock()
        t = _make_template(name="Cinematic")
        svc.apply_to_series = AsyncMock(
            return_value=(t, ["voice_profile_id", "visual_style", "music_mood"])
        )
        tid, sid = uuid4(), uuid4()
        out = await apply_template_to_series(tid, sid, svc=svc)
        assert out.applied_fields == ["voice_profile_id", "visual_style", "music_mood"]
        # Message includes the count for the toast.
        assert "3 field" in out.message

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.apply_to_series = AsyncMock(side_effect=NotFoundError("video_template", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await apply_template_to_series(uuid4(), uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── POST /from-series/{series_id} ──────────────────────────────────


class TestCreateFromSeries:
    async def test_strips_template_prefix_in_message(self) -> None:
        # The template name starts with "Template: " (the service convention)
        # → the human-readable message recovers the original series name.
        svc = MagicMock()
        t = _make_template(name="Template: Mech Hour")
        svc.create_from_series = AsyncMock(return_value=t)
        sid = uuid4()
        out = await create_template_from_series(sid, svc=svc)
        assert "Mech Hour" in out.message
        assert "from series" in out.message
        assert out.template.name == "Template: Mech Hour"

    async def test_no_prefix_omits_from_clause(self) -> None:
        # Defensive: if a future migration produces a template without the
        # "Template: " prefix, the message gracefully omits the "from series"
        # clause rather than splicing in an empty quote.
        svc = MagicMock()
        t = _make_template(name="Custom Name")
        svc.create_from_series = AsyncMock(return_value=t)
        out = await create_template_from_series(uuid4(), svc=svc)
        assert "from series" not in out.message
        assert "Custom Name" in out.message

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.create_from_series = AsyncMock(side_effect=NotFoundError("series", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await create_template_from_series(uuid4(), svc=svc)
        assert exc.value.status_code == 404
