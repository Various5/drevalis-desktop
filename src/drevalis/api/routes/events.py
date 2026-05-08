"""App-event log route.

Endpoint
--------
``GET /api/v1/events``

Returns recent warning / error / critical events parsed from the
structlog JSON log file.  The log file path is read from
``settings.log_file``; when not configured the endpoint returns an
empty list rather than an error.

Authorization
-------------
Uses the same ``require_owner`` gate as ``GET /api/v1/diagnostics/bundle``:
- **Team mode**: caller must be authenticated with the ``owner`` role.
- **Non-team mode** (no user rows in the DB): ``require_user`` raises 401,
  which the frontend handles as a graceful no-auth state.  Single-user
  installs that don't use team mode will want to note that this endpoint
  requires setting up team mode or removing the guard for local-only use.

Known limitation — Docker socket integration
--------------------------------------------
Worker and infrastructure container logs (Postgres, Redis) are **not**
surfaced here.  Doing so would require mounting ``/var/run/docker.sock``
into the backend container.  That widens the trust boundary significantly:
any process with access to the socket can control the Docker daemon,
read environment variables from other containers, and escalate to host
root.  This is a deliberate security boundary that must not be crossed
without explicit operator sign-off.

Follow-up: bind-mount a shared log directory from the host instead of
the Docker socket, then add a ``LOG_FILE_WORKER`` setting that points at
the worker's JSON log file.  This surfaces worker errors without touching
the socket trust boundary.
"""

from __future__ import annotations

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from drevalis.api.routes.auth import require_owner
from drevalis.core.config import Settings
from drevalis.core.deps import get_settings
from drevalis.models.user import User
from drevalis.services.event_log import LogEvent, read_recent_events

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/events", tags=["events"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LIMIT = 200
_MAX_LIMIT = 1000

# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class EventsResponse(BaseModel):
    """Envelope returned by ``GET /api/v1/events``."""

    events: list[LogEvent]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=EventsResponse,
    status_code=status.HTTP_200_OK,
    summary="Recent app warning/error events from the structured log file",
    description=(
        "Reads the structlog JSON log file (``LOG_FILE`` env var / "
        "``settings.log_file``) and returns up to ``limit`` events at or "
        "above ``min_level``, newest first.  Returns an empty list when the "
        "log file is not configured or does not exist — never raises 500 for "
        "a missing file.\n\n"
        "Requires owner role in team-mode installs."
    ),
)
async def get_events(
    _owner: Annotated[User, Depends(require_owner)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=_MAX_LIMIT,
            description=f"Maximum events to return (1–{_MAX_LIMIT}, default {_DEFAULT_LIMIT}).",
        ),
    ] = _DEFAULT_LIMIT,
    min_level: Annotated[
        Literal["warning", "error", "critical"],
        Query(description="Minimum log severity to include."),
    ] = "warning",
) -> EventsResponse:
    """Return recent log events at or above *min_level*.

    Events are read from the JSON-lines log file configured via the
    ``LOG_FILE`` environment variable.  If the file is absent or the
    variable is unset, the response contains an empty ``events`` list.

    Args:
        _owner: Resolved by ``require_owner`` — enforces owner-role gate.
        settings: Application settings (injected).
        limit: Maximum number of events to return.
        min_level: Minimum severity; one of ``warning``, ``error``,
            ``critical``.

    Returns:
        ``EventsResponse`` with a ``events`` list ordered newest-first.
    """
    events = await read_recent_events(settings, limit=limit, min_level=min_level)
    logger.debug(
        "events.fetched",
        count=len(events),
        limit=limit,
        min_level=min_level,
    )
    return EventsResponse(events=events)
