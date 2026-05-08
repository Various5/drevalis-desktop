"""Shared Redis cache key constants.

Centralised so producers (the route that writes the cache) and
consumers / invalidators (the worker that busts it after a destructive
operation) reference the same string. Drift between the two is silent —
a stale cache key just means the invalidation no-ops while the route
keeps reading the old data.
"""

from __future__ import annotations

# Storage-probe diagnostic report. Written by ``GET /api/v1/backup/
# storage-probe`` and busted by ``restore_backup_async`` so a fresh
# post-restore state is reflected in the Backup tab immediately rather
# than after the 5-min TTL elapses.
STORAGE_PROBE_CACHE_KEY = "storage_probe:report"
