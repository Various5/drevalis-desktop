"""Tests for ``main.create_app`` — the FastAPI app factory.

Covers the build path (middleware stack, routers, static mounts).
The lifespan startup path (DB + Redis init) is integration territory
since it requires real services; the build itself is pure construction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI


def _make_settings(*, storage_base: Path) -> Any:
    s = MagicMock()
    s.app_name = "Drevalis"
    s.debug = False
    s.encryption_key = "k"
    s.storage_base_path = storage_base
    s.license_public_key_override = None
    s.demo_mode = False
    s.api_auth_token = None
    return s


# ── create_app: build path ──────────────────────────────────────────


class TestCreateApp:
    def test_returns_fastapi_instance(self, tmp_path: Path) -> None:
        from drevalis.main import create_app

        with patch("drevalis.main.Settings", return_value=_make_settings(storage_base=tmp_path)):
            app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_metadata_set(self, tmp_path: Path) -> None:
        from drevalis.main import create_app

        with patch("drevalis.main.Settings", return_value=_make_settings(storage_base=tmp_path)):
            app = create_app()
        assert app.title == "Drevalis Creator Studio"
        assert app.version == "0.1.0"

    def test_middleware_stack_includes_required_layers(self, tmp_path: Path) -> None:
        # The middleware stack is the security+observability boundary;
        # silently dropping one would ship the install with a hole.
        # Pin every middleware that should be present.
        from drevalis.main import create_app

        with patch("drevalis.main.Settings", return_value=_make_settings(storage_base=tmp_path)):
            app = create_app()
        middleware_names = {m.cls.__name__ for m in app.user_middleware}
        # Required: request logging, security headers, optional auth,
        # license gate, demo guard, CORS.
        assert "RequestLoggingMiddleware" in middleware_names
        assert "SecurityHeadersMiddleware" in middleware_names
        assert "OptionalAPIKeyMiddleware" in middleware_names
        assert "LicenseGateMiddleware" in middleware_names
        assert "DemoGuardMiddleware" in middleware_names
        assert "CORSMiddleware" in middleware_names

    def test_api_and_ws_routers_mounted(self, tmp_path: Path) -> None:
        from drevalis.main import create_app

        with patch("drevalis.main.Settings", return_value=_make_settings(storage_base=tmp_path)):
            app = create_app()
        # Look for at least one /api/v1 route and one /ws route.
        paths = [getattr(r, "path", "") for r in app.routes]
        assert any(p.startswith("/api/v1") for p in paths)
        assert any(p.startswith("/ws") for p in paths)

    def test_static_dirs_created_under_storage_base(self, tmp_path: Path) -> None:
        # The factory creates storage subdirectories on first build so
        # static mounts don't fail on fresh installs.
        from drevalis.main import create_app

        with patch("drevalis.main.Settings", return_value=_make_settings(storage_base=tmp_path)):
            create_app()
        assert (tmp_path / "episodes").is_dir()
        assert (tmp_path / "voice_previews").is_dir()
        assert (tmp_path / "audiobooks").is_dir()

    def test_static_mounts_present(self, tmp_path: Path) -> None:
        from drevalis.main import create_app

        with patch("drevalis.main.Settings", return_value=_make_settings(storage_base=tmp_path)):
            app = create_app()
        # Look for the three /storage/* mounts.
        mount_paths = {
            getattr(r, "path", "") for r in app.routes if r.__class__.__name__ == "Mount"
        }
        assert "/storage/episodes" in mount_paths
        assert "/storage/voice_previews" in mount_paths
        assert "/storage/audiobooks" in mount_paths

    def test_cors_allows_localhost_dev_origins(self, tmp_path: Path) -> None:
        # The dev CORS list MUST include ports 3000 (Vite default) and
        # 5173 (Vite alternate). Dropping these breaks local frontend
        # development against the live backend.
        from drevalis.main import create_app

        with patch("drevalis.main.Settings", return_value=_make_settings(storage_base=tmp_path)):
            app = create_app()
        # Find the CORS middleware in the stack.
        cors_mw = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
        origins = cors_mw.kwargs.get("allow_origins") or []
        assert any(":3000" in o for o in origins)
        assert any(":5173" in o for o in origins)
        assert any(":8000" in o for o in origins)

    def test_cors_allow_methods_includes_destructive_verbs(self, tmp_path: Path) -> None:
        # CORS must permit DELETE/PUT so destructive admin operations
        # work from the browser. PATCH is required for partial updates.
        from drevalis.main import create_app

        with patch("drevalis.main.Settings", return_value=_make_settings(storage_base=tmp_path)):
            app = create_app()
        cors_mw = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
        methods = cors_mw.kwargs.get("allow_methods") or []
        assert "DELETE" in methods
        assert "PUT" in methods
        assert "PATCH" in methods
        assert "OPTIONS" in methods  # preflight
