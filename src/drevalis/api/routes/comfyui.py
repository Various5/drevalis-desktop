"""ComfyUI API router -- CRUD for servers and workflows, connection testing.

Layering: routes call ``ComfyUIServerService`` / ``ComfyUIWorkflowService``
only. No repository imports, no ``encrypt_value`` / ``decrypt_value`` in
the route file. The connection-test endpoint still uses the runtime
``ComfyUIClient`` since that's a different concern from CRUD.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.models.comfyui import ComfyUIServer
from drevalis.schemas.comfyui_crud import (
    ComfyUIModelsResponse,
    ComfyUIServerCreate,
    ComfyUIServerResponse,
    ComfyUIServerTestResponse,
    ComfyUIServerUpdate,
    ComfyUIWorkflowCreate,
    ComfyUIWorkflowResponse,
    ComfyUIWorkflowUpdate,
)
from drevalis.services.comfyui_admin import (
    ComfyUIServerService,
    ComfyUIWorkflowService,
)

router = APIRouter(prefix="/api/v1/comfyui", tags=["comfyui"])


def _server_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ComfyUIServerService:
    return ComfyUIServerService(
        db,
        settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )


def _workflow_service(db: AsyncSession = Depends(get_db)) -> ComfyUIWorkflowService:
    return ComfyUIWorkflowService(db)


# ── Helpers ───────────────────────────────────────────────────────────────


def _server_to_response(server: ComfyUIServer) -> ComfyUIServerResponse:
    """Convert a ComfyUIServer ORM object to a response with has_api_key."""
    return ComfyUIServerResponse(
        id=server.id,
        name=server.name,
        url=server.url,
        has_api_key=server.api_key_encrypted is not None,
        max_concurrent=server.max_concurrent,
        is_active=server.is_active,
        last_tested_at=server.last_tested_at,
        last_test_status=server.last_test_status,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Servers
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/servers",
    response_model=list[ComfyUIServerResponse],
    status_code=status.HTTP_200_OK,
    summary="List all ComfyUI servers",
)
async def list_servers(
    svc: ComfyUIServerService = Depends(_server_service),
) -> list[ComfyUIServerResponse]:
    """Return all registered ComfyUI servers."""
    servers = await svc.list_all()
    return [_server_to_response(s) for s in servers]


@router.post(
    "/servers",
    response_model=ComfyUIServerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new ComfyUI server",
)
async def create_server(
    payload: ComfyUIServerCreate,
    svc: ComfyUIServerService = Depends(_server_service),
) -> ComfyUIServerResponse:
    """Register a new ComfyUI server instance."""
    try:
        server = await svc.create(
            name=payload.name,
            url=payload.url,
            api_key=payload.api_key,
            max_concurrent=payload.max_concurrent,
            is_active=payload.is_active,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail
        ) from exc
    return _server_to_response(server)


@router.get(
    "/servers/{server_id}",
    response_model=ComfyUIServerResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a ComfyUI server by ID",
)
async def get_server(
    server_id: UUID,
    svc: ComfyUIServerService = Depends(_server_service),
) -> ComfyUIServerResponse:
    """Fetch a single ComfyUI server by ID."""
    try:
        server = await svc.get(server_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _server_to_response(server)


@router.put(
    "/servers/{server_id}",
    response_model=ComfyUIServerResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a ComfyUI server",
)
async def update_server(
    server_id: UUID,
    payload: ComfyUIServerUpdate,
    svc: ComfyUIServerService = Depends(_server_service),
) -> ComfyUIServerResponse:
    """Update an existing ComfyUI server."""
    try:
        server = await svc.update(server_id, **payload.model_dump(exclude_unset=True))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _server_to_response(server)


@router.delete(
    "/servers/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a ComfyUI server",
)
async def delete_server(
    server_id: UUID,
    svc: ComfyUIServerService = Depends(_server_service),
) -> None:
    """Remove a ComfyUI server registration."""
    try:
        await svc.delete(server_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/servers/{server_id}/test",
    response_model=ComfyUIServerTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Test ComfyUI server connection",
)
async def test_server(
    server_id: UUID,
    svc: ComfyUIServerService = Depends(_server_service),
) -> ComfyUIServerTestResponse:
    """Test connectivity to a ComfyUI server and update its health status."""
    try:
        server = await svc.get(server_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    api_key = await svc.decrypt_api_key(server)

    try:
        from drevalis.services.comfyui import ComfyUIClient

        client = ComfyUIClient(base_url=server.url, api_key=api_key)
        try:
            reachable = await client.test_connection()
        finally:
            await client.close()

        test_status = "ok" if reachable else "unreachable"
        await svc.record_test_status(server_id, test_status)

        if reachable:
            return ComfyUIServerTestResponse(
                success=True,
                message=f"Server '{server.name}' is reachable",
                server_id=server_id,
            )
        return ComfyUIServerTestResponse(
            success=False,
            message=f"Server '{server.name}' is unreachable",
            server_id=server_id,
        )
    except Exception as exc:
        await svc.record_test_status(server_id, f"error: {exc}")
        return ComfyUIServerTestResponse(
            success=False,
            message=f"Connection test failed: {exc}",
            server_id=server_id,
        )


@router.get(
    "/servers/{server_id}/models",
    response_model=ComfyUIModelsResponse,
    status_code=status.HTTP_200_OK,
    summary="List model files installed on a ComfyUI server",
)
async def list_server_models(
    server_id: UUID,
    svc: ComfyUIServerService = Depends(_server_service),
) -> ComfyUIModelsResponse:
    """Return the checkpoints / LoRAs / VAEs / UNETs installed on the server
    so the UI can offer a real pick-list. Degrades to ``available=False`` with
    empty lists when the server is offline or unreachable — never raises a 5xx
    for a box that simply isn't running, so series setup is never blocked.
    """
    try:
        server = await svc.get(server_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    api_key = await svc.decrypt_api_key(server)

    from drevalis.services.comfyui import ComfyUIClient

    client = ComfyUIClient(base_url=server.url, api_key=api_key)
    try:
        models = await client.list_models()
        return ComfyUIModelsResponse(available=True, **models)
    except Exception as exc:
        # Offline / unreachable / unexpected payload — degrade gracefully so
        # the UI falls back to free-text model entry instead of erroring.
        return ComfyUIModelsResponse(available=False, message=str(exc))
    finally:
        await client.close()


# ═══════════════════════════════════════════════════════════════════════════
# Workflows
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/workflows",
    response_model=list[ComfyUIWorkflowResponse],
    status_code=status.HTTP_200_OK,
    summary="List all ComfyUI workflows",
)
async def list_workflows(
    svc: ComfyUIWorkflowService = Depends(_workflow_service),
) -> list[ComfyUIWorkflowResponse]:
    """Return all registered ComfyUI workflows."""
    workflows = await svc.list_all()
    return [ComfyUIWorkflowResponse.model_validate(w) for w in workflows]


@router.post(
    "/workflows",
    response_model=ComfyUIWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new ComfyUI workflow",
)
async def create_workflow(
    payload: ComfyUIWorkflowCreate,
    svc: ComfyUIWorkflowService = Depends(_workflow_service),
) -> ComfyUIWorkflowResponse:
    """Register a new ComfyUI workflow template."""
    try:
        workflow = await svc.create(**payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail
        ) from exc
    return ComfyUIWorkflowResponse.model_validate(workflow)


@router.get(
    "/workflows/{workflow_id}",
    response_model=ComfyUIWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a ComfyUI workflow by ID",
)
async def get_workflow(
    workflow_id: UUID,
    svc: ComfyUIWorkflowService = Depends(_workflow_service),
) -> ComfyUIWorkflowResponse:
    """Fetch a single ComfyUI workflow by ID."""
    try:
        workflow = await svc.get(workflow_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ComfyUIWorkflowResponse.model_validate(workflow)


@router.put(
    "/workflows/{workflow_id}",
    response_model=ComfyUIWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a ComfyUI workflow",
)
async def update_workflow(
    workflow_id: UUID,
    payload: ComfyUIWorkflowUpdate,
    svc: ComfyUIWorkflowService = Depends(_workflow_service),
) -> ComfyUIWorkflowResponse:
    """Update an existing ComfyUI workflow."""
    try:
        workflow = await svc.update(workflow_id, **payload.model_dump(exclude_unset=True))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ComfyUIWorkflowResponse.model_validate(workflow)


@router.delete(
    "/workflows/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a ComfyUI workflow",
)
async def delete_workflow(
    workflow_id: UUID,
    svc: ComfyUIWorkflowService = Depends(_workflow_service),
) -> None:
    """Remove a ComfyUI workflow registration."""
    try:
        await svc.delete(workflow_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Bundled workflow templates ──────────────────────────────────────


from pydantic import BaseModel as _TplBase  # noqa: E402


class WorkflowTemplateResponse(_TplBase):
    slug: str
    name: str
    description: str
    content_format: str
    scene_mode: str


class InstallTemplateResponse(_TplBase):
    workflow_id: str
    workflow_json_path: str


@router.get(
    "/templates",
    response_model=list[WorkflowTemplateResponse],
    summary="List bundled ComfyUI workflow templates",
)
async def list_templates() -> list[WorkflowTemplateResponse]:
    from drevalis.services.comfyui.templates import TEMPLATES

    return [
        WorkflowTemplateResponse(
            slug=t.slug,
            name=t.name,
            description=t.description,
            content_format=t.content_format,
            scene_mode=t.scene_mode,
        )
        for t in TEMPLATES.values()
    ]


@router.post(
    "/templates/{slug}/install",
    response_model=InstallTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Install a bundled workflow — copies the JSON + registers a ComfyUIWorkflow row",
)
async def install_template(
    slug: str,
    svc: ComfyUIWorkflowService = Depends(_workflow_service),
    settings: Settings = Depends(get_settings),
) -> InstallTemplateResponse:
    """Copy the bundled workflow JSON into
    ``storage/comfyui_workflows/drevalis/<slug>-<epoch>.json`` and create
    a ``ComfyUIWorkflow`` row with the template's input_mappings.
    """
    import os.path as _osp
    import re
    import shutil as _shutil
    import time

    from drevalis.services.comfyui.templates import TEMPLATES, template_json_path

    # Reject non-identifiers up-front. The TEMPLATES dict lookup below
    # also gates against unknown slugs, but doing the regex first
    # short-circuits before any filesystem call.
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", slug):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid template slug")

    tpl = TEMPLATES.get(slug)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"template {slug} not found")

    src_json = template_json_path(slug)
    if not src_json.exists():
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"template file missing on disk: {src_json.name}",
        )

    # CodeQL py/path-injection: textbook ``realpath`` + ``startswith``
    # sanitizer on strings before any pathlib touches user input.
    import os as _os

    safe_filename = _osp.basename(f"{slug}-{int(time.time())}.json")
    storage_base_real = _osp.realpath(str(settings.storage_base_path))
    target_dir_str = _osp.realpath(
        _osp.join(storage_base_real, "comfyui_workflows", "drevalis")
    )
    target_path_str = _osp.realpath(_osp.join(target_dir_str, safe_filename))
    if not (
        target_path_str == target_dir_str
        or target_path_str.startswith(target_dir_str + _os.sep)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid template slug")
    # Pure ``os`` API on the sanitized string — wrapping back into
    # ``Path()`` re-taints the value in CodeQL's flow model.
    _os.makedirs(target_dir_str, exist_ok=True)
    _shutil.copyfile(str(src_json), target_path_str)

    # ``rel_path`` is for storage in the DB row — derive from the
    # sanitized strings using ``os.path.relpath`` (also string API).
    rel_path = _osp.relpath(target_path_str, storage_base_real).replace(_os.sep, "/")

    wf = await svc.install_template(
        name=tpl.name,
        description=tpl.description,
        workflow_json_path=rel_path,
        input_mappings=tpl.input_mappings,
        content_format=tpl.content_format,
        scene_mode=tpl.scene_mode,
    )
    return InstallTemplateResponse(
        workflow_id=str(wf.id),
        workflow_json_path=rel_path,
    )
