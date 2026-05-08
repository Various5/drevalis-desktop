"""Unit tests for OptionalAPIKeyMiddleware.

Strategy
--------
The middleware reads ``API_AUTH_TOKEN`` from ``os.environ`` in ``__init__``,
so environment manipulation must happen *before* the middleware object is
created.  Two helper fixtures are provided:

* ``app_with_token`` -- builds a Starlette test application with the
  middleware initialised with an explicit token (bypasses os.environ so
  tests are hermetic).
* The shared ``client`` fixture from conftest.py already uses ``create_app()``,
  which calls ``add_middleware(OptionalAPIKeyMiddleware)`` without a token
  argument.  When ``API_AUTH_TOKEN`` is absent from the environment the
  middleware is therefore disabled -- used for the "auth disabled" tests.

All tests target the middleware's observable HTTP behaviour, not its internals.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from drevalis.core.auth import OptionalAPIKeyMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_TOKEN = "super-secret-test-token-abc123"


async def _dummy_api_endpoint(request: Request) -> JSONResponse:
    """Minimal endpoint that lives under /api/v1/ to trigger auth checks."""
    return JSONResponse({"ok": True})


async def _dummy_ws_endpoint(request: Request) -> JSONResponse:
    """Minimal endpoint that lives under /ws/ to trigger auth checks."""
    return JSONResponse({"ok": True})


async def _dummy_health_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _dummy_docs_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({"docs": True})


async def _dummy_openapi_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({})


def _build_protected_app(token: str | None) -> Starlette:
    """Build a minimal Starlette app with the middleware wired in.

    Using Starlette directly (rather than the full FastAPI app) keeps these
    tests fast and isolated from the rest of the application stack.
    """
    app = Starlette(
        routes=[
            Route("/health", _dummy_health_endpoint),
            Route("/docs", _dummy_docs_endpoint),
            Route("/openapi.json", _dummy_openapi_endpoint),
            Route("/api/v1/series", _dummy_api_endpoint),
            Route("/ws/progress/123", _dummy_ws_endpoint),
        ]
    )
    # Inject the token explicitly so the test does not depend on os.environ.
    app.add_middleware(OptionalAPIKeyMiddleware, token=token)
    return app


@pytest.fixture
async def protected_client() -> AsyncGenerator[AsyncClient, None]:
    """Client connected to the middleware under test with a valid token configured."""
    app = _build_protected_app(token=_VALID_TOKEN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def open_client() -> AsyncGenerator[AsyncClient, None]:
    """Client connected to the middleware under test with *no* token (auth disabled)."""
    app = _build_protected_app(token=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Auth disabled (no API_AUTH_TOKEN configured)
# ---------------------------------------------------------------------------


class TestAuthDisabled:
    """When no token is configured every request must pass through."""

    async def test_api_request_passes_without_any_header(self, open_client: AsyncClient) -> None:
        response = await open_client.get("/api/v1/series")

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    async def test_api_request_passes_with_irrelevant_header(
        self, open_client: AsyncClient
    ) -> None:
        response = await open_client.get("/api/v1/series", headers={"X-Custom-Header": "anything"})

        assert response.status_code == 200

    async def test_ws_request_passes_without_token(self, open_client: AsyncClient) -> None:
        response = await open_client.get("/ws/progress/123")

        assert response.status_code == 200

    async def test_health_passes_without_token(self, open_client: AsyncClient) -> None:
        response = await open_client.get("/health")

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Auth enabled -- missing / malformed token
# ---------------------------------------------------------------------------


class TestAuthRequired:
    """When a token is configured, /api/ and /ws/ requests require a Bearer token."""

    async def test_missing_authorization_header_returns_401(
        self, protected_client: AsyncClient
    ) -> None:
        response = await protected_client.get("/api/v1/series")

        assert response.status_code == 401
        assert "detail" in response.json()

    async def test_bearer_prefix_missing_returns_401(self, protected_client: AsyncClient) -> None:
        # Provides the raw token without the "Bearer " prefix.
        response = await protected_client.get(
            "/api/v1/series", headers={"Authorization": _VALID_TOKEN}
        )

        assert response.status_code == 401

    async def test_wrong_scheme_returns_401(self, protected_client: AsyncClient) -> None:
        response = await protected_client.get(
            "/api/v1/series", headers={"Authorization": f"Token {_VALID_TOKEN}"}
        )

        assert response.status_code == 401

    async def test_ws_missing_token_returns_401(self, protected_client: AsyncClient) -> None:
        response = await protected_client.get("/ws/progress/123")

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Auth enabled -- invalid token value
# ---------------------------------------------------------------------------


class TestInvalidToken:
    """A Bearer token that does not match the configured secret must be rejected."""

    async def test_wrong_token_returns_403(self, protected_client: AsyncClient) -> None:
        response = await protected_client.get(
            "/api/v1/series", headers={"Authorization": "Bearer wrong-token"}
        )

        assert response.status_code == 403
        assert "detail" in response.json()

    async def test_empty_token_value_returns_403(self, protected_client: AsyncClient) -> None:
        # "Bearer " followed by an empty string.
        response = await protected_client.get(
            "/api/v1/series", headers={"Authorization": "Bearer "}
        )

        assert response.status_code == 403

    async def test_partial_token_returns_403(self, protected_client: AsyncClient) -> None:
        partial = _VALID_TOKEN[: len(_VALID_TOKEN) // 2]
        response = await protected_client.get(
            "/api/v1/series", headers={"Authorization": f"Bearer {partial}"}
        )

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Auth enabled -- valid token
# ---------------------------------------------------------------------------


class TestValidToken:
    """A correctly-formed Bearer token matching the secret must be allowed through."""

    async def test_correct_token_returns_200(self, protected_client: AsyncClient) -> None:
        response = await protected_client.get(
            "/api/v1/series", headers={"Authorization": f"Bearer {_VALID_TOKEN}"}
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    async def test_correct_token_on_ws_route_returns_200(
        self, protected_client: AsyncClient
    ) -> None:
        response = await protected_client.get(
            "/ws/progress/123", headers={"Authorization": f"Bearer {_VALID_TOKEN}"}
        )

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Exempt paths -- auth is enabled but these routes are always allowed
# ---------------------------------------------------------------------------


class TestExemptPaths:
    """/health, /docs, and /openapi.json are exempt regardless of token config."""

    async def test_health_exempt_no_token(self, protected_client: AsyncClient) -> None:
        response = await protected_client.get("/health")

        assert response.status_code == 200

    async def test_docs_exempt_no_token(self, protected_client: AsyncClient) -> None:
        response = await protected_client.get("/docs")

        assert response.status_code == 200

    async def test_openapi_json_exempt_no_token(self, protected_client: AsyncClient) -> None:
        response = await protected_client.get("/openapi.json")

        assert response.status_code == 200

    async def test_health_exempt_with_wrong_token(self, protected_client: AsyncClient) -> None:
        # Even a wrong token must not block /health.
        response = await protected_client.get("/health", headers={"Authorization": "Bearer wrong"})

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Token initialisation from os.environ (constructor-level integration)
# ---------------------------------------------------------------------------


class TestEnvironmentTokenResolution:
    """Middleware constructor falls back to os.environ when no token is passed."""

    def test_token_read_from_env_when_not_explicitly_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("API_AUTH_TOKEN", "env-token-xyz")

        # Build without passing the token kwarg -- it must read from env.
        from starlette.testclient import TestClient

        app = Starlette(routes=[Route("/api/v1/test", _dummy_api_endpoint)])
        app.add_middleware(OptionalAPIKeyMiddleware)

        client = TestClient(app, raise_server_exceptions=True)

        # No token -- expect 401
        response = client.get("/api/v1/test")
        assert response.status_code == 401

        # Correct token -- expect 200
        response = client.get("/api/v1/test", headers={"Authorization": "Bearer env-token-xyz"})
        assert response.status_code == 200

    def test_no_env_var_means_auth_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)

        from starlette.testclient import TestClient

        app = Starlette(routes=[Route("/api/v1/test", _dummy_api_endpoint)])
        app.add_middleware(OptionalAPIKeyMiddleware)

        client = TestClient(app, raise_server_exceptions=True)

        response = client.get("/api/v1/test")
        assert response.status_code == 200
