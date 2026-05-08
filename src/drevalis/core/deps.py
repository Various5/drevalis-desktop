"""FastAPI dependency injection providers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.database import get_db_session
from drevalis.core.redis import get_redis as _get_redis


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton.

    Uses ``functools.lru_cache`` so the ``.env`` file is read at most once.
    """
    return Settings()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session (delegates to ``database.get_db_session``)."""
    async for session in get_db_session():
        yield session


async def get_redis() -> AsyncGenerator[Redis, None]:
    """Yield a Redis client from the connection pool."""
    async for client in _get_redis():
        yield client


def is_demo_mode(settings: Settings = Depends(get_settings)) -> bool:
    """Return True when the install is running in demo mode."""
    return bool(settings.demo_mode)


def require_not_demo(settings: Settings = Depends(get_settings)) -> None:
    """Refuse the request when demo mode is active.

    Use on destructive routes (DELETE, RESET, RESTORE, regenerate) that
    don't belong in a public playground.
    """
    if settings.demo_mode:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "disabled_in_demo",
        )
