"""Environment-driven configuration.

Required secrets (set via Fly.io secrets in prod, ``.env`` file locally):

- ``LICENSE_PRIVATE_KEY_PEM``     : Ed25519 PEM contents (full PEM string).
- ``STRIPE_SECRET_KEY``           : ``sk_live_...`` or ``sk_test_...``.
- ``STRIPE_WEBHOOK_SECRET``       : ``whsec_...`` for signature verification.
- ``ADMIN_TOKEN``                 : Bearer token for ``/admin/*`` routes.

Optional:

- ``DATABASE_PATH``   (default ``/data/licenses.db``)
- ``RESEND_API_KEY``  (email delivery; log-only if unset)
- ``RESEND_FROM``     (default ``Drevalis <no-reply@drevalis.com>``)
- ``APP_BASE_URL``    (shown in emails and Checkout success URL)

Stripe price IDs per tier (create these in the Stripe dashboard and paste
the IDs here):

- ``STRIPE_PRICE_CREATOR_MONTHLY`` / ``STRIPE_PRICE_CREATOR_YEARLY``
  (``STRIPE_PRICE_SOLO_*`` kept as legacy alias for pre-rebrand customers)
- ``STRIPE_PRICE_PRO_MONTHLY``     / ``STRIPE_PRICE_PRO_YEARLY``
- ``STRIPE_PRICE_STUDIO_MONTHLY``  / ``STRIPE_PRICE_STUDIO_YEARLY``
- ``STRIPE_PRICE_LIFETIME_PRO``    one-time CHF 599 purchase
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # ── Signing ─────────────────────────────────────────────────────
    license_private_key_pem: str = Field(
        default="",
        description="Ed25519 private key, PEM-encoded (PKCS8). Required.",
    )

    # ── Stripe ──────────────────────────────────────────────────────
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # New "creator" naming (post-rebrand); solo_* kept as legacy alias.
    stripe_price_creator_monthly: str = ""
    stripe_price_creator_yearly: str = ""
    stripe_price_solo_monthly: str = ""
    stripe_price_solo_yearly: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""
    stripe_price_studio_monthly: str = ""
    stripe_price_studio_yearly: str = ""

    # Lifetime (one-time) — CHF 599, mode="payment".
    stripe_price_lifetime_pro: str = ""

    # Lifetime-tier update window (days from purchase during which updates
    # remain included). 3 years = 1095 days. Only used at issuance time —
    # the license itself never expires.
    lifetime_update_window_days: int = 1095

    # ── Admin ───────────────────────────────────────────────────────
    admin_token: str = ""

    # ── Storage ─────────────────────────────────────────────────────
    database_path: str = "/data/licenses.db"

    # ── Email ───────────────────────────────────────────────────────
    resend_api_key: str = ""
    resend_from: str = "Drevalis <no-reply@drevalis.com>"

    # ── App ─────────────────────────────────────────────────────────
    app_base_url: str = "https://drevalis.com"
    checkout_success_url: str = "https://drevalis.com/thank-you"
    checkout_cancel_url: str = "https://drevalis.com/pricing"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


def price_for(tier: str, interval: str) -> str:
    """Resolve a Stripe price ID from (tier, interval).

    Handles the creator/solo alias: "creator" falls back to the legacy
    STRIPE_PRICE_SOLO_* vars if STRIPE_PRICE_CREATOR_* is not configured,
    so existing installs keep working during the rename rollout.
    """
    s = get_settings()
    if tier == "lifetime_pro":
        return s.stripe_price_lifetime_pro
    key = f"stripe_price_{tier}_{interval}"
    value = getattr(s, key, "")
    if not value and tier == "creator":
        legacy = f"stripe_price_solo_{interval}"
        value = getattr(s, legacy, "")
    return value


def tier_for_price(price_id: str) -> tuple[str, str] | None:
    """Reverse lookup: Stripe price ID → (tier, interval).

    One-time lifetime purchases map to ("lifetime_pro", "once").
    """
    s = get_settings()
    if price_id and price_id == s.stripe_price_lifetime_pro:
        return "lifetime_pro", "once"
    for tier in ("creator", "solo", "pro", "studio"):
        for interval in ("monthly", "yearly"):
            if getattr(s, f"stripe_price_{tier}_{interval}", "") == price_id:
                # Normalize legacy "solo" back to canonical "creator" on reverse
                # lookup so licenses issued from legacy prices get the new name.
                canonical = "creator" if tier == "solo" else tier
                return canonical, interval
    return None
