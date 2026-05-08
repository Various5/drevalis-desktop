"""RunPod cloud GPU integration service.

Wraps the RunPod GraphQL API (https://graphql-spec.runpod.io/) using a thin
async httpx client.  No RunPod SDK is used to keep the dependency footprint
minimal and to stay in full control of error handling.

All public methods raise ``RunPodAPIError`` on API errors so callers can catch
a single, specific exception type.
"""

from __future__ import annotations

from typing import Any, cast

import httpx

# -- Exceptions ----------------------------------------------------------------


class RunPodAPIError(Exception):
    """Raised when the RunPod GraphQL API returns an error.

    Attributes:
        status_code: HTTP status code (or 400 for GraphQL-level errors).
        detail: Error message text (truncated to 500 chars).
    """

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"RunPod API error {status_code}: {detail}")


# -- Default values ------------------------------------------------------------

DEFAULT_GPU_TYPE: str = "NVIDIA RTX A4000"
DEFAULT_IMAGE: str = "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel"
DEFAULT_VOLUME_GB: int = 20
# Exposes ComfyUI (8188) and LM Studio (1234) via HTTP tunnels.
DEFAULT_PORTS: str = "8188/http,1234/http"


# -- GraphQL queries and mutations ---------------------------------------------

_QUERY_GPU_TYPES = """
{
  gpuTypes {
    id
    displayName
    memoryInGb
    secureCloud
    communityCloud
    securePrice
    communityPrice
  }
}
"""

_QUERY_TEMPLATES = """
{
  podTemplates {
    id
    name
    imageName
    isPublic
    category
  }
}
"""

_QUERY_PODS = """
query Pods {
  myself {
    pods {
      id
      name
      desiredStatus
      imageName
      machineId
      machine {
        gpuDisplayName
      }
      runtime {
        uptimeInSeconds
        ports {
          ip
          isIpPublic
          privatePort
          publicPort
          type
        }
        gpus {
          id
          gpuUtilPercent
          memoryUtilPercent
        }
      }
      gpuCount
      vcpuCount
      memoryInGb
      volumeInGb
      costPerHr
    }
  }
}
"""

_MUTATION_CREATE_POD = """
mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
  podFindAndDeployOnDemand(input: $input) {
    id
    name
    desiredStatus
    imageName
    costPerHr
    gpuCount
    vcpuCount
    memoryInGb
    volumeInGb
    machine {
      gpuDisplayName
    }
  }
}
"""

_MUTATION_STOP_POD = """
mutation StopPod($podId: String!) {
  podStop(input: { podId: $podId }) {
    id
    desiredStatus
  }
}
"""

_MUTATION_RESUME_POD = """
mutation ResumePod($podId: String!) {
  podResume(input: { podId: $podId, gpuCount: 1 }) {
    id
    desiredStatus
    costPerHr
  }
}
"""

_MUTATION_DELETE_POD = """
mutation DeletePod($podId: String!) {
  podTerminate(input: { podId: $podId })
}
"""


# -- Service -------------------------------------------------------------------


class RunPodService:
    """Async client for the RunPod GraphQL API.

    The instance owns an ``httpx.AsyncClient`` that must be cleaned up when
    the service is no longer needed -- call :meth:`close` explicitly or use the
    service as an async context manager::

        async with RunPodService(api_key) as svc:
            pods = await svc.list_pods()

    Args:
        api_key: Plain-text RunPod API key.  Never log or return this value.
    """

    GRAPHQL_URL: str = "https://api.runpod.io/graphql"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("RunPod API key must not be empty.")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(30.0),
        )

    # -- Context manager -------------------------------------------------------

    async def __aenter__(self) -> RunPodService:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client and release its connection pool."""
        await self._client.aclose()

    # -- Private helpers -------------------------------------------------------

    async def _query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query/mutation and return the ``data`` payload.

        Raises:
            RunPodAPIError: On HTTP errors or GraphQL-level errors.
        """
        payload: dict[str, object] = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = await self._client.post(self.GRAPHQL_URL, json=payload)
        except httpx.HTTPError as exc:
            raise RunPodAPIError(
                status_code=500,
                detail=f"HTTP request failed: {str(exc)[:500]}",
            ) from exc

        if not response.is_success:
            try:
                detail = response.text[:500]
            except Exception:
                detail = f"(could not read response body -- HTTP {response.status_code})"
            raise RunPodAPIError(
                status_code=response.status_code,
                detail=detail,
            )

        body = response.json()

        if "errors" in body and body["errors"]:
            errors = body["errors"]
            # Extract the first error message for a concise detail string.
            messages = [
                e.get("message", str(e)) for e in (errors if isinstance(errors, list) else [errors])
            ]
            detail = "; ".join(messages)[:500]
            raise RunPodAPIError(status_code=400, detail=detail)

        return cast(dict[str, Any], body.get("data", {}))

    # -- GPU types -------------------------------------------------------------

    async def get_gpu_types(self) -> list[dict[str, Any]]:
        """List GPU types available for on-demand pod provisioning.

        Returns:
            List of GPU type dicts containing ``id``, ``displayName``,
            ``memoryInGb``, ``secureCloud``, ``communityCloud``,
            ``securePrice`` (float, $/hr), and ``communityPrice``
            (float, $/hr).
        """
        data = await self._query(_QUERY_GPU_TYPES)
        return cast(list[dict[str, Any]], data.get("gpuTypes", []))

    async def get_templates(self, category: str | None = None) -> list[dict[str, Any]]:
        """List available RunPod pod templates.

        Args:
            category: Optional category filter (case-insensitive match).

        Returns:
            List of template dicts containing ``id``, ``name``,
            ``imageName``, ``isPublic``, and ``category``.
        """
        data = await self._query(_QUERY_TEMPLATES)
        templates: list[dict[str, Any]] = data.get("podTemplates", [])
        if category:
            templates = [t for t in templates if t.get("category", "").lower() == category.lower()]
        return templates

    # -- Pods ------------------------------------------------------------------

    async def list_pods(self) -> list[dict[str, Any]]:
        """Return all pods associated with the API key.

        Returns:
            A list of pod objects.  Each dict contains ``id``, ``name``,
            ``desiredStatus``, ``machine``, ``runtime``, ``costPerHr``, etc.
        """
        data = await self._query(_QUERY_PODS)
        myself = data.get("myself", {})
        return cast(list[dict[str, Any]], myself.get("pods", []))

    async def create_pod(
        self,
        name: str,
        gpu_type_id: str = DEFAULT_GPU_TYPE,
        image: str = DEFAULT_IMAGE,
        gpu_count: int = 1,
        volume_gb: int = DEFAULT_VOLUME_GB,
        ports: str = DEFAULT_PORTS,
        template_id: str | None = None,
        env: dict[str, str] | None = None,
        docker_args: str = "",
    ) -> dict:  # type: ignore[type-arg]
        """Provision and start a new RunPod GPU pod.

        Args:
            name: Human-readable pod name.
            gpu_type_id: GPU type ID string (e.g. ``"NVIDIA RTX A4000"``).
            image: Docker image to run.
            gpu_count: Number of GPUs to attach (1-8).
            volume_gb: Persistent volume size in GB.
            ports: Comma-separated port/protocol mappings.
            template_id: Optional RunPod template ID.
            env: Optional environment variables (e.g. ``{"HF_TOKEN": "hf_..."}``).

        Returns:
            The newly created pod object dict.
        """
        input_vars: dict[str, object] = {
            "name": name,
            "gpuTypeId": gpu_type_id,
            "imageName": image,
            "gpuCount": gpu_count,
            "volumeInGb": volume_gb,
            "containerDiskInGb": max(20, volume_gb),
            "volumeMountPath": "/workspace",
            "ports": ports,
        }
        if template_id:
            input_vars["templateId"] = template_id
        if docker_args:
            input_vars["dockerArgs"] = docker_args
        if env:
            input_vars["env"] = [{"key": k, "value": v} for k, v in env.items()]

        data = await self._query(
            _MUTATION_CREATE_POD,
            variables={"input": input_vars},
        )
        return cast(dict[str, Any], data.get("podFindAndDeployOnDemand", {}))

    async def stop_pod(self, pod_id: str) -> dict[str, Any]:
        """Stop a running pod (suspend billing without deleting storage).

        Args:
            pod_id: RunPod pod identifier string.

        Returns:
            Updated pod object dict with ``id`` and ``desiredStatus``.
        """
        data = await self._query(
            _MUTATION_STOP_POD,
            variables={"podId": pod_id},
        )
        return cast(dict[str, Any], data.get("podStop", {}))

    async def start_pod(self, pod_id: str) -> dict[str, Any]:
        """Resume a stopped pod (resume billing).

        Args:
            pod_id: RunPod pod identifier string.

        Returns:
            Updated pod object dict with ``id``, ``desiredStatus``, and
            ``costPerHr``.
        """
        data = await self._query(
            _MUTATION_RESUME_POD,
            variables={"podId": pod_id},
        )
        return cast(dict[str, Any], data.get("podResume", {}))

    async def delete_pod(self, pod_id: str) -> None:
        """Permanently delete a pod and its storage.

        Args:
            pod_id: RunPod pod identifier string.
        """
        await self._query(
            _MUTATION_DELETE_POD,
            variables={"podId": pod_id},
        )
