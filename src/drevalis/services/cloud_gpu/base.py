"""Cloud GPU provider abstraction — unified surface across RunPod,
Vast.ai, Lambda Labs, and future add-ons.

Each provider implements :class:`CloudGPUProvider`. The protocol is
deliberately minimal — the goal is "launch a GPU VM, point the app's
ComfyUI / vLLM service at its IP, shut it down when idle." Providers
differ wildly in how they model their inventory (RunPod has
templates, Vast has a marketplace of offers, Lambda has fixed
instance types), but every surface here returns the same normalised
dict shapes so the API + UI can stay provider-agnostic.

Normalised shapes:

``GpuType`` — things the user can launch::

    {
      "id":          "<provider-local id>",
      "label":       "RTX 4090 (24 GB)",
      "vram_gb":     24,
      "hourly_usd":  0.39,
      "provider":    "runpod" | "vastai" | "lambda",
      "region":      "optional region/location hint",
      "metadata":    {...raw provider-specific extras...},
    }

``Pod`` — a running (or launching / stopped) instance::

    {
      "id":          "<provider-local pod id>",
      "name":        "<user-visible label>",
      "status":      "queued" | "starting" | "running" | "stopping" |
                     "stopped" | "terminated" | "error",
      "gpu_type_id": "<id of the GpuType this was launched from>",
      "public_url":  "http://1.2.3.4:8188" or None,
      "hourly_usd":  0.39,
      "started_at":  ISO 8601 string or None,
      "provider":    "runpod" | "vastai" | "lambda",
      "metadata":    {...raw extras...},
    }
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CloudGPUProvider(Protocol):
    """Every cloud GPU provider implements these six methods.

    Providers that have no native concept of a given operation (e.g.
    Lambda doesn't separate "stop" from "terminate") raise
    :class:`NotImplementedError` with a clear message so the UI can
    disable the relevant button rather than silently succeed.
    """

    @property
    def name(self) -> str:
        """Short identifier: ``"runpod"``, ``"vastai"``, ``"lambda"``."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable label for UI."""
        ...

    async def list_gpu_types(self) -> list[dict[str, Any]]:
        """Return the catalogue of GPU tiers the user can launch."""
        ...

    async def list_pods(self) -> list[dict[str, Any]]:
        """Return every pod the user's account currently owns."""
        ...

    async def create_pod(
        self,
        *,
        gpu_type_id: str,
        name: str,
        image: str | None = None,
        disk_gb: int = 40,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Provision and launch a new pod. Returns the normalised pod dict."""
        ...

    async def stop_pod(self, pod_id: str) -> dict[str, Any]:
        """Stop a running pod (keeps state, cheap to resume)."""
        ...

    async def start_pod(self, pod_id: str) -> dict[str, Any]:
        """Resume a stopped pod."""
        ...

    async def delete_pod(self, pod_id: str) -> None:
        """Permanently destroy a pod + its storage."""
        ...

    async def get_pod(self, pod_id: str) -> dict[str, Any] | None:
        """Fetch one pod's current status. None when it no longer exists."""
        ...


class CloudGPUProviderError(Exception):
    """Raised when a provider call fails in a way the operator should see.

    Carries ``status_code`` so the route layer can pass the right HTTP
    status through, plus ``detail`` with a human-readable message.
    """

    def __init__(self, *, provider: str, status_code: int, detail: str) -> None:
        super().__init__(f"[{provider}] {status_code}: {detail}")
        self.provider = provider
        self.status_code = status_code
        self.detail = detail


class CloudGPUConfigError(CloudGPUProviderError):
    """Raised when a provider can't be used because its credentials / config
    are missing. The UI renders this as a "connect this provider in
    Settings" prompt rather than a red error banner."""

    def __init__(self, *, provider: str, hint: str) -> None:
        super().__init__(provider=provider, status_code=503, detail=hint)


def wrap_httpx_error(provider: str, action: str, exc: Exception) -> CloudGPUProviderError:
    """Build a CloudGPUProviderError out of a raised httpx exception.

    The raise-from-httpx.HTTPError boilerplate was duplicated 26x across
    runpod / vastai / lambda_labs providers; centralising it ensures
    every provider surfaces upstream status codes the same way and that
    the UI gets one consistent shape to render.
    """
    status_code = 500
    response = getattr(exc, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", 500)
    return CloudGPUProviderError(
        provider=provider,
        status_code=status_code,
        detail=f"Failed to {action}: {exc}",
    )


def wrap_provider_api_error(provider: str, exc: Any) -> CloudGPUProviderError:
    """Build a CloudGPUProviderError from a provider-specific API exception.

    Use for upstream-SDK exception classes (e.g. RunPodAPIError) that
    already expose ``status_code`` and ``detail`` attributes — the
    helper just lifts them onto our shared error type so callers don't
    repeat the same construction boilerplate at every call site.
    """
    return CloudGPUProviderError(
        provider=provider,
        status_code=int(getattr(exc, "status_code", 500) or 500),
        detail=str(getattr(exc, "detail", "") or str(exc)),
    )
