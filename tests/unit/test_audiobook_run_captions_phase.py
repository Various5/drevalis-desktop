"""Tests for ``AudiobookService._run_captions_phase`` (F-CQ-01 step 10).

Three terminal states distinguished: success, skipped (faster-whisper
not installed — optional dep), failed (any other ASR exception). Pin
that all three flip the DAG correctly and that the failure paths
do NOT propagate the exception (audiobook still completes).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.services.audiobook._monolith import AudiobookService


def _service() -> AudiobookService:
    svc = AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )
    svc._check_cancelled = AsyncMock()  # type: ignore[method-assign]
    svc._broadcast_progress = AsyncMock()  # type: ignore[method-assign]
    svc._dag_global = AsyncMock()  # type: ignore[method-assign]
    return svc


class _StubCaptionResult:
    def __init__(self, ass_path: Path, count: int = 50) -> None:
        self.ass_path = ass_path
        self.captions = [object()] * count


def _patch_caption_service(svc_mock: Any) -> Any:
    """Patch the late-imported CaptionService + CaptionStyle classes
    inside the audiobook module's import scope."""
    captions_mod = MagicMock()
    captions_mod.CaptionService = MagicMock(return_value=svc_mock)
    captions_mod.CaptionStyle = MagicMock(side_effect=lambda **kw: kw)
    return patch.dict(sys.modules, {"drevalis.services.captions": captions_mod})


# ── Success path ─────────────────────────────────────────────────────


class TestSuccess:
    async def test_returns_full_path_tuple_and_marks_dag_done(self, tmp_path: Path) -> None:
        ab_id = uuid4()
        ass = tmp_path / "captions" / "captions.ass"
        ass.parent.mkdir(parents=True, exist_ok=True)
        ass.write_text("[Script Info]\n", encoding="utf-8")

        caption_svc = MagicMock()
        caption_svc.generate_from_audio = AsyncMock(return_value=_StubCaptionResult(ass_path=ass))

        svc = _service()
        with _patch_caption_service(caption_svc):
            ass_path, ass_rel, srt_rel = await svc._run_captions_phase(
                audiobook_id=ab_id,
                abs_dir=tmp_path,
                final_audio=tmp_path / "audiobook.wav",
                caption_style_preset=None,
                video_width=1920,
                video_height=1080,
            )

        assert ass_path == ass
        assert ass_rel == f"audiobooks/{ab_id}/captions/captions.ass"
        assert srt_rel == f"audiobooks/{ab_id}/captions/captions.srt"
        # DAG: in_progress → done.
        statuses = [c.args[1] for c in svc._dag_global.call_args_list]
        assert statuses == ["in_progress", "done"]

    async def test_progress_at_85_percent(self, tmp_path: Path) -> None:
        ass = tmp_path / "x.ass"
        ass.write_text("[Script Info]\n", encoding="utf-8")
        caption_svc = MagicMock()
        caption_svc.generate_from_audio = AsyncMock(return_value=_StubCaptionResult(ass_path=ass))

        svc = _service()
        with _patch_caption_service(caption_svc):
            await svc._run_captions_phase(
                audiobook_id=uuid4(),
                abs_dir=tmp_path,
                final_audio=tmp_path / "x.wav",
                caption_style_preset=None,
                video_width=1920,
                video_height=1080,
            )
        bc = svc._broadcast_progress.call_args
        assert bc.args[1] == "captions"
        assert bc.args[2] == 85

    async def test_default_preset_is_youtube_highlight(self, tmp_path: Path) -> None:
        # The contract: caption_style_preset=None falls back to
        # "youtube_highlight" so the dropdown's "default" actually
        # produces the documented style.
        ass = tmp_path / "x.ass"
        ass.write_text("", encoding="utf-8")
        caption_svc = MagicMock()
        caption_svc.generate_from_audio = AsyncMock(return_value=_StubCaptionResult(ass_path=ass))
        captured_style: dict[str, Any] = {}

        async def _capture(*, audio_path, output_dir, language, style):  # noqa: ANN001
            captured_style.update(style)
            return _StubCaptionResult(ass_path=ass)

        caption_svc.generate_from_audio = AsyncMock(side_effect=_capture)

        svc = _service()
        with _patch_caption_service(caption_svc):
            await svc._run_captions_phase(
                audiobook_id=uuid4(),
                abs_dir=tmp_path,
                final_audio=tmp_path / "x.wav",
                caption_style_preset=None,
                video_width=1920,
                video_height=1080,
            )
        assert captured_style.get("preset") == "youtube_highlight"

    async def test_explicit_preset_propagates(self, tmp_path: Path) -> None:
        ass = tmp_path / "x.ass"
        ass.write_text("", encoding="utf-8")
        captured: dict[str, Any] = {}

        async def _capture(*, audio_path, output_dir, language, style):  # noqa: ANN001
            captured.update(style)
            return _StubCaptionResult(ass_path=ass)

        caption_svc = MagicMock()
        caption_svc.generate_from_audio = AsyncMock(side_effect=_capture)

        svc = _service()
        with _patch_caption_service(caption_svc):
            await svc._run_captions_phase(
                audiobook_id=uuid4(),
                abs_dir=tmp_path,
                final_audio=tmp_path / "x.wav",
                caption_style_preset="audiobook_classic",
                video_width=1920,
                video_height=1080,
            )
        assert captured["preset"] == "audiobook_classic"

    async def test_video_dims_threaded_into_play_res(self, tmp_path: Path) -> None:
        ass = tmp_path / "x.ass"
        ass.write_text("", encoding="utf-8")
        captured: dict[str, Any] = {}

        async def _capture(*, audio_path, output_dir, language, style):  # noqa: ANN001
            captured.update(style)
            return _StubCaptionResult(ass_path=ass)

        caption_svc = MagicMock()
        caption_svc.generate_from_audio = AsyncMock(side_effect=_capture)

        svc = _service()
        with _patch_caption_service(caption_svc):
            await svc._run_captions_phase(
                audiobook_id=uuid4(),
                abs_dir=tmp_path,
                final_audio=tmp_path / "x.wav",
                caption_style_preset=None,
                video_width=1080,
                video_height=1920,
            )
        # ASS PlayResX/PlayResY come from the video dims so subtitle
        # positioning matches the actual frame size.
        assert captured["play_res_x"] == 1080
        assert captured["play_res_y"] == 1920


# ── Skipped path (faster-whisper not installed) ─────────────────────


class TestSkipped:
    async def test_import_error_marks_dag_skipped(self, tmp_path: Path) -> None:
        # The optional faster-whisper dependency is missing — the
        # ``from drevalis.services.captions import ...`` line raises
        # ImportError. Audiobook continues without captions.
        svc = _service()
        real_import = __import__

        def _patched_import(
            name: str,
            globals: Any = None,
            locals: Any = None,
            fromlist: Any = (),
            level: int = 0,
        ) -> Any:
            if name == "drevalis.services.captions":
                raise ImportError("No module named 'faster_whisper'")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=_patched_import):
            ass_path, ass_rel, srt_rel = await svc._run_captions_phase(
                audiobook_id=uuid4(),
                abs_dir=tmp_path,
                final_audio=tmp_path / "x.wav",
                caption_style_preset=None,
                video_width=1920,
                video_height=1080,
            )

        # All three return values are None — downstream video creation
        # falls through to the no-captions path.
        assert ass_path is None
        assert ass_rel is None
        assert srt_rel is None
        # DAG: in_progress → skipped.
        statuses = [c.args[1] for c in svc._dag_global.call_args_list]
        assert statuses == ["in_progress", "skipped"]


# ── Failed path (other ASR exceptions) ───────────────────────────────


class TestFailed:
    async def test_arbitrary_exception_marks_dag_failed_no_propagate(self, tmp_path: Path) -> None:
        # Any non-ImportError exception during ASR is logged and
        # converted to a "failed" DAG state; the audiobook still
        # completes (just without captions).
        caption_svc = MagicMock()
        caption_svc.generate_from_audio = AsyncMock(side_effect=RuntimeError("CUDA OOM"))

        svc = _service()
        with _patch_caption_service(caption_svc):
            ass_path, ass_rel, srt_rel = await svc._run_captions_phase(
                audiobook_id=uuid4(),
                abs_dir=tmp_path,
                final_audio=tmp_path / "x.wav",
                caption_style_preset=None,
                video_width=1920,
                video_height=1080,
            )

        # All None on failure.
        assert ass_path is None
        assert ass_rel is None
        assert srt_rel is None
        # DAG: in_progress → failed.
        statuses = [c.args[1] for c in svc._dag_global.call_args_list]
        assert statuses == ["in_progress", "failed"]


# ── Cancellation ─────────────────────────────────────────────────────


class TestCancellation:
    async def test_cancellation_checked_before_dag_in_progress(self, tmp_path: Path) -> None:
        # If the user cancels right at the boundary, we don't want to
        # spin up faster-whisper for nothing.
        ass = tmp_path / "x.ass"
        ass.write_text("", encoding="utf-8")
        caption_svc = MagicMock()
        caption_svc.generate_from_audio = AsyncMock(return_value=_StubCaptionResult(ass_path=ass))

        order: list[str] = []
        svc = _service()
        svc._check_cancelled = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *_a, **_k: order.append("cancel")
        )
        svc._dag_global = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *args, **_k: order.append(f"dag:{args[1]}")
        )

        with _patch_caption_service(caption_svc):
            await svc._run_captions_phase(
                audiobook_id=uuid4(),
                abs_dir=tmp_path,
                final_audio=tmp_path / "x.wav",
                caption_style_preset=None,
                video_width=1920,
                video_height=1080,
            )

        # cancellation precedes the DAG transition.
        assert order[0] == "cancel"
        assert "dag:in_progress" in order
