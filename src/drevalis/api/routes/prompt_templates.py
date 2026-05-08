"""Prompt Templates API router -- CRUD endpoints.

Layering: this router calls ``PromptTemplateService`` only. No
repository imports here — that's the service's job.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.deps import get_db
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateResponse,
    PromptTemplateUpdate,
)
from drevalis.services.prompt_template import PromptTemplateService

router = APIRouter(prefix="/api/v1/prompt-templates", tags=["prompt-templates"])


def _service(db: AsyncSession = Depends(get_db)) -> PromptTemplateService:
    return PromptTemplateService(db)


# ── List prompt templates ─────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[PromptTemplateResponse],
    status_code=status.HTTP_200_OK,
    summary="List all prompt templates",
)
async def list_prompt_templates(
    template_type: str | None = Query(
        default=None,
        description="Filter by type: script, visual, hook, hashtag",
    ),
    svc: PromptTemplateService = Depends(_service),
) -> list[PromptTemplateResponse]:
    """Return all prompt templates, optionally filtered by type."""
    templates = await svc.list(template_type)
    return [PromptTemplateResponse.model_validate(t) for t in templates]


# ── Create prompt template ────────────────────────────────────────────────


@router.post(
    "",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new prompt template",
)
async def create_prompt_template(
    payload: PromptTemplateCreate,
    svc: PromptTemplateService = Depends(_service),
) -> PromptTemplateResponse:
    """Create a new prompt template."""
    template = await svc.create(**payload.model_dump())
    return PromptTemplateResponse.model_validate(template)


# ── Get prompt template ──────────────────────────────────────────────────


@router.get(
    "/{template_id}",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a prompt template by ID",
)
async def get_prompt_template(
    template_id: UUID,
    svc: PromptTemplateService = Depends(_service),
) -> PromptTemplateResponse:
    """Fetch a single prompt template by ID."""
    try:
        template = await svc.get(template_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PromptTemplateResponse.model_validate(template)


# ── Update prompt template ───────────────────────────────────────────────


@router.put(
    "/{template_id}",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a prompt template",
)
async def update_prompt_template(
    template_id: UUID,
    payload: PromptTemplateUpdate,
    svc: PromptTemplateService = Depends(_service),
) -> PromptTemplateResponse:
    """Update an existing prompt template."""
    try:
        template = await svc.update(template_id, **payload.model_dump(exclude_unset=True))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PromptTemplateResponse.model_validate(template)


# ── Delete prompt template ───────────────────────────────────────────────


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a prompt template",
)
async def delete_prompt_template(
    template_id: UUID,
    svc: PromptTemplateService = Depends(_service),
) -> None:
    """Delete a prompt template by ID."""
    try:
        await svc.delete(template_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
