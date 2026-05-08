"""Tests for the music-video service (Phase 1: plan + beat detection)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from drevalis.services.music_video import (
    SongSection,
    SongStructure,
    _coerce_song_structure,
    _extract_json_block,
    _instrumental_fallback,
    detect_beats,
    plan_song,
    render_song,
    slice_scenes_to_beats,
)

# ── _extract_json_block ─────────────────────────────────────────────────


class TestExtractJsonBlock:
    def test_plain_json(self) -> None:
        assert _extract_json_block('{"a": 1}') == {"a": 1}

    def test_inside_code_fence(self) -> None:
        text = '```json\n{"a": 1, "b": "two"}\n```'
        assert _extract_json_block(text) == {"a": 1, "b": "two"}

    def test_inside_unlabelled_fence(self) -> None:
        text = '```\n{"a": 1}\n```'
        assert _extract_json_block(text) == {"a": 1}

    def test_with_trailing_chatter(self) -> None:
        text = 'Sure, here is the plan:\n{"a": 1}\nLet me know!'
        assert _extract_json_block(text) == {"a": 1}

    def test_returns_none_on_garbage(self) -> None:
        assert _extract_json_block("no json at all") is None

    def test_returns_none_on_unparseable(self) -> None:
        assert _extract_json_block('{"a": 1, broken}') is None

    def test_extracts_inner_object_from_array_wrapper(self) -> None:
        # The extractor is intentionally permissive: when the response
        # is a single-object array, it pulls the inner object out so
        # the LLM doesn't accidentally fail planning by emitting
        # ``[{...}]`` instead of ``{...}``.
        assert _extract_json_block('[{"a": 1}]') == {"a": 1}

    def test_returns_none_when_no_braces(self) -> None:
        assert _extract_json_block("[1, 2, 3]") is None


# ── _coerce_song_structure ──────────────────────────────────────────────


class TestCoerceSongStructure:
    def test_full_well_formed_input(self) -> None:
        raw = {
            "title": "Neon Dreams",
            "artist_persona": "Synth-pop duo, breathy vocals",
            "genre": "synth-pop",
            "mood": "dreamy",
            "key": "C minor",
            "bpm": 128,
            "sections": [
                {
                    "name": "intro",
                    "lyrics": "(instrumental)",
                    "duration_seconds": 8,
                    "visual_prompt": "Neon city at dusk",
                },
                {
                    "name": "verse1",
                    "lyrics": "Walking down the rain",
                    "duration_seconds": 24,
                    "visual_prompt": "Singer in slow-mo",
                },
            ],
        }
        plan = _coerce_song_structure(raw)
        assert plan.title == "Neon Dreams"
        assert plan.genre == "synth-pop"
        assert plan.key_bpm == ("C minor", 128)
        assert len(plan.sections) == 2
        assert plan.sections[0].name == "intro"
        assert plan.sections[1].duration_seconds == 24

    def test_missing_fields_use_defaults(self) -> None:
        plan = _coerce_song_structure({})
        assert plan.title == "Untitled"
        assert plan.genre == "synth-pop"
        assert plan.mood == "cinematic"
        assert plan.key_bpm == ("C major", 120)
        assert plan.sections == []

    def test_invalid_bpm_clamped(self) -> None:
        plan = _coerce_song_structure({"bpm": 999})
        assert plan.key_bpm[1] == 220
        plan = _coerce_song_structure({"bpm": 5})
        assert plan.key_bpm[1] == 40
        plan = _coerce_song_structure({"bpm": "abc"})
        assert plan.key_bpm[1] == 120

    def test_section_with_zero_duration_dropped(self) -> None:
        raw = {
            "sections": [
                {"name": "intro", "duration_seconds": 0},
                {"name": "verse", "duration_seconds": 20},
            ]
        }
        plan = _coerce_song_structure(raw)
        assert len(plan.sections) == 1
        assert plan.sections[0].name == "verse"

    def test_section_duration_clamped(self) -> None:
        raw = {"sections": [{"name": "x", "duration_seconds": 999}]}
        plan = _coerce_song_structure(raw)
        assert plan.sections[0].duration_seconds == 120.0

    def test_overly_long_strings_truncated(self) -> None:
        raw = {
            "title": "x" * 500,
            "sections": [
                {
                    "name": "y" * 100,
                    "duration_seconds": 5,
                    "visual_prompt": "z" * 1000,
                }
            ],
        }
        plan = _coerce_song_structure(raw)
        assert len(plan.title) <= 120
        assert len(plan.sections[0].name) <= 40
        assert len(plan.sections[0].visual_prompt) <= 400


# ── plan_song ───────────────────────────────────────────────────────────


@dataclass
class _FakeLLMResult:
    content: str
    model: str = "fake"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class _FakeLLMProvider:
    def __init__(self, content: str | Exception) -> None:
        self.content = content
        self.calls: list[tuple[str, str, dict]] = []

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> _FakeLLMResult:
        self.calls.append(
            (
                system_prompt,
                user_prompt,
                {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "json_mode": json_mode,
                },
            )
        )
        if isinstance(self.content, Exception):
            raise self.content
        return _FakeLLMResult(content=self.content)


class TestPlanSong:
    async def test_happy_path_returns_full_plan(self) -> None:
        plan_json = json.dumps(
            {
                "title": "Sunlit",
                "artist_persona": "Indie folk",
                "genre": "folk",
                "mood": "warm",
                "key": "G major",
                "bpm": 90,
                "sections": [
                    {
                        "name": "intro",
                        "lyrics": "(instrumental)",
                        "duration_seconds": 8,
                        "visual_prompt": "Wheat field at sunrise",
                    },
                    {
                        "name": "verse1",
                        "lyrics": "Hello morning sun",
                        "duration_seconds": 22,
                        "visual_prompt": "Singer walking",
                    },
                ],
            }
        )
        provider = _FakeLLMProvider(plan_json)
        plan = await plan_song(provider, "morning walk", target_duration_seconds=60.0)
        assert plan.title == "Sunlit"
        assert len(plan.sections) == 2
        assert plan.sections[0].name == "intro"

    async def test_calls_llm_with_json_mode(self) -> None:
        provider = _FakeLLMProvider(
            json.dumps({"title": "X", "sections": [{"name": "v", "duration_seconds": 30}]})
        )
        await plan_song(provider, "topic", target_duration_seconds=30.0)
        assert provider.calls, "provider was not called"
        kwargs = provider.calls[0][2]
        assert kwargs["json_mode"] is True

    async def test_user_prompt_contains_topic_and_duration(self) -> None:
        provider = _FakeLLMProvider(
            json.dumps({"title": "X", "sections": [{"name": "v", "duration_seconds": 30}]})
        )
        await plan_song(provider, "rainy nights", target_duration_seconds=180.0, genre_hint="lofi")
        user_prompt = provider.calls[0][1]
        assert "rainy nights" in user_prompt
        assert "180" in user_prompt
        assert "lofi" in user_prompt

    async def test_llm_failure_falls_back_to_instrumental(self) -> None:
        provider = _FakeLLMProvider(ConnectionError("LM Studio down"))
        plan = await plan_song(provider, "topic", target_duration_seconds=60.0)
        assert plan.sections[0].name == "intro"
        assert plan.sections[0].lyrics == "(instrumental)"
        assert plan.sections[0].duration_seconds == 60.0

    async def test_garbage_response_falls_back_to_instrumental(self) -> None:
        provider = _FakeLLMProvider("definitely not json")
        plan = await plan_song(provider, "topic", target_duration_seconds=45.0)
        assert plan.sections[0].name == "intro"
        assert plan.sections[0].duration_seconds >= 15.0

    async def test_empty_sections_falls_back(self) -> None:
        provider = _FakeLLMProvider(json.dumps({"title": "X", "sections": []}))
        plan = await plan_song(provider, "topic", target_duration_seconds=30.0)
        assert len(plan.sections) == 1
        assert plan.sections[0].lyrics == "(instrumental)"


# ── detect_beats ────────────────────────────────────────────────────────


class TestDetectBeats:
    def test_returns_empty_when_librosa_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force the import to fail.
        import builtins

        original_import = builtins.__import__

        def _no_librosa(name, *a, **kw):
            if name == "librosa":
                raise ImportError("librosa not installed")
            return original_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", _no_librosa)

        wav = tmp_path / "song.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 1024)
        beats, bpm = detect_beats(wav)
        assert beats == []
        assert bpm == 0.0

    def test_returns_empty_when_file_missing(self) -> None:
        beats, bpm = detect_beats(Path("/no/such/file.wav"))
        assert beats == []
        assert bpm == 0.0


# ── slice_scenes_to_beats ───────────────────────────────────────────────


class TestSliceScenesToBeats:
    def test_no_sections_returns_empty(self) -> None:
        assert slice_scenes_to_beats(beats=[1.0, 2.0], sections=[]) == []

    def test_evenly_spaced_when_no_beats(self) -> None:
        sections = [
            SongSection(
                name="verse",
                lyrics="x",
                duration_seconds=20.0,
                visual_prompt="prompt",
            )
        ]
        slots = slice_scenes_to_beats(beats=[], sections=sections, scenes_per_section=4)
        assert len(slots) == 4
        # 5 s per slot, contiguous.
        assert slots[0] == (0.0, 5.0, "prompt")
        assert slots[3] == (15.0, 20.0, "prompt")

    def test_beat_aligned_when_enough_beats(self) -> None:
        sections = [
            SongSection(
                name="verse",
                lyrics="x",
                duration_seconds=16.0,
                visual_prompt="prompt",
            )
        ]
        # 16 beats spaced 1 s apart inside a 16 s section.
        beats = [float(i) for i in range(16)]
        slots = slice_scenes_to_beats(beats=beats, sections=sections, scenes_per_section=4)
        assert len(slots) == 4
        # Each slot starts on a beat.
        assert slots[0][0] == 0.0
        assert slots[1][0] == 4.0
        assert slots[2][0] == 8.0
        # Last slot must extend to section end.
        assert slots[-1][1] == 16.0

    def test_section_boundary_advances_cursor(self) -> None:
        sections = [
            SongSection(name="intro", lyrics="", duration_seconds=4.0, visual_prompt="A"),
            SongSection(name="verse", lyrics="x", duration_seconds=8.0, visual_prompt="B"),
        ]
        slots = slice_scenes_to_beats(beats=[], sections=sections, scenes_per_section=2)
        # 2 + 2 = 4 slots.
        assert len(slots) == 4
        # Intro slots span [0,2] [2,4]; verse slots span [4,8] [8,12].
        assert slots[0] == (0.0, 2.0, "A")
        assert slots[1] == (2.0, 4.0, "A")
        assert slots[2] == (4.0, 8.0, "B")
        assert slots[3] == (8.0, 12.0, "B")

    def test_scenes_per_section_clamped_to_one(self) -> None:
        sections = [SongSection(name="x", lyrics="", duration_seconds=10.0, visual_prompt="p")]
        slots = slice_scenes_to_beats(beats=[], sections=sections, scenes_per_section=0)
        assert len(slots) == 1


# ── render_song stub ────────────────────────────────────────────────────


class TestRenderSongStub:
    async def test_raises_not_implemented(self, tmp_path: Path) -> None:
        plan = SongStructure(
            title="x",
            artist_persona="y",
            genre="g",
            mood="m",
            key_bpm=("C", 120),
            sections=[],
        )
        with pytest.raises(NotImplementedError):
            await render_song(plan, tmp_path / "out.wav", AsyncMock())


# ── _instrumental_fallback ──────────────────────────────────────────────


class TestInstrumentalFallback:
    def test_single_section_at_target_duration(self) -> None:
        plan = _instrumental_fallback("rainy night", 90.0, "lofi", "melancholy")
        assert len(plan.sections) == 1
        assert plan.sections[0].duration_seconds == 90.0
        assert plan.sections[0].lyrics == "(instrumental)"
        assert "rainy night" in plan.sections[0].visual_prompt
        assert "lofi" in plan.sections[0].visual_prompt

    def test_minimum_15_seconds(self) -> None:
        plan = _instrumental_fallback("topic", 5.0, None, None)
        assert plan.sections[0].duration_seconds == 15.0
