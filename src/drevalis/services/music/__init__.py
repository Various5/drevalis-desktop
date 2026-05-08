"""Music service package — backward-compatible re-exports."""

from drevalis.services.music._monolith import (  # noqa: F401
    _ACESTEP_MAX_DURATION,
    _ACESTEP_WORKFLOW_TEMPLATE,
    _MOOD_MUSIC_PARAMS,
    _MOOD_TAGS,
    MusicService,
)

__all__ = [
    "MusicService",
    "_ACESTEP_MAX_DURATION",
    "_ACESTEP_WORKFLOW_TEMPLATE",
    "_MOOD_MUSIC_PARAMS",
    "_MOOD_TAGS",
]
