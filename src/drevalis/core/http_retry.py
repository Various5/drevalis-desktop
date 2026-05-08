"""Shared ``request_with_retry`` wrapper for outbound httpx calls.

Purpose: every external API we talk to (Anthropic, OpenAI, ElevenLabs,
YouTube Data, TikTok, Instagram, Meta Graph, RunPod) occasionally
returns HTTP 429 or 503, and a meaningful fraction of those responses
include a ``Retry-After`` header. Without honouring them, a single
minute of throttling on the upstream cascades into a pipeline failure
and (worse) incorrect "service down" logs.

This helper:

* Retries on HTTP 429 / 502 / 503 / 504 and on httpx transport errors.
* Respects the ``Retry-After`` header when present (seconds or HTTP-date).
* Otherwise falls back to exponential backoff with jitter.
* Gives up after ``max_attempts`` and raises the last exception OR
  returns the last response so the caller can surface the final error.

Non-goals: we do NOT retry 4xx other than 429 (those are client bugs).
We do NOT drain the response body when not retrying — caller owns the
returned ``httpx.Response``.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx
import structlog

_T = TypeVar("_T")

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})
_RETRYABLE_EXC = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


def _parse_retry_after(value: str | None) -> float | None:
    """Best-effort parse of a ``Retry-After`` header.

    Accepts the two forms RFC 9110 permits: delta-seconds (e.g. ``"5"``)
    and HTTP-date (e.g. ``"Wed, 21 Oct 2026 07:28:00 GMT"``). Returns the
    suggested wait in seconds, or ``None`` if the header is missing or
    unparseable (caller falls back to exponential backoff).
    """
    if not value:
        return None
    v = value.strip()
    # delta-seconds
    try:
        seconds = float(v)
        if seconds >= 0:
            return min(seconds, 600.0)  # cap at 10 minutes so a hostile
            # header can't hang us indefinitely
    except ValueError:
        pass
    # HTTP-date
    try:
        import datetime as _dt

        when = parsedate_to_datetime(v)
        now = _dt.datetime.now(tz=when.tzinfo) if when.tzinfo else _dt.datetime.now()
        delta = (when - now).total_seconds()
        return min(max(0.0, delta), 600.0)
    except (TypeError, ValueError):
        return None


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 5,
    base_backoff_s: float = 1.0,
    max_backoff_s: float = 30.0,
    label: str | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Send ``method url`` with retry/backoff on 429/5xx + transport errors.

    Returns the final :class:`httpx.Response`. Raises the last
    transport exception when every attempt failed to receive one.

    Callers should still check ``response.status_code`` — the helper
    only re-tries a bounded set of statuses and returns the response
    on the final attempt regardless.
    """
    last_exc: Exception | None = None
    last_response: httpx.Response | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await client.request(method, url, **kwargs)
        except _RETRYABLE_EXC as exc:
            last_exc = exc
            last_response = None
            wait = min(
                max_backoff_s,
                base_backoff_s * (2 ** (attempt - 1)) * (0.5 + random.random()),
            )
            logger.warning(
                "http_retry_transport_error",
                label=label or url,
                attempt=attempt,
                wait_s=round(wait, 2),
                error=str(exc)[:150],
            )
            if attempt == max_attempts:
                break
            await asyncio.sleep(wait)
            continue

        if resp.status_code not in _RETRYABLE_STATUSES:
            return resp

        last_response = resp
        last_exc = None
        wait = _parse_retry_after(resp.headers.get("retry-after"))
        if wait is None:
            wait = min(
                max_backoff_s,
                base_backoff_s * (2 ** (attempt - 1)) * (0.5 + random.random()),
            )
        logger.warning(
            "http_retry_retryable_status",
            label=label or url,
            attempt=attempt,
            status=resp.status_code,
            wait_s=round(wait, 2),
            retry_after_header=resp.headers.get("retry-after"),
        )
        if attempt == max_attempts:
            return resp
        # Close the consumable body so we don't leak the underlying
        # connection across retries.
        await resp.aclose()
        await asyncio.sleep(wait)

    if last_response is not None:
        return last_response
    assert last_exc is not None
    raise last_exc


async def retry_async(
    fn: Callable[[], Awaitable[_T]],
    *,
    is_retryable: Callable[[Exception], bool],
    max_attempts: int = 3,
    base_backoff_s: float = 5.0,
    max_backoff_s: float = 60.0,
    label: str | None = None,
) -> _T:
    """Generic async retry wrapper for non-httpx callables.

    Parameters
    ----------
    fn:
        Zero-arg async callable. The callable is invoked up to
        ``max_attempts`` times.
    is_retryable:
        Predicate that decides whether to retry a particular exception.
        Anything the predicate returns ``False`` for re-raises immediately
        (so 4xx auth errors can fail fast while 5xx retries).
    max_attempts:
        Total number of attempts including the first. Default ``3``.
    base_backoff_s / max_backoff_s:
        Exponential backoff with jitter, capped at ``max_backoff_s``.
    label:
        Free-form string for log lines.

    Used for SDK call sites (OpenAI, Anthropic, ElevenLabs) where the
    httpx-specific ``request_with_retry`` doesn't fit because the caller
    isn't talking to httpx directly. F-CQ-08.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - predicate decides
            if not is_retryable(exc):
                raise
            last_exc = exc
            if attempt == max_attempts:
                break
            wait = min(
                max_backoff_s,
                base_backoff_s * (2 ** (attempt - 1)) * (0.5 + random.random()),
            )
            logger.warning(
                "retry_async",
                label=label or "fn",
                attempt=attempt,
                wait_s=round(wait, 2),
                error_type=type(exc).__name__,
                error=str(exc)[:150],
            )
            await asyncio.sleep(wait)
    assert last_exc is not None
    raise last_exc


__all__ = ["request_with_retry", "retry_async"]
