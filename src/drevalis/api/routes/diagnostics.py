"""Diagnostics bundle endpoint.

Endpoint
--------
``GET /api/v1/diagnostics/bundle``

Returns a ``application/zip`` response containing a redacted snapshot of
the installation's configuration, health, recent logs, and system info.
Intended to be emailed to support when a user reports a problem.

Authorization: requires the ``owner`` role (team-mode) or open access when
team mode is not active (the same guard used by user-management routes).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.api.routes.auth import require_owner
from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.models.user import User
from drevalis.services.diagnostics import build_bundle

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])


@router.get(
    "/bundle",
    summary="Download a redacted support diagnostics bundle",
    description=(
        "Assembles a ZIP containing MANIFEST.txt, version.json, config.json "
        "(secrets redacted), health.json, recent_logs.txt, system.json, and "
        "db_revision.txt. Safe to email to support. Requires owner role in "
        "team-mode installs."
    ),
    status_code=200,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Diagnostics ZIP archive",
        }
    },
)
async def download_diagnostics_bundle(
    _owner: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Build and stream the diagnostics bundle as a ZIP download.

    The ``require_owner`` dependency means:
    - In **team mode**: the caller must be authenticated with the ``owner``
      role.
    - In **non-team mode** (no users in DB): ``_current_user`` returns
      ``None``, so ``require_user`` would raise 401.  Because most single-
      user installs don't use team mode, we degrade gracefully: if
      ``require_owner`` raises because there is no session (no team mode),
      the frontend handles that as a login prompt.  The bundle itself is
      not sensitive to anonymous users, but keeping the gate consistent
      with other admin-only endpoints is safer.
    """
    zip_bytes, size = await build_bundle(settings=settings, db=db)

    date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    filename = f"drevalis-diagnostics-{date_str}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(size),
        },
    )
