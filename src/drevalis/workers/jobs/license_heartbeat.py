"""Daily license heartbeat.

Runs as an arq cron every 24h. Reads the stored JWT, extracts the license
key from the ``jti`` claim, and POSTs ``/heartbeat`` to the license server.
On success, replaces the stored JWT with the freshly-minted one and bumps
the cross-process state version so all uvicorn workers re-read. On explicit
revocation (402 ``license_revoked``), zeros the JWT — the next request
flips the app into EXPIRED and the frontend returns to the activation
wizard.

Network failures are logged but tolerated: the cached JWT's own ``exp``
carries the app through the 7-day offline grace window.
"""

from __future__ import annotations

from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def license_heartbeat(ctx: dict[str, Any]) -> dict[str, Any]:
    from drevalis.core.config import Settings
    from drevalis.core.license.activation import (
        ActivationError,
        ActivationNetworkError,
        heartbeat_with_server,
    )
    from drevalis.core.license.machine import stable_machine_id
    from drevalis.core.license.verifier import (
        LicenseVerificationError,
        bootstrap_license_state,
        bump_state_version,
        verify_jwt,
    )
    from drevalis.repositories.license_state import LicenseStateRepository

    settings = Settings()
    session_factory = ctx["session_factory"]
    redis = ctx.get("redis")

    log = logger.bind(job="license_heartbeat")

    # Nothing to do without a configured server — Phase 1 installs are
    # activated from a directly-pasted JWT and don't need heartbeats.
    if not settings.license_server_url:
        log.debug("heartbeat_skipped_no_server_url")
        return {"skipped": "no_server_url"}

    async with session_factory() as session:
        repo = LicenseStateRepository(session)
        row = await repo.get()
        if row is None or not row.jwt:
            log.debug("heartbeat_skipped_no_license")
            return {"skipped": "no_license"}

        try:
            plaintext_jwt = await repo.get_plaintext_jwt()
        except ValueError as exc:
            log.error("heartbeat_stored_jwt_decrypt_failed", error=str(exc)[:200])
            return {"skipped": "jwt_decrypt_failed"}
        if not plaintext_jwt:
            return {"skipped": "no_license"}

        try:
            claims = verify_jwt(
                plaintext_jwt,
                public_key_override_pem=settings.license_public_key_override,
            )
        except LicenseVerificationError as exc:
            log.warning("heartbeat_stored_jwt_invalid", error=str(exc)[:120])
            return {"skipped": "jwt_invalid"}

        machine_id = row.machine_id or stable_machine_id()

        try:
            fresh_jwt = await heartbeat_with_server(
                settings.license_server_url,
                license_key=claims.jti,
                machine_id=machine_id,
                version="0.1.0",
            )
        except ActivationNetworkError as exc:
            log.info("heartbeat_network_failure", error=str(exc)[:120])
            await repo.record_heartbeat("network_error")
            await session.commit()
            return {"status": "network_error"}
        except ActivationError as exc:
            # ONLY 4xx should be treated as revocation. A transient 5xx
            # from the license server (brief outage, cold-start) must not
            # brick every client that happens to heartbeat during the
            # window — that would zero the JWT, flip state to EXPIRED,
            # and require every customer to re-activate by hand.
            if 500 <= exc.status_code < 600:
                log.warning(
                    "heartbeat_server_5xx_treat_as_network",
                    status_code=exc.status_code,
                    error=exc.error,
                )
                await repo.record_heartbeat(f"server_error:{exc.status_code}")
                await session.commit()
                return {"status": "server_error", "code": exc.status_code}

            # 4xx: explicit revocation / not-found / bad request. Zero
            # the JWT so the app locks on the next request, matching the
            # behavior of an explicit deactivate.
            log.warning(
                "heartbeat_rejected",
                status_code=exc.status_code,
                error=exc.error,
            )
            await repo.clear()
            await repo.record_heartbeat(f"revoked:{exc.error}")
            await session.commit()
            if redis is not None:
                await bump_state_version(redis)
            # Re-bootstrap local state in this process immediately.
            await bootstrap_license_state(
                session_factory,
                public_key_override_pem=settings.license_public_key_override,
            )
            return {"status": "revoked", "error": exc.error}

        # Success — replace the stored JWT with the renewed one.
        await repo.upsert(jwt=fresh_jwt, machine_id=machine_id)
        await repo.record_heartbeat("ok")
        await session.commit()

    if redis is not None:
        await bump_state_version(redis)
    await bootstrap_license_state(
        session_factory,
        public_key_override_pem=settings.license_public_key_override,
    )
    log.info("heartbeat_ok", tier=claims.tier)
    return {"status": "ok", "tier": claims.tier}
