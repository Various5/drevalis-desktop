"""Soft deprecation headers for endpoints sold as Pro+ but not yet hard-gated.

Three endpoints are advertised on the marketing pricing matrix as Pro+
features but do NOT currently require ``require_feature`` — hard-cutting
them would 402 existing Creator-tier users mid-flight without warning.
This module is the two-step migration path:

* **Now (this release):** when a Creator-tier user calls one of these
  endpoints, the response carries ``Deprecation: true`` (RFC 9745) and
  ``Sunset: <date>`` (RFC 8594) headers. The body still succeeds — no
  behavioral change. API consumers see the deprecation in their HTTP
  layer and can plan accordingly.

* **After the sunset date:** the same endpoints flip to a hard
  ``require_feature("...")`` gate. That commit is one line per route.

The sunset date below is 60 days out — long enough for a customer
email cycle, short enough that we don't drag the migration forever.

Usage in a route handler:

    from fastapi import Response

    @router.post("/{episode_id}/continuity")
    async def check_script_continuity(response: Response, ...):
        apply_deprecation_headers(response, "continuity_check")
        # ... existing logic ...
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime

import structlog
from fastapi import Response

from drevalis.core.license.features import _current_feature_set
from drevalis.core.license.usage import log_feature_usage

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# 2026-07-06 23:59:59 UTC. ~60 days from the v0.36.x release window.
# When this date passes, the three endpoints listed in
# ``DEPRECATED_FEATURES`` flip to a hard ``require_feature`` gate.
SUNSET_DATE: datetime = datetime(2026, 7, 6, 23, 59, 59, tzinfo=UTC)
SUNSET_HTTP: str = format_datetime(SUNSET_DATE, usegmt=True)

# Per-feature human-readable description for the body hint. Surfaced
# alongside the response so callers don't have to look up the feature
# name in our docs.
_FEATURE_DESCRIPTIONS: dict[str, str] = {
    "continuity_check": "Continuity check (LLM-driven script analysis)",
    "cross_platform_bulk": "Cross-platform bulk publish",
    "elevenlabs": "Voice cloning via ElevenLabs IVC",
}

_PRICING_URL = "https://drevalis.com/pricing"


def apply_deprecation_headers(response: Response, feature: str) -> None:
    """Attach RFC 8594 / 9745 deprecation headers when the caller lacks
    *feature*. No-op for callers who already have the feature.

    Always emits a ``feature_usage`` structlog event (mirrors
    ``log_feature_usage``); also emits ``feature_deprecation_warning``
    when the headers actually fire so we can count Creator-tier hits
    distinctly from in-tier ones.
    """
    log_feature_usage(feature)
    if feature in _current_feature_set():
        return

    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = SUNSET_HTTP
    response.headers["Link"] = f'<{_PRICING_URL}>; rel="successor-version"'
    description = _FEATURE_DESCRIPTIONS.get(feature, feature)
    response.headers["X-Drevalis-Deprecation-Notice"] = (
        f"{description} will require Pro+ tier after "
        f"{SUNSET_DATE.date().isoformat()}. See {_PRICING_URL}."
    )

    _logger.info(
        "feature_deprecation_warning",
        feature=feature,
        sunset=SUNSET_DATE.isoformat(),
    )


__all__ = [
    "SUNSET_DATE",
    "SUNSET_HTTP",
    "apply_deprecation_headers",
]
