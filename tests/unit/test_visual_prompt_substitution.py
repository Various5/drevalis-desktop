"""Unit tests for the visual-prompt refiner placeholder substitution
behaviour (Phase 2.4).

Covers the four template-shape cases:
1. Legacy template using ``{prompt}``
2. New template using ``{scene_prompt}``
3. Mixed: template references both ``{prompt}`` and ``{character}``
4. Unknown placeholder: should not crash; missing keys substitute ``""``

The orchestrator method is tested indirectly through ``_DefaultPromptDict``
and ``str.format_map`` — that's the load-bearing primitive. We don't need
a full PipelineOrchestrator instance to verify the substitution.
"""

from __future__ import annotations

from drevalis.services.pipeline._monolith import _DefaultPromptDict


def _format(template: str, **kwargs: str) -> str:
    return template.format_map(_DefaultPromptDict(kwargs))


class TestDefaultPromptDictSubstitution:
    def test_legacy_prompt_placeholder(self) -> None:
        template = "Refine this prompt: {prompt}"
        out = _format(template, prompt="wide shot, golden hour")
        assert out == "Refine this prompt: wide shot, golden hour"

    def test_new_scene_prompt_placeholder(self) -> None:
        template = "Original prompt:\n{scene_prompt}\n\nStyle: {style}"
        out = _format(
            template,
            scene_prompt="brass sextant on stained linen",
            style="kodachrome 70s",
        )
        assert "brass sextant on stained linen" in out
        assert "kodachrome 70s" in out

    def test_mixed_placeholders(self) -> None:
        template = "Original: {scene_prompt}\nLegacy: {prompt}\nCharacter: {character}"
        out = _format(
            template,
            scene_prompt="A",
            prompt="B",
            character="Jonathan James, fifteen",
        )
        assert "Original: A" in out
        assert "Legacy: B" in out
        assert "Character: Jonathan James, fifteen" in out

    def test_unknown_placeholder_resolves_to_empty(self) -> None:
        template = "Prompt: {scene_prompt}\nMystery: {nonexistent}"
        out = _format(template, scene_prompt="rain on tarmac")
        assert "Prompt: rain on tarmac" in out
        # The unknown placeholder substitutes to "" rather than raising.
        assert "Mystery: " in out
        assert "{nonexistent}" not in out

    def test_empty_substitutions_dont_crash(self) -> None:
        template = "{scene_prompt} | {style} | {character}"
        out = _format(template)
        assert out == " |  | "

    def test_dict_only_returns_empty_for_missing_keys(self) -> None:
        d = _DefaultPromptDict({"a": "x"})
        assert d["a"] == "x"
        assert d["b"] == ""
        # Direct __missing__ contract — important for format_map.
        assert d.__missing__("anything") == ""
