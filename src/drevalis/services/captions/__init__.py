"""Captions service package — backward-compatible re-exports."""

from drevalis.services.captions._monolith import (  # noqa: F401
    Caption,
    CaptionResult,
    CaptionService,
    CaptionStyle,
)

__all__ = [
    "Caption",
    "CaptionResult",
    "CaptionService",
    "CaptionStyle",
]
