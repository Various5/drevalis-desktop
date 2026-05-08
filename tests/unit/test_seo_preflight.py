"""Unit tests for the upload SEO pre-flight scoring.

The module is dependency-free and pure-functional, so the tests cover
each individual check plus the aggregate ``preflight`` rollup. No
fixtures required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from drevalis.services.seo_preflight import (
    Check,
    PreflightResult,
    _check_clickbait,
    _check_description,
    _check_hashtags,
    _check_hook,
    _check_tags,
    _check_thumbnail,
    _check_title,
    preflight,
)


class TestCheckTitle:
    def test_empty_title_fails(self) -> None:
        result = _check_title("", "youtube_shorts")
        assert result.severity == "fail"
        assert "empty" in result.message.lower()

    def test_too_short_fails(self) -> None:
        result = _check_title("hi", "youtube_shorts")
        assert result.severity == "fail"
        assert "short" in result.message.lower()

    def test_over_platform_max_fails(self) -> None:
        long = "x" * 200  # > 100-char shorts limit
        result = _check_title(long, "youtube_shorts")
        assert result.severity == "fail"

    def test_over_ideal_warns(self) -> None:
        result = _check_title("x" * 80, "youtube_shorts")  # 80 < 100 max, > 60 ideal
        assert result.severity == "warn"

    def test_clean_passes(self) -> None:
        result = _check_title("How to fix the leaky faucet in 5 minutes", "youtube_shorts")
        assert result.severity == "pass"

    def test_longform_has_tighter_max(self) -> None:
        # 80 chars exceeds longform's 70-char hard limit
        result = _check_title("x" * 80, "youtube_longform")
        assert result.severity == "fail"


class TestCheckDescription:
    def test_short_warn_when_above_floor(self) -> None:
        result = _check_description("a" * 50, "youtube_shorts")
        assert result.severity == "warn"

    def test_extremely_short_fails(self) -> None:
        result = _check_description("hi", "youtube_shorts")
        assert result.severity == "fail"

    def test_too_long_fails(self) -> None:
        result = _check_description("x" * 600, "youtube_shorts")
        assert result.severity == "fail"

    def test_first_line_short_warns(self) -> None:
        # Description meets length requirements but first line is short
        body = "Short head\n" + ("x" * 200)
        result = _check_description(body, "youtube_shorts")
        assert result.severity == "warn"
        assert "first line" in result.message.lower()

    def test_clean_passes(self) -> None:
        body = (
            "Detailed walkthrough of how we wired the new authentication system end to end "
            "for a public launch — includes the migration plan, the cookie strategy, and the rollout."
        )
        result = _check_description(body, "youtube_shorts")
        assert result.severity == "pass"


class TestCheckHashtags:
    def test_zero_warns(self) -> None:
        assert _check_hashtags([], "youtube_shorts").severity == "warn"

    def test_below_ideal_warns(self) -> None:
        assert _check_hashtags(["#one"], "youtube_shorts").severity == "warn"

    def test_above_ideal_warns(self) -> None:
        assert _check_hashtags([f"#tag{i}" for i in range(10)], "youtube_shorts").severity == "warn"

    def test_in_range_passes(self) -> None:
        assert _check_hashtags(["#a", "#b", "#c", "#d"], "youtube_shorts").severity == "pass"


class TestCheckTags:
    def test_zero_warns(self) -> None:
        assert _check_tags([]).severity == "warn"

    def test_below_min_warns(self) -> None:
        assert _check_tags(["a", "b"]).severity == "warn"

    def test_above_max_warns(self) -> None:
        assert _check_tags([f"t{i}" for i in range(20)]).severity == "warn"

    def test_in_range_passes(self) -> None:
        assert _check_tags(["a", "b", "c", "d", "e", "f", "g"]).severity == "pass"


class TestCheckHook:
    def test_empty_fails(self) -> None:
        assert _check_hook("", None).severity == "fail"

    def test_too_long_warns(self) -> None:
        long_hook = "word " * 30  # ~30 words, ~12s @ 2.5 wps
        assert _check_hook(long_hook.strip(), None).severity == "warn"

    def test_too_few_words_warns(self) -> None:
        assert _check_hook("just three words", None).severity == "warn"

    def test_normal_passes(self) -> None:
        assert _check_hook("Did you know your cat ignores you on purpose?", None).severity == "pass"

    def test_explicit_duration_overrides_word_estimate(self) -> None:
        assert _check_hook("a a a a a a a a", 1.5).severity == "pass"


class TestCheckThumbnail:
    def test_none_warns(self) -> None:
        assert _check_thumbnail(None).severity == "warn"

    def test_missing_file_fails(self, tmp_path: Path) -> None:
        assert _check_thumbnail(tmp_path / "nonexistent.jpg").severity == "fail"

    def test_too_small_warns(self, tmp_path: Path) -> None:
        small = tmp_path / "tiny.jpg"
        small.write_bytes(b"x" * 1024)  # 1 KB
        assert _check_thumbnail(small).severity == "warn"

    def test_too_large_warns(self, tmp_path: Path) -> None:
        big = tmp_path / "huge.jpg"
        big.write_bytes(b"x" * (3 * 1024 * 1024))  # 3 MB > 2 MB cap
        assert _check_thumbnail(big).severity == "warn"

    def test_normal_passes(self, tmp_path: Path) -> None:
        ok = tmp_path / "ok.jpg"
        ok.write_bytes(b"x" * (200 * 1024))  # 200 KB
        assert _check_thumbnail(ok).severity == "pass"


class TestCheckClickbait:
    def test_all_caps_warns(self) -> None:
        results = _check_clickbait("CLICK HERE NOW BEFORE GONE", "")
        caps = next(c for c in results if c.id == "clickbait_caps")
        assert caps.severity == "warn"

    def test_normal_caps_passes(self) -> None:
        results = _check_clickbait("Why your code is slow", "")
        caps = next(c for c in results if c.id == "clickbait_caps")
        assert caps.severity == "pass"

    def test_emoji_density_warns(self) -> None:
        results = _check_clickbait("Five tips 🔥🔥🔥🔥🔥", "")
        emoji = next(c for c in results if c.id == "clickbait_emoji")
        assert emoji.severity == "warn"

    def test_few_emoji_passes(self) -> None:
        results = _check_clickbait("Five tips ✨", "")
        emoji = next(c for c in results if c.id == "clickbait_emoji")
        assert emoji.severity == "pass"

    def test_empty_title_returns_empty(self) -> None:
        assert _check_clickbait("", "") == []


class TestPreflightAggregate:
    def _ok_args(self, tmp_path: Path) -> dict:
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * (200 * 1024))
        return {
            "title": "How to fix the slowest endpoint in your stack",
            "description": (
                "Walkthrough of profiling a 3-second API endpoint, finding the N+1 query, and "
                "fixing it with a single selectinload — covers the metric setup and the debugging "
                "loop you'd actually use in production."
            ),
            "hashtags": ["#python", "#fastapi", "#perf"],
            "tags": ["python", "fastapi", "sqlalchemy", "n+1", "selectinload", "perf"],
            "hook_text": "Did you know one missing index can make your API ten times slower?",
            "hook_duration_seconds": 2.4,
            "thumbnail_path": thumb,
            "platform": "youtube_shorts",
        }

    def test_ok_args_grade_a(self, tmp_path: Path) -> None:
        result = preflight(**self._ok_args(tmp_path))
        assert isinstance(result, PreflightResult)
        assert result.grade == "A"
        assert result.score >= 90
        assert result.blocking is False

    def test_blocking_when_any_fail(self, tmp_path: Path) -> None:
        args = self._ok_args(tmp_path)
        args["title"] = ""  # forces fail
        result = preflight(**args)
        assert result.blocking is True

    def test_to_dict_serialises_checks(self, tmp_path: Path) -> None:
        result = preflight(**self._ok_args(tmp_path))
        d = result.to_dict()
        assert {"score", "grade", "blocking", "checks"} <= d.keys()
        assert all({"id", "severity", "title", "message"} <= c.keys() for c in d["checks"])

    def test_grade_thresholds(self, tmp_path: Path) -> None:
        # Force a low score by zeroing every signal except thumbnail.
        args = self._ok_args(tmp_path)
        args["title"] = ""
        args["description"] = ""
        args["hashtags"] = []
        args["tags"] = []
        args["hook_text"] = ""
        result = preflight(**args)
        assert result.grade in {"D", "F"}


class TestCheckDataclass:
    def test_check_is_frozen(self) -> None:
        c = Check(id="x", severity="pass", title="t", message="m")
        with pytest.raises(Exception):  # FrozenInstanceError
            c.severity = "fail"  # type: ignore[misc]
