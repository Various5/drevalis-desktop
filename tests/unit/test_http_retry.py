"""Unit tests for the generic ``retry_async`` helper (F-CQ-08).

The httpx-specific ``request_with_retry`` is exercised via the
existing call sites; this file targets the new generic helper that
LLM/TTS sites use.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest

from drevalis.core.http_retry import retry_async


class _Boom(Exception):
    """Marker class used to drive retry decisions in the tests."""


class _NotRetryable(Exception):
    """Marker class used to assert fail-fast behaviour."""


async def test_first_attempt_succeeds_no_retry() -> None:
    fn = AsyncMock(return_value=42)
    result = await retry_async(
        fn,
        is_retryable=lambda _exc: True,
        max_attempts=3,
        base_backoff_s=0,
        max_backoff_s=0,
    )
    assert result == 42
    assert fn.await_count == 1


async def test_retries_until_success() -> None:
    fn = AsyncMock(side_effect=[_Boom("first"), _Boom("second"), "ok"])
    result = await retry_async(
        fn,
        is_retryable=lambda exc: isinstance(exc, _Boom),
        max_attempts=3,
        base_backoff_s=0,
        max_backoff_s=0,
    )
    assert result == "ok"
    assert fn.await_count == 3


async def test_non_retryable_propagates_immediately() -> None:
    fn = AsyncMock(side_effect=_NotRetryable("4xx"))
    with pytest.raises(_NotRetryable):
        await retry_async(
            fn,
            is_retryable=lambda exc: isinstance(exc, _Boom),  # only _Boom retries
            max_attempts=5,
            base_backoff_s=0,
            max_backoff_s=0,
        )
    # Predicate said no — must not have retried.
    assert fn.await_count == 1


async def test_max_attempts_exhausted_reraises_last() -> None:
    fn = AsyncMock(side_effect=[_Boom("a"), _Boom("b"), _Boom("c")])
    with pytest.raises(_Boom, match="c"):
        await retry_async(
            fn,
            is_retryable=lambda _exc: True,
            max_attempts=3,
            base_backoff_s=0,
            max_backoff_s=0,
        )
    assert fn.await_count == 3


async def test_predicate_receives_exception_instance() -> None:
    seen: list[type[BaseException]] = []

    def _predicate(exc: Exception) -> bool:
        seen.append(type(exc))
        return False  # fail fast on the first one

    fn = AsyncMock(side_effect=_Boom("hi"))
    with pytest.raises(_Boom):
        await retry_async(
            fn,
            is_retryable=_predicate,
            max_attempts=3,
            base_backoff_s=0,
            max_backoff_s=0,
        )
    assert seen == [_Boom]


async def test_label_forwarded_for_logging() -> None:
    """retry_async accepts a ``label`` kwarg even when not retried —
    just verify the signature doesn't reject it."""
    fn = AsyncMock(return_value="ok")
    result = await retry_async(
        fn,
        is_retryable=lambda _exc: True,
        max_attempts=2,
        base_backoff_s=0,
        max_backoff_s=0,
        label="some_label",
    )
    assert result == "ok"


async def test_typed_callable_signature() -> None:
    """retry_async preserves the callable's return type — no runtime
    check, but importing + assigning to a typed alias is the test."""
    fn: Callable[[], Awaitable[int]] = AsyncMock(return_value=7)
    result: int = await retry_async(
        fn,
        is_retryable=lambda _exc: True,
        max_attempts=1,
        base_backoff_s=0,
        max_backoff_s=0,
    )
    assert result == 7
