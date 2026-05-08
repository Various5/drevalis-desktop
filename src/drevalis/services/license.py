"""LicenseService — wraps license state, verifier, and activation flows.

Layering: keeps the route file free of ``LicenseStateRepository`` and
the directly-instantiated httpx client used by the billing portal call
(audit F-A-01).

The service depends on ``drevalis.core.license.*`` modules — those are
already FastAPI-free and act as the provider boundary. The service adds
a single orchestration layer that ties the repo + state + remote-server
calls together so the route only deals with HTTP shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from drevalis.core.exceptions import ValidationError
from drevalis.core.license.activation import (
    ActivationError,
    ActivationNetworkError,
    deactivate_machine_with_server,
    deactivate_with_server,
    exchange_key_for_jwt,
    list_activations_with_server,
    looks_like_jwt,
)
from drevalis.core.license.claims import LicenseClaims
from drevalis.core.license.machine import stable_machine_id
from drevalis.core.license.state import LicenseStatus, get_state, set_state
from drevalis.core.license.verifier import (
    LicenseState,
    LicenseVerificationError,
    bump_state_version,
    refresh_if_stale,
    verify_jwt,
)
from drevalis.repositories.license_state import LicenseStateRepository

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.core.config import Settings
    from drevalis.models.license_state import LicenseStateRow

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class LicenseConfigError(Exception):
    """Raised when an operation requires the license server URL but it is not set."""


class NoActiveLicenseError(Exception):
    """Raised when an operation needs the locally-stored JWT's jti and there is none."""


class LicenseNotActiveError(Exception):
    """Raised when a JWT verifies but is currently expired / not-yet-valid."""

    def __init__(self, classification: LicenseStatus) -> None:
        self.classification = classification
        super().__init__(f"License is not active: {classification.value}")


class LicensePortalUpstreamError(Exception):
    """Raised when the upstream portal endpoint returned a non-2xx response."""

    def __init__(self, status_code: int, detail: dict[str, Any] | str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Portal upstream returned {status_code}")


class LicenseService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        redis: Redis,
    ) -> None:
        self._session = session
        self._settings = settings
        self._redis = redis
        self._repo = LicenseStateRepository(session)

    # ── Status ─────────────────────────────────────────────────────────

    async def get_status(self) -> dict[str, Any]:
        """Return the dict the route serialises into LicenseStatusResponse."""
        from drevalis.core.database import get_session_factory as _gsf

        try:
            await refresh_if_stale(
                _gsf(),
                self._redis,
                public_key_override_pem=self._settings.license_public_key_override,
            )
        except Exception:
            pass

        state = get_state()
        row: LicenseStateRow | None = await self._repo.get()
        claims = state.claims
        update_window = None
        if claims and claims.update_window_expires_at:
            update_window = datetime.fromtimestamp(claims.update_window_expires_at, tz=UTC)
        return {
            "state": state.status.value,
            "tier": claims.tier if claims else None,
            "features": list(claims.features) if claims and claims.features else [],
            "machines_cap": claims.machines if claims else None,
            "machine_id": stable_machine_id(),
            "activated_at": row.activated_at if row else None,
            "last_heartbeat_at": row.last_heartbeat_at if row else None,
            "last_heartbeat_status": row.last_heartbeat_status if row else None,
            "period_end": claims.period_end_datetime() if claims else None,
            "exp": claims.exp_datetime() if claims else None,
            "error": state.error,
            "license_type": claims.license_type if claims else None,
            "update_window_expires_at": update_window,
        }

    # ── Activate ──────────────────────────────────────────────────────

    async def activate(self, payload: str) -> dict[str, Any]:
        """Activate a license. ``payload`` is either a JWT or a license key UUID."""
        machine_id = stable_machine_id()
        jwt_payload = payload.strip()

        if not looks_like_jwt(jwt_payload):
            if not self._settings.license_server_url:
                raise ValidationError(
                    "This install is configured for offline-only activation. "
                    "Paste the raw JWT from your license email instead of the short key."
                )
            jwt_payload = await exchange_key_for_jwt(
                self._settings.license_server_url,
                license_key=payload.strip(),
                machine_id=machine_id,
            )

        try:
            claims = verify_jwt(
                jwt_payload,
                public_key_override_pem=self._settings.license_public_key_override,
            )
        except LicenseVerificationError:
            raise

        classification = _classify_now(claims)
        if classification in (LicenseStatus.EXPIRED, LicenseStatus.INVALID):
            raise LicenseNotActiveError(classification)

        await self._repo.upsert(jwt=jwt_payload, machine_id=machine_id)
        await self._session.commit()

        set_state(LicenseState(status=classification, claims=claims))
        await bump_state_version(self._redis)
        return await self.get_status()

    # ── Deactivate ────────────────────────────────────────────────────

    async def deactivate(self) -> dict[str, Any]:
        current = get_state()
        if self._settings.license_server_url and current.claims is not None and current.claims.jti:
            await deactivate_with_server(
                self._settings.license_server_url,
                license_key=current.claims.jti,
                machine_id=stable_machine_id(),
            )

        await self._repo.clear()
        await self._session.commit()
        set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
        await bump_state_version(self._redis)
        return await self.get_status()

    # ── Activations management ────────────────────────────────────────

    def _require_server(self) -> str:
        if not self._settings.license_server_url:
            raise LicenseConfigError("license_server_not_configured")
        return self._settings.license_server_url

    def _require_local_jti(self) -> str:
        state = get_state()
        if state.claims is None or not state.claims.jti:
            raise NoActiveLicenseError("no_active_license")
        return state.claims.jti

    async def list_activations(self) -> dict[str, Any]:
        url = self._require_server()
        jti = self._require_local_jti()
        raw = await list_activations_with_server(url, license_key=jti)
        return self._format_activations(raw)

    async def list_activations_by_key(self, license_key: str) -> dict[str, Any]:
        url = self._require_server()
        raw = await list_activations_with_server(url, license_key=license_key)
        return self._format_activations(raw)

    async def deactivate_machine_by_key(self, license_key: str, machine_id: str) -> dict[str, Any]:
        url = self._require_server()
        await deactivate_machine_with_server(
            url,
            license_key=license_key,
            machine_id=machine_id,
        )
        return await self.list_activations_by_key(license_key)

    async def deactivate_machine(self, machine_id: str) -> dict[str, Any]:
        url = self._require_server()
        jti = self._require_local_jti()
        await deactivate_machine_with_server(url, license_key=jti, machine_id=machine_id)

        # If the caller just released this very install's seat, also zero
        # local JWT so the next request flips the UI to the wizard.
        if machine_id == stable_machine_id():
            await self._repo.clear()
            await self._session.commit()
            set_state(LicenseState(status=LicenseStatus.UNACTIVATED))
            await bump_state_version(self._redis)

        return await self.list_activations()

    def _format_activations(self, raw: dict[str, Any]) -> dict[str, Any]:
        this_id = stable_machine_id()
        entries: list[dict[str, Any]] = []
        for a in raw.get("activations", []) or []:
            if not isinstance(a, dict):
                continue
            mid = str(a.get("machine_id") or "")
            entries.append(
                {
                    "machine_id": mid,
                    "first_seen": a.get("first_seen"),
                    "last_heartbeat": a.get("last_heartbeat"),
                    "last_known_version": a.get("last_known_version"),
                    "is_this_machine": mid == this_id,
                }
            )
        return {
            "tier": str(raw.get("tier", "")),
            "cap": int(raw.get("cap", 1)),
            "this_machine_id": this_id,
            "activations": entries,
        }

    # ── Billing portal ────────────────────────────────────────────────

    async def billing_portal(self) -> str:
        state = get_state()
        if not state.is_usable or state.claims is None:
            raise NoActiveLicenseError("license_required")
        if not self._settings.license_server_url:
            raise LicenseConfigError(
                "Billing portal requires the online license server. "
                "Manage your subscription at drevalis.com/account instead."
            )

        url = self._settings.license_server_url.rstrip("/") + "/portal"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json={"license_key": state.claims.jti})
        except httpx.HTTPError as exc:
            raise ActivationNetworkError(str(exc)[:200]) from exc

        if resp.status_code >= 400:
            detail: dict[str, Any] | str = {}
            try:
                parsed = resp.json().get("detail", {})
                detail = parsed if isinstance(parsed, dict) else {"raw": str(parsed)}
            except Exception:
                detail = {}
            raise LicensePortalUpstreamError(resp.status_code, detail)

        body = resp.json()
        return str(body.get("url") or "")


def _classify_now(claims: LicenseClaims) -> LicenseStatus:
    now = int(datetime.now(tz=UTC).timestamp())
    if now < claims.nbf:
        return LicenseStatus.INVALID
    if now >= claims.exp:
        return LicenseStatus.EXPIRED
    if now >= claims.period_end:
        return LicenseStatus.GRACE
    return LicenseStatus.ACTIVE


__all__ = [
    "ActivationError",
    "ActivationNetworkError",
    "LicenseConfigError",
    "LicenseNotActiveError",
    "LicensePortalUpstreamError",
    "LicenseService",
    "LicenseVerificationError",
    "NoActiveLicenseError",
]
