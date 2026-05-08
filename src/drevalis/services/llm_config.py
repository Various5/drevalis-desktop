"""LLMConfigService — CRUD over the ``llm_configs`` table.

Layering: keeps the route file free of repository imports and the
encryption helper (audit F-A-01). The router used to import both
``LLMConfigRepository`` and ``encrypt_value`` directly.

Note: there's already an ``LLMService`` in ``services/llm`` that owns
runtime LLM provider orchestration. This is a separate, narrower
service for the *configuration row* CRUD.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.security import encrypt_value
from drevalis.models.llm_config import LLMConfig
from drevalis.repositories.llm_config import LLMConfigRepository


class LLMConfigService:
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
        # tag after a rotation. Decryption happens elsewhere
        # (``LLMService``); this service is encrypt-only.
        self._encryption_keys: dict[int, str] = encryption_keys or {1: encryption_key}
        self._repo = LLMConfigRepository(db)

    def _encrypt(self, plaintext: str) -> tuple[str, int]:
        """Encrypt + tag with the current key version so post-rotation
        re-encryption sweeps can filter rows by stale-version."""
        return encrypt_value(
            plaintext,
            self._encryption_key,
            version=max(self._encryption_keys),
        )

    async def list_all(self) -> list[LLMConfig]:
        return await self._repo.get_all()

    async def get(self, config_id: UUID) -> LLMConfig:
        config = await self._repo.get_by_id(config_id)
        if config is None:
            raise NotFoundError("LLM config", config_id)
        return config

    async def create(
        self,
        *,
        name: str,
        base_url: str,
        model_name: str,
        api_key: str | None,
        max_tokens: int,
        temperature: float,
    ) -> LLMConfig:
        api_key_encrypted: str | None = None
        api_key_version = 1
        if api_key:
            api_key_encrypted, api_key_version = self._encrypt(api_key)

        config = await self._repo.create(
            name=name,
            base_url=base_url,
            model_name=model_name,
            api_key_encrypted=api_key_encrypted,
            api_key_version=api_key_version,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        await self._db.commit()
        await self._db.refresh(config)
        return config

    async def update(self, config_id: UUID, **patch: Any) -> LLMConfig:
        if not patch:
            raise ValidationError("No fields to update")

        # Handle API key encryption inline so the route doesn't need the
        # encryption helper.
        if "api_key" in patch:
            raw_key = patch.pop("api_key")
            if raw_key is not None:
                encrypted, version = self._encrypt(raw_key)
                patch["api_key_encrypted"] = encrypted
                patch["api_key_version"] = version
            else:
                patch["api_key_encrypted"] = None

        config = await self._repo.update(config_id, **patch)
        if config is None:
            raise NotFoundError("LLM config", config_id)
        await self._db.commit()
        await self._db.refresh(config)
        return config

    async def delete(self, config_id: UUID) -> None:
        deleted = await self._repo.delete(config_id)
        if not deleted:
            raise NotFoundError("LLM config", config_id)
        await self._db.commit()

    async def expunge(self, config: LLMConfig) -> None:
        """Detach an instance from the session.

        Used by the test endpoint before passing the ORM row through
        the LLMService — keeps an autoflush from persisting decrypted
        values back to the row (M5 fix from the March audit).
        """
        self._db.expunge(config)
