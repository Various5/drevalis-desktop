"""Stripe Checkout session creation (public endpoint)."""

from __future__ import annotations

from typing import Literal

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.config import get_settings, price_for
from app.rate_limit import RateLimiter, rate_limit_ip

router = APIRouter(tags=["public"])

# 20 / IP / minute. Checkout creates a Stripe session — each call is a
# real Stripe API hit we're billed for. Pile-ons past this are either
# a mistake or an attack.
_checkout_rl = RateLimiter(capacity=20, refill_per_second=20 / 60)


class CheckoutRequest(BaseModel):
    # "solo" retained as a back-compat alias for pages that still post the
    # old name; the webhook + price lookup normalize it to "creator".
    tier: Literal["creator", "solo", "pro", "studio", "lifetime_pro"]
    interval: Literal["monthly", "yearly", "once"]
    email: EmailStr | None = None


class CheckoutResponse(BaseModel):
    url: str
    session_id: str


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    dependencies=[Depends(rate_limit_ip(_checkout_rl, prefix="checkout"))],
)
async def create_checkout(body: CheckoutRequest) -> CheckoutResponse:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe not configured",
        )
    price_id = price_for(body.tier, body.interval)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No price configured for {body.tier}/{body.interval}",
        )

    stripe.api_key = settings.stripe_secret_key

    # Normalize the "solo" legacy tier name to "creator" in metadata so
    # the webhook always sees a single canonical tier string going forward.
    canonical_tier = "creator" if body.tier == "solo" else body.tier

    is_lifetime = body.tier == "lifetime_pro"
    mode: Literal["subscription", "payment"] = "payment" if is_lifetime else "subscription"
    kwargs: dict[str, object] = {
        "mode": mode,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": settings.checkout_success_url,
        "cancel_url": settings.checkout_cancel_url,
        "customer_email": body.email,
        "allow_promotion_codes": True,
        "metadata": {"tier": canonical_tier, "interval": body.interval},
    }
    if mode == "subscription":
        # Stripe only accepts subscription_data on subscription-mode sessions.
        kwargs["subscription_data"] = {
            "metadata": {"tier": canonical_tier, "interval": body.interval},
        }
    else:
        # Capture tier on the PaymentIntent metadata too, so the webhook
        # can survive Stripe shape churn.
        kwargs["payment_intent_data"] = {
            "metadata": {"tier": canonical_tier, "interval": body.interval},
        }

    session = stripe.checkout.Session.create(**kwargs)
    return CheckoutResponse(url=session.url or "", session_id=session.id)
