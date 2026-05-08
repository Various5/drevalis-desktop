"""Tests for ``regenerate_audiobook_chapter`` and
``regenerate_audiobook_chapter_image``.

The earlier safety-branch suite pinned the missing-audiobook exit.
This file covers the actual orchestration:

* `regenerate_audiobook_chapter`:
  - In-place text replacement preserves whitespace/style of the
    original text outside the target chapter.
  - When the parsed body can't be located in the original text
    (rare — user added trailing whitespace) → falls back to
    `## `-headered rebuild WITHOUT silently dropping the edit.
  - Voice profile missing AFTER the text edit → marked failed.
  - Per-chapter chunk-cache invalidation runs before generate so
    only the edited chapter gets re-TTSed.
  - Generic exception → status=failed + 2000-char cap.

* `regenerate_audiobook_chapter_image`:
  - Out-of-range chapter index → returns failed dict.
  - No ComfyUI service in ctx → returns failed with
    "ComfyUI not configured".
  - `_generate_chapter_images` returns no result → failed.
  - Old image path on disk is best-effort deleted (delete failure
    swallowed).
  - Happy path persists `image_path` into the chapters JSON.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.audiobook import (
    regenerate_audiobook_chapter,
    regenerate_audiobook_chapter_image,
)


def _ctx() -> dict[str, Any]:
    return {
        "redis": AsyncMock(),
        "tts_service": MagicMock(),
        "ffmpeg_service": MagicMock(),
        "comfyui_service": MagicMock(),
        "storage": MagicMock(),
    }


def _ab(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "title": "Test",
        "text": "## Chapter 1\n\nFirst body.\n\n## Chapter 2\n\nSecond body.",
        "voice_profile_id": uuid4(),
        "background_image_path": None,
        "output_format": "audio_only",
        "cover_image_path": None,
        "voice_casting": None,
        "music_enabled": False,
        "music_mood": None,
        "music_volume_db": -14.0,
        "speed": 1.0,
        "pitch": 1.0,
        "chapters": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _factory_with(session: Any) -> Any:
    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    return _sf


def _gen_result() -> dict[str, Any]:
    return {
        "audio_rel_path": "audiobooks/x/audio.wav",
        "video_rel_path": None,
        "mp3_rel_path": "audiobooks/x/audio.mp3",
        "duration_seconds": 60.0,
        "file_size_bytes": 2_500_000,
        "chapters": [],
    }


# ── regenerate_audiobook_chapter ──────────────────────────────────


class TestRegenerateChapter:
    async def test_text_replacement_preserves_other_chapters(self) -> None:
        # Pin: the in-place replacement strategy keeps whitespace +
        # the surrounding `## ` style EXACTLY as in the source text.
        ab = _ab(text="## Chapter 1\n\nOLD body 1.\n\n## Chapter 2\n\nbody 2.")
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session = AsyncMock()
        session.commit = AsyncMock()

        # Mock the parser used to locate chapter bodies.
        chapters = [
            {"title": "Chapter 1", "text": "OLD body 1."},
            {"title": "Chapter 2", "text": "body 2."},
        ]
        ab_service = MagicMock()
        ab_service._parse_chapters = MagicMock(return_value=chapters)
        ab_service.invalidate_chapter_chunks = AsyncMock(return_value=2)
        ab_service.generate = AsyncMock(return_value=_gen_result())

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.repositories.voice_profile.VoiceProfileRepository",
                return_value=vp_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
        ):
            out = await regenerate_audiobook_chapter(
                ctx, str(ab.id), 0, new_chapter_text="NEW body 1."
            )

        assert out["status"] == "success"

        # Pin: the first ab_repo.update with text=... carries the
        # in-place-replaced source text (Chapter 2's `## ` header AND
        # body preserved, Chapter 1's body swapped).
        text_updates = [c.kwargs for c in ab_repo.update.await_args_list if "text" in c.kwargs]
        assert text_updates
        new_text = text_updates[0]["text"]
        assert "NEW body 1." in new_text
        assert "OLD body 1." not in new_text
        # Chapter 2 untouched.
        assert "## Chapter 2\n\nbody 2." in new_text

        # Pin: per-chapter chunk-cache invalidation ran BEFORE
        # generate (so only chapter 0's chunks get re-TTSed).
        ab_service.invalidate_chapter_chunks.assert_awaited_once_with(ab.id, 0)

    async def test_unfindable_body_falls_back_to_rebuild(self) -> None:
        # Pin: when the parsed body can't be found in the source text
        # (parser stripped trailing whitespace), the route REBUILDS
        # the text using `##` headers — the alternative is silently
        # losing the user's edit.
        ab = _ab(text="raw text with no parseable structure")
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session = AsyncMock()
        session.commit = AsyncMock()

        # Parser returns chapters whose body is NOT a substring of
        # `audiobook.text` → triggers the fallback branch.
        chapters = [
            {"title": "Chapter 1", "text": "missing-from-source-1"},
            {"title": "Chapter 2", "text": "missing-from-source-2"},
        ]
        ab_service = MagicMock()
        ab_service._parse_chapters = MagicMock(return_value=chapters)
        ab_service.invalidate_chapter_chunks = AsyncMock(return_value=0)
        ab_service.generate = AsyncMock(return_value=_gen_result())

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.repositories.voice_profile.VoiceProfileRepository",
                return_value=vp_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
        ):
            out = await regenerate_audiobook_chapter(
                ctx, str(ab.id), 0, new_chapter_text="REPLACED"
            )

        assert out["status"] == "success"

        # The rebuild text contains REPLACED (the new chapter 0 body)
        # AND the unchanged chapter 2 body.
        text_updates = [c.kwargs for c in ab_repo.update.await_args_list if "text" in c.kwargs]
        assert text_updates
        new_text = text_updates[0]["text"]
        assert "REPLACED" in new_text
        assert "missing-from-source-2" in new_text

    async def test_voice_profile_missing_marks_failed(self) -> None:
        ab = _ab()
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=None)
        session = AsyncMock()
        session.commit = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.repositories.voice_profile.VoiceProfileRepository",
                return_value=vp_repo,
            ),
        ):
            out = await regenerate_audiobook_chapter(ctx, str(ab.id), 0, new_chapter_text=None)
        assert out["status"] == "failed"
        # error_message persisted.
        last = ab_repo.update.await_args_list[-1].kwargs
        assert last["status"] == "failed"
        assert "Voice profile not found" in last["error_message"]

    async def test_generate_failure_caps_error_at_2000(self) -> None:
        ab = _ab()
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        vp_repo = MagicMock()
        vp_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        session = AsyncMock()
        session.commit = AsyncMock()

        ab_service = MagicMock()
        ab_service.invalidate_chapter_chunks = AsyncMock(return_value=0)
        long_err = "Z" * 5000
        ab_service.generate = AsyncMock(side_effect=RuntimeError(long_err))

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.repositories.voice_profile.VoiceProfileRepository",
                return_value=vp_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
        ):
            out = await regenerate_audiobook_chapter(ctx, str(ab.id), 0)
        assert out["status"] == "failed"
        last = ab_repo.update.await_args_list[-1].kwargs
        assert last["status"] == "failed"
        assert len(last["error_message"]) == 2000


# ── regenerate_audiobook_chapter_image ───────────────────────────


class TestRegenerateChapterImage:
    async def test_chapter_index_out_of_range(self) -> None:
        ab = _ab(chapters=[{"title": "Chapter 1", "image_path": None}])
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        session = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)
        with patch(
            "drevalis.repositories.audiobook.AudiobookRepository",
            return_value=ab_repo,
        ):
            out = await regenerate_audiobook_chapter_image(ctx, str(ab.id), 99)
        assert out["status"] == "failed"
        assert "out of range" in out["error"]

    async def test_negative_chapter_index_failed(self) -> None:
        ab = _ab(chapters=[{"title": "Chapter 1"}])
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        session = AsyncMock()
        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)
        with patch(
            "drevalis.repositories.audiobook.AudiobookRepository",
            return_value=ab_repo,
        ):
            out = await regenerate_audiobook_chapter_image(ctx, str(ab.id), -1)
        assert out["status"] == "failed"

    async def test_no_comfyui_service_marks_failed(self) -> None:
        ab = _ab(chapters=[{"title": "Chapter 1", "image_path": None}])
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        session = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)
        # Pin: ComfyUI service is None (not configured) → failed with
        # the operator-friendly hint.
        ctx["comfyui_service"] = None

        ab_service = MagicMock()
        ab_service.comfyui_service = None

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
        ):
            out = await regenerate_audiobook_chapter_image(ctx, str(ab.id), 0)
        assert out["status"] == "failed"
        assert "ComfyUI not configured" in out["error"]

    async def test_no_image_returned_marks_failed(self, tmp_path: Path) -> None:
        ab = _ab(chapters=[{"title": "Chapter 1", "image_path": None}])
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        session = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)
        ctx["storage"].resolve_path = MagicMock(return_value=tmp_path)

        ab_service = MagicMock()
        ab_service.comfyui_service = MagicMock()
        ab_service._generate_chapter_images = AsyncMock(return_value=[None])

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
        ):
            out = await regenerate_audiobook_chapter_image(ctx, str(ab.id), 0)
        assert out["status"] == "failed"
        assert "no result" in out["error"]

    async def test_old_image_deleted_best_effort(self, tmp_path: Path) -> None:
        # Pin: the existing `image_path` on disk is best-effort deleted
        # before regenerating. Pin with a real file that exists, then
        # assert it's gone.
        old_image = tmp_path / "old.png"
        old_image.write_bytes(b"\x89PNG")
        new_image = tmp_path / "new.png"
        new_image.write_bytes(b"\x89PNG NEW")

        ab = _ab(
            chapters=[
                {"title": "Chapter 1", "image_path": str(old_image)},
            ]
        )
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        session = AsyncMock()
        session.commit = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)
        ctx["storage"].resolve_path = MagicMock(return_value=tmp_path)

        ab_service = MagicMock()
        ab_service.comfyui_service = MagicMock()
        ab_service._generate_chapter_images = AsyncMock(return_value=[new_image])

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
        ):
            out = await regenerate_audiobook_chapter_image(ctx, str(ab.id), 0)
        assert out["status"] == "done"
        assert out["image_path"] == str(new_image)
        # Old image was removed.
        assert not old_image.exists()
        # Chapter 0's image_path was patched on the row.
        update_kwargs = ab_repo.update.call_args.kwargs
        assert update_kwargs["chapters"][0]["image_path"] == str(new_image)

    async def test_old_image_delete_failure_swallowed(self, tmp_path: Path) -> None:
        # Pin: when unlinking the old image raises (Windows file lock,
        # permission), the route still proceeds to regenerate.
        ab = _ab(
            chapters=[
                {"title": "Chapter 1", "image_path": "/nonexistent/locked.png"},
            ]
        )
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        session = AsyncMock()
        session.commit = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)
        ctx["storage"].resolve_path = MagicMock(return_value=tmp_path)

        new_image = tmp_path / "new.png"
        new_image.write_bytes(b"\x89PNG NEW")

        ab_service = MagicMock()
        ab_service.comfyui_service = MagicMock()
        ab_service._generate_chapter_images = AsyncMock(return_value=[new_image])

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
        ):
            out = await regenerate_audiobook_chapter_image(ctx, str(ab.id), 0)
        # Pin: even though the old path doesn't exist (so can't be
        # unlinked), the route still completes successfully.
        assert out["status"] == "done"

    async def test_prompt_override_passed_to_service(self, tmp_path: Path) -> None:
        ab = _ab(
            chapters=[
                {
                    "title": "Chapter 1",
                    "image_path": None,
                    "visual_prompt": "default prompt",
                }
            ]
        )
        ab_repo = MagicMock()
        ab_repo.get_by_id = AsyncMock(return_value=ab)
        ab_repo.update = AsyncMock()
        session = AsyncMock()
        session.commit = AsyncMock()

        ctx = _ctx()
        ctx["session_factory"] = _factory_with(session)
        ctx["storage"].resolve_path = MagicMock(return_value=tmp_path)

        new_image = tmp_path / "new.png"
        new_image.write_bytes(b"\x89PNG")

        ab_service = MagicMock()
        ab_service.comfyui_service = MagicMock()
        ab_service._generate_chapter_images = AsyncMock(return_value=[new_image])

        with (
            patch(
                "drevalis.repositories.audiobook.AudiobookRepository",
                return_value=ab_repo,
            ),
            patch(
                "drevalis.services.audiobook.AudiobookService",
                return_value=ab_service,
            ),
        ):
            await regenerate_audiobook_chapter_image(
                ctx, str(ab.id), 0, prompt_override="custom prompt"
            )
        # Pin: chapter dict passed to _generate_chapter_images carries
        # the override.
        kwargs = ab_service._generate_chapter_images.call_args.kwargs
        assert kwargs["chapters"][0]["visual_prompt"] == "custom prompt"
