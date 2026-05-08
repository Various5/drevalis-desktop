"""Effective parallel-generation slot calculation.

The per-tier marketing claim ("up to 2 / 6 / 8 parallel generations") is
enforced here: ``effective_max_concurrent_generations`` returns the
minimum of the operator's global cap and the active license tier's cap.

When no license is active (headless / dev) the global cap wins. Routes
should use this helper instead of reading ``settings.max_concurrent_generations``
directly when they enqueue generation work.
"""

from __future__ import annotations

from drevalis.core.license.features import current_parallel_cap


def effective_max_concurrent_generations(global_max: int) -> int:
    return min(global_max, current_parallel_cap(global_max))
