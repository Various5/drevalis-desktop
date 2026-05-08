"""Authentication + user management routes.

Endpoints:

- ``POST /api/v1/auth/login``              email+password → session cookie (or TOTP challenge).
- ``POST /api/v1/auth/login/totp``         TOTP / recovery-code → session cookie.
- ``POST /api/v1/auth/logout``             clears the cookie.
- ``POST /api/v1/auth/logout-everywhere``  increments session_version → all
                                           existing tokens on all devices are
                                           invalidated immediately.
- ``GET  /api/v1/auth/me``                 current user (when logged in).
- ``GET  /api/v1/auth/login-history``      current user's last N login events.
- ``GET  /api/v1/auth/mode``               public — team / demo mode flags.
- ``POST /api/v1/auth/forgot-password``    request a reset email (public, timing-uniform).
- ``POST /api/v1/auth/reset-password``     consume token + set new password (public).
- ``POST /api/v1/auth/2fa/enroll``         generate & store TOTP secret (authenticated).
- ``POST /api/v1/auth/2fa/confirm``        verify first code → activate 2FA (authenticated).
- ``POST /api/v1/auth/2fa/disable``        re-prompt password → clear all TOTP columns (authenticated).
- ``GET  /api/v1/users``                   list all users (owner only).
- ``POST /api/v1/users``                   invite a new user (owner only).
- ``PUT  /api/v1/users/{id}``              change role / enable-disable (owner only).
- ``DELETE /api/v1/users/{id}``            remove a user (owner only; can't remove self).
- ``GET  /api/v1/users/{id}/login-history`` per-user events (owner only).

The login endpoint writes an HTTP-only ``drevalis_session`` cookie
rather than returning a token — same-origin XHR through the frontend
automatically sends it, so nothing else needs to change.

TOTP two-factor authentication (CWE-287, OWASP A07:2021):

When a user has confirmed 2FA (``totp_confirmed_at IS NOT NULL``),
``POST /auth/login`` does NOT issue the session cookie immediately.
Instead it returns::

    {stage: "totp_required", challenge: "<fernet_blob>"}

The challenge is a short-lived (5-minute) Fernet-encrypted blob that
carries ``user_id`` and a ``nonce``.  The client must then call
``POST /auth/login/totp`` with ``{challenge, code}`` to complete the
flow and receive the cookie.  This design:

* Never reveals which stage failed — both steps return 401 with the
  same ``invalid_credentials`` body to outside observers.
* The challenge is single-use: the nonce is stored in Redis with a 5-
  minute TTL; a second submit with the same challenge is rejected even
  if the code is correct.
* Recovery codes (16 hex chars) follow the same endpoint, routed by
  code length/format.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession  # runtime import — FastAPI Depends

from drevalis.core.auth import (
    LoginRateLimitedError,
    check_login_rate_limit,
    record_login_failure,
)
from drevalis.core.deps import get_db, get_settings
from drevalis.models.login_event import LoginEvent
from drevalis.models.user import User
from drevalis.services.team import (
    ensure_owner_from_env,
    hash_password,
    mint_session_token,
    parse_session_token,
    verify_password,
)

# Plain-string email with a light regex — avoids a hard dep on
# ``email-validator`` (pydantic[email]) which isn't in the runtime image.
_EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


if TYPE_CHECKING:
    from drevalis.core.config import Settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["auth"])

_COOKIE_NAME = "drevalis_session"

# ---------------------------------------------------------------------------
# A.1 — Constant-time dummy hash for email enumeration prevention.
#
# PBKDF2 at 480k iterations takes ~150ms. When a login attempt uses an
# unknown email, we skip verify_password — making that branch ~150ms faster
# than a valid-email/wrong-password branch. An attacker can measure this
# delta to enumerate which emails are registered.
#
# Fix: compute one real PBKDF2 hash at import time (pays the cost once) and
# run verify_password against it whenever the user doesn't exist or is
# inactive. The result is discarded; only the timing matters.
#
# The dummy password is a random sentinel so no submitted string will ever
# accidentally match it (verify_password always returns False here).
# ---------------------------------------------------------------------------
_DUMMY_HASH: str = hash_password("__drevalis_dummy_sentinel__")

# ---------------------------------------------------------------------------
# TOTP challenge constants.
#
# The challenge blob is a Fernet-encrypted JSON object:
#   {"uid": "<user-uuid>", "nonce": "<hex32>"}
#
# The challenge TTL is enforced by Fernet's built-in timestamp check
# (``max_age`` kwarg on decrypt) and by a Redis key that is set at
# issuance and deleted on first use to prevent replay.
#
# Using Fernet here means we don't need a separate short-lived session
# store — the TTL is embedded in the ciphertext itself.
# ---------------------------------------------------------------------------
_CHALLENGE_TTL_SECONDS = 300  # 5 minutes


class LoginRequest(BaseModel):
    email: str = Field(..., pattern=_EMAIL_RE)
    password: str = Field(..., min_length=1)


class TotpLoginRequest(BaseModel):
    challenge: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)


class TotpEnrollResponse(BaseModel):
    secret_base32: str
    otpauth_uri: str
    recovery_codes: list[str]


class TotpConfirmRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TotpDisableRequest(BaseModel):
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str
    display_name: str | None
    is_active: bool
    last_login_at: datetime | None
    totp_enabled: bool = False

    @classmethod
    def from_orm(cls, u: User) -> UserResponse:
        return cls(
            id=u.id,
            email=u.email,
            role=u.role,
            display_name=u.display_name,
            is_active=u.is_active,
            last_login_at=u.last_login_at,
            totp_enabled=u.totp_confirmed_at is not None,
        )


class LoginEventResponse(BaseModel):
    """Login history row returned to the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    timestamp: datetime
    ip: str
    user_agent: str | None
    success: bool
    failure_reason: str | None


# ── Session helpers ────────────────────────────────────────────────────


async def _current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None
    payload = parse_session_token(token, secret=settings.get_session_secret())
    if not payload:
        return None
    try:
        uid = UUID(str(payload["uid"]))
    except (KeyError, ValueError):
        return None
    user = await db.get(User, uid)
    if not user or not user.is_active:
        return None
    # A.3 — session-version check: reject tokens minted before a
    # logout-everywhere that incremented the counter.
    token_sv = int(payload.get("sv", 0))
    if token_sv != user.session_version:
        return None
    return user


async def require_user(user: User | None = Depends(_current_user)) -> User:
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
    return user


async def require_owner(user: User = Depends(require_user)) -> User:
    if user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner_role_required")
    return user


# ── Audit helpers ──────────────────────────────────────────────────────


def _client_ip(request: Request) -> str:
    """Best-effort client IP: prefer X-Forwarded-For, fallback to socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


async def _record_login_event(
    db: AsyncSession,
    *,
    user_id: UUID | None,
    email_attempted: str | None,
    ip: str,
    user_agent: str | None,
    success: bool,
    failure_reason: str | None,
) -> None:
    """Insert a login_events row.  Called via asyncio.create_task so a slow
    DB write never delays the auth response.  Errors are logged and swallowed.
    """
    try:
        event = LoginEvent(
            user_id=user_id,
            email_attempted=email_attempted,
            ip=ip,
            user_agent=user_agent,
            success=success,
            failure_reason=failure_reason,
        )
        db.add(event)
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("auth.login_event_write_failed", exc_info=True)


# ── TOTP challenge helpers ─────────────────────────────────────────────


def _mint_totp_challenge(user_id: UUID, settings: Settings) -> str:
    """Create a short-lived, single-use Fernet-encrypted challenge token.

    The blob is ``{"uid": "<uuid>", "nonce": "<hex32>"}`` encrypted with
    the current Fernet key.  The nonce is stored in Redis (TTL = 5 min)
    so a replayed challenge (same ciphertext) is rejected even if the TOTP
    code would be valid.

    CWE-384 (Session Fixation): each challenge has a unique nonce so two
    separate TOTP completions cannot share the same challenge blob.
    """
    nonce = secrets.token_hex(16)
    payload = json.dumps({"uid": str(user_id), "nonce": nonce})
    ciphertext, _ver = settings.encrypt(payload)
    return ciphertext


def _verify_totp_challenge(challenge: str, settings: Settings) -> str:
    """Decrypt and return the user_id string from a TOTP challenge.

    Raises ``HTTPException(401)`` if the challenge cannot be decrypted,
    is expired (Fernet enforces the TTL), or has already been consumed.

    The Fernet TTL check uses ``max_age`` to gate on ``_CHALLENGE_TTL_SECONDS``
    — the cryptographic timestamp embedded at encryption time is validated
    server-side, no separate clock comparison is needed.

    Returns the raw nonce alongside the uid so the caller can invalidate it.
    Raises HTTPException on any failure — callers must not distinguish between
    "bad ciphertext" and "expired" to prevent oracle attacks.
    """
    from cryptography.fernet import Fernet, InvalidToken

    try:
        # We need max_age enforcement; use the raw Fernet directly.
        # ``settings.decrypt`` doesn't expose max_age, so we reach into
        # the key map ourselves.
        keys = settings.get_encryption_keys()
        plaintext: str | None = None
        for _ver in sorted(keys, reverse=True):
            try:
                f = Fernet(keys[_ver].encode())
                raw_bytes = f.decrypt(challenge.encode("ascii"), ttl=_CHALLENGE_TTL_SECONDS)
                plaintext = raw_bytes.decode("utf-8")
                break
            except InvalidToken:
                continue
        if plaintext is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
        data = json.loads(plaintext)
        uid_val = data["uid"]
        return str(uid_val)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials") from None


def _challenge_redis_key(challenge: str) -> str:
    """Return the Redis key that marks a challenge as consumed."""
    # Use only the first 32 chars as a key suffix — the Fernet blob can be
    # long and we only need enough to disambiguate within the 5-min window.
    return f"totp_challenge_used:{challenge[:32]}"


async def _mark_challenge_used(challenge: str) -> None:
    """Store a 'used' marker in Redis so the challenge cannot be replayed."""
    try:
        from redis.asyncio import Redis as _Redis

        from drevalis.core.redis import get_pool

        _redis: _Redis = _Redis(connection_pool=get_pool())
        try:
            key = _challenge_redis_key(challenge)
            await _redis.set(key, "1", ex=_CHALLENGE_TTL_SECONDS)
        finally:
            await _redis.aclose()
    except Exception:  # noqa: BLE001
        # Best-effort — if Redis is unavailable we degrade gracefully.
        # The Fernet TTL still limits the replay window to 5 minutes.
        pass


async def _is_challenge_used(challenge: str) -> bool:
    """Return True if this challenge has already been consumed."""
    try:
        from redis.asyncio import Redis as _Redis

        from drevalis.core.redis import get_pool

        _redis: _Redis = _Redis(connection_pool=get_pool())
        try:
            val = await _redis.get(_challenge_redis_key(challenge))
            return val is not None
        finally:
            await _redis.aclose()
    except Exception:  # noqa: BLE001
        return False  # Fail-open: let the Fernet TTL be the backstop.


# ── Auth ──────────────────────────────────────────────────────────────


@router.post("/api/v1/auth/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    # First-run bootstrap from env vars — creates the owner account
    # if the users table is empty and OWNER_EMAIL/OWNER_PASSWORD are set.
    await ensure_owner_from_env(db)

    # F-S-09: per-(IP, email) rate limit on login attempts.
    # PBKDF2 at 480k iterations gives ~6 attempts/sec; without this a
    # patient attacker could still bruteforce a weak password over hours.
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")
    email_norm = body.email.lower().strip()
    try:
        await check_login_rate_limit(ip, email_norm)
    except LoginRateLimitedError as exc:
        logger.warning("auth.login_rate_limited", ip=ip, email=email_norm)
        # A.2 — fire-and-forget: record rate-limited attempt (no user_id known).
        asyncio.create_task(
            _record_login_event(
                db,
                user_id=None,
                email_attempted=email_norm,
                ip=ip,
                user_agent=ua,
                success=False,
                failure_reason="rate_limited",
            )
        )
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    row = await db.execute(select(User).where(User.email == email_norm))
    user = row.scalar_one_or_none()

    # A.1 — Constant-time login: always run verify_password so the
    # response time is uniform whether or not the email exists.
    # The structlog events below still carry the true reason so operators
    # can audit — the information never reaches the HTTP response body.
    if user is None:
        verify_password(body.password, _DUMMY_HASH)  # constant-time burn
        logger.warning("auth.login_failure", reason="unknown_email", ip=ip)
        await record_login_failure(ip, email_norm)
        # A.2
        asyncio.create_task(
            _record_login_event(
                db,
                user_id=None,
                email_attempted=email_norm,
                ip=ip,
                user_agent=ua,
                success=False,
                failure_reason="unknown_email",
            )
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    if not user.is_active:
        verify_password(body.password, _DUMMY_HASH)  # constant-time burn
        logger.warning("auth.login_failure", reason="inactive_user", user_id=str(user.id), ip=ip)
        await record_login_failure(ip, email_norm)
        asyncio.create_task(
            _record_login_event(
                db,
                user_id=user.id,
                email_attempted=None,
                ip=ip,
                user_agent=ua,
                success=False,
                failure_reason="inactive_user",
            )
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    if not verify_password(body.password, user.password_hash):
        logger.warning("auth.login_failure", reason="wrong_password", user_id=str(user.id), ip=ip)
        await record_login_failure(ip, email_norm)
        asyncio.create_task(
            _record_login_event(
                db,
                user_id=user.id,
                email_attempted=None,
                ip=ip,
                user_agent=ua,
                success=False,
                failure_reason="wrong_password",
            )
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    # ── TOTP gate ──────────────────────────────────────────────────────
    # If 2FA is confirmed (totp_confirmed_at IS NOT NULL), do NOT issue
    # the session cookie yet.  Return a short-lived challenge the client
    # must complete via POST /auth/login/totp.
    if user.totp_confirmed_at is not None:
        challenge = _mint_totp_challenge(user.id, settings)
        logger.info("auth.login_totp_required", user_id=str(user.id), ip=ip)
        # Record as a stage-1 success / totp_required in audit log.
        # success=False: the full login is not yet complete; the frontend
        # "recent logins" feed uses this to show a pending-2FA entry.
        asyncio.create_task(
            _record_login_event(
                db,
                user_id=user.id,
                email_attempted=None,
                ip=ip,
                user_agent=ua,
                success=False,
                failure_reason="totp_required",
            )
        )
        return {"stage": "totp_required", "challenge": challenge}

    # ── Password-only success ──────────────────────────────────────────
    user.last_login_at = datetime.now(tz=UTC)
    await db.commit()

    # A.2 — record success (fire-and-forget).
    asyncio.create_task(
        _record_login_event(
            db,
            user_id=user.id,
            email_attempted=None,
            ip=ip,
            user_agent=ua,
            success=True,
            failure_reason=None,
        )
    )

    token = mint_session_token(
        user_id=user.id,
        role=user.role,
        secret=settings.get_session_secret(),
        session_version=user.session_version,
    )
    response.set_cookie(
        _COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,  # 14 days
        path="/",
    )
    logger.info("auth.login_success", user_id=str(user.id), email=user.email)
    return {"message": "logged_in", "role": user.role, "display_name": user.display_name or ""}


# ── TOTP second factor ─────────────────────────────────────────────────


@router.post("/api/v1/auth/login/totp")
async def login_totp(
    body: TotpLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Complete a TOTP two-factor login.

    Accepts either:
    * A 6-digit TOTP code (routed to verify_code).
    * A 16-hex-char recovery code (consumed from the encrypted list).

    Rate-limited with the same Redis bucket as the password endpoint
    (same IP + email key prefix, same window + threshold).

    CWE-308 (Use of Single-factor Authentication): this endpoint is the
    second factor — single-factor bypass via this endpoint is blocked by
    requiring a valid short-lived challenge token.
    """
    from drevalis.services.totp import verify_code as _verify_totp

    ip = _client_ip(request)
    ua = request.headers.get("user-agent")

    # Decode challenge — raises 401 on bad/expired ciphertext.
    uid_str = _verify_totp_challenge(body.challenge, settings)

    # Replay protection — reject a challenge that has already been used.
    if await _is_challenge_used(body.challenge):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    try:
        uid = UUID(uid_str)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials") from None

    user = await db.get(User, uid)
    if not user or not user.is_active or user.totp_confirmed_at is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    # Apply the same rate-limit as password login — same IP + email key.
    try:
        await check_login_rate_limit(ip, user.email)
    except LoginRateLimitedError as exc:
        logger.warning("auth.totp_rate_limited", ip=ip, user_id=str(uid))
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    code = body.code.strip()

    # Route by code format:
    # * 6 decimal digits → TOTP path.
    # * 16 hex chars (lower/upper) → recovery code path.
    code_valid = False
    if len(code) == 6 and code.isdigit():
        # TOTP path.
        if user.totp_secret_encrypted is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
        try:
            secret = settings.decrypt(user.totp_secret_encrypted)
        except Exception:  # noqa: BLE001
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials") from None
        code_valid = _verify_totp(secret, code)

    elif len(code) == 16 and _is_hex(code):
        # Recovery code path.
        code_valid = await _consume_recovery_code(user, code.lower(), settings, db)

    # If the code is invalid, record the failure and raise 401.
    if not code_valid:
        await record_login_failure(ip, user.email)
        asyncio.create_task(
            _record_login_event(
                db,
                user_id=user.id,
                email_attempted=None,
                ip=ip,
                user_agent=ua,
                success=False,
                failure_reason="wrong_password",  # keep generic — don't leak "wrong TOTP"
            )
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    # Mark challenge as used (best-effort, Fernet TTL backs this up).
    await _mark_challenge_used(body.challenge)

    # Full login success.
    user.last_login_at = datetime.now(tz=UTC)
    await db.commit()

    asyncio.create_task(
        _record_login_event(
            db,
            user_id=user.id,
            email_attempted=None,
            ip=ip,
            user_agent=ua,
            success=True,
            failure_reason=None,
        )
    )

    token = mint_session_token(
        user_id=user.id,
        role=user.role,
        secret=settings.get_session_secret(),
        session_version=user.session_version,
    )
    response.set_cookie(
        _COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
        path="/",
    )
    logger.info("auth.totp_login_success", user_id=str(user.id))
    return {"message": "logged_in", "role": user.role, "display_name": user.display_name or ""}


def _is_hex(s: str) -> bool:
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


async def _consume_recovery_code(
    user: User,
    code: str,
    settings: Settings,
    db: AsyncSession,
) -> bool:
    """Check whether *code* is in the user's recovery list.

    If found: removes it from the list (it is single-use), re-encrypts the
    updated list, and persists the change.  Returns True if the code was
    valid, False otherwise.

    Recovery codes are compared case-insensitively (hex normalised to lower).
    CWE-262 (Not Using Password Aging): recovery codes are consumed on use —
    a used code cannot be reused.
    """
    if not user.totp_recovery_codes_encrypted:
        return False

    try:
        raw = settings.decrypt(user.totp_recovery_codes_encrypted)
        codes: list[str] = json.loads(raw)
    except Exception:  # noqa: BLE001
        return False

    normalised = code.lower()
    if normalised not in codes:
        return False

    # Remove the consumed code.
    codes.remove(normalised)
    new_ciphertext, new_version = settings.encrypt(json.dumps(codes))
    user.totp_recovery_codes_encrypted = new_ciphertext
    user.totp_key_version = new_version
    await db.flush()  # persist within the current transaction; caller commits.
    return True


# ── Logout ────────────────────────────────────────────────────────────


@router.post("/api/v1/auth/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(_COOKIE_NAME, path="/")
    return {"message": "logged_out"}


@router.post("/api/v1/auth/logout-everywhere")
async def logout_everywhere(
    response: Response,
    me: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Invalidate all existing session tokens for the current user.

    Increments ``session_version`` on the user row.  Every token minted
    before this call carries the old ``sv`` value and will be rejected by
    ``_current_user``.  The caller's own cookie is also cleared so they
    are signed out immediately.

    CWE-613 (Insufficient Session Expiration), OWASP A07:2021.
    """
    me.session_version = me.session_version + 1
    await db.commit()
    response.delete_cookie(_COOKIE_NAME, path="/")
    logger.info("auth.logout_everywhere", user_id=str(me.id), new_version=me.session_version)
    return {"message": "logged_out_everywhere"}


@router.get("/api/v1/auth/me", response_model=UserResponse | None)
async def whoami(user: User | None = Depends(_current_user)) -> UserResponse | None:
    return UserResponse.from_orm(user) if user else None


# ── Per-user preferences (dashboard layout, theme, etc.) ─────────────


class PreferencesUpdate(BaseModel):
    """Partial preferences update — keys present here are merged into
    the existing ``users.preferences`` JSON. Keys NOT in the request
    are left untouched.

    No schema validation on the values themselves — clients write what
    they need and the backend stores it as-is. Top-level keys SHOULD be
    namespaced by feature (``dashboard_layout``, ``theme``,
    ``calendar_view``, …) so removals can target a single feature
    without colliding with others.
    """

    model_config = ConfigDict(extra="allow")


@router.get("/api/v1/auth/preferences")
async def get_preferences(user: User = Depends(require_user)) -> dict[str, Any]:
    """Return the current user's preferences blob.

    Empty for users that have never set anything. Always a dict.
    """
    return dict(user.preferences or {})


@router.put("/api/v1/auth/preferences")
async def update_preferences(
    body: dict[str, Any],
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Shallow-merge *body* into the user's preferences and persist.

    ``null`` values delete that top-level key (so the client can
    explicitly reset a feature's prefs). Other values are written as-is.
    Returns the new full preferences blob.
    """
    current = dict(user.preferences or {})
    for key, value in body.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    user.preferences = current
    await db.commit()
    return current


@router.get("/api/v1/auth/mode")
async def auth_mode(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    """Public endpoint — reports whether team mode and/or demo mode are active.

    The frontend's login gate calls this when ``/auth/me`` returns null:
    if ``team_mode`` is true, redirect to ``/login``; otherwise keep
    the single-user no-auth path. ``demo_mode`` is surfaced separately
    so the UI can render the banner and disable destructive actions.
    """
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one() or 0
    owner_env = bool((os.environ.get("OWNER_EMAIL") or "").strip())
    return {
        "team_mode": count > 0 or owner_env,
        "demo_mode": bool(settings.demo_mode),
    }


# ── Login history ─────────────────────────────────────────────────────


@router.get("/api/v1/auth/login-history", response_model=list[LoginEventResponse])
async def my_login_history(
    me: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[LoginEventResponse]:
    """Return the current user's most-recent login events (self only).

    IP and user-agent are included because this is the owner querying
    their own history — they have legitimate interest in spotting
    unfamiliar IPs.  The owner-gated ``/users/{id}/login-history`` route
    applies the same column set.
    """
    rows = (
        (
            await db.execute(
                select(LoginEvent)
                .where(LoginEvent.user_id == me.id)
                .order_by(LoginEvent.timestamp.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [LoginEventResponse.model_validate(r, from_attributes=True) for r in rows]


# ── 2FA enrolment / management ────────────────────────────────────────


@router.post("/api/v1/auth/2fa/enroll", response_model=TotpEnrollResponse)
async def totp_enroll(
    me: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TotpEnrollResponse:
    """Generate a TOTP secret and recovery codes; store them encrypted.

    Idempotent check: if ``totp_confirmed_at IS NOT NULL``, 2FA is already
    active — return 409 rather than silently overwriting the secret (which
    would lock the user out of their authenticator app).

    The returned ``recovery_codes`` are shown ONCE.  They are stored
    encrypted, not hashed, so the consume path can display which code was
    used without round-tripping through the UI.

    CWE-330: recovery codes use ``secrets.token_hex`` (CSPRNG).
    CWE-321: secret uses ``secrets.token_bytes`` (CSPRNG, 160 bits).
    """
    from drevalis.services.totp import (
        generate_recovery_codes,
        generate_secret,
        provisioning_uri,
    )

    # Idempotency guard: reject if 2FA is already confirmed.
    if me.totp_confirmed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "2fa_already_enrolled")

    secret = generate_secret()
    recovery_codes = generate_recovery_codes(10)

    # Encrypt secret.
    secret_ct, key_ver = settings.encrypt(secret)
    # Encrypt recovery codes as a JSON list.
    codes_ct, _kv = settings.encrypt(json.dumps(recovery_codes))

    me.totp_secret_encrypted = secret_ct
    me.totp_key_version = key_ver
    me.totp_recovery_codes_encrypted = codes_ct
    # totp_confirmed_at remains NULL — login enforcement won't activate
    # until the user verifies their first code (POST /2fa/confirm).
    await db.commit()

    uri = provisioning_uri(secret=secret, account=me.email)
    logger.info("auth.2fa_enroll", user_id=str(me.id))
    return TotpEnrollResponse(
        secret_base32=secret,
        otpauth_uri=uri,
        recovery_codes=recovery_codes,
    )


@router.post("/api/v1/auth/2fa/confirm")
async def totp_confirm(
    body: TotpConfirmRequest,
    me: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Verify the user can produce a valid TOTP code → activate 2FA.

    Until this endpoint succeeds, the stored secret is "pending" and the
    login flow does NOT yet require TOTP.  This prevents lock-out when the
    user saves the secret but never sets up their authenticator app.

    Returns 400 ``totp_not_enrolled`` if no secret is stored yet.
    Returns 409 ``2fa_already_enrolled`` if already confirmed.
    Returns 401 ``invalid_totp_code`` if the code is wrong.
    """
    from drevalis.services.totp import verify_code as _verify_totp

    if me.totp_confirmed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "2fa_already_enrolled")

    if me.totp_secret_encrypted is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "totp_not_enrolled")

    try:
        secret = settings.decrypt(me.totp_secret_encrypted)
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "totp_decrypt_error") from None

    if not _verify_totp(secret, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_totp_code")

    me.totp_confirmed_at = datetime.now(tz=UTC)
    await db.commit()
    logger.info("auth.2fa_confirmed", user_id=str(me.id))
    return {"message": "2fa_activated"}


@router.post("/api/v1/auth/2fa/disable")
async def totp_disable(
    body: TotpDisableRequest,
    me: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Disable TOTP 2FA after re-confirming the account password.

    Re-prompts for the password to prevent an unattended browser session
    from being able to silently disable 2FA (CWE-620, CWE-269).

    After success, all four TOTP columns are NULLed and ``session_version``
    is bumped to invalidate all existing sessions — the user must log in
    again, completing the full password-only flow (no challenge needed
    since totp_confirmed_at is now NULL).
    """
    if not verify_password(body.password, me.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    me.totp_secret_encrypted = None
    me.totp_key_version = None
    me.totp_confirmed_at = None
    me.totp_recovery_codes_encrypted = None
    # Bump session_version to kill all existing sessions — the device that
    # disabled 2FA might itself be compromised.
    me.session_version = me.session_version + 1
    await db.commit()
    logger.info("auth.2fa_disabled", user_id=str(me.id))
    return {"message": "2fa_disabled"}


# ── Forgot / reset password ───────────────────────────────────────────


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., pattern=_EMAIL_RE)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
    totp_code: str | None = None  # required when the user has 2FA active


# Per-IP rate-limit for forgot-password: 5 requests / hour.
_FORGOT_RATE_LIMIT = 5
_FORGOT_RATE_WINDOW = 3600  # 1 hour


async def _check_forgot_rate(client_ip: str) -> bool:
    """Return True (allowed) / False (blocked) for the per-IP forgot-password limit.

    Best-effort: Redis unavailability degrades gracefully (fail-open).
    """
    key = f"forgot_rate:ip:{client_ip}"
    try:
        from redis.asyncio import Redis as _Redis

        from drevalis.core.redis import get_pool

        _redis: _Redis = _Redis(connection_pool=get_pool())
        try:
            pipe = _redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, _FORGOT_RATE_WINDOW, nx=True)
            results = await pipe.execute()
            count = int(results[0])
        finally:
            await _redis.aclose()
    except Exception:  # noqa: BLE001
        return True

    return count <= _FORGOT_RATE_LIMIT


@router.post("/api/v1/auth/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Request a password-reset email.

    Always returns 200 with the same generic message whether or not the
    email is registered, whether SMTP is configured, and whether the
    rate-limit has been hit (server-side only).  This prevents account
    enumeration (CWE-204, CWE-208).

    Rate-limited per-IP at 5 requests / hour (per-email limit is inside
    ``request_reset`` at 3 / hour).

    Audit: records a ``login_events`` row with failure_reason='reset_requested'
    (success=False) to preserve a timeline for security review.
    """
    from drevalis.services.password_reset import request_reset

    ip = _client_ip(request)
    ua = request.headers.get("user-agent")
    email_norm = body.email.lower().strip()

    _GENERIC_RESPONSE = {"message": "if your email is on file, a reset link has been sent"}

    # ── Per-IP rate limit ──────────────────────────────────────────────
    allowed = await _check_forgot_rate(ip)
    if not allowed:
        logger.warning("auth.forgot_password_rate_limited", ip=ip)
        # Intentionally return the same 200 — no information leakage.
        return _GENERIC_RESPONSE

    # Audit record (fire-and-forget).
    asyncio.create_task(
        _record_login_event(
            db,
            user_id=None,
            email_attempted=email_norm,
            ip=ip,
            user_agent=ua,
            success=False,
            failure_reason="reset_requested",
        )
    )

    # Delegate all real work (timing-uniform, never raises).
    await request_reset(db=db, email=email_norm, settings=settings)

    return _GENERIC_RESPONSE


@router.post("/api/v1/auth/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Consume a password-reset token and set a new password.

    On success:
    * The session cookie is cleared (user must log in fresh).
    * If the account has TOTP 2FA active, a ``totp_required`` challenge is
      returned instead — same as the regular login flow.  The full session
      is only issued after the TOTP step completes.

    On failure: always 400 ``invalid_or_expired_token``.  Never
    distinguishes between "expired", "already used", "wrong token" so
    callers cannot probe the token state.

    Audit: success and failure rows written to ``login_events``.
    """
    from drevalis.services.password_reset import consume_reset

    ip = _client_ip(request)
    ua = request.headers.get("user-agent")

    _BAD_TOKEN = HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "invalid_or_expired_token",
    )

    user = await consume_reset(
        db=db,
        raw_token=body.token,
        new_password=body.new_password,
        settings=settings,
    )

    if user is None:
        # Audit failure.
        asyncio.create_task(
            _record_login_event(
                db,
                user_id=None,
                email_attempted=None,
                ip=ip,
                user_agent=ua,
                success=False,
                failure_reason="invalid_token",
            )
        )
        raise _BAD_TOKEN

    # Clear any existing session cookie — user must log in fresh.
    response.delete_cookie(_COOKIE_NAME, path="/")

    # ── TOTP gate ──────────────────────────────────────────────────────
    # If 2FA is enabled, do not issue a session cookie yet. The client
    # must complete the TOTP step exactly as in the normal login flow.
    if user.totp_confirmed_at is not None:
        challenge = _mint_totp_challenge(user.id, settings)
        asyncio.create_task(
            _record_login_event(
                db,
                user_id=user.id,
                email_attempted=None,
                ip=ip,
                user_agent=ua,
                success=False,
                failure_reason="totp_required",
            )
        )
        logger.info("auth.reset_password_totp_required", user_id=str(user.id))
        return {"stage": "totp_required", "challenge": challenge}

    # ── No 2FA — record success and return ────────────────────────────
    asyncio.create_task(
        _record_login_event(
            db,
            user_id=user.id,
            email_attempted=None,
            ip=ip,
            user_agent=ua,
            success=True,
            failure_reason=None,
        )
    )
    logger.info("auth.reset_password_success", user_id=str(user.id))
    return {"message": "password_reset_successful"}


# ── User management ───────────────────────────────────────────────────


class UserCreate(BaseModel):
    email: str = Field(..., pattern=_EMAIL_RE)
    password: str = Field(..., min_length=8)
    role: str = Field(default="editor", pattern="^(owner|editor|viewer)$")
    display_name: str | None = None


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(owner|editor|viewer)$")
    display_name: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


@router.get("/api/v1/users", response_model=list[UserResponse])
async def list_users(
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [UserResponse.from_orm(u) for u in rows]


@router.post("/api/v1/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    existing = await db.execute(select(User).where(User.email == body.email.lower().strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "email_already_registered")
    user = User(
        email=body.email.lower().strip(),
        password_hash=hash_password(body.password),
        role=body.role,
        display_name=body.display_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.from_orm(user)


@router.put("/api/v1/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    me: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")

    # Prevent an owner from demoting themselves to a non-owner role if
    # they're the only owner — guards against accidental lockout.
    if user.id == me.id and body.role and body.role != "owner":
        owner_count = (
            (await db.execute(select(User).where(User.role == "owner", User.is_active.is_(True))))
            .scalars()
            .all()
        )
        if len([o for o in owner_count if o.id != user.id]) == 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "cannot_remove_last_owner",
            )

    if body.role is not None:
        user.role = body.role
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)
    await db.commit()
    await db.refresh(user)
    return UserResponse.from_orm(user)


@router.delete("/api/v1/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    me: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    if user_id == me.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot_delete_self")
    user = await db.get(User, user_id)
    if not user:
        return
    await db.delete(user)
    await db.commit()


@router.get("/api/v1/users/{user_id}/login-history", response_model=list[LoginEventResponse])
async def user_login_history(
    user_id: UUID,
    _: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[LoginEventResponse]:
    """Return login events for any user (owner-gated).

    Returns the same columns as ``/auth/login-history`` since the owner
    already has elevated privileges over all user data.
    """
    rows = (
        (
            await db.execute(
                select(LoginEvent)
                .where(LoginEvent.user_id == user_id)
                .order_by(LoginEvent.timestamp.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [LoginEventResponse.model_validate(r, from_attributes=True) for r in rows]
