"""Shared internals for the episodes route package.

Every sub-router imports ``_episode_service`` (the DI provider) and
``logger`` from here so the route handlers stay terse. Response
converters live here too because both ``lifecycle`` and ``exports``
want to render ``EpisodeResponse`` / ``EpisodeListResponse``.

This module is package-private — nothing outside
``drevalis.api.routes.episodes.*`` should import from it. The public
``router`` aggregate is exposed via ``episodes/__init__.py``.
"""

from __future__ import annotations

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.deps import get_db
from drevalis.models.episode import Episode
from drevalis.schemas.episode import EpisodeListResponse, EpisodeResponse
from drevalis.services.episode import EpisodeService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def episode_service(db: AsyncSession = Depends(get_db)) -> EpisodeService:
    """Build an ``EpisodeService`` bound to the request's DB session.

    Used as the ``Depends`` provider on every route in this package.
    Kept package-private (underscored alias also exported) — external
    callers should construct ``EpisodeService`` directly.
    """
    return EpisodeService(db)


# Underscored alias preserves the original ``_monolith.py`` name so
# any internal cross-references that still spell it that way during
# the split keep working. Drop after the split is verified.
_episode_service = episode_service


def episode_to_response(episode: Episode) -> EpisodeResponse:
    """Convert an Episode ORM object (with relations loaded) to a response."""
    return EpisodeResponse.model_validate(episode)


def episode_to_list(episode: Episode) -> EpisodeListResponse:
    """Convert an Episode ORM object to a list response."""
    return EpisodeListResponse.model_validate(episode)


# Same underscore-alias pattern for the converters.
_episode_to_response = episode_to_response
_episode_to_list = episode_to_list
