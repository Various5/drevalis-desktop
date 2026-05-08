"""ApiKeyStoreService — encrypted-credentials orchestration.

Layering: keeps the router free of the encryption helper +
repository (audit F-A-01). The route handlers call this service;
this service is the only place that constructs
``ApiKeyStoreRepository`` and calls ``encrypt_value``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError
from drevalis.core.security import encrypt_value
from drevalis.repositories.api_key_store import ApiKeyStoreRepository


class ApiKeyStoreService:
    def __init__(
        self,
        db: AsyncSession,
        encryption_key: str,
        *,
        encryption_keys: dict[int, str] | None = None,
    ) -> None:
        self._db = db
        self._encryption_key = encryption_key
        # Versioned key map so writes carry the correct ``key_version``
        # tag after a rotation. This service is encrypt-only (callers
        # decrypt elsewhere).
        self._encryption_keys: dict[int, str] = encryption_keys or {1: encryption_key}
        self._repo = ApiKeyStoreRepository(db)

    def _encrypt(self, plaintext: str) -> tuple[str, int]:
        return encrypt_value(
            plaintext,
            self._encryption_key,
            version=max(self._encryption_keys),
        )

    async def list(self) -> list[Any]:
        """Return every stored entry. Encrypted values are not decrypted."""
        return await self._repo.get_all()

    async def upsert(self, *, key_name: str, api_key: str) -> None:
        """Encrypt + persist (or replace) one entry."""
        encrypted, key_version = self._encrypt(api_key)
        await self._repo.upsert(
            key_name=key_name,
            encrypted_value=encrypted,
            key_version=key_version,
        )
        await self._db.commit()

    async def delete(self, key_name: str) -> None:
        """Drop the entry for ``key_name``; raise NotFoundError if missing."""
        deleted = await self._repo.delete_by_key_name(key_name)
        if not deleted:
            raise NotFoundError("API key", key_name)
        await self._db.commit()

    async def list_stored_names(self) -> set[str]:
        """Return just the set of key_name strings (used by the
        integrations-status endpoint to skip a re-fetch)."""
        entries = await self._repo.get_all()
        return {e.key_name for e in entries}
