"""Jobs API router package — backward-compatible re-export."""

from drevalis.api.routes.jobs._monolith import router  # noqa: F401

__all__ = ["router"]
