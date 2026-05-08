"""Soft tier-usage instrumentation.

Some endpoints are advertised on the marketing pricing matrix as paid-
tier features but are not yet ``require_feature``-gated server-side
because hard-cutting them mid-flight would break existing users on
lower tiers. Until the team runs a proper deprecation cycle (header
warning → email comms → hard gate), we still want visibility into who
is actually exercising the un-gated features.

``log_feature_usage`` is the seam: call it at the entry of one of these
endpoints with the feature name. It emits a single structlog event tagged
``feature_usage`` with the current license tier and whether the tier
nominally has the feature. No exceptions, no behavioral change — pure
telemetry.

Once we have a release cycle of data we can bump these to
``require_feature`` calls and the stale-tier users get a tidy 402.
"""

from __future__ import annotations

import structlog

from drevalis.core.license.features import _current_feature_set, current_tier

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def log_feature_usage(feature: str) -> None:
    """Emit a structlog event tagging the current call with feature + tier.

    Side-effect-only. Never raises. Designed to be safe to drop at the
    top of any handler without changing behavior.
    """
    tier = current_tier()
    in_tier = feature in _current_feature_set()
    _logger.info(
        "feature_usage",
        feature=feature,
        tier=tier,
        in_tier=in_tier,
    )
