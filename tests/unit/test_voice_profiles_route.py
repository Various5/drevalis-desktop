"""Tests for ``api/routes/voice_profiles.py``.

Thin router over ``VoiceProfileService``. Pin layered status mapping +
the test-voice endpoint's default-text fallback (used by the UI's
"play sample" button which posts an empty body).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.voice_profiles import (
    _service,
    clone_voice,
    create_voice_profile,
    delete_voice_profile,
    generate_voice_previews,
    get_voice_profile,
    list_voice_profiles,
    update_voice_profile,
)
from drevalis.api.routes.voice_profiles import (
    test_voice_profile as _test_voice_profile,  # noqa: F401 -- aliased below
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.voice_profile import (
    CloneVoiceRequest,
    CloneVoiceResponse,
    VoiceProfileCreate,
    VoiceProfileUpdate,
    VoiceTestRequest,
    VoiceTestResponse,
)
from drevalis.services.voice_profile import VoiceProfileService

# Pytest collects bare ``test_*`` callables imported into the module as
# tests. Rename the route handler so it isn't picked up.
voice_test_endpoint = _test_voice_profile


def _make_profile(**overrides: Any) -> Any:
    p = MagicMock()
    p.id = overrides.get("id", uuid4())
    p.name = overrides.get("name", "Default")
    p.provider = overrides.get("provider", "piper")
    p.piper_model_path = overrides.get("piper_model_path")
    p.piper_speaker_id = overrides.get("piper_speaker_id")
    p.speed = overrides.get("speed", 1.0)
    p.pitch = overrides.get("pitch", 1.0)
    p.elevenlabs_voice_id = overrides.get("elevenlabs_voice_id")
    p.kokoro_voice_name = overrides.get("kokoro_voice_name")
    p.kokoro_model_path = overrides.get("kokoro_model_path")
    p.edge_voice_id = overrides.get("edge_voice_id")
    p.gender = overrides.get("gender")
    p.sample_audio_path = overrides.get("sample_audio_path")
    p.language_code = overrides.get("language_code")
    p.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    p.updated_at = overrides.get("updated_at", datetime(2026, 1, 1))
    return p


def _settings() -> Any:
    s = MagicMock()
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    s.storage_base_path = MagicMock()
    s.piper_models_path = MagicMock()
    s.kokoro_models_path = MagicMock()
    return s


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service(self) -> None:
        svc = _service(db=AsyncMock(), settings=_settings())
        assert isinstance(svc, VoiceProfileService)


# ── GET / ───────────────────────────────────────────────────────────


class TestList:
    async def test_passes_filters(self) -> None:
        svc = MagicMock()
        svc.list_filtered = AsyncMock(return_value=[_make_profile()])
        out = await list_voice_profiles(provider="piper", language_code="en-US", svc=svc)
        assert len(out) == 1
        svc.list_filtered.assert_awaited_once_with(provider="piper", language_code="en-US")


# ── POST /generate-previews ────────────────────────────────────────


class TestGeneratePreviews:
    async def test_success_returns_counts(self) -> None:
        svc = MagicMock()
        svc.generate_all_previews = AsyncMock(
            return_value={"generated": 3, "skipped": 1, "failed": 0}
        )
        out = await generate_voice_previews(svc=svc)
        assert out["generated"] == 3

    async def test_validation_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.generate_all_previews = AsyncMock(side_effect=ValidationError("no comfyui server"))
        with pytest.raises(HTTPException) as exc:
            await generate_voice_previews(svc=svc)
        assert exc.value.status_code == 400


# ── POST / ──────────────────────────────────────────────────────────


class TestCreate:
    async def test_create_returns_profile(self) -> None:
        svc = MagicMock()
        p = _make_profile(name="Sara")
        svc.create = AsyncMock(return_value=p)
        body = VoiceProfileCreate(name="Sara", provider="piper")
        out = await create_voice_profile(body, svc=svc)
        assert out.name == "Sara"


# ── GET /{id} ───────────────────────────────────────────────────────


class TestGet:
    async def test_success(self) -> None:
        svc = MagicMock()
        p = _make_profile()
        svc.get = AsyncMock(return_value=p)
        out = await get_voice_profile(p.id, svc=svc)
        assert out.id == p.id

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("voice_profile", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_voice_profile(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── PUT /{id} ───────────────────────────────────────────────────────


class TestUpdate:
    async def test_success(self) -> None:
        svc = MagicMock()
        p = _make_profile(name="renamed")
        svc.update = AsyncMock(return_value=p)
        out = await update_voice_profile(p.id, VoiceProfileUpdate(name="renamed"), svc=svc)
        assert out.name == "renamed"

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=NotFoundError("voice_profile", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_voice_profile(uuid4(), VoiceProfileUpdate(), svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_error_maps_to_422(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ValidationError("invalid speed"))
        with pytest.raises(HTTPException) as exc:
            await update_voice_profile(uuid4(), VoiceProfileUpdate(speed=99.0), svc=svc)
        assert exc.value.status_code == 422


# ── DELETE /{id} ────────────────────────────────────────────────────


class TestDelete:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_voice_profile(uuid4(), svc=svc)
        svc.delete.assert_awaited_once()

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("voice_profile", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_voice_profile(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── POST /{id}/test ────────────────────────────────────────────────


class TestVoiceTest:
    async def test_uses_provided_text(self) -> None:
        svc = MagicMock()
        svc.test = AsyncMock(
            return_value=VoiceTestResponse(success=True, message="ok", audio_path="x.wav")
        )
        out = await voice_test_endpoint(uuid4(), VoiceTestRequest(text="custom"), svc=svc)
        assert out.success
        # Service called with the custom text, not the default.
        kwargs_text = svc.test.call_args.args[1]
        assert kwargs_text == "custom"

    async def test_uses_default_text_when_body_omitted(self) -> None:
        # The UI's "play sample" button posts an empty body — pin that
        # the route falls back to a meaningful default rather than 422.
        svc = MagicMock()
        svc.test = AsyncMock(return_value=VoiceTestResponse(success=True, message="ok"))
        await voice_test_endpoint(uuid4(), payload=None, svc=svc)
        called_text = svc.test.call_args.args[1]
        assert "test" in called_text.lower()

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.test = AsyncMock(side_effect=NotFoundError("voice_profile", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await voice_test_endpoint(uuid4(), payload=None, svc=svc)
        assert exc.value.status_code == 404


# ── POST /clone ────────────────────────────────────────────────────


class TestCloneVoice:
    async def test_success(self) -> None:
        svc = MagicMock()
        resp = CloneVoiceResponse(
            voice_profile_id=uuid4(),
            provider="elevenlabs",
            status="pending_training",
            note="upload pending",
        )
        svc.clone = AsyncMock(return_value=resp)
        body = CloneVoiceRequest(asset_id=uuid4(), display_name="Sara Clone")
        out = await clone_voice(body, svc=svc)
        assert out.status == "pending_training"

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.clone = AsyncMock(side_effect=NotFoundError("asset", uuid4()))
        body = CloneVoiceRequest(asset_id=uuid4(), display_name="Sara")
        with pytest.raises(HTTPException) as exc:
            await clone_voice(body, svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.clone = AsyncMock(side_effect=ValidationError("not an audio asset"))
        body = CloneVoiceRequest(asset_id=uuid4(), display_name="Sara")
        with pytest.raises(HTTPException) as exc:
            await clone_voice(body, svc=svc)
        assert exc.value.status_code == 400
