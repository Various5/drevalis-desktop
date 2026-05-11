"""Stripe webhook handler.

Handles the subset of events needed for license lifecycle:

- ``checkout.session.completed``    → create a new license + email the key
- ``customer.subscription.updated`` → bump ``period_end``; un-revoke on reactivation
- ``customer.subscription.deleted`` → revoke license (user cancelled / expired)
- ``charge.refunded``               → revoke license (disputed charge)

Idempotency: each event ID is recorded in ``webhook_events`` on first
process. Duplicate deliveries short-circuit.
"""

from __future__ import annotations

import json
import time

import stripe
import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status

from app import db
from app.config import get_settings
from app.crypto import new_license_id
from app.email import send_license_key_email

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["stripe"])


def _as_dict(obj) -> dict:
    """Coerce a Stripe SDK object (or anything JSON-serialisable) to plain dict.

    Stripe SDK 15 dropped ``.get()`` from ``StripeObject`` and changed how
    ``to_dict_recursive`` behaves. Multiple fallbacks so this code survives
    further SDK churn:

    1. plain dict → copy
    2. ``to_dict_recursive`` if present (older SDKs)
    3. JSON round-trip via ``str(obj)`` — Stripe objects serialize as JSON
    4. dict-comprehension over iteration
    """
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "to_dict_recursive"):
        try:
            result = obj.to_dict_recursive()
            if result:
                return result
        except Exception:
            pass
    try:
        return json.loads(str(obj))
    except Exception:
        pass
    try:
        return {k: obj[k] for k in obj}
    except Exception:
        return {}


def _subscription_period_end(sub) -> int:
    """Stripe moved ``current_period_end`` off the Subscription object and
    onto the SubscriptionItem in the 2025 API version. Read from both so the
    code works across SDK upgrades."""
    d = _as_dict(sub)
    val = d.get("current_period_end")
    if val is None:
        try:
            val = d["items"]["data"][0]["current_period_end"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("subscription has no current_period_end in either shape")
    return int(val)


async def _handle_checkout_completed(event: dict) -> None:
    session = _as_dict(event["data"]["object"])
    customer = session.get("customer")
    subscription = session.get("subscription")
    email = (session.get("customer_details") or {}).get("email") or session.get("customer_email")
    metadata = session.get("metadata") or {}
    tier = metadata.get("tier") or "creator"
    # Normalize legacy "solo" metadata (from cached sessions issued before
    # the rebrand) to the canonical "creator" name.
    if tier == "solo":
        tier = "creator"
    interval = metadata.get("interval") or "monthly"
    mode = session.get("mode")

    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key

    # One-time payment path: used for Lifetime (Pro). No subscription; the
    # license never expires and carries an ``update_window_expires_at``
    # stamp so the client can tell the user when free updates end.
    if mode == "payment":
        existing = await db.get_lifetime_license_by_customer(customer) if customer else None
        now = int(time.time())
        if existing:
            logger.info(
                "lifetime_license_already_exists",
                license_id=existing["id"],
                customer=customer,
            )
            return
        license_id = new_license_id()
        update_window_expires_at = now + settings.lifetime_update_window_days * 24 * 3600
        await db.create_license(
            license_id=license_id,
            stripe_customer=customer,
            stripe_subscription=None,
            email=email,
            tier="lifetime_pro",
            interval="once",
            # ``period_end`` is required NOT NULL. For a lifetime license
            # the JWT sets ``exp`` independently; store a sentinel 100y
            # stamp here so any query that inspects period_end still works.
            period_end=now + 100 * 365 * 24 * 3600,
            license_type="lifetime_pro",
            update_window_expires_at=update_window_expires_at,
        )
        logger.info(
            "lifetime_license_created",
            license_id=license_id,
            customer=customer,
        )
        if email:
            await send_license_key_email(
                to=email,
                license_key=license_id,
                tier="lifetime_pro",
                interval="once",
            )
        return

    # Subscription path (Creator / Pro / Studio monthly & yearly).
    if not subscription:
        logger.warning("checkout_completed_no_subscription", session_id=session.get("id"))
        return
    sub = stripe.Subscription.retrieve(subscription)
    period_end = _subscription_period_end(sub)

    # If a license already exists for this subscription (re-delivery after a
    # previous failure), just update it instead of creating a duplicate.
    existing = await db.get_license_by_subscription(subscription)
    if existing:
        await db.update_license_period_end(existing["id"], period_end)
        license_id = existing["id"]
        logger.info("license_refreshed", license_id=license_id, subscription=subscription)
    else:
        license_id = new_license_id()
        await db.create_license(
            license_id=license_id,
            stripe_customer=customer,
            stripe_subscription=subscription,
            email=email,
            tier=tier,
            interval=interval,
            period_end=period_end,
        )
        logger.info(
            "license_created",
            license_id=license_id,
            customer=customer,
            tier=tier,
        )
        if email:
            await send_license_key_email(
                to=email, license_key=license_id, tier=tier, interval=interval
            )


async def _handle_subscription_updated(event: dict) -> None:
    sub = _as_dict(event["data"]["object"])
    license_row = await db.get_license_by_subscription(sub["id"])
    if license_row is None:
        logger.warning("subscription_updated_no_license", subscription=sub["id"])
        return
    status_name = sub.get("status")
    if status_name in ("active", "trialing", "past_due"):
        await db.update_license_period_end(license_row["id"], _subscription_period_end(sub))
    elif status_name in ("canceled", "incomplete_expired", "unpaid"):
        await db.revoke_license(license_row["id"])
        logger.info("license_revoked_via_subscription", license_id=license_row["id"])


async def _handle_subscription_deleted(event: dict) -> None:
    sub = _as_dict(event["data"]["object"])
    license_row = await db.get_license_by_subscription(sub["id"])
    if license_row is None:
        return
    await db.revoke_license(license_row["id"])
    logger.info("license_revoked_subscription_deleted", license_id=license_row["id"])


async def _handle_charge_refunded(event: dict) -> None:
    """Revoke the specific license whose subscription was refunded.

    The previous implementation revoked **every** active license for
    the Stripe customer when any single charge was refunded — a
    partial refund on one seat killed every other seat the same
    customer owned. Scope to the ``subscription`` on the charge (or
    the invoice's subscription) and revoke only that license.
    """
    charge = _as_dict(event["data"]["object"])
    customer = charge.get("customer")
    if not customer:
        return

    # Preferred path: charge has an explicit ``invoice`` / ``subscription``.
    subscription_id = charge.get("subscription")
    if not subscription_id:
        invoice = charge.get("invoice")
        if isinstance(invoice, dict):
            subscription_id = invoice.get("subscription")
        # Some Stripe webhook shapes embed the invoice as an id string;
        # we can't dereference those synchronously without a Stripe call,
        # so fall through to the customer-scoped guard below.

    if subscription_id:
        license_row = await db.get_license_by_subscription(subscription_id)
        if license_row and license_row["status"] == "active":
            await db.revoke_license(license_row["id"])
            logger.info(
                "license_revoked_charge_refunded",
                license_id=license_row["id"],
                subscription_id=subscription_id,
            )
        return

    # Fallback: no subscription on the charge. Only revoke if the
    # customer owns a *single* active license — otherwise we'd be
    # re-introducing the original bug by guessing which license the
    # refund applied to.
    active = [
        row
        for row in await db.list_licenses(limit=10000)
        if row.get("stripe_customer") == customer and row["status"] == "active"
    ]
    if len(active) == 1:
        await db.revoke_license(active[0]["id"])
        logger.info(
            "license_revoked_charge_refunded_sole_license",
            license_id=active[0]["id"],
        )
    else:
        logger.warning(
            "charge_refund_could_not_scope_to_license",
            customer=customer,
            active_count=len(active),
        )


_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "charge.refunded": _handle_charge_refunded,
}


@router.post("/webhook/stripe", status_code=200)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook secret not configured",
        )

    payload = await request.body()
    try:
        # ``Webhook.construct_event`` is the only signature-check path that
        # reliably auto-decodes bytes→str across Stripe SDK versions. We
        # throw away its StripeObject return value and re-parse the raw
        # bytes with ``json.loads`` — StripeObject's dict semantics have
        # churned (no ``.get()`` in SDK 15), and a plain dict is all the
        # downstream handlers need.
        stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature or "",
            secret=settings.stripe_webhook_secret,
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        logger.warning("webhook_signature_invalid", error=str(exc)[:120])
        raise HTTPException(status_code=400, detail="signature_invalid") from exc

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        logger.warning("webhook_body_not_json", error=str(exc)[:120])
        raise HTTPException(status_code=400, detail="body_not_json") from exc

    event_id = event.get("id") or ""
    if not await db.mark_webhook_processed(event_id):
        logger.info("webhook_duplicate", event_id=event_id, type=event.get("type"))
        return {"received": True, "duplicate": True}

    handler = _HANDLERS.get(event.get("type"))
    if handler is None:
        logger.debug("webhook_ignored", event_id=event_id, type=event.get("type"))
        return {"received": True, "ignored": True}

    try:
        await handler(event)
    except Exception:
        logger.exception("webhook_handler_failed", event_id=event_id, type=event.get("type"))
        # Un-mark so the next Stripe retry actually re-enters the
        # handler instead of short-circuiting as a duplicate — otherwise
        # the first transient failure on ``subscription.updated`` /
        # ``deleted`` permanently loses the state transition.
        await db.unmark_webhook_processed(event_id)
        raise HTTPException(status_code=500, detail="handler_failed")

    return {"received": True}
