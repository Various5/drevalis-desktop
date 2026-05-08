"""Tests for the tightened analytics-scope detection + tokeninfo helper."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from drevalis.services.youtube import (
    _decode_google_http_error,
    fetch_token_scopes,
)

# ── _decode_google_http_error ────────────────────────────────────────────


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status = status


class _FakeHttpError(Exception):
    """Stand-in for googleapiclient.errors.HttpError."""

    def __init__(
        self,
        status: int = 403,
        content: bytes | None = None,
        error_details: list | None = None,
    ) -> None:
        super().__init__(f"HttpError {status}")
        self.resp = _FakeResp(status)
        self.content = content
        self.error_details = error_details


class TestDecodeGoogleHttpError:
    def test_uses_error_details_when_available(self) -> None:
        exc = _FakeHttpError(
            status=403,
            error_details=[
                {
                    "reason": "insufficientPermissions",
                    "message": "Insufficient Permission",
                }
            ],
        )
        result = _decode_google_http_error(exc)
        assert result["status"] == 403
        assert result["reason"] == "insufficientPermissions"
        assert result["message"] == "Insufficient Permission"

    def test_falls_back_to_content_json(self) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": 403,
                    "message": "Forbidden",
                    "errors": [{"reason": "forbidden", "message": "The user is not the owner."}],
                }
            }
        ).encode("utf-8")
        exc = _FakeHttpError(status=403, content=body)
        result = _decode_google_http_error(exc)
        assert result["reason"] == "forbidden"
        assert result["message"] == "The user is not the owner."

    def test_quota_exceeded_recognised(self) -> None:
        body = json.dumps(
            {"error": {"errors": [{"reason": "quotaExceeded", "message": "Quota."}]}}
        ).encode("utf-8")
        exc = _FakeHttpError(status=403, content=body)
        result = _decode_google_http_error(exc)
        assert result["reason"] == "quotaExceeded"

    def test_garbage_content_falls_back_gracefully(self) -> None:
        exc = _FakeHttpError(status=500, content=b"<html>not json</html>")
        result = _decode_google_http_error(exc)
        assert result["status"] == 500
        # Reason couldn't be parsed — should be None, not crash.
        assert result["reason"] is None
        # Message is the str(exc) fallback.
        assert "HttpError" in (result["message"] or "")

    def test_no_resp_attr_doesnt_crash(self) -> None:
        # An exception without ``resp`` attribute — robustness check.
        result = _decode_google_http_error(Exception("plain error"))
        assert result["status"] is None
        assert result["reason"] is None


# ── fetch_token_scopes ───────────────────────────────────────────────────


class _FakeHttpResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeHttpResponse | Exception) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args, **kwargs) -> None:
        return None

    async def get(self, *args, **kwargs):  # noqa: ANN001, ANN003
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class TestFetchTokenScopes:
    async def test_parses_scope_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = _FakeHttpResponse(
            200,
            {
                "scope": (
                    "https://www.googleapis.com/auth/youtube.upload "
                    "https://www.googleapis.com/auth/youtube "
                    "https://www.googleapis.com/auth/yt-analytics.readonly"
                )
            },
        )
        with patch(
            "httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(response),
        ):
            scopes = await fetch_token_scopes("fake-token")
        assert "https://www.googleapis.com/auth/yt-analytics.readonly" in scopes
        assert "https://www.googleapis.com/auth/youtube.upload" in scopes
        assert "https://www.googleapis.com/auth/youtube" in scopes

    async def test_missing_analytics_scope(self) -> None:
        response = _FakeHttpResponse(
            200,
            {
                "scope": (
                    "https://www.googleapis.com/auth/youtube.upload "
                    "https://www.googleapis.com/auth/youtube"
                )
            },
        )
        with patch(
            "httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(response),
        ):
            scopes = await fetch_token_scopes("fake-token")
        assert "https://www.googleapis.com/auth/yt-analytics.readonly" not in scopes
        assert "https://www.googleapis.com/auth/youtube.upload" in scopes

    async def test_revoked_token_returns_empty(self) -> None:
        response = _FakeHttpResponse(400, {"error": "invalid_token"})
        with patch(
            "httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(response),
        ):
            scopes = await fetch_token_scopes("revoked-token")
        assert scopes == []

    async def test_network_failure_returns_empty(self) -> None:
        import httpx as _httpx

        with patch(
            "httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(_httpx.ConnectError("boom")),
        ):
            scopes = await fetch_token_scopes("any-token")
        assert scopes == []

    async def test_empty_scope_string(self) -> None:
        response = _FakeHttpResponse(200, {"scope": ""})
        with patch(
            "httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(response),
        ):
            scopes = await fetch_token_scopes("token")
        assert scopes == []
