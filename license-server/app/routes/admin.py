"""Bearer-protected admin endpoints.

No UI yet — curl against these from the owner's machine. A small HTML page
can be added later once the set of operations stabilises.

Auth: ``Authorization: Bearer <ADMIN_TOKEN>``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app import db
from app.config import get_settings
from app.crypto import mint_jwt, new_license_id
from app.email import send_license_key_email

router = APIRouter(prefix="/admin", tags=["admin"])


async def _require_admin(
    authorization: str | None = Header(default=None),
) -> None:
    import hmac as _hmac

    expected = get_settings().admin_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin token not configured",
        )
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    # Constant-time comparison — straight ``!=`` leaks the number of
    # matching prefix bytes via response timing. Byte-encoded inputs
    # because ``compare_digest`` on mismatched-length strings is still
    # safe but bytes is the recommended contract.
    provided = authorization.encode("utf-8")
    target = f"Bearer {expected}".encode()
    if not _hmac.compare_digest(provided, target):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@router.get("/licenses", dependencies=[Depends(_require_admin)])
async def list_licenses() -> list[dict]:
    return await db.list_licenses()


@router.get("/licenses/{license_id}", dependencies=[Depends(_require_admin)])
async def get_license(license_id: str) -> dict:
    row = await db.get_license(license_id)
    if row is None:
        raise HTTPException(status_code=404)
    row["activations"] = await db.list_activations(license_id)
    return row


@router.post("/licenses/{license_id}/revoke", dependencies=[Depends(_require_admin)])
async def revoke_license(license_id: str) -> dict:
    row = await db.get_license(license_id)
    if row is None:
        raise HTTPException(status_code=404)
    await db.revoke_license(license_id)
    return {"ok": True, "license_id": license_id}


class IssueRequest(BaseModel):
    tier: str
    interval: str = "monthly"
    email: str | None = None
    period_end_unix: int  # when this license's paid period ends
    send_email: bool = False


@router.post("/licenses/issue", dependencies=[Depends(_require_admin)])
async def issue_license(body: IssueRequest) -> dict:
    """Manually create a license row (no Stripe). Useful for comps, support
    cases, or bootstrapping before Stripe is fully configured."""
    license_id = new_license_id()
    await db.create_license(
        license_id=license_id,
        stripe_customer=None,
        stripe_subscription=None,
        email=body.email,
        tier=body.tier,
        interval=body.interval,
        period_end=body.period_end_unix,
    )
    if body.send_email and body.email:
        await send_license_key_email(
            to=body.email,
            license_key=license_id,
            tier=body.tier,
            interval=body.interval,
        )
    return {"license_id": license_id, "tier": body.tier, "period_end": body.period_end_unix}


class PreviewJwtRequest(BaseModel):
    license_id: str
    machine_id: str = "admin-preview"


@router.post("/licenses/preview-jwt", dependencies=[Depends(_require_admin)])
async def preview_jwt(body: PreviewJwtRequest) -> dict:
    """Mint a JWT for an existing license without recording an activation.
    Admin-only; lets the owner hand out a JWT directly if email delivery
    failed."""
    row = await db.get_license(body.license_id)
    if row is None:
        raise HTTPException(status_code=404)
    token = mint_jwt(
        license_id=row["id"],
        customer=row["stripe_customer"] or row.get("email") or row["id"],
        tier=row["tier"],
        period_end_unix=row["period_end"],
    )
    return {"license_jwt": token}
