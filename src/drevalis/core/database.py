"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from drevalis.core.config import Settings

# Module-level singletons, initialised during app lifespan.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(settings: Settings) -> None:
    """Create the async engine and session factory.

    Called once during the FastAPI lifespan startup phase.
    """
    global _engine, _session_factory  # noqa: PLW0603

    _engine = create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        echo=settings.db_echo,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def close_db() -> None:
    """Dispose of the engine connection pool.

    Called once during the FastAPI lifespan shutdown phase.
    """
    global _engine, _session_factory  # noqa: PLW0603

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the current session factory (must be initialised)."""
    if _session_factory is None:
        raise RuntimeError(
            "Database session factory is not initialised. "
            "Ensure init_db() has been called during application startup."
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session.

    The session is automatically closed when the request finishes.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
