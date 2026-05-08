"""Bundled ComfyUI workflow templates.

Each template ships as two pieces:

1. A ``*.json`` file in this folder containing the full ComfyUI
   workflow JSON. This is the file the server loads and executes.
2. An entry in ``TEMPLATES`` below mapping a slug → metadata
   (display name, description, input mappings).

Templates are installed via ``POST /api/v1/comfyui/templates/{slug}/install``
which copies the JSON into ``workflows/drevalis/<slug>.json`` relative
to the active ComfyUI server's data dir and creates a matching
``ComfyUIWorkflow`` row so the UI can select it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkflowTemplate:
    """Single bundled template."""

    slug: str
    name: str
    description: str
    content_format: str  # "shorts" | "longform"
    scene_mode: str  # "image" | "video"
    # Named inputs the pipeline hands off to the workflow. Shape mirrors
    # ``WorkflowInputMapping`` on the ComfyUIWorkflow model.
    input_mappings: dict[str, Any]


TEMPLATES: dict[str, WorkflowTemplate] = {
    "ipadapter-faceid-sdxl": WorkflowTemplate(
        slug="ipadapter-faceid-sdxl",
        name="IPAdapter FaceID — SDXL",
        description=(
            "Character consistency across scenes. Wires series.character_lock's "
            "asset_ids into an IPAdapter-FaceID loader so every scene uses the "
            "same face. Works with SDXL base / Juggernaut / RealVisXL."
        ),
        content_format="shorts",
        scene_mode="image",
        input_mappings={
            "positive_prompt_node_id": "6",
            "negative_prompt_node_id": "7",
            "seed_node_id": "10",
            "width_node_id": "5",
            "height_node_id": "5",
            "character_ref_image_node_id": "42",
            "character_lora_node_id": "44",
        },
    ),
    "style-ref-sdxl": WorkflowTemplate(
        slug="style-ref-sdxl",
        name="Style reference — SDXL",
        description=(
            "Style consistency across scenes via IPAdapter-Style. Series.style_lock "
            "asset_ids are loaded as style references so every scene shares "
            "lighting / palette / grain. Stackable with a character lock."
        ),
        content_format="shorts",
        scene_mode="image",
        input_mappings={
            "positive_prompt_node_id": "6",
            "negative_prompt_node_id": "7",
            "seed_node_id": "10",
            "width_node_id": "5",
            "height_node_id": "5",
            "style_ref_image_node_id": "50",
            "style_lora_node_id": "52",
        },
    ),
    "wan2-6-i2v-motion-ref": WorkflowTemplate(
        slug="wan2-6-i2v-motion-ref",
        name="Wan 2.6 — image-to-video with motion ref",
        description=(
            "Long-form video scenes: generates a still from the scene prompt, "
            "animates it with Wan 2.6 i2v, optionally conditioned on a motion "
            "reference video (scene.motion_reference_asset_id)."
        ),
        content_format="longform",
        scene_mode="video",
        input_mappings={
            "positive_prompt_node_id": "6",
            "negative_prompt_node_id": "7",
            "seed_node_id": "10",
            "width_node_id": "5",
            "height_node_id": "5",
            "motion_reference_video_node_id": "60",
        },
    ),
}


def template_json_path(slug: str) -> Path:
    """Return the absolute path to a template's workflow JSON file."""
    return Path(__file__).parent / f"{slug}.json"
