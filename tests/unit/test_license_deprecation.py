"""Tests for the soft-deprecation header helper.

Pins the contract that:

* In-tier callers see no deprecation headers.
* Out-of-tier callers see RFC 8594 ``Sunset`` + RFC 9745
  ``Deprecation`` + a human-readable ``X-Drevalis-Deprecation-Notice``.
* The Sunset value is a valid RFC 5322 / 7231 HTTP-date.
* The helper never raises (mirrors ``log_feature_usage``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from fastapi import Response

from drevalis.core.license import state as _state
from drevalis.core.license.claims import LicenseClaims
from drevalis.core.license.deprecation import (
    SUNSET_DATE,
    SUNSET_HTTP,
    apply_deprecation_headers,
)
from drevalis.core.license.state import LicenseState, LicenseStatus


def _claims(tier: str, features: list[str] | None = None) -> LicenseClaims:
    now = int(datetime.now(tz=UTC).timestamp())
    return LicenseClaims(
        iss="x",
        sub="x",
        jti="x",
        tier=tier,
        features=features or [],
        iat=now - 100,
        nbf=now - 100,
        exp=now + 86400,
        period_end=now + 86400,
    )


def _set(tier: str | None) -> None:
    if tier is None:
        _state.set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
    else:
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_claims(tier)))


def test_in_tier_caller_sees_no_deprecation_headers() -> None:
    # Pro tier has ``continuity_check``; the helper should be a no-op.
    _set("pro")
    response = Response()
    apply_deprecation_headers(response, "continuity_check")
    assert "Deprecation" not in response.headers
    assert "Sunset" not in response.headers
    assert "X-Drevalis-Deprecation-Notice" not in response.headers


def test_out_of_tier_caller_gets_full_header_set() -> None:
    # Creator tier does NOT have ``continuity_check`` — headers fire.
    _set("creator")
    response = Response()
    apply_deprecation_headers(response, "continuity_check")
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"] == SUNSET_HTTP
    assert "successor-version" in response.headers["Link"]
    assert "Continuity check" in response.headers["X-Drevalis-Deprecation-Notice"]
    assert "Pro+" in response.headers["X-Drevalis-Deprecation-Notice"]


def test_unactivated_caller_gets_headers() -> None:
    # No license = no features. Treated like Creator for header purposes.
    _set(None)
    response = Response()
    apply_deprecation_headers(response, "elevenlabs")
    assert response.headers.get("Deprecation") == "true"


def test_sunset_value_is_valid_http_date() -> None:
    parsed = parsedate_to_datetime(SUNSET_HTTP)
    assert parsed == SUNSET_DATE


def test_sunset_is_in_the_future_relative_to_today() -> None:
    # Pin the policy: the sunset date must be in the future at release
    # time. If a future commit lets the date drift backward we want the
    # test to fail loudly so we re-decide rather than silently ship a
    # past-date deprecation header (which UAs may treat as immediately
    # sunsetted).
    assert SUNSET_DATE > datetime.now(tz=UTC), (
        "SUNSET_DATE has passed; either flip the routes to a hard "
        "require_feature gate or push the sunset date forward and ship "
        "another customer email cycle."
    )


def test_unknown_feature_uses_feature_name_in_notice() -> None:
    """Defensive: a feature name not in ``_FEATURE_DESCRIPTIONS`` still
    renders a sensible notice (falls back to the raw feature key).
    """
    _set("creator")
    response = Response()
    apply_deprecation_headers(response, "made_up_feature")
    assert "made_up_feature" in response.headers["X-Drevalis-Deprecation-Notice"]
