"""Telemetry bootstrap endpoint.

Single GET that the frontend hits on page load to discover whether it
should initialise Sentry/Glitchtip and, if so, which DSN to use. The
backend is the source of truth — the SPA bundle never bakes a DSN in
so the operator can flip destinations without re-shipping the
frontend.

The response intentionally exposes a *public* DSN value: Sentry/
Glitchtip DSNs are designed to be embedded in browser bundles. They
identify the project, not an authenticated user, and the ingestion
endpoint rate-limits per-DSN. Treat it as roughly equivalent to a
"site key" in a CAPTCHA service.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.models.user import User

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


class TelemetryBootstrapResponse(BaseModel):
    """Frontend-consumable telemetry config.

    ``dsn`` and ``enabled`` together gate whether the SPA initialises
    the SDK. ``release`` is the app version string used for grouping
    events in the dashboard.
    """

    dsn: str | None
    enabled: bool
    environment: str
    release: str | None


@router.get(
    "/bootstrap",
    response_model=TelemetryBootstrapResponse,
    status_code=status.HTTP_200_OK,
    summary="Telemetry config the frontend needs to initialise its SDK",
)
async def get_telemetry_bootstrap(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TelemetryBootstrapResponse:
    """Return the frontend telemetry config.

    Always returns 200 (including when telemetry is disabled) so the
    frontend has a single deterministic call shape and can flip-flop
    cleanly when the user toggles Settings → Privacy without a hard
    refresh.

    The final ``enabled`` value is the AND of:
        1. ``Settings.telemetry_enabled`` (env, restart to change)
        2. ``Settings.telemetry_dsn`` is set
        3. User did not explicitly opt out via ``preferences[
           "telemetry_opt_out"] = True``
    """
    user_opted_out = False
    # Single-user desktop installs: the first user row IS the owner.
    user = (await db.execute(select(User).limit(1))).scalars().first()
    if user is not None:
        user_opted_out = bool((user.preferences or {}).get("telemetry_opt_out"))

    enabled = (
        settings.telemetry_enabled
        and bool(settings.telemetry_dsn)
        and not user_opted_out
    )
    return TelemetryBootstrapResponse(
        dsn=settings.telemetry_dsn if enabled else None,
        enabled=enabled,
        environment=settings.telemetry_environment,
        release=os.environ.get("DREVALIS_RELEASE"),
    )
