"""API key store router -- encrypted storage/retrieval of third-party API keys.

Endpoints
---------
GET  /api/v1/settings/api-keys                   List stored key names (values never returned)
POST /api/v1/settings/api-keys                   Store or update an encrypted API key
DELETE /api/v1/settings/api-keys/{key_name}      Delete a stored API key
GET  /api/v1/settings/integrations               Report configuration status of all integrations

These endpoints let the frontend Settings UI read/write integration credentials
without the user needing direct access to ``.env`` or environment variables.
Values are Fernet-encrypted before being persisted to the ``api_key_store`` table.

Layering: this router calls ``ApiKeyStoreService`` only — no
``ApiKeyStoreRepository`` or ``encrypt_value`` imports here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError
from drevalis.schemas.runpod import (
    ApiKeyStoreListItem,
    ApiKeyStoreListResponse,
    ApiKeyStoreRequest,
    IntegrationsStatusResponse,
    IntegrationStatus,
)
from drevalis.services.api_key_store import ApiKeyStoreService

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ApiKeyStoreService:
    return ApiKeyStoreService(
        db,
        settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )


# ── API key CRUD ──────────────────────────────────────────────────────────


@router.get(
    "/api-keys",
    response_model=ApiKeyStoreListResponse,
    status_code=status.HTTP_200_OK,
    summary="List stored API key names",
    description=(
        "Returns the names (slugs) of all API keys stored in the database.  "
        "The encrypted values are never included in the response."
    ),
)
async def list_api_keys(
    svc: ApiKeyStoreService = Depends(_service),
) -> ApiKeyStoreListResponse:
    """Return all stored API key names without their values."""
    entries = await svc.list()
    items = [
        ApiKeyStoreListItem(
            key_name=e.key_name,
            has_value=True,
            created_at=e.created_at,
            updated_at=e.updated_at,
        )
        for e in entries
    ]
    return ApiKeyStoreListResponse(items=items)


@router.post(
    "/api-keys",
    response_model=ApiKeyStoreListItem,
    status_code=status.HTTP_200_OK,
    summary="Store or update an encrypted API key",
    description=(
        "Encrypts the provided API key with the application Fernet key and stores "
        "it in the database.  If a key for ``key_name`` already exists it is "
        "overwritten.  The plain-text value is never persisted."
    ),
)
async def upsert_api_key(
    payload: ApiKeyStoreRequest,
    svc: ApiKeyStoreService = Depends(_service),
) -> ApiKeyStoreListItem:
    """Encrypt and persist a third-party API key."""
    await svc.upsert(key_name=payload.key_name, api_key=payload.api_key)
    return ApiKeyStoreListItem(key_name=payload.key_name, has_value=True)


@router.delete(
    "/api-keys/{key_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a stored API key",
    description="Permanently removes the encrypted API key for the given name.",
)
async def delete_api_key(
    key_name: str,
    svc: ApiKeyStoreService = Depends(_service),
) -> None:
    """Remove a stored API key entry by name."""
    try:
        await svc.delete(key_name)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No API key stored for '{key_name}'.",
        ) from exc


# ── Integrations status ───────────────────────────────────────────────────


@router.get(
    "/integrations",
    response_model=IntegrationsStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Integration configuration status",
    description=(
        "Reports whether each supported third-party integration has a key "
        "configured.  Checks both the DB store and env vars.  "
        "Actual key values are never returned."
    ),
)
async def get_integrations_status(
    svc: ApiKeyStoreService = Depends(_service),
    settings: Settings = Depends(get_settings),
) -> IntegrationsStatusResponse:
    """Check which third-party integrations are configured."""
    stored_keys = await svc.list_stored_names()

    def _status(key_name: str, env_value: str) -> IntegrationStatus:
        """Determine source for a given integration key."""
        if key_name in stored_keys:
            return IntegrationStatus(configured=True, source="db")
        if env_value:
            return IntegrationStatus(configured=True, source="env")
        return IntegrationStatus(configured=False, source="none")

    # YouTube needs BOTH ``youtube_client_id`` AND ``youtube_client_secret``
    # rows present in the api_keys store (or both env vars). Pre-v0.28.1 the
    # lookup queried for a single ``"youtube"`` row that's never written by
    # the Settings UI, so the integrations endpoint reported
    # ``configured=false`` even when the publish path's underlying creds
    # were stored. RunPod wasn't affected because it stores a single
    # ``"runpod"`` row that DOES match the lookup.
    from drevalis.services.integration_keys import youtube_configured_in_db

    youtube_in_db = youtube_configured_in_db(stored_keys)
    youtube_in_env = bool(settings.youtube_client_id and settings.youtube_client_secret)
    if youtube_in_db:
        yt_status = IntegrationStatus(configured=True, source="db")
    elif youtube_in_env:
        yt_status = IntegrationStatus(configured=True, source="env")
    else:
        yt_status = IntegrationStatus(configured=False, source="none")

    return IntegrationsStatusResponse(
        runpod=_status("runpod", settings.runpod_api_key),
        elevenlabs=_status("elevenlabs", ""),  # ElevenLabs key is per voice-profile
        anthropic=_status("anthropic", settings.anthropic_api_key),
        youtube=yt_status,
    )
