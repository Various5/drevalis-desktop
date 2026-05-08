"""Stable machine identifier derivation.

Used for seat-cap enforcement on the license server. Sent on activate and
every heartbeat. A stable per-install value; changes if the user migrates
to new hardware or a new hostname, which correctly releases/re-claims a
seat.
"""

from __future__ import annotations

import hashlib
import socket
import uuid as _uuid

_SALT = b"drevalis/machine_id/v1"


def _primary_mac_int() -> int:
    """Return the primary MAC as a 48-bit int, or 0 if unavailable.

    ``uuid.getnode`` returns a 48-bit int; the low bit of byte 0 is 1 when
    it synthesized a random value rather than reading a real NIC. We still
    use it either way — a synthesized value is stable for the duration of
    the container, which is what matters for seat counting.
    """
    try:
        return _uuid.getnode()
    except Exception:
        return 0


def stable_machine_id() -> str:
    """Return a 16-hex-char stable identifier for this install."""
    try:
        hostname = socket.gethostname().encode("utf-8", errors="ignore")
    except Exception:
        hostname = b""
    mac = _primary_mac_int().to_bytes(8, byteorder="big", signed=False)
    digest = hashlib.sha256(_SALT + b"|" + hostname + b"|" + mac).hexdigest()
    return digest[:16]
