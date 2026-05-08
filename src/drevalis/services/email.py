"""Async email delivery via stdlib smtplib (no new dependency).

Public API
----------
``send_email`` — send a transactional email.  Returns True on success,
False on any error.  Never raises — callers can fire-and-forget.

Security notes
--------------
* Recipient is masked in all log output (j**@example.com) so mail
  addresses never appear in structured logs (CWE-359).
* SMTP credentials are read from Settings; they are never logged.
* Returns False silently when SMTP is not configured — the endpoint
  behaviour is unchanged (CWE-209, no information leakage).
"""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from drevalis.core.config import Settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _mask_email(address: str) -> str:
    """Return a masked version of *address*, e.g. ``j**@example.com``.

    Keeps the first character of the local part and the full domain so
    the log entry is still useful for debugging without exposing the
    full address.
    """
    if "@" not in address:
        return "***"
    local, domain = address.split("@", 1)
    return f"{local[:1]}**@{domain}"


def _send_sync(
    *,
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    use_tls: bool,
    from_addr: str,
    to_addr: str,
    subject: str,
    html: str,
    text: str,
) -> None:
    """Blocking SMTP send — intended to be called via asyncio.to_thread."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    if use_tls:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        smtp = smtplib.SMTP(host, port, timeout=15)

    with smtp:
        if not use_tls:
            smtp.ehlo()
            try:
                smtp.starttls()
                smtp.ehlo()
            except smtplib.SMTPException:
                pass  # server doesn't support STARTTLS — proceed plaintext
        if username and password:
            smtp.login(username, password)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())


async def send_email(
    *,
    settings: Settings,
    to: str,
    subject: str,
    html: str,
    text: str,
) -> bool:
    """Send a transactional email.

    Returns True on success, False on any error (including SMTP not
    configured).  Never raises.

    Recipient address is masked in all log events so it never appears
    in structured logs.

    CWE-359 (Exposure of Private Information): masked logging.
    CWE-209 (Information Exposure Through Error Messages): errors logged
    server-side only; callers receive a bool, not an exception.
    """
    masked = _mask_email(to)

    # ── Guard: SMTP not configured ─────────────────────────────────────
    if not settings.smtp_host:
        logger.warning(
            "email.send_skipped",
            reason="smtp_host_not_configured",
            recipient=masked,
        )
        return False

    from_addr = settings.smtp_from or settings.smtp_username
    if not from_addr:
        logger.warning(
            "email.send_skipped",
            reason="smtp_from_not_configured",
            recipient=masked,
        )
        return False

    # ── Send ────────────────────────────────────────────────────────────
    try:
        await asyncio.to_thread(
            _send_sync,
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            from_addr=from_addr,
            to_addr=to,
            subject=subject,
            html=html,
            text=text,
        )
    except Exception:  # noqa: BLE001
        logger.warning("email.send_failed", recipient=masked, exc_info=True)
        return False

    logger.info("email.send_success", recipient=masked)
    return True
