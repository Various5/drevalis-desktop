"""Tests for ``api/routes/cloud_gpu.py``.

Unified provider surface (RunPod / Vast.ai / Lambda). Pin:

* `_provider_path` rejects unknown names with 400 + structured detail.
* `_handle_provider_exc`:
  - `CloudGPUConfigError` → **503** ``provider_not_configured`` (UI
    renders "connect this provider in Settings").
  - `CloudGPUProviderError` → propagates upstream `status_code` when
    in [400, 600), else **502 Bad Gateway**.
* `list_all_pods` aggregator: skips unconfigured providers and
  swallows per-provider failures (logs + continues) so one broken
  provider doesn't take the whole list down.
* `provider.close()` is awaited in every endpoint's `finally` block.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from drevalis.api.routes.cloud_gpu import (
    LaunchRequest,
    _handle_provider_exc,
    _provider_path,
    delete_pod,
    launch_pod,
    list_all_pods,
    list_gpu_types,
    list_pods,
    list_providers,
    start_pod,
    stop_pod,
)
from drevalis.services.cloud_gpu import (
    CloudGPUConfigError,
    CloudGPUProviderError,
)


def _settings() -> Any:
    return MagicMock()


def _provider(close: bool = True, **methods: Any) -> Any:
    p = MagicMock()
    for name, ret in methods.items():
        setattr(p, name, AsyncMock(return_value=ret))
    if close:
        p.close = AsyncMock()
    else:
        # Pin: route checks `hasattr(provider, "close")` — providers
        # that don't expose it must still work.
        if hasattr(p, "close"):
            del p.close
    return p


# ── _provider_path ──────────────────────────────────────────────────


class TestProviderPath:
    def test_known_providers_pass_through(self) -> None:
        for n in ("runpod", "vastai", "lambda"):
            assert _provider_path(n) == n

    def test_unknown_provider_400(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _provider_path("aws")
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "unknown_provider"
        assert exc.value.detail["provider"] == "aws"


# ── _handle_provider_exc ───────────────────────────────────────────


class TestHandleProviderExc:
    def test_config_error_maps_to_503(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _handle_provider_exc(CloudGPUConfigError(provider="runpod", hint="set RUNPOD_API_KEY"))
        assert exc.value.status_code == 503
        assert exc.value.detail["error"] == "provider_not_configured"
        assert exc.value.detail["provider"] == "runpod"

    def test_provider_error_passes_upstream_status(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _handle_provider_exc(
                CloudGPUProviderError(provider="vastai", status_code=429, detail="rate limited")
            )
        assert exc.value.status_code == 429
        assert exc.value.detail["provider"] == "vastai"

    def test_out_of_range_status_clamps_to_502(self) -> None:
        # Pin: a transport error wrapped with status_code=0 / 999 must
        # NOT be passed straight to FastAPI (FastAPI rejects values
        # outside [400, 600)). Route clamps to 502.
        with pytest.raises(HTTPException) as exc:
            _handle_provider_exc(
                CloudGPUProviderError(provider="runpod", status_code=0, detail="transport")
            )
        assert exc.value.status_code == 502

    def test_other_exception_returns_none(self) -> None:
        # Non-CloudGPU exceptions are not the helper's concern — it
        # returns None (callers re-raise). Pin to prevent accidental
        # swallowing of unrelated errors.
        out = _handle_provider_exc(ValueError("nope"))
        assert out is None


# ── /providers ─────────────────────────────────────────────────────


class TestListProviders:
    async def test_delegates_to_service(self) -> None:
        statuses = [
            {"name": "runpod", "configured": True},
            {"name": "vastai", "configured": False},
            {"name": "lambda", "configured": False},
        ]
        with patch(
            "drevalis.api.routes.cloud_gpu.list_providers_with_status",
            AsyncMock(return_value=statuses),
        ):
            out = await list_providers(db=AsyncMock(), settings=_settings())
        assert out == statuses


# ── Per-provider endpoints (gpu-types / list / launch / stop / start / delete) ──


class TestNonCloudGPUExceptionsBubbleUp:
    """Pin: anything that's NOT a CloudGPU* error must propagate
    unchanged. Otherwise a stray ValueError in a provider would get
    silently turned into a 500 with no useful detail."""

    async def test_get_provider_value_error_reraised(self) -> None:
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(side_effect=ValueError("bad config")),
        ):
            with pytest.raises(ValueError, match="bad config"):
                await list_gpu_types(name="runpod", db=AsyncMock(), settings=_settings())

    async def test_provider_call_value_error_reraised_and_close_awaited(
        self,
    ) -> None:
        prov = MagicMock()
        prov.list_pods = AsyncMock(side_effect=ValueError("boom"))
        prov.close = AsyncMock()
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(ValueError):
                await list_pods(name="runpod", db=AsyncMock(), settings=_settings())
        prov.close.assert_awaited_once()

    async def test_launch_pod_value_error_reraised(self) -> None:
        prov = MagicMock()
        prov.create_pod = AsyncMock(side_effect=ValueError("x"))
        prov.close = AsyncMock()
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(ValueError):
                await launch_pod(
                    body=LaunchRequest(name="d", gpu_type_id="A4000"),
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )
        prov.close.assert_awaited_once()

    async def test_stop_pod_value_error_reraised(self) -> None:
        prov = MagicMock()
        prov.stop_pod = AsyncMock(side_effect=ValueError("x"))
        prov.close = AsyncMock()
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(ValueError):
                await stop_pod(
                    pod_id="p1",
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )
        prov.close.assert_awaited_once()

    async def test_start_pod_get_provider_value_error_reraised(self) -> None:
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(side_effect=ValueError("get fails")),
        ):
            with pytest.raises(ValueError):
                await start_pod(
                    pod_id="p1",
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )

    async def test_delete_pod_value_error_reraised(self) -> None:
        prov = MagicMock()
        prov.delete_pod = AsyncMock(side_effect=ValueError("x"))
        prov.close = AsyncMock()
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(ValueError):
                await delete_pod(
                    pod_id="p1",
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )
        prov.close.assert_awaited_once()

    async def test_launch_pod_get_provider_value_error_reraised(self) -> None:
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(side_effect=ValueError("x")),
        ):
            with pytest.raises(ValueError):
                await launch_pod(
                    body=LaunchRequest(name="d", gpu_type_id="A4000"),
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )

    async def test_stop_pod_get_provider_value_error_reraised(self) -> None:
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(side_effect=ValueError("x")),
        ):
            with pytest.raises(ValueError):
                await stop_pod(
                    pod_id="p1",
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )

    async def test_list_gpu_types_call_value_error_reraised(self) -> None:
        prov = MagicMock()
        prov.list_gpu_types = AsyncMock(side_effect=ValueError("inner"))
        prov.close = AsyncMock()
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(ValueError):
                await list_gpu_types(name="runpod", db=AsyncMock(), settings=_settings())
        prov.close.assert_awaited_once()

    async def test_list_pods_get_provider_value_error_reraised(self) -> None:
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(side_effect=ValueError("x")),
        ):
            with pytest.raises(ValueError):
                await list_pods(name="runpod", db=AsyncMock(), settings=_settings())

    async def test_start_pod_call_value_error_reraised(self) -> None:
        prov = MagicMock()
        prov.start_pod = AsyncMock(side_effect=ValueError("x"))
        prov.close = AsyncMock()
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(ValueError):
                await start_pod(
                    pod_id="p1",
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )
        prov.close.assert_awaited_once()

    async def test_delete_pod_get_provider_value_error_reraised(self) -> None:
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(side_effect=ValueError("x")),
        ):
            with pytest.raises(ValueError):
                await delete_pod(
                    pod_id="p1",
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )


class TestPerProviderEndpoints:
    async def test_list_gpu_types_success_closes_provider(self) -> None:
        prov = _provider(list_gpu_types=[{"id": "A4000"}])
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            out = await list_gpu_types(name="runpod", db=AsyncMock(), settings=_settings())
        assert out == [{"id": "A4000"}]
        prov.close.assert_awaited_once()

    async def test_list_gpu_types_provider_not_configured(self) -> None:
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(side_effect=CloudGPUConfigError(provider="vastai", hint="missing key")),
        ):
            with pytest.raises(HTTPException) as exc:
                await list_gpu_types(name="vastai", db=AsyncMock(), settings=_settings())
        assert exc.value.status_code == 503

    async def test_list_gpu_types_provider_error_during_call_closes(self) -> None:
        # Provider returned fine but the .list_gpu_types() call raised.
        # close() MUST still be awaited.
        prov = MagicMock()
        prov.list_gpu_types = AsyncMock(
            side_effect=CloudGPUProviderError(provider="runpod", status_code=429, detail="rate")
        )
        prov.close = AsyncMock()
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(HTTPException) as exc:
                await list_gpu_types(name="runpod", db=AsyncMock(), settings=_settings())
        assert exc.value.status_code == 429
        prov.close.assert_awaited_once()

    async def test_list_gpu_types_provider_without_close_attribute(self) -> None:
        # Provider type doesn't expose `close` — pin: the
        # `hasattr(provider, "close")` guard must NOT crash.
        class _NoClose:
            async def list_gpu_types(self) -> list[dict[str, Any]]:
                return [{"id": "x"}]

        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=_NoClose()),
        ):
            out = await list_gpu_types(name="runpod", db=AsyncMock(), settings=_settings())
        assert out == [{"id": "x"}]

    async def test_list_pods_success(self) -> None:
        prov = _provider(list_pods=[{"id": "p1"}])
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            out = await list_pods(name="runpod", db=AsyncMock(), settings=_settings())
        assert out[0]["id"] == "p1"
        prov.close.assert_awaited_once()

    async def test_list_pods_get_provider_failure_closes_nothing(self) -> None:
        # get_provider raised — there's no provider to close. Pin: route
        # surfaces the error without trying to close a None.
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(
                side_effect=CloudGPUProviderError(provider="runpod", status_code=500, detail="boom")
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await list_pods(name="runpod", db=AsyncMock(), settings=_settings())
        assert exc.value.status_code == 500

    async def test_launch_pod_success(self) -> None:
        prov = _provider(create_pod={"id": "p1", "status": "PROVISIONING"})
        body = LaunchRequest(name="dre", gpu_type_id="A4000")
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            out = await launch_pod(
                body=body,
                name="runpod",
                db=AsyncMock(),
                settings=_settings(),
            )
        assert out["id"] == "p1"
        prov.create_pod.assert_awaited_once()

    async def test_launch_pod_provider_error_closes(self) -> None:
        prov = MagicMock()
        prov.create_pod = AsyncMock(
            side_effect=CloudGPUProviderError(provider="runpod", status_code=409, detail="dup")
        )
        prov.close = AsyncMock()
        body = LaunchRequest(name="dre", gpu_type_id="A4000")
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(HTTPException) as exc:
                await launch_pod(
                    body=body,
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )
        assert exc.value.status_code == 409
        prov.close.assert_awaited_once()

    async def test_stop_pod_success(self) -> None:
        prov = _provider(stop_pod={"id": "p1", "status": "EXITED"})
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            out = await stop_pod(pod_id="p1", name="runpod", db=AsyncMock(), settings=_settings())
        assert out["status"] == "EXITED"

    async def test_stop_pod_get_provider_error(self) -> None:
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(side_effect=CloudGPUConfigError(provider="lambda", hint="no key")),
        ):
            with pytest.raises(HTTPException) as exc:
                await stop_pod(
                    pod_id="p1",
                    name="lambda",
                    db=AsyncMock(),
                    settings=_settings(),
                )
        assert exc.value.status_code == 503

    async def test_start_pod_success(self) -> None:
        prov = _provider(start_pod={"id": "p1", "status": "RUNNING"})
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            out = await start_pod(pod_id="p1", name="runpod", db=AsyncMock(), settings=_settings())
        assert out["status"] == "RUNNING"

    async def test_start_pod_provider_call_error(self) -> None:
        prov = MagicMock()
        prov.start_pod = AsyncMock(
            side_effect=CloudGPUProviderError(provider="runpod", status_code=404, detail="no pod")
        )
        prov.close = AsyncMock()
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(HTTPException) as exc:
                await start_pod(
                    pod_id="p1",
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )
        assert exc.value.status_code == 404

    async def test_delete_pod_success(self) -> None:
        prov = _provider(delete_pod=None)
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            await delete_pod(
                pod_id="p1",
                name="runpod",
                db=AsyncMock(),
                settings=_settings(),
            )
        prov.delete_pod.assert_awaited_once_with("p1")

    async def test_delete_pod_get_provider_error(self) -> None:
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(
                side_effect=CloudGPUProviderError(provider="runpod", status_code=500, detail="x")
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await delete_pod(
                    pod_id="p1",
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )
        assert exc.value.status_code == 500

    async def test_delete_pod_provider_call_error_closes(self) -> None:
        prov = MagicMock()
        prov.delete_pod = AsyncMock(
            side_effect=CloudGPUProviderError(provider="runpod", status_code=404, detail="x")
        )
        prov.close = AsyncMock()
        with patch(
            "drevalis.api.routes.cloud_gpu.get_provider",
            AsyncMock(return_value=prov),
        ):
            with pytest.raises(HTTPException) as exc:
                await delete_pod(
                    pod_id="p1",
                    name="runpod",
                    db=AsyncMock(),
                    settings=_settings(),
                )
        assert exc.value.status_code == 404
        prov.close.assert_awaited_once()


# ── /pods (aggregate fan-out) ──────────────────────────────────────


class TestListAllPods:
    async def test_skips_unconfigured_and_aggregates(self) -> None:
        statuses = [
            {"name": "runpod", "configured": True},
            {"name": "vastai", "configured": False},
            {"name": "lambda", "configured": True},
        ]
        runpod = _provider(list_pods=[{"id": "rp1"}])
        lambda_p = _provider(list_pods=[{"id": "lp1"}])

        async def _factory(name: str, *_a: Any, **_k: Any) -> Any:
            return {"runpod": runpod, "lambda": lambda_p}[name]

        with (
            patch(
                "drevalis.api.routes.cloud_gpu.list_providers_with_status",
                AsyncMock(return_value=statuses),
            ),
            patch(
                "drevalis.api.routes.cloud_gpu.get_provider",
                AsyncMock(side_effect=_factory),
            ),
        ):
            out = await list_all_pods(db=AsyncMock(), settings=_settings())

        assert {p["id"] for p in out} == {"rp1", "lp1"}
        runpod.close.assert_awaited_once()
        lambda_p.close.assert_awaited_once()

    async def test_unconfigured_only_returns_empty_list(self) -> None:
        # No configured providers at all — must return [] without
        # invoking get_provider.
        with (
            patch(
                "drevalis.api.routes.cloud_gpu.list_providers_with_status",
                AsyncMock(
                    return_value=[
                        {"name": "runpod", "configured": False},
                        {"name": "vastai", "configured": False},
                    ]
                ),
            ),
            patch(
                "drevalis.api.routes.cloud_gpu.get_provider",
                AsyncMock(side_effect=AssertionError("must not be called")),
            ),
        ):
            out = await list_all_pods(db=AsyncMock(), settings=_settings())
        assert out == []

    async def test_per_provider_failure_does_not_break_aggregate(self) -> None:
        # One provider blew up — the other still contributes pods.
        statuses = [
            {"name": "runpod", "configured": True},
            {"name": "lambda", "configured": True},
        ]
        runpod = MagicMock()
        runpod.list_pods = AsyncMock(
            side_effect=CloudGPUProviderError(provider="runpod", status_code=429, detail="rate")
        )
        runpod.close = AsyncMock()
        lambda_p = _provider(list_pods=[{"id": "lp1"}])

        async def _factory(name: str, *_a: Any, **_k: Any) -> Any:
            return {"runpod": runpod, "lambda": lambda_p}[name]

        with (
            patch(
                "drevalis.api.routes.cloud_gpu.list_providers_with_status",
                AsyncMock(return_value=statuses),
            ),
            patch(
                "drevalis.api.routes.cloud_gpu.get_provider",
                AsyncMock(side_effect=_factory),
            ),
        ):
            out = await list_all_pods(db=AsyncMock(), settings=_settings())

        # The good provider's pods are returned; runpod's failure was
        # logged-and-swallowed.
        assert out == [{"id": "lp1"}]
