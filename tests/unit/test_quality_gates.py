"""Unit tests for pure-function pipeline quality gates.

The async ``check_voice_track`` and ``check_scene_image`` gates depend
on ffprobe / ffmpeg / PIL on real files and live in integration tests.
This module covers the pure-functional ``check_caption_density`` plus
the ``QualityReport`` shape so a regression on the gate output contract
fails loudly.
"""

from __future__ import annotations

from drevalis.services.quality_gates import QualityReport, check_caption_density


class TestQualityReport:
    def test_default_fields(self) -> None:
        r = QualityReport(gate="x", passed=True)
        assert r.issues == []
        assert r.metrics == {}

    def test_custom_metrics_keep_types(self) -> None:
        r = QualityReport(
            gate="voice",
            passed=False,
            issues=["too quiet"],
            metrics={"lufs": -28.4, "channels": 1, "path": "/tmp/v.wav"},
        )
        assert r.metrics["lufs"] == -28.4
        assert r.metrics["channels"] == 1
        assert isinstance(r.metrics["path"], str)


class TestCheckCaptionDensity:
    def test_zero_duration_fails(self) -> None:
        r = check_caption_density(total_words=10, audio_duration_s=0.0)
        assert r.passed is False
        assert "zero" in r.issues[0].lower()

    def test_unreadable_density_fails(self) -> None:
        # 50 words / 5s = 10 wps — well above 5 wps cap.
        r = check_caption_density(total_words=50, audio_duration_s=5.0)
        assert r.passed is False
        assert any("unreadable" in iss for iss in r.issues)

    def test_low_coverage_warns(self) -> None:
        # 100 words / 60s = 1.67 wps (good); coverage 30s/60s = 50% (< 60% min)
        r = check_caption_density(total_words=100, audio_duration_s=60.0, total_caption_span_s=30.0)
        assert r.passed is False
        assert any("cover" in iss.lower() for iss in r.issues)

    def test_passes_with_normal_density_and_coverage(self) -> None:
        r = check_caption_density(total_words=120, audio_duration_s=60.0, total_caption_span_s=55.0)
        assert r.passed is True
        assert r.issues == []

    def test_metrics_populated(self) -> None:
        r = check_caption_density(total_words=120, audio_duration_s=60.0)
        assert r.metrics["total_words"] == 120
        assert r.metrics["audio_duration_s"] == 60.0
        assert r.metrics["wps"] == 2.0

    def test_caption_span_optional(self) -> None:
        # Without span we only rate density; this should pass with normal wps.
        r = check_caption_density(total_words=120, audio_duration_s=60.0)
        assert "coverage" not in r.metrics

    def test_custom_max_wps_threshold(self) -> None:
        # Same density but tighter cap should now fail.
        r = check_caption_density(total_words=120, audio_duration_s=60.0, max_wps=1.5)
        assert r.passed is False

    def test_custom_min_coverage(self) -> None:
        # 30/60 = 50% coverage. Default 60% min flags it. Custom 40% min passes.
        r_strict = check_caption_density(
            total_words=120, audio_duration_s=60.0, total_caption_span_s=30.0
        )
        r_lax = check_caption_density(
            total_words=120,
            audio_duration_s=60.0,
            total_caption_span_s=30.0,
            min_coverage=0.40,
        )
        assert r_strict.passed is False
        assert r_lax.passed is True
