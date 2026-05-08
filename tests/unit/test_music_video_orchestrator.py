"""Tests for the music-video orchestrator (Phase 2a)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from drevalis.services.music_video_orchestrator import MusicVideoOrchestrator

# ── Test doubles ─────────────────────────────────────────────────────────


@dataclass
class _FakeSeries:
    id: UUID
    title: str = "Test Series"
    content_format: str = "music_video"
    target_duration_minutes: int = 1
    music_genre: str | None = "synth-pop"
    music_mood: str | None = "dreamy"
    visual_style: str | None = None
    scenes_per_chapter: int = 4


@dataclass
class _FakeEpisode:
    id: UUID
    series_id: UUID
    series: _FakeSeries
    title: str = "Test episode"
    topic: str | None = "neon city"
    status: str = "draft"
    error_message: str | None = None
    script: dict | None = None


class _FakeEpisodeRepo:
    def __init__(self, episode: _FakeEpisode) -> None:
        self.episode = episode
        self.update_calls: list[dict[str, Any]] = []
        self.status_calls: list[str] = []

    async def get_by_id(self, episode_id: UUID) -> _FakeEpisode | None:
        if episode_id == self.episode.id:
            return self.episode
        return None

    async def update(self, episode_id: UUID, **kwargs) -> _FakeEpisode | None:  # noqa: ARG002, ANN003
        self.update_calls.append(kwargs)
        # The orchestrator's failure path calls ``update(status='failed',
        # error_message=...)`` instead of ``update_status``; mirror that
        # here so the test sees the final status either way.
        if "status" in kwargs:
            self.status_calls.append(kwargs["status"])
        for k, v in kwargs.items():
            setattr(self.episode, k, v)
        return self.episode

    async def update_status(self, episode_id: UUID, status: str) -> None:  # noqa: ARG002
        self.status_calls.append(status)
        self.episode.status = status


@dataclass
class _FakeLLMResult:
    content: str
    model: str = "fake"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class _FakeLLMPool:
    """Stand-in for ``LLMPool`` — exposes a ``generate`` method."""

    def __init__(self, content: str) -> None:
        self.content = content

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> _FakeLLMResult:  # noqa: ARG002
        return _FakeLLMResult(content=self.content)


class _FakeMusicService:
    def __init__(self, music_path: Path | None) -> None:
        self.music_path = music_path
        self.calls: list[tuple[str, float]] = []

    async def get_music_for_episode(
        self, mood: str, target_duration: float, episode_id: UUID
    ) -> Path | None:  # noqa: ARG002
        self.calls.append((mood, target_duration))
        return self.music_path


class _FakeStorage:
    def __init__(self, base: Path) -> None:
        self.base = base

    def resolve_path(self, rel: str) -> Path:
        return self.base / rel


class _RecordingDB:
    """Minimal AsyncSession stand-in — records commits."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _build_orchestrator(
    *,
    tmp_path: Path,
    plan_json: str,
    music_path: Path | None,
    cancel_redis_value: bytes | None = None,
) -> tuple[MusicVideoOrchestrator, _FakeEpisodeRepo, _FakeMusicService]:
    series = _FakeSeries(id=uuid4())
    episode = _FakeEpisode(id=uuid4(), series_id=series.id, series=series)
    repo = _FakeEpisodeRepo(episode)

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cancel_redis_value)
    redis.publish = AsyncMock(return_value=1)
    redis.delete = AsyncMock(return_value=1)

    music = _FakeMusicService(music_path)
    storage = _FakeStorage(tmp_path)

    orch = MusicVideoOrchestrator(
        episode_id=episode.id,
        db_session=_RecordingDB(),  # type: ignore[arg-type]
        redis=redis,
        llm_pool=_FakeLLMPool(plan_json),  # type: ignore[arg-type]
        music_service=music,  # type: ignore[arg-type]
        ffmpeg_service=AsyncMock(),
        storage=storage,  # type: ignore[arg-type]
    )
    # Inject the fake repo so we don't need a real DB for the test.
    orch.episode_repo = repo  # type: ignore[assignment]
    orch.asset_repo = AsyncMock()  # type: ignore[assignment]

    # Stub Phase 2b legs by default. Tests that want to exercise them
    # restore real implementations or replace with their own stubs.
    async def _noop_scenes(*args, **kwargs):  # noqa: ANN001, ANN003
        return []

    async def _noop_captions(*args, **kwargs):  # noqa: ANN001, ANN003
        return None

    async def _noop_assembly(*args, **kwargs):  # noqa: ANN001, ANN003
        from pathlib import Path as _P

        return _P(tmp_path / "video.mp4")

    async def _noop_thumb(*args, **kwargs):  # noqa: ANN001, ANN003
        return None

    orch._run_scenes = _noop_scenes  # type: ignore[assignment]
    orch._run_captions = _noop_captions  # type: ignore[assignment]
    orch._run_assembly = _noop_assembly  # type: ignore[assignment]
    orch._run_thumbnail = _noop_thumb  # type: ignore[assignment]
    return orch, repo, music


# ── Happy path ──────────────────────────────────────────────────────────


_HAPPY_PLAN = json.dumps(
    {
        "title": "Neon Dreams",
        "artist_persona": "Synth-pop duo",
        "genre": "synth-pop",
        "mood": "dreamy",
        "key": "C minor",
        "bpm": 120,
        "sections": [
            {
                "name": "intro",
                "lyrics": "(instrumental)",
                "duration_seconds": 8,
                "visual_prompt": "Wide neon-lit cityscape at dusk",
            },
            {
                "name": "verse1",
                "lyrics": "Walking down the rain",
                "duration_seconds": 22,
                "visual_prompt": "Singer in slow-mo on rainy street",
            },
        ],
    }
)


class TestRunHappyPath:
    async def test_persists_song_plan_to_episode_script(self, tmp_path: Path) -> None:
        # Pre-create a fake "music track" so the copy step succeeds.
        music_src = tmp_path / "library" / "calm" / "track.wav"
        music_src.parent.mkdir(parents=True)
        music_src.write_bytes(b"RIFF" + b"\x00" * 8192)

        orch, repo, music = _build_orchestrator(
            tmp_path=tmp_path,
            plan_json=_HAPPY_PLAN,
            music_path=music_src,
        )
        await orch.run()

        # Episode was set to 'generating' first, then 'review' at the end.
        assert "generating" in repo.status_calls
        assert "review" in repo.status_calls
        assert repo.status_calls[-1] == "review"

        # MusicService called with the song's mood + total duration.
        assert music.calls, "MusicService.get_music_for_episode was not called"
        called_mood, called_duration = music.calls[0]
        assert called_mood == "dreamy"
        assert called_duration == pytest.approx(30.0)  # 8 + 22

        # Persisted script blob has the music_video shape.
        script = repo.episode.script
        assert script is not None
        assert script["kind"] == "music_video"
        mv = script["music_video"]
        assert mv["song"]["title"] == "Neon Dreams"
        assert len(mv["song"]["sections"]) == 2
        assert mv["audio"]["song_path"] == f"episodes/{repo.episode.id}/voice/song.wav"
        # Beat detection might return 0 (librosa not available); both
        # paths should still produce ``scene_slots`` with the right count.
        assert "scene_slots" in mv["audio"]
        assert len(mv["audio"]["scene_slots"]) == 8  # 2 sections × scenes_per_chapter=4

    async def test_episode_title_overwritten_with_song_title(self, tmp_path: Path) -> None:
        music_src = tmp_path / "track.wav"
        music_src.write_bytes(b"RIFF" + b"\x00" * 4096)

        orch, repo, _ = _build_orchestrator(
            tmp_path=tmp_path, plan_json=_HAPPY_PLAN, music_path=music_src
        )
        await orch.run()

        # update() was called with title='Neon Dreams' to match the song.
        title_updates = [c for c in repo.update_calls if "title" in c]
        assert title_updates, "title was never updated"
        assert title_updates[-1]["title"] == "Neon Dreams"

    async def test_song_copied_into_episode_voice_dir(self, tmp_path: Path) -> None:
        music_src = tmp_path / "library" / "track.wav"
        music_src.parent.mkdir(parents=True)
        music_src.write_bytes(b"RIFF" + b"\x00" * 8192)

        orch, repo, _ = _build_orchestrator(
            tmp_path=tmp_path, plan_json=_HAPPY_PLAN, music_path=music_src
        )
        await orch.run()

        # Episode-scoped path exists.
        target = tmp_path / "episodes" / str(repo.episode.id) / "voice" / "song.wav"
        assert target.exists(), f"song.wav was not copied to {target}"


# ── Failure paths ────────────────────────────────────────────────────────


class TestFailurePaths:
    async def test_no_music_resolved_marks_failed(self, tmp_path: Path) -> None:
        orch, repo, _ = _build_orchestrator(
            tmp_path=tmp_path, plan_json=_HAPPY_PLAN, music_path=None
        )
        with pytest.raises(RuntimeError, match="Music backing track"):
            await orch.run()
        assert repo.status_calls[-1] == "failed"
        assert repo.episode.error_message is not None

    async def test_cancel_flag_aborts_run(self, tmp_path: Path) -> None:
        import asyncio

        music_src = tmp_path / "track.wav"
        music_src.write_bytes(b"RIFF" + b"\x00" * 4096)

        orch, repo, _ = _build_orchestrator(
            tmp_path=tmp_path,
            plan_json=_HAPPY_PLAN,
            music_path=music_src,
            cancel_redis_value=b"1",
        )
        with pytest.raises(asyncio.CancelledError):
            await orch.run()
        assert repo.status_calls[-1] == "failed"

    async def test_phase_2b_runs_when_comfyui_and_captions_provided(self, tmp_path: Path) -> None:
        """When comfyui_service + caption_service are wired the
        orchestrator goes all the way through SCENES + CAPTIONS +
        ASSEMBLY + THUMBNAIL and ends in review."""
        music_src = tmp_path / "track.wav"
        music_src.write_bytes(b"RIFF" + b"\x00" * 4096)

        # Build the orchestrator the usual way then bolt on Phase 2b
        # stubs that record their calls.
        orch, repo, _ = _build_orchestrator(
            tmp_path=tmp_path, plan_json=_HAPPY_PLAN, music_path=music_src
        )

        # Stub _run_scenes / _run_captions / _run_assembly / _run_thumbnail
        # at the orchestrator layer — Phase 2b call sites are exercised
        # but their real bodies (which need ComfyUI + ffmpeg) are
        # bypassed. This test checks the wiring + status transitions.
        from typing import Any as _Any
        from unittest.mock import AsyncMock as _AM

        called = {"scenes": False, "captions": False, "assembly": False, "thumb": False}

        async def _scenes(plan, audio_meta, series) -> list[_Any]:  # noqa: ARG001, ANN001
            called["scenes"] = True
            return []

        async def _captions(plan, audio_meta):  # noqa: ARG001, ANN001
            called["captions"] = True
            return None

        async def _assembly(plan, audio_meta, generated_images, captions_path):  # noqa: ARG001, ANN001
            called["assembly"] = True
            from pathlib import Path as _P

            return _P(tmp_path / "video.mp4")

        async def _thumbnail(generated_images):  # noqa: ARG001, ANN001
            called["thumb"] = True
            return None

        orch._run_scenes = _scenes  # type: ignore[assignment]
        orch._run_captions = _captions  # type: ignore[assignment]
        orch._run_assembly = _assembly  # type: ignore[assignment]
        orch._run_thumbnail = _thumbnail  # type: ignore[assignment]
        # Indicate Phase 2b deps are present so the orchestrator
        # doesn't think they're missing.
        orch.comfyui_service = _AM()
        orch.caption_service = _AM()

        await orch.run()

        assert called["scenes"]
        assert called["captions"]
        assert called["assembly"]
        assert called["thumb"]
        assert repo.status_calls[-1] == "review"

    async def test_phase_2b_assembly_failure_marks_failed(self, tmp_path: Path) -> None:
        music_src = tmp_path / "track.wav"
        music_src.write_bytes(b"RIFF" + b"\x00" * 4096)

        orch, repo, _ = _build_orchestrator(
            tmp_path=tmp_path, plan_json=_HAPPY_PLAN, music_path=music_src
        )
        from unittest.mock import AsyncMock as _AM

        async def _scenes(plan, audio_meta, series) -> list:  # noqa: ARG001, ANN001
            return []

        async def _captions(plan, audio_meta):  # noqa: ARG001, ANN001
            return None

        async def _assembly_fail(plan, audio_meta, gen, captions):  # noqa: ARG001, ANN001
            raise RuntimeError("ffmpeg fell over")

        orch._run_scenes = _scenes  # type: ignore[assignment]
        orch._run_captions = _captions  # type: ignore[assignment]
        orch._run_assembly = _assembly_fail  # type: ignore[assignment]
        orch.comfyui_service = _AM()
        orch.caption_service = _AM()

        with pytest.raises(RuntimeError, match="ffmpeg fell over"):
            await orch.run()

        assert repo.status_calls[-1] == "failed"

    async def test_select_workflow_prefers_music_video_then_longform(self, tmp_path: Path) -> None:
        """``_select_workflow`` ranks music_video > longform > shorts > any."""
        music_src = tmp_path / "track.wav"
        music_src.write_bytes(b"RIFF" + b"\x00" * 4096)
        orch, _, _ = _build_orchestrator(
            tmp_path=tmp_path, plan_json=_HAPPY_PLAN, music_path=music_src
        )

        @dataclass
        class _WF:
            name: str
            content_format: str
            input_mappings: dict
            workflow_json_path: str = "workflows/x.json"

        # Stub the workflow repo lookup to return three workflows in
        # arbitrary order; we should get back the music_video one.
        async def _fake_get_all(limit: int = 20):  # noqa: ARG001
            return [
                _WF(
                    name="shorts_qwen",
                    content_format="shorts",
                    input_mappings={"output_field_name": "images"},
                ),
                _WF(
                    name="music_video_v1",
                    content_format="music_video",
                    input_mappings={"output_field_name": "images"},
                ),
                _WF(
                    name="longform_wan",
                    content_format="longform",
                    input_mappings={"output_field_name": "images"},
                ),
            ]

        from drevalis.repositories import comfyui as _comfyui_repo_mod

        # Patch the repo so the orchestrator's lookup returns the test
        # workflows instead of hitting the DB.
        original = _comfyui_repo_mod.ComfyUIWorkflowRepository.get_all

        async def _patched(self, limit: int = 20):  # noqa: ARG001, ARG002
            return await _fake_get_all(limit)

        _comfyui_repo_mod.ComfyUIWorkflowRepository.get_all = _patched  # type: ignore[method-assign]
        try:
            chosen = await orch._select_workflow()
            assert chosen is not None
            assert chosen.name == "music_video_v1"
        finally:
            _comfyui_repo_mod.ComfyUIWorkflowRepository.get_all = original  # type: ignore[method-assign]

    async def test_llm_garbage_falls_back_to_instrumental(self, tmp_path: Path) -> None:
        music_src = tmp_path / "track.wav"
        music_src.write_bytes(b"RIFF" + b"\x00" * 4096)

        orch, repo, _ = _build_orchestrator(
            tmp_path=tmp_path, plan_json="not json at all", music_path=music_src
        )
        await orch.run()
        # Fallback plan has 1 section with lyrics "(instrumental)" —
        # the orchestrator still progresses to 'review' rather than
        # crashing.
        assert repo.status_calls[-1] == "review"
        script = repo.episode.script
        assert script["music_video"]["song"]["sections"][0]["lyrics"] == "(instrumental)"
