"""YouTube API router package — backward-compatible re-export."""

from drevalis.api.routes.youtube._monolith import (  # noqa: F401
    build_youtube_service,
    router,
)

__all__ = ["build_youtube_service", "router"]
