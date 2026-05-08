"""Tests for `workers/jobs/video_ingest.py` — analyze + commit
orchestration.

Pin:

* `analyze_video_ingest`:
  - Job not found → `{"status": "not_found"}` (NOT raise — operator
    deleted it).
  - Asset missing or wrong kind → `_fail` invoked with reason +
    `failed` status returned.
  - Source file not on disk → `_fail` invoked.
  - ffmpeg audio extract non-zero exit → `_fail` invoked.
  - Happy path: progress updates flow through stages
    (transcribing → audio_extracted → analyzing → done) and the
    candidate_clips field is populated.
  - No LLM configured → naive fallback used.
* `commit_video_ingest_clip`:
  - Job not in `done` status → ValueError.
  - clip_index out of range → ValueError.
  - Source asset gone → ValueError.
  - Happy path: creates draft Episode with single-scene script
    windowed to the chosen clip's `[start_s, end_s]` range and
    updates the ingest job with `selected_clip_index`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from drevalis.workers.jobs.video_ingest import (
    analyze_video_ingest,
    commit_video_ingest_clip,
)


def _settings(tmp_path: Path) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    s.ffmpeg_path = "ffmpeg"
    return s


def _ctx_with_session(session: Any, ffmpeg_returncode: int = 0) -> dict[str, Any]:
    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    caption_svc = MagicMock()
    caption_svc._transcribe = MagicMock(
        return_value=[
            SimpleNamespace(word="hello", start_seconds=0.0, end_seconds=0.5),
            SimpleNamespace(word="world", start_seconds=0.6, end_seconds=1.2),
        ]
    )
    return {
        "session_factory": _sf,
        "caption_service": caption_svc,
        "llm_service": MagicMock(),
    }


def _make_job(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "asset_id": uuid4(),
        "status": "queued",
        "stage": "queued",
        "progress_pct": 0,
        "transcript": None,
        "candidate_clips": None,
        "selected_clip_index": None,
        "resulting_episode_id": None,
        "error_message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_asset(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "kind": "video",
        "file_path": "uploads/v.mp4",
        "duration_seconds": 300.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── analyze_video_ingest ──────────────────────────────────────────


class TestAnalyzeVideoIngestSafetyBranches:
    async def test_job_not_found_returns_status(self, tmp_path: Path) -> None:
        session = AsyncMock()
        session.commit = AsyncMock()

        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=None)
        asset_repo = MagicMock()
        llm_repo = MagicMock()

        with (
            patch(
                "drevalis.repositories.asset.VideoIngestJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.asset.AssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(tmp_path),
            ),
        ):
            out = await analyze_video_ingest(
                _ctx_with_session(session),
                str(uuid4()),
            )
        assert out == {"status": "not_found"}

    async def test_asset_missing_marks_failed(self, tmp_path: Path) -> None:
        session = AsyncMock()
        session.commit = AsyncMock()

        job = _make_job()
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)
        job_repo.update = AsyncMock()
        asset_repo = MagicMock()
        asset_repo.get_by_id = AsyncMock(return_value=None)
        llm_repo = MagicMock()

        with (
            patch(
                "drevalis.repositories.asset.VideoIngestJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.asset.AssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(tmp_path),
            ),
        ):
            out = await analyze_video_ingest(_ctx_with_session(session), str(job.id))
        assert out == {"status": "failed", "error": "source_asset_missing"}
        # _fail was invoked → update with status=failed.
        update_calls = [
            c for c in job_repo.update.await_args_list if c.kwargs.get("status") == "failed"
        ]
        assert update_calls

    async def test_wrong_asset_kind_marks_failed(self, tmp_path: Path) -> None:
        session = AsyncMock()
        session.commit = AsyncMock()

        job = _make_job()
        asset = _make_asset(kind="image")  # not a video
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)
        job_repo.update = AsyncMock()
        asset_repo = MagicMock()
        asset_repo.get_by_id = AsyncMock(return_value=asset)
        llm_repo = MagicMock()

        with (
            patch(
                "drevalis.repositories.asset.VideoIngestJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.asset.AssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(tmp_path),
            ),
        ):
            out = await analyze_video_ingest(_ctx_with_session(session), str(job.id))
        assert out["status"] == "failed"
        assert out["error"] == "source_asset_missing"

    async def test_source_file_missing_on_disk_marks_failed(self, tmp_path: Path) -> None:
        session = AsyncMock()
        session.commit = AsyncMock()

        job = _make_job()
        # Asset row points at a path that doesn't exist.
        asset = _make_asset(file_path="missing.mp4")
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)
        job_repo.update = AsyncMock()
        asset_repo = MagicMock()
        asset_repo.get_by_id = AsyncMock(return_value=asset)
        llm_repo = MagicMock()

        with (
            patch(
                "drevalis.repositories.asset.VideoIngestJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.asset.AssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(tmp_path),
            ),
        ):
            out = await analyze_video_ingest(_ctx_with_session(session), str(job.id))
        assert out["error"] == "source_file_missing"

    async def test_ffmpeg_extract_failure_marks_failed(self, tmp_path: Path) -> None:
        # Stage a real source file so we get past the file-existence
        # guard and reach the ffmpeg extraction.
        src = tmp_path / "v.mp4"
        src.write_bytes(b"\x00")

        session = AsyncMock()
        session.commit = AsyncMock()

        job = _make_job()
        asset = _make_asset(file_path="v.mp4")
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)
        job_repo.update = AsyncMock()
        asset_repo = MagicMock()
        asset_repo.get_by_id = AsyncMock(return_value=asset)
        llm_repo = MagicMock()

        # ffmpeg returns non-zero — and even if it returned 0, the
        # output file wouldn't exist (we don't run it for real). The
        # route checks BOTH conditions.
        async def _fake_extract(*_args: Any) -> int:
            return 1

        with (
            patch(
                "drevalis.repositories.asset.VideoIngestJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.asset.AssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(tmp_path),
            ),
            patch(
                "drevalis.workers.jobs.video_ingest._ffmpeg_extract_audio",
                _fake_extract,
            ),
        ):
            out = await analyze_video_ingest(_ctx_with_session(session), str(job.id))
        assert out["error"] == "ffmpeg_failed"


class TestAnalyzeVideoIngestHappyPath:
    async def test_no_llm_configured_falls_back_to_naive(self, tmp_path: Path) -> None:
        # Real source file + ffmpeg "succeeds" + the .whisper.wav file
        # gets created → caption_svc transcribes → naive_candidates
        # picks (no LLM configured).
        src = tmp_path / "v.mp4"
        src.write_bytes(b"\x00")

        session = AsyncMock()
        session.commit = AsyncMock()

        job = _make_job()
        asset = _make_asset(file_path="v.mp4", duration_seconds=120.0)
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)
        job_repo.update = AsyncMock()
        asset_repo = MagicMock()
        asset_repo.get_by_id = AsyncMock(return_value=asset)
        llm_repo = MagicMock()
        llm_repo.get_all = AsyncMock(return_value=[])  # no LLM

        # Stub the audio extract to succeed AND create the output file.
        async def _fake_extract(_src: Path, dst: Path) -> int:
            dst.write_bytes(b"\x00")
            return 0

        with (
            patch(
                "drevalis.repositories.asset.VideoIngestJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.asset.AssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(tmp_path),
            ),
            patch(
                "drevalis.workers.jobs.video_ingest._ffmpeg_extract_audio",
                _fake_extract,
            ),
        ):
            out = await analyze_video_ingest(_ctx_with_session(session), str(job.id))
        assert out["status"] == "done"
        # The final update marks done + populates candidate_clips.
        final_call = job_repo.update.await_args_list[-1]
        assert final_call.kwargs["status"] == "done"
        assert final_call.kwargs["progress_pct"] == 100
        # 120 s of audio fits exactly two windows (45 s each) → naive
        # picker returned at least one clip.
        assert len(final_call.kwargs["candidate_clips"]) >= 1

    async def test_with_llm_uses_llm_pick(self, tmp_path: Path) -> None:
        src = tmp_path / "v.mp4"
        src.write_bytes(b"\x00")

        session = AsyncMock()
        session.commit = AsyncMock()

        job = _make_job()
        asset = _make_asset(file_path="v.mp4", duration_seconds=300.0)
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)
        job_repo.update = AsyncMock()
        asset_repo = MagicMock()
        asset_repo.get_by_id = AsyncMock(return_value=asset)
        llm_repo = MagicMock()
        cfg = SimpleNamespace(id=uuid4(), name="lm")
        llm_repo.get_all = AsyncMock(return_value=[cfg])

        async def _fake_extract(_src: Path, dst: Path) -> int:
            dst.write_bytes(b"\x00")
            return 0

        async def _fake_pick(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            return [
                {
                    "start_s": 0.0,
                    "end_s": 30.0,
                    "title": "LLM clip",
                    "reason": "best moment",
                    "score": 0.9,
                }
            ]

        with (
            patch(
                "drevalis.repositories.asset.VideoIngestJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.asset.AssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.llm_config.LLMConfigRepository",
                return_value=llm_repo,
            ),
            patch(
                "drevalis.core.deps.get_settings",
                return_value=_settings(tmp_path),
            ),
            patch(
                "drevalis.workers.jobs.video_ingest._ffmpeg_extract_audio",
                _fake_extract,
            ),
            patch(
                "drevalis.workers.jobs.video_ingest._llm_pick",
                _fake_pick,
            ),
        ):
            out = await analyze_video_ingest(_ctx_with_session(session), str(job.id))
        assert out["status"] == "done"
        assert out["candidates"] == 1
        final_call = job_repo.update.await_args_list[-1]
        assert final_call.kwargs["candidate_clips"][0]["title"] == "LLM clip"


# ── commit_video_ingest_clip ──────────────────────────────────────


class TestCommitVideoIngestClip:
    async def test_job_not_done_raises(self) -> None:
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = {"session_factory": _sf}

        job = _make_job(status="running")
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)

        with patch(
            "drevalis.repositories.asset.VideoIngestJobRepository",
            return_value=job_repo,
        ):
            with pytest.raises(ValueError, match="not ready"):
                await commit_video_ingest_clip(ctx, str(job.id), 0, str(uuid4()))

    async def test_clip_index_out_of_range_raises(self) -> None:
        session = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = {"session_factory": _sf}

        job = _make_job(
            status="done",
            candidate_clips=[
                {"start_s": 0, "end_s": 30, "title": "c1"},
            ],
        )
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)

        with patch(
            "drevalis.repositories.asset.VideoIngestJobRepository",
            return_value=job_repo,
        ):
            with pytest.raises(ValueError, match="out of range"):
                await commit_video_ingest_clip(ctx, str(job.id), 99, str(uuid4()))

    async def test_negative_clip_index_raises(self) -> None:
        session = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = {"session_factory": _sf}

        job = _make_job(
            status="done",
            candidate_clips=[
                {"start_s": 0, "end_s": 30, "title": "c1"},
            ],
        )
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)

        with patch(
            "drevalis.repositories.asset.VideoIngestJobRepository",
            return_value=job_repo,
        ):
            with pytest.raises(ValueError, match="out of range"):
                await commit_video_ingest_clip(ctx, str(job.id), -1, str(uuid4()))

    async def test_asset_disappeared_raises(self) -> None:
        session = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = {"session_factory": _sf}

        job = _make_job(
            status="done",
            candidate_clips=[
                {"start_s": 0, "end_s": 30, "title": "c1"},
            ],
        )
        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)
        asset_repo = MagicMock()
        asset_repo.get_by_id = AsyncMock(return_value=None)

        with (
            patch(
                "drevalis.repositories.asset.VideoIngestJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.asset.AssetRepository",
                return_value=asset_repo,
            ),
        ):
            with pytest.raises(ValueError, match="asset disappeared"):
                await commit_video_ingest_clip(ctx, str(job.id), 0, str(uuid4()))

    async def test_happy_path_creates_episode_and_updates_job(self) -> None:
        session = AsyncMock()
        session.commit = AsyncMock()

        @asynccontextmanager
        async def _sf() -> Any:
            yield session

        ctx = {"session_factory": _sf}

        job = _make_job(
            status="done",
            candidate_clips=[
                {
                    "start_s": 10.0,
                    "end_s": 40.0,
                    "title": "Best moment",
                    "reason": "high energy",
                    "score": 0.9,
                }
            ],
        )
        asset = _make_asset()

        job_repo = MagicMock()
        job_repo.get_by_id = AsyncMock(return_value=job)
        job_repo.update = AsyncMock()
        asset_repo = MagicMock()
        asset_repo.get_by_id = AsyncMock(return_value=asset)
        ep_repo = MagicMock()
        new_ep = SimpleNamespace(id=uuid4())
        ep_repo.create = AsyncMock(return_value=new_ep)

        sid = str(uuid4())
        with (
            patch(
                "drevalis.repositories.asset.VideoIngestJobRepository",
                return_value=job_repo,
            ),
            patch(
                "drevalis.repositories.asset.AssetRepository",
                return_value=asset_repo,
            ),
            patch(
                "drevalis.repositories.episode.EpisodeRepository",
                return_value=ep_repo,
            ),
        ):
            out = await commit_video_ingest_clip(ctx, str(job.id), 0, sid)
        assert out["episode_id"] == str(new_ep.id)
        # Episode created with single-scene script windowed to clip.
        ep_repo.create.assert_awaited_once()
        kwargs = ep_repo.create.call_args.kwargs
        assert kwargs["title"] == "Best moment"
        assert kwargs["topic"] == "high energy"
        assert kwargs["status"] == "review"
        scene = kwargs["script"]["scenes"][0]
        assert scene["clip_start_s"] == 10.0
        assert scene["clip_end_s"] == 40.0
        # duration_seconds = end - start = 30.0
        assert scene["duration_seconds"] == 30.0
        # Job updated with selected_clip_index + resulting_episode_id.
        job_repo.update.assert_awaited_once()
        update_kwargs = job_repo.update.call_args.kwargs
        assert update_kwargs["selected_clip_index"] == 0
        assert update_kwargs["resulting_episode_id"] == new_ep.id
