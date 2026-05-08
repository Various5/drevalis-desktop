"""Repository for the singleton ``license_state`` row.

The JWT is stored Fernet-encrypted so a DB snapshot (backup theft,
misconfigured volume) does not immediately yield a live license key.
Rows written before the at-rest-encryption migration landed remain
valid: when ``jwt_key_version`` is NULL the stored value is treated as
legacy plaintext and transparently re-encrypted on the next write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from drevalis.core.config import Settings
from drevalis.models.license_state import LicenseStateRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _decrypt_stored_jwt(row: LicenseStateRow) -> str | None:
    """Return the plaintext JWT for *row*, handling legacy plaintext rows.

    Returns None when no JWT is stored. Raises ``ValueError`` if the
    stored value looks encrypted but cannot be decrypted with the
    current key (indicates key rotation gone wrong or tampering).
    """
    if not row.jwt:
        return None
    if row.jwt_key_version is None:
        # Legacy plaintext row (pre-encryption migration). Safe to return
        # as-is; the next write will re-encrypt it.
        return row.jwt
    settings = Settings()
    try:
        return settings.decrypt(row.jwt)
    except InvalidToken as exc:
        raise ValueError(
            "license_state.jwt cannot be decrypted with the current "
            "ENCRYPTION_KEY. If you rotated the key, restore the "
            "previous value or re-activate the license."
        ) from exc


class LicenseStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> LicenseStateRow | None:
        result = await self._session.execute(select(LicenseStateRow).where(LicenseStateRow.id == 1))
        return result.scalar_one_or_none()

    async def get_plaintext_jwt(self) -> str | None:
        """Fetch and decrypt the stored JWT, or None if no license is set."""
        row = await self.get()
        if row is None:
            return None
        return _decrypt_stored_jwt(row)

    async def upsert(
        self,
        *,
        jwt: str,
        machine_id: str | None,
    ) -> LicenseStateRow:
        """Write or replace the singleton license row (JWT encrypted at rest)."""
        settings = Settings()
        ciphertext, key_version = settings.encrypt(jwt)

        row = await self.get()
        now = datetime.now(tz=UTC)
        if row is None:
            row = LicenseStateRow(
                id=1,
                jwt=ciphertext,
                jwt_key_version=key_version,
                machine_id=machine_id,
                activated_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.jwt = ciphertext
            row.jwt_key_version = key_version
            row.machine_id = machine_id
            if row.activated_at is None:
                row.activated_at = now
            row.updated_at = now
        await self._session.flush()
        return row

    async def clear(self) -> None:
        """Zero the JWT but keep the row for historical fields."""
        row = await self.get()
        if row is None:
            return
        row.jwt = None
        row.jwt_key_version = None
        row.updated_at = datetime.now(tz=UTC)
        await self._session.flush()

    async def record_heartbeat(self, status: str) -> None:
        row = await self.get()
        if row is None:
            return
        now = datetime.now(tz=UTC)
        row.last_heartbeat_at = now
        row.last_heartbeat_status = status
        row.updated_at = now
        await self._session.flush()
