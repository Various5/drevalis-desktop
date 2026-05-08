"""Tests for ``api/routes/video_ingest.py``.

Three thin endpoints over ``VideoIngestService``. Pin the contract:
non-video uploads → 400; ``ValidationError`` from the service → 400;
``NotFoundError`` from the get → 404; pick endpoint surfaces validation
errors so the UI can show "clip already taken" etc.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from drevalis.api.routes.video_ingest import (
    PickRequest,
    _service,
    get_video_ingest_job,
    pick_video_ingest_clip,
    start_video_ingest,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.services.video_ingest import VideoIngestService


def _fake_upload(content_type: str = "video/mp4", filename: str = "v.mp4") -> Any:
    f = MagicMock(spec=UploadFile)
    f.content_type = content_type
    f.filename = filename
    f.read = AsyncMock(return_value=b"\x00" * 100)
    return f


def _make_job(**overrides: Any) -> Any:
    j = MagicMock()
    j.id = overrides.get("id", uuid4())
    j.asset_id = overrides.get("asset_id", uuid4())
    j.status = overrides.get("status", "queued")
    j.stage = overrides.get("stage")
    j.progress_pct = overrides.get("progress_pct", 0)
    j.candidate_clips = overrides.get("candidate_clips")
    j.selected_clip_index = overrides.get("selected_clip_index")
    j.resulting_episode_id = overrides.get("resulting_episode_id")
    j.error_message = overrides.get("error_message")
    return j


# ── _service factory ────────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_service_bound_to_session_and_path(self) -> None:
        db = AsyncMock()
        settings = MagicMock()
        settings.storage_base_path = MagicMock()
        svc = _service(db=db, settings=settings)
        assert isinstance(svc, VideoIngestService)


# ── POST /api/v1/video-ingest ───────────────────────────────────────


class TestStartVideoIngest:
    async def test_non_video_upload_rejected(self) -> None:
        svc = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await start_video_ingest(
                file=_fake_upload(content_type="image/png"),
                description=None,
                svc=svc,
            )
        assert exc.value.status_code == 400

    async def test_no_content_type_rejected(self) -> None:
        # Some browsers / curl invocations send no Content-Type at all —
        # router must default to "" and reject (rather than blow up on
        # ``None.startswith``).
        svc = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await start_video_ingest(
                file=_fake_upload(content_type=None),  # type: ignore[arg-type]
                description=None,
                svc=svc,
            )
        assert exc.value.status_code == 400

    async def test_success_returns_job_response(self) -> None:
        svc = MagicMock()
        job = _make_job()
        svc.upload_and_enqueue = AsyncMock(return_value=job)
        out = await start_video_ingest(
            file=_fake_upload(),
            description="rough cut",
            svc=svc,
        )
        assert out.id == job.id
        assert out.status == "queued"
        # The candidate_clips field is None at enqueue time.
        assert out.candidate_clips is None

    async def test_validation_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.upload_and_enqueue = AsyncMock(side_effect=ValidationError("file too large"))
        with pytest.raises(HTTPException) as exc:
            await start_video_ingest(
                file=_fake_upload(),
                description=None,
                svc=svc,
            )
        assert exc.value.status_code == 400


# ── GET /api/v1/video-ingest/{id} ──────────────────────────────────


class TestGetVideoIngestJob:
    async def test_returns_job_with_clips(self) -> None:
        svc = MagicMock()
        job = _make_job(
            status="done",
            stage="analyzed",
            progress_pct=100,
            candidate_clips=[
                {
                    "start_s": 0.0,
                    "end_s": 12.0,
                    "title": "Hook",
                    "reason": "high energy",
                    "score": 0.91,
                }
            ],
        )
        svc.get_job = AsyncMock(return_value=job)
        out = await get_video_ingest_job(job.id, svc=svc)
        assert out.status == "done"
        assert out.candidate_clips is not None
        assert len(out.candidate_clips) == 1
        assert out.candidate_clips[0].score == 0.91

    async def test_not_found_maps_to_404(self) -> None:
        svc = MagicMock()
        svc.get_job = AsyncMock(side_effect=NotFoundError("video_ingest_job", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_video_ingest_job(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_handles_empty_candidate_clips(self) -> None:
        # Job in 'queued' state — candidate_clips is None, NOT an
        # empty list. Router must coerce to [] without crashing.
        svc = MagicMock()
        job = _make_job(candidate_clips=None)
        svc.get_job = AsyncMock(return_value=job)
        out = await get_video_ingest_job(job.id, svc=svc)
        assert out.candidate_clips == []


# ── POST /api/v1/video-ingest/{id}/pick ────────────────────────────


class TestPickClip:
    async def test_success_returns_enqueued(self) -> None:
        svc = MagicMock()
        svc.pick_clip = AsyncMock()
        out = await pick_video_ingest_clip(
            uuid4(),
            PickRequest(clip_index=0, series_id=uuid4()),
            svc=svc,
        )
        assert out == {"status": "enqueued"}

    async def test_validation_error_maps_to_400(self) -> None:
        svc = MagicMock()
        svc.pick_clip = AsyncMock(side_effect=ValidationError("clip_index out of range"))
        with pytest.raises(HTTPException) as exc:
            await pick_video_ingest_clip(
                uuid4(),
                PickRequest(clip_index=99, series_id=uuid4()),
                svc=svc,
            )
        assert exc.value.status_code == 400
