"""Team / user management service.

Owns password hashing, session token minting, and the one piece of
bootstrap magic: if the install has zero users AND ``OWNER_EMAIL`` +
``OWNER_PASSWORD`` env vars are set, create the initial owner account
automatically on first request. That keeps the "I just installed
Drevalis, how do I log in" path friction-free while still leaving
team mode opt-in for creators who don't want any auth.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.user import User

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ── Password hashing ───────────────────────────────────────────────────
#
# We use stdlib-only PBKDF2-HMAC-SHA256 so there's no new dependency on
# bcrypt or argon2. 480k iterations matches OWASP 2023 guidance and
# takes ~150ms on commodity x86. The stored format is::
#
#     pbkdf2_sha256$<iterations>$<salt-b64>$<hash-b64>
#
# Re-hash on login if the iteration count has drifted from the current
# constant — simple forward-compat for when we bump it.

_PBKDF2_ITERATIONS = 480_000
_PBKDF2_DIGEST = "sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac(_PBKDF2_DIGEST, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return (
        f"pbkdf2_sha256${_PBKDF2_ITERATIONS}"
        f"${base64.urlsafe_b64encode(salt).decode().rstrip('=')}"
        f"${base64.urlsafe_b64encode(hashed).decode().rstrip('=')}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
    except (ValueError, AttributeError):
        return False

    salt = base64.urlsafe_b64decode(_pad_b64(salt_b64))
    expected = base64.urlsafe_b64decode(_pad_b64(hash_b64))
    candidate = hashlib.pbkdf2_hmac(_PBKDF2_DIGEST, password.encode("utf-8"), salt, iters)
    return hmac.compare_digest(candidate, expected)


def _pad_b64(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return (s + padding).encode("ascii")


# ── Session tokens ─────────────────────────────────────────────────────
#
# Tokens are HMAC-SHA256-signed JSON payloads: we don't need server-
# side session storage, and the app already has an encryption key we
# can key the HMAC off. Format: base64url(payload) + '.' +
# base64url(hmac). Caller supplies the key; this module doesn't
# reach for ``Settings`` directly so it's easy to unit-test.


_SESSION_TTL = timedelta(days=14)


def mint_session_token(*, user_id: UUID, role: str, secret: str, session_version: int = 0) -> str:
    """Return a signed session token.

    The ``sv`` (session-version) claim is embedded so that
    ``_current_user`` can reject tokens minted before a
    ``logout-everywhere`` call incremented the counter.
    """
    payload: dict[str, int | str] = {
        "uid": str(user_id),
        "role": role,
        "exp": int((datetime.now(tz=UTC) + _SESSION_TTL).timestamp()),
        "sv": session_version,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = _sign(body, secret)
    return f"{body}.{sig}"


def parse_session_token(token: str, *, secret: str) -> dict[str, int | str] | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(body, secret)):
        return None
    try:
        raw = base64.urlsafe_b64decode(_pad_b64(body)).decode()
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    if int(payload.get("exp", 0)) < int(datetime.now(tz=UTC).timestamp()):
        return None
    assert isinstance(payload, dict)
    return payload


def _sign(body: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


# ── Bootstrap ─────────────────────────────────────────────────────────


async def ensure_owner_from_env(session: AsyncSession) -> User | None:
    """Create the first owner account from ``OWNER_EMAIL`` + ``OWNER_PASSWORD``
    env vars if the users table is empty. No-op otherwise."""
    count = await session.execute(select(func.count()).select_from(User))
    if (count.scalar_one() or 0) > 0:
        return None
    email = (os.environ.get("OWNER_EMAIL") or "").strip().lower()
    password = os.environ.get("OWNER_PASSWORD") or ""
    if not email or not password:
        return None
    user = User(
        email=email,
        password_hash=hash_password(password),
        role="owner",
        display_name=email.split("@")[0].title(),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    logger.info("team.owner_bootstrapped", email=email)
    return user
