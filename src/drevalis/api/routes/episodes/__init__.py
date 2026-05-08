"""Episodes API router package — backward-compatible re-export."""

from drevalis.api.routes.episodes._monolith import router  # noqa: F401

__all__ = ["router"]
