"""Fernet encryption utilities with key-version support.

The application stores a *current* encryption key in ``ENCRYPTION_KEY`` and may
optionally keep older keys as ``ENCRYPTION_KEY_V1``, ``ENCRYPTION_KEY_V2``, etc.
to allow transparent decryption of values encrypted with a previous key.

``encrypt_value`` always uses the current key and returns the ciphertext together
with a version number (defaulting to the highest version available).

``decrypt_value`` accepts an explicit key or tries all known key versions when
the caller supplies a version hint.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken


def _validate_fernet_key(key: str) -> bytes:
    """Validate and return the key as bytes."""
    key_bytes = key.encode() if isinstance(key, str) else key
    # Fernet keys are 32 url-safe base64-encoded bytes (44 chars with padding)
    try:
        decoded = base64.urlsafe_b64decode(key_bytes)
    except Exception as exc:
        raise ValueError("Invalid Fernet key: unable to base64-decode.") from exc
    if len(decoded) != 32:
        raise ValueError(f"Invalid Fernet key: decoded length is {len(decoded)}, expected 32.")
    return key_bytes


def encrypt_value(plaintext: str, key: str, *, version: int = 1) -> tuple[str, int]:
    """Encrypt *plaintext* with the given Fernet *key*.

    Returns:
        A ``(ciphertext, version)`` tuple.  The ciphertext is a URL-safe
        base64-encoded string.  *version* is passed through so the caller
        can persist it alongside the ciphertext for future decryption.
    """
    key_bytes = _validate_fernet_key(key)
    f = Fernet(key_bytes)
    token: bytes = f.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii"), version


def decrypt_value(ciphertext: str, key: str) -> str:
    """Decrypt *ciphertext* using the given Fernet *key*.

    Raises:
        ``cryptography.fernet.InvalidToken`` if the key cannot decrypt the
        ciphertext (wrong key or tampered data).
    """
    key_bytes = _validate_fernet_key(key)
    f = Fernet(key_bytes)
    try:
        plaintext_bytes: bytes = f.decrypt(ciphertext.encode("ascii"))
    except InvalidToken:
        raise
    return plaintext_bytes.decode("utf-8")


def decrypt_value_multi(ciphertext: str, keys: dict[int, str]) -> tuple[str, int]:
    """Try decrypting *ciphertext* with multiple versioned keys.

    *keys* maps version numbers to Fernet key strings, e.g.
    ``{1: "key-v1...", 2: "key-v2..."}``.  Keys are tried from the highest
    version to the lowest.

    Returns:
        ``(plaintext, version)`` on the first successful decryption.

    Raises:
        ``cryptography.fernet.InvalidToken`` if **no** key can decrypt the
        value.
    """
    for version in sorted(keys, reverse=True):
        try:
            plaintext = decrypt_value(ciphertext, keys[version])
            return plaintext, version
        except InvalidToken:
            continue
    raise InvalidToken("None of the provided keys could decrypt the ciphertext.")
