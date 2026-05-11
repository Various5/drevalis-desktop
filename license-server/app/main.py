"""License server entry point.

Run locally::

    cd license-server
    export LICENSE_PRIVATE_KEY_PEM="$(cat /path/to/dev_private.pem)"
    uvicorn app.main:app --reload --port 9000

Deploy: see fly.toml + README.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import os

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.routes import activate, admin, checkout, portal, updates, webhook


# Comma-separated list of origins that may POST /checkout and /portal
# from the browser. Defaults to the Drevalis marketing domain. Override
# via CORS_ORIGINS env var if you host the marketing site somewhere else.
_DEFAULT_CORS = (
    "https://drevalis.com,"
    "https://www.drevalis.com"
)
_CORS_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", _DEFAULT_CORS).split(",") if o.strip()
]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    await db.init_db()
    logger.info("license_server_startup_complete")
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Drevalis License Server",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Permit the marketing site to POST /checkout and /portal from the
    # browser. Webhook, activate, heartbeat, deactivate, admin: all called
    # server-to-server, no CORS needed.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=False,
        max_age=3600,
    )

    @application.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    application.include_router(checkout.router)
    application.include_router(portal.router)
    application.include_router(webhook.router)
    application.include_router(activate.router)
    application.include_router(admin.router)
    application.include_router(updates.router)
    return application


app = create_app()
