"""License management routes.

Layering: this router calls ``LicenseService`` only. No repository
imports, no direct httpx orchestration here (audit F-A-01).

These endpoints are intentionally exempt from ``LicenseGateMiddleware``
so an unactivated install can still respond to ``GET /status`` (so the
frontend knows what screen to show) and ``POST /activate`` (to accept a
key from the user).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from drevalis.core.database import get_db_session
from drevalis.core.deps import get_redis, get_settings
from drevalis.core.exceptions import ValidationError
from drevalis.services.license import (
    ActivationError,
    ActivationNetworkError,
    LicenseConfigError,
    LicenseNotActiveError,
    LicensePortalUpstreamError,
    LicenseService,
    LicenseVerificationError,
    NoActiveLicenseError,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.core.config import Settings


router = APIRouter(prefix="/api/v1/license", tags=["license"])


def _service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> LicenseService:
    return LicenseService(session, settings, redis)


# ── Schemas ──────────────────────────────────────────────────────────────


class LicenseStatusResponse(BaseModel):
    state: str = Field(description="LicenseStatus value: unactivated|active|grace|expired|invalid")
    tier: str | None = None
    features: list[str] = Field(default_factory=list)
    machines_cap: int | None = None
    machine_id: str
    activated_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_heartbeat_status: str | None = None
    period_end: datetime | None = None
    exp: datetime | None = None
    error: str | None = None
    license_type: str | None = None
    update_window_expires_at: datetime | None = None


class ActivateRequest(BaseModel):
    license_jwt: str = Field(
        description=(
            "Accepts either a short license key (UUID, as emailed to the customer) "
            "OR a raw signed JWT. If a key is passed and LICENSE_SERVER_URL is "
            "configured, the server exchanges it for a JWT; otherwise the value "
            "is verified locally."
        ),
        min_length=8,
    )


class ActivationEntry(BaseModel):
    machine_id: str
    first_seen: int | None = None
    last_heartbeat: int | None = None
    last_known_version: str | None = None
    is_this_machine: bool = False


class ActivationsResponse(BaseModel):
    tier: str
    cap: int
    this_machine_id: str
    activations: list[ActivationEntry]


class ActivationsByKeyRequest(BaseModel):
    license_key: str = Field(min_length=8)


class DeactivateByKeyRequest(BaseModel):
    license_key: str = Field(min_length=8)
    machine_id: str = Field(min_length=4, max_length=64)


class PortalResponse(BaseModel):
    url: str


# ── Error mapping ────────────────────────────────────────────────────────


def _activation_error(exc: ActivationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.error, **exc.detail},
    )


def _network_error(exc: ActivationNetworkError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "license_server_unreachable", "reason": str(exc)[:200]},
    )


# ── Status ───────────────────────────────────────────────────────────────


@router.get("/status", response_model=LicenseStatusResponse)
async def get_license_status(
    svc: LicenseService = Depends(_service),
) -> LicenseStatusResponse:
    return LicenseStatusResponse(**await svc.get_status())


@router.get("/quota")
async def get_quota(
    redis: Redis = Depends(get_redis),
) -> dict[str, int | None]:
    """Today's episode-generation usage against the tier's daily cap.

    Returns ``{used, limit}``. ``limit`` is ``None`` for unlimited tiers
    (Creator+, with the post-rebrand pricing). Unactivated installs
    return ``{used: 0, limit: 0}`` rather than raising — the dashboard
    widget can render a calm "0 / 0" instead of an error pill.
    """
    from drevalis.core.license.quota import get_daily_episode_usage

    return await get_daily_episode_usage(redis)


# ── Activate / Deactivate ────────────────────────────────────────────────


@router.post("/activate", response_model=LicenseStatusResponse)
async def activate_license(
    body: ActivateRequest,
    svc: LicenseService = Depends(_service),
) -> LicenseStatusResponse:
    """Activate a license on this install.

    Accepts either a JWT (paste directly, Phase 1 path) or a license key
    UUID (Phase 2: exchange with the license server, get a fresh JWT).
    The final stored value is always a JWT, verified with the embedded
    public key before being persisted.
    """
    try:
        result = await svc.activate(body.license_jwt)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "license_server_not_configured", "hint": exc.detail},
        ) from exc
    except ActivationNetworkError as exc:
        raise _network_error(exc) from exc
    except ActivationError as exc:
        raise _activation_error(exc) from exc
    except LicenseVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_license", "reason": str(exc)[:200]},
        ) from exc
    except LicenseNotActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "license_not_active", "state": exc.classification.value},
        ) from exc
    return LicenseStatusResponse(**result)


@router.post("/deactivate", response_model=LicenseStatusResponse)
async def deactivate_license(
    svc: LicenseService = Depends(_service),
) -> LicenseStatusResponse:
    """Remove the stored JWT. App flips back to UNACTIVATED on next request.

    If a license server is configured, best-effort releases the seat so the
    user can activate another machine. Network errors here don't block the
    local deactivate — the JWT is always cleared.
    """
    return LicenseStatusResponse(**await svc.deactivate())


# ── Activations management ───────────────────────────────────────────────


@router.get("/activations", response_model=ActivationsResponse)
async def list_activations(
    svc: LicenseService = Depends(_service),
) -> ActivationsResponse:
    """Return every machine currently holding a seat on this license."""
    try:
        raw = await svc.list_activations()
    except LicenseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "license_server_not_configured"},
        ) from exc
    except NoActiveLicenseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_active_license"},
        ) from exc
    except ActivationNetworkError as exc:
        raise _network_error(exc) from exc
    except ActivationError as exc:
        raise _activation_error(exc) from exc
    return ActivationsResponse(**raw)


@router.post(
    "/activations/query",
    response_model=ActivationsResponse,
    summary="List seats for a license key (no local activation required)",
)
async def list_activations_by_key(
    body: ActivationsByKeyRequest,
    svc: LicenseService = Depends(_service),
) -> ActivationsResponse:
    """List seats using a license key supplied in the request body."""
    try:
        raw = await svc.list_activations_by_key(body.license_key)
    except LicenseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "license_server_not_configured"},
        ) from exc
    except ActivationNetworkError as exc:
        raise _network_error(exc) from exc
    except ActivationError as exc:
        raise _activation_error(exc) from exc
    return ActivationsResponse(**raw)


@router.post(
    "/activations/free-seat",
    response_model=ActivationsResponse,
    summary="Deactivate a machine via license key (works pre-activation)",
)
async def deactivate_machine_by_key(
    body: DeactivateByKeyRequest,
    svc: LicenseService = Depends(_service),
) -> ActivationsResponse:
    """Release the seat for ``machine_id`` using a license key supplied
    in the request body. Used by the activation wizard to recover from
    seat-cap lockout. Does NOT touch local state."""
    try:
        raw = await svc.deactivate_machine_by_key(body.license_key, body.machine_id)
    except LicenseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "license_server_not_configured"},
        ) from exc
    except ActivationNetworkError as exc:
        raise _network_error(exc) from exc
    except ActivationError as exc:
        raise _activation_error(exc) from exc
    return ActivationsResponse(**raw)


@router.post(
    "/activations/{machine_id}/deactivate",
    response_model=ActivationsResponse,
    summary="Deactivate a specific machine",
)
async def deactivate_machine(
    machine_id: str,
    svc: LicenseService = Depends(_service),
) -> ActivationsResponse:
    """Release the seat held by ``machine_id`` on this license.

    If ``machine_id`` matches the caller's own machine, additionally
    clears the local JWT — same effect as POST /deactivate. If it's a
    different machine, only the server-side seat is released.
    """
    try:
        raw = await svc.deactivate_machine(machine_id)
    except LicenseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "license_server_not_configured"},
        ) from exc
    except NoActiveLicenseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_active_license"},
        ) from exc
    except ActivationNetworkError as exc:
        raise _network_error(exc) from exc
    except ActivationError as exc:
        raise _activation_error(exc) from exc
    return ActivationsResponse(**raw)


# ── Billing portal ───────────────────────────────────────────────────────


@router.post("/portal", response_model=PortalResponse)
async def open_billing_portal(
    svc: LicenseService = Depends(_service),
) -> PortalResponse:
    """Relay the current license to the server's ``/portal`` endpoint.

    Returns a Stripe billing-portal URL the frontend can redirect to.
    Requires the license_key (``jti``) from the currently-verified JWT,
    so only an actively-licensed install can open the portal.
    """
    try:
        url = await svc.billing_portal()
    except NoActiveLicenseError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "license_required"},
        ) from exc
    except LicenseConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "license_server_not_configured", "hint": str(exc)},
        ) from exc
    except ActivationNetworkError as exc:
        raise _network_error(exc) from exc
    except LicensePortalUpstreamError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail if isinstance(exc.detail, dict) else {"raw": str(exc.detail)},
        ) from exc
    return PortalResponse(url=url)
