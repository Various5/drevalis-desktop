"""Minimal email templates for transactional messages.

All HTML uses inline styles only — many email clients strip <style> blocks.
Keep the copy short and actionable.
"""

from __future__ import annotations

from datetime import datetime


def password_reset_html(
    *,
    user_email: str,
    reset_url: str,
    expires_at: datetime,
) -> str:
    """Return the HTML body for a password-reset email."""
    expiry_str = expires_at.strftime("%H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f0f0f;font-family:sans-serif;color:#e5e5e5;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:40px auto;">
    <tr>
      <td style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:36px 32px;">
        <p style="margin:0 0 4px;font-size:18px;font-weight:600;color:#ffffff;">
          Password reset
        </p>
        <p style="margin:0 0 24px;font-size:13px;color:#888;">
          Drevalis Creator Studio
        </p>
        <p style="font-size:14px;color:#ccc;margin:0 0 8px;">
          Someone requested a password reset for <strong style="color:#fff;">{user_email}</strong>.
          If that was you, click the button below.
        </p>
        <p style="font-size:13px;color:#888;margin:0 0 24px;">
          This link expires at {expiry_str} (60 minutes from the request).
        </p>
        <a href="{reset_url}"
           style="display:inline-block;background:#7c3aed;color:#fff;text-decoration:none;
                  font-size:14px;font-weight:600;padding:12px 28px;border-radius:6px;">
          Set new password
        </a>
        <p style="margin:24px 0 0;font-size:12px;color:#666;">
          If you did not request this, ignore this email — your password will not change.<br>
          Do not share this link with anyone.
        </p>
        <hr style="border:none;border-top:1px solid #2a2a2a;margin:24px 0;">
        <p style="font-size:11px;color:#555;margin:0;">
          If the button above does not work, copy and paste this URL into your browser:<br>
          <span style="color:#7c3aed;word-break:break-all;">{reset_url}</span>
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""


def password_reset_text(
    *,
    user_email: str,
    reset_url: str,
    expires_at: datetime,
) -> str:
    """Return the plain-text body for a password-reset email."""
    expiry_str = expires_at.strftime("%H:%M UTC")
    return (
        f"Password reset — Drevalis Creator Studio\n"
        f"{'=' * 48}\n\n"
        f"Someone requested a password reset for: {user_email}\n\n"
        f"If that was you, visit the link below to set a new password.\n"
        f"This link expires at {expiry_str} (60 minutes from the request).\n\n"
        f"{reset_url}\n\n"
        f"If you did not request this, ignore this email.\n"
        f"Your password will not change unless you follow the link above.\n\n"
        f"Do not share this link with anyone.\n"
    )
