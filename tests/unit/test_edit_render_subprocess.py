"""Tests for `workers/jobs/edit_render.py` — FFmpeg subprocess paths.

Patches `asyncio.create_subprocess_exec` so the FFmpeg invocations
are inspected (cmd shape) without actually spawning the binary. Pin:

* `_apply_overlays`:
  - Drawtext-only pass when no image overlays.
  - Image-only pass when no drawtext (skips the drawtext stage).
  - Mixed pass: drawtext first, then per-image stage.
  - Skip image overlays with missing `asset_path` or non-existent
    file on disk.
  - FFmpeg non-zero exit → `RuntimeError` with the stderr tail.
  - Final move logic: when no overlay was applied at all (no
    drawtext, no image), the input is left untouched (no replace
    call).
* `_apply_audio_envelopes`:
  - No envelopes → early return without spawning ffmpeg.
  - Builds the piecewise expression with the right number of
    `if(...)` segments + matching closing parens.
  - FFmpeg non-zero exit → `RuntimeError`.
  - Degenerate segments (t1 <= t0) skipped without crashing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from drevalis.workers.jobs.edit_render import (
    _apply_audio_envelopes,
    _apply_overlays,
)


def _proc(returncode: int = 0, stderr: bytes = b"") -> Any:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"", stderr))
    return proc


# ── _apply_overlays ───────────────────────────────────────────────


class TestApplyOverlays:
    async def test_drawtext_only_pass(self, tmp_path: Path) -> None:
        # No image overlays → only one ffmpeg pass with drawtext.
        in_path = tmp_path / "in.mp4"
        in_path.write_bytes(b"\x00")
        out_path = tmp_path / "out.mp4"

        captured: list[list[str]] = []

        async def _fake_exec(*args: Any, **_kwargs: Any) -> Any:
            captured.append(list(args))
            # Stage the output file so the route's `.replace(...)`
            # rename doesn't fail.
            out_arg = args[-1]
            Path(out_arg).write_bytes(b"\x00")
            return _proc(returncode=0)

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            await _apply_overlays(
                ffmpeg_path="ffmpeg",
                input_path=in_path,
                output_path=out_path,
                overlays=[
                    {
                        "kind": "text",
                        "text": "Hello",
                        "start_s": 0,
                        "end_s": 2,
                    }
                ],
                storage_base=tmp_path,
            )
        # Only ONE ffmpeg pass.
        assert len(captured) == 1
        cmd = captured[0]
        assert cmd[0] == "ffmpeg"
        assert "-vf" in cmd
        # drawtext fragment landed in the -vf arg.
        vf_idx = cmd.index("-vf") + 1
        assert "drawtext=" in cmd[vf_idx]
        # Audio passthrough so we don't waste cycles re-encoding.
        assert "-c:a" in cmd
        assert cmd[cmd.index("-c:a") + 1] == "copy"

    async def test_drawtext_failure_raises(self, tmp_path: Path) -> None:
        in_path = tmp_path / "in.mp4"
        in_path.write_bytes(b"\x00")
        out_path = tmp_path / "out.mp4"

        async def _fake_exec(*_args: Any, **_kwargs: Any) -> Any:
            return _proc(returncode=1, stderr=b"some ffmpeg error")

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            with pytest.raises(RuntimeError, match="overlay drawtext failed"):
                await _apply_overlays(
                    ffmpeg_path="ffmpeg",
                    input_path=in_path,
                    output_path=out_path,
                    overlays=[{"kind": "text", "text": "x", "start_s": 0, "end_s": 1}],
                    storage_base=tmp_path,
                )

    async def test_image_only_pass(self, tmp_path: Path) -> None:
        # No drawtext → drawtext pass is SKIPPED entirely; only the
        # per-image overlay pass runs.
        in_path = tmp_path / "in.mp4"
        in_path.write_bytes(b"\x00")
        out_path = tmp_path / "out.mp4"
        img = tmp_path / "logo.png"
        img.write_bytes(b"\x89PNG")

        captured: list[list[str]] = []

        async def _fake_exec(*args: Any, **_kwargs: Any) -> Any:
            captured.append(list(args))
            # Stage the output file so the route's `.replace(...)`
            # rename doesn't fail.
            out_arg = args[-1]
            Path(out_arg).write_bytes(b"\x00")
            return _proc(returncode=0)

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            await _apply_overlays(
                ffmpeg_path="ffmpeg",
                input_path=in_path,
                output_path=out_path,
                overlays=[
                    {
                        "kind": "image",
                        "asset_path": "logo.png",
                        "start_s": 1,
                        "end_s": 3,
                    }
                ],
                storage_base=tmp_path,
            )
        # Only the image-overlay pass — exactly one invocation.
        assert len(captured) == 1
        cmd = captured[0]
        # Pin: filter_complex used (not -vf) for the image overlay.
        assert "-filter_complex" in cmd

    async def test_mixed_drawtext_and_image_runs_two_passes(self, tmp_path: Path) -> None:
        in_path = tmp_path / "in.mp4"
        in_path.write_bytes(b"\x00")
        out_path = tmp_path / "out.mp4"
        img = tmp_path / "logo.png"
        img.write_bytes(b"\x89PNG")

        captured: list[list[str]] = []

        async def _fake_exec(*args: Any, **_kwargs: Any) -> Any:
            captured.append(list(args))
            # Stage the output file so the route's `.replace(...)`
            # rename doesn't fail.
            out_arg = args[-1]
            Path(out_arg).write_bytes(b"\x00")
            return _proc(returncode=0)

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            await _apply_overlays(
                ffmpeg_path="ffmpeg",
                input_path=in_path,
                output_path=out_path,
                overlays=[
                    {"kind": "text", "text": "hi", "start_s": 0, "end_s": 1},
                    {
                        "kind": "image",
                        "asset_path": "logo.png",
                        "start_s": 1,
                        "end_s": 2,
                    },
                ],
                storage_base=tmp_path,
            )
        # Pin: drawtext first, then image overlay → exactly 2 passes.
        assert len(captured) == 2
        # First pass uses -vf (drawtext); second uses -filter_complex.
        assert "-vf" in captured[0]
        assert "-filter_complex" in captured[1]

    async def test_image_overlay_missing_path_skipped(self, tmp_path: Path) -> None:
        in_path = tmp_path / "in.mp4"
        in_path.write_bytes(b"\x00")
        out_path = tmp_path / "out.mp4"

        captured: list[list[str]] = []

        async def _fake_exec(*args: Any, **_kwargs: Any) -> Any:
            captured.append(list(args))
            # Stage the output file so the route's `.replace(...)`
            # rename doesn't fail.
            out_arg = args[-1]
            Path(out_arg).write_bytes(b"\x00")
            return _proc(returncode=0)

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            await _apply_overlays(
                ffmpeg_path="ffmpeg",
                input_path=in_path,
                output_path=out_path,
                overlays=[
                    # No asset_path → skipped.
                    {"kind": "image", "start_s": 0, "end_s": 1},
                    # Asset_path points at non-existent file → skipped.
                    {
                        "kind": "image",
                        "asset_path": "missing.png",
                        "start_s": 1,
                        "end_s": 2,
                    },
                ],
                storage_base=tmp_path,
            )
        # Pin: NO ffmpeg passes — both image overlays skipped, and
        # there were no drawtext entries either.
        assert captured == []

    async def test_image_overlay_failure_raises(self, tmp_path: Path) -> None:
        in_path = tmp_path / "in.mp4"
        in_path.write_bytes(b"\x00")
        out_path = tmp_path / "out.mp4"
        img = tmp_path / "logo.png"
        img.write_bytes(b"\x89PNG")

        async def _fake_exec(*_args: Any, **_kwargs: Any) -> Any:
            return _proc(returncode=1, stderr=b"image overlay error")

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            with pytest.raises(RuntimeError, match="overlay image failed"):
                await _apply_overlays(
                    ffmpeg_path="ffmpeg",
                    input_path=in_path,
                    output_path=out_path,
                    overlays=[
                        {
                            "kind": "image",
                            "asset_path": "logo.png",
                            "start_s": 0,
                            "end_s": 1,
                        }
                    ],
                    storage_base=tmp_path,
                )


# ── _apply_audio_envelopes ────────────────────────────────────────


class TestApplyAudioEnvelopes:
    async def test_empty_envelopes_early_returns(self, tmp_path: Path) -> None:
        # Pin: no keyframes at all → return without spawning ffmpeg.
        called = {"yes": False}

        async def _fake_exec(*_args: Any, **_kwargs: Any) -> Any:
            called["yes"] = True
            return _proc()

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            await _apply_audio_envelopes(
                ffmpeg_path="ffmpeg",
                input_path=tmp_path / "in.mp4",
                output_path=tmp_path / "out.mp4",
                envelopes=[],
            )
        assert called["yes"] is False

    async def test_builds_piecewise_expression(self, tmp_path: Path) -> None:
        in_path = tmp_path / "in.mp4"
        in_path.write_bytes(b"\x00")
        out_path = tmp_path / "out.mp4"

        captured: list[list[str]] = []

        async def _fake_exec(*args: Any, **_kwargs: Any) -> Any:
            captured.append(list(args))
            # Stage the output file so the route's `.replace(...)`
            # rename doesn't fail.
            out_arg = args[-1]
            Path(out_arg).write_bytes(b"\x00")
            return _proc(returncode=0)

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            # Three keyframes → 2 segments (head + 2 segments + tail = 4 ifs).
            await _apply_audio_envelopes(
                ffmpeg_path="ffmpeg",
                input_path=in_path,
                output_path=out_path,
                envelopes=[(0.0, 0.0), (5.0, -6.0), (10.0, -12.0)],
            )
        cmd = captured[0]
        # The -af expression contains the volume= filter.
        assert "-af" in cmd
        af_expr = cmd[cmd.index("-af") + 1]
        assert "volume=eval=frame:volume='" in af_expr
        # Pin the closing-paren count: 2 segments + head + tail = 4 ifs.
        assert af_expr.count("if(") == 4
        # Audio re-encoded (volume= needs decoded samples), video passthrough.
        assert cmd[cmd.index("-c:v") + 1] == "copy"
        assert cmd[cmd.index("-c:a") + 1] == "aac"

    async def test_degenerate_segment_skipped(self, tmp_path: Path) -> None:
        # Pin: t1 <= t0 (zero or backwards segment) is skipped without
        # raising — the head + tail still produce a valid expression.
        captured: list[list[str]] = []

        async def _fake_exec(*args: Any, **_kwargs: Any) -> Any:
            captured.append(list(args))
            # Stage the output file so the route's `.replace(...)`
            # rename doesn't fail.
            out_arg = args[-1]
            Path(out_arg).write_bytes(b"\x00")
            return _proc(returncode=0)

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            await _apply_audio_envelopes(
                ffmpeg_path="ffmpeg",
                input_path=tmp_path / "in.mp4",
                output_path=tmp_path / "out.mp4",
                # Two keyframes at the same time → degenerate segment.
                envelopes=[(5.0, 0.0), (5.0, -6.0)],
            )
        # Did invoke ffmpeg.
        assert len(captured) == 1
        cmd = captured[0]
        af_expr = cmd[cmd.index("-af") + 1]
        # Head + tail = 2 ifs (no middle segment).
        assert af_expr.count("if(") == 2

    async def test_unsorted_keyframes_sorted_first(self, tmp_path: Path) -> None:
        # Pin: input keyframes in any order are sorted by time before
        # building the expression. Without this, the head/tail logic
        # would be wrong.
        captured: list[list[str]] = []

        async def _fake_exec(*args: Any, **_kwargs: Any) -> Any:
            captured.append(list(args))
            # Stage the output file so the route's `.replace(...)`
            # rename doesn't fail.
            out_arg = args[-1]
            Path(out_arg).write_bytes(b"\x00")
            return _proc(returncode=0)

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            await _apply_audio_envelopes(
                ffmpeg_path="ffmpeg",
                input_path=tmp_path / "in.mp4",
                output_path=tmp_path / "out.mp4",
                envelopes=[(10.0, -12.0), (0.0, 0.0), (5.0, -6.0)],
            )
        cmd = captured[0]
        af_expr = cmd[cmd.index("-af") + 1]
        # Head condition fires for t < 0 (first sorted point, t=0).
        assert "lt(t,0.000)" in af_expr
        # Tail condition uses t=10 (last sorted point).
        assert "gte(t,10.000)" in af_expr

    async def test_failure_raises_runtime_error(self, tmp_path: Path) -> None:
        async def _fake_exec(*_args: Any, **_kwargs: Any) -> Any:
            return _proc(returncode=1, stderr=b"envelope error")

        with patch("asyncio.create_subprocess_exec", _fake_exec):
            with pytest.raises(RuntimeError, match="envelope render failed"):
                await _apply_audio_envelopes(
                    ffmpeg_path="ffmpeg",
                    input_path=tmp_path / "in.mp4",
                    output_path=tmp_path / "out.mp4",
                    envelopes=[(0.0, 0.0), (5.0, -6.0)],
                )
