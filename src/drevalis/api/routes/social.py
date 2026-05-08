"""Social platform integration API routes — connect, upload, stats.

Layering: this router calls ``SocialService`` only. No repository
imports, no httpx calls to TikTok, no Redis bookkeeping here (audit
F-A-01).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.license.features import require_feature
from drevalis.schemas.social import (
    OverallStats,
    PlatformConnect,
    PlatformResponse,
    SocialUploadRequest,
    SocialUploadResponse,
    TikTokAuthURLResponse,
    TikTokConnectionStatus,
)
from drevalis.services.social import (
    SocialService,
    TikTokInvalidStateError,
    TikTokNotConfiguredError,
    TikTokOAuthError,
    platform_to_response,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/social", tags=["social"])

# Per-platform feature gates. TikTok is on Pro+; Instagram/Facebook/X
# require Studio. ``service.connect_platform`` and ``service.create_upload``
# enforce these per request based on the resolved platform name.
PLATFORM_FEATURE: dict[str, str] = {
    "tiktok": "social_tiktok",
    "instagram": "social_extended",
    "facebook": "social_extended",
    "x": "social_extended",
}


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SocialService:
    return SocialService(db, settings)


# ── TikTok OAuth flow ────────────────────────────────────────────────────


@router.get(
    "/tiktok/auth-url",
    response_model=TikTokAuthURLResponse,
    status_code=status.HTTP_200_OK,
    summary="Get TikTok OAuth authorization URL",
    description=(
        "Generate a TikTok Login Kit OAuth 2.0 consent URL. "
        "The caller should redirect the user to `auth_url` and store the "
        "returned `state` value for CSRF verification on callback."
    ),
)
async def tiktok_auth_url(
    svc: SocialService = Depends(_service),
) -> TikTokAuthURLResponse:
    require_feature(PLATFORM_FEATURE["tiktok"])
    try:
        url, state = await svc.tiktok_auth_url()
    except TikTokNotConfiguredError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return TikTokAuthURLResponse(auth_url=url, state=state)


@router.get(
    "/tiktok/callback",
    status_code=status.HTTP_302_FOUND,
    summary="Handle TikTok OAuth callback",
    response_class=RedirectResponse,
)
async def tiktok_callback(
    code: str = Query(..., description="Authorization code returned by TikTok"),
    state: str = Query(default="", description="OAuth state parameter for CSRF"),
    error: str | None = Query(default=None, description="Error code if user denied access"),
    error_description: str | None = Query(
        default=None, description="Human-readable error description"
    ),
    svc: SocialService = Depends(_service),
) -> RedirectResponse:
    """Complete the TikTok OAuth 2.0 authorization code flow.

    On success: stores encrypted tokens and redirects to the frontend.
    On failure: redirects to the frontend with an ``error`` query
    parameter so the UI can display an appropriate message without
    exposing raw API error details to the browser's address bar.
    """
    frontend_settings_url = "http://localhost:3000/settings?section=social"

    if error:
        logger.warning(
            "tiktok_oauth_denied",
            error=error,
            error_description=error_description,
        )
        return RedirectResponse(
            url=f"{frontend_settings_url}&tiktok_error={error}",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        await svc.tiktok_complete_oauth(code, state)
    except TikTokInvalidStateError:
        logger.warning("tiktok_oauth_state_invalid")
        return RedirectResponse(
            url=f"{frontend_settings_url}&tiktok_error=invalid_state",
            status_code=status.HTTP_302_FOUND,
        )
    except TikTokNotConfiguredError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except TikTokOAuthError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"TikTok authorization failed: {exc.error}"
        ) from exc

    return RedirectResponse(url=frontend_settings_url, status_code=status.HTTP_302_FOUND)


@router.get(
    "/tiktok/status",
    response_model=TikTokConnectionStatus,
    status_code=status.HTTP_200_OK,
    summary="Check TikTok connection status",
)
async def tiktok_status(
    svc: SocialService = Depends(_service),
) -> TikTokConnectionStatus:
    platform = await svc.tiktok_active_connection()
    if platform is None:
        return TikTokConnectionStatus(connected=False, account=None)
    return TikTokConnectionStatus(connected=True, account=platform_to_response(platform))


# ── Platform CRUD ────────────────────────────────────────────────────────


@router.get(
    "/platforms",
    response_model=list[PlatformResponse],
    status_code=status.HTTP_200_OK,
)
async def list_platforms(
    svc: SocialService = Depends(_service),
) -> list[PlatformResponse]:
    platforms = await svc.list_platforms()
    return [platform_to_response(p) for p in platforms]


@router.post(
    "/platforms",
    response_model=PlatformResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_platform(
    body: PlatformConnect,
    svc: SocialService = Depends(_service),
) -> PlatformResponse:
    """Connect a new social platform account."""
    require_feature(PLATFORM_FEATURE[body.platform])
    try:
        platform = await svc.connect_platform(body)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
    return platform_to_response(platform)


@router.delete(
    "/platforms/{platform_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_platform(
    platform_id: UUID,
    svc: SocialService = Depends(_service),
) -> None:
    try:
        await svc.disconnect_platform(platform_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform account not found.") from exc


# ── Uploads ──────────────────────────────────────────────────────────────


@router.post(
    "/uploads",
    response_model=SocialUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload(
    body: SocialUploadRequest,
    svc: SocialService = Depends(_service),
) -> SocialUploadResponse:
    """Create a new social media upload record. Worker handles upload async."""
    platform = await svc.get_platform(body.platform_id)
    if platform is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform account not found.")
    feature = PLATFORM_FEATURE.get(platform.platform)
    if feature:
        require_feature(feature)
    try:
        upload = await svc.create_upload(body)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform account not found.") from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
    return SocialUploadResponse.model_validate(upload)


@router.get(
    "/uploads",
    response_model=list[SocialUploadResponse],
    status_code=status.HTTP_200_OK,
)
async def list_uploads(
    platform_id: UUID | None = None,
    limit: int = 50,
    svc: SocialService = Depends(_service),
) -> list[SocialUploadResponse]:
    uploads = await svc.list_uploads(platform_id=platform_id, limit=limit)
    return [SocialUploadResponse.model_validate(u) for u in uploads]


# ── Stats ────────────────────────────────────────────────────────────────


@router.get(
    "/stats",
    response_model=OverallStats,
    status_code=status.HTTP_200_OK,
)
async def get_stats(
    svc: SocialService = Depends(_service),
) -> OverallStats:
    return await svc.stats()
