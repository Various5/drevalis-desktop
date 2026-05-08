"""OS keychain helpers for the Fernet master key.

Phase 0 spike — minimal surface to validate the round-trip:

  1. Read ``ENCRYPTION_KEY`` from the OS keychain (Windows Credential Manager
     on Windows, macOS Keychain on macOS, Secret Service on Linux).
  2. If absent, fall back to the value already loaded into ``Settings`` from
     the env / .env, then write that value back to the keychain so future
     starts no longer need an env var.
  3. Versioned keys (``ENCRYPTION_KEY_V1``, ``V2``, ...) follow the same
     pattern under the ``Drevalis/encryption_key_v<N>`` service name.

This module deliberately does **not** mutate ``Settings``. Wiring the
keychain-resolved key back into the running ``Settings`` instance is a
Phase 1 task — Phase 0 just proves the round-trip works.
"""

from __future__ import annotations

import keyring

SERVICE = "Drevalis"
CURRENT_USERNAME = "encryption_key"


def _versioned_username(version: int) -> str:
    return f"encryption_key_v{version}"


def get_or_set_encryption_key(env_value: str | None) -> str:
    """Resolve the current Fernet master key.

    Returns the key string. Order of precedence:

    1. Existing keychain entry under ``Drevalis/encryption_key``.
    2. ``env_value`` (whatever the env / .env yielded). If present, this is
       persisted to the keychain so subsequent starts no longer need it.

    Raises ``RuntimeError`` if neither source supplies a key — the caller
    should treat that as a first-run failure and surface a setup prompt.
    """
    stored = keyring.get_password(SERVICE, CURRENT_USERNAME)
    if stored:
        return stored
    if env_value:
        keyring.set_password(SERVICE, CURRENT_USERNAME, env_value)
        return env_value
    raise RuntimeError(
        "No ENCRYPTION_KEY found in OS keychain or environment. "
        "Run the first-run setup or set ENCRYPTION_KEY in .env."
    )


def get_versioned_key(version: int) -> str | None:
    """Return a historical key version from the keychain (or ``None``)."""
    return keyring.get_password(SERVICE, _versioned_username(version))


def set_versioned_key(version: int, value: str) -> None:
    """Persist a historical key version to the keychain (rotation flow)."""
    keyring.set_password(SERVICE, _versioned_username(version), value)


def delete_encryption_key() -> None:
    """Remove the current key from the keychain. Test/uninstall helper."""
    try:
        keyring.delete_password(SERVICE, CURRENT_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
