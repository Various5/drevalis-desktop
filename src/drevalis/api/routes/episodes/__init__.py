"""Episodes API router package.

Public surface: the single ``router`` import. The actual route
definitions live in topical sub-modules:

  * ``_monolith.py``  — lifecycle, pipeline control, script + scene
                        editing, regenerate-* operations, inpaint
  * ``music.py``      — /music/*, /set-music
  * ``exports.py``    — /export/*, /thumbnail, /edit/*
  * ``seo.py``        — /seo-score, /seo, /seo-preflight, /seo-variants,
                        /publish-all, /continuity, /quality-report

Each sub-module declares its own ``APIRouter`` with the same
``/api/v1/episodes`` prefix; we aggregate them here so the public
import shape stays the same as the pre-split monolith. The split
is *purely organisational* — no route paths or response shapes
changed in alpha.28.
"""

from fastapi import APIRouter

from drevalis.api.routes.episodes._monolith import router as _lifecycle_router
from drevalis.api.routes.episodes.exports import router as _exports_router
from drevalis.api.routes.episodes.music import router as _music_router
from drevalis.api.routes.episodes.seo import router as _seo_router

# Aggregator owns no routes itself; everything is bolted on from the
# sub-modules. We bind FastAPI's ``include_router`` (not a manual
# ``routes.extend(...)``) so each sub-module's per-route metadata
# (response_model, tags, summary) is preserved verbatim in OpenAPI.
router = APIRouter()
router.include_router(_lifecycle_router)
router.include_router(_music_router)
router.include_router(_exports_router)
router.include_router(_seo_router)


__all__ = ["router"]
