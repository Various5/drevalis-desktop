"""Pydantic schemas for ComfyUIWorkflow.input_mappings JSONB field.

input_mappings describes how Drevalis maps its internal parameters
(scene visual_prompt, seed, dimensions, etc.) onto the node inputs
of a particular ComfyUI workflow JSON.

Example payload::

    {
        "mappings": [
            {
                "sf_field": "visual_prompt",
                "node_id": "3",
                "field_name": "text",
                "description": "Positive prompt input on the KSampler"
            },
            {
                "sf_field": "negative_prompt",
                "node_id": "7",
                "field_name": "text",
                "description": "Negative prompt input"
            },
            {
                "sf_field": "seed",
                "node_id": "3",
                "field_name": "seed",
                "description": "Random seed for reproducibility"
            },
            {
                "sf_field": "width",
                "node_id": "5",
                "field_name": "width",
                "description": "Output image width"
            },
            {
                "sf_field": "height",
                "node_id": "5",
                "field_name": "height",
                "description": "Output image height"
            }
        ],
        "output_node_id": "9",
        "output_field_name": "images"
    }
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NodeInput(BaseModel):
    """Maps a single Drevalis field to a ComfyUI workflow node input."""

    sf_field: str = Field(
        ...,
        min_length=1,
        description=(
            "Drevalis internal field name "
            "(e.g. visual_prompt, negative_prompt, seed, width, height)"
        ),
    )
    node_id: str = Field(
        ...,
        min_length=1,
        description="ComfyUI node ID inside the workflow JSON",
    )
    field_name: str = Field(
        ...,
        min_length=1,
        description="Input field name on the target node",
    )
    description: str = Field(
        default="",
        description="Human-readable description of this mapping",
    )


class WorkflowInputMapping(BaseModel):
    """Top-level schema for comfyui_workflows.input_mappings JSONB column.

    Validated before INSERT/UPDATE to guarantee structural integrity.
    """

    mappings: list[NodeInput] = Field(
        ...,
        min_length=1,
        description="List of field-to-node input mappings",
    )
    output_node_id: str = Field(
        ...,
        min_length=1,
        description="Node ID that produces the final output image(s)",
    )
    output_field_name: str = Field(
        default="images",
        description="Output field name on the output node",
    )
