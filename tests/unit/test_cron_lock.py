"""Tests for the Redis-backed cron lock (workers/cron_lock.py).

The lock decides whether a multi-worker arq deployment double-fires
external side-effects (YouTube uploads, Stripe calls). Misses ship
as duplicate posts the user can see in their channels — high stakes,
worth pinning every branch.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from drevalis.workers.cron_lock import cron_lock


class TestCronLock:
    async def test_no_redis_in_ctx_runs_anyway(self) -> None:
        # Bare invocation (tests, single-worker dev): the lock degrades
        # to a no-op and yields True so the body runs.
        async with cron_lock({}, "x") as is_owner:
            assert is_owner is True

    async def test_acquired_yields_true(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)  # NX claim succeeded
        redis.eval = AsyncMock(return_value=1)
        async with cron_lock({"redis": redis}, "publish") as is_owner:
            assert is_owner is True
        redis.set.assert_awaited_once()
        # Atomic SET NX EX with right key + ttl.
        args, kwargs = redis.set.call_args
        assert args[0] == "cron:publish"
        assert kwargs["nx"] is True
        assert kwargs["ex"] == 280  # default

    async def test_custom_ttl(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.eval = AsyncMock(return_value=1)
        async with cron_lock({"redis": redis}, "x", ttl_s=60):
            pass
        assert redis.set.call_args.kwargs["ex"] == 60

    async def test_already_held_yields_false(self) -> None:
        # Second worker hits the same tick — SET NX returns falsy.
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=None)
        redis.eval = AsyncMock()
        async with cron_lock({"redis": redis}, "x") as is_owner:
            assert is_owner is False
        # Don't release a lock we don't own.
        redis.eval.assert_not_called()

    async def test_set_exception_runs_anyway(self) -> None:
        # Redis blip during SET NX: the contract says "fail open" — yield
        # True so the cron job still does its work. Slightly worse than
        # double-posting, much better than missing every cron tick when
        # Redis hiccups.
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=ConnectionError("redis offline"))
        redis.eval = AsyncMock()
        async with cron_lock({"redis": redis}, "x") as is_owner:
            assert is_owner is True
        # No release attempted — we never acquired.
        redis.eval.assert_not_called()

    async def test_release_uses_lua_compare_and_delete(self) -> None:
        # Lock release must compare the owner string before delete so a
        # TTL-reclaimed successor isn't accidentally clobbered.
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.eval = AsyncMock(return_value=1)

        async with cron_lock({"redis": redis}, "x"):
            pass

        # Lua eval called with the script + 1 key + owner string.
        redis.eval.assert_awaited_once()
        args = redis.eval.call_args.args
        # Signature: (script, num_keys, key, owner)
        script_text = args[0]
        assert "redis.call('get'" in script_text
        assert "redis.call('del'" in script_text
        assert args[1] == 1  # num_keys
        assert args[2] == "cron:x"  # KEYS[1]
        # ARGV[1] = owner — opaque per-process token, just confirm it exists.
        owner_token = args[3]
        assert isinstance(owner_token, str)
        assert ":" in owner_token  # hostname:pid:uuid8

    async def test_release_failure_swallowed(self) -> None:
        # Release-time errors must NOT propagate (job has already run
        # successfully; ensure the wrapper exits cleanly).
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.eval = AsyncMock(side_effect=RuntimeError("redis hiccup"))

        # Must not raise.
        async with cron_lock({"redis": redis}, "x"):
            pass

    async def test_owner_token_unique_per_call(self) -> None:
        # Two acquire attempts mint distinct owner tokens so a stale
        # release from one can't accidentally release the other.
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.eval = AsyncMock(return_value=1)

        owners: list[str] = []

        async def _capture(*args: Any, **kwargs: Any) -> bool:
            # SET key owner NX EX ttl
            owners.append(args[1])
            return True

        redis.set = AsyncMock(side_effect=_capture)
        async with cron_lock({"redis": redis}, "x"):
            pass
        async with cron_lock({"redis": redis}, "x"):
            pass

        assert len(owners) == 2
        assert owners[0] != owners[1]

    async def test_body_exception_still_releases_lock(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.eval = AsyncMock(return_value=1)

        with __import__("contextlib").suppress(RuntimeError):
            async with cron_lock({"redis": redis}, "x"):
                raise RuntimeError("body blew up")

        # The finally clause releases even on body errors.
        redis.eval.assert_awaited_once()

    async def test_no_release_when_lock_was_not_acquired(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=None)  # not acquired
        redis.eval = AsyncMock()
        async with cron_lock({"redis": redis}, "x"):
            pass
        # We never claimed the lock, so we don't try to delete it.
        redis.eval.assert_not_called()

    async def test_lock_name_namespaced_with_cron_prefix(self) -> None:
        # Pin the key prefix so future code can rely on a single
        # SCAN match for cron monitoring etc.
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.eval = AsyncMock(return_value=1)
        async with cron_lock({"redis": redis}, "publish_scheduled_posts"):
            pass
        assert redis.set.call_args.args[0] == "cron:publish_scheduled_posts"
