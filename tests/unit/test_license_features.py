"""Tests for tier / feature gating helpers (core/license/features.py).

These functions sit in front of every paid endpoint. A subtle bug
(wrong tier rank, JWT features claim ignored, fallback table drift)
silently grants or denies access to paid features. Each branch is
pinned with a direct test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from drevalis.core.license import features as _features
from drevalis.core.license import state as _state
from drevalis.core.license.claims import LicenseClaims
from drevalis.core.license.state import LicenseState, LicenseStatus


def _claims(tier: str, features: list[str] | None = None, **overrides: Any) -> LicenseClaims:
    now = int(datetime.now(tz=UTC).timestamp())
    base: dict[str, Any] = {
        "iss": "x",
        "sub": "x",
        "jti": "x",
        "tier": tier,
        "features": features or [],
        "iat": now - 100,
        "nbf": now - 100,
        "exp": now + 86400,
        "period_end": now + 86400,
    }
    base.update(overrides)
    return LicenseClaims(**base)


def _set(tier: str | None, features: list[str] | None = None) -> None:
    if tier is None:
        _state.set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
    else:
        _state.set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=_claims(tier, features)))


# ── _current_feature_set / has_feature ───────────────────────────────


class TestFeatureSet:
    def setup_method(self) -> None:
        _set(None)

    def test_unactivated_yields_empty_set(self) -> None:
        assert _features._current_feature_set() == frozenset()
        assert _features.has_feature("basic_generation") is False

    def test_explicit_features_claim_unions_with_tier_default(self) -> None:
        # JWT carries an explicit ``features=["custom1"]`` claim. The
        # gate UNIONS that with the canonical TIER_FEATURES["creator"]
        # set so a license can never grant LESS than its tier's
        # currently-documented features (the tier set may have grown
        # since the JWT was minted), and the explicit claim can still
        # add extra features (upsell / grandfathered feature).
        _set("creator", features=["custom1"])
        result = _features._current_feature_set()
        assert "custom1" in result  # explicit add survives
        assert "basic_generation" in result  # tier default also granted
        assert _features.has_feature("custom1") is True
        assert _features.has_feature("basic_generation") is True

    def test_stale_claim_still_gets_new_tier_features(self) -> None:
        # Regression: licenses minted before a feature joined the tier
        # used to 402 on the new feature forever. With the union, a
        # stale claim that omits ``seo_preflight`` still grants it as
        # long as the tier currently includes it.
        _set("studio", features=["basic_generation", "runpod"])  # stale, missing seo_preflight
        assert _features.has_feature("seo_preflight") is True
        assert _features.has_feature("audiobooks") is True

    def test_empty_features_claim_falls_back_to_tier_default(self) -> None:
        _set("pro", features=[])
        assert "basic_generation" in _features._current_feature_set()
        assert _features.has_feature("runpod") is True

    def test_unknown_tier_returns_empty(self) -> None:
        _set("mythical_tier")
        assert _features._current_feature_set() == frozenset()


# ── require_feature ──────────────────────────────────────────────────


class TestRequireFeature:
    def setup_method(self) -> None:
        _set(None)

    def test_unactivated_raises_402(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _features.require_feature("basic_generation")
        assert exc.value.status_code == 402
        assert exc.value.detail["error"] == "license_required"  # type: ignore[index]

    def test_missing_feature_raises_402_with_payload(self) -> None:
        _set("creator")  # creator only has basic_generation
        with pytest.raises(HTTPException) as exc:
            _features.require_feature("runpod")
        assert exc.value.status_code == 402
        detail = exc.value.detail
        assert isinstance(detail, dict)
        assert detail["error"] == "feature_not_in_tier"
        assert detail["feature"] == "runpod"
        assert detail["tier"] == "creator"

    def test_present_feature_returns_silently(self) -> None:
        _set("pro")
        # Pro has runpod + audiobooks.
        _features.require_feature("runpod")
        _features.require_feature("audiobooks")

    def test_studio_has_premium_features(self) -> None:
        _set("studio")
        _features.require_feature("multichannel")
        _features.require_feature("social_platforms")
        _features.require_feature("api_access")

    def test_lifetime_pro_inherits_pro_features(self) -> None:
        _set("lifetime_pro")
        _features.require_feature("runpod")
        _features.require_feature("audiobooks")

    def test_explicit_features_claim_overrides_tier(self) -> None:
        # Server-issued features claim overrides client-side tier table.
        _set("trial", features=["runpod"])
        # runpod normally requires Pro+, but the claim grants it.
        _features.require_feature("runpod")


# ── require_tier ─────────────────────────────────────────────────────


class TestRequireTier:
    def setup_method(self) -> None:
        _set(None)

    def test_unactivated_raises_license_required(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _features.require_tier("creator")
        assert exc.value.detail["error"] == "license_required"  # type: ignore[index]

    def test_lower_tier_raises_with_payload(self) -> None:
        _set("creator")
        with pytest.raises(HTTPException) as exc:
            _features.require_tier("pro")
        assert exc.value.status_code == 402
        detail = exc.value.detail
        assert isinstance(detail, dict)
        assert detail["error"] == "tier_too_low"
        assert detail["required"] == "pro"
        assert detail["current"] == "creator"

    def test_equal_tier_passes(self) -> None:
        _set("pro")
        _features.require_tier("pro")

    def test_higher_tier_passes(self) -> None:
        _set("studio")
        _features.require_tier("pro")

    def test_solo_and_creator_share_rank(self) -> None:
        # The rebrand preserved seat semantics — both pass require_tier("solo").
        _set("solo")
        _features.require_tier("solo")
        _features.require_tier("creator")
        _set("creator")
        _features.require_tier("solo")

    def test_lifetime_pro_satisfies_require_pro(self) -> None:
        _set("lifetime_pro")
        _features.require_tier("pro")

    def test_pro_satisfies_require_lifetime_pro(self) -> None:
        # Same rank — symmetric.
        _set("pro")
        _features.require_tier("lifetime_pro")

    def test_unknown_tier_treated_as_below_everything(self) -> None:
        _set("mythical_tier")
        with pytest.raises(HTTPException):
            _features.require_tier("trial")

    def test_unknown_minimum_treated_as_above_everything(self) -> None:
        _set("studio")
        # Unknown minimum → required_rank=999 → studio (rank 3) < 999 → raises.
        with pytest.raises(HTTPException):
            _features.require_tier("mythical_tier")


# ── fastapi_dep factories ────────────────────────────────────────────


class TestFastapiDepFactories:
    def setup_method(self) -> None:
        _set(None)

    def test_dep_require_feature_returns_callable(self) -> None:
        dep = _features.fastapi_dep_require_feature("runpod")
        assert callable(dep)

    def test_dep_require_feature_invokes_check(self) -> None:
        _set("creator")
        dep = _features.fastapi_dep_require_feature("runpod")
        with pytest.raises(HTTPException):
            dep()

    def test_dep_require_feature_passes_when_present(self) -> None:
        _set("pro")
        dep = _features.fastapi_dep_require_feature("runpod")
        dep()  # no raise

    def test_dep_require_tier_invokes_check(self) -> None:
        _set("trial")
        dep = _features.fastapi_dep_require_tier("pro")
        with pytest.raises(HTTPException):
            dep()

    def test_dep_require_tier_passes_when_satisfied(self) -> None:
        _set("studio")
        dep = _features.fastapi_dep_require_tier("pro")
        dep()


# ── Tier table consistency ───────────────────────────────────────────


class TestTierTables:
    def test_every_tier_present_in_every_table(self) -> None:
        # The rebrand left many parallel tier→X dicts; this guards against
        # a new tier being added to one map and forgotten in another.
        canonical = {"trial", "solo", "creator", "pro", "lifetime_pro", "studio"}
        assert canonical <= _features.TIER_FEATURES.keys()
        assert canonical <= _features.TIER_MACHINE_CAP.keys()
        assert canonical <= _features.TIER_DAILY_EPISODE_QUOTA.keys()
        assert canonical <= _features.TIER_CHANNEL_CAP.keys()

    def test_lifetime_pro_features_match_pro(self) -> None:
        assert _features.TIER_FEATURES["lifetime_pro"] == _features.TIER_FEATURES["pro"]

    def test_solo_and_creator_features_match(self) -> None:
        # The post-rebrand contract: legacy ``solo`` licenses behave as
        # ``creator`` licenses.
        assert _features.TIER_FEATURES["solo"] == _features.TIER_FEATURES["creator"]

    def test_studio_is_a_strict_superset_of_pro(self) -> None:
        assert _features.TIER_FEATURES["pro"] <= _features.TIER_FEATURES["studio"]

    def test_machine_caps_monotonic(self) -> None:
        # Higher tier → equal-or-greater seat count.
        assert (
            _features.TIER_MACHINE_CAP["trial"]
            <= _features.TIER_MACHINE_CAP["creator"]
            <= _features.TIER_MACHINE_CAP["pro"]
            <= _features.TIER_MACHINE_CAP["studio"]
        )

    def test_pro_and_lifetime_pro_seat_caps_match(self) -> None:
        assert _features.TIER_MACHINE_CAP["pro"] == _features.TIER_MACHINE_CAP["lifetime_pro"]

    def test_paid_tiers_have_unlimited_episode_quota(self) -> None:
        # Trial is the only tier with a numeric cap.
        for tier in ("solo", "creator", "pro", "lifetime_pro", "studio"):
            assert _features.TIER_DAILY_EPISODE_QUOTA[tier] is None
        assert isinstance(_features.TIER_DAILY_EPISODE_QUOTA["trial"], int)
