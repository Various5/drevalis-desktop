"""Tests for the LicenseGateMiddleware (core/license/gate.py).

Pins the contract that decides when a request is gated by the license
status. Wrong answers ship as either silent paywall bypasses or a
locked-out user when their license is healthy.

Tests use a tiny Starlette app + TestClient so we exercise the actual
ASGI dispatch path, not just the middleware's branches in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from drevalis.core.license import gate as _gate
from drevalis.core.license import state as _state
from drevalis.core.license.claims import LicenseClaims
from drevalis.core.license.gate import LicenseGateMiddleware
from drevalis.core.license.state import LicenseState, LicenseStatus

# ── Helpers ──────────────────────────────────────────────────────────


def _claims() -> LicenseClaims:
    now = int(datetime.now(tz=UTC).timestamp())
    return LicenseClaims(
        iss="x",
        sub="x",
        jti="x",
        tier="creator",
        iat=now - 100,
        nbf=now - 100,
        exp=now + 86400,
        period_end=now + 86400,
    )


def _set(status: LicenseStatus, claims: LicenseClaims | None = None) -> None:
    _state.set_state(LicenseState(status=status, claims=claims))


async def _ok(request: Request) -> JSONResponse:  # noqa: ARG001
    return JSONResponse({"ok": True})


def _make_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build a Starlette app guarded by LicenseGateMiddleware.

    Stub the heavy parts of the middleware that touch real Redis / DB:
    bootstrap_license_state and refresh_if_stale are no-ops; demo_mode
    is False; ``get_redis`` yields a dummy.
    """

    async def _no_bootstrap(*args: Any, **kwargs: Any) -> None:
        return None

    async def _no_refresh(*args: Any, **kwargs: Any) -> None:
        return None

    async def _fake_redis_gen() -> Any:  # async generator
        class _Dummy:
            pass

        yield _Dummy()

    class _StubSettings:
        demo_mode = False
        license_public_key_override = None

    monkeypatch.setattr(_gate, "bootstrap_license_state", _no_bootstrap)
    monkeypatch.setattr(_gate, "refresh_if_stale", _no_refresh)
    # Make is_bootstrapped read True so the bootstrap_license_state stub
    # path is mostly skipped — those tests verify the bootstrap-race
    # branch separately.
    _state.set_state(LicenseState(status=LicenseStatus.UNACTIVATED))

    # The middleware imports get_settings + get_redis via late `from`
    # statements inside dispatch. Monkey-patch the source modules so the
    # middleware's late imports pick up the stubs.
    from drevalis.core import deps as _deps
    from drevalis.core import redis as _redis_mod

    monkeypatch.setattr(_deps, "get_settings", lambda: _StubSettings())
    monkeypatch.setattr(_redis_mod, "get_redis", _fake_redis_gen)

    app = Starlette(
        routes=[
            Route("/api/v1/episodes", _ok),
            Route("/api/v1/license/status", _ok),
            Route("/health", _ok),
            Route("/storage/foo.mp4", _ok),
            Route("/docs", _ok),
            Route("/", _ok),  # not /api/ or /ws/ — passes through
        ],
        middleware=[],
    )
    app.add_middleware(LicenseGateMiddleware)
    return TestClient(app)


# ── Exempt paths always pass ─────────────────────────────────────────


class TestExemptPaths:
    def test_health_passes_when_unactivated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(monkeypatch)
        _set(LicenseStatus.UNACTIVATED)
        r = client.get("/health")
        assert r.status_code == 200

    def test_license_status_passes_when_unactivated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The activation wizard MUST be reachable even before activation —
        # otherwise the user can't activate.
        client = _make_app(monkeypatch)
        _set(LicenseStatus.UNACTIVATED)
        r = client.get("/api/v1/license/status")
        assert r.status_code == 200

    def test_docs_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(monkeypatch)
        _set(LicenseStatus.UNACTIVATED)
        r = client.get("/docs")
        assert r.status_code == 200

    def test_storage_passes_when_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Past output must remain downloadable even if the license expired.
        client = _make_app(monkeypatch)
        _set(LicenseStatus.INVALID)
        r = client.get("/storage/foo.mp4")
        assert r.status_code == 200


# ── Non-guarded paths pass through ───────────────────────────────────


class TestNonGuardedPaths:
    def test_root_passes_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(monkeypatch)
        _set(LicenseStatus.UNACTIVATED)
        r = client.get("/")
        assert r.status_code == 200


# ── Guarded paths gated by status ────────────────────────────────────


class TestGuardedPathsByStatus:
    def test_active_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(monkeypatch)
        _set(LicenseStatus.ACTIVE, claims=_claims())
        r = client.get("/api/v1/episodes")
        assert r.status_code == 200

    def test_grace_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(monkeypatch)
        _set(LicenseStatus.GRACE, claims=_claims())
        r = client.get("/api/v1/episodes")
        assert r.status_code == 200

    def test_unactivated_returns_402_with_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(monkeypatch)
        _set(LicenseStatus.UNACTIVATED)
        r = client.get("/api/v1/episodes")
        assert r.status_code == 402
        body = r.json()
        assert body["detail"]["error"] == "license_required"
        assert body["detail"]["state"] == "unactivated"

    def test_expired_returns_402(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(monkeypatch)
        _set(LicenseStatus.EXPIRED)
        r = client.get("/api/v1/episodes")
        assert r.status_code == 402
        assert r.json()["detail"]["state"] == "expired"

    def test_invalid_returns_402_with_error_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(monkeypatch)
        _state.set_state(LicenseState(status=LicenseStatus.INVALID, error="signature mismatch"))
        r = client.get("/api/v1/episodes")
        assert r.status_code == 402
        body = r.json()
        assert body["detail"]["state"] == "invalid"
        assert body["detail"]["error_message"] == "signature mismatch"


# ── Demo mode bypass ─────────────────────────────────────────────────


class TestDemoModeBypass:
    def test_demo_mode_bypasses_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from drevalis.core import deps as _deps

        class _DemoSettings:
            demo_mode = True
            license_public_key_override = None

        async def _no_bootstrap(*args: Any, **kwargs: Any) -> None:
            return None

        async def _no_refresh(*args: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr(_gate, "bootstrap_license_state", _no_bootstrap)
        monkeypatch.setattr(_gate, "refresh_if_stale", _no_refresh)
        monkeypatch.setattr(_deps, "get_settings", lambda: _DemoSettings())

        app = Starlette(routes=[Route("/api/v1/episodes", _ok)])
        app.add_middleware(LicenseGateMiddleware)

        _set(LicenseStatus.UNACTIVATED)  # would normally 402
        client = TestClient(app)
        r = client.get("/api/v1/episodes")
        assert r.status_code == 200


# ── Custom prefix configuration ──────────────────────────────────────


class TestCustomPrefixes:
    def test_custom_exempt_prefix_passes(self) -> None:
        # Caller can pass extra exempt prefixes to whitelist a custom path.
        app = Starlette(routes=[Route("/admin/special", _ok)])
        app.add_middleware(
            LicenseGateMiddleware,
            exempt_prefixes=("/admin/",),
            guarded_prefixes=("/admin/",),
        )
        _set(LicenseStatus.UNACTIVATED)
        client = TestClient(app)
        r = client.get("/admin/special")
        assert r.status_code == 200

    def test_custom_guarded_prefix_blocks(self) -> None:
        app = Starlette(routes=[Route("/admin/special", _ok)])
        app.add_middleware(
            LicenseGateMiddleware,
            exempt_prefixes=("/health",),
            guarded_prefixes=("/admin/",),
        )
        _set(LicenseStatus.UNACTIVATED)
        client = TestClient(app)
        r = client.get("/admin/special")
        assert r.status_code == 402
