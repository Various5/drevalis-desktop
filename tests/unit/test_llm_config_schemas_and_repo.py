"""Tests for ``schemas/llm_config.py`` and ``repositories/llm_config.py``.

Both are tiny — schema is mostly pydantic Field declarations + a URL
validator delegated to ``core.validators``. Repository is a single
``__init__`` that wires the BaseRepository to the LLMConfig model.

Pin:
* ``LLMConfigCreate.validate_base_url`` rejects unsafe URLs and accepts
  localhost / private hosts (which ``validate_safe_url_or_localhost``
  permits, unlike the SSRF-strict variant)
* ``LLMConfigUpdate.validate_base_url`` is a no-op when ``None`` (only
  applies when the caller actually patches the field)
* ``LLMConfigRepository.__init__`` constructs a base repo bound to
  the LLMConfig model class
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from drevalis.models.llm_config import LLMConfig
from drevalis.repositories.llm_config import LLMConfigRepository
from drevalis.schemas.llm_config import (
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMTestRequest,
    LLMTestResponse,
)

# ── LLMConfigCreate.validate_base_url ───────────────────────────────


class TestLLMConfigCreateValidateBaseUrl:
    def test_localhost_url_accepted(self) -> None:
        # localhost is the LM Studio default — must work.
        cfg = LLMConfigCreate(
            name="local",
            base_url="http://localhost:1234/v1",
            model_name="qwen2.5-7b",
        )
        assert cfg.base_url == "http://localhost:1234/v1"

    def test_https_public_url_accepted(self) -> None:
        cfg = LLMConfigCreate(
            name="anthropic",
            base_url="https://api.anthropic.com",
            model_name="claude-opus-4-7",
        )
        assert cfg.base_url == "https://api.anthropic.com"

    def test_invalid_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfigCreate(
                name="x",
                base_url="ftp://example.com",
                model_name="m",
            )


# ── LLMConfigUpdate.validate_base_url ───────────────────────────────


class TestLLMConfigUpdateValidateBaseUrl:
    def test_none_passes_through(self) -> None:
        # Patch payload that omits base_url entirely — validator
        # MUST short-circuit so the missing field stays unset rather
        # than triggering URL parsing on ``None``.
        upd = LLMConfigUpdate(name="renamed")
        assert upd.base_url is None

    def test_explicit_none_short_circuits_validator(self) -> None:
        # Explicitly setting base_url=None still drives the validator
        # branch where ``v is None`` — validator must return v as-is
        # rather than calling validate_safe_url_or_localhost(None).
        upd = LLMConfigUpdate(base_url=None)
        assert upd.base_url is None

    def test_provided_url_validated(self) -> None:
        upd = LLMConfigUpdate(base_url="http://localhost:1234/v1")
        assert upd.base_url == "http://localhost:1234/v1"

    def test_provided_invalid_url_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfigUpdate(base_url="not-a-url")


# ── LLMTestRequest / LLMTestResponse defaults ──────────────────────


class TestLLMTestSchemas:
    def test_test_request_default_prompt(self) -> None:
        # The default keeps the smoke-test endpoint copy-paste safe.
        req = LLMTestRequest()
        assert req.prompt == "Say hello in one sentence."

    def test_test_request_rejects_empty_prompt(self) -> None:
        with pytest.raises(ValidationError):
            LLMTestRequest(prompt="")

    def test_test_response_optional_fields(self) -> None:
        resp = LLMTestResponse(success=True, message="ok")
        assert resp.response_text is None
        assert resp.tokens_used is None


# ── LLMConfigRepository.__init__ ────────────────────────────────────


class TestLLMConfigRepository:
    def test_binds_model_to_base_repo(self) -> None:
        # Pin the wiring: subclassing BaseRepository[LLMConfig] without
        # passing the model would throw at runtime — this construction
        # asserts the constructor wired the right model class.
        session = AsyncMock()
        repo = LLMConfigRepository(session)
        assert repo.model is LLMConfig
        assert repo.session is session
