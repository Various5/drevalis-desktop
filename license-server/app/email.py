"""Transactional email via Resend.

If ``RESEND_API_KEY`` is unset, calls become structured-log no-ops — useful
for local development and for graceful degradation during a Resend outage.
"""

from __future__ import annotations

import httpx
import structlog

from app.config import get_settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


async def send_license_key_email(
    *,
    to: str,
    license_key: str,
    tier: str,
    interval: str,
) -> None:
    """Email the user their newly issued license key."""
    settings = get_settings()
    if not settings.resend_api_key:
        logger.info(
            "email_skipped_no_resend_key",
            to=to,
            tier=tier,
            license_key_prefix=license_key[:8],
        )
        return

    subject = f"Your Drevalis Creator Studio {tier.title()} license"
    html = f"""<!doctype html>
<html><body style="font-family:Inter,system-ui,sans-serif;max-width:520px;margin:24px auto;color:#111">
  <h2 style="margin-top:0">Your license key</h2>
  <p>Thanks for subscribing to Creator Studio <b>{tier.title()}</b> ({interval}).</p>
  <p>Paste this key into the activation screen in your install:</p>
  <pre style="background:#f4f4f5;padding:12px;border-radius:8px;word-break:break-all;font-size:13px">{license_key}</pre>
  <p>If you lose this key, reply to this email and we'll re-send it.</p>
  <p style="color:#666;font-size:12px">
    Subscription can be managed at <a href="{settings.app_base_url}/account">{settings.app_base_url}/account</a>.
    <br/>— The Drevalis team
  </p>
</body></html>"""

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _RESEND_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from,
                "to": [to],
                "subject": subject,
                "html": html,
            },
        )
    if resp.status_code >= 400:
        logger.error(
            "email_send_failed",
            to=to,
            status=resp.status_code,
            body=resp.text[:300],
        )
    else:
        logger.info("email_sent", to=to, tier=tier)
