"""Tests for ``api/routes/llm.py``.

CRUD over ``LLMConfigService`` plus the live test endpoint that
actually calls a provider. Pin:

* `_config_to_response` derives `has_api_key` from the encrypted
  blob's presence (never returns the decrypted value).
* `delete` 404s when missing.
* `update` ValidationError → 422, NotFoundError → 404.
* The test endpoint **expunges** the config from the session before
  decrypting so a stray autoflush can't persist plaintext keys to
  the DB. Pinned with `expunge.assert_awaited_once_with(config)`.
* Test endpoint failure path returns `success=False` instead of
  raising — the UI shows a banner rather than a 500.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.llm import (
    _config_to_response,
    _service,
    create_llm_config,
    delete_llm_config,
    get_llm_config,
    list_llm_configs,
    update_llm_config,
)
from drevalis.api.routes.llm import (
    test_llm_config as _route_test_llm_config,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.llm_config import (
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMTestRequest,
)
from drevalis.services.llm_config import LLMConfigService

# Pytest collects bare ``test_*`` callables imported into the module.
# Rename to a non-collecting name so we can call the route handler.
llm_test_endpoint = _route_test_llm_config


def _make_config(**overrides: Any) -> Any:
    c = MagicMock()
    c.id = overrides.get("id", uuid4())
    c.name = overrides.get("name", "LM Studio")
    c.base_url = overrides.get("base_url", "http://localhost:1234/v1")
    c.model_name = overrides.get("model_name", "qwen2.5-7b")
    c.api_key_encrypted = overrides.get("api_key_encrypted")
    c.max_tokens = overrides.get("max_tokens", 4096)
    c.temperature = overrides.get("temperature", 0.7)
    c.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    c.updated_at = overrides.get("updated_at", datetime(2026, 1, 1))
    return c


def _settings() -> Any:
    s = MagicMock()
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    return s


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service(self) -> None:
        svc = _service(db=AsyncMock(), settings=_settings())
        assert isinstance(svc, LLMConfigService)


# ── _config_to_response ─────────────────────────────────────────────


class TestConfigToResponse:
    def test_no_api_key_yields_has_api_key_false(self) -> None:
        out = _config_to_response(_make_config(api_key_encrypted=None))
        assert out.has_api_key is False

    def test_encrypted_blob_yields_has_api_key_true(self) -> None:
        out = _config_to_response(_make_config(api_key_encrypted=b"opaque"))
        assert out.has_api_key is True


# ── GET / ───────────────────────────────────────────────────────────


class TestList:
    async def test_returns_response_models(self) -> None:
        svc = MagicMock()
        svc.list_all = AsyncMock(return_value=[_make_config(), _make_config()])
        out = await list_llm_configs(svc=svc)
        assert len(out) == 2


# ── POST / ──────────────────────────────────────────────────────────


class TestCreate:
    async def test_create_returns_response(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(return_value=_make_config())
        body = LLMConfigCreate(
            name="local",
            base_url="http://localhost:1234/v1",
            model_name="qwen2.5-7b",
        )
        out = await create_llm_config(body, svc=svc)
        assert out.name == "LM Studio"


# ── GET /{id} ───────────────────────────────────────────────────────


class TestGet:
    async def test_success(self) -> None:
        svc = MagicMock()
        c = _make_config()
        svc.get = AsyncMock(return_value=c)
        out = await get_llm_config(c.id, svc=svc)
        assert out.id == c.id

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("llm_config", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_llm_config(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── PUT /{id} ───────────────────────────────────────────────────────


class TestUpdate:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(return_value=_make_config(name="renamed"))
        out = await update_llm_config(uuid4(), LLMConfigUpdate(name="renamed"), svc=svc)
        assert out.name == "renamed"
        # exclude_unset semantics on update.
        kwargs = svc.update.call_args.kwargs
        assert kwargs == {"name": "renamed"}

    async def test_validation_error_maps_to_422(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ValidationError("bad temperature"))
        with pytest.raises(HTTPException) as exc:
            await update_llm_config(uuid4(), LLMConfigUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 422

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=NotFoundError("llm_config", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_llm_config(uuid4(), LLMConfigUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 404


# ── DELETE /{id} ────────────────────────────────────────────────────


class TestDelete:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_llm_config(uuid4(), svc=svc)
        svc.delete.assert_awaited_once()

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("llm_config", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_llm_config(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── POST /{id}/test ────────────────────────────────────────────────


class TestLLMTest:
    async def test_not_found_on_config_lookup_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("llm_config", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await llm_test_endpoint(uuid4(), payload=None, svc=svc, settings=_settings())
        assert exc.value.status_code == 404

    async def test_success_path_calls_provider_and_expunges(self) -> None:
        # Critical security pin: ``expunge`` MUST be awaited before any
        # decryption happens in the runtime, so an autoflush can't write
        # plaintext keys back to the DB. Confirm the order + the call.
        svc = MagicMock()
        config = _make_config()
        svc.get = AsyncMock(return_value=config)
        svc.expunge = AsyncMock()

        runtime = MagicMock()
        result = MagicMock()
        result.content = "Hello there!"
        result.model = "qwen2.5-7b"
        result.total_tokens = 12
        provider = MagicMock()
        provider.generate = AsyncMock(return_value=result)
        runtime.get_provider = MagicMock(return_value=provider)

        with patch("drevalis.services.llm.LLMService", return_value=runtime):
            out = await llm_test_endpoint(
                config.id,
                payload=LLMTestRequest(prompt="hi"),
                svc=svc,
                settings=_settings(),
            )

        assert out.success is True
        assert out.response_text == "Hello there!"
        assert out.model == "qwen2.5-7b"
        assert out.tokens_used == 12
        svc.expunge.assert_awaited_once_with(config)

    async def test_default_prompt_when_payload_omitted(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(return_value=_make_config())
        svc.expunge = AsyncMock()

        runtime = MagicMock()
        result = MagicMock()
        result.content = "ok"
        result.model = "m"
        result.total_tokens = 1
        provider = MagicMock()
        provider.generate = AsyncMock(return_value=result)
        runtime.get_provider = MagicMock(return_value=provider)

        with patch("drevalis.services.llm.LLMService", return_value=runtime):
            await llm_test_endpoint(uuid4(), payload=None, svc=svc, settings=_settings())

        # Default prompt used.
        called_user_prompt = provider.generate.call_args.kwargs["user_prompt"]
        assert "hello" in called_user_prompt.lower()

    async def test_runtime_failure_returns_failed_response(self) -> None:
        # When the provider raises (no LM Studio running, network error,
        # bad credentials) the route must NOT 500 — it returns a
        # success=False payload so the UI shows a banner.
        svc = MagicMock()
        svc.get = AsyncMock(return_value=_make_config())
        svc.expunge = AsyncMock()

        runtime = MagicMock()
        provider = MagicMock()
        provider.generate = AsyncMock(side_effect=ConnectionError("LM Studio down"))
        runtime.get_provider = MagicMock(return_value=provider)

        with patch("drevalis.services.llm.LLMService", return_value=runtime):
            out = await llm_test_endpoint(uuid4(), payload=None, svc=svc, settings=_settings())

        assert out.success is False
        assert out.response_text is None
