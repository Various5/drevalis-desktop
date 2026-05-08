"""Generic async base repository for SQLAlchemy 2.x models."""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """CRUD helper wrapping an async SQLAlchemy session for a single model.

    Subclass and override *model* in the constructor::

        class SeriesRepository(BaseRepository[Series]):
            def __init__(self, session: AsyncSession):
                super().__init__(session, Series)
    """

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    # ── Read ────────────────────────────────────────────────────────────

    async def get_by_id(self, id: UUID) -> ModelT | None:
        """Fetch a single entity by primary key, or *None*."""
        return await self.session.get(self.model, id)

    async def get_all(
        self,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ModelT]:
        """Return a paginated list of entities ordered by creation time."""
        stmt = (
            select(self.model)
            .order_by(self.model.created_at.desc())  # type: ignore[attr-defined]
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        """Return the total number of rows for this model."""
        stmt = select(func.count()).select_from(self.model)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # ── Write ───────────────────────────────────────────────────────────

    async def create(self, **kwargs: Any) -> ModelT:
        """Insert a new row and return the refreshed ORM instance."""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, id: UUID, **kwargs: Any) -> ModelT | None:
        """Update an existing row by PK.  Returns *None* if not found."""
        instance = await self.session.get(self.model, id)
        if instance is None:
            return None
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, id: UUID) -> bool:
        """Delete by PK.  Returns *True* if the row existed."""
        instance = await self.session.get(self.model, id)
        if instance is None:
            return False
        await self.session.delete(instance)
        await self.session.flush()
        return True
