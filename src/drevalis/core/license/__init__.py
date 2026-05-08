"""License subsystem: JWT verification, state, middleware, feature gating.

Public API re-exports. Internal callers should import from this package, not
from the submodules directly.
"""

from drevalis.core.license.claims import LicenseClaims
from drevalis.core.license.features import (
    TIER_FEATURES,
    TIER_MACHINE_CAP,
    has_feature,
    require_feature,
    require_tier,
)
from drevalis.core.license.machine import stable_machine_id
from drevalis.core.license.state import (
    LicenseState,
    LicenseStatus,
    get_local_version,
    get_state,
    set_local_version,
    set_state,
)
from drevalis.core.license.verifier import (
    LicenseVerificationError,
    bootstrap_license_state,
    verify_jwt,
)

__all__ = [
    "LicenseClaims",
    "LicenseState",
    "LicenseStatus",
    "LicenseVerificationError",
    "TIER_FEATURES",
    "TIER_MACHINE_CAP",
    "bootstrap_license_state",
    "get_local_version",
    "get_state",
    "has_feature",
    "require_feature",
    "require_tier",
    "set_local_version",
    "set_state",
    "stable_machine_id",
    "verify_jwt",
]
