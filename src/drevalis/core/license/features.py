"""Tier / feature gating helpers used by routes and worker tasks."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, status

from drevalis.core.license.state import get_state

# Canonical tier → feature map. The license server SHOULD put the same
# features list into the JWT's ``features`` claim; this map is the local
# fallback used when the claim is empty (e.g. for legacy licenses) and also
# doubles as documentation of what each tier buys.
#
# ``creator`` is the post-rebrand name for ``solo``; both are kept in the
# maps below so legacy JWTs (issued before the rename) keep working.
# ``lifetime_pro`` inherits the Pro feature set.
#
# Feature names are derived directly from the marketing pricing matrix
# (drevalis.com/pricing). When the matrix changes, both this file and the
# marketing HTML must be updated together.
_CREATOR_FEATURES = frozenset(
    {
        "basic_generation",
        "scheduled_publish",
        "seo_preflight",
    }
)

_PRO_FEATURES = _CREATOR_FEATURES | frozenset(
    {
        "runpod",
        "audiobooks",
        "elevenlabs",  # ElevenLabs TTS + voice cloning
        "character_packs",  # Character + style locks
        "continuity_check",
        "social_tiktok",  # TikTok direct upload
        "multichannel",  # YouTube cap raised from 1 to 3
        "cross_platform_bulk",  # Bulk publish across connected platforms
    }
)

# Studio inherits Pro and adds the extended-social bundle, team mode, and
# REST API access. ``social_platforms`` is kept as a legacy alias so JWTs
# minted before the split keep granting Studio its full social bundle.
_STUDIO_FEATURES = _PRO_FEATURES | frozenset(
    {
        "social_extended",  # Instagram Reels + Facebook + X
        "social_platforms",  # legacy alias — granted at Studio for back-compat
        "team_mode",
        "api_access",
    }
)

TIER_FEATURES: dict[str, frozenset[str]] = {
    "trial": frozenset({"basic_generation"}),
    "solo": _CREATOR_FEATURES,
    "creator": _CREATOR_FEATURES,
    "pro": _PRO_FEATURES,
    "lifetime_pro": _PRO_FEATURES,
    "studio": _STUDIO_FEATURES,
}

# Per-tier parallel-generation cap. Mirrored on the marketing pricing
# matrix; enforced by ``services.generation_slots.tier_slot_cap`` rather
# than by routes directly.
TIER_PARALLEL_CAP: dict[str, int] = {
    "trial": 1,
    "solo": 2,
    "creator": 2,
    "pro": 6,
    "lifetime_pro": 6,
    "studio": 8,
}

# Machine seat cap per tier (enforced server-side at activation; this is the
# client-side mirror for UI display).
TIER_MACHINE_CAP: dict[str, int] = {
    "trial": 1,
    "solo": 1,
    "creator": 1,
    "pro": 3,
    "lifetime_pro": 3,
    "studio": 5,
}

# Daily episode quota per tier; ``None`` means unlimited. Enforced in
# ``quota.check_episode_quota``.
#
# Creator is unlimited as of the pricing refresh — the old 30-episodes-per-
# month cap has been removed. ``solo`` mirrors the new unlimited value so
# legacy licenses don't silently regress.
TIER_DAILY_EPISODE_QUOTA: dict[str, int | None] = {
    "trial": 3,
    "solo": None,
    "creator": None,
    "pro": None,
    "lifetime_pro": None,
    "studio": None,
}

# Max YouTube channels per tier.
TIER_CHANNEL_CAP: dict[str, int] = {
    "trial": 1,
    "solo": 1,
    "creator": 1,
    "pro": 3,
    "lifetime_pro": 3,
    "studio": 1_000,
}


def current_tier() -> str | None:
    state = get_state()
    if not state.is_usable or state.claims is None:
        return None
    return state.claims.tier


def current_parallel_cap(global_default: int) -> int:
    """Return the active license's parallel-generation cap.

    Falls back to ``global_default`` (typically ``settings.max_concurrent_generations``)
    when no tier is active so headless / dev environments keep working.
    """
    tier = current_tier()
    if tier is None:
        return global_default
    return TIER_PARALLEL_CAP.get(tier, global_default)


def _current_feature_set() -> frozenset[str]:
    state = get_state()
    if not state.is_usable or state.claims is None:
        return frozenset()
    tier = state.claims.tier
    # Union the JWT's explicit ``features`` claim with the canonical
    # ``TIER_FEATURES`` set for the same tier. The license server
    # snapshots tier features into the JWT at mint time; if a new
    # feature later joins that tier server-side, every previously
    # minted license would otherwise 402 on it forever (since JWTs
    # are not reissued automatically). Unioning means: a license can
    # never grant LESS than its own tier's currently-documented
    # feature set, and an explicit claim can still grant MORE (e.g.
    # an upsell add-on or grandfathered feature on a lower tier).
    tier_features = TIER_FEATURES.get(tier, frozenset())
    claim_features = frozenset(state.claims.features) if state.claims.features else frozenset()
    return tier_features | claim_features


def has_feature(feature: str) -> bool:
    return feature in _current_feature_set()


def require_feature(feature: str) -> None:
    """FastAPI dependency: raise 402 if the current license lacks ``feature``.

    Use as ``Depends(lambda: require_feature("runpod"))`` or wrap in a small
    ``Depends`` factory — see ``fastapi_dep`` below.
    """
    state = get_state()
    if not state.is_usable:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "license_required", "state": state.status.value},
        )
    if feature not in _current_feature_set():
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "feature_not_in_tier",
                "feature": feature,
                "tier": state.claims.tier if state.claims else None,
            },
        )


def require_tier(minimum: str) -> None:
    """Raise 402 unless the current tier is ``>=`` the minimum.

    Ordering: trial < solo/creator < pro/lifetime_pro < studio.

    ``solo`` and ``creator`` share rank 1 (the rebrand preserved seat
    semantics). ``lifetime_pro`` shares rank 2 with ``pro`` — a Lifetime
    license satisfies any ``require_tier("pro")`` gate.
    """
    order = {
        "trial": 0,
        "solo": 1,
        "creator": 1,
        "pro": 2,
        "lifetime_pro": 2,
        "studio": 3,
    }
    state = get_state()
    if not state.is_usable or state.claims is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "license_required", "state": state.status.value},
        )
    current_rank = order.get(state.claims.tier, -1)
    required_rank = order.get(minimum, 999)
    if current_rank < required_rank:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "tier_too_low",
                "required": minimum,
                "current": state.claims.tier,
            },
        )


def fastapi_dep_require_feature(feature: str) -> Callable[[], None]:
    """Factory that returns a FastAPI dependency for ``require_feature``.

    Usage:
        @router.post("/...", dependencies=[Depends(fastapi_dep_require_feature("runpod"))])
    """

    def _dep() -> None:
        require_feature(feature)

    return _dep


def fastapi_dep_require_tier(minimum: str) -> Callable[[], None]:
    def _dep() -> None:
        require_tier(minimum)

    return _dep
