"""SocialService — TikTok OAuth + platform CRUD + uploads + stats.

Layering: keeps the route file free of repository imports, encryption
helpers, raw httpx calls to TikTok, and Redis PKCE bookkeeping (audit
F-A-01).

The TikTok OAuth callback returns ``RedirectResponse`` so the route
handles the redirect itself; the service exposes a flow method that
either persists the tokens (success path) or raises a typed exception
the route maps to a redirect with an error query parameter.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from uuid import UUID

import httpx
import structlog

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.repositories.api_key_store import ApiKeyStoreRepository
from drevalis.repositories.social import (
    SocialPlatformRepository,
    SocialUploadRepository,
)
from drevalis.schemas.social import (
    OverallStats,
    PlatformConnect,
    PlatformResponse,
    PlatformStats,
    SocialUploadRequest,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.core.config import Settings
    from drevalis.models.social_platform import SocialPlatform, SocialUpload

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_TIKTOK_AUTH_BASE = "https://www.tiktok.com/v2/auth/authorize/"
_TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_TIKTOK_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
_TIKTOK_SCOPES = "user.info.basic,video.publish,video.upload"


class TikTokNotConfiguredError(Exception):
    """Raised when TikTok client_key/client_secret are not configured."""


class TikTokOAuthError(Exception):
    """Raised when the TikTok token exchange returns an error response."""

    def __init__(self, error: str) -> None:
        self.error = error
        super().__init__(f"TikTok OAuth failed: {error}")


class TikTokInvalidStateError(Exception):
    """Raised when the OAuth state is missing, unknown, or replayed."""


def platform_to_response(platform: SocialPlatform) -> PlatformResponse:
    return PlatformResponse(
        id=platform.id,
        platform=platform.platform,
        account_id=platform.account_id,
        account_name=platform.account_name,
        is_active=platform.is_active,
        has_access_token=platform.access_token_encrypted is not None,
        has_refresh_token=platform.refresh_token_encrypted is not None,
        created_at=platform.created_at,
        updated_at=platform.updated_at,
    )


class SocialService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._platforms = SocialPlatformRepository(db)
        self._uploads = SocialUploadRepository(db)
        self._key_store = ApiKeyStoreRepository(db)

    # ── TikTok OAuth credential resolution ───────────────────────────────

    async def _resolve_tiktok_credentials(self) -> tuple[str, str, str]:
        client_key = self._settings.tiktok_client_key
        client_secret = self._settings.tiktok_client_secret
        redirect_uri = self._settings.tiktok_redirect_uri

        key_row = await self._key_store.get_by_key_name("tiktok_client_key")
        if key_row:
            client_key = self._settings.decrypt(key_row.encrypted_value)
        secret_row = await self._key_store.get_by_key_name("tiktok_client_secret")
        if secret_row:
            client_secret = self._settings.decrypt(secret_row.encrypted_value)
        uri_row = await self._key_store.get_by_key_name("tiktok_redirect_uri")
        if uri_row:
            redirect_uri = self._settings.decrypt(uri_row.encrypted_value)

        if not client_key or not client_secret:
            raise TikTokNotConfiguredError(
                "TikTok integration is not configured. Go to Settings → API Keys "
                "and add 'tiktok_client_key' and 'tiktok_client_secret'."
            )
        return client_key, client_secret, redirect_uri

    # ── TikTok auth-url with PKCE ────────────────────────────────────────

    async def tiktok_auth_url(self) -> tuple[str, str]:
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool

        client_key, _, redirect_uri = await self._resolve_tiktok_credentials()

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )

        rc: Redis = Redis(connection_pool=get_pool())
        try:
            await rc.set(f"tiktok_pkce:{state}", code_verifier, ex=600)
        finally:
            await rc.aclose()

        url = (
            f"{_TIKTOK_AUTH_BASE}"
            f"?client_key={client_key}"
            f"&response_type=code"
            f"&scope={quote(_TIKTOK_SCOPES, safe='')}"
            f"&redirect_uri={quote(redirect_uri, safe='')}"
            f"&state={state}"
            f"&code_challenge={code_challenge}"
            f"&code_challenge_method=S256"
        )
        logger.info("tiktok_auth_url_generated", state=state)
        return url, state

    # ── TikTok callback flow (token exchange + user lookup + persist) ────

    async def tiktok_complete_oauth(self, code: str, state: str) -> None:
        from redis.asyncio import Redis

        from drevalis.core.redis import get_pool

        client_key, client_secret, redirect_uri = await self._resolve_tiktok_credentials()

        if not state:
            raise TikTokInvalidStateError("state missing")

        rc: Redis = Redis(connection_pool=get_pool())
        try:
            raw = await rc.getdel(f"tiktok_pkce:{state}")
        finally:
            await rc.aclose()

        if not raw:
            raise TikTokInvalidStateError("state unknown or replayed")
        code_verifier = raw if isinstance(raw, str) else raw.decode()

        token_payload = {
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            token_payload["code_verifier"] = code_verifier

        async with httpx.AsyncClient(timeout=30.0) as client:
            token_resp = await client.post(
                _TIKTOK_TOKEN_URL,
                data=token_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_data: dict[str, Any] = token_resp.json()

        if "access_token" not in token_data:
            tiktok_error = token_data.get("error", "unknown_error")
            logger.error(
                "tiktok_token_exchange_failed",
                error=tiktok_error,
                error_description=token_data.get("error_description", ""),
            )
            raise TikTokOAuthError(str(tiktok_error))

        access_token: str = token_data["access_token"]
        refresh_token: str = token_data.get("refresh_token", "")
        open_id: str = token_data.get("open_id", "")
        expires_in: int = int(token_data.get("expires_in", 86400))
        refresh_expires_in: int = int(token_data.get("refresh_expires_in", 31536000))
        token_expires_at = datetime.now(tz=UTC) + timedelta(seconds=expires_in)

        # Best-effort display name
        display_name = "TikTok User"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                user_resp = await client.get(
                    _TIKTOK_USER_INFO_URL,
                    params={"fields": "open_id,display_name,avatar_url"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                user_data = user_resp.json()
                user_obj = user_data.get("data", {}).get("user", {})
                if user_obj.get("display_name"):
                    display_name = user_obj["display_name"]
        except Exception:
            logger.warning("tiktok_user_info_fetch_failed", exc_info=True)

        enc_access, key_version = self._settings.encrypt(access_token)
        enc_refresh: str | None = None
        if refresh_token:
            enc_refresh, _ = self._settings.encrypt(refresh_token)

        await self._platforms.deactivate_platform("tiktok")
        await self._platforms.create(
            platform="tiktok",
            account_name=display_name,
            account_id=open_id or None,
            access_token_encrypted=enc_access,
            refresh_token_encrypted=enc_refresh,
            token_key_version=key_version,
            token_expires_at=token_expires_at,
            is_active=True,
        )
        await self._db.commit()
        logger.info(
            "tiktok_account_connected",
            open_id=open_id,
            display_name=display_name,
            expires_in=expires_in,
            refresh_expires_in=refresh_expires_in,
        )

    async def tiktok_active_connection(self) -> SocialPlatform | None:
        return await self._platforms.get_active_by_platform("tiktok")

    # ── Platform CRUD ────────────────────────────────────────────────────

    async def list_platforms(self) -> list[SocialPlatform]:
        return list(await self._platforms.get_all())

    async def get_platform(self, platform_id: UUID) -> SocialPlatform | None:
        return await self._platforms.get_by_id(platform_id)

    async def connect_platform(self, body: PlatformConnect) -> SocialPlatform:
        # Guard against the "connector silently doesn't work" surprises:
        if body.platform == "facebook" and not (body.account_id or "").strip():
            raise ValidationError(
                "Facebook needs the Page ID. Paste the numeric Page ID into the "
                "'Page / Account ID' field."
            )
        if body.platform == "instagram":
            if not (body.account_id or "").strip():
                raise ValidationError(
                    "Instagram needs the Business/Creator account ID. "
                    "Paste it into the 'Page / Account ID' field."
                )
            meta = body.account_metadata or {}
            if not (meta.get("public_video_base_url") or "").strip():
                raise ValidationError(
                    "Instagram Reels need a public HTTPS URL that maps to your "
                    "storage folder. Set the 'Public video base URL' field "
                    "before connecting."
                )

        await self._platforms.deactivate_platform(body.platform)

        access_encrypted, key_version = self._settings.encrypt(body.access_token)
        refresh_encrypted: str | None = None
        if body.refresh_token:
            refresh_encrypted, _ = self._settings.encrypt(body.refresh_token)

        platform = await self._platforms.create(
            platform=body.platform,
            account_name=body.account_name,
            account_id=(body.account_id or "").strip() or None,
            access_token_encrypted=access_encrypted,
            refresh_token_encrypted=refresh_encrypted,
            token_key_version=key_version,
            account_metadata=body.account_metadata,
            is_active=True,
        )
        await self._db.commit()
        logger.info(
            "social_platform_connected",
            platform=body.platform,
            account_name=body.account_name,
        )
        return platform

    async def disconnect_platform(self, platform_id: UUID) -> None:
        deleted = await self._platforms.delete(platform_id)
        if not deleted:
            raise NotFoundError("SocialPlatform", platform_id)
        await self._db.commit()
        logger.info("social_platform_disconnected", platform_id=str(platform_id))

    # ── Uploads ──────────────────────────────────────────────────────────

    async def create_upload(self, body: SocialUploadRequest) -> SocialUpload:
        platform = await self._platforms.get_by_id(body.platform_id)
        if platform is None:
            raise NotFoundError("SocialPlatform", body.platform_id)
        if not platform.is_active:
            raise ValidationError("Platform account is not active.")

        upload = await self._uploads.create(
            platform_id=body.platform_id,
            episode_id=body.episode_id,
            content_type=body.content_type,
            title=body.title,
            description=body.description or None,
            hashtags=body.hashtags or None,
            upload_status="pending",
        )
        await self._db.commit()
        logger.info(
            "social_upload_created",
            upload_id=str(upload.id),
            platform=platform.platform,
            content_type=body.content_type,
        )
        return upload

    async def list_uploads(
        self, *, platform_id: UUID | None = None, limit: int = 50
    ) -> list[SocialUpload]:
        if platform_id:
            return list(await self._uploads.get_by_platform(platform_id, limit=limit))
        return list(await self._uploads.get_recent(limit=limit))

    # ── Stats ────────────────────────────────────────────────────────────

    async def stats(self) -> OverallStats:
        active_platforms = await self._platforms.get_all_active()
        raw_stats = await self._uploads.get_platform_stats()
        platform_stats = [PlatformStats(**s) for s in raw_stats]
        return OverallStats(
            platforms=platform_stats,
            total_platforms_connected=len(active_platforms),
            total_uploads=sum(s.total_uploads for s in platform_stats),
            total_views=sum(s.total_views for s in platform_stats),
            total_likes=sum(s.total_likes for s in platform_stats),
        )


__all__ = [
    "SocialService",
    "TikTokInvalidStateError",
    "TikTokNotConfiguredError",
    "TikTokOAuthError",
    "platform_to_response",
]
