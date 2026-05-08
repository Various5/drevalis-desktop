"""Process-wide license state holder.

The state is set at startup by ``bootstrap_license_state`` and updated when
the user activates/deactivates via the API. It is read by middleware,
routes, worker hooks, and feature-gating helpers.

Intentionally a plain module-level variable guarded by a lock rather than
FastAPI ``app.state``, because the worker process (no FastAPI app) needs
access to the same concept.
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass

from drevalis.core.license.claims import LicenseClaims


class LicenseStatus(enum.StrEnum):
    """Runtime license status.

    - ``UNACTIVATED``: no license on file; user must paste a key.
    - ``ACTIVE``: valid license, within the paid period.
    - ``GRACE``: past ``period_end`` but within the 7-day offline grace (app
      still works, UI shows a renewal banner).
    - ``EXPIRED``: past the grace window or explicitly revoked.
    - ``INVALID``: signature verification failed (tampered/wrong key).
    """

    UNACTIVATED = "unactivated"
    ACTIVE = "active"
    GRACE = "grace"
    EXPIRED = "expired"
    INVALID = "invalid"


@dataclass(frozen=True)
class LicenseState:
    status: LicenseStatus
    claims: LicenseClaims | None = None
    error: str | None = None

    @property
    def is_usable(self) -> bool:
        """Whether protected API routes should be served.

        ``GRACE`` is still usable; the banner is advisory.
        """
        return self.status in (LicenseStatus.ACTIVE, LicenseStatus.GRACE)


_lock = threading.Lock()
_state: LicenseState = LicenseState(status=LicenseStatus.UNACTIVATED)
# Local snapshot of the Redis ``license:state_version`` counter. When the
# Redis counter is ahead of the local snapshot, this worker's state is
# stale (another process activated/deactivated) and must be rebootstrapped.
_local_version: int = 0
# True once ``bootstrap_license_state`` has completed at least once in
# this process. Before that, the middleware should NOT return 402
# (doing so right after uvicorn forks but before ``lifespan`` ran caused
# every request to be gated as UNACTIVATED until the worker got lucky).
_bootstrapped: bool = False


def get_state() -> LicenseState:
    with _lock:
        return _state


def set_state(new: LicenseState) -> None:
    global _state, _bootstrapped
    with _lock:
        _state = new
        _bootstrapped = True


def is_bootstrapped() -> bool:
    """Whether ``bootstrap_license_state`` has run at least once.

    The license gate middleware uses this to avoid returning 402 during
    the startup window where state is still at its default UNACTIVATED
    value but bootstrap simply hasn't executed yet.
    """
    with _lock:
        return _bootstrapped


def get_local_version() -> int:
    with _lock:
        return _local_version


def set_local_version(v: int) -> None:
    global _local_version
    with _lock:
        _local_version = v
