"""Tests for ``api/routes/api_keys.py``.

Settings → API Keys + Integrations dashboard. Pin:

* Encrypted values are NEVER returned — list endpoint returns names
  + timestamps only.
* `delete` 404s when the key isn't stored (so the UI can show
  "already removed" instead of a generic 500).
* `/integrations`: source priority is **DB > env > none**. The
  YouTube integration is special because it needs BOTH client_id +
  client_secret rows; the regression that mistakenly looked for a
  single ``"youtube"`` row is pinned with explicit assertions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.api_keys import (
    _service,
    delete_api_key,
    get_integrations_status,
    list_api_keys,
    upsert_api_key,
)
from drevalis.core.exceptions import NotFoundError
from drevalis.schemas.runpod import ApiKeyStoreRequest
from drevalis.services.api_key_store import ApiKeyStoreService


def _make_settings(**overrides: Any) -> Any:
    s = MagicMock()
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    s.runpod_api_key = overrides.get("runpod_api_key", "")
    s.anthropic_api_key = overrides.get("anthropic_api_key", "")
    s.youtube_client_id = overrides.get("youtube_client_id", "")
    s.youtube_client_secret = overrides.get("youtube_client_secret", "")
    return s


def _make_entry(key_name: str) -> Any:
    e = MagicMock()
    e.key_name = key_name
    e.created_at = datetime(2026, 1, 1)
    e.updated_at = datetime(2026, 1, 2)
    return e


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service(self) -> None:
        svc = _service(db=AsyncMock(), settings=_make_settings())
        assert isinstance(svc, ApiKeyStoreService)


# ── GET /api-keys ──────────────────────────────────────────────────


class TestListApiKeys:
    async def test_returns_names_with_timestamps(self) -> None:
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[_make_entry("runpod"), _make_entry("anthropic")])
        out = await list_api_keys(svc=svc)
        names = [item.key_name for item in out.items]
        assert names == ["runpod", "anthropic"]
        # Every item is marked has_value (the DB row exists by definition).
        assert all(item.has_value for item in out.items)
        assert out.items[0].created_at == datetime(2026, 1, 1)


# ── POST /api-keys ─────────────────────────────────────────────────


class TestUpsertApiKey:
    async def test_persists_and_returns_name(self) -> None:
        svc = MagicMock()
        svc.upsert = AsyncMock()
        body = ApiKeyStoreRequest(key_name="runpod", api_key="rp-secret")
        out = await upsert_api_key(body, svc=svc)
        assert out.key_name == "runpod"
        # The plain-text key reaches the service (which encrypts) but is
        # NEVER reflected back in the response — pin that.
        assert not hasattr(out, "api_key")
        svc.upsert.assert_awaited_once_with(key_name="runpod", api_key="rp-secret")


# ── DELETE /api-keys/{key_name} ────────────────────────────────────


class TestDeleteApiKey:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_api_key("runpod", svc=svc)
        svc.delete.assert_awaited_once_with("runpod")

    async def test_not_found_maps_to_404_with_named_detail(self) -> None:
        # Pin: detail string includes the key name so the UI can render
        # "No API key stored for 'runpod'" rather than a generic 404.
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("api_key", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_api_key("runpod", svc=svc)
        assert exc.value.status_code == 404
        assert "runpod" in str(exc.value.detail)


# ── GET /integrations ──────────────────────────────────────────────


class TestIntegrationsStatus:
    async def test_db_keys_take_priority_over_env(self) -> None:
        svc = MagicMock()
        svc.list_stored_names = AsyncMock(return_value={"runpod", "anthropic"})
        # Env has runpod + anthropic too, but DB wins.
        settings = _make_settings(
            runpod_api_key="env-runpod",
            anthropic_api_key="env-anthropic",
        )
        out = await get_integrations_status(svc=svc, settings=settings)
        assert out.runpod.configured is True
        assert out.runpod.source == "db"
        assert out.anthropic.configured is True
        assert out.anthropic.source == "db"

    async def test_env_only_when_db_missing(self) -> None:
        svc = MagicMock()
        svc.list_stored_names = AsyncMock(return_value=set())
        settings = _make_settings(
            runpod_api_key="env-runpod",
            anthropic_api_key="",
        )
        out = await get_integrations_status(svc=svc, settings=settings)
        assert out.runpod.source == "env"
        # No env value either → not configured.
        assert out.anthropic.configured is False
        assert out.anthropic.source == "none"

    async def test_elevenlabs_never_env_sourced(self) -> None:
        # ElevenLabs is per-voice-profile; the integrations endpoint
        # passes "" as the env_value. Pin that env never claims it
        # configured.
        svc = MagicMock()
        svc.list_stored_names = AsyncMock(return_value=set())
        settings = _make_settings()
        out = await get_integrations_status(svc=svc, settings=settings)
        assert out.elevenlabs.configured is False
        assert out.elevenlabs.source == "none"

    async def test_elevenlabs_db_source_when_stored(self) -> None:
        svc = MagicMock()
        svc.list_stored_names = AsyncMock(return_value={"elevenlabs"})
        out = await get_integrations_status(svc=svc, settings=_make_settings())
        assert out.elevenlabs.configured is True
        assert out.elevenlabs.source == "db"

    async def test_youtube_requires_both_client_id_and_secret_in_db(self) -> None:
        # Regression pin: pre-v0.28.1 looked for a single "youtube" row
        # which never existed. The fix queries for both
        # ``youtube_client_id`` and ``youtube_client_secret``.
        svc = MagicMock()
        svc.list_stored_names = AsyncMock(
            return_value={"youtube_client_id", "youtube_client_secret"}
        )
        out = await get_integrations_status(svc=svc, settings=_make_settings())
        assert out.youtube.configured is True
        assert out.youtube.source == "db"

    async def test_youtube_partial_db_falls_through(self) -> None:
        # Only ``youtube_client_id`` stored → not configured (need both).
        svc = MagicMock()
        svc.list_stored_names = AsyncMock(return_value={"youtube_client_id"})
        out = await get_integrations_status(svc=svc, settings=_make_settings())
        assert out.youtube.configured is False
        assert out.youtube.source == "none"

    async def test_youtube_env_when_both_set(self) -> None:
        svc = MagicMock()
        svc.list_stored_names = AsyncMock(return_value=set())
        settings = _make_settings(
            youtube_client_id="env-cid",
            youtube_client_secret="env-secret",
        )
        out = await get_integrations_status(svc=svc, settings=settings)
        assert out.youtube.configured is True
        assert out.youtube.source == "env"

    async def test_youtube_env_partial_falls_through(self) -> None:
        # Only client_id in env → not configured.
        svc = MagicMock()
        svc.list_stored_names = AsyncMock(return_value=set())
        settings = _make_settings(youtube_client_id="env-cid")
        out = await get_integrations_status(svc=svc, settings=settings)
        assert out.youtube.configured is False
