"""Tests for the bundled ComfyUI workflow template registry.

The TEMPLATES dict ships JSON workflows that the install endpoint
copies into the user's ComfyUI workflows folder. A drift between the
registry and the on-disk JSON files (missing slug, wrong filename)
ships as "Install button silently does nothing" tickets.
"""

from __future__ import annotations

import json

import pytest

from drevalis.services.comfyui.templates import (
    TEMPLATES,
    WorkflowTemplate,
    template_json_path,
)

# ── Registry shape ───────────────────────────────────────────────────


class TestTemplateRegistry:
    def test_registry_has_at_least_one_template(self) -> None:
        assert len(TEMPLATES) > 0

    def test_every_slug_matches_its_entry(self) -> None:
        for slug, tpl in TEMPLATES.items():
            assert tpl.slug == slug, f"{slug} entry has wrong slug={tpl.slug}"

    @pytest.mark.parametrize("slug", list(TEMPLATES.keys()))
    def test_template_has_required_metadata(self, slug: str) -> None:
        tpl = TEMPLATES[slug]
        assert tpl.name
        assert tpl.description
        assert tpl.content_format in {"shorts", "longform", "animation"}
        assert tpl.scene_mode in {"image", "video"}
        assert isinstance(tpl.input_mappings, dict)
        assert tpl.input_mappings  # non-empty

    @pytest.mark.parametrize("slug", list(TEMPLATES.keys()))
    def test_input_mappings_use_string_node_ids(self, slug: str) -> None:
        tpl = TEMPLATES[slug]
        for key, node_id in tpl.input_mappings.items():
            # ComfyUI node IDs are strings even when they look numeric.
            assert isinstance(node_id, str), (
                f"{slug}: input_mappings[{key!r}]={node_id!r} should be str"
            )

    def test_workflow_template_is_frozen(self) -> None:
        # frozen=True dataclass: any mutation raises FrozenInstanceError.
        tpl = next(iter(TEMPLATES.values()))
        with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError or AttributeError
            tpl.name = "mutated"  # type: ignore[misc]


# ── template_json_path + on-disk consistency ─────────────────────────


class TestTemplateJsonPath:
    @pytest.mark.parametrize("slug", list(TEMPLATES.keys()))
    def test_path_for_slug_exists(self, slug: str) -> None:
        path = template_json_path(slug)
        assert path.exists(), f"template JSON missing on disk: {path}"
        assert path.is_file()

    @pytest.mark.parametrize("slug", list(TEMPLATES.keys()))
    def test_path_filename_is_slug_dot_json(self, slug: str) -> None:
        path = template_json_path(slug)
        assert path.name == f"{slug}.json"

    def test_path_for_unknown_slug_returns_nonexistent(self) -> None:
        # The function returns a path even for unknown slugs — it doesn't
        # validate, just composes the path. The install endpoint surfaces
        # the file-not-found error to the user.
        path = template_json_path("definitely-not-a-real-template")
        assert path.exists() is False

    @pytest.mark.parametrize("slug", list(TEMPLATES.keys()))
    def test_template_json_is_valid_json(self, slug: str) -> None:
        # A dist with a corrupted JSON file would silently fail at install
        # time. Pin the structural contract so corruption shows up here.
        path = template_json_path(slug)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        # ComfyUI workflow JSONs are dicts of node_id → node_def.
        assert len(data) > 0

    @pytest.mark.parametrize("slug", list(TEMPLATES.keys()))
    def test_all_node_ids_in_input_mappings_exist_in_workflow_json(self, slug: str) -> None:
        # The strongest invariant: every node_id the registry references
        # must exist in the actual workflow JSON. Missing node_ids =
        # silent prompt-not-applied bugs at scene-gen time.
        path = template_json_path(slug)
        data = json.loads(path.read_text(encoding="utf-8"))
        # ComfyUI exports vary: top-level dict of node_id→node, or
        # ``{"nodes": [...]}`` from the "Save (API Format)" path. Handle both.
        node_ids: set[str] = set()
        if isinstance(data, dict) and "nodes" in data and isinstance(data["nodes"], list):
            for node in data["nodes"]:
                nid = node.get("id")
                if nid is not None:
                    node_ids.add(str(nid))
        else:
            node_ids = {str(k) for k in data}

        if not node_ids:
            pytest.skip(f"{slug}: workflow JSON has no recognisable node id structure")

        tpl = TEMPLATES[slug]
        for key, ref_id in tpl.input_mappings.items():
            assert ref_id in node_ids, (
                f"{slug}: input_mappings[{key!r}]={ref_id!r} not found in workflow JSON. "
                f"Available node ids: {sorted(node_ids)[:10]}..."
            )


# ── WorkflowTemplate dataclass ───────────────────────────────────────


class TestWorkflowTemplateDataclass:
    def test_construct_minimal(self) -> None:
        tpl = WorkflowTemplate(
            slug="x",
            name="X",
            description="d",
            content_format="shorts",
            scene_mode="image",
            input_mappings={"a": "1"},
        )
        assert tpl.slug == "x"
        assert tpl.input_mappings == {"a": "1"}

    def test_path_under_module_dir(self) -> None:
        # template_json_path returns a path inside the templates package
        # (so install logic can resolve it via importlib.resources).
        path = template_json_path("any-slug")
        # Path is rooted in the templates/ folder.
        assert path.parent.name == "templates"
        assert path.parent.parent.name == "comfyui"


# ── Registry uniqueness invariants ───────────────────────────────────


class TestRegistryUniqueness:
    def test_slugs_are_unique(self) -> None:
        slugs = list(TEMPLATES.keys())
        assert len(slugs) == len(set(slugs))

    def test_display_names_are_unique(self) -> None:
        # Two templates with identical display names confuse the install
        # picker. Pin uniqueness.
        names = [t.name for t in TEMPLATES.values()]
        assert len(names) == len(set(names))

    def test_slugs_are_filename_safe(self) -> None:
        # Slugs are used as filenames; reject anything that wouldn't
        # roundtrip cleanly through the filesystem.
        for slug in TEMPLATES:
            assert "/" not in slug
            assert "\\" not in slug
            assert ".." not in slug
            assert " " not in slug
