"""Shared helpers for resolving third-party integration credentials.

Pre-fix, ``_resolve_youtube_credentials`` lived in the YouTube router
(``api/routes/youtube/_monolith.py``) so the worker scheduled.py path
couldn't reach it without an import cycle. The worker therefore
bypassed the api_keys store and read only ``settings.youtube_client_id``
— even when the Settings UI had saved the keys to the DB. This module
is the single shared helper both call sites use.

See bug fix v0.28.1 (2026-04-29) for the original report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.core.config import Settings

logger = structlog.get_logger(__name__)


async def resolve_youtube_credentials(settings: Settings, db: AsyncSession) -> tuple[str, str]:
    """Return ``(client_id, client_secret)`` from env or api_keys store.

    Priority: env (``YOUTUBE_CLIENT_ID`` / ``YOUTUBE_CLIENT_SECRET``)
    first, then Fernet-decrypted rows from the ``api_keys`` table
    (``key_name`` ``youtube_client_id`` / ``youtube_client_secret``).
    Either or both fields can come back empty — caller decides what
    "missing" means (HTTP 503 in the route, RuntimeError in the
    worker).

    Decryption failures are logged and treated as missing rather than
    raising. The most common cause is a backup restored onto a host
    with a different ``ENCRYPTION_KEY``; surfacing that as "not
    configured" matches the rest of the integration-resolution
    contract and the Settings UI re-save flow naturally repairs it.
    """
    from drevalis.repositories.api_key_store import ApiKeyStoreRepository

    client_id = settings.youtube_client_id
    client_secret = settings.youtube_client_secret

    if not client_id or not client_secret:
        repo = ApiKeyStoreRepository(db)
        if not client_id:
            row = await repo.get_by_key_name("youtube_client_id")
            if row and row.encrypted_value:
                try:
                    client_id = settings.decrypt(row.encrypted_value)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "youtube_client_id_decrypt_failed",
                        error=f"{type(exc).__name__}: {str(exc)[:120]}",
                    )
                    client_id = ""
        if not client_secret:
            row = await repo.get_by_key_name("youtube_client_secret")
            if row and row.encrypted_value:
                try:
                    client_secret = settings.decrypt(row.encrypted_value)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "youtube_client_secret_decrypt_failed",
                        error=f"{type(exc).__name__}: {str(exc)[:120]}",
                    )
                    client_secret = ""

    return client_id, client_secret


def youtube_configured_in_db(stored_key_names: set[str]) -> bool:
    """``True`` iff the ``api_keys`` table has BOTH youtube rows.

    The ``/integrations`` endpoint pre-fix queried for a single
    ``"youtube"`` row that doesn't exist; YouTube actually stores
    two rows (``youtube_client_id`` + ``youtube_client_secret``)
    and BOTH must be present for the integration to be usable.

    RunPod stores a single ``"runpod"`` row, which is why the
    pre-fix integrations check worked for RunPod but not YouTube.
    """
    return "youtube_client_id" in stored_key_names and "youtube_client_secret" in stored_key_names


__all__ = ["resolve_youtube_credentials", "youtube_configured_in_db"]
