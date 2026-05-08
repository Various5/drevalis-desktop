"""Tests for the soft-instrumentation helper (core/license/usage.py).

The helper wraps a structlog ``info`` call with the current tier +
whether the tier nominally has the feature. It deliberately does
nothing else — no exception, no behavioral change. These tests pin
the event payload across the four interesting license states so we
catch any regression that breaks the telemetry signal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from structlog.testing import capture_logs

from drevalis.core.license import state as _state
from drevalis.core.license import usage
from drevalis.core.license.claims import LicenseClaims
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


def _set(tier: str | None, features: list[str] | None = None) -> None:
    if tier is None:
        _state.set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
    else:
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_claims(tier, features)))


class TestLogFeatureUsage:
    def setup_method(self) -> None:
        _set(None)
        # ``capture_logs`` only intercepts events when the test logger
        # has a structlog renderer in its chain. Force the default
        # configuration so the helper's logger is captured regardless
        # of what an earlier test left behind.
        structlog.reset_defaults()

    def test_no_license_logs_null_tier_and_not_in_tier(self) -> None:
        with capture_logs() as logs:
            usage.log_feature_usage("audiobooks")

        assert len(logs) == 1
        event = logs[0]
        assert event["event"] == "feature_usage"
        assert event["feature"] == "audiobooks"
        assert event["tier"] is None
        assert event["in_tier"] is False

    def test_tier_grants_feature(self) -> None:
        # Creator tier nominally has basic_generation per TIER_FEATURES.
        _set("creator")
        with capture_logs() as logs:
            usage.log_feature_usage("basic_generation")

        assert len(logs) == 1
        event = logs[0]
        assert event["tier"] == "creator"
        assert event["in_tier"] is True

    def test_tier_lacks_feature(self) -> None:
        # Audiobooks is Pro+; a Creator tier license does NOT have it.
        # This is the case the soft instrumentation specifically exists
        # to count — a Creator user is hitting an unguarded paid
        # endpoint.
        _set("creator")
        with capture_logs() as logs:
            usage.log_feature_usage("audiobooks")

        assert len(logs) == 1
        event = logs[0]
        assert event["tier"] == "creator"
        assert event["in_tier"] is False
        assert event["feature"] == "audiobooks"

    def test_explicit_jwt_claim_grants_feature_above_tier_default(self) -> None:
        # Creator tier doesn't have ``audiobooks`` by default but the
        # JWT carries an explicit grant. The helper reflects what the
        # ``require_feature`` gate would actually decide — it queries
        # the same ``_current_feature_set`` union.
        _set("creator", features=["audiobooks"])
        with capture_logs() as logs:
            usage.log_feature_usage("audiobooks")

        assert len(logs) == 1
        assert logs[0]["in_tier"] is True

    def test_helper_never_raises(self) -> None:
        # Defensive: the helper is dropped at the top of handlers and
        # must never disrupt the request path. This test deliberately
        # corrupts the license state to a partially-constructed object
        # to cover the "what if a future refactor breaks state.claims"
        # concern.
        broken: Any = LicenseState(status=LicenseStatus.UNACTIVATED)
        _state.set_state(broken)
        with capture_logs() as logs:
            usage.log_feature_usage("anything")

        assert len(logs) == 1
