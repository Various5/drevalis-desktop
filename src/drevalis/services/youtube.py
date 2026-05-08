"""YouTube Data API v3 integration — OAuth and video upload.

Wraps the synchronous ``google-api-python-client`` library with
``asyncio.to_thread`` so callers can use ``await`` without blocking
the event loop.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from drevalis.core.security import decrypt_value, decrypt_value_multi, encrypt_value

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class YouTubeTokenExpiredError(Exception):
    """Raised when the access token is expired and cannot be refreshed.

    Distinct from a generic network error - it means the stored grant is
    dead and the user must re-auth through the OAuth flow. The frontend
    maps this to a "Reconnect YouTube" CTA.
    """


class YouTubeService:
    """High-level service for YouTube OAuth and video uploads."""

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        # yt-analytics.readonly unlocks the YouTube Analytics API v2
        # (CTR, average view duration, retention, subscribers gained/lost).
        # Existing users whose tokens were minted before this was added
        # will see 403 on the analytics endpoint until they reconnect —
        # the frontend catches that and prompts a re-auth.
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        encryption_key: str,
        *,
        encryption_keys: dict[int, str] | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.encryption_key = encryption_key
        # Versioned key map for rotation-aware OAuth-token decryption.
        self._encryption_keys: dict[int, str] = encryption_keys or {1: encryption_key}
        # Store PKCE code_verifiers keyed by OAuth state parameter
        self._pending_states: dict[str, str | None] = {}

    def _decrypt(self, ciphertext: str) -> str:
        if len(self._encryption_keys) > 1:
            plaintext, _ = decrypt_value_multi(ciphertext, self._encryption_keys)
            return plaintext
        return decrypt_value(ciphertext, self.encryption_key)

    def _encrypt(self, plaintext: str) -> tuple[str, int]:
        return encrypt_value(
            plaintext,
            self.encryption_key,
            version=max(self._encryption_keys),
        )

    # ── OAuth ────────────────────────────────────────────────────────────

    def _client_config(self) -> dict[str, Any]:
        """Build a client config dict for ``google_auth_oauthlib``."""
        return {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

    def get_auth_url(self) -> tuple[str, str]:
        """Generate the Google OAuth consent URL for YouTube authorization.

        Uses manual URL construction to avoid google_auth_oauthlib's
        automatic PKCE (which requires persisting code_verifier state).
        """
        import secrets
        from urllib.parse import urlencode

        state = secrets.token_urlsafe(24)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
        return auth_url, state

    async def handle_callback(self, code: str, state: str | None = None) -> dict[str, Any]:
        """Exchange an authorization code for OAuth tokens.

        Uses direct HTTP token exchange (no PKCE) to avoid state
        persistence issues with google_auth_oauthlib.
        """

        def _exchange() -> dict[str, Any]:
            import httpx as _httpx
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            # Exchange code for tokens via direct HTTP POST
            token_resp = _httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

            credentials = Credentials(
                token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=self.SCOPES,
            )

            # Encrypt tokens.
            access_enc, key_ver = self._encrypt(credentials.token or "")
            refresh_enc = ""
            if credentials.refresh_token:
                refresh_enc, _ = self._encrypt(credentials.refresh_token)

            # Fetch channel info.
            youtube = build("youtube", "v3", credentials=credentials)
            response = youtube.channels().list(part="snippet", mine=True).execute()
            items = response.get("items", [])
            if not items:
                raise ValueError("No YouTube channel found for this account")

            channel = items[0]
            return {
                "channel_id": channel["id"],
                "channel_name": channel["snippet"]["title"],
                "access_token_encrypted": access_enc,
                "refresh_token_encrypted": refresh_enc,
                "token_key_version": key_ver,
                "token_expiry": credentials.expiry,
            }

        result = await asyncio.to_thread(_exchange)
        logger.info(
            "youtube_oauth_callback_success",
            channel_id=result["channel_id"],
            channel_name=result["channel_name"],
        )
        return result

    # ── Credentials ──────────────────────────────────────────────────────

    def _build_credentials(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
    ) -> Any:
        """Decrypt tokens and construct a ``google.oauth2.credentials.Credentials``."""
        from google.oauth2.credentials import Credentials

        access_token = self._decrypt(access_token_encrypted)
        refresh_token = None
        if refresh_token_encrypted:
            refresh_token = self._decrypt(refresh_token_encrypted)

        # Google's Credentials uses naive datetimes internally (utcnow),
        # so strip timezone info to avoid comparison errors.
        expiry = token_expiry
        if expiry and expiry.tzinfo is not None:
            expiry = expiry.replace(tzinfo=None)

        return Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            expiry=expiry,
        )

    # ── Upload ───────────────────────────────────────────────────────────

    async def delete_video(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
        video_id: str,
    ) -> None:
        """Delete a video from YouTube via the Data API v3."""
        credentials = self._build_credentials(
            access_token_encrypted, refresh_token_encrypted, token_expiry
        )

        def _do_delete() -> None:
            from googleapiclient.discovery import build

            youtube = build("youtube", "v3", credentials=credentials)
            youtube.videos().delete(id=video_id).execute()

        await asyncio.to_thread(_do_delete)
        logger.info("youtube_video_deleted", video_id=video_id)

    async def upload_video(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        privacy_status: str,
        thumbnail_path: Path | None = None,
    ) -> dict[str, str]:
        """Upload a video to YouTube via the Data API v3.

        Returns a dict with ``video_id`` and ``url``.
        """
        credentials = self._build_credentials(
            access_token_encrypted, refresh_token_encrypted, token_expiry
        )

        def _do_upload() -> dict[str, str]:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            youtube = build("youtube", "v3", credentials=credentials)

            body: dict[str, Any] = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": tags,
                    "categoryId": "22",  # "People & Blogs"
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": False,
                },
            }

            media = MediaFileUpload(
                str(video_path),
                mimetype="video/mp4",
                resumable=True,
                chunksize=10 * 1024 * 1024,  # 10 MB chunks
            )

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                _, response = request.next_chunk()

            video_id = response["id"]
            url = f"https://www.youtube.com/watch?v={video_id}"

            # Set thumbnail if provided.
            if thumbnail_path and thumbnail_path.exists():
                try:
                    youtube.thumbnails().set(
                        videoId=video_id,
                        media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
                    ).execute()
                    logger.info(
                        "youtube_thumbnail_set",
                        video_id=video_id,
                    )
                except Exception:
                    logger.warning(
                        "youtube_thumbnail_set_failed",
                        video_id=video_id,
                        exc_info=True,
                    )

            return {"video_id": video_id, "url": url}

        logger.info(
            "youtube_upload_starting",
            video_path=str(video_path),
            title=title,
            privacy=privacy_status,
        )
        result = await asyncio.to_thread(_do_upload)
        logger.info(
            "youtube_upload_complete",
            video_id=result["video_id"],
            url=result["url"],
        )
        return result

    # ── Token refresh ────────────────────────────────────────────────────

    async def refresh_tokens_if_needed(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
    ) -> dict[str, Any] | None:
        """Refresh the access token if it has expired.

        Returns updated encrypted tokens dict if refreshed, or ``None`` if
        the token is still valid.
        """
        expired = False
        if token_expiry:
            # Ensure both datetimes are timezone-aware for comparison
            expiry = token_expiry if token_expiry.tzinfo else token_expiry.replace(tzinfo=UTC)
            if expiry > datetime.now(UTC):
                return None
            expired = True

        if not refresh_token_encrypted:
            # If the token is already expired and we have no refresh token,
            # bail loudly - callers that silently continue will hit a
            # cryptic 401 on the next API call. Raise so the caller can
            # surface a meaningful "reconnect this channel" error.
            if expired:
                raise YouTubeTokenExpiredError(
                    "YouTube access token has expired and no refresh token is "
                    "stored. Reconnect the channel via Settings -> YouTube."
                )
            logger.warning("youtube_no_refresh_token")
            return None

        credentials = self._build_credentials(
            access_token_encrypted, refresh_token_encrypted, token_expiry
        )

        def _refresh() -> dict[str, Any]:
            import google.auth.transport.requests

            request = google.auth.transport.requests.Request()
            credentials.refresh(request)

            new_access_enc, key_ver = self._encrypt(credentials.token)
            result: dict[str, Any] = {
                "access_token_encrypted": new_access_enc,
                "token_key_version": key_ver,
                "token_expiry": credentials.expiry,
            }
            if credentials.refresh_token:
                new_refresh_enc, _ = self._encrypt(credentials.refresh_token)
                result["refresh_token_encrypted"] = new_refresh_enc
            return result

        updated = await asyncio.to_thread(_refresh)
        logger.info("youtube_token_refreshed")
        return updated

    # ── Playlists ─────────────────────────────────────────────────────────

    async def create_playlist(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
        title: str,
        description: str,
        privacy_status: str,
    ) -> dict[str, Any]:
        """Create a new YouTube playlist and return its metadata.

        Returns a dict with ``playlist_id``, ``title``, ``description``,
        ``privacy_status``, and ``item_count``.
        """
        credentials = self._build_credentials(
            access_token_encrypted, refresh_token_encrypted, token_expiry
        )

        def _create() -> dict[str, Any]:
            from googleapiclient.discovery import build

            youtube = build("youtube", "v3", credentials=credentials)
            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                },
                "status": {"privacyStatus": privacy_status},
            }
            response = youtube.playlists().insert(part="snippet,status", body=body).execute()
            return {
                "playlist_id": response["id"],
                "title": response["snippet"]["title"],
                "description": response["snippet"].get("description", ""),
                "privacy_status": response["status"]["privacyStatus"],
                "item_count": response["contentDetails"].get("itemCount", 0)
                if "contentDetails" in response
                else 0,
            }

        result = await asyncio.to_thread(_create)
        logger.info("youtube_playlist_created", playlist_id=result["playlist_id"], title=title)
        return result

    async def list_playlists(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
    ) -> list[dict[str, Any]]:
        """Return all playlists owned by the authenticated channel.

        Each entry contains ``playlist_id``, ``title``, ``description``,
        ``privacy_status``, and ``item_count``.
        """
        credentials = self._build_credentials(
            access_token_encrypted, refresh_token_encrypted, token_expiry
        )

        def _list() -> list[dict[str, Any]]:
            from googleapiclient.discovery import build

            youtube = build("youtube", "v3", credentials=credentials)
            results: list[dict[str, Any]] = []
            page_token: str | None = None

            while True:
                kwargs: dict[str, Any] = {
                    "part": "snippet,status,contentDetails",
                    "mine": True,
                    "maxResults": 50,
                }
                if page_token:
                    kwargs["pageToken"] = page_token

                response = youtube.playlists().list(**kwargs).execute()
                for item in response.get("items", []):
                    results.append(
                        {
                            "playlist_id": item["id"],
                            "title": item["snippet"]["title"],
                            "description": item["snippet"].get("description", ""),
                            "privacy_status": item["status"]["privacyStatus"],
                            "item_count": item.get("contentDetails", {}).get("itemCount", 0),
                        }
                    )
                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            return results

        return await asyncio.to_thread(_list)

    async def add_to_playlist(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
        playlist_id: str,
        video_id: str,
    ) -> dict[str, Any]:
        """Add a video to a playlist.

        Returns the created playlist item resource dict (includes ``id``).
        """
        credentials = self._build_credentials(
            access_token_encrypted, refresh_token_encrypted, token_expiry
        )

        def _add() -> dict[str, Any]:
            from googleapiclient.discovery import build

            youtube = build("youtube", "v3", credentials=credentials)
            body = {
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            }
            return youtube.playlistItems().insert(part="snippet", body=body).execute()  # type: ignore[no-any-return]

        result = await asyncio.to_thread(_add)
        logger.info(
            "youtube_playlist_item_added",
            playlist_id=playlist_id,
            video_id=video_id,
            item_id=result.get("id"),
        )
        return result

    async def delete_playlist(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
        playlist_id: str,
    ) -> None:
        """Delete a YouTube playlist by its playlist ID."""
        credentials = self._build_credentials(
            access_token_encrypted, refresh_token_encrypted, token_expiry
        )

        def _delete() -> None:
            from googleapiclient.discovery import build

            youtube = build("youtube", "v3", credentials=credentials)
            youtube.playlists().delete(id=playlist_id).execute()

        await asyncio.to_thread(_delete)
        logger.info("youtube_playlist_deleted", playlist_id=playlist_id)

    # ── Analytics ─────────────────────────────────────────────────────────

    async def get_video_stats(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
        video_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch statistics and snippet for any number of video IDs.

        YouTube's ``videos.list`` accepts at most 50 IDs per call. This
        method chunks the input at 50 and concatenates the results, so
        callers can hand us thousands of IDs without worrying about the
        upstream limit. Returns a list of dicts with ``video_id``,
        ``title``, ``views``, ``likes``, ``comments``, and
        ``published_at``. The YouTube API silently omits videos that do
        not exist or are private, so the returned list may be shorter
        than ``video_ids``.
        """
        if not video_ids:
            return []

        credentials = self._build_credentials(
            access_token_encrypted, refresh_token_encrypted, token_expiry
        )

        # Dedupe while preserving order — multiple callers occasionally
        # pass the same ID twice (e.g. an episode showing up in two
        # series), and YouTube returns it once anyway.
        seen: set[str] = set()
        ordered_ids: list[str] = []
        for vid in video_ids:
            if vid not in seen:
                seen.add(vid)
                ordered_ids.append(vid)

        chunks = [ordered_ids[i : i + 50] for i in range(0, len(ordered_ids), 50)]

        def _fetch_chunk(ids_param: str) -> list[dict[str, Any]]:
            from googleapiclient.discovery import build

            youtube = build("youtube", "v3", credentials=credentials)
            response = (
                youtube.videos()
                .list(
                    part="statistics,snippet",
                    id=ids_param,
                )
                .execute()
            )

            chunk_stats: list[dict[str, Any]] = []
            for item in response.get("items", []):
                statistics = item.get("statistics", {})
                snippet = item.get("snippet", {})
                chunk_stats.append(
                    {
                        "video_id": item["id"],
                        "title": snippet.get("title", ""),
                        "views": int(statistics.get("viewCount", 0)),
                        "likes": int(statistics.get("likeCount", 0)),
                        "comments": int(statistics.get("commentCount", 0)),
                        "published_at": snippet.get("publishedAt"),
                    }
                )
            return chunk_stats

        async def _fetch_all() -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            for chunk in chunks:
                ids_param = ",".join(chunk)
                results.extend(await asyncio.to_thread(_fetch_chunk, ids_param))
            return results

        return await _fetch_all()

    async def get_channel_analytics(
        self,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        token_expiry: datetime | None,
        days: int = 28,
    ) -> dict[str, Any]:
        """Pull channel-level YouTube Analytics for the last ``days`` days.

        Uses the YouTube Analytics API v2 (``youtubeAnalytics.v2``), which
        requires the ``yt-analytics.readonly`` scope in addition to the
        Data API scopes. Returns:

        - ``totals``: aggregated KPIs over the window (views, watch time,
          avg view duration, subscribers gained/lost, impressions, CTR,
          likes, comments, shares).
        - ``daily``: time-series of views + watchMinutes per day for
          drawing a simple sparkline.

        Raises ``AnalyticsNotAuthorized`` if the token doesn't carry the
        analytics scope (403 from Google) — callers surface that as a
        "reconnect to enable analytics" prompt rather than a hard error.
        """
        from datetime import date, timedelta

        credentials = self._build_credentials(
            access_token_encrypted, refresh_token_encrypted, token_expiry
        )

        end = date.today()
        start = end - timedelta(days=max(1, int(days)))

        def _fetch() -> dict[str, Any]:
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError

            ya = build("youtubeAnalytics", "v2", credentials=credentials)

            try:
                totals_resp = (
                    ya.reports()
                    .query(
                        ids="channel==MINE",
                        startDate=start.isoformat(),
                        endDate=end.isoformat(),
                        metrics=(
                            "views,estimatedMinutesWatched,averageViewDuration,"
                            "subscribersGained,subscribersLost,likes,comments,shares,"
                            "cardClickRate,cardImpressions"
                        ),
                    )
                    .execute()
                )
                daily_resp = (
                    ya.reports()
                    .query(
                        ids="channel==MINE",
                        startDate=start.isoformat(),
                        endDate=end.isoformat(),
                        metrics="views,estimatedMinutesWatched",
                        dimensions="day",
                        sort="day",
                    )
                    .execute()
                )
            except HttpError as exc:
                # Pre-fix: ANY 403 → "scope missing". That misclassified
                # plenty of other Google 403s (brand-account channel,
                # quota exhaustion, Analytics API disabled in GCP, no
                # data in window, etc.) as scope errors. The new
                # detection looks at Google's actual ``reason`` field
                # so users get the real story.
                detail = _decode_google_http_error(exc)
                reason = (detail.get("reason") or "").lower()
                if reason in (
                    "insufficientpermissions",
                    "access_token_scope_insufficient",
                    "forbidden_for_scope",
                ):
                    raise AnalyticsNotAuthorized(
                        "YouTube analytics scope missing — reconnect this "
                        "channel from Settings → YouTube to grant access. "
                        "If you've already reconnected, revoke the app at "
                        "myaccount.google.com → Security → Third-party "
                        "access, then reconnect."
                    ) from exc
                # Surface the real Google message instead of pretending
                # every 403 is a scope issue.
                raise RuntimeError(
                    f"YouTube Analytics API error: "
                    f"status={detail.get('status')} reason={detail.get('reason')!r} "
                    f"message={detail.get('message')!r}"
                ) from exc

            # ``rows`` is a list-of-lists keyed by column order.
            tcols = [c["name"] for c in totals_resp.get("columnHeaders", [])]
            trow = (totals_resp.get("rows") or [[0] * len(tcols)])[0]
            totals = dict(zip(tcols, trow, strict=False))

            dcols = [c["name"] for c in daily_resp.get("columnHeaders", [])]
            daily = [dict(zip(dcols, r, strict=False)) for r in (daily_resp.get("rows") or [])]

            def _num(v: Any) -> int | float:
                if isinstance(v, (int, float)):
                    return v
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return 0

            return {
                "window_days": days,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "totals": {
                    "views": int(_num(totals.get("views", 0))),
                    "estimated_minutes_watched": int(
                        _num(totals.get("estimatedMinutesWatched", 0))
                    ),
                    "average_view_duration_seconds": int(
                        _num(totals.get("averageViewDuration", 0))
                    ),
                    "subscribers_gained": int(_num(totals.get("subscribersGained", 0))),
                    "subscribers_lost": int(_num(totals.get("subscribersLost", 0))),
                    "likes": int(_num(totals.get("likes", 0))),
                    "comments": int(_num(totals.get("comments", 0))),
                    "shares": int(_num(totals.get("shares", 0))),
                    "card_click_rate": float(_num(totals.get("cardClickRate", 0))),
                    "card_impressions": int(_num(totals.get("cardImpressions", 0))),
                },
                "daily": [
                    {
                        "day": d.get("day"),
                        "views": int(_num(d.get("views", 0))),
                        "minutes_watched": int(_num(d.get("estimatedMinutesWatched", 0))),
                    }
                    for d in daily
                ],
            }

        return await asyncio.to_thread(_fetch)


class AnalyticsNotAuthorized(Exception):
    """Raised when the channel's OAuth token lacks yt-analytics.readonly.

    Callers should translate this into a 403 with a hint to reconnect
    the channel from Settings → YouTube.
    """


def _decode_google_http_error(exc: Any) -> dict[str, Any]:
    """Best-effort parse of a ``googleapiclient.errors.HttpError``.

    Returns ``{status, reason, message, raw}`` where ``reason`` is the
    machine-readable code from the first error entry (e.g.
    ``insufficientPermissions``, ``forbidden``, ``quotaExceeded``,
    ``brandAccountRequired``). ``message`` is the human-readable
    description. ``raw`` is the parsed response body for callers that
    want to dig deeper.

    Robust to API client versions: prefers ``error_details`` (newer),
    falls back to parsing ``content`` JSON, then to ``str(exc)``.
    """
    import json as _json

    out: dict[str, Any] = {
        "status": getattr(getattr(exc, "resp", None), "status", None),
        "reason": None,
        "message": None,
        "raw": None,
    }

    # Newer googleapiclient: pre-parsed list of error dicts.
    error_details = getattr(exc, "error_details", None)
    if error_details and isinstance(error_details, list) and error_details:
        first = error_details[0] or {}
        out["reason"] = first.get("reason") or first.get("@type")
        out["message"] = first.get("message")
        out["raw"] = error_details

    # Fall back to the raw response body.
    if out["reason"] is None and hasattr(exc, "content"):
        try:
            body = exc.content
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            parsed = _json.loads(body)
            err = parsed.get("error") or {}
            out["raw"] = parsed
            errors_list = err.get("errors") or []
            if errors_list:
                first = errors_list[0]
                out["reason"] = first.get("reason")
                out["message"] = first.get("message")
            if not out["message"]:
                out["message"] = err.get("message")
        except (_json.JSONDecodeError, ValueError, AttributeError):
            pass

    # Last-ditch: pull what we can from the exception's str form.
    if out["message"] is None:
        out["message"] = str(exc)[:300]
    return out


async def fetch_token_scopes(access_token: str) -> list[str]:
    """Return the OAuth scopes the access token actually carries.

    Hits Google's ``tokeninfo`` endpoint — definitive answer to
    "did the user grant analytics scope" without having to call the
    Analytics API and infer from a 403.

    Returns an empty list when the token can't be introspected
    (revoked, expired, network failure). Caller can compare the
    returned scopes against ``YouTubeService.SCOPES`` to decide
    whether a reconnect is required.
    """
    import httpx as _httpx

    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"access_token": access_token},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
    except (_httpx.HTTPError, ValueError):
        return []
    scope_field = data.get("scope") or ""
    return [s for s in scope_field.split(" ") if s]
