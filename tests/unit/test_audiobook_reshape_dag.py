"""Tests for ``AudiobookService._reshape_dag_for_chapters`` (F-CQ-01 step 4).

The helper takes the parsed chapters list + flag state and rewrites
the per-stage DAG so progress percentages are accurate. Bugs here ship
as either silently-misaligned progress bars (chapters going from 0% to
100% instantly because skipped stages weren't marked) or chapter_moods
overrides being lost.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from drevalis.services.audiobook._monolith import AudiobookService


def _make_service() -> AudiobookService:
    return AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )


def _chapter(idx: int, text: str = "...") -> dict[str, Any]:
    return {"index": idx, "title": f"C{idx}", "text": text}


# ── DAG reshape ──────────────────────────────────────────────────────


class TestDagReshape:
    async def test_normalises_to_chapter_count(self) -> None:
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]

        chapters = [_chapter(0), _chapter(1), _chapter(2)]
        await svc._reshape_dag_for_chapters(
            chapters=chapters,
            image_generation_enabled=True,
            output_format="audio_video",
            music_enabled=True,
            chapter_moods=None,
        )
        # Reshaped to 3 chapters.
        assert len(svc._job_state["chapters"]) == 3

    async def test_persists_dag_after_reshape(self) -> None:
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        await svc._reshape_dag_for_chapters(
            chapters=[_chapter(0)],
            image_generation_enabled=True,
            output_format="audio_video",
            music_enabled=True,
            chapter_moods=None,
        )
        svc._persist_dag.assert_awaited_once()

    async def test_image_skipped_when_disabled(self) -> None:
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        await svc._reshape_dag_for_chapters(
            chapters=[_chapter(0), _chapter(1)],
            image_generation_enabled=False,
            output_format="audio_video",
            music_enabled=True,
            chapter_moods=None,
        )
        for ch in svc._job_state["chapters"].values():
            assert ch["image"] == "skipped"

    async def test_image_skipped_when_audio_only(self) -> None:
        # Even with image_generation_enabled=True, audio_only output has
        # nowhere to display the image — mark it skipped so progress is honest.
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        await svc._reshape_dag_for_chapters(
            chapters=[_chapter(0)],
            image_generation_enabled=True,
            output_format="audio_only",
            music_enabled=True,
            chapter_moods=None,
        )
        for ch in svc._job_state["chapters"].values():
            assert ch["image"] == "skipped"

    async def test_music_skipped_when_disabled(self) -> None:
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        await svc._reshape_dag_for_chapters(
            chapters=[_chapter(0), _chapter(1)],
            image_generation_enabled=True,
            output_format="audio_video",
            music_enabled=False,
            chapter_moods=None,
        )
        for ch in svc._job_state["chapters"].values():
            assert ch["music"] == "skipped"

    async def test_mp4_export_skipped_when_audio_only(self) -> None:
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        await svc._reshape_dag_for_chapters(
            chapters=[_chapter(0)],
            image_generation_enabled=False,
            output_format="audio_only",
            music_enabled=False,
            chapter_moods=None,
        )
        assert svc._job_state["mp4_export"] == "skipped"

    async def test_full_pipeline_keeps_all_stages_pending(self) -> None:
        # All flags enabled + audio_video output → no stage marked
        # ``skipped`` (everything will actually run).
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        await svc._reshape_dag_for_chapters(
            chapters=[_chapter(0)],
            image_generation_enabled=True,
            output_format="audio_video",
            music_enabled=True,
            chapter_moods=None,
        )
        for ch in svc._job_state["chapters"].values():
            assert ch["image"] != "skipped"
            assert ch["music"] != "skipped"
        assert svc._job_state.get("mp4_export") != "skipped"


# ── chapter_moods application ───────────────────────────────────────


class TestChapterMoodsApplication:
    async def test_none_moods_leaves_chapters_untouched(self) -> None:
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        chapters = [_chapter(0), _chapter(1)]
        await svc._reshape_dag_for_chapters(
            chapters=chapters,
            image_generation_enabled=True,
            output_format="audio_video",
            music_enabled=True,
            chapter_moods=None,
        )
        assert "music_mood" not in chapters[0]
        assert "music_mood" not in chapters[1]

    async def test_full_moods_applied(self) -> None:
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        chapters = [_chapter(0), _chapter(1), _chapter(2)]
        await svc._reshape_dag_for_chapters(
            chapters=chapters,
            image_generation_enabled=True,
            output_format="audio_video",
            music_enabled=True,
            chapter_moods=["calm", "epic", "tense"],
        )
        assert chapters[0]["music_mood"] == "calm"
        assert chapters[1]["music_mood"] == "epic"
        assert chapters[2]["music_mood"] == "tense"

    async def test_short_moods_list_only_applies_to_first_n_chapters(self) -> None:
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        chapters = [_chapter(0), _chapter(1), _chapter(2)]
        await svc._reshape_dag_for_chapters(
            chapters=chapters,
            image_generation_enabled=True,
            output_format="audio_video",
            music_enabled=True,
            chapter_moods=["calm"],
        )
        assert chapters[0]["music_mood"] == "calm"
        assert "music_mood" not in chapters[1]
        assert "music_mood" not in chapters[2]

    async def test_empty_string_mood_does_not_overwrite(self) -> None:
        # Defensive: empty string is falsy so we don't blat over an
        # existing chapter-level mood with an empty placeholder.
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        chapters = [_chapter(0)]
        chapters[0]["music_mood"] = "preexisting"
        await svc._reshape_dag_for_chapters(
            chapters=chapters,
            image_generation_enabled=True,
            output_format="audio_video",
            music_enabled=True,
            chapter_moods=[""],
        )
        assert chapters[0]["music_mood"] == "preexisting"

    async def test_more_moods_than_chapters_extras_ignored(self) -> None:
        svc = _make_service()
        svc._job_state = {}
        svc._persist_dag = AsyncMock()  # type: ignore[method-assign]
        chapters = [_chapter(0)]
        await svc._reshape_dag_for_chapters(
            chapters=chapters,
            image_generation_enabled=True,
            output_format="audio_video",
            music_enabled=True,
            chapter_moods=["calm", "epic", "tense"],  # 3 entries, 1 chapter
        )
        assert chapters[0]["music_mood"] == "calm"
        # Only one chapter to mutate.
        assert len(chapters) == 1
