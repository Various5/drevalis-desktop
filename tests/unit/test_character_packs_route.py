"""Tests for ``api/routes/character_packs.py``.

Thin router that calls ``CharacterPackService``. Pin the layering
contract: validation errors map to 400, missing rows on apply map to
404, and the response shape mirrors the model fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.character_packs import (
    ApplyPackRequest,
    CharacterPackCreate,
    _service,
    apply_pack,
    create_pack,
    delete_pack,
    list_packs,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.services.character_pack import CharacterPackService


class TestServiceFactory:
    def test_returns_service_bound_to_session(self) -> None:
        # ``_service`` is the FastAPI dep that wires every route handler
        # to a per-request CharacterPackService. Pin the wiring so a
        # later refactor doesn't accidentally drop the session.
        db = AsyncMock()
        svc = _service(db=db)
        assert isinstance(svc, CharacterPackService)


def _make_pack(**overrides: Any) -> Any:
    p = MagicMock()
    p.id = overrides.get("id", uuid4())
    p.name = overrides.get("name", "Mech Hero")
    p.description = overrides.get("description", "Stylised cyberpunk lead")
    p.thumbnail_asset_id = overrides.get("thumbnail_asset_id")
    p.character_lock = overrides.get("character_lock", {"face": "abc"})
    p.style_lock = overrides.get("style_lock")
    p.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    return p


# ── GET / ───────────────────────────────────────────────────────────


class TestListPacks:
    async def test_returns_response_models(self) -> None:
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[_make_pack(), _make_pack()])
        out = await list_packs(svc=svc)
        assert len(out) == 2
        assert all(r.name == "Mech Hero" for r in out)


# ── POST / ──────────────────────────────────────────────────────────


class TestCreatePack:
    async def test_create_returns_pack(self) -> None:
        svc = MagicMock()
        pack = _make_pack(name="Witch")
        svc.create = AsyncMock(return_value=pack)

        body = CharacterPackCreate(name="Witch")
        out = await create_pack(body, svc=svc)

        assert out.name == "Witch"
        # Service called with kw-only args.
        svc.create.assert_awaited_once()
        kwargs = svc.create.call_args.kwargs
        assert kwargs["name"] == "Witch"

    async def test_validation_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=ValidationError("bad name"))
        body = CharacterPackCreate(name="x")
        with pytest.raises(HTTPException) as exc:
            await create_pack(body, svc=svc)
        assert exc.value.status_code == 400


# ── DELETE /{pack_id} ───────────────────────────────────────────────


class TestDeletePack:
    async def test_delegates_to_service(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        pid = uuid4()
        await delete_pack(pid, svc=svc)
        svc.delete.assert_awaited_once_with(pid)


# ── POST /{pack_id}/apply ───────────────────────────────────────────


class TestApplyPack:
    async def test_apply_returns_service_result(self) -> None:
        svc = MagicMock()
        svc.apply = AsyncMock(return_value={"applied": True})
        pid, sid = uuid4(), uuid4()
        out = await apply_pack(pid, ApplyPackRequest(series_id=sid), svc=svc)
        assert out == {"applied": True}
        svc.apply.assert_awaited_once_with(pid, sid)

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.apply = AsyncMock(side_effect=NotFoundError("character_pack", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await apply_pack(uuid4(), ApplyPackRequest(series_id=uuid4()), svc=svc)
        assert exc.value.status_code == 404
