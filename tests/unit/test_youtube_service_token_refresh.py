"""Service-layer tests for the invalid_grant → YouTubeTokenExpiredError
conversion in ``services/youtube.py``.

Root cause of the reported "ApiError (502) invalid_grant" bug: a dead or
revoked Google OAuth grant raises ``google.auth.exceptions.RefreshError``
that nothing converted into the typed :class:`YouTubeTokenExpiredError`,
so the route layer mapped it to an opaque 502 instead of an actionable
401 "reconnect this channel". These tests pin the conversion on both
paths:

* the explicit refresh (``refresh_tokens_if_needed`` → ``credentials.refresh``)
* the auto-refresh that google-auth performs *inside* a data API call
  (``get_video_stats``) when the locally-stored ``token_expiry`` is still
  in the future but the grant was revoked server-side.

A non-``invalid_grant`` ``RefreshError`` (e.g. a transient
``temporarily_unavailable``) must NOT be reclassified — it propagates
unchanged so it keeps mapping to a 502.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError

from drevalis.services.youtube import (
    YouTubeService,
    YouTubeTokenExpiredError,
    _is_invalid_grant,
)

_FERNET_KEY = base64.urlsafe_b64encode(b"\x00" * 32).decode()


def _service() -> YouTubeService:
    return YouTubeService(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://localhost/callback",
        encryption_key=_FERNET_KEY,
    )


# ── _is_invalid_grant classifier ──────────────────────────────────────


class TestIsInvalidGrant:
    def test_detects_dict_form(self) -> None:
        exc = RefreshError(
            "invalid_grant: Token has been expired or revoked.",
            {"error": "invalid_grant", "error_description": "Token revoked."},
        )
        assert _is_invalid_grant(exc) is True

    def test_detects_message_only_form(self) -> None:
        # Older google-auth versions raise with just a string arg.
        exc = RefreshError("invalid_grant: Token has been expired or revoked.")
        assert _is_invalid_grant(exc) is True

    def test_rejects_transient_error(self) -> None:
        exc = RefreshError(
            "temporarily_unavailable: try again",
            {"error": "temporarily_unavailable"},
        )
        assert _is_invalid_grant(exc) is False

    def test_structured_code_overrides_misleading_message(self) -> None:
        # A structured error code wins over the message text: a transient
        # error whose message happens to mention 'invalid_grant' must NOT
        # be reclassified as a dead grant (it would wrongly become a 401).
        exc = RefreshError(
            "This is not an invalid_grant; retry later.",
            {"error": "temporarily_unavailable"},
        )
        assert _is_invalid_grant(exc) is False


# ── Explicit refresh path ─────────────────────────────────────────────


class TestRefreshTokensIfNeeded:
    async def test_invalid_grant_raises_token_expired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        svc = _service()
        creds = MagicMock()
        creds.refresh.side_effect = RefreshError(
            "invalid_grant: Token has been expired or revoked.",
            {"error": "invalid_grant"},
        )
        monkeypatch.setattr(svc, "_build_credentials", lambda *a, **k: creds)

        past = datetime(2000, 1, 1, tzinfo=UTC)
        with pytest.raises(YouTubeTokenExpiredError):
            await svc.refresh_tokens_if_needed("enc-access", "enc-refresh", past)

    async def test_transient_refresh_error_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = _service()
        creds = MagicMock()
        creds.refresh.side_effect = RefreshError(
            "temporarily_unavailable",
            {"error": "temporarily_unavailable"},
        )
        monkeypatch.setattr(svc, "_build_credentials", lambda *a, **k: creds)

        past = datetime(2000, 1, 1, tzinfo=UTC)
        # NOT converted — a transient google error must keep its type so
        # the route maps it to a 502 (retryable) rather than a 401.
        with pytest.raises(RefreshError):
            await svc.refresh_tokens_if_needed("enc-access", "enc-refresh", past)

    async def test_still_valid_token_skips_refresh(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = _service()
        creds = MagicMock()
        # Should never be touched — expiry is in the future.
        creds.refresh.side_effect = AssertionError("refresh must not run")
        monkeypatch.setattr(svc, "_build_credentials", lambda *a, **k: creds)

        future = datetime(2999, 1, 1, tzinfo=UTC)
        assert await svc.refresh_tokens_if_needed("enc-access", "enc-refresh", future) is None


# ── Auto-refresh-inside-data-call path ────────────────────────────────


class TestGetVideoStatsAutoRefresh:
    async def test_invalid_grant_during_execute_raises_token_expired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = _service()
        monkeypatch.setattr(svc, "_build_credentials", lambda *a, **k: MagicMock())

        fake_youtube = MagicMock()
        fake_youtube.videos.return_value.list.return_value.execute.side_effect = RefreshError(
            "invalid_grant: Token has been expired or revoked.",
            {"error": "invalid_grant"},
        )
        monkeypatch.setattr(
            "googleapiclient.discovery.build", lambda *a, **k: fake_youtube
        )

        # token_expiry in the future → no explicit refresh; the dead grant
        # only surfaces when google-auth auto-refreshes inside execute().
        future = datetime(2999, 1, 1, tzinfo=UTC)
        with pytest.raises(YouTubeTokenExpiredError):
            await svc.get_video_stats("enc-access", "enc-refresh", future, ["vid1"])

    async def test_transient_error_during_execute_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = _service()
        monkeypatch.setattr(svc, "_build_credentials", lambda *a, **k: MagicMock())

        fake_youtube = MagicMock()
        fake_youtube.videos.return_value.list.return_value.execute.side_effect = RefreshError(
            "temporarily_unavailable",
            {"error": "temporarily_unavailable"},
        )
        monkeypatch.setattr(
            "googleapiclient.discovery.build", lambda *a, **k: fake_youtube
        )

        future = datetime(2999, 1, 1, tzinfo=UTC)
        with pytest.raises(RefreshError):
            await svc.get_video_stats("enc-access", "enc-refresh", future, ["vid1"])


# ── Write-method auto-refresh path (via _run_credentialed) ────────────


class TestWriteMethodAutoRefresh:
    async def test_delete_video_invalid_grant_raises_token_expired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Confirms the shared _run_credentialed helper converts a dead grant
        # for non-analytics (write) methods too, so their routes can 401.
        svc = _service()
        monkeypatch.setattr(svc, "_build_credentials", lambda *a, **k: MagicMock())

        fake_youtube = MagicMock()
        fake_youtube.videos.return_value.delete.return_value.execute.side_effect = RefreshError(
            "invalid_grant: Token has been expired or revoked.",
            {"error": "invalid_grant"},
        )
        monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **k: fake_youtube)

        future = datetime(2999, 1, 1, tzinfo=UTC)
        with pytest.raises(YouTubeTokenExpiredError):
            await svc.delete_video("enc-access", "enc-refresh", future, "vid1")

    async def test_delete_video_transient_error_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = _service()
        monkeypatch.setattr(svc, "_build_credentials", lambda *a, **k: MagicMock())

        fake_youtube = MagicMock()
        fake_youtube.videos.return_value.delete.return_value.execute.side_effect = RefreshError(
            "temporarily_unavailable",
            {"error": "temporarily_unavailable"},
        )
        monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **k: fake_youtube)

        future = datetime(2999, 1, 1, tzinfo=UTC)
        with pytest.raises(RefreshError):
            await svc.delete_video("enc-access", "enc-refresh", future, "vid1")
