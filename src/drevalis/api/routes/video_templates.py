"""Video Templates API router.

Provides CRUD for :class:`VideoTemplate` records plus two convenience
endpoints that bridge templates and series:

- ``POST /{id}/apply/{series_id}``  -- push template settings onto a series
- ``POST /from-series/{series_id}`` -- capture a series's settings as a new template

Layering: this router calls ``VideoTemplateService`` only. No
repository imports here.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.deps import get_db
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.video_template import (
    ApplyTemplateResponse,
    CreateFromSeriesResponse,
    VideoTemplateCreate,
    VideoTemplateResponse,
    VideoTemplateUpdate,
)
from drevalis.services.video_template import VideoTemplateService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/video-templates", tags=["video-templates"])


def _service(db: AsyncSession = Depends(get_db)) -> VideoTemplateService:
    return VideoTemplateService(db)


# ── List ─────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[VideoTemplateResponse],
    status_code=status.HTTP_200_OK,
    summary="List all video templates",
    description="Return every video template ordered by creation date (newest first).",
)
async def list_video_templates(
    svc: VideoTemplateService = Depends(_service),
) -> list[VideoTemplateResponse]:
    """Return all video templates."""
    templates = await svc.list_all()
    return [VideoTemplateResponse.model_validate(t) for t in templates]


# ── Create ────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=VideoTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new video template",
    description=(
        "Create a named preset capturing voice, visual, caption, music, and "
        "audio-mastering settings.  If ``is_default`` is ``true`` any previously "
        "default template is demoted automatically."
    ),
)
async def create_video_template(
    payload: VideoTemplateCreate,
    svc: VideoTemplateService = Depends(_service),
) -> VideoTemplateResponse:
    """Create a new video template."""
    template = await svc.create(**payload.model_dump())
    log.info(
        "video_template.created",
        template_id=str(template.id),
        name=template.name,
        is_default=template.is_default,
    )
    return VideoTemplateResponse.model_validate(template)


# ── Get by ID ─────────────────────────────────────────────────────────────


@router.get(
    "/{template_id}",
    response_model=VideoTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a video template by ID",
)
async def get_video_template(
    template_id: UUID,
    svc: VideoTemplateService = Depends(_service),
) -> VideoTemplateResponse:
    """Fetch a single video template by primary key."""
    try:
        template = await svc.get(template_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return VideoTemplateResponse.model_validate(template)


# ── Update ────────────────────────────────────────────────────────────────


@router.put(
    "/{template_id}",
    response_model=VideoTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a video template",
    description=(
        "Partial update: only the fields present in the request body are "
        "modified.  Setting ``is_default=true`` demotes the current default."
    ),
)
async def update_video_template(
    template_id: UUID,
    payload: VideoTemplateUpdate,
    svc: VideoTemplateService = Depends(_service),
) -> VideoTemplateResponse:
    """Update an existing video template."""
    try:
        template = await svc.update(template_id, **payload.model_dump(exclude_unset=True))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    log.info("video_template.updated", template_id=str(template_id))
    return VideoTemplateResponse.model_validate(template)


# ── Delete ────────────────────────────────────────────────────────────────


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a video template",
)
async def delete_video_template(
    template_id: UUID,
    svc: VideoTemplateService = Depends(_service),
) -> None:
    """Delete a video template by ID."""
    try:
        await svc.delete(template_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    log.info("video_template.deleted", template_id=str(template_id))


# ── Apply template to series ──────────────────────────────────────────────


@router.post(
    "/{template_id}/apply/{series_id}",
    response_model=ApplyTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply a video template to a series",
    description=(
        "Copy the template's settings onto the target series.  Fields that "
        "are ``None`` on the template are skipped — the series retains its "
        "existing values for those fields.  ``caption_style_preset`` is merged "
        "into the series ``caption_style`` JSONB as a ``preset`` key rather "
        "than replacing the entire caption config.  The template's "
        "``times_used`` counter is incremented atomically."
    ),
)
async def apply_template_to_series(
    template_id: UUID,
    series_id: UUID,
    svc: VideoTemplateService = Depends(_service),
) -> ApplyTemplateResponse:
    """Apply a video template to a series."""
    try:
        template, applied_fields = await svc.apply_to_series(template_id, series_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    log.info(
        "video_template.applied",
        template_id=str(template_id),
        series_id=str(series_id),
        fields_applied=applied_fields,
    )
    return ApplyTemplateResponse(
        series_id=series_id,
        template_id=template_id,
        applied_fields=applied_fields,
        message=(
            f"Template '{template.name}' applied to series. {len(applied_fields)} field(s) updated."
        ),
    )


# ── Create template from series ───────────────────────────────────────────


@router.post(
    "/from-series/{series_id}",
    response_model=CreateFromSeriesResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a video template from an existing series",
    description=(
        "Snapshot the current series settings into a new video template.  "
        "The template name defaults to the series name prefixed with 'Template: '.  "
        "``caption_style_preset`` is extracted from the series ``caption_style['preset']`` "
        "key if it exists.  The new template starts with ``times_used=0`` and "
        "``is_default=False``."
    ),
)
async def create_template_from_series(
    series_id: UUID,
    svc: VideoTemplateService = Depends(_service),
) -> CreateFromSeriesResponse:
    """Create a new video template by capturing the current state of a series."""
    try:
        template = await svc.create_from_series(series_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    log.info(
        "video_template.created_from_series",
        template_id=str(template.id),
        series_id=str(series_id),
    )
    return CreateFromSeriesResponse(
        template=VideoTemplateResponse.model_validate(template),
        # The original message read "from series '{series.name}'"; the
        # template name is "Template: {series.name}" so we strip the
        # prefix to recover the same human-readable string.
        message=(
            f"Template '{template.name}' created"
            f"{' from series ' + chr(39) + template.name.removeprefix('Template: ') + chr(39) if template.name.startswith('Template: ') else ''}."
        ),
    )
