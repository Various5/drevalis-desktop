"""ComfyUIServerService + ComfyUIWorkflowService — admin-side CRUD.

Layering: keeps the comfyui router free of repository imports plus
the encryption/validation helpers (audit F-A-01). Two services rather
than one because the comfyui router covers two distinct resources.

These are the *config-row* services. ``services/comfyui`` (the
package) hosts the runtime ``ComfyUIClient`` + ``ComfyUIPool`` that
the pipeline talks to during generation — different concern.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.security import decrypt_value, decrypt_value_multi, encrypt_value
from drevalis.core.validators import UnsafeURLError, validate_safe_url_or_localhost
from drevalis.models.comfyui import ComfyUIServer, ComfyUIWorkflow
from drevalis.repositories.comfyui import (
    ComfyUIServerRepository,
    ComfyUIWorkflowRepository,
)
from drevalis.schemas.comfyui import WorkflowInputMapping


class ComfyUIServerService:
    def __init__(
        self,
        db: AsyncSession,
        encryption_key: str,
        *,
        encryption_keys: dict[int, str] | None = None,
    ) -> None:
        self._db = db
        self._encryption_key = encryption_key  # used for new ENCRYPT writes
        # Versioned key map for DECRYPT: when caller passes the full
        # ``settings.get_encryption_keys()`` dict, rows encrypted under a
        # historical ``ENCRYPTION_KEY_V<N>`` still decrypt after rotation.
        # When ``encryption_keys`` is None we synthesise a single-version
        # map so the helper code below has one shape to handle.
        self._encryption_keys: dict[int, str] = encryption_keys or {1: encryption_key}
        self._repo = ComfyUIServerRepository(db)

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt against the versioned key map. Falls back to the
        single-key path when only one key is loaded so existing tests
        that patch ``decrypt_value`` directly keep working."""
        if len(self._encryption_keys) > 1:
            plaintext, _ = decrypt_value_multi(ciphertext, self._encryption_keys)
            return plaintext
        return decrypt_value(ciphertext, self._encryption_key)

    def _encrypt(self, plaintext: str) -> tuple[str, int]:
        """Encrypt with the current key + tag with its version so a
        background re-encryption sweep can later filter rows with
        ``key_version < current_version``."""
        return encrypt_value(
            plaintext,
            self._encryption_key,
            version=max(self._encryption_keys),
        )

    async def list_all(self) -> list[ComfyUIServer]:
        return await self._repo.get_all()

    async def get(self, server_id: UUID) -> ComfyUIServer:
        server = await self._repo.get_by_id(server_id)
        if server is None:
            raise NotFoundError("ComfyUI server", server_id)
        return server

    async def create(
        self,
        *,
        name: str,
        url: str,
        api_key: str | None,
        max_concurrent: int,
        is_active: bool,
    ) -> ComfyUIServer:
        try:
            validate_safe_url_or_localhost(url)
        except UnsafeURLError as exc:
            raise ValidationError(f"Invalid server URL: {exc}") from exc

        api_key_encrypted: str | None = None
        api_key_version = 1
        if api_key:
            api_key_encrypted, api_key_version = self._encrypt(api_key)

        server = await self._repo.create(
            name=name,
            url=url,
            api_key_encrypted=api_key_encrypted,
            api_key_version=api_key_version,
            max_concurrent=max_concurrent,
            is_active=is_active,
        )
        await self._db.commit()
        await self._db.refresh(server)
        return server

    async def update(self, server_id: UUID, **patch: Any) -> ComfyUIServer:
        if not patch:
            raise ValidationError("No fields to update")

        if "api_key" in patch:
            raw_key = patch.pop("api_key")
            if raw_key is not None:
                encrypted, version = self._encrypt(raw_key)
                patch["api_key_encrypted"] = encrypted
                patch["api_key_version"] = version
            else:
                patch["api_key_encrypted"] = None

        server = await self._repo.update(server_id, **patch)
        if server is None:
            raise NotFoundError("ComfyUI server", server_id)
        await self._db.commit()
        await self._db.refresh(server)
        return server

    async def delete(self, server_id: UUID) -> None:
        deleted = await self._repo.delete(server_id)
        if not deleted:
            raise NotFoundError("ComfyUI server", server_id)
        await self._db.commit()

    async def decrypt_api_key(self, server: ComfyUIServer) -> str | None:
        """Best-effort decrypt; returns None on failure (matches the
        previous in-route swallow-and-continue behaviour)."""
        if not server.api_key_encrypted:
            return None
        try:
            return self._decrypt(server.api_key_encrypted)
        except Exception:
            return None

    async def record_test_status(self, server_id: UUID, status_label: str) -> None:
        await self._repo.update_test_status(server_id, status_label, datetime.now(UTC))
        await self._db.commit()


class ComfyUIWorkflowService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = ComfyUIWorkflowRepository(db)

    async def list_all(self) -> list[ComfyUIWorkflow]:
        return await self._repo.get_all()

    async def get(self, workflow_id: UUID) -> ComfyUIWorkflow:
        wf = await self._repo.get_by_id(workflow_id)
        if wf is None:
            raise NotFoundError("ComfyUI workflow", workflow_id)
        return wf

    async def create(self, **payload: Any) -> ComfyUIWorkflow:
        # Validate input_mappings shape before insert.
        try:
            WorkflowInputMapping.model_validate(payload.get("input_mappings"))
        except Exception as exc:
            raise ValidationError(f"Invalid input_mappings: {exc}") from exc

        wf = await self._repo.create(**payload)
        await self._db.commit()
        await self._db.refresh(wf)
        return wf

    async def update(self, workflow_id: UUID, **patch: Any) -> ComfyUIWorkflow:
        if not patch:
            raise ValidationError("No fields to update")

        if "input_mappings" in patch and patch["input_mappings"] is not None:
            try:
                WorkflowInputMapping.model_validate(patch["input_mappings"])
            except Exception as exc:
                raise ValidationError(f"Invalid input_mappings: {exc}") from exc

        wf = await self._repo.update(workflow_id, **patch)
        if wf is None:
            raise NotFoundError("ComfyUI workflow", workflow_id)
        await self._db.commit()
        await self._db.refresh(wf)
        return wf

    async def delete(self, workflow_id: UUID) -> None:
        deleted = await self._repo.delete(workflow_id)
        if not deleted:
            raise NotFoundError("ComfyUI workflow", workflow_id)
        await self._db.commit()

    async def install_template(self, **payload: Any) -> ComfyUIWorkflow:
        """Bundled-template install path. Same write shape as create()
        but skips the input_mappings validation (templates ship with
        already-validated mappings)."""
        wf = await self._repo.create(**payload)
        await self._db.commit()
        return wf
