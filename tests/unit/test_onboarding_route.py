"""Tests for ``api/routes/onboarding.py``.

Three tiny endpoints — pin the contract:

* ``GET /status`` reports per-resource counts + ``should_show`` based on
  whether any of the three critical resources (comfyui / llm / voice)
  is still empty AND the wizard hasn't been dismissed.
* ``POST /dismiss`` sets the Redis flag.
* ``POST /reset`` clears the Redis flag (Help → "Re-run onboarding").
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from drevalis.api.routes.onboarding import (
    _REDIS_KEY,
    dismiss_onboarding,
    get_onboarding_status,
    reset_onboarding,
)


def _make_session(counts: dict[type, int]) -> Any:
    """Build a session whose ``execute(...).scalar_one()`` returns the
    count for whichever model the function is selecting from."""
    session = AsyncMock()
    call_idx = {"i": 0}
    # The route calls _count(ComfyUI), _count(LLM), _count(Voice), _count(YT)
    # in that order. We honour ordering rather than introspecting the SQL.
    order = list(counts.values())

    async def _execute(_stmt: Any) -> Any:
        result = MagicMock()
        result.scalar_one = MagicMock(return_value=order[call_idx["i"]])
        call_idx["i"] += 1
        return result

    session.execute = _execute  # type: ignore[assignment]
    return session


# ── GET /status ─────────────────────────────────────────────────────


class TestGetOnboardingStatus:
    async def test_should_show_when_critical_missing_and_not_dismissed(
        self,
    ) -> None:
        # Fresh install — every count zero, no dismiss flag → wizard pops up.
        session = _make_session({"comfyui": 0, "llm": 0, "voice": 0, "yt": 0})
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        resp = await get_onboarding_status(session=session, redis=redis)

        assert resp.comfyui_servers == 0
        assert resp.llm_configs == 0
        assert resp.voice_profiles == 0
        assert resp.youtube_channels == 0
        assert resp.dismissed is False
        assert resp.should_show is True

    async def test_should_not_show_when_dismissed(self) -> None:
        session = _make_session({"comfyui": 0, "llm": 0, "voice": 0, "yt": 0})
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")

        resp = await get_onboarding_status(session=session, redis=redis)

        assert resp.dismissed is True
        # Still missing critical resources, but explicit dismiss wins.
        assert resp.should_show is False

    async def test_should_not_show_when_all_critical_present(self) -> None:
        # YouTube count zero is fine — only the three critical resources
        # gate ``should_show``.
        session = _make_session({"comfyui": 1, "llm": 1, "voice": 1, "yt": 0})
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        resp = await get_onboarding_status(session=session, redis=redis)

        assert resp.dismissed is False
        assert resp.should_show is False

    async def test_partial_critical_keeps_wizard_open(self) -> None:
        # Two of three critical resources configured — one still missing
        # so the wizard must keep popping up.
        session = _make_session({"comfyui": 1, "llm": 1, "voice": 0, "yt": 5})
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        resp = await get_onboarding_status(session=session, redis=redis)

        assert resp.voice_profiles == 0
        assert resp.youtube_channels == 5
        assert resp.should_show is True


# ── POST /dismiss / /reset ──────────────────────────────────────────


class TestDismissAndReset:
    async def test_dismiss_sets_redis_key(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock()
        await dismiss_onboarding(redis=redis)
        redis.set.assert_awaited_once_with(_REDIS_KEY, "1")

    async def test_reset_deletes_redis_key(self) -> None:
        redis = AsyncMock()
        redis.delete = AsyncMock()
        await reset_onboarding(redis=redis)
        redis.delete.assert_awaited_once_with(_REDIS_KEY)
