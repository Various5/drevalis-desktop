"""Tests for ``AudiobookService._resolve_output_format`` and
``_resolve_video_dims`` (F-CQ-01 step 3).

Both pure static helpers, lifted out of ``generate``. Pinning every
branch protects against silent regressions like a vertical Short
suddenly rendering at 1920×1080 because someone accidentally swapped
the if/else.
"""

from __future__ import annotations

import pytest

from drevalis.services.audiobook._monolith import AudiobookService

# ── _resolve_output_format ──────────────────────────────────────────


class TestResolveOutputFormat:
    @pytest.mark.parametrize(
        "current,expected",
        [
            ("audio_only", "audio_video"),
            ("audio_image", "audio_image"),  # already non-default
            ("audio_video", "audio_video"),
        ],
    )
    def test_legacy_flag_only_promotes_audio_only(self, current: str, expected: str) -> None:
        # ``generate_video=True`` only takes effect when the caller
        # left ``output_format`` at the default ``audio_only``.
        assert AudiobookService._resolve_output_format(current, generate_video=True) == expected

    @pytest.mark.parametrize(
        "current",
        ["audio_only", "audio_image", "audio_video"],
    )
    def test_no_legacy_flag_passes_through(self, current: str) -> None:
        assert AudiobookService._resolve_output_format(current, generate_video=False) == current


# ── _resolve_video_dims ─────────────────────────────────────────────


class TestResolveVideoDims:
    def test_vertical_returns_shorts_dimensions(self) -> None:
        assert AudiobookService._resolve_video_dims("vertical") == (1080, 1920)

    def test_landscape_returns_widescreen(self) -> None:
        assert AudiobookService._resolve_video_dims("landscape") == (1920, 1080)

    def test_unknown_orientation_falls_back_to_landscape(self) -> None:
        # Defensive: a typoed orientation (``"vert"``, ``"upright"``)
        # falls through to landscape rather than producing a 0×0
        # video that ffmpeg silently accepts.
        assert AudiobookService._resolve_video_dims("vert") == (1920, 1080)
        assert AudiobookService._resolve_video_dims("") == (1920, 1080)
        assert AudiobookService._resolve_video_dims("PORTRAIT") == (1920, 1080)

    @pytest.mark.parametrize(
        "orientation,dims",
        [
            ("vertical", (1080, 1920)),
            ("landscape", (1920, 1080)),
        ],
    )
    def test_pinned_aspect_ratio(self, orientation: str, dims: tuple[int, int]) -> None:
        # Pin both ratios — silent flip would ship every Short
        # letterboxed and every long-form pillarboxed.
        w, h = dims
        if orientation == "vertical":
            assert h > w
        else:
            assert w > h
        assert AudiobookService._resolve_video_dims(orientation) == dims
