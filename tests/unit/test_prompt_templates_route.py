"""Tests for ``api/routes/prompt_templates.py``.

Thin router over ``PromptTemplateService``. Pin the layering contract:
``NotFoundError`` → 404, ``ValidationError`` → 422, response models
serialised from ORM rows via ``model_validate``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.prompt_templates import (
    _service,
    create_prompt_template,
    delete_prompt_template,
    get_prompt_template,
    list_prompt_templates,
    update_prompt_template,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateUpdate,
)
from drevalis.services.prompt_template import PromptTemplateService


def _make_template(**overrides: Any) -> Any:
    t = MagicMock()
    t.id = overrides.get("id", uuid4())
    t.name = overrides.get("name", "Default Script")
    t.template_type = overrides.get("template_type", "script")
    t.system_prompt = overrides.get("system_prompt", "You are a writer.")
    t.user_prompt_template = overrides.get("user_prompt_template", "Write about {topic}")
    t.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    t.updated_at = overrides.get("updated_at", datetime(2026, 1, 1))
    return t


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service_bound_to_session(self) -> None:
        db = AsyncMock()
        svc = _service(db=db)
        assert isinstance(svc, PromptTemplateService)


# ── GET / ───────────────────────────────────────────────────────────


class TestList:
    async def test_no_filter(self) -> None:
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[_make_template(), _make_template()])
        out = await list_prompt_templates(template_type=None, svc=svc)
        assert len(out) == 2
        svc.list.assert_awaited_once_with(None)

    async def test_filter_by_type(self) -> None:
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[_make_template(template_type="hook")])
        out = await list_prompt_templates(template_type="hook", svc=svc)
        assert out[0].template_type == "hook"
        svc.list.assert_awaited_once_with("hook")


# ── POST / ──────────────────────────────────────────────────────────


class TestCreate:
    async def test_returns_response(self) -> None:
        svc = MagicMock()
        t = _make_template(name="X")
        svc.create = AsyncMock(return_value=t)
        body = PromptTemplateCreate(
            name="X",
            template_type="script",
            system_prompt="sys",
            user_prompt_template="usr",
        )
        out = await create_prompt_template(body, svc=svc)
        assert out.name == "X"


# ── GET /{id} ───────────────────────────────────────────────────────


class TestGet:
    async def test_returns_response(self) -> None:
        svc = MagicMock()
        t = _make_template()
        svc.get = AsyncMock(return_value=t)
        out = await get_prompt_template(t.id, svc=svc)
        assert out.id == t.id

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("prompt_template", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_prompt_template(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── PUT /{id} ───────────────────────────────────────────────────────


class TestUpdate:
    async def test_returns_updated(self) -> None:
        svc = MagicMock()
        t = _make_template(name="renamed")
        svc.update = AsyncMock(return_value=t)
        body = PromptTemplateUpdate(name="renamed")
        out = await update_prompt_template(t.id, body, svc=svc)
        assert out.name == "renamed"
        # exclude_unset semantics: only provided fields go to the service.
        kwargs = svc.update.call_args.kwargs
        assert kwargs == {"name": "renamed"}

    async def test_validation_error_maps_to_422(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ValidationError("empty patch"))
        with pytest.raises(HTTPException) as exc:
            await update_prompt_template(uuid4(), PromptTemplateUpdate(), svc=svc)
        assert exc.value.status_code == 422

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=NotFoundError("prompt_template", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_prompt_template(uuid4(), PromptTemplateUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 404


# ── DELETE /{id} ────────────────────────────────────────────────────


class TestDelete:
    async def test_success_returns_none(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_prompt_template(uuid4(), svc=svc)
        svc.delete.assert_awaited_once()

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("prompt_template", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_prompt_template(uuid4(), svc=svc)
        assert exc.value.status_code == 404
