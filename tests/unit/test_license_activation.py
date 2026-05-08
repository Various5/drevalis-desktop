"""Tests for the license-server activation client (core/license/activation.py).

Each function does a single httpx round-trip with bespoke
success/error parsing. Tests use ``httpx.MockTransport`` so the real
network is never touched and every status / payload shape is
deterministic.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from drevalis.core.license.activation import (
    ActivationError,
    ActivationNetworkError,
    deactivate_machine_with_server,
    deactivate_with_server,
    exchange_key_for_jwt,
    heartbeat_with_server,
    list_activations_with_server,
    looks_like_jwt,
)

# ── Helpers ──────────────────────────────────────────────────────────


# Capture the real AsyncClient up-front so patches that wrap it can
# always reach back to the unpatched constructor.
_RealAsyncClient = httpx.AsyncClient


def _mock_transport_factory(handler: Any) -> Any:
    """Patch ``httpx.AsyncClient`` so it uses a MockTransport with handler.

    The patched constructor injects a ``MockTransport`` and delegates to
    the *real* ``AsyncClient`` so we don't recurse through the patch.
    """

    def _patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)

    return patch(
        "drevalis.core.license.activation.httpx.AsyncClient",
        side_effect=_patched,
    )


def _mock_transport_raises(exc: Exception) -> Any:
    """Patch ``httpx.AsyncClient`` so the request raises *exc*."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        raise exc

    return _mock_transport_factory(_handler)


def _success_handler(payload: dict[str, Any]) -> Any:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return _h


def _error_handler(status: int, payload: dict[str, Any] | str | None = None) -> Any:
    def _h(request: httpx.Request) -> httpx.Response:
        if payload is None:
            return httpx.Response(status)
        if isinstance(payload, str):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    return _h


# ── looks_like_jwt ───────────────────────────────────────────────────


class TestLooksLikeJwt:
    def test_uuid_key_is_not_jwt(self) -> None:
        assert looks_like_jwt("550e8400-e29b-41d4-a716-446655440000") is False

    def test_jwt_returns_true(self) -> None:
        # 3-segment dotted base64 with > 40 chars total
        token = "abcdef.ghijklmnop.qrstuvwxyz0123456789-AAAAAAA"
        assert looks_like_jwt(token) is True

    def test_short_dotted_string_rejected(self) -> None:
        assert looks_like_jwt("a.b.c") is False

    def test_only_one_dot_rejected(self) -> None:
        assert looks_like_jwt("foo.bar" * 20) is False

    def test_empty_string(self) -> None:
        assert looks_like_jwt("") is False


# ── exchange_key_for_jwt ─────────────────────────────────────────────


class TestExchangeKeyForJwt:
    async def test_success_returns_token(self) -> None:
        with _mock_transport_factory(_success_handler({"license_jwt": "tok123"})):
            tok = await exchange_key_for_jwt("https://lic.test", license_key="abc", machine_id="m1")
        assert tok == "tok123"

    async def test_includes_version_when_provided(self) -> None:
        captured: dict[str, Any] = {}

        def _h(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"license_jwt": "tok"})

        with _mock_transport_factory(_h):
            await exchange_key_for_jwt(
                "https://lic.test",
                license_key="abc",
                machine_id="m1",
                version="1.2.3",
            )
        assert captured == {"license_key": "abc", "machine_id": "m1", "version": "1.2.3"}

    async def test_omits_version_when_none(self) -> None:
        captured: dict[str, Any] = {}

        def _h(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"license_jwt": "tok"})

        with _mock_transport_factory(_h):
            await exchange_key_for_jwt("https://lic.test", license_key="abc", machine_id="m1")
        assert "version" not in captured

    async def test_strips_trailing_slash_from_url(self) -> None:
        captured_url: list[str] = []

        def _h(request: httpx.Request) -> httpx.Response:
            captured_url.append(str(request.url))
            return httpx.Response(200, json={"license_jwt": "tok"})

        with _mock_transport_factory(_h):
            await exchange_key_for_jwt("https://lic.test/", license_key="abc", machine_id="m1")
        # No double-slash in the path; ``/activate`` appended cleanly.
        assert captured_url[0].endswith("/activate")
        assert "//activate" not in captured_url[0]

    async def test_4xx_with_detail_payload_raises_activation_error(self) -> None:
        with _mock_transport_factory(
            _error_handler(403, {"detail": {"error": "license_revoked", "reason": "fraud"}})
        ):
            with pytest.raises(ActivationError) as exc:
                await exchange_key_for_jwt("https://lic.test", license_key="abc", machine_id="m1")
        assert exc.value.status_code == 403
        assert exc.value.error == "license_revoked"
        assert exc.value.detail == {"error": "license_revoked", "reason": "fraud"}

    async def test_4xx_without_detail_uses_reason_phrase(self) -> None:
        with _mock_transport_factory(_error_handler(404)):
            with pytest.raises(ActivationError) as exc:
                await exchange_key_for_jwt("https://lic.test", license_key="abc", machine_id="m1")
        assert exc.value.status_code == 404
        # Reason phrase or fallback string — never empty.
        assert exc.value.error

    async def test_4xx_with_non_dict_detail_normalised(self) -> None:
        # Server returns ``{"detail": "string error"}`` instead of a nested object.
        with _mock_transport_factory(_error_handler(400, {"detail": "string-form"})):
            with pytest.raises(ActivationError) as exc:
                await exchange_key_for_jwt("https://lic.test", license_key="abc", machine_id="m1")
        assert exc.value.status_code == 400
        # The non-dict detail isn't lost — it ends up in detail['raw'].
        # (Note: the implementation calls ``.get('detail', {})`` which yields
        #  the string and then the isinstance check routes to {'raw': ...}.)
        # Either way: we don't crash and we surface a status code.

    async def test_malformed_success_response_raises(self) -> None:
        # 200 OK but no ``license_jwt`` field → the server is misconfigured.
        with _mock_transport_factory(_success_handler({"unrelated": "x"})):
            with pytest.raises(ActivationError) as exc:
                await exchange_key_for_jwt("https://lic.test", license_key="abc", machine_id="m1")
        assert exc.value.error == "malformed_response"

    async def test_connect_error_raises_network_error(self) -> None:
        with _mock_transport_raises(httpx.ConnectError("connection refused")):
            with pytest.raises(ActivationNetworkError):
                await exchange_key_for_jwt("https://lic.test", license_key="abc", machine_id="m1")

    async def test_read_timeout_raises_network_error(self) -> None:
        with _mock_transport_raises(httpx.ReadTimeout("slow")):
            with pytest.raises(ActivationNetworkError):
                await exchange_key_for_jwt("https://lic.test", license_key="abc", machine_id="m1")


# ── heartbeat_with_server ────────────────────────────────────────────


class TestHeartbeat:
    async def test_success_returns_token(self) -> None:
        with _mock_transport_factory(_success_handler({"license_jwt": "newtok"})):
            tok = await heartbeat_with_server("https://lic.test", license_key="k", machine_id="m")
        assert tok == "newtok"

    async def test_4xx_raises_activation_error(self) -> None:
        with _mock_transport_factory(_error_handler(401, {"detail": {"error": "expired"}})):
            with pytest.raises(ActivationError) as exc:
                await heartbeat_with_server("https://lic.test", license_key="k", machine_id="m")
        assert exc.value.status_code == 401
        assert exc.value.error == "expired"

    async def test_missing_token_in_success_raises(self) -> None:
        with _mock_transport_factory(_success_handler({})):
            with pytest.raises(ActivationError) as exc:
                await heartbeat_with_server("https://lic.test", license_key="k", machine_id="m")
        assert exc.value.error == "malformed_response"

    async def test_network_error_raises_activation_network_error(self) -> None:
        with _mock_transport_raises(httpx.ConnectTimeout("dns down")):
            with pytest.raises(ActivationNetworkError):
                await heartbeat_with_server("https://lic.test", license_key="k", machine_id="m")

    async def test_4xx_default_error_name(self) -> None:
        with _mock_transport_factory(_error_handler(500, {"detail": "raw"})):
            with pytest.raises(ActivationError) as exc:
                await heartbeat_with_server("https://lic.test", license_key="k", machine_id="m")
        # Default fallback when no ``error`` key found.
        assert exc.value.error == "heartbeat_failed"

    async def test_includes_version_when_provided(self) -> None:
        # Server distinguishes installs running different app versions via
        # the optional ``version`` field. Pin that the parameter actually
        # makes it onto the wire.
        captured: dict[str, Any] = {}

        def _h(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"license_jwt": "tok"})

        with _mock_transport_factory(_h):
            await heartbeat_with_server(
                "https://lic.test",
                license_key="k",
                machine_id="m",
                version="0.29.61",
            )
        assert captured["version"] == "0.29.61"

    async def test_4xx_with_non_json_body_falls_back(self) -> None:
        # Server returned 500 with HTML or empty body. The ``resp.json()``
        # call inside the error path raises — must be swallowed so callers
        # still get a structured ActivationError instead of a JSON decode
        # crash bubbling up.
        with _mock_transport_factory(_error_handler(502, "<html>bad gateway</html>")):
            with pytest.raises(ActivationError) as exc:
                await heartbeat_with_server("https://lic.test", license_key="k", machine_id="m")
        assert exc.value.status_code == 502
        assert exc.value.error == "heartbeat_failed"


# ── deactivate_with_server (best-effort, swallows errors) ────────────


class TestDeactivateBestEffort:
    async def test_success_returns_none(self) -> None:
        with _mock_transport_factory(_success_handler({"ok": True})):
            result = await deactivate_with_server(
                "https://lic.test", license_key="k", machine_id="m"
            )
        assert result is None

    async def test_4xx_does_not_raise(self) -> None:
        # Best-effort: the local JWT is zeroed regardless, so server-side
        # errors don't propagate.
        with _mock_transport_factory(_error_handler(500)):
            await deactivate_with_server("https://lic.test", license_key="k", machine_id="m")

    async def test_network_error_does_not_raise(self) -> None:
        with _mock_transport_raises(httpx.ConnectError("dns")):
            await deactivate_with_server("https://lic.test", license_key="k", machine_id="m")


# ── list_activations_with_server ─────────────────────────────────────


class TestListActivations:
    async def test_success_returns_body(self) -> None:
        body = {
            "tier": "creator",
            "cap": 1,
            "activations": [{"machine_id": "m1", "first_seen": 0, "last_heartbeat": 100}],
        }
        with _mock_transport_factory(_success_handler(body)):
            result = await list_activations_with_server("https://lic.test", license_key="k")
        assert result == body

    async def test_4xx_raises(self) -> None:
        with _mock_transport_factory(_error_handler(403, {"detail": {"error": "no_such_key"}})):
            with pytest.raises(ActivationError) as exc:
                await list_activations_with_server("https://lic.test", license_key="k")
        assert exc.value.error == "no_such_key"

    async def test_network_error_raises_network_error(self) -> None:
        with _mock_transport_raises(httpx.NetworkError("connection lost")):
            with pytest.raises(ActivationNetworkError):
                await list_activations_with_server("https://lic.test", license_key="k")

    async def test_timeout_raises_network_error(self) -> None:
        with _mock_transport_raises(httpx.ReadTimeout("slow")):
            with pytest.raises(ActivationNetworkError):
                await list_activations_with_server("https://lic.test", license_key="k")

    async def test_4xx_default_error_name(self) -> None:
        with _mock_transport_factory(_error_handler(500, "")):
            with pytest.raises(ActivationError) as exc:
                await list_activations_with_server("https://lic.test", license_key="k")
        # Empty / non-JSON detail → reason phrase used.
        assert exc.value.error


# ── deactivate_machine_with_server (errors surfaced) ─────────────────


class TestDeactivateMachine:
    async def test_success_returns_none(self) -> None:
        with _mock_transport_factory(_success_handler({"ok": True})):
            await deactivate_machine_with_server(
                "https://lic.test", license_key="k", machine_id="m1"
            )

    async def test_4xx_raises_activation_error(self) -> None:
        # Differs from the best-effort variant: surfaces 4xx so the UI
        # can show "this install is no longer registered" etc.
        with _mock_transport_factory(
            _error_handler(404, {"detail": {"error": "machine_not_registered"}})
        ):
            with pytest.raises(ActivationError) as exc:
                await deactivate_machine_with_server(
                    "https://lic.test", license_key="k", machine_id="m1"
                )
        assert exc.value.status_code == 404
        assert exc.value.error == "machine_not_registered"

    async def test_network_error_raises_network_error(self) -> None:
        with _mock_transport_raises(httpx.NetworkError("offline")):
            with pytest.raises(ActivationNetworkError):
                await deactivate_machine_with_server(
                    "https://lic.test", license_key="k", machine_id="m1"
                )

    async def test_4xx_with_non_json_body_falls_back(self) -> None:
        # Same pattern as heartbeat: non-JSON 4xx response must surface as
        # a structured ActivationError, never a JSON decode crash.
        with _mock_transport_factory(_error_handler(503, "service unavailable")):
            with pytest.raises(ActivationError) as exc:
                await deactivate_machine_with_server(
                    "https://lic.test", license_key="k", machine_id="m1"
                )
        assert exc.value.status_code == 503
        assert exc.value.error  # falls back to reason phrase or default


# ── ActivationError dataclass-ish ────────────────────────────────────


class TestActivationError:
    def test_message_includes_status_and_error(self) -> None:
        err = ActivationError(status_code=403, error="revoked", detail={"x": 1})
        assert "403" in str(err)
        assert "revoked" in str(err)

    def test_default_detail_is_empty_dict(self) -> None:
        err = ActivationError(status_code=500, error="x")
        assert err.detail == {}

    def test_attributes_preserved(self) -> None:
        err = ActivationError(status_code=429, error="rate_limited", detail={"retry_after": 30})
        assert err.status_code == 429
        assert err.error == "rate_limited"
        assert err.detail == {"retry_after": 30}
