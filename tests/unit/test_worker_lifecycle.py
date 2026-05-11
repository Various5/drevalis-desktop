"""Tests for ``workers/lifecycle.py``.

The full ``startup`` flow is integration territory (it sets up DB,
Redis, all services). The unit tests cover the parts that are
testable in isolation:

* ``on_job_start`` — license-gate hook with the EXEMPT_JOBS bypass
* ``shutdown`` — clean teardown that no-ops on missing services
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from drevalis.workers.lifecycle import on_job_start, shutdown

# ── on_job_start: license gate ──────────────────────────────────────


class TestOnJobStartLicenseGate:
    async def test_exempt_job_passes_when_unactivated(self) -> None:
        # Heartbeat must run without a license — otherwise an unactivated
        # install would look permanently crashed in the API liveness probe.
        from drevalis.core.license.state import (
            LicenseState,
            LicenseStatus,
            set_state,
        )

        set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
        # Should NOT raise Retry.
        await on_job_start({"job_name": "worker_heartbeat", "job_id": "x"})

    async def test_publish_scheduled_posts_also_exempt(self) -> None:
        # Cron-publishing self-checks the license at upload time, so the
        # cron itself must keep ticking. Verify it's in the exempt set.
        from drevalis.core.license.state import (
            LicenseState,
            LicenseStatus,
            set_state,
        )

        set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
        await on_job_start({"job_name": "publish_scheduled_posts", "job_id": "x"})

    async def test_active_license_passes_for_any_job(self) -> None:
        # A non-exempt job runs as long as the license is usable.
        from datetime import UTC, datetime

        from drevalis.core.license.claims import LicenseClaims
        from drevalis.core.license.state import (
            LicenseState,
            LicenseStatus,
            set_state,
        )

        now = int(datetime.now(tz=UTC).timestamp())
        claims = LicenseClaims(
            iss="x",
            sub="x",
            jti="x",
            tier="creator",
            iat=now - 100,
            nbf=now - 100,
            exp=now + 86400,
            period_end=now + 86400,
        )
        set_state(LicenseState(status=LicenseStatus.ACTIVE, claims=claims))
        await on_job_start({"job_name": "generate_episode", "job_id": "x"})

    async def test_unactivated_protected_job_returns_without_raising(self) -> None:
        # Non-exempt job with no license: the hook used to ``raise
        # arq.worker.Retry`` here, but arq's job-level try/except wraps
        # the job body — NOT ``on_job_start`` — so the Retry crashed
        # the worker (launcher then killed the API). Hook now just
        # logs; the individual job functions self-gate on license.
        from drevalis.core.license.state import (
            LicenseState,
            LicenseStatus,
            set_state,
        )

        set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
        # Should NOT raise.
        await on_job_start({"job_name": "generate_episode", "job_id": "x"})

    async def test_invalid_license_protected_job_returns_without_raising(self) -> None:
        from drevalis.core.license.state import (
            LicenseState,
            LicenseStatus,
            set_state,
        )

        set_state(LicenseState(status=LicenseStatus.INVALID, error="signature mismatch"))
        await on_job_start({"job_name": "generate_episode", "job_id": "x"})

    async def test_extracts_function_name_from_cron_job_id(self) -> None:
        # arq does NOT populate ``job_name`` in the ctx for on_job_start
        # (only job_id, job_try, enqueue_time, score). Cron job_ids
        # always look like ``cron:<funcname>:<timestamp>`` — the hook
        # parses the function name out so exempt cron jobs (like
        # ``worker_heartbeat``) are correctly recognised.
        from drevalis.core.license.state import (
            LicenseState,
            LicenseStatus,
            set_state,
        )
        from drevalis.workers.lifecycle import _job_name_from_ctx

        set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
        assert (
            _job_name_from_ctx({"job_id": "cron:worker_heartbeat:1778524020123"})
            == "worker_heartbeat"
        )
        assert (
            _job_name_from_ctx({"job_id": "cron:publish_scheduled_posts:1"})
            == "publish_scheduled_posts"
        )
        # Non-cron id → empty string fall-through; caller decides.
        assert _job_name_from_ctx({"job_id": "some-uuid"}) == ""
        # Explicit job_name in ctx wins over parsing.
        assert (
            _job_name_from_ctx({"job_name": "explicit", "job_id": "cron:other:1"})
            == "explicit"
        )


# ── shutdown ────────────────────────────────────────────────────────


class TestShutdown:
    async def test_closes_all_resources_when_present(self) -> None:
        comfyui_pool = AsyncMock()
        comfyui_pool.close_all = AsyncMock()
        redis_client = AsyncMock()
        redis_client.aclose = AsyncMock()
        redis_pool = AsyncMock()
        redis_pool.aclose = AsyncMock()
        engine = AsyncMock()
        engine.dispose = AsyncMock()

        ctx = {
            "comfyui_pool": comfyui_pool,
            "redis": redis_client,
            "redis_pool": redis_pool,
            "engine": engine,
        }
        await shutdown(ctx)

        comfyui_pool.close_all.assert_awaited_once()
        redis_client.aclose.assert_awaited_once()
        redis_pool.aclose.assert_awaited_once()
        engine.dispose.assert_awaited_once()

    async def test_no_op_when_resources_missing(self) -> None:
        # Worker was killed mid-startup before resources were assigned.
        # shutdown should still run cleanly without raising.
        await shutdown({})

    async def test_partial_resources_only_close_present_ones(self) -> None:
        # Only redis was assigned (startup blew up after assigning
        # redis but before ComfyUI). shutdown closes redis only.
        redis_client = AsyncMock()
        redis_client.aclose = AsyncMock()
        await shutdown({"redis": redis_client})
        redis_client.aclose.assert_awaited_once()
