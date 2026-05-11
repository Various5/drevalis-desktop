"""Ed25519 JWT minting for issued licenses.

Single shared signing key is loaded from ``LICENSE_PRIVATE_KEY_PEM`` at
process start. The client side verifies against the matching embedded
public key (see ``src/drevalis/core/license/keys.py`` in the main app
repo). Rotation is supported by adding a second public key to the client
and then swapping this server's private key.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import get_settings

ISS = "drevalis-license-server"
GRACE_DAYS = 7

# Canonical tier → features mapping. Keep in sync with
# ``src/drevalis/core/license/features.py``.
#
# ``creator`` is the post-rebrand name for what used to be ``solo``.
# Both names are kept in this map so legacy JWTs (issued before the
# rename) keep verifying; ``creator`` is the canonical name for new
# issuance. ``lifetime_pro`` inherits the Pro feature set.
_PRO_FEATURES = ["basic_generation", "runpod", "audiobooks"]

TIER_FEATURES: dict[str, list[str]] = {
    "trial": ["basic_generation"],
    "solo": ["basic_generation"],
    "creator": ["basic_generation"],
    "pro": list(_PRO_FEATURES),
    "lifetime_pro": list(_PRO_FEATURES),
    "studio": [
        "basic_generation",
        "runpod",
        "audiobooks",
        "multichannel",
        "social_platforms",
        "api_access",
    ],
}

TIER_MACHINES: dict[str, int] = {
    "trial": 1,
    "solo": 1,
    "creator": 1,
    "pro": 3,
    "lifetime_pro": 3,
    "studio": 5,
}


@lru_cache(maxsize=1)
def _private_key() -> Ed25519PrivateKey:
    pem = get_settings().license_private_key_pem.strip()
    if not pem:
        raise RuntimeError(
            "LICENSE_PRIVATE_KEY_PEM is not set. Generate an Ed25519 keypair "
            "and put the PEM-encoded private key in the environment."
        )
    # Support both the full PEM (multi-line) and a base64 glob (no newlines).
    if "-----BEGIN" not in pem:
        pem = (
            "-----BEGIN PRIVATE KEY-----\n"
            + "\n".join(pem[i : i + 64] for i in range(0, len(pem), 64))
            + "\n-----END PRIVATE KEY-----\n"
        )
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError(f"expected Ed25519 private key, got {type(key).__name__}")
    return key


def mint_jwt(
    *,
    license_id: str,
    customer: str,
    tier: str,
    period_end_unix: int,
    machines: int | None = None,
    license_type: str = "subscription",
    update_window_expires_at: int | None = None,
) -> str:
    """Sign a license JWT.

    For subscriptions: ``exp`` is ``period_end + 7 days`` so the JWT itself
    carries the offline grace window.

    For ``lifetime_pro``: ``exp`` is set far in the future (but not infinite
    — JWT libraries dislike very large ``exp`` values). The client skips
    expiry checks when ``license_type == "lifetime_pro"`` anyway, but we
    still set ``update_window_expires_at`` so the client can tell the user
    when free updates end.
    """
    now = int(datetime.now(tz=UTC).timestamp())
    if license_type == "lifetime_pro":
        # 100 years out — safely within int64 / typical JWT constraints.
        exp = now + 100 * 365 * 24 * 3600
    else:
        exp = period_end_unix + GRACE_DAYS * 24 * 3600
    payload: dict[str, object] = {
        "iss": ISS,
        "sub": customer,
        "jti": license_id,
        "tier": tier,
        "features": TIER_FEATURES.get(tier, []),
        "machines": machines or TIER_MACHINES.get(tier, 1),
        "iat": now,
        "nbf": now,
        "exp": exp,
        "period_end": period_end_unix,
        "license_type": license_type,
    }
    if update_window_expires_at is not None:
        payload["update_window_expires_at"] = update_window_expires_at
    return jwt.encode(payload, _private_key(), algorithm="EdDSA")


def new_license_id() -> str:
    return str(uuid.uuid4())
