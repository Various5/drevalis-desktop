"""Tests for PipelineOrchestrator._get_error_suggestion (F-Tst-11).

The static method maps error keywords to user-facing suggestion strings.
A copy-paste typo in a keyword (``"comfui"`` vs ``"comfyui"``) would
silently route the user to "Try retrying this step" instead of the
actionable suggestion. Pinning each branch with a direct assertion is
trivial — the method is pure and takes no I/O.
"""

from __future__ import annotations

import pytest

from drevalis.services.pipeline import PipelineOrchestrator, PipelineStep


def _suggest(exc_msg: str, step: PipelineStep = PipelineStep.SCRIPT) -> str:
    return PipelineOrchestrator._get_error_suggestion(step, RuntimeError(exc_msg))


class TestGetErrorSuggestion:
    def test_comfyui_keyword(self) -> None:
        assert "ComfyUI" in _suggest("ComfyUI server unreachable")

    def test_connection_keyword_routes_to_comfyui_branch(self) -> None:
        # ``connection`` is OR'd with ``comfyui`` since most pipeline
        # connection errors are the comfyui server going away.
        assert "ComfyUI" in _suggest("connection refused")

    def test_timeout_keyword(self) -> None:
        s = _suggest("operation timeout exceeded")
        assert "timed out" in s.lower()

    def test_piper_keyword(self) -> None:
        assert "TTS" in _suggest("piper subprocess failed")

    def test_edge_tts_keyword(self) -> None:
        assert "TTS" in _suggest("edge_tts request rejected")

    def test_ffmpeg_keyword(self) -> None:
        assert "FFmpeg" in _suggest("ffmpeg returned non-zero")

    def test_cancelled_keyword(self) -> None:
        assert "cancelled" in _suggest("job cancelled by user").lower()

    def test_llm_keyword(self) -> None:
        s = _suggest("llm provider exhausted")
        assert "LLM" in s

    def test_openai_keyword_routes_to_llm(self) -> None:
        assert "LLM" in _suggest("openai 500 error")

    def test_anthropic_keyword_routes_to_llm(self) -> None:
        assert "LLM" in _suggest("anthropic rate limit")

    def test_whisper_keyword(self) -> None:
        s = _suggest("faster-whisper model load failed")
        assert "Caption" in s

    def test_no_x_found_pattern_includes_step(self) -> None:
        s = _suggest("no audio found", step=PipelineStep.ASSEMBLY)
        assert "assembly" in s
        assert "previous steps" in s.lower()

    def test_unknown_error_returns_generic_retry(self) -> None:
        assert _suggest("something completely unrelated") == "Try retrying this step"

    def test_case_insensitive(self) -> None:
        # The method lowercases internally; UPPERCASE keywords match.
        assert "ComfyUI" in _suggest("COMFYUI EXPLODED")
        assert "FFmpeg" in _suggest("FFMPEG core dumped")

    def test_keyword_priority_comfyui_beats_timeout(self) -> None:
        # ``comfyui`` checked before ``timeout`` — error mentioning both
        # should route to the ComfyUI branch (more actionable).
        s = _suggest("comfyui timeout after 60s")
        assert "ComfyUI" in s
        assert "timed out" not in s.lower()

    @pytest.mark.parametrize("step", list(PipelineStep))
    def test_no_x_found_works_for_every_step(self, step: PipelineStep) -> None:
        # Defensive: the step name is interpolated into the message; no
        # step value should produce a malformed suggestion.
        s = _suggest("no scene found", step=step)
        assert step.value in s
