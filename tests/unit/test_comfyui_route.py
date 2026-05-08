"""Tests for ``api/routes/comfyui.py``.

Server + workflow CRUD over ``ComfyUIServerService`` /
``ComfyUIWorkflowService`` plus the connection-test endpoint and the
bundled-template installer. Pin:

* `_server_to_response` derives `has_api_key` from the encrypted blob —
  the plain-text key never appears in the response.
* Server `test` records the test status (`ok` / `unreachable` /
  `error: ...`) regardless of outcome — operators rely on the
  status column to know which servers are flaky.
* `install_template` 404s on missing slug; 500s with a clear hint
  when the bundled JSON is missing on disk; success copies the file
  to a timestamped target and persists the row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from drevalis.api.routes.comfyui import (
    _server_service,
    _server_to_response,
    _workflow_service,
    create_server,
    create_workflow,
    delete_server,
    delete_workflow,
    get_server,
    get_workflow,
    install_template,
    list_servers,
    list_templates,
    list_workflows,
    update_server,
    update_workflow,
)
from drevalis.api.routes.comfyui import (
    test_server as _route_test_server,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.comfyui_crud import (
    ComfyUIServerCreate,
    ComfyUIServerUpdate,
    ComfyUIWorkflowCreate,
    ComfyUIWorkflowUpdate,
)
from drevalis.services.comfyui_admin import (
    ComfyUIServerService,
    ComfyUIWorkflowService,
)

# Avoid pytest collection of the imported `test_server` name.
comfyui_test_server = _route_test_server


def _make_server(**overrides: Any) -> Any:
    s = MagicMock()
    s.id = overrides.get("id", uuid4())
    s.name = overrides.get("name", "Local")
    s.url = overrides.get("url", "http://localhost:8188")
    s.api_key_encrypted = overrides.get("api_key_encrypted")
    s.max_concurrent = overrides.get("max_concurrent", 2)
    s.is_active = overrides.get("is_active", True)
    s.last_tested_at = overrides.get("last_tested_at")
    s.last_test_status = overrides.get("last_test_status")
    s.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    s.updated_at = overrides.get("updated_at", datetime(2026, 1, 1))
    return s


def _make_workflow(**overrides: Any) -> Any:
    w = MagicMock()
    w.id = overrides.get("id", uuid4())
    w.name = overrides.get("name", "Qwen Image")
    w.description = overrides.get("description")
    w.workflow_json_path = overrides.get("workflow_json_path", "workflows/drevalis/qwen-1.json")
    w.version = overrides.get("version", 1)
    w.input_mappings = overrides.get("input_mappings", {"prompt_node": "6"})
    w.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    w.updated_at = overrides.get("updated_at", datetime(2026, 1, 1))
    return w


def _settings(tmp_path: Any) -> Any:
    s = MagicMock()
    import base64

    s.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()
    s.storage_base_path = tmp_path
    return s


# ── _service factories ─────────────────────────────────────────────


class TestServiceFactories:
    def test_server_factory(self, tmp_path: Any) -> None:
        svc = _server_service(db=AsyncMock(), settings=_settings(tmp_path))
        assert isinstance(svc, ComfyUIServerService)

    def test_workflow_factory(self) -> None:
        svc = _workflow_service(db=AsyncMock())
        assert isinstance(svc, ComfyUIWorkflowService)


# ── _server_to_response ────────────────────────────────────────────


class TestServerToResponse:
    def test_no_api_key_yields_has_api_key_false(self) -> None:
        out = _server_to_response(_make_server(api_key_encrypted=None))
        assert out.has_api_key is False

    def test_encrypted_blob_yields_has_api_key_true(self) -> None:
        out = _server_to_response(_make_server(api_key_encrypted=b"opaque"))
        assert out.has_api_key is True


# ── Server CRUD ────────────────────────────────────────────────────


class TestServerCrud:
    async def test_list(self) -> None:
        svc = MagicMock()
        svc.list_all = AsyncMock(return_value=[_make_server(), _make_server()])
        out = await list_servers(svc=svc)
        assert len(out) == 2

    async def test_create_success(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(return_value=_make_server())
        body = ComfyUIServerCreate(name="L", url="http://localhost:8188")
        out = await create_server(body, svc=svc)
        assert out.name == "Local"

    async def test_create_validation_error_maps_to_422(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=ValidationError("URL unreachable"))
        body = ComfyUIServerCreate(name="x", url="http://localhost:1")
        with pytest.raises(HTTPException) as exc:
            await create_server(body, svc=svc)
        assert exc.value.status_code == 422

    async def test_get_success(self) -> None:
        svc = MagicMock()
        s = _make_server()
        svc.get = AsyncMock(return_value=s)
        out = await get_server(s.id, svc=svc)
        assert out.id == s.id

    async def test_get_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("comfyui_server", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_server(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_update_success(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(return_value=_make_server(name="renamed"))
        out = await update_server(uuid4(), ComfyUIServerUpdate(name="renamed"), svc=svc)
        assert out.name == "renamed"
        kwargs = svc.update.call_args.kwargs
        assert kwargs == {"name": "renamed"}

    async def test_update_validation_422(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ValidationError("bad"))
        with pytest.raises(HTTPException) as exc:
            await update_server(uuid4(), ComfyUIServerUpdate(max_concurrent=8), svc=svc)
        assert exc.value.status_code == 422

    async def test_update_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=NotFoundError("comfyui_server", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_server(uuid4(), ComfyUIServerUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 404

    async def test_delete_success(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_server(uuid4(), svc=svc)
        svc.delete.assert_awaited_once()

    async def test_delete_not_found_404(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("comfyui_server", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_server(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── POST /servers/{id}/test ────────────────────────────────────────


class TestServerTest:
    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("comfyui_server", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await comfyui_test_server(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_reachable_records_ok_status(self) -> None:
        svc = MagicMock()
        s = _make_server()
        svc.get = AsyncMock(return_value=s)
        svc.decrypt_api_key = AsyncMock(return_value=None)
        svc.record_test_status = AsyncMock()

        client = MagicMock()
        client.test_connection = AsyncMock(return_value=True)
        client.close = AsyncMock()
        with patch("drevalis.services.comfyui.ComfyUIClient", return_value=client):
            out = await comfyui_test_server(s.id, svc=svc)
        assert out.success is True
        svc.record_test_status.assert_awaited_once_with(s.id, "ok")
        client.close.assert_awaited_once()

    async def test_unreachable_records_status(self) -> None:
        svc = MagicMock()
        s = _make_server()
        svc.get = AsyncMock(return_value=s)
        svc.decrypt_api_key = AsyncMock(return_value=None)
        svc.record_test_status = AsyncMock()

        client = MagicMock()
        client.test_connection = AsyncMock(return_value=False)
        client.close = AsyncMock()
        with patch("drevalis.services.comfyui.ComfyUIClient", return_value=client):
            out = await comfyui_test_server(s.id, svc=svc)
        assert out.success is False
        svc.record_test_status.assert_awaited_once_with(s.id, "unreachable")

    async def test_exception_records_error_status_without_raising(self) -> None:
        # Pin: a connection crash MUST be swallowed so the route can
        # update last_test_status — otherwise the status column never
        # reflects that the server is down.
        svc = MagicMock()
        s = _make_server()
        svc.get = AsyncMock(return_value=s)
        svc.decrypt_api_key = AsyncMock(return_value=None)
        svc.record_test_status = AsyncMock()

        client = MagicMock()
        client.test_connection = AsyncMock(side_effect=ConnectionError("dns"))
        client.close = AsyncMock()
        with patch("drevalis.services.comfyui.ComfyUIClient", return_value=client):
            out = await comfyui_test_server(s.id, svc=svc)
        assert out.success is False
        # Status surface includes the error class for debugging.
        called_status = svc.record_test_status.call_args.args[1]
        assert called_status.startswith("error:")


# ── Workflow CRUD ──────────────────────────────────────────────────


class TestWorkflowCrud:
    async def test_list(self) -> None:
        svc = MagicMock()
        svc.list_all = AsyncMock(return_value=[_make_workflow()])
        out = await list_workflows(svc=svc)
        assert len(out) == 1

    async def test_create_success(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(return_value=_make_workflow())
        body = ComfyUIWorkflowCreate(
            name="W",
            workflow_json_path="workflows/x.json",
            input_mappings={"prompt_node": "6"},
        )
        out = await create_workflow(body, svc=svc)
        assert out.name == "Qwen Image"

    async def test_create_validation_error_maps_to_422(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=ValidationError("missing node"))
        body = ComfyUIWorkflowCreate(
            name="W",
            workflow_json_path="workflows/x.json",
            input_mappings={},
        )
        with pytest.raises(HTTPException) as exc:
            await create_workflow(body, svc=svc)
        assert exc.value.status_code == 422

    async def test_get_success(self) -> None:
        svc = MagicMock()
        w = _make_workflow()
        svc.get = AsyncMock(return_value=w)
        out = await get_workflow(w.id, svc=svc)
        assert out.id == w.id

    async def test_get_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("comfyui_workflow", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_workflow(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_update_success(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(return_value=_make_workflow(name="renamed"))
        out = await update_workflow(uuid4(), ComfyUIWorkflowUpdate(name="renamed"), svc=svc)
        assert out.name == "renamed"

    async def test_update_validation_422(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ValidationError("invalid mapping"))
        with pytest.raises(HTTPException) as exc:
            await update_workflow(uuid4(), ComfyUIWorkflowUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 422

    async def test_update_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=NotFoundError("comfyui_workflow", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_workflow(uuid4(), ComfyUIWorkflowUpdate(name="x"), svc=svc)
        assert exc.value.status_code == 404

    async def test_delete_success(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_workflow(uuid4(), svc=svc)
        svc.delete.assert_awaited_once()

    async def test_delete_not_found_404(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("comfyui_workflow", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_workflow(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── Bundled templates ──────────────────────────────────────────────


class TestTemplates:
    async def test_list_templates_returns_response(self) -> None:
        out = await list_templates()
        # Bundled set is non-empty by design.
        assert len(out) > 0
        assert all(t.slug for t in out)

    async def test_install_template_unknown_slug_404(self, tmp_path: Any) -> None:
        svc = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await install_template(slug="does-not-exist", svc=svc, settings=_settings(tmp_path))
        assert exc.value.status_code == 404

    async def test_install_template_missing_json_returns_500(self, tmp_path: Any) -> None:
        # Force the template-file lookup to a non-existent path so the
        # 500 ``template file missing on disk`` branch fires.
        svc = MagicMock()
        from drevalis.services.comfyui.templates import (
            TEMPLATES,
            template_json_path,
        )

        slug = next(iter(TEMPLATES.keys()))
        bogus = tmp_path / "no-such-file.json"
        with patch(
            "drevalis.services.comfyui.templates.template_json_path",
            return_value=bogus,
        ):
            with pytest.raises(HTTPException) as exc:
                await install_template(slug=slug, svc=svc, settings=_settings(tmp_path))
        # Use the imported function to confirm the test set up reality.
        assert template_json_path  # silence linter
        assert exc.value.status_code == 500
        assert "template file missing" in str(exc.value.detail)

    async def test_install_template_success_copies_and_persists(self, tmp_path: Any) -> None:
        svc = MagicMock()
        wf = _make_workflow()
        svc.install_template = AsyncMock(return_value=wf)

        from drevalis.services.comfyui.templates import TEMPLATES

        slug = next(iter(TEMPLATES.keys()))

        # Stage a fake bundled JSON file the route will copy.
        src = tmp_path / "bundled.json"
        src.write_text('{"prompt": {}}')

        with patch(
            "drevalis.services.comfyui.templates.template_json_path",
            return_value=src,
        ):
            out = await install_template(slug=slug, svc=svc, settings=_settings(tmp_path))

        # Returned path is relative to storage_base_path.
        assert out.workflow_json_path.startswith("comfyui_workflows/drevalis/")
        # Service was called with the relative path so the row points at it.
        kwargs = svc.install_template.call_args.kwargs
        assert kwargs["workflow_json_path"] == out.workflow_json_path
        # The copied file landed where we said it would.
        copied = tmp_path / out.workflow_json_path
        assert copied.exists()
