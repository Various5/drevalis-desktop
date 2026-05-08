"""Tests for ``PromptTemplateService`` (services/prompt_template.py).

Thin service layer over the repo — pin the layering contract:
NotFoundError raised on missing rows, ValidationError on empty patch,
DB commits orchestrated correctly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.services.prompt_template import PromptTemplateService


def _make_service() -> tuple[PromptTemplateService, MagicMock, AsyncMock]:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    repo = MagicMock()
    repo.get_by_type = AsyncMock(return_value=[])
    repo.get_all = AsyncMock(return_value=[])
    repo.get_by_id = AsyncMock(return_value=None)
    repo.create = AsyncMock()
    repo.update = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=False)
    with patch(
        "drevalis.services.prompt_template.PromptTemplateRepository",
        return_value=repo,
    ):
        svc = PromptTemplateService(db)
    return svc, repo, db


# ── list ────────────────────────────────────────────────────────────


class TestList:
    async def test_no_type_filter_calls_get_all(self) -> None:
        svc, repo, _ = _make_service()
        rows = [MagicMock(), MagicMock()]
        repo.get_all = AsyncMock(return_value=rows)
        out = await svc.list()
        assert out == rows
        repo.get_all.assert_awaited_once()
        repo.get_by_type.assert_not_awaited()

    async def test_type_filter_calls_get_by_type(self) -> None:
        svc, repo, _ = _make_service()
        rows = [MagicMock()]
        repo.get_by_type = AsyncMock(return_value=rows)
        out = await svc.list(template_type="script")
        assert out == rows
        repo.get_by_type.assert_awaited_once_with("script")
        repo.get_all.assert_not_awaited()


# ── get ────────────────────────────────────────────────────────────


class TestGet:
    async def test_returns_template_when_found(self) -> None:
        svc, repo, _ = _make_service()
        template = MagicMock()
        repo.get_by_id = AsyncMock(return_value=template)
        out = await svc.get(uuid4())
        assert out is template

    async def test_raises_not_found_when_missing(self) -> None:
        svc, repo, _ = _make_service()
        repo.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(NotFoundError):
            await svc.get(uuid4())


# ── create ─────────────────────────────────────────────────────────


class TestCreate:
    async def test_create_commits_and_refreshes(self) -> None:
        svc, repo, db = _make_service()
        template = MagicMock()
        repo.create = AsyncMock(return_value=template)
        out = await svc.create(name="X", template_type="script")
        assert out is template
        repo.create.assert_awaited_once()
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(template)


# ── update ─────────────────────────────────────────────────────────


class TestUpdate:
    async def test_empty_patch_raises_validation_error(self) -> None:
        svc, _, db = _make_service()
        with pytest.raises(ValidationError):
            await svc.update(uuid4())  # no kwargs
        # No commit on validation failure.
        db.commit.assert_not_awaited()

    async def test_missing_template_raises_not_found(self) -> None:
        svc, repo, db = _make_service()
        repo.update = AsyncMock(return_value=None)
        with pytest.raises(NotFoundError):
            await svc.update(uuid4(), name="X")
        # No commit when nothing was updated.
        db.commit.assert_not_awaited()

    async def test_successful_update_commits_and_refreshes(self) -> None:
        svc, repo, db = _make_service()
        updated = MagicMock()
        repo.update = AsyncMock(return_value=updated)
        out = await svc.update(uuid4(), name="X", description="Y")
        assert out is updated
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(updated)


# ── delete ─────────────────────────────────────────────────────────


class TestDelete:
    async def test_missing_template_raises_not_found(self) -> None:
        svc, repo, db = _make_service()
        repo.delete = AsyncMock(return_value=False)
        with pytest.raises(NotFoundError):
            await svc.delete(uuid4())
        db.commit.assert_not_awaited()

    async def test_existing_template_commits(self) -> None:
        svc, repo, db = _make_service()
        repo.delete = AsyncMock(return_value=True)
        await svc.delete(uuid4())
        db.commit.assert_awaited_once()
