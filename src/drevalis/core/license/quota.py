"""Redis-backed daily quota counters for tier enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

from drevalis.core.license.features import TIER_DAILY_EPISODE_QUOTA
from drevalis.core.license.state import get_state

if TYPE_CHECKING:
    from redis.asyncio import Redis

_EPISODE_QUOTA_PREFIX = "license:episodes"
_TTL_SECONDS = 60 * 60 * 48  # 48h — counter covers the UTC day and decays next day


def _today_key() -> str:
    day = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    return f"{_EPISODE_QUOTA_PREFIX}:{day}"


async def check_and_increment_episode_quota(redis: Redis) -> None:
    """Raise 402 if the current tier has hit its daily episode cap.

    Called on the episode-generate endpoint, before enqueueing. Increments
    the counter atomically so concurrent requests are accounted for.
    Unlimited tiers (``None`` cap) short-circuit without touching Redis.
    """
    state = get_state()
    if not state.is_usable or state.claims is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "license_required", "state": state.status.value},
        )

    cap = TIER_DAILY_EPISODE_QUOTA.get(state.claims.tier)
    if cap is None:
        return  # unlimited

    key = _today_key()
    try:
        new_value = await redis.incr(key)
        if new_value == 1:
            await redis.expire(key, _TTL_SECONDS)
    except Exception:
        # Fail-open on Redis errors — losing a quota enforcement is
        # preferable to blocking legitimate users if Redis hiccups.
        return

    if new_value > cap:
        # Roll back the overshoot so repeated failing calls don't accumulate.
        try:
            await redis.decr(key)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "daily_quota_exceeded",
                "tier": state.claims.tier,
                "limit": cap,
            },
        )


async def get_daily_episode_usage(redis: Redis) -> dict[str, int | None]:
    """Return ``{used, limit}`` for display in the UI."""
    state = get_state()
    if not state.is_usable or state.claims is None:
        return {"used": 0, "limit": 0}
    cap = TIER_DAILY_EPISODE_QUOTA.get(state.claims.tier)
    try:
        raw = await redis.get(_today_key())
        used = int(raw) if raw else 0
    except Exception:
        used = 0
    return {"used": used, "limit": cap}
