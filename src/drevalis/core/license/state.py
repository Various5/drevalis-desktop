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
import os
import threading
from dataclasses import dataclass

from drevalis.core.license.claims import LicenseClaims

# License bypass — opt-in escape hatch for development. The default is
# OFF: the desktop port now talks to the real license server (the
# original SCOPE.md decision to ship desktop license-free has been
# reversed). Set ``DREVALIS_LICENSE_BYPASS=1`` only for dev / CI work
# that needs the gates open without a real activation. Not coupled to
# ``DREVALIS_DESKTOP_MODE`` anymore — that flag still controls
# desktop-only routing and error-hint flavor, but licensing is now
# enforced on every install regardless of platform.
_LICENSE_BYPASS = os.environ.get("DREVALIS_LICENSE_BYPASS", "0") == "1"


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


def _build_desktop_claims() -> LicenseClaims:
    """Synthetic claims for desktop installs.

    The desktop port has no licensing (SCOPE.md), but the feature-gating
    helpers (``require_feature``, ``has_feature``) still consult
    ``state.claims`` to decide whether a route is allowed. Without
    claims, every Pro/Studio gate (character packs, audiobooks, etc.)
    returned 402 even though ``is_usable`` was true.

    Synthesising a Studio-tier claims object grants every documented
    feature so feature-gated routes work end-to-end on desktop. Sentinel
    values (``"desktop"``, far-future ``exp``) make this state easy to
    spot in logs and never collide with a real license.
    """
    # 100 years out — large enough for ``is_in_grace`` to never flip,
    # mirroring the lifetime sentinel used in the JWT spec.
    far_future = 32_503_680_000  # 3000-01-01 UTC

    # Late import to break the circular: ``features.py`` imports
    # ``state.get_state`` at module load.
    from drevalis.core.license.features import _STUDIO_FEATURES

    return LicenseClaims(
        iss="drevalis-desktop",
        sub="desktop",
        jti="desktop",
        tier="studio",
        features=sorted(_STUDIO_FEATURES),
        machines=1,
        iat=0,
        nbf=0,
        exp=far_future,
        period_end=far_future,
        license_type="desktop",
    )


# Synthetic always-on state for desktop. Cached on first read of
# ``get_state`` so the import order between ``state`` and ``features``
# doesn't matter — both modules can finish loading before either set of
# constants is materialised.
_DESKTOP_STATE: LicenseState | None = None


def _desktop_state() -> LicenseState:
    global _DESKTOP_STATE
    if _DESKTOP_STATE is None:
        _DESKTOP_STATE = LicenseState(
            status=LicenseStatus.ACTIVE,
            claims=_build_desktop_claims(),
        )
    return _DESKTOP_STATE
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
    if _LICENSE_BYPASS:
        return _desktop_state()
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
    if _LICENSE_BYPASS:
        return True
    with _lock:
        return _bootstrapped


def get_local_version() -> int:
    with _lock:
        return _local_version


def set_local_version(v: int) -> None:
    global _local_version
    with _lock:
        _local_version = v
