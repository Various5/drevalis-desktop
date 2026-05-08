"""Cloud GPU provider registry — resolves a provider instance from an API key
in the :class:`ApiKeyStore` or the ``Settings`` env vars.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from drevalis.services.cloud_gpu.base import (
    CloudGPUConfigError,
    CloudGPUProvider,
)
from drevalis.services.cloud_gpu.lambda_labs import LambdaLabsProvider
from drevalis.services.cloud_gpu.runpod import RunPodProvider
from drevalis.services.cloud_gpu.vastai import VastAIProvider

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.core.config import Settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# Ordered so the UI lists providers in a sensible default order.
SUPPORTED_PROVIDERS: tuple[dict[str, str | None], ...] = (
    {
        "name": "runpod",
        "display_name": "RunPod",
        "api_key_name": "runpod_api_key",
        # Legacy alias — the integrations dropdown used to store the
        # key under the bare slug "runpod"; keep accepting it so
        # existing installs don't lose their pod access.
        "api_key_alias": "runpod",
        "settings_attr": "runpod_api_key",
        "docs_url": "https://docs.runpod.io/",
    },
    {
        "name": "vastai",
        "display_name": "Vast.ai",
        "api_key_name": "vastai_api_key",
        "settings_attr": None,  # no env-var fallback yet
        "docs_url": "https://vast.ai/docs/",
    },
    {
        "name": "lambda",
        "display_name": "Lambda Labs",
        "api_key_name": "lambda_api_key",
        "settings_attr": None,
        "docs_url": "https://docs.lambda.ai/",
    },
)


async def _resolve_api_key(
    db: AsyncSession,
    settings: Settings,
    spec: dict[str, str | None],
) -> str | None:
    """Fetch a provider's API key from the encrypted key-store first,
    then fall back to the Settings env-var (if one exists).

    The registry's canonical key name is the ``api_key_name`` field
    (e.g. ``runpod_api_key``). For backward compatibility with the
    integrations dropdown — which historically stored RunPod under the
    bare ``runpod`` slug — we also check the alias when defined. This
    means users who added their key before v0.20.40 still resolve,
    and new users can use either form.
    """
    from drevalis.repositories.api_key_store import ApiKeyStoreRepository

    repo = ApiKeyStoreRepository(db)
    lookup_names: list[str] = []
    primary = spec.get("api_key_name")
    if primary:
        lookup_names.append(primary)
    alias = spec.get("api_key_alias")
    if alias:
        lookup_names.append(alias)

    for name in lookup_names:
        row = await repo.get_by_key_name(name)
        if row and row.encrypted_value:
            try:
                return settings.decrypt(row.encrypted_value)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "cloud_gpu.decrypt_failed",
                    provider=spec["name"],
                    key_name=name,
                    error=str(exc)[:200],
                )

    attr = spec.get("settings_attr")
    if attr:
        fallback = getattr(settings, attr, None)
        if fallback:
            return str(fallback)

    return None


async def list_providers_with_status(
    db: AsyncSession,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Return every supported provider + whether it's configured."""
    out: list[dict[str, Any]] = []
    for spec in SUPPORTED_PROVIDERS:
        key = await _resolve_api_key(db, settings, spec)
        out.append(
            {
                "name": spec["name"],
                "display_name": spec["display_name"],
                "configured": bool(key),
                "api_key_name": spec["api_key_name"],
                "docs_url": spec["docs_url"],
            }
        )
    return out


async def get_provider(
    provider_name: str,
    db: AsyncSession,
    settings: Settings,
) -> CloudGPUProvider:
    """Construct an initialised provider. Raises :class:`CloudGPUConfigError`
    when the provider's API key isn't configured yet."""
    spec = next((s for s in SUPPORTED_PROVIDERS if s["name"] == provider_name), None)
    if not spec:
        raise CloudGPUConfigError(
            provider=provider_name,
            hint=f"Unknown cloud GPU provider {provider_name!r}. Supported: "
            + ", ".join(str(s["name"]) for s in SUPPORTED_PROVIDERS),
        )

    key = await _resolve_api_key(db, settings, spec)
    if not key:
        raise CloudGPUConfigError(
            provider=provider_name,
            hint=f"{spec['display_name']} is not connected. Add the API key "
            f"named {spec['api_key_name']!r} under Settings → API Keys.",
        )

    if provider_name == "runpod":
        return RunPodProvider(api_key=key)
    if provider_name == "vastai":
        return VastAIProvider(api_key=key)
    if provider_name == "lambda":
        return LambdaLabsProvider(api_key=key)
    raise CloudGPUConfigError(
        provider=provider_name,
        hint=f"No adapter implemented for {provider_name!r}.",
    )
