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

    async def test_unactivated_protected_job_raises_retry(self) -> None:
        # Non-exempt job with no license → arq.Retry so the job is
        # deferred for an hour. Worker stays alive.
        from arq.worker import Retry

        from drevalis.core.license.state import (
            LicenseState,
            LicenseStatus,
            set_state,
        )

        set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
        with pytest.raises(Retry) as exc:
            await on_job_start({"job_name": "generate_episode", "job_id": "x"})
        # Defer is 1 hour (3600s). arq's Retry stores the defer-until
        # value on ``defer_score`` (epoch seconds when set) — just
        # confirm it's populated; exact value depends on test wall clock.
        assert exc.value.defer_score is not None

    async def test_invalid_license_protected_job_raises_retry(self) -> None:
        from arq.worker import Retry

        from drevalis.core.license.state import (
            LicenseState,
            LicenseStatus,
            set_state,
        )

        set_state(LicenseState(status=LicenseStatus.INVALID, error="signature mismatch"))
        with pytest.raises(Retry):
            await on_job_start({"job_name": "generate_episode", "job_id": "x"})

    async def test_missing_job_name_treated_as_protected(self) -> None:
        # Defensive: if arq context didn't populate ``job_name`` for
        # some reason, fall through to the license check rather than
        # silently skipping the gate.
        from arq.worker import Retry

        from drevalis.core.license.state import (
            LicenseState,
            LicenseStatus,
            set_state,
        )

        set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
        with pytest.raises(Retry):
            await on_job_start({"job_id": "x"})  # no job_name


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
