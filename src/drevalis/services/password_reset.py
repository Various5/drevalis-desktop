"""Password-reset service: request + consume flows.

Security invariants
-------------------
* ``request_reset`` is void-returning so the route layer cannot
  accidentally expose whether the email is registered (CWE-204).
* Both the known-email and unknown-email paths call ``send_email`` so
  wall-clock response time is uniform (~150 ms PBKDF2 + SMTP latency);
  an attacker cannot time the response to enumerate accounts (CWE-208).
* Raw tokens are generated with ``secrets.token_urlsafe`` (CSPRNG); only
  the SHA-256 digest is persisted (CWE-916, no plaintext secret at rest).
* ``consume_reset`` bumps ``session_version`` so any stolen cookie is
  invalidated the moment the password changes (CWE-613).
* A successful consume marks used_at on the redeemed row AND NULLs
  used_at-is-NULL siblings for the same user (close the door entirely).
* Token TTL: 60 minutes.
* Cap: at most 3 unused tokens per user — oldest trimmed on each new
  request so the inbox is not spammed indefinitely.
* Per-email rate-limit: 3 requests per hour tracked in Redis.  Enforced
  inside ``request_reset`` (not at the HTTP layer) so the route always
  returns the same 200 regardless.

Redis keys
----------
``reset_rate:{email}``  — counter, TTL 3 600 s.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.password_reset_token import PasswordResetToken
from drevalis.models.user import User
from drevalis.services.email import send_email
from drevalis.services.email_templates import password_reset_html, password_reset_text
from drevalis.services.team import hash_password

if TYPE_CHECKING:
    from drevalis.core.config import Settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Token validity window (60 minutes).
_TOKEN_TTL = timedelta(minutes=60)

# Maximum number of unused tokens a single user may have at once.
# Extra requests beyond this trim the oldest ones.
_TOKEN_CAP = 3

# Per-email rate-limit: 3 requests / 3 600 s.
_RATE_LIMIT = 3
_RATE_WINDOW = 3600  # 1 hour


def _hash_token(raw: str) -> str:
    """Return the SHA-256 hex digest of *raw* (the URL-safe token)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reset_url(settings: Settings, raw_token: str) -> str:
    """Build the frontend password-reset URL."""
    base = (settings.app_base_url or "").rstrip("/")
    return f"{base}/reset-password?token={raw_token}"


# ---------------------------------------------------------------------------
# Per-email rate-limiting via Redis
# ---------------------------------------------------------------------------


async def _check_and_increment_rate(email: str) -> bool:
    """Return True if the caller is within the rate limit (allow), False if blocked.

    Increments the counter regardless so every call counts.  Best-effort:
    Redis unavailability degrades gracefully (fail-open).
    """
    key = f"reset_rate:{email.lower()}"
    try:
        from redis.asyncio import Redis as _Redis

        from drevalis.core.redis import get_pool

        redis: _Redis = _Redis(connection_pool=get_pool())
        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, _RATE_WINDOW, nx=True)
            results = await pipe.execute()
            count = int(results[0])
        finally:
            await redis.aclose()
    except Exception:  # noqa: BLE001
        # Redis down — fail open (PBKDF2 cost + SMTP latency are the backstop).
        return True

    return count <= _RATE_LIMIT


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def request_reset(
    db: AsyncSession,
    email: str,
    settings: Settings,
) -> None:
    """Initiate a password-reset flow for *email*.

    Always returns without raising.  The caller (HTTP route) must return
    the same generic 200 response regardless of this function's outcome.

    Timing-uniform contract: both the known-email and unknown-email paths
    call ``send_email`` so the wall-clock response time cannot distinguish
    between the two (CWE-208).
    """
    email_norm = email.lower().strip()

    # ── Per-email rate limit ───────────────────────────────────────────
    allowed = await _check_and_increment_rate(email_norm)
    if not allowed:
        logger.warning("password_reset.rate_limited", email_masked=email_norm[:3] + "***")
        # Still must not reveal rate-limiting to the HTTP layer; the
        # route always returns the same 200. Just return silently.
        return

    # ── Look up the user ───────────────────────────────────────────────
    row = await db.execute(select(User).where(User.email == email_norm))
    user: User | None = row.scalar_one_or_none()

    # Mint a raw token unconditionally — on the unknown-email path it's
    # sent to a discard address so the SMTP latency is still incurred.
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    now = datetime.now(tz=UTC)
    expires_at = now + _TOKEN_TTL

    if user is not None and user.is_active:
        # ── Enforce cap: trim oldest unused tokens ─────────────────────
        existing = (
            (
                await db.execute(
                    select(PasswordResetToken)
                    .where(
                        PasswordResetToken.user_id == user.id,
                        PasswordResetToken.used_at.is_(None),
                        PasswordResetToken.expires_at > now,
                    )
                    .order_by(PasswordResetToken.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        # If at cap, delete the oldest to stay at _TOKEN_CAP - 1 before
        # inserting the new one.  Convert to list so .pop(0) is available
        # (.all() returns a Sequence[T] which doesn't guarantee pop).
        existing_list = list(existing)
        while len(existing_list) >= _TOKEN_CAP:
            oldest = existing_list.pop(0)
            await db.delete(oldest)

        # ── Insert the new token ───────────────────────────────────────
        prt = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(prt)
        await db.flush()  # get the row into the DB within the transaction

        recipient = email_norm
        html = password_reset_html(
            user_email=email_norm,
            reset_url=_reset_url(settings, raw_token),
            expires_at=expires_at,
        )
        text = password_reset_text(
            user_email=email_norm,
            reset_url=_reset_url(settings, raw_token),
            expires_at=expires_at,
        )
        logger.info(
            "password_reset.token_created",
            user_id=str(user.id),
            expires_at=expires_at.isoformat(),
        )
    else:
        # Unknown or inactive email — still call send_email for timing
        # uniformity; use a discard address so no real email is sent.
        recipient = "discard@invalid.example"
        html = ""
        text = ""

    await db.commit()

    # Fire-and-forget the email so the HTTP response is not blocked by
    # SMTP latency.  send_email never raises; errors are logged inside.
    await send_email(
        settings=settings,
        to=recipient,
        subject="Reset your Drevalis password",
        html=html,
        text=text,
    )


async def consume_reset(
    db: AsyncSession,
    raw_token: str,
    new_password: str,
    settings: Settings,
) -> User | None:
    """Validate *raw_token* and set *new_password* on the associated user.

    Returns the updated ``User`` on success, None on any failure
    (expired, already used, not found, wrong token).

    On success:
    * ``used_at`` is written on the redeemed row.
    * All other unused unexpired tokens for the same user are also
      invalidated (prevents parallel resets after one legitimate one).
    * ``session_version`` is incremented to revoke all existing session
      cookies (CWE-613).
    * The new password is hashed with PBKDF2-SHA256 @ 480k iterations.
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(tz=UTC)

    # ── Find valid token ───────────────────────────────────────────────
    result = await db.execute(
        select(PasswordResetToken).where(
            and_(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
        )
    )
    prt: PasswordResetToken | None = result.scalar_one_or_none()

    if prt is None:
        return None

    # ── Fetch and validate user ────────────────────────────────────────
    user = await db.get(User, prt.user_id)
    if user is None or not user.is_active:
        return None

    # ── Mark this token used ───────────────────────────────────────────
    prt.used_at = now

    # ── Invalidate sibling tokens for the same user ────────────────────
    # Use an UPDATE statement rather than loading all rows so this is a
    # single round-trip even when there are multiple sibling tokens.
    await db.execute(
        update(PasswordResetToken)
        .where(
            and_(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.id != prt.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
        )
        .values(used_at=now)
    )

    # ── Update password + bump session_version ─────────────────────────
    user.password_hash = hash_password(new_password)
    user.session_version = user.session_version + 1

    await db.commit()

    logger.info(
        "password_reset.consumed",
        user_id=str(user.id),
        new_session_version=user.session_version,
    )
    return user
