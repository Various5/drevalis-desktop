"""Redis connection pool management."""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import ConnectionPool, Redis

from drevalis.core.config import Settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Module-level singletons, initialised during app lifespan.
_pool: ConnectionPool | None = None
_arq_pool: ArqRedis | None = None


async def _wait_for_redis_dns(
    url: str,
    *,
    total_seconds: float = 60.0,
    initial_delay: float = 1.0,
    max_delay: float = 5.0,
) -> None:
    """Resolve + TCP-connect the Redis host with backoff.

    arq's RedisSettings retry catches transient ``ConnectionError``
    once the hostname resolves but doesn't loop on DNS NX answers
    (``socket.gaierror: [Errno -5]``). On a fresh ``compose up``
    the worker / app can race ahead of Docker registering the
    redis service in its embedded DNS. This wrapper bridges that
    gap before handing the URL to ``create_pool``.
    """
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    deadline = time.monotonic() + total_seconds
    delay = initial_delay
    attempt = 0
    last_err: str = ""
    while True:
        attempt += 1
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=5.0,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            if attempt > 1:
                logger.info(
                    "redis_preflight_ok",
                    host=host,
                    port=port,
                    attempts=attempt,
                )
            return
        except socket.gaierror as exc:
            last_err = f"DNS lookup failed for {host}: {exc}"
        except (OSError, TimeoutError) as exc:
            last_err = f"connect to {host}:{port} failed: {type(exc).__name__}: {exc}"

        if time.monotonic() >= deadline:
            logger.error(
                "redis_preflight_timeout",
                host=host,
                port=port,
                total_seconds=total_seconds,
                attempts=attempt,
                last_error=last_err,
            )
            raise RuntimeError(
                f"Redis ({host}:{port}) not reachable after {total_seconds:.0f}s "
                f"and {attempt} attempts. Last error: {last_err}"
            )

        logger.warning(
            "redis_preflight_retry",
            host=host,
            port=port,
            attempt=attempt,
            error=last_err,
            next_delay=delay,
        )
        await asyncio.sleep(delay)
        delay = min(delay * 1.5, max_delay)


def _parse_redis_settings(url: str) -> RedisSettings:
    """Parse a redis:// URL into arq RedisSettings."""
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password,
        conn_timeout=5,
        conn_retries=5,
        conn_retry_delay=2,
    )


async def init_redis(settings: Settings) -> None:
    """Create the Redis connection pool and arq pool.

    Pre-flight waits for the Redis hostname to resolve + accept TCP
    before invoking arq's ``create_pool`` (whose retry budget can't
    cover Docker DNS races). After pre-flight succeeds, arq's own
    retry handles any in-flight hiccup.
    """
    global _pool, _arq_pool  # noqa: PLW0603

    await _wait_for_redis_dns(settings.redis_url)

    _pool = ConnectionPool.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=20,
        socket_connect_timeout=10,
        socket_timeout=30,
    )

    try:
        _arq_pool = await create_pool(_parse_redis_settings(settings.redis_url))
    except Exception as exc:
        logger.error(
            "redis_init_failed",
            url=settings.redis_url,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise


async def close_redis() -> None:
    """Close and release the Redis connection pool.

    Called once during the FastAPI lifespan shutdown phase.
    """
    global _pool, _arq_pool  # noqa: PLW0603

    if _arq_pool is not None:
        await _arq_pool.aclose()
        _arq_pool = None

    if _pool is not None:
        await _pool.aclose()
        _pool = None


def get_pool() -> ConnectionPool:
    """Return the current connection pool (must be initialised)."""
    if _pool is None:
        raise RuntimeError(
            "Redis connection pool is not initialised. "
            "Ensure init_redis() has been called during application startup."
        )
    return _pool


def get_arq_pool() -> ArqRedis:
    """Return the arq connection pool for enqueuing jobs."""
    if _arq_pool is None:
        raise RuntimeError(
            "arq connection pool is not initialised. "
            "Ensure init_redis() has been called during application startup."
        )
    return _arq_pool


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency that yields a Redis client from the pool.

    The client is automatically closed when the request finishes.
    """
    pool = get_pool()
    client: Redis = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()
