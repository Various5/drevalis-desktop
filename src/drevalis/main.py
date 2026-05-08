"""FastAPI application factory for Drevalis."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from drevalis.api.router import router as api_router
from drevalis.api.websocket import router as ws_router
from drevalis.core.auth import OptionalAPIKeyMiddleware
from drevalis.core.config import Settings
from drevalis.core.database import close_db, init_db
from drevalis.core.logging import setup_logging
from drevalis.core.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware
from drevalis.core.redis import close_redis, init_redis

log = structlog.stdlib.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown logic."""
    settings = Settings()

    # ── Startup ───────────────────────────────────────────────────────────
    setup_logging(debug=settings.debug, log_file=settings.log_file)
    log.info("starting_up", app=settings.app_name, debug=settings.debug)

    # Validate encryption key at startup (M1)
    from drevalis.core.security import _validate_fernet_key

    try:
        _validate_fernet_key(settings.encryption_key)
    except ValueError as exc:
        log.error("invalid_encryption_key", error="Encryption key is not a valid Fernet key")
        raise SystemExit(
            "FATAL: ENCRYPTION_KEY is not a valid Fernet key. "
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from exc

    await init_db(settings)
    log.info("database_initialised")

    await init_redis(settings)
    log.info("redis_initialised")

    # Ensure the storage directory exists
    settings.storage_base_path.mkdir(parents=True, exist_ok=True)

    # Load license state from DB; never fails startup — the frontend can
    # prompt for activation if no valid license is present.
    try:
        from drevalis.core.database import get_session_factory
        from drevalis.core.license.verifier import bootstrap_license_state

        await bootstrap_license_state(
            get_session_factory(),
            public_key_override_pem=settings.license_public_key_override,
        )
    except Exception:
        log.warning("license_bootstrap_failed", exc_info=True)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    log.info("shutting_down")
    await close_redis()
    await close_db()
    log.info("shutdown_complete")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    application = FastAPI(
        title="Drevalis Creator Studio",
        version="0.1.0",
        description="AI-powered YouTube Shorts creation studio",
        lifespan=lifespan,
    )

    # ── Request logging middleware (observability) ──────────────────────
    application.add_middleware(RequestLoggingMiddleware)

    # ── Security headers (defense-in-depth for /storage/*) ──────────────
    application.add_middleware(SecurityHeadersMiddleware)

    # ── Auth middleware (H4: optional API key authentication) ────────────
    application.add_middleware(OptionalAPIKeyMiddleware)

    # ── License gate (returns 402 on protected routes when unlicensed) ──
    from drevalis.core.license.gate import LicenseGateMiddleware

    application.add_middleware(LicenseGateMiddleware)

    # ── Demo guard (returns 403 on external-API routes in demo mode) ────
    from drevalis.core.demo_guard import DemoGuardMiddleware

    application.add_middleware(DemoGuardMiddleware)

    # ── CORS (permissive for local development) ──────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Accept"],
    )

    # ── Routers ──────────────────────────────────────────────────────────
    application.include_router(api_router)
    application.include_router(ws_router)

    # ── Static files ─────────────────────────────────────────────────────
    # Only serve the episodes output subdirectory (not the entire storage
    # tree which contains models, temp files, etc.).  Uses the configured
    # storage_base_path for consistency.
    from fastapi.staticfiles import StaticFiles

    settings = Settings()
    episodes_path = settings.storage_base_path / "episodes"
    episodes_path.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/storage/episodes",
        StaticFiles(directory=str(episodes_path), follow_symlink=False),
        name="episode_storage",
    )

    # Voice preview audio files
    voice_previews_path = settings.storage_base_path / "voice_previews"
    voice_previews_path.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/storage/voice_previews",
        StaticFiles(directory=str(voice_previews_path), follow_symlink=False),
        name="voice_previews",
    )

    # Audiobook output files (audio + optional video)
    audiobooks_path = settings.storage_base_path / "audiobooks"
    audiobooks_path.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/storage/audiobooks",
        StaticFiles(directory=str(audiobooks_path), follow_symlink=False),
        name="audiobook_storage",
    )

    return application


# Module-level app instance used by ``uvicorn src.drevalis.main:app``
app = create_app()
