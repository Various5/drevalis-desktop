"""LLM configuration API router -- CRUD and connection testing.

Layering: this router calls ``LLMConfigService`` only. The runtime
``LLMService`` (from ``services/llm``) is still imported lazily inside
the test endpoint — that's a separate concern (it owns the provider
orchestration, not the config-row CRUD).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.models.llm_config import LLMConfig
from drevalis.schemas.llm_config import (
    LLMConfigCreate,
    LLMConfigResponse,
    LLMConfigUpdate,
    LLMTestRequest,
    LLMTestResponse,
)
from drevalis.services.llm_config import LLMConfigService

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


def _service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LLMConfigService:
    return LLMConfigService(
        db,
        settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )


# ── Helpers ───────────────────────────────────────────────────────────────


def _config_to_response(config: LLMConfig) -> LLMConfigResponse:
    """Convert an LLMConfig ORM object to a response with has_api_key."""
    return LLMConfigResponse(
        id=config.id,
        name=config.name,
        base_url=config.base_url,
        model_name=config.model_name,
        has_api_key=config.api_key_encrypted is not None,
        max_tokens=config.max_tokens,
        temperature=float(config.temperature),
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


# ── List LLM configs ─────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[LLMConfigResponse],
    status_code=status.HTTP_200_OK,
    summary="List all LLM configurations",
)
async def list_llm_configs(
    svc: LLMConfigService = Depends(_service),
) -> list[LLMConfigResponse]:
    """Return all registered LLM configurations."""
    configs = await svc.list_all()
    return [_config_to_response(c) for c in configs]


# ── Create LLM config ────────────────────────────────────────────────────


@router.post(
    "",
    response_model=LLMConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new LLM configuration",
)
async def create_llm_config(
    payload: LLMConfigCreate,
    svc: LLMConfigService = Depends(_service),
) -> LLMConfigResponse:
    """Create a new LLM configuration. Encrypts api_key when present."""
    config = await svc.create(
        name=payload.name,
        base_url=payload.base_url,
        model_name=payload.model_name,
        api_key=payload.api_key,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
    )
    return _config_to_response(config)


# ── Get LLM config ───────────────────────────────────────────────────────


@router.get(
    "/{config_id}",
    response_model=LLMConfigResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an LLM configuration by ID",
)
async def get_llm_config(
    config_id: UUID,
    svc: LLMConfigService = Depends(_service),
) -> LLMConfigResponse:
    """Fetch a single LLM configuration by ID."""
    try:
        config = await svc.get(config_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _config_to_response(config)


# ── Update LLM config ────────────────────────────────────────────────────


@router.put(
    "/{config_id}",
    response_model=LLMConfigResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an LLM configuration",
)
async def update_llm_config(
    config_id: UUID,
    payload: LLMConfigUpdate,
    svc: LLMConfigService = Depends(_service),
) -> LLMConfigResponse:
    """Update an existing LLM configuration."""
    try:
        config = await svc.update(config_id, **payload.model_dump(exclude_unset=True))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _config_to_response(config)


# ── Delete LLM config ────────────────────────────────────────────────────


@router.delete(
    "/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an LLM configuration",
)
async def delete_llm_config(
    config_id: UUID,
    svc: LLMConfigService = Depends(_service),
) -> None:
    """Delete an LLM configuration by ID."""
    try:
        await svc.delete(config_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Test LLM config ──────────────────────────────────────────────────────


@router.post(
    "/{config_id}/test",
    response_model=LLMTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Test LLM configuration with sample prompt",
)
async def test_llm_config(
    config_id: UUID,
    payload: LLMTestRequest | None = None,
    svc: LLMConfigService = Depends(_service),
    settings: Settings = Depends(get_settings),
) -> LLMTestResponse:
    """Send a test prompt to the configured LLM endpoint and return the result."""
    try:
        config = await svc.get(config_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    prompt_text = "Say hello in one sentence."
    if payload is not None:
        prompt_text = payload.prompt

    try:
        from drevalis.services.llm import LLMService

        # Pass the encryption key to LLMService so it can decrypt API keys
        # internally without mutating the ORM object (M5 fix).
        runtime = LLMService(
            encryption_key=settings.encryption_key,
            encryption_keys=settings.get_encryption_keys(),
        )

        # Expunge the config from the session so that no accidental
        # autoflush can persist decrypted values to the database.
        await svc.expunge(config)

        provider = runtime.get_provider(config)
        result = await provider.generate(
            system_prompt="You are a helpful assistant.",
            user_prompt=prompt_text,
            temperature=float(config.temperature),
            max_tokens=min(config.max_tokens, 256),
        )

        return LLMTestResponse(
            success=True,
            message="LLM test completed successfully",
            response_text=result.content[:500],
            model=result.model,
            tokens_used=result.total_tokens,
        )
    except Exception:
        return LLMTestResponse(
            success=False,
            message="LLM test failed. Check server logs for details.",
        )
