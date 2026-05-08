"""Repository for the ApiKeyStore model -- encrypted third-party API keys."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.api_key_store import ApiKeyStore

from .base import BaseRepository


class ApiKeyStoreRepository(BaseRepository[ApiKeyStore]):
    """CRUD repository for :class:`ApiKeyStore` entries.

    Each row maps a ``key_name`` slug to a Fernet-encrypted secret value.
    The base class provides ``get_by_id``, ``create``, ``update``, and
    ``delete``.  This subclass adds a lookup by ``key_name`` which is the
    primary access pattern for the API-key endpoints.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ApiKeyStore)

    async def get_by_key_name(self, key_name: str) -> ApiKeyStore | None:
        """Return the entry whose ``key_name`` matches, or *None*."""
        stmt = select(ApiKeyStore).where(ApiKeyStore.key_name == key_name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        key_name: str,
        encrypted_value: str,
        key_version: int,
    ) -> ApiKeyStore:
        """Insert or update the entry for *key_name*.

        If a row with this ``key_name`` already exists it is updated in place;
        otherwise a new row is created.  The caller must ``commit`` afterwards.
        """
        existing = await self.get_by_key_name(key_name)
        if existing is not None:
            updated = await self.update(
                existing.id,
                encrypted_value=encrypted_value,
                key_version=key_version,
            )
            # update() returns None only when the PK is missing, which cannot
            # happen here since we just fetched the row.
            assert updated is not None
            return updated
        return await self.create(
            key_name=key_name,
            encrypted_value=encrypted_value,
            key_version=key_version,
        )

    async def delete_by_key_name(self, key_name: str) -> bool:
        """Delete the entry by ``key_name``.  Returns *True* if it existed."""
        existing = await self.get_by_key_name(key_name)
        if existing is None:
            return False
        return await self.delete(existing.id)
