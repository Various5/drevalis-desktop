"""PromptTemplateService — thin service layer over the repo.

Worked example for the layering rule (audit F-A-01): routers must NEVER
import a repository directly. The route handlers call this service;
this service is the only place that constructs `PromptTemplateRepository`.

Behavior is intentionally identical to the previous in-route logic — the
goal is the layering, not added features. Domain exceptions surface via
``drevalis.core.exceptions`` so the service stays FastAPI-free.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.models.prompt_template import PromptTemplate
from drevalis.repositories.prompt_template import PromptTemplateRepository


class PromptTemplateService:
    """CRUD orchestration for ``prompt_templates``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = PromptTemplateRepository(db)

    async def list(self, template_type: str | None = None) -> list[PromptTemplate]:
        """Return every template, optionally filtered by ``type``."""
        if template_type is not None:
            return await self._repo.get_by_type(template_type)
        return await self._repo.get_all()

    async def get(self, template_id: UUID) -> PromptTemplate:
        """Fetch one template; raise ``NotFoundError`` if missing."""
        template = await self._repo.get_by_id(template_id)
        if template is None:
            raise NotFoundError("Prompt template", template_id)
        return template

    async def create(self, **payload: Any) -> PromptTemplate:
        """Create a template; commit + refresh inside the unit-of-work."""
        template = await self._repo.create(**payload)
        await self._db.commit()
        await self._db.refresh(template)
        return template

    async def update(self, template_id: UUID, **patch: Any) -> PromptTemplate:
        """Apply a partial update; raise ``ValidationError`` on empty patch."""
        if not patch:
            raise ValidationError("No fields to update")
        template = await self._repo.update(template_id, **patch)
        if template is None:
            raise NotFoundError("Prompt template", template_id)
        await self._db.commit()
        await self._db.refresh(template)
        return template

    async def delete(self, template_id: UUID) -> None:
        """Delete a template; raise ``NotFoundError`` if missing."""
        deleted = await self._repo.delete(template_id)
        if not deleted:
            raise NotFoundError("Prompt template", template_id)
        await self._db.commit()
