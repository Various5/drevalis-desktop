"""Client-facing activation, heartbeat, and deactivation."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app import db
from app.crypto import TIER_MACHINES, mint_jwt
from app.rate_limit import RateLimiter, _client_ip, rate_limit_ip

router = APIRouter(tags=["client"])

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# 30 requests / IP / minute. Activation is a ~UUID-keyed lookup; real
# clients heartbeat once per day, so any IP hitting the limit is
# almost certainly a scanner / brute-forcer.
_activate_rl = RateLimiter(capacity=30, refill_per_second=30 / 60)

# Per-LICENSE throttle for the seat-management surface (/activations,
# /deactivate). The per-IP limiter above is bypassable by rotating source
# IPs; keying on the license key caps total seat-management operations for
# a single license regardless of origin, blunting roster enumeration and
# seat-griefing by anyone who learns a license key. Generous for real use
# (the app lists seats on panel mount and deactivates rarely).
_seat_rl = RateLimiter(capacity=20, refill_per_second=20 / 60)


def _seat_throttle(license_key: str) -> None:
    """429 when the per-license seat-management budget is exhausted."""
    if not _seat_rl.take(f"seat:{license_key}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limited"},
            headers={"Retry-After": "60"},
        )


class ActivateRequest(BaseModel):
    license_key: str = Field(min_length=8)
    machine_id: str = Field(min_length=4, max_length=64)
    version: str | None = None


class HeartbeatRequest(BaseModel):
    license_key: str
    machine_id: str
    version: str | None = None


class DeactivateRequest(BaseModel):
    license_key: str
    machine_id: str


class JwtResponse(BaseModel):
    license_jwt: str
    tier: str
    period_end: int


async def _validate_and_mint(license_id: str, machine_id: str, version: str | None) -> JwtResponse:
    row = await db.get_license(license_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "license_not_found"},
        )
    if row["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "license_revoked"},
        )

    # Enforce seat cap before recording the activation — if we're at the
    # cap and this is a NEW machine, reject. Existing machines always pass.
    existing = {a["machine_id"] for a in await db.list_activations(license_id)}
    cap = TIER_MACHINES.get(row["tier"], 1)
    if machine_id not in existing and len(existing) >= cap:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "seat_cap_exceeded",
                "tier": row["tier"],
                "cap": cap,
                "current": len(existing),
                "hint": "Deactivate another machine first or upgrade your tier.",
            },
        )

    await db.record_activation(license_id=license_id, machine_id=machine_id, version=version)

    # ``license_type`` / ``update_window_expires_at`` are additive columns;
    # legacy subscription rows return None for the window, and the default
    # license_type is "subscription" via the ALTER TABLE default.
    license_type = row.get("license_type") or "subscription"
    update_window_expires_at = row.get("update_window_expires_at")

    token = mint_jwt(
        license_id=license_id,
        customer=row["stripe_customer"] or row.get("email") or license_id,
        tier=row["tier"],
        period_end_unix=row["period_end"],
        license_type=license_type,
        update_window_expires_at=update_window_expires_at,
    )
    return JwtResponse(license_jwt=token, tier=row["tier"], period_end=row["period_end"])


@router.post(
    "/activate",
    response_model=JwtResponse,
    dependencies=[Depends(rate_limit_ip(_activate_rl, prefix="activate"))],
)
async def activate(body: ActivateRequest) -> JwtResponse:
    return await _validate_and_mint(body.license_key, body.machine_id, body.version)


@router.post(
    "/heartbeat",
    response_model=JwtResponse,
    dependencies=[Depends(rate_limit_ip(_activate_rl, prefix="heartbeat"))],
)
async def heartbeat(body: HeartbeatRequest) -> JwtResponse:
    """Reissues the JWT with a fresh ``exp`` based on the license's current
    ``period_end``. If the license was revoked on the server, returns 402 so
    the client can zero its stored JWT.
    """
    return await _validate_and_mint(body.license_key, body.machine_id, body.version)


@router.post(
    "/deactivate",
    status_code=204,
    dependencies=[Depends(rate_limit_ip(_activate_rl, prefix="deactivate"))],
)
async def deactivate(body: DeactivateRequest, request: Request) -> None:
    _seat_throttle(body.license_key)
    row = await db.get_license(body.license_key)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "license_not_found"})
    await db.delete_activation(body.license_key, body.machine_id)
    # Audit trail: seat removal is destructive and gated only by knowledge
    # of the license key, so record who did it. Log a key SUFFIX as a
    # correlator — never the full key.
    logger.info(
        "seat_deactivated",
        ip=_client_ip(request),
        license_suffix=body.license_key[-6:],
        machine_id=body.machine_id,
    )


# ── Seat inspection ─────────────────────────────────────────────────
#
# The main app calls these to populate its Settings → License panel.
# They were missing before v0.20.2 — without them, every mount of the
# LicenseSection component produced a 404 and the UI retried on each
# render, flooding the toast stack. The endpoints are authenticated
# only by the caller's ability to present the license key (the key is
# the bearer token on this surface). To blunt abuse by anyone who learns
# a key, the seat surface is additionally throttled per-license (not just
# per-IP) and seat removals are audit-logged with the source IP. Full
# proof-of-possession (a signed license JWT on these calls) is a future
# coordinated client+server change — deployed clients send no JWT today.


class ActivationsListRequest(BaseModel):
    license_key: str = Field(min_length=8)


class ActivationsListEntry(BaseModel):
    machine_id: str
    first_seen: int | None = None
    last_heartbeat: int | None = None
    last_known_version: str | None = None


class ActivationsListResponse(BaseModel):
    tier: str
    cap: int
    activations: list[ActivationsListEntry]


@router.post(
    "/activations",
    response_model=ActivationsListResponse,
    dependencies=[Depends(rate_limit_ip(_activate_rl, prefix="activations"))],
)
async def list_seats(body: ActivationsListRequest) -> ActivationsListResponse:
    """Return the every-machine seat roster for a license key."""
    _seat_throttle(body.license_key)
    row = await db.get_license(body.license_key)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "license_not_found"},
        )
    cap = TIER_MACHINES.get(row["tier"], 1)
    raw = await db.list_activations(body.license_key)
    entries = [
        ActivationsListEntry(
            machine_id=str(a.get("machine_id") or ""),
            first_seen=a.get("first_seen"),
            last_heartbeat=a.get("last_heartbeat"),
            last_known_version=a.get("last_known_version"),
        )
        for a in raw
    ]
    return ActivationsListResponse(tier=row["tier"], cap=cap, activations=entries)


# Seat-freeing uses the existing ``/deactivate`` route — same payload
# shape (license_key + machine_id). No extra endpoint needed.
