"""Tests for ``api/routes/audiobooks/_monolith.py`` (CRUD + simple
generation control).

Pin the layered status mapping the audiobooks UI depends on:

* ``NotFoundError`` → 404 across get/update/delete/regen/cancel.
* ``ValidationError`` → 422 on update / regenerate-chapter
  / regenerate-image; → 400 on `/create-ai`.
* `cancel` returns a different message when the audiobook isn't
  generating (no cancel signal sent).
* `upload_cover_image` rejects non-image content_type → 422,
  oversize → 413, invalid image bytes → 422 (Pillow `verify()`
  fails); writes the unique-name file to `audiobooks/covers/`.
"""

from __future__ import annotations

import io
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from drevalis.api.routes.audiobooks._monolith import (
    AudiobookAICreateRequest,
    AudiobookScriptRequest,
    AudiobookTextUpdate,
    ChapterImageRegeneratePayload,
    ChapterRegeneratePayload,
    TrackMixPayload,
    _service,
    cancel_audiobook,
    cancel_script_job,
    create_ai_audiobook,
    create_audiobook,
    delete_audiobook,
    generate_audiobook_script,
    get_audiobook,
    get_script_job,
    list_audiobooks,
    regenerate_audiobook,
    regenerate_chapter,
    regenerate_chapter_image,
    remix_audiobook,
    update_audiobook,
    update_audiobook_text,
    update_audiobook_voices,
    upload_cover_image,
)
from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.schemas.audiobook import AudiobookCreate, AudiobookUpdate
from drevalis.services.audiobook_admin import AudiobookAdminService


def _settings(tmp_path: Any = None) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    s.lm_studio_base_url = "http://localhost:1234/v1"
    s.lm_studio_default_model = "local-model"
    return s


def _make_ab(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "title": "Title",
        "text": "Some text",
        "voice_profile_id": uuid4(),
        "status": "generating",
        "output_format": "audio_only",
        "cover_image_path": None,
        "chapters": None,
        "voice_casting": None,
        "music_enabled": False,
        "music_mood": None,
        "music_volume_db": -14.0,
        "speed": 1.0,
        "pitch": 1.0,
        "audio_path": None,
        "video_path": None,
        "mp3_path": None,
        "duration_seconds": None,
        "file_size_bytes": None,
        "error_message": None,
        "background_image_path": None,
        "video_orientation": "landscape",
        "caption_style_preset": None,
        "image_generation_enabled": False,
        "youtube_channel_id": None,
        "track_mix": None,
        "settings_json": None,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_create() -> AudiobookCreate:
    return AudiobookCreate(
        title="Test",
        text="The quick brown fox.",
        voice_profile_id=uuid4(),
    )


# ── _service factory ───────────────────────────────────────────────


class TestServiceFactory:
    def test_returns_admin_service(self, tmp_path: Any) -> None:
        svc = _service(db=AsyncMock(), settings=_settings(tmp_path))
        assert isinstance(svc, AudiobookAdminService)


# ── POST /generate-script (async) ──────────────────────────────────


class TestGenerateScript:
    async def test_returns_job_id_and_generating(self) -> None:
        svc = MagicMock()
        svc.enqueue_script_job = AsyncMock(return_value="job-abc")
        out = await generate_audiobook_script(
            AudiobookScriptRequest(
                concept="A short fantasy tale about a dragon",
                target_minutes=5,
            ),
            svc=svc,
        )
        assert out.job_id == "job-abc"
        assert out.status == "generating"


# ── GET /script-job/{id} ───────────────────────────────────────────


class TestGetScriptJob:
    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get_script_job = AsyncMock(side_effect=NotFoundError("script_job", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_script_job("missing", svc=svc)
        assert exc.value.status_code == 404

    async def test_generating_returns_status_with_no_result(self) -> None:
        svc = MagicMock()
        svc.get_script_job = AsyncMock(
            return_value={"status": "generating", "result": None, "error": None}
        )
        out = await get_script_job("abc", svc=svc)
        assert out.status == "generating"
        assert out.result is None
        assert out.error is None

    async def test_done_parses_result(self) -> None:
        svc = MagicMock()
        svc.get_script_job = AsyncMock(
            return_value={
                "status": "done",
                "result": {
                    "title": "Dragons",
                    "script": "[Narrator] Once upon a time...",
                    "characters": ["Narrator"],
                    "chapters": ["Chapter 1"],
                    "word_count": 10,
                    "estimated_minutes": 0.07,
                },
                "error": None,
            }
        )
        out = await get_script_job("abc", svc=svc)
        assert out.status == "done"
        assert out.result is not None
        assert out.result.title == "Dragons"

    async def test_failed_surfaces_error(self) -> None:
        svc = MagicMock()
        svc.get_script_job = AsyncMock(
            return_value={
                "status": "failed",
                "result": None,
                "error": "LLM timed out",
            }
        )
        out = await get_script_job("abc", svc=svc)
        assert out.error == "LLM timed out"


# ── POST /script-job/{id}/cancel ───────────────────────────────────


class TestCancelScriptJob:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.cancel_script_job = AsyncMock()
        out = await cancel_script_job("abc", svc=svc)
        assert out["message"] == "Cancelled"

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.cancel_script_job = AsyncMock(side_effect=NotFoundError("script_job", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await cancel_script_job("nope", svc=svc)
        assert exc.value.status_code == 404


# ── POST /create-ai ────────────────────────────────────────────────


class TestCreateAI:
    async def test_success_returns_id_and_status(self) -> None:
        svc = MagicMock()
        ab = _make_ab(title="Dragon Tale")
        svc.create_ai = AsyncMock(return_value=ab)
        out = await create_ai_audiobook(
            AudiobookAICreateRequest(concept="A dragon adventure tale"),
            svc=svc,
        )
        assert out["audiobook_id"] == str(ab.id)
        assert out["status"] == "generating"
        assert out["title"] == "Dragon Tale"

    async def test_validation_400(self) -> None:
        svc = MagicMock()
        svc.create_ai = AsyncMock(side_effect=ValidationError("LLM not configured"))
        with pytest.raises(HTTPException) as exc:
            await create_ai_audiobook(
                AudiobookAICreateRequest(concept="A dragon adventure tale"),
                svc=svc,
            )
        assert exc.value.status_code == 400

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.create_ai = AsyncMock(side_effect=NotFoundError("voice_profile", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await create_ai_audiobook(
                AudiobookAICreateRequest(concept="A dragon adventure tale"),
                svc=svc,
            )
        assert exc.value.status_code == 404


# ── GET / (list) and POST / (create) ───────────────────────────────


class TestListAndCreate:
    async def test_list_passes_filters(self) -> None:
        svc = MagicMock()
        svc.list_filtered = AsyncMock(return_value=[_make_ab()])
        out = await list_audiobooks(status_filter="done", offset=10, limit=25, svc=svc)
        assert len(out) == 1
        svc.list_filtered.assert_awaited_once_with(status_filter="done", offset=10, limit=25)

    async def test_create_success(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(return_value=_make_ab())
        with patch(
            "drevalis.schemas.audiobook.resolve_audiobook_settings",
            return_value=MagicMock(model_dump=MagicMock(return_value={})),
        ):
            out = await create_audiobook(_make_create(), svc=svc)
        assert out.title == "Title"

    async def test_create_invalid_settings_422(self) -> None:
        svc = MagicMock()
        with patch(
            "drevalis.schemas.audiobook.resolve_audiobook_settings",
            side_effect=ValueError("unknown preset"),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_audiobook(_make_create(), svc=svc)
        assert exc.value.status_code == 422

    async def test_create_validation_422(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=ValidationError("bad voice"))
        with patch(
            "drevalis.schemas.audiobook.resolve_audiobook_settings",
            return_value=MagicMock(model_dump=MagicMock(return_value={})),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_audiobook(_make_create(), svc=svc)
        assert exc.value.status_code == 422

    async def test_create_not_found_404(self) -> None:
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=NotFoundError("voice_profile", uuid4()))
        with patch(
            "drevalis.schemas.audiobook.resolve_audiobook_settings",
            return_value=MagicMock(model_dump=MagicMock(return_value={})),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_audiobook(_make_create(), svc=svc)
        assert exc.value.status_code == 404


# ── POST /upload-cover ─────────────────────────────────────────────


def _png_bytes() -> bytes:
    """A 1x1 PNG that Pillow can verify."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _ufile(content: bytes, filename: str = "cover.png", mime: str = "image/png") -> Any:
    f = MagicMock(spec=UploadFile)
    f.filename = filename
    f.content_type = mime
    chunks = [content[i : i + 1024 * 1024] for i in range(0, len(content), 1024 * 1024)] + [b""]

    async def _read(_size: int) -> bytes:
        return chunks.pop(0) if chunks else b""

    f.read = AsyncMock(side_effect=_read)
    return f


class TestUploadCover:
    async def test_non_image_content_type_422(self, tmp_path: Any) -> None:
        with pytest.raises(HTTPException) as exc:
            await upload_cover_image(
                file=_ufile(b"data", mime="application/pdf"),
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 422

    async def test_oversize_413(self, tmp_path: Any) -> None:
        # Patch the route's MAX inline by uploading 11 MiB worth.
        big = b"\x00" * (11 * 1024 * 1024)
        with pytest.raises(HTTPException) as exc:
            await upload_cover_image(
                file=_ufile(big, mime="image/png"),
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 413

    async def test_invalid_image_bytes_422(self, tmp_path: Any) -> None:
        # PNG content_type but garbage bytes — Pillow `verify()` rejects.
        with pytest.raises(HTTPException) as exc:
            await upload_cover_image(
                file=_ufile(b"not a real png", mime="image/png"),
                settings=_settings(tmp_path),
            )
        assert exc.value.status_code == 422

    async def test_success_writes_unique_file(self, tmp_path: Any) -> None:
        out = await upload_cover_image(
            file=_ufile(_png_bytes(), filename="my cover.PNG", mime="image/png"),
            settings=_settings(tmp_path),
        )
        rel = out["cover_image_path"]
        assert rel.startswith("audiobooks/covers/")
        # File on disk has the bytes we sent (PNG header).
        target = tmp_path / rel
        assert target.exists()
        assert target.read_bytes()[:4] == b"\x89PNG"

    async def test_unknown_extension_falls_back_to_png(self, tmp_path: Any) -> None:
        # Filename without extension → fallback `.png`.
        out = await upload_cover_image(
            file=_ufile(_png_bytes(), filename="bare", mime="image/png"),
            settings=_settings(tmp_path),
        )
        assert out["cover_image_path"].endswith(".png")


# ── GET /{id} / PUT /{id} / PUT /{id}/text ─────────────────────────


class TestCrud:
    async def test_get_success(self) -> None:
        svc = MagicMock()
        ab = _make_ab()
        svc.get = AsyncMock(return_value=ab)
        out = await get_audiobook(ab.id, svc=svc)
        assert out.id == ab.id

    async def test_get_not_found_404(self) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await get_audiobook(uuid4(), svc=svc)
        assert exc.value.status_code == 404

    async def test_update_success(self) -> None:
        svc = MagicMock()
        svc.update_metadata = AsyncMock(return_value=_make_ab(title="renamed"))
        out = await update_audiobook(uuid4(), AudiobookUpdate(title="renamed"), svc=svc)
        assert out.title == "renamed"
        # exclude_unset semantics.
        kwargs = svc.update_metadata.call_args.args[1]
        assert kwargs == {"title": "renamed"}

    async def test_update_validation_422(self) -> None:
        svc = MagicMock()
        svc.update_metadata = AsyncMock(side_effect=ValidationError("bad"))
        with pytest.raises(HTTPException) as exc:
            await update_audiobook(uuid4(), AudiobookUpdate(title="x"), svc=svc)
        assert exc.value.status_code == 422

    async def test_update_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update_metadata = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_audiobook(uuid4(), AudiobookUpdate(title="x"), svc=svc)
        assert exc.value.status_code == 404

    async def test_update_text_success(self) -> None:
        svc = MagicMock()
        svc.update_text = AsyncMock(return_value=_make_ab())
        await update_audiobook_text(uuid4(), AudiobookTextUpdate(text="new text"), svc=svc)
        svc.update_text.assert_awaited_once()

    async def test_update_text_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update_text = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_audiobook_text(uuid4(), AudiobookTextUpdate(text="x"), svc=svc)
        assert exc.value.status_code == 404


# ── POST /{id}/regenerate-chapter ──────────────────────────────────


class TestRegenerateChapter:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.regenerate_chapter = AsyncMock()
        out = await regenerate_chapter(uuid4(), 2, ChapterRegeneratePayload(text="new"), svc=svc)
        assert out["chapter_index"] == 2

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.regenerate_chapter = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await regenerate_chapter(uuid4(), 1, None, svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_422(self) -> None:
        svc = MagicMock()
        svc.regenerate_chapter = AsyncMock(
            side_effect=ValidationError("chapter index out of range")
        )
        with pytest.raises(HTTPException) as exc:
            await regenerate_chapter(uuid4(), 99, None, svc=svc)
        assert exc.value.status_code == 422

    async def test_omit_payload_passes_none_text(self) -> None:
        svc = MagicMock()
        svc.regenerate_chapter = AsyncMock()
        await regenerate_chapter(uuid4(), 1, None, svc=svc)
        # Third positional arg is `new_text` — should be None.
        called = svc.regenerate_chapter.call_args.args[2]
        assert called is None


# ── POST /{id}/regenerate-chapter-image ────────────────────────────


class TestRegenerateChapterImage:
    async def test_success_with_prompt_override(self) -> None:
        svc = MagicMock()
        svc.regenerate_chapter_image = AsyncMock()
        await regenerate_chapter_image(
            uuid4(),
            1,
            ChapterImageRegeneratePayload(prompt_override="dragon flying"),
            svc=svc,
        )
        called = svc.regenerate_chapter_image.call_args.args[2]
        assert called == "dragon flying"

    async def test_omit_payload_passes_none(self) -> None:
        svc = MagicMock()
        svc.regenerate_chapter_image = AsyncMock()
        await regenerate_chapter_image(uuid4(), 1, None, svc=svc)
        called = svc.regenerate_chapter_image.call_args.args[2]
        assert called is None

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.regenerate_chapter_image = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await regenerate_chapter_image(uuid4(), 1, None, svc=svc)
        assert exc.value.status_code == 404

    async def test_validation_422(self) -> None:
        svc = MagicMock()
        svc.regenerate_chapter_image = AsyncMock(side_effect=ValidationError("invalid prompt"))
        with pytest.raises(HTTPException) as exc:
            await regenerate_chapter_image(uuid4(), 1, None, svc=svc)
        assert exc.value.status_code == 422


# ── PUT /{id}/voices ───────────────────────────────────────────────


class TestUpdateVoices:
    async def test_regenerated_returns_generating_status(self) -> None:
        svc = MagicMock()
        svc.update_voices = AsyncMock(return_value=True)
        out = await update_audiobook_voices(
            uuid4(),
            {"voice_casting": {"Narrator": str(uuid4())}, "regenerate": True},
            svc=svc,
        )
        assert out["status"] == "generating"

    async def test_not_regenerated_returns_simple_message(self) -> None:
        svc = MagicMock()
        svc.update_voices = AsyncMock(return_value=False)
        out = await update_audiobook_voices(
            uuid4(),
            {"voice_casting": {"Narrator": str(uuid4())}, "regenerate": False},
            svc=svc,
        )
        assert out == {"message": "Voices updated"}

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.update_voices = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await update_audiobook_voices(uuid4(), {}, svc=svc)
        assert exc.value.status_code == 404


# ── POST /{id}/cancel ──────────────────────────────────────────────


class TestCancelAudiobook:
    async def test_signalled_message(self) -> None:
        svc = MagicMock()
        svc.cancel = AsyncMock(return_value="cancel-signalled")
        out = await cancel_audiobook(uuid4(), svc=svc)
        assert "next step boundary" in out["message"]

    async def test_not_generating_returns_status_message(self) -> None:
        svc = MagicMock()
        svc.cancel = AsyncMock(return_value="done")
        out = await cancel_audiobook(uuid4(), svc=svc)
        # Pin: cancel on a completed audiobook returns the current
        # status, NOT a 409 — idempotent UI button.
        assert "nothing to cancel" in out["message"]
        assert out["status"] == "done"

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.cancel = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await cancel_audiobook(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── POST /{id}/regenerate ──────────────────────────────────────────


class TestRegenerateAudiobook:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.regenerate = AsyncMock()
        out = await regenerate_audiobook(uuid4(), svc=svc)
        assert "regeneration enqueued" in out["message"]

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.regenerate = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await regenerate_audiobook(uuid4(), svc=svc)
        assert exc.value.status_code == 404


# ── POST /{id}/remix ───────────────────────────────────────────────


class TestRemix:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.remix = AsyncMock(return_value={"voice_db": -2.0})
        out = await remix_audiobook(uuid4(), TrackMixPayload(voice_db=-2.0), svc=svc)
        assert out["track_mix"] == {"voice_db": -2.0}

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.remix = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await remix_audiobook(uuid4(), TrackMixPayload(voice_db=-2.0), svc=svc)
        assert exc.value.status_code == 404


# ── DELETE /{id} ───────────────────────────────────────────────────


class TestDelete:
    async def test_success(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock()
        await delete_audiobook(uuid4(), svc=svc)
        svc.delete.assert_awaited_once()

    async def test_not_found_404(self) -> None:
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=NotFoundError("audiobook", uuid4()))
        with pytest.raises(HTTPException) as exc:
            await delete_audiobook(uuid4(), svc=svc)
        assert exc.value.status_code == 404
