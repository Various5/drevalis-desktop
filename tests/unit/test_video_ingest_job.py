"""Tests for the video-ingest analysis worker
(``workers/jobs/video_ingest.py``).

Heavy worker that drives ffmpeg → faster-whisper → LLM. Unit tests
pin the early-exit branches that handle missing inputs:

* Job row missing → not_found
* Asset row missing or wrong kind → failed
* Source file not on disk → failed
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.video_ingest import analyze_video_ingest

# ── Helpers ──────────────────────────────────────────────────────────


def _make_session_factory(session_mock: Any) -> Any:
    class _SF:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return session_mock

        async def __aexit__(self, *_a: Any) -> None:
            return None

    return _SF()


def _make_settings(*, storage_base: str = "/tmp/storage") -> Any:
    s = MagicMock()
    s.storage_base_path = storage_base
    return s


def _patch_repos(
    *,
    job: Any,
    asset: Any,
    llm_config: Any | None = None,
) -> Any:
    job_repo = MagicMock()
    job_repo.get_by_id = AsyncMock(return_value=job)
    job_repo.update = AsyncMock()
    asset_repo = MagicMock()
    asset_repo.get_by_id = AsyncMock(return_value=asset)
    llm_repo = MagicMock()
    llm_repo.get_by_id = AsyncMock(return_value=llm_config)

    from contextlib import ExitStack

    es = ExitStack()
    es.enter_context(
        patch(
            "drevalis.repositories.asset.VideoIngestJobRepository",
            return_value=job_repo,
        )
    )
    es.enter_context(patch("drevalis.repositories.asset.AssetRepository", return_value=asset_repo))
    es.enter_context(
        patch(
            "drevalis.repositories.llm_config.LLMConfigRepository",
            return_value=llm_repo,
        )
    )
    es.enter_context(patch("drevalis.core.deps.get_settings", return_value=_make_settings()))
    return es, job_repo


# ── not_found path ──────────────────────────────────────────────────


class TestJobNotFound:
    async def test_returns_not_found_when_job_row_missing(self) -> None:
        # Worker dequeued a job_id but the row was deleted in the
        # meantime (operator hit "Cancel" + "Delete" on the
        # ingest-jobs page). Don't crash — return early.
        session = AsyncMock()
        sf = _make_session_factory(session)
        es, _ = _patch_repos(job=None, asset=None)
        with es:
            result = await analyze_video_ingest({"session_factory": sf}, str(uuid4()))
        assert result == {"status": "not_found"}


# ── source_asset_missing path ───────────────────────────────────────


class TestSourceAssetMissing:
    async def test_returns_failed_when_asset_row_missing(self) -> None:
        job = MagicMock()
        job.id = uuid4()
        job.asset_id = uuid4()
        session = AsyncMock()
        session.commit = AsyncMock()
        sf = _make_session_factory(session)
        es, job_repo = _patch_repos(job=job, asset=None)
        with es:
            result = await analyze_video_ingest({"session_factory": sf}, str(uuid4()))
        assert result == {"status": "failed", "error": "source_asset_missing"}
        # Job marked failed via ``_fail`` helper.
        update_calls = job_repo.update.call_args_list
        assert any((c.kwargs.get("status") == "failed") for c in update_calls)

    async def test_returns_failed_when_asset_kind_is_not_video(self) -> None:
        # Edge case: someone uploaded an audio file then queued an
        # ingest job — the kind check rejects.
        job = MagicMock()
        job.id = uuid4()
        job.asset_id = uuid4()
        asset = MagicMock()
        asset.kind = "audio"
        asset.file_path = "x.mp3"
        session = AsyncMock()
        session.commit = AsyncMock()
        sf = _make_session_factory(session)
        es, _ = _patch_repos(job=job, asset=asset)
        with es:
            result = await analyze_video_ingest({"session_factory": sf}, str(uuid4()))
        assert result == {"status": "failed", "error": "source_asset_missing"}


# ── source_file_missing path ────────────────────────────────────────


class TestSourceFileMissing:
    async def test_returns_failed_when_file_not_on_disk(self) -> None:
        # Asset row exists, kind=video, but the underlying file was
        # deleted off disk (storage volume swapped, manual cleanup).
        # Surface the failure with a clear error code.
        job = MagicMock()
        job.id = uuid4()
        job.asset_id = uuid4()
        asset = MagicMock()
        asset.kind = "video"
        asset.file_path = "ghost-file.mp4"
        session = AsyncMock()
        session.commit = AsyncMock()
        sf = _make_session_factory(session)
        es, job_repo = _patch_repos(job=job, asset=asset)
        with es:
            result = await analyze_video_ingest({"session_factory": sf}, str(uuid4()))
        assert result == {"status": "failed", "error": "source_file_missing"}
        # Job marked failed.
        assert any((c.kwargs.get("status") == "failed") for c in job_repo.update.call_args_list)
