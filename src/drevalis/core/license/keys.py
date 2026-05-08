"""Embedded Ed25519 public key(s) for license JWT verification.

The private key is held only by the license server and never shipped with
the client. A list is used so key rotation does not require a code release:
a new key is added here ahead of time; old licenses still validate against
the previous key; once all licenses are re-issued the old key is removed.

Override: setting ``LICENSE_PUBLIC_KEY_OVERRIDE`` in the environment replaces
this list entirely (dev/test only — production images should not set this).
"""

from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# ── Embedded public keys (PEM, SubjectPublicKeyInfo) ──────────────────────
# Add new keys at the TOP of the list when rotating. Do NOT remove an entry
# until every outstanding license signed by the old key has been re-issued
# or expired.
_PUBLIC_KEYS_PEM: tuple[bytes, ...] = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"MCowBQYDK2VwAyEAqHN/J/o2INT6NjLZ/LJ9p30tJ87d0y23hOG6XIabI84=\n"
    b"-----END PUBLIC KEY-----\n",
)


def _load_pem(pem: bytes) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError(f"expected Ed25519 public key, got {type(key).__name__}")
    return key


def get_public_keys(override_pem: str | None = None) -> list[Ed25519PublicKey]:
    """Return the list of Ed25519 public keys to verify against.

    If ``override_pem`` is provided, returns only that single key — intended
    for tests and dev-mode overrides.
    """
    if override_pem:
        return [_load_pem(override_pem.encode())]
    return [_load_pem(pem) for pem in _PUBLIC_KEYS_PEM]
