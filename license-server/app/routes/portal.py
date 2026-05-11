"""Stripe Customer Portal session creation.

Given a valid, active license key, returns a URL that takes the customer to
Stripe's hosted billing portal. From there they can upgrade/downgrade the
subscription, update their payment method, view invoices, or cancel.

No access-control beyond "you know the license key" — that UUID is the
customer's login. It's the same key they paste into the app to activate.
"""

from __future__ import annotations

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app import db
from app.config import get_settings
from app.rate_limit import RateLimiter, rate_limit_ip

router = APIRouter(tags=["public"])

# 20 / IP / minute. Portal endpoint leaks the existence of a license
# key if abused at volume (see audit finding H-2); throttling tightens
# that enumeration surface.
_portal_rl = RateLimiter(capacity=20, refill_per_second=20 / 60)


class PortalRequest(BaseModel):
    license_key: str = Field(min_length=8)


class PortalResponse(BaseModel):
    url: str


@router.post(
    "/portal",
    response_model=PortalResponse,
    dependencies=[Depends(rate_limit_ip(_portal_rl, prefix="portal"))],
)
async def create_portal(body: PortalRequest) -> PortalResponse:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe not configured",
        )

    row = await db.get_license(body.license_key)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "license_not_found"},
        )
    customer_id = row.get("stripe_customer")
    if not customer_id:
        # Manually-issued / comp licenses have no Stripe customer. Nothing
        # for the billing portal to show.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_stripe_customer", "hint": "This license was issued manually and has no Stripe subscription to manage. Contact support."},
        )

    stripe.api_key = settings.stripe_secret_key

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=settings.app_base_url + "/account",
    )
    return PortalResponse(url=session.url or "")
