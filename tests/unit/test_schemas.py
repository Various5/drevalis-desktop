"""Tests for Pydantic schemas -- validation and serialization."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from drevalis.schemas.comfyui import NodeInput, WorkflowInputMapping
from drevalis.schemas.progress import ProgressMessage
from drevalis.schemas.script import EpisodeScript, SceneScript
from drevalis.schemas.series import SeriesCreate


class TestEpisodeScript:
    """Test EpisodeScript schema validation."""

    def test_episode_script_valid(self, sample_episode_script: EpisodeScript) -> None:
        assert sample_episode_script.title == "Why Cats Ignore You"
        assert len(sample_episode_script.scenes) == 3
        assert sample_episode_script.total_duration_seconds == 16.0
        assert sample_episode_script.language == "en-US"
        assert sample_episode_script.outro == "Follow for more cat facts!"

    def test_episode_script_from_dict(self) -> None:
        data = {
            "title": "Test Title",
            "hook": "Attention hook",
            "scenes": [
                {
                    "scene_number": 1,
                    "narration": "Scene one text.",
                    "visual_prompt": "A cinematic scene",
                    "duration_seconds": 5.0,
                }
            ],
            "total_duration_seconds": 5.0,
        }
        script = EpisodeScript.model_validate(data)
        assert script.title == "Test Title"
        assert script.outro == ""  # default
        assert script.language == "en-US"  # default

    def test_episode_script_missing_hook_defaults_to_empty(self) -> None:
        # ``hook`` is no longer required (defaults to "") so that LLM
        # outputs missing the field still validate. The caller's
        # ``_step_script`` treats an empty hook as a silent no-op.
        script = EpisodeScript(
            title="Title",
            scenes=[
                SceneScript(
                    scene_number=1,
                    narration="Text",
                    visual_prompt="Prompt",
                    duration_seconds=5.0,
                )
            ],
            total_duration_seconds=5.0,
        )
        assert script.hook == ""

    def test_episode_script_empty_title_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EpisodeScript(
                title="",  # min_length=1
                hook="hook",
                scenes=[
                    SceneScript(
                        scene_number=1,
                        narration="text",
                        visual_prompt="prompt",
                        duration_seconds=5.0,
                    )
                ],
                total_duration_seconds=5.0,
            )

    def test_episode_script_empty_scenes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EpisodeScript(
                title="Title",
                hook="Hook",
                scenes=[],  # min_length=1
                total_duration_seconds=5.0,
            )

    def test_episode_script_zero_duration_accepted(self) -> None:
        # ``total_duration_seconds`` is a derived / advisory field; the
        # assembly step computes the real duration from scene assets.
        # Zero is accepted so partial LLM outputs don't fail validation
        # before the pipeline can recompute.
        script = EpisodeScript(
            title="Title",
            hook="Hook",
            scenes=[
                SceneScript(
                    scene_number=1,
                    narration="text",
                    visual_prompt="prompt",
                    duration_seconds=5.0,
                )
            ],
            total_duration_seconds=0,
        )
        assert script.total_duration_seconds == 0


class TestSceneScript:
    """Test SceneScript schema validation."""

    def test_scene_script_valid(self) -> None:
        scene = SceneScript(
            scene_number=1,
            narration="Some narration",
            visual_prompt="A prompt",
            duration_seconds=3.5,
        )
        assert scene.scene_number == 1
        assert scene.duration_seconds == 3.5

    def test_scene_script_zero_scene_number_accepted(self) -> None:
        # ``scene_number=0`` is accepted (ge=0) so LLM outputs that
        # forget to number the hook/intro scene still validate. The
        # pipeline re-numbers scenes deterministically before storage.
        scene = SceneScript(
            scene_number=0,
            narration="text",
            visual_prompt="prompt",
            duration_seconds=5.0,
        )
        assert scene.scene_number == 0

    def test_scene_script_negative_duration(self) -> None:
        with pytest.raises(ValidationError):
            SceneScript(
                scene_number=1,
                narration="text",
                visual_prompt="prompt",
                duration_seconds=-1.0,  # gt=0
            )

    def test_scene_script_empty_narration(self) -> None:
        with pytest.raises(ValidationError):
            SceneScript(
                scene_number=1,
                narration="",  # min_length=1
                visual_prompt="prompt",
                duration_seconds=5.0,
            )


class TestWorkflowInputMapping:
    """Test WorkflowInputMapping schema validation."""

    def test_workflow_input_mapping_valid(
        self, sample_workflow_mapping: WorkflowInputMapping
    ) -> None:
        assert len(sample_workflow_mapping.mappings) == 5
        assert sample_workflow_mapping.output_node_id == "9"
        assert sample_workflow_mapping.output_field_name == "images"

    def test_workflow_input_mapping_from_dict(self) -> None:
        data = {
            "mappings": [
                {
                    "sf_field": "visual_prompt",
                    "node_id": "3",
                    "field_name": "text",
                }
            ],
            "output_node_id": "9",
            "output_field_name": "images",
        }
        mapping = WorkflowInputMapping.model_validate(data)
        assert mapping.mappings[0].sf_field == "visual_prompt"
        assert mapping.mappings[0].description == ""  # default

    def test_workflow_input_mapping_empty_mappings_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowInputMapping(
                mappings=[],  # min_length=1
                output_node_id="9",
            )

    def test_workflow_input_mapping_empty_output_node_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowInputMapping(
                mappings=[
                    NodeInput(
                        sf_field="visual_prompt",
                        node_id="3",
                        field_name="text",
                    )
                ],
                output_node_id="",  # min_length=1
            )

    def test_workflow_input_mapping_default_output_field(self) -> None:
        mapping = WorkflowInputMapping(
            mappings=[
                NodeInput(
                    sf_field="visual_prompt",
                    node_id="3",
                    field_name="text",
                )
            ],
            output_node_id="9",
        )
        assert mapping.output_field_name == "images"  # default


class TestProgressMessage:
    """Test ProgressMessage schema."""

    def test_progress_message_serialization(self) -> None:
        msg = ProgressMessage(
            episode_id="abc-123",
            job_id="job-456",
            step="scenes",
            status="running",
            progress_pct=42,
            message="Generating scene 2 of 5",
            detail={"scene_number": 2, "total_scenes": 5},
        )

        # Serialize to JSON
        json_str = msg.model_dump_json()
        data = json.loads(json_str)

        assert data["episode_id"] == "abc-123"
        assert data["step"] == "scenes"
        assert data["status"] == "running"
        assert data["progress_pct"] == 42
        assert data["detail"]["scene_number"] == 2
        assert data["error"] is None

    def test_progress_message_with_error(self) -> None:
        msg = ProgressMessage(
            episode_id="abc",
            job_id="job",
            step="voice",
            status="failed",
            progress_pct=10,
            error="ConnectionError: TTS server down",
        )

        assert msg.error == "ConnectionError: TTS server down"
        assert msg.status == "failed"

    def test_progress_message_invalid_step_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProgressMessage(
                episode_id="abc",
                job_id="job",
                step="invalid_step",  # Not in Literal
                status="running",
                progress_pct=0,
            )

    def test_progress_message_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProgressMessage(
                episode_id="abc",
                job_id="job",
                step="script",
                status="unknown",  # Not in Literal
                progress_pct=0,
            )

    def test_progress_message_pct_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ProgressMessage(
                episode_id="abc",
                job_id="job",
                step="script",
                status="running",
                progress_pct=101,  # > 100
            )

        with pytest.raises(ValidationError):
            ProgressMessage(
                episode_id="abc",
                job_id="job",
                step="script",
                status="running",
                progress_pct=-1,  # < 0
            )


class TestSeriesCreate:
    """Test SeriesCreate schema validation."""

    def test_series_create_valid_durations(self) -> None:
        for duration in (15, 30, 60):
            series = SeriesCreate(
                name=f"Test Series {duration}s",
                target_duration_seconds=duration,
            )
            assert series.target_duration_seconds == duration

    def test_series_create_invalid_duration(self) -> None:
        with pytest.raises(ValidationError):
            SeriesCreate(
                name="Bad Duration Series",
                target_duration_seconds=45,  # Not in Literal[15, 30, 60]
            )

    def test_series_create_default_duration(self) -> None:
        series = SeriesCreate(name="Default Series")
        assert series.target_duration_seconds == 30  # default

    def test_series_create_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SeriesCreate(name="")  # min_length=1

    def test_series_create_defaults(self) -> None:
        series = SeriesCreate(name="Minimal Series")
        assert series.description is None
        assert series.voice_profile_id is None
        assert series.visual_style == ""
        assert series.default_language == "en-US"
