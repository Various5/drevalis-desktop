"""Tests for ``api/routes/license.py``.

Status / activate / deactivate / activations / portal — every error
type from ``LicenseService`` has a different status code in the route
layer because the frontend's activation wizard uses the code + detail
shape to decide what UI to show next:

* ``LicenseConfigError`` → 400 ``license_server_not_configured`` (most
  endpoints) or 503 ``license_server_not_configured`` (portal — config
  is a server-side problem from the customer's POV).
* ``NoActiveLicenseError`` → 400 ``no_active_license`` (most) or 402
  ``license_required`` (portal — Payment Required is the real semantic).
* ``LicenseVerificationError`` → 400 ``invalid_license``.
* ``LicenseNotActiveError`` → 400 ``license_not_active`` with the JWT
  classification value so the wizard can route to grace / expired /
  invalid screens.
* ``ActivationError`` → propagate the upstream status code + detail.
* ``ActivationNetworkError`` → 503 ``license_server_unreachable``.
* ``LicensePortalUpstreamError`` → propagate upstream code + detail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from drevalis.api.routes.license import (
    ActivateRequest,
    ActivationsByKeyRequest,
    DeactivateByKeyRequest,
    _activation_error,
    _network_error,
    _service,
    activate_license,
    deactivate_license,
    deactivate_machine,
    deactivate_machine_by_key,
    get_license_status,
    list_activations,
    list_activations_by_key,
    open_billing_portal,
)
from drevalis.core.exceptions import ValidationError
from drevalis.services.license import (
    ActivationError,
    ActivationNetworkError,
    LicenseConfigError,
    LicenseNotActiveError,
    LicensePortalUpstreamError,
    LicenseService,
    LicenseVerificationError,
    NoActiveLicenseError,
)


def _status_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "state": "active",
        "tier": "creator",
        "features": ["youtube_upload"],
        "machines_cap": 1,
        "machine_id": "m1",
        "activated_at": datetime(2026, 1, 1),
        "last_heartbeat_at": None,
        "last_heartbeat_status": None,
        "period_end": None,
        "exp": None,
        "error": None,
        "license_type": "subscription",
        "update_window_expires_at": None,
    }
    base.update(overrides)
    return base


def _activations_payload() -> dict[str, Any]:
    return {
        "tier": "creator",
        "cap": 1,
        "this_machine_id": "m1",
        "activations": [
            {
                "machine_id": "m1",
                "first_seen": 0,
                "last_heartbeat": 100,
                "last_known_version": "0.29.66",
                "is_this_machine": True,
            }
        ],
    }


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service_with_session_settings_redis(self) -> None:
        session = AsyncMock()
        settings = MagicMock()
        redis = AsyncMock()
        svc = _service(session=session, settings=settings, redis=redis)
        assert isinstance(svc, LicenseService)


# ── Error helpers ──────────────────────────────────────────────────


class TestErrorHelpers:
    def test_activation_error_propagates_status_and_detail(self) -> None:
        exc = ActivationError(
            status_code=403, error="seat_cap_reached", detail={"cap": 1, "used": 2}
        )
        http_exc = _activation_error(exc)
        assert http_exc.status_code == 403
        assert http_exc.detail["error"] == "seat_cap_reached"
        assert http_exc.detail["cap"] == 1

    def test_network_error_maps_to_503(self) -> None:
        http_exc = _network_error(ActivationNetworkError("dns down"))
        assert http_exc.status_code == 503
        assert http_exc.detail["error"] == "license_server_unreachable"


# ── GET /status ─────────────────────────────────────────────────────


class TestGetLicenseStatus:
    async def test_returns_status_response(self) -> None:
        svc = MagicMock()
        svc.get_status = AsyncMock(return_value=_status_payload())
        out = await get_license_status(svc=svc)
        assert out.state == "active"
        assert out.machine_id == "m1"


# ── POST /activate ─────────────────────────────────────────────────


class TestActivateLicense:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.activate = AsyncMock(return_value=_status_payload())
        out = await activate_license(ActivateRequest(license_jwt="abc.def.ghi"), svc=svc)
        assert out.state == "active"

    async def test_validation_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.activate = AsyncMock(side_effect=ValidationError("server URL not configured"))
        with pytest.raises(HTTPException) as exc:
            await activate_license(ActivateRequest(license_jwt="key-uuid-1234"), svc=svc)
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "license_server_not_configured"

    async def test_network_error_maps_to_503(self) -> None:
        svc = MagicMock()
        svc.activate = AsyncMock(side_effect=ActivationNetworkError("dns down"))
        with pytest.raises(HTTPException) as exc:
            await activate_license(ActivateRequest(license_jwt="abc.def.ghi"), svc=svc)
        assert exc.value.status_code == 503

    async def test_activation_error_propagates_upstream_status(self) -> None:
        svc = MagicMock()
        svc.activate = AsyncMock(
            side_effect=ActivationError(
                status_code=403, error="seat_cap_reached", detail={"cap": 1}
            )
        )
        with pytest.raises(HTTPException) as exc:
            await activate_license(ActivateRequest(license_jwt="abc.def.ghi"), svc=svc)
        assert exc.value.status_code == 403
        assert exc.value.detail["error"] == "seat_cap_reached"

    async def test_verification_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.activate = AsyncMock(side_effect=LicenseVerificationError("bad signature"))
        with pytest.raises(HTTPException) as exc:
            await activate_license(ActivateRequest(license_jwt="abc.def.ghi"), svc=svc)
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "invalid_license"

    async def test_not_active_error_includes_classification(self) -> None:
        # Build a LicenseStatus-like enum stand-in carrying a `.value`.
        from drevalis.services.license import LicenseStatus  # noqa: PLC0415

        svc = MagicMock()
        svc.activate = AsyncMock(side_effect=LicenseNotActiveError(LicenseStatus.EXPIRED))
        with pytest.raises(HTTPException) as exc:
            await activate_license(ActivateRequest(license_jwt="abc.def.ghi"), svc=svc)
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "license_not_active"
        assert exc.value.detail["state"] == "expired"


# ── POST /deactivate ───────────────────────────────────────────────


class TestDeactivateLicense:
    async def test_returns_status(self) -> None:
        svc = MagicMock()
        svc.deactivate = AsyncMock(return_value=_status_payload(state="unactivated"))
        out = await deactivate_license(svc=svc)
        assert out.state == "unactivated"


# ── GET /activations ───────────────────────────────────────────────


class TestListActivations:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.list_activations = AsyncMock(return_value=_activations_payload())
        out = await list_activations(svc=svc)
        assert out.tier == "creator"
        assert out.activations[0].is_this_machine is True

    async def test_config_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.list_activations = AsyncMock(side_effect=LicenseConfigError())
        with pytest.raises(HTTPException) as exc:
            await list_activations(svc=svc)
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "license_server_not_configured"

    async def test_no_active_license_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.list_activations = AsyncMock(side_effect=NoActiveLicenseError())
        with pytest.raises(HTTPException) as exc:
            await list_activations(svc=svc)
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "no_active_license"

    async def test_network_error_maps_to_503(self) -> None:
        svc = MagicMock()
        svc.list_activations = AsyncMock(side_effect=ActivationNetworkError("dns"))
        with pytest.raises(HTTPException) as exc:
            await list_activations(svc=svc)
        assert exc.value.status_code == 503

    async def test_activation_error_propagates(self) -> None:
        svc = MagicMock()
        svc.list_activations = AsyncMock(
            side_effect=ActivationError(status_code=403, error="forbidden", detail={})
        )
        with pytest.raises(HTTPException) as exc:
            await list_activations(svc=svc)
        assert exc.value.status_code == 403


# ── POST /activations/query ────────────────────────────────────────


class TestListActivationsByKey:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.list_activations_by_key = AsyncMock(return_value=_activations_payload())
        out = await list_activations_by_key(
            ActivationsByKeyRequest(license_key="key-1234"), svc=svc
        )
        assert out.tier == "creator"

    async def test_config_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.list_activations_by_key = AsyncMock(side_effect=LicenseConfigError())
        with pytest.raises(HTTPException) as exc:
            await list_activations_by_key(ActivationsByKeyRequest(license_key="key-1234"), svc=svc)
        assert exc.value.status_code == 400

    async def test_network_error_maps_to_503(self) -> None:
        svc = MagicMock()
        svc.list_activations_by_key = AsyncMock(side_effect=ActivationNetworkError("dns"))
        with pytest.raises(HTTPException) as exc:
            await list_activations_by_key(ActivationsByKeyRequest(license_key="key-1234"), svc=svc)
        assert exc.value.status_code == 503

    async def test_activation_error_propagates(self) -> None:
        svc = MagicMock()
        svc.list_activations_by_key = AsyncMock(
            side_effect=ActivationError(status_code=404, error="no_such_key", detail={})
        )
        with pytest.raises(HTTPException) as exc:
            await list_activations_by_key(ActivationsByKeyRequest(license_key="key-1234"), svc=svc)
        assert exc.value.status_code == 404


# ── POST /activations/free-seat ────────────────────────────────────


class TestDeactivateMachineByKey:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.deactivate_machine_by_key = AsyncMock(return_value=_activations_payload())
        out = await deactivate_machine_by_key(
            DeactivateByKeyRequest(license_key="key-1234", machine_id="m1xx"), svc=svc
        )
        assert out.tier == "creator"

    async def test_config_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.deactivate_machine_by_key = AsyncMock(side_effect=LicenseConfigError())
        with pytest.raises(HTTPException) as exc:
            await deactivate_machine_by_key(
                DeactivateByKeyRequest(license_key="key-1234", machine_id="m1xx"),
                svc=svc,
            )
        assert exc.value.status_code == 400

    async def test_network_error_maps_to_503(self) -> None:
        svc = MagicMock()
        svc.deactivate_machine_by_key = AsyncMock(side_effect=ActivationNetworkError("dns"))
        with pytest.raises(HTTPException) as exc:
            await deactivate_machine_by_key(
                DeactivateByKeyRequest(license_key="key-1234", machine_id="m1xx"),
                svc=svc,
            )
        assert exc.value.status_code == 503

    async def test_activation_error_propagates(self) -> None:
        svc = MagicMock()
        svc.deactivate_machine_by_key = AsyncMock(
            side_effect=ActivationError(status_code=404, error="machine_not_registered", detail={})
        )
        with pytest.raises(HTTPException) as exc:
            await deactivate_machine_by_key(
                DeactivateByKeyRequest(license_key="key-1234", machine_id="m1xx"),
                svc=svc,
            )
        assert exc.value.status_code == 404


# ── POST /activations/{machine_id}/deactivate ──────────────────────


class TestDeactivateMachine:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.deactivate_machine = AsyncMock(return_value=_activations_payload())
        out = await deactivate_machine("m2", svc=svc)
        assert out.tier == "creator"

    async def test_config_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.deactivate_machine = AsyncMock(side_effect=LicenseConfigError())
        with pytest.raises(HTTPException) as exc:
            await deactivate_machine("m2", svc=svc)
        assert exc.value.status_code == 400

    async def test_no_active_license_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.deactivate_machine = AsyncMock(side_effect=NoActiveLicenseError())
        with pytest.raises(HTTPException) as exc:
            await deactivate_machine("m2", svc=svc)
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "no_active_license"

    async def test_network_error_maps_to_503(self) -> None:
        svc = MagicMock()
        svc.deactivate_machine = AsyncMock(side_effect=ActivationNetworkError("x"))
        with pytest.raises(HTTPException) as exc:
            await deactivate_machine("m2", svc=svc)
        assert exc.value.status_code == 503

    async def test_activation_error_propagates(self) -> None:
        svc = MagicMock()
        svc.deactivate_machine = AsyncMock(
            side_effect=ActivationError(status_code=403, error="forbidden", detail={})
        )
        with pytest.raises(HTTPException) as exc:
            await deactivate_machine("m2", svc=svc)
        assert exc.value.status_code == 403


# ── POST /portal ───────────────────────────────────────────────────


class TestPortal:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.billing_portal = AsyncMock(return_value="https://billing.test/abc")
        out = await open_billing_portal(svc=svc)
        assert out.url == "https://billing.test/abc"

    async def test_no_active_license_maps_to_402(self) -> None:
        # 402 Payment Required is the right code here — the install needs
        # a license to access billing. Pin it so a future "consistency"
        # pass doesn't homogenise license errors to 400.
        svc = MagicMock()
        svc.billing_portal = AsyncMock(side_effect=NoActiveLicenseError())
        with pytest.raises(HTTPException) as exc:
            await open_billing_portal(svc=svc)
        assert exc.value.status_code == 402
        assert exc.value.detail["error"] == "license_required"

    async def test_config_error_maps_to_503(self) -> None:
        svc = MagicMock()
        svc.billing_portal = AsyncMock(side_effect=LicenseConfigError("URL unset"))
        with pytest.raises(HTTPException) as exc:
            await open_billing_portal(svc=svc)
        assert exc.value.status_code == 503
        assert exc.value.detail["error"] == "license_server_not_configured"

    async def test_network_error_maps_to_503(self) -> None:
        svc = MagicMock()
        svc.billing_portal = AsyncMock(side_effect=ActivationNetworkError("dns"))
        with pytest.raises(HTTPException) as exc:
            await open_billing_portal(svc=svc)
        assert exc.value.status_code == 503

    async def test_portal_upstream_error_with_dict_detail(self) -> None:
        svc = MagicMock()
        svc.billing_portal = AsyncMock(
            side_effect=LicensePortalUpstreamError(status_code=502, detail={"error": "stripe_down"})
        )
        with pytest.raises(HTTPException) as exc:
            await open_billing_portal(svc=svc)
        assert exc.value.status_code == 502
        assert exc.value.detail == {"error": "stripe_down"}

    async def test_portal_upstream_error_with_string_detail(self) -> None:
        # Defensive: upstream sometimes returns a plain text body. The
        # router must still produce a dict-shaped detail for the frontend.
        svc = MagicMock()
        svc.billing_portal = AsyncMock(
            side_effect=LicensePortalUpstreamError(status_code=500, detail="raw error text")
        )
        with pytest.raises(HTTPException) as exc:
            await open_billing_portal(svc=svc)
        assert exc.value.status_code == 500
        assert exc.value.detail == {"raw": "raw error text"}
