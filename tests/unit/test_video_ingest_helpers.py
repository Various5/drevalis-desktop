"""Pure-helper tests for ``workers/jobs/video_ingest.py``.

Pin:

* `_naive_candidates` window/hop math: 45 s windows stepping every 60 s,
  capped at 5 clips, returns [] for non-positive duration.
* `_llm_pick` LLM-output sanitisation:
  - non-JSON output → falls back to naive candidates.
  - clips missing start_s/end_s → skipped (not crashed).
  - clips shorter than 10 s or longer than 120 s → skipped.
  - title/reason capped at 120/240 chars to fit DB column.
  - empty cleaned list → falls back to naive (better something than
    a zero-clip suggestion list).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from drevalis.workers.jobs.video_ingest import _llm_pick, _naive_candidates

# ── _naive_candidates ─────────────────────────────────────────────


class TestNaiveCandidates:
    def test_empty_when_duration_zero(self) -> None:
        assert _naive_candidates([], 0.0) == []

    def test_empty_when_duration_negative(self) -> None:
        assert _naive_candidates([], -10.0) == []

    def test_short_video_yields_no_clips(self) -> None:
        # 45 s window doesn't fit in 30 s of footage.
        assert _naive_candidates([], 30.0) == []

    def test_basic_window(self) -> None:
        # 60 s of audio → exactly one clip starting at 0 ending at 45.
        out = _naive_candidates([], 60.0)
        assert len(out) == 1
        assert out[0]["start_s"] == 0.0
        assert out[0]["end_s"] == 45.0
        assert out[0]["score"] == 0.5

    def test_caps_at_five_clips(self) -> None:
        # 45-min source → many windows fit, but we cap at 5.
        out = _naive_candidates([], duration_s=2700.0)
        assert len(out) == 5
        # Hop is 60s so successive starts step by 60.
        assert out[0]["start_s"] == 0.0
        assert out[1]["start_s"] == 60.0
        assert out[4]["start_s"] == 240.0

    def test_titles_indexed_from_one(self) -> None:
        out = _naive_candidates([], duration_s=300.0)
        assert out[0]["title"] == "Clip 1"
        assert out[-1]["title"].startswith("Clip ")


# ── _llm_pick sanitisation ────────────────────────────────────────


def _provider_returning(text: str) -> Any:
    """Build an LLM service whose provider returns a result with the
    given text content."""
    result = MagicMock()
    result.text = text
    provider = MagicMock()
    provider.generate = AsyncMock(return_value=result)
    svc = MagicMock()
    svc.get_provider = MagicMock(return_value=provider)
    return svc


def _provider_raising(exc: Exception) -> Any:
    provider = MagicMock()
    provider.generate = AsyncMock(side_effect=exc)
    svc = MagicMock()
    svc.get_provider = MagicMock(return_value=provider)
    return svc


class TestLLMPick:
    async def test_provider_failure_falls_back_to_naive(self) -> None:
        word_ts = [{"s": 0.0, "e": 1.0, "w": "hi"}]
        out = await _llm_pick(
            llm_service=_provider_raising(ConnectionError("LM down")),
            llm_config=MagicMock(),
            word_ts=word_ts,
            duration_s=300.0,
            log=MagicMock(),
        )
        # Naive fallback fired → at least one clip with title "Clip 1".
        assert len(out) > 0
        assert out[0]["title"].startswith("Clip ")

    async def test_non_json_response_falls_back(self) -> None:
        out = await _llm_pick(
            llm_service=_provider_returning("not actually JSON"),
            llm_config=MagicMock(),
            word_ts=[],
            duration_s=300.0,
            log=MagicMock(),
        )
        # Falls back to naive — but there's no transcript so the naive
        # picker still returns a list (transcript text is independent
        # of the duration-based windowing).
        assert isinstance(out, list)

    async def test_short_clips_filtered(self) -> None:
        # Returned clip < 10 s → filtered. No usable clips → falls back.
        clips_json = '{"clips": [{"start_s": 0, "end_s": 5, "title": "x", "score": 0.9}]}'
        out = await _llm_pick(
            llm_service=_provider_returning(clips_json),
            llm_config=MagicMock(),
            word_ts=[],
            duration_s=300.0,
            log=MagicMock(),
        )
        # No usable clip → naive fallback.
        assert all(c["title"].startswith("Clip ") for c in out)

    async def test_long_clips_filtered(self) -> None:
        # Returned clip > 120 s → filtered.
        clips_json = '{"clips": [{"start_s": 0, "end_s": 200, "title": "x", "score": 0.9}]}'
        out = await _llm_pick(
            llm_service=_provider_returning(clips_json),
            llm_config=MagicMock(),
            word_ts=[],
            duration_s=300.0,
            log=MagicMock(),
        )
        assert all(c["title"].startswith("Clip ") for c in out)

    async def test_clips_missing_fields_skipped(self) -> None:
        # Malformed clips with missing start_s/end_s should be skipped
        # rather than crashing the picker.
        clips_json = (
            '{"clips": ['
            '{"start_s": 0, "title": "no end"},'
            '{"end_s": 50, "title": "no start"},'
            '{"start_s": 0, "end_s": 30, "title": "valid", "score": 0.8}'
            "]}"
        )
        out = await _llm_pick(
            llm_service=_provider_returning(clips_json),
            llm_config=MagicMock(),
            word_ts=[],
            duration_s=300.0,
            log=MagicMock(),
        )
        # Only the third clip survives.
        assert len(out) == 1
        assert out[0]["title"] == "valid"

    async def test_caps_clips_at_max_count(self) -> None:
        # 7 valid clips returned → cap at 5 (default max_count).
        clips_json = (
            '{"clips": ['
            + ",".join(
                f'{{"start_s": {i * 30}, "end_s": {i * 30 + 30}, "title": "c{i}", "score": 0.9}}'
                for i in range(7)
            )
            + "]}"
        )
        out = await _llm_pick(
            llm_service=_provider_returning(clips_json),
            llm_config=MagicMock(),
            word_ts=[],
            duration_s=300.0,
            log=MagicMock(),
            max_count=5,
        )
        assert len(out) == 5

    async def test_truncates_title_and_reason(self) -> None:
        long_title = "T" * 300
        long_reason = "R" * 500
        clips_json = (
            '{"clips": [{"start_s": 0, "end_s": 30, "title": "'
            + long_title
            + '", "reason": "'
            + long_reason
            + '", "score": 0.9}]}'
        )
        out = await _llm_pick(
            llm_service=_provider_returning(clips_json),
            llm_config=MagicMock(),
            word_ts=[],
            duration_s=300.0,
            log=MagicMock(),
        )
        assert len(out) == 1
        assert len(out[0]["title"]) == 120
        assert len(out[0]["reason"]) == 240

    async def test_score_defaults_to_zero_when_missing(self) -> None:
        # Pin: score field is optional; missing → 0.0 (so the UI's
        # sort-by-score doesn't crash on None).
        clips_json = '{"clips": [{"start_s": 0, "end_s": 30, "title": "x"}]}'
        out = await _llm_pick(
            llm_service=_provider_returning(clips_json),
            llm_config=MagicMock(),
            word_ts=[],
            duration_s=300.0,
            log=MagicMock(),
        )
        assert len(out) == 1
        assert out[0]["score"] == 0.0
