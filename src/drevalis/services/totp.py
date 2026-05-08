"""TOTP 2FA service helpers — stdlib only, no pyotp dependency.

All cryptographic primitives are from the Python standard library:
* ``secrets``  — secure random bytes / hex tokens.
* ``hmac``     — TOTP MAC per RFC 6238 / RFC 4226.
* ``time``     — current UNIX epoch for step calculation.
* ``base64``   — base32 encoding of the raw secret bytes.
* ``hashlib``  — SHA-1 digest for TOTP (RFC 6238 mandates SHA-1 for
                 compatibility with every authenticator app).
* ``struct``   — big-endian counter packing for HOTP.

CWE-287 (Improper Authentication), OWASP A07:2021.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Secret generation
# ---------------------------------------------------------------------------

_SECRET_BYTES = 20  # 160 bits — RFC 6238 §4 minimum; sufficient for 6-digit TOTP.


def generate_secret() -> str:
    """Return a 160-bit RFC 6238 base32 TOTP secret (no padding).

    Uses ``secrets.token_bytes`` so the entropy source is
    ``os.urandom`` / ``getrandom`` — not a seeded PRNG.

    The returned string is 32 base32 characters, decodable to exactly
    20 raw bytes.  No '=' padding is included; authenticator apps handle
    both padded and unpadded inputs.
    """
    raw = secrets.token_bytes(_SECRET_BYTES)
    return base64.b32encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# Code verification
# ---------------------------------------------------------------------------

_TOTP_STEP = 30  # seconds per time step (RFC 6238 default)
_TOTP_DIGITS = 6  # output length
_TOTP_DIGEST = "sha1"  # RFC 6238 mandates SHA-1 for interoperability


def _hotp(secret_b32: str, counter: int) -> str:
    """Compute an HOTP value (RFC 4226) for the given counter.

    Internal helper used by both ``verify_code`` and the provisioning-URI
    builder.  *secret_b32* is an unpadded base32 string; *counter* is a
    64-bit big-endian integer.

    Returns a zero-padded decimal string of length ``_TOTP_DIGITS``.
    """
    # Re-add base32 padding so the stdlib decoder accepts the secret.
    padding = "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(secret_b32.upper() + padding)

    msg = struct.pack(">Q", counter)  # big-endian uint64
    mac = hmac.new(key, msg, hashlib.sha1).digest()  # noqa: S324 — RFC-mandated

    # Dynamic truncation (RFC 4226 §5.4).
    offset = mac[-1] & 0x0F
    code_int = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10**_TOTP_DIGITS)).zfill(_TOTP_DIGITS)


def verify_code(secret: str, code: str, *, window: int = 1) -> bool:
    """Verify a 6-digit TOTP code against the shared *secret*.

    *window* accepts ±N steps (1 step = 30 s) to tolerate clock skew.
    The default window of 1 allows codes from the previous or next
    30-second interval, matching the TOTP spec's recommended skew budget.

    The comparison uses ``hmac.compare_digest`` to prevent timing-based
    enumeration of valid codes (CWE-208).

    Returns ``True`` only when the supplied code matches at least one
    step within the window.  Returns ``False`` for any invalid input
    (wrong length, non-digits, unknown secret format).
    """
    if not code or len(code) != _TOTP_DIGITS or not code.isdigit():
        # Constant-time return False even for structurally invalid codes.
        # Run _hotp once against the current step so execution time is
        # indistinguishable from a valid-format code that mismatches.
        _hotp(secret, int(time.time()) // _TOTP_STEP)
        return False

    # Always iterate ALL steps in the window — do not short-circuit on the
    # first match.  An early return would make a matching code (which hits on
    # delta=0) faster than a non-matching code (which runs all 2*window+1
    # iterations), creating a measurable timing oracle (CWE-208).
    #
    # ``matched`` is a plain bool accumulator; ``|=`` is not a branch.
    # ``hmac.compare_digest`` guarantees constant-time string comparison
    # independent of the content of ``expected``.
    current_step = int(time.time()) // _TOTP_STEP
    matched = False
    for delta in range(-window, window + 1):
        expected = _hotp(secret, current_step + delta)
        matched |= hmac.compare_digest(expected.encode(), code.encode())
    return matched


# ---------------------------------------------------------------------------
# Provisioning URI
# ---------------------------------------------------------------------------


def provisioning_uri(
    *,
    secret: str,
    account: str,
    issuer: str = "Drevalis Creator Studio",
) -> str:
    """Return an ``otpauth://`` URI suitable for QR code rendering.

    Format: ``otpauth://totp/<issuer>:<account>?secret=<secret>&issuer=<issuer>``

    RFC 6238 / Google Authenticator Key URI Format.  All components are
    percent-encoded so the URI is safe to embed in a QR code or as a
    hyperlink.

    The client renders the QR from this URI — we do not generate a PNG
    server-side (no qrcode dep, no bundle budget hit).
    """
    label = quote(f"{issuer}:{account}", safe="")
    params = f"secret={quote(secret, safe='')}&issuer={quote(issuer, safe='')}&algorithm=SHA1&digits={_TOTP_DIGITS}&period={_TOTP_STEP}"
    return f"otpauth://totp/{label}?{params}"


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------

_RECOVERY_CODE_BYTES = 8  # 8 bytes → 16 hex chars


def generate_recovery_codes(count: int = 10) -> list[str]:
    """Generate *count* one-time recovery codes (16 hex characters each).

    Each code is produced by ``secrets.token_hex(8)`` which draws from
    ``os.urandom``.  The codes are shown once to the user after enrolment,
    then stored encrypted (Fernet) so they can be surfaced again on
    consumption (the user sees which code they used when they disable 2FA
    or refresh the list).

    CWE-330 (Use of Insufficiently Random Values): ``secrets`` module
    guarantees cryptographically secure randomness.
    """
    return [secrets.token_hex(_RECOVERY_CODE_BYTES) for _ in range(count)]
