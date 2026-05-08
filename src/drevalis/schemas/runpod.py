"""Pydantic v2 request/response schemas for the RunPod integration endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# -- Pod management schemas ----------------------------------------------------


class RunPodCreatePodRequest(BaseModel):
    """Payload for provisioning a new RunPod GPU pod."""

    model_config = ConfigDict(strict=True)

    name: str = Field(..., min_length=1, max_length=255, description="Pod display name")
    gpu_type_id: str = Field(
        default="NVIDIA RTX A4000",
        description="GPU type ID (see GET /api/v1/runpod/gpu-types for valid values)",
    )
    image: str = Field(
        default="runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel",
        description="Docker image for the pod container",
    )
    gpu_count: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Number of GPUs to attach",
    )
    template_id: str | None = Field(
        default=None,
        description="Optional RunPod template ID to pre-configure env vars and mounts",
    )
    volume_gb: int = Field(
        default=20,
        ge=5,
        le=500,
        description="Persistent volume size in GB",
    )
    ports: str = Field(
        default="8188/http,1234/http",
        description="Comma-separated port/protocol mappings (e.g. '8188/http,1234/http')",
    )
    env: dict[str, str] | None = Field(
        default=None,
        description="Environment variables to set on the pod (e.g. {'HF_TOKEN': 'hf_...'})",
    )
    docker_args: str = Field(
        default="",
        description="Docker command arguments for the container entrypoint",
    )


class RunPodRegisterPodRequest(BaseModel):
    """Payload for registering a running RunPod pod as a ComfyUI server."""

    model_config = ConfigDict(strict=True)

    comfyui_port: int = Field(
        default=8188,
        ge=1,
        le=65535,
        description="Port ComfyUI is listening on inside the pod",
    )
    server_name: str | None = Field(
        default=None,
        description=("Name for the ComfyUI server entry. Defaults to the pod ID if not supplied."),
    )
    max_concurrent: int = Field(
        default=2,
        ge=1,
        le=32,
        description="Maximum concurrent ComfyUI requests for this server",
    )


# -- Response schemas ----------------------------------------------------------


class RunPodGpuTypeResponse(BaseModel):
    """A single GPU type available for pod provisioning, with pricing."""

    id: str
    display_name: str = Field(alias="displayName")
    memory_in_gb: int = Field(alias="memoryInGb")
    secure_cloud: bool = Field(alias="secureCloud", default=False)
    community_cloud: bool = Field(alias="communityCloud", default=False)
    secure_price: float | None = Field(alias="securePrice", default=None)
    community_price: float | None = Field(alias="communityPrice", default=None)

    model_config = ConfigDict(populate_by_name=True)


class RunPodTemplateResponse(BaseModel):
    """A RunPod pod template returned by the templates endpoint."""

    id: str
    name: str
    image_name: str | None = Field(alias="imageName", default=None)
    is_public: bool = Field(alias="isPublic", default=False)
    category: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class RunPodPodRuntime(BaseModel):
    """Runtime information for a running pod."""

    uptime_in_seconds: int | None = Field(alias="uptimeInSeconds", default=None)
    ports: list[dict] | None = None  # type: ignore[type-arg]
    gpus: list[dict] | None = None  # type: ignore[type-arg]

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class RunPodPodMachine(BaseModel):
    """Machine information for a pod."""

    gpu_display_name: str | None = Field(alias="gpuDisplayName", default=None)

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class RunPodPodResponse(BaseModel):
    """Representation of a RunPod pod returned by list/get operations.

    RunPod's API returns variable fields depending on pod state; all optional
    fields here may be absent in certain states (e.g. while provisioning).
    """

    id: str
    name: str
    desired_status: str = Field(alias="desiredStatus", default="")
    image_name: str | None = Field(alias="imageName", default=None)
    gpu_count: int | None = Field(alias="gpuCount", default=None)
    vcpu_count: int | None = Field(alias="vcpuCount", default=None)
    memory_in_gb: int | None = Field(alias="memoryInGb", default=None)
    volume_in_gb: int | None = Field(alias="volumeInGb", default=None)
    cost_per_hr: float | None = Field(alias="costPerHr", default=None)
    machine: RunPodPodMachine | None = None
    runtime: RunPodPodRuntime | None = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class RunPodRegisterResponse(BaseModel):
    """Result of registering a pod as a ComfyUI server."""

    pod_id: str
    comfyui_server_id: str
    comfyui_url: str
    connection_ok: bool
    message: str


# -- API key store schemas (unchanged) -----------------------------------------


class ApiKeyStoreRequest(BaseModel):
    """Payload for storing an encrypted third-party API key."""

    model_config = ConfigDict(strict=True)

    key_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_-]+$",
        description="Slug identifier for the integration (e.g. 'runpod')",
    )
    api_key: str = Field(
        ...,
        min_length=1,
        description="Plain-text API key (will be encrypted before storage)",
    )


class ApiKeyStoreListItem(BaseModel):
    """Name-only representation of a stored API key (value is never returned).

    Timestamps surface when the key was added / last rotated — the UI
    displays them on the Settings → API Keys row. Optional for
    back-compat with the upsert response which only knows the name
    after writing.
    """

    key_name: str
    has_value: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ApiKeyStoreListResponse(BaseModel):
    """List of stored API key names."""

    items: list[ApiKeyStoreListItem]


class IntegrationStatus(BaseModel):
    """Whether a named integration has a configured API key."""

    configured: bool
    source: str = Field(
        description="Where the key was found: 'db', 'env', or 'none'",
    )


class IntegrationsStatusResponse(BaseModel):
    """Integration configuration status for all supported third-party services."""

    runpod: IntegrationStatus
    elevenlabs: IntegrationStatus
    anthropic: IntegrationStatus
    youtube: IntegrationStatus
