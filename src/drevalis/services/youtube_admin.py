"""YouTubeAdminService — route-orchestration over YouTubeService.

Layering: keeps the youtube route file free of repository imports +
direct token-persist-on-refresh logic + SEO generation orchestration
(audit F-A-01).

This is distinct from the existing ``services/youtube.py``
(``YouTubeService``) which is the upstream API client. The pattern
matches ``AudiobookAdminService`` vs ``AudiobookService``.

Channel resolution rules (used across upload, analytics, playlist
flows):

1. If the caller passes a ``channel_id``, look it up; ``NotFoundError``
   on miss.
2. Otherwise, single-channel installs implicitly use the only one.
3. In demo mode, fall back to the first channel.
4. Otherwise, ``MultipleChannelsAmbiguousError`` carries the list so
   the route renders an actionable 400.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.repositories.episode import EpisodeRepository
from drevalis.repositories.media_asset import MediaAssetRepository
from drevalis.repositories.youtube import (
    YouTubeChannelRepository,
    YouTubePlaylistRepository,
    YouTubeUploadRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.core.config import Settings
    from drevalis.models.episode import Episode
    from drevalis.models.youtube_channel import (
        YouTubeChannel,
        YouTubePlaylist,
        YouTubeUpload,
    )
    from drevalis.services.youtube import YouTubeService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class YouTubeNotConfiguredError(Exception):
    """Raised when YOUTUBE_CLIENT_ID/SECRET aren't set in env or DB."""

    def __init__(self, *, has_id_row: bool, has_secret_row: bool) -> None:
        self.has_id_row = has_id_row
        self.has_secret_row = has_secret_row
        super().__init__("YouTube integration is not configured.")


class ChannelCapExceededError(Exception):
    """Raised when adding a new channel would exceed the license tier's cap."""

    def __init__(self, tier: str, limit: int) -> None:
        self.tier = tier
        self.limit = limit
        super().__init__(f"Tier {tier} caps YouTube channels at {limit}")


class MultipleChannelsAmbiguousError(Exception):
    """Raised when an op requires picking a channel and several are connected."""

    def __init__(self, channels: list[YouTubeChannel]) -> None:
        self.channels = channels
        super().__init__("Multiple channels connected; channel_id required.")


class NoChannelConnectedError(Exception):
    """Raised when an op requires a channel and none are connected."""


class DuplicateUploadError(Exception):
    """Raised when a YouTube upload would re-publish an episode already on
    that channel. The earliest ``done`` row is treated as canonical."""

    def __init__(
        self,
        *,
        episode_id: UUID,
        channel_id: UUID,
        existing_upload_id: UUID,
        existing_video_id: str | None,
    ) -> None:
        self.episode_id = episode_id
        self.channel_id = channel_id
        self.existing_upload_id = existing_upload_id
        self.existing_video_id = existing_video_id
        super().__init__(
            f"Episode {episode_id} is already published on channel {channel_id} "
            f"as {existing_video_id or '<unknown video>'}."
        )


class TokenRefreshError(Exception):
    """Raised when token refresh failed — the route maps this to 401 with hint."""


# ── Module-level credential resolver (shared with audiobooks route) ────


async def build_youtube_service(settings: Settings, db: AsyncSession) -> YouTubeService:
    """Build a YouTubeService, pulling credentials from env + DB store.

    Stays module-level (rather than a method on the service) because
    other modules (notably the audiobooks route) call this directly
    and we don't want them to instantiate YouTubeAdminService just for
    credential resolution.
    """
    from drevalis.repositories.api_key_store import ApiKeyStoreRepository
    from drevalis.services.integration_keys import resolve_youtube_credentials
    from drevalis.services.youtube import YouTubeService

    client_id, client_secret = await resolve_youtube_credentials(settings, db)
    if not client_id or not client_secret:
        repo = ApiKeyStoreRepository(db)
        has_id_row = await repo.get_by_key_name("youtube_client_id") is not None
        has_secret_row = await repo.get_by_key_name("youtube_client_secret") is not None
        raise YouTubeNotConfiguredError(has_id_row=has_id_row, has_secret_row=has_secret_row)

    return YouTubeService(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=settings.youtube_redirect_uri,
        encryption_key=settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )


class YouTubeAdminService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._channels = YouTubeChannelRepository(db)
        self._uploads = YouTubeUploadRepository(db)
        self._playlists = YouTubePlaylistRepository(db)
        self._episodes = EpisodeRepository(db)
        self._assets = MediaAssetRepository(db)

    # ── Channel CRUD + connection management ─────────────────────────────

    async def upsert_oauth_channel(self, channel_info: dict[str, Any]) -> YouTubeChannel:
        """Insert-or-update channel after OAuth callback. Enforces the
        license tier's channel cap on insert."""
        existing = await self._channels.get_by_channel_id(channel_info["channel_id"])
        if existing:
            existing.channel_name = channel_info["channel_name"]
            existing.access_token_encrypted = channel_info["access_token_encrypted"]
            existing.refresh_token_encrypted = channel_info["refresh_token_encrypted"]
            existing.token_key_version = channel_info["token_key_version"]
            existing.token_expiry = channel_info.get("token_expiry")
            existing.is_active = True
            await self._db.flush()
            await self._db.refresh(existing)
            channel = existing
        else:
            from drevalis.core.license.features import TIER_CHANNEL_CAP
            from drevalis.core.license.state import get_state as _get_license_state

            lic = _get_license_state()
            if lic.is_usable and lic.claims is not None:
                cap = TIER_CHANNEL_CAP.get(lic.claims.tier, 1)
                existing_count = len(await self._channels.get_all_channels())
                if existing_count >= cap:
                    raise ChannelCapExceededError(lic.claims.tier, cap)

            channel = await self._channels.create(
                channel_id=channel_info["channel_id"],
                channel_name=channel_info["channel_name"],
                access_token_encrypted=channel_info["access_token_encrypted"],
                refresh_token_encrypted=channel_info["refresh_token_encrypted"],
                token_key_version=channel_info["token_key_version"],
                token_expiry=channel_info.get("token_expiry"),
                is_active=True,
            )

        await self._db.commit()
        await self._db.refresh(channel)
        logger.info(
            "youtube_channel_connected",
            channel_id=channel.channel_id,
            channel_name=channel.channel_name,
        )
        return channel

    async def list_channels(self, *, include_inactive: bool = False) -> list[YouTubeChannel]:
        channels = await self._channels.get_all_channels()
        if not include_inactive:
            channels = [c for c in channels if c.is_active]
        return list(channels)

    async def connection_status(self) -> tuple[list[YouTubeChannel], YouTubeChannel | None]:
        all_channels = list(await self._channels.get_all_channels())
        active = await self._channels.get_active()
        return all_channels, active

    async def disconnect(self, channel_id: UUID | None) -> str:
        """Wipe tokens + deactivate. Returns the channel name."""
        if channel_id:
            channel = await self._channels.get_by_id(channel_id)
        else:
            all_channels = await self._channels.get_all_channels()
            if len(all_channels) > 1:
                raise MultipleChannelsAmbiguousError(list(all_channels))
            channel = all_channels[0] if all_channels else None

        if channel is None:
            raise NotFoundError("YouTubeChannel", channel_id or "any")

        channel.access_token_encrypted = None
        channel.refresh_token_encrypted = None
        channel.token_expiry = None
        channel.is_active = False
        await self._db.commit()
        logger.info("youtube_channel_disconnected", channel_id=channel.channel_id)
        return channel.channel_name

    async def delete_channel(self, channel_id: UUID) -> str:
        channel = await self._channels.get_by_id(channel_id)
        if channel is None:
            raise NotFoundError("YouTubeChannel", channel_id)
        name = channel.channel_name
        await self._db.delete(channel)
        await self._db.commit()
        logger.info("youtube_channel_deleted", channel_id=str(channel_id))
        return name

    async def update_channel(self, channel_id: UUID, updates: dict[str, Any]) -> YouTubeChannel:
        channel = await self._channels.get_by_id(channel_id)
        if channel is None:
            raise NotFoundError("YouTubeChannel", channel_id)
        for key, value in updates.items():
            setattr(channel, key, value)
        await self._db.commit()
        await self._db.refresh(channel)
        return channel

    # ── Channel resolution helper (multi-channel rules) ──────────────────

    async def resolve_channel(self, channel_id: UUID | None) -> YouTubeChannel:
        if channel_id is not None:
            ch = await self._channels.get_by_id(channel_id)
            if ch is None:
                raise NotFoundError("YouTubeChannel", channel_id)
            return ch

        all_channels = list(await self._channels.get_all_channels())
        if not all_channels:
            raise NoChannelConnectedError()
        if len(all_channels) == 1:
            return all_channels[0]
        if self._settings.demo_mode:
            return all_channels[0]
        raise MultipleChannelsAmbiguousError(all_channels)

    # ── Token refresh + persist ──────────────────────────────────────────

    async def refresh_and_persist_tokens(
        self, channel: YouTubeChannel, yt_service: YouTubeService, *, commit: bool = False
    ) -> None:
        """Refresh tokens, copy back onto the channel row, optionally commit.

        Used before every API call that goes through OAuth. ``commit=True``
        is for the upload path which can take minutes — losing a freshly-
        minted token to a worker crash mid-upload is worse than the extra
        commit. ``commit=False`` (default) just flushes; the caller commits
        when its overall flow ends."""
        from drevalis.services.youtube import YouTubeTokenExpiredError

        try:
            updated_tokens = await yt_service.refresh_tokens_if_needed(
                channel.access_token_encrypted or "",
                channel.refresh_token_encrypted,
                channel.token_expiry,
            )
        except YouTubeTokenExpiredError as exc:
            raise TokenRefreshError(str(exc)) from exc
        if updated_tokens:
            for key, value in updated_tokens.items():
                setattr(channel, key, value)
            await self._db.flush()
            if commit:
                await self._db.commit()

    # ── Episode upload flow ──────────────────────────────────────────────

    async def resolve_episode_upload_target(
        self, episode_id: UUID, override_channel_id: UUID | None
    ) -> tuple[Episode, YouTubeChannel, Path]:
        """Resolve the channel and validate the video file. Returns
        ``(episode, channel, absolute_video_path)``.

        Channel resolution: explicit override > series assignment.
        """
        from drevalis.repositories.series import SeriesRepository

        episode = await self._episodes.get_by_id(episode_id)
        if episode is None:
            raise NotFoundError("Episode", episode_id)

        channel = None
        if override_channel_id:
            channel = await self._channels.get_by_id(override_channel_id)
        if channel is None and episode.series_id:
            series = await SeriesRepository(self._db).get_by_id(episode.series_id)
            if series and series.youtube_channel_id:
                channel = await self._channels.get_by_id(series.youtube_channel_id)
        if channel is None:
            raise ValidationError(
                "No YouTube channel assigned to this series. "
                "Assign a channel in the series settings or pass channel_id in the request."
            )

        video_assets = await self._assets.get_by_episode_and_type(episode_id, "video")
        if not video_assets:
            raise NotFoundError("EpisodeVideo", episode_id)
        video_path = Path(self._settings.storage_base_path) / video_assets[-1].file_path
        if not video_path.exists():
            raise NotFoundError("EpisodeVideoFile", str(video_path))
        return episode, channel, video_path

    async def get_thumbnail_path(self, episode_id: UUID) -> Path | None:
        thumb_assets = await self._assets.get_by_episode_and_type(episode_id, "thumbnail")
        if thumb_assets:
            candidate = Path(self._settings.storage_base_path) / thumb_assets[-1].file_path
            if candidate.exists():
                return candidate
        return None

    async def get_or_generate_seo(self, episode: Episode) -> dict[str, Any]:
        """Return cached SEO from ``episode.metadata_['seo']`` or generate
        on-the-fly via the LLM (cached back). Best-effort — returns
        ``{}`` on failure."""
        episode_meta = episode.metadata_ or {}
        if isinstance(episode_meta, dict) and "seo" in episode_meta:
            seo_data = episode_meta["seo"]
            if isinstance(seo_data, dict):
                return seo_data

        if not episode.script:
            return {}

        try:
            from drevalis.repositories.llm_config import LLMConfigRepository
            from drevalis.schemas.script import EpisodeScript
            from drevalis.services.llm import (
                LLMService,
                OpenAICompatibleProvider,
                extract_json,
            )

            script_obj = EpisodeScript.model_validate(episode.script)
            narration = " ".join(s.narration for s in script_obj.scenes if s.narration)

            configs = await LLMConfigRepository(self._db).get_all(limit=1)
            if configs:
                provider: Any = LLMService(
                    encryption_key=self._settings.encryption_key,
                    encryption_keys=self._settings.get_encryption_keys(),
                ).get_provider(configs[0])
            else:
                provider = OpenAICompatibleProvider(
                    base_url=self._settings.lm_studio_base_url,
                    model=self._settings.lm_studio_default_model,
                )

            from drevalis.services.seo_prompts import (
                SEO_SYSTEM_PROMPT,
                build_seo_user_prompt,
            )

            existing_description = ""
            if isinstance(episode.script, dict):
                raw_desc = episode.script.get("description")
                if isinstance(raw_desc, str):
                    existing_description = raw_desc

            result = await provider.generate(
                SEO_SYSTEM_PROMPT,
                build_seo_user_prompt(
                    title=episode.title,
                    narration=narration,
                    script_description=existing_description,
                ),
                temperature=0.7,
                max_tokens=1024,
                json_mode=True,
            )
            seo_data = json.loads(extract_json(result.content))

            new_meta = dict(episode_meta) if isinstance(episode_meta, dict) else {}
            new_meta["seo"] = seo_data
            await self._episodes.update(episode.id, metadata_=new_meta)
            await self._db.flush()
            logger.info("seo_auto_generated_for_upload", episode_id=str(episode.id))
            return seo_data if isinstance(seo_data, dict) else {}
        except Exception as exc:
            logger.warning("seo_auto_generation_failed", error=str(exc)[:200])
            return {}

    async def create_upload_row(
        self,
        *,
        episode_id: UUID,
        channel_id: UUID,
        title: str,
        description: str,
        privacy_status: str,
    ) -> YouTubeUpload:
        # Duplicate guard: refuse to start a new upload if this episode is
        # already on this channel. Without this, a manual retry, a stuck
        # tab, or an overlap with the scheduled-post cron can publish the
        # same video twice.
        existing = await self._uploads.get_existing_done(episode_id, channel_id)
        if existing is not None:
            raise DuplicateUploadError(
                episode_id=episode_id,
                channel_id=channel_id,
                existing_upload_id=existing.id,
                existing_video_id=existing.youtube_video_id,
            )
        upload = await self._uploads.create(
            episode_id=episode_id,
            channel_id=channel_id,
            title=title,
            description=description,
            privacy_status=privacy_status,
            upload_status="uploading",
        )
        await self._db.commit()
        await self._db.refresh(upload)
        return upload

    async def record_upload_success(
        self, upload: YouTubeUpload, *, video_id: str, url: str, episode_id: UUID
    ) -> None:
        upload.youtube_video_id = video_id
        upload.youtube_url = url
        upload.upload_status = "done"
        await self._episodes.update_status(episode_id, "exported")
        await self._db.commit()
        await self._db.refresh(upload)

    async def record_upload_failure(self, upload: YouTubeUpload, error: str) -> None:
        upload.upload_status = "failed"
        upload.error_message = error[:1000]
        await self._db.commit()
        await self._db.refresh(upload)

    # ── Series playlist orchestration (post-upload bonus) ────────────────

    async def auto_add_to_series_playlist(
        self,
        *,
        yt_service: YouTubeService,
        episode: Episode,
        channel: YouTubeChannel,
        video_id: str,
        privacy_status: str,
    ) -> None:
        """Best-effort: ensure series has a playlist on YouTube, then add
        the new video to it. Failure is non-fatal and only logged."""
        try:
            from sqlalchemy import text as sa_text

            from drevalis.repositories.series import SeriesRepository

            if not episode.series_id:
                return
            series = await SeriesRepository(self._db).get_by_id(episode.series_id)
            if not series:
                return

            series_meta = series.metadata_ if hasattr(series, "metadata_") else {}
            if not isinstance(series_meta, dict):
                series_meta = {}

            playlist_id = series_meta.get("youtube_playlist_id")
            if not playlist_id:
                playlist_result = await yt_service.create_playlist(
                    access_token_encrypted=channel.access_token_encrypted or "",
                    refresh_token_encrypted=channel.refresh_token_encrypted,
                    token_expiry=channel.token_expiry,
                    title=series.name,
                    description=series.description or f"Episodes from {series.name}",
                    privacy_status=privacy_status,
                )
                playlist_id = playlist_result.get("playlist_id", "")
                if playlist_id:
                    series_meta["youtube_playlist_id"] = playlist_id
                    await self._db.execute(
                        sa_text("UPDATE series SET metadata = :meta WHERE id = :sid"),
                        {"meta": json.dumps(series_meta), "sid": str(series.id)},
                    )
                    await self._db.commit()
                    logger.info(
                        "youtube_playlist_created",
                        series=series.name,
                        playlist_id=playlist_id,
                    )

            if playlist_id:
                await yt_service.add_to_playlist(
                    access_token_encrypted=channel.access_token_encrypted or "",
                    refresh_token_encrypted=channel.refresh_token_encrypted,
                    token_expiry=channel.token_expiry,
                    playlist_id=playlist_id,
                    video_id=video_id,
                )
                logger.info(
                    "youtube_added_to_playlist",
                    video_id=video_id,
                    playlist_id=playlist_id,
                )
        except Exception as exc:
            logger.warning("youtube_playlist_failed", error=str(exc)[:200])

    # ── Upload history ───────────────────────────────────────────────────

    async def list_uploads(self, limit: int) -> list[YouTubeUpload]:
        return list(await self._uploads.get_recent(limit=limit))

    # ── Duplicate sweep ──────────────────────────────────────────────────

    async def find_duplicate_uploads(self) -> list[dict[str, Any]]:
        """Return one summary per duplicated (episode, channel) group.

        Each entry has ``episode_id``, ``channel_id``, ``keep`` (the
        canonical upload id + video id), and ``duplicates`` (the
        superseded upload ids + video ids that should be removed).
        """
        groups = await self._uploads.find_duplicates()
        out: list[dict[str, Any]] = []
        for group in groups:
            keep, *dupes = group  # earliest row is canonical
            out.append(
                {
                    "episode_id": str(keep.episode_id),
                    "channel_id": str(keep.channel_id),
                    "keep": {
                        "upload_id": str(keep.id),
                        "video_id": keep.youtube_video_id,
                    },
                    "duplicates": [
                        {
                            "upload_id": str(d.id),
                            "video_id": d.youtube_video_id,
                            "created_at": d.created_at.isoformat() if d.created_at else None,
                        }
                        for d in dupes
                    ],
                }
            )
        return out

    async def dedupe_uploads(
        self,
        *,
        yt_service: YouTubeService,
        delete_on_youtube: bool = True,
    ) -> dict[str, Any]:
        """Remove duplicate ``done`` uploads for every (episode, channel) pair.

        Strategy: keep the earliest ``done`` row, mark the rest as
        ``failed`` with an explanatory ``error_message``, and (optionally)
        delete the duplicate video on YouTube via the Data API.

        Returns counts and a per-group summary so the caller can show the
        operator what was actually changed.
        """
        from drevalis.repositories.youtube import YouTubeChannelRepository

        channel_repo = YouTubeChannelRepository(self._db)
        channel_cache: dict[UUID, YouTubeChannel | None] = {}

        async def _channel(cid: UUID) -> YouTubeChannel | None:
            if cid not in channel_cache:
                channel_cache[cid] = await channel_repo.get_by_id(cid)
            return channel_cache[cid]

        groups = await self._uploads.find_duplicates()
        summary: list[dict[str, Any]] = []
        rows_marked = 0
        videos_deleted = 0
        delete_errors: list[str] = []

        for group in groups:
            keep, *dupes = group
            channel = await _channel(keep.channel_id)
            removed: list[dict[str, Any]] = []

            for dupe in dupes:
                # 1) Delete from YouTube if we still have a valid token +
                #    a concrete video id. Failures are logged and surfaced
                #    but don't stop the row-level cleanup.
                if delete_on_youtube and channel and dupe.youtube_video_id:
                    try:
                        await self.refresh_and_persist_tokens(channel, yt_service, commit=False)
                    except Exception:  # noqa: BLE001
                        # refresh failure isn't fatal — try the delete
                        # with whatever token we already have.
                        pass
                    try:
                        await yt_service.delete_video(
                            access_token_encrypted=channel.access_token_encrypted or "",
                            refresh_token_encrypted=channel.refresh_token_encrypted,
                            token_expiry=channel.token_expiry,
                            video_id=dupe.youtube_video_id,
                        )
                        videos_deleted += 1
                    except Exception as exc:  # noqa: BLE001
                        delete_errors.append(f"video={dupe.youtube_video_id}: {str(exc)[:160]}")

                # 2) Mark the row failed with a clear note. Keeping the
                #    row (rather than deleting it) preserves the audit
                #    trail so an operator can see what happened.
                dupe.upload_status = "failed"
                dupe.error_message = (
                    f"duplicate — superseded by upload {keep.id} "
                    f"(video {keep.youtube_video_id or '?'})"
                )[:1000]
                rows_marked += 1
                removed.append(
                    {
                        "upload_id": str(dupe.id),
                        "video_id": dupe.youtube_video_id,
                    }
                )

            summary.append(
                {
                    "episode_id": str(keep.episode_id),
                    "channel_id": str(keep.channel_id),
                    "kept_upload_id": str(keep.id),
                    "kept_video_id": keep.youtube_video_id,
                    "removed": removed,
                }
            )

        await self._db.commit()
        return {
            "groups": len(groups),
            "rows_marked_failed": rows_marked,
            "videos_deleted": videos_deleted,
            "delete_errors": delete_errors,
            "summary": summary,
        }

    # ── Playlist CRUD ────────────────────────────────────────────────────

    async def create_playlist_row(
        self,
        *,
        channel_id: UUID,
        youtube_playlist_id: str,
        title: str,
        description: str | None,
        privacy_status: str,
        item_count: int,
    ) -> YouTubePlaylist:
        playlist = await self._playlists.create(
            channel_id=channel_id,
            youtube_playlist_id=youtube_playlist_id,
            title=title,
            description=description,
            privacy_status=privacy_status,
            item_count=item_count,
        )
        await self._db.commit()
        await self._db.refresh(playlist)
        return playlist

    async def list_playlists_for_channel(self, channel_id: UUID) -> list[YouTubePlaylist]:
        return list(await self._playlists.get_by_channel(channel_id))

    async def get_playlist_with_channel(
        self, playlist_id: UUID
    ) -> tuple[YouTubePlaylist, YouTubeChannel]:
        playlist = await self._playlists.get_by_id(playlist_id)
        if playlist is None:
            raise NotFoundError("YouTubePlaylist", playlist_id)
        channel = await self._channels.get_by_id(playlist.channel_id)
        if channel is None:
            raise NotFoundError("YouTubeChannel", playlist.channel_id)
        return playlist, channel

    async def increment_playlist_item_count(self, playlist: YouTubePlaylist, by: int = 1) -> None:
        await self._playlists.update(playlist.id, item_count=playlist.item_count + by)
        await self._db.commit()

    async def delete_playlist_row(self, playlist_id: UUID) -> None:
        await self._playlists.delete(playlist_id)
        await self._db.commit()


__all__ = [
    "ChannelCapExceededError",
    "MultipleChannelsAmbiguousError",
    "NoChannelConnectedError",
    "TokenRefreshError",
    "YouTubeAdminService",
    "YouTubeNotConfiguredError",
    "build_youtube_service",
]
