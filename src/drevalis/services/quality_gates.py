"""Quality-gate helpers run between pipeline steps.

Each function returns a ``QualityReport`` with a ``passed`` flag and
human-readable ``issues``. The pipeline orchestrator treats failed
gates as warnings (logged, surfaced in progress messages) rather than
hard errors — generation continues; the operator decides whether to
re-run the offending step. This matches the audit guidance that quality
gates should never increase the failure rate of the pipeline, only the
trustworthiness of its output.

The gates are deliberately simple and stdlib-only: ffprobe for audio
characteristics, PIL for image sanity, plain math elsewhere. No new
dependencies (spaCy is detected at import time but never required).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from drevalis.schemas.script import EpisodeScript

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass
class QualityReport:
    gate: str
    passed: bool
    issues: list[str] = field(default_factory=list)
    metrics: dict[str, float | int | str] = field(default_factory=dict)


# ── Voice gate ─────────────────────────────────────────────────────


async def check_voice_track(
    audio_path: Path,
    *,
    expected_duration_s: float | None = None,
    duration_tolerance: float = 0.25,
    lufs_min: float = -25.0,
    lufs_max: float = -10.0,
) -> QualityReport:
    """Validate a TTS voiceover WAV.

    * Duration within ``duration_tolerance`` of ``expected_duration_s``.
    * Integrated LUFS inside the ``[lufs_min, lufs_max]`` broadcast band.
    * Detect pathological silence / DC offset.
    """
    issues: list[str] = []
    metrics: dict[str, float | int | str] = {"path": str(audio_path)}

    if not audio_path.exists() or audio_path.stat().st_size < 1024:
        return QualityReport(
            gate="voice",
            passed=False,
            issues=["audio file missing or implausibly small"],
            metrics=metrics,
        )

    # ffprobe → duration + channels
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=channels,sample_rate",
        "-of",
        "json",
        str(audio_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        data = json.loads(out.decode("utf-8", errors="replace"))
        duration = float((data.get("format") or {}).get("duration") or 0.0)
        stream = (data.get("streams") or [{}])[0]
        metrics["duration_s"] = round(duration, 3)
        metrics["channels"] = stream.get("channels") or 0
        metrics["sample_rate"] = stream.get("sample_rate") or "?"
    except Exception as exc:  # noqa: BLE001
        return QualityReport(
            gate="voice",
            passed=False,
            issues=[f"ffprobe failed: {exc}"],
            metrics=metrics,
        )

    if duration < 0.2:
        issues.append(f"audio duration {duration:.2f}s is implausibly short")
    if expected_duration_s and duration > 0:
        drift = abs(duration - expected_duration_s) / expected_duration_s
        metrics["duration_drift"] = round(drift, 3)
        if drift > duration_tolerance:
            issues.append(
                f"duration {duration:.1f}s differs from expected "
                f"{expected_duration_s:.1f}s by {drift * 100:.0f}%"
            )

    # EBU R128 integrated loudness
    proc2 = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(audio_path),
        "-af",
        "loudnorm=print_format=json",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc2.communicate()
    stderr_s = stderr.decode("utf-8", errors="replace")
    # ffmpeg's loudnorm JSON payload is the last {...} block on stderr.
    try:
        json_start = stderr_s.rfind("{")
        json_end = stderr_s.rfind("}")
        if json_start != -1 and json_end > json_start:
            payload = json.loads(stderr_s[json_start : json_end + 1])
            lufs = float(payload.get("input_i") or 0.0)
            true_peak = float(payload.get("input_tp") or 0.0)
            metrics["lufs"] = round(lufs, 2)
            metrics["true_peak_db"] = round(true_peak, 2)
            if lufs < lufs_min:
                issues.append(f"audio too quiet at {lufs:.1f} LUFS (< {lufs_min})")
            elif lufs > lufs_max:
                issues.append(f"audio too loud at {lufs:.1f} LUFS (> {lufs_max})")
            if true_peak > -0.1:
                issues.append(f"true peak {true_peak:.2f} dB — clipping likely")
    except Exception as exc:  # noqa: BLE001
        logger.debug("voice_loudnorm_parse_failed", error=str(exc)[:120])

    return QualityReport(gate="voice", passed=not issues, issues=issues, metrics=metrics)


# ── Scene image gate ───────────────────────────────────────────────


async def check_scene_image(
    image_path: Path,
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
    min_mean_luma: float = 12.0,
) -> QualityReport:
    """Validate a generated scene image.

    * File exists and is non-trivially sized.
    * Dimensions match the expected aspect-ratio bucket.
    * Not an all-black / all-white frame (degenerate generation).
    """
    issues: list[str] = []
    metrics: dict[str, float | int | str] = {"path": str(image_path)}

    if not image_path.exists() or image_path.stat().st_size < 4 * 1024:
        return QualityReport(
            gate="scene",
            passed=False,
            issues=["image missing or < 4 KB (likely a failed render)"],
            metrics=metrics,
        )

    try:
        # PIL is already a runtime dep (thumbnail pipeline).
        from PIL import Image, ImageStat

        with Image.open(image_path) as img:
            img.load()
            w, h = img.size
            metrics["width"] = w
            metrics["height"] = h
            if expected_width and w != expected_width:
                issues.append(f"width {w} != expected {expected_width}")
            if expected_height and h != expected_height:
                issues.append(f"height {h} != expected {expected_height}")
            try:
                stat = ImageStat.Stat(img.convert("L"))
                mean_luma = float(stat.mean[0] if stat.mean else 0.0)
                metrics["mean_luma"] = round(mean_luma, 2)
                if mean_luma < min_mean_luma:
                    issues.append(f"frame too dark (mean luma {mean_luma:.1f})")
                if mean_luma > 253.0:
                    issues.append(f"frame blown out (mean luma {mean_luma:.1f})")
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        issues.append(f"PIL failed to open image: {exc}")

    return QualityReport(gate="scene", passed=not issues, issues=issues, metrics=metrics)


# ── Caption gate ───────────────────────────────────────────────────


def check_caption_density(
    total_words: int,
    audio_duration_s: float,
    *,
    max_wps: float = 5.0,
    min_coverage: float = 0.60,
    total_caption_span_s: float | None = None,
) -> QualityReport:
    """Check captions against readable word-per-second density."""
    issues: list[str] = []
    metrics: dict[str, float | int | str] = {
        "total_words": total_words,
        "audio_duration_s": round(audio_duration_s, 2),
    }
    if audio_duration_s <= 0:
        return QualityReport(
            gate="captions",
            passed=False,
            issues=["audio duration is zero"],
            metrics=metrics,
        )

    wps = total_words / audio_duration_s
    metrics["wps"] = round(wps, 2)
    if wps > max_wps:
        issues.append(f"captions run at {wps:.1f} words/s (> {max_wps}) — unreadable")

    if total_caption_span_s is not None:
        coverage = total_caption_span_s / audio_duration_s
        metrics["coverage"] = round(coverage, 3)
        if coverage < min_coverage:
            issues.append(
                f"captions cover only {coverage * 100:.0f}% of the audio track "
                f"(< {min_coverage * 100:.0f}%)"
            )

    return QualityReport(gate="captions", passed=not issues, issues=issues, metrics=metrics)


# ── Script content gate ─────────────────────────────────────────────


# Global banned vocabulary — these are AI tells that show up across
# topics. Kept lowercase; matched case-insensitively with word-boundary
# anchoring so prefixes/suffixes (e.g. "delved", "tapestries") still
# trip the gate. This list mirrors the Phase 2.3 shorts script prompt
# rules 3 + 4 — keep them in sync when expanding.
_GLOBAL_BANNED_WORDS: tuple[str, ...] = (
    # AI tells (rule 3)
    "delve",
    "delves",
    "delved",
    "delving",
    "tapestry",
    "tapestries",
    "navigate",
    "navigates",
    "navigating",
    "realm",
    "realms",
    "journey",
    "journeys",
    "embark",
    "embarks",
    "embarking",
    "elevate",
    "elevates",
    "elevating",
    "unleash",
    "unleashes",
    "unleashing",
    "leverage",
    "leverages",
    "leveraging",
    "harness",
    "harnesses",
    "harnessing",
    "intricate",
    "nuanced",
    "foster",
    "fosters",
    "fostering",
    "cultivate",
    "cultivates",
    "cultivating",
    "robust",
    "seamless",
    "meticulously",
    "profoundly",
    "fundamentally",
    "essentially",
    "ultimately",
    "moreover",
    "furthermore",
)

# Multi-word banned phrases — matched as substrings, case-insensitive.
_GLOBAL_BANNED_PHRASES: tuple[str, ...] = (
    "in conclusion",
    "it's worth noting",
    "the world of",
    "let's dive in",
    "buckle up",
    "stay tuned",
    "without further ado",
    "but wait, there's more",
    "you won't believe what happened next",
    "the answer will shock you",
    "absolutely incredible",
    "mind-blowing",
)

# Listicle markers — only flagged when ``allow_listicle`` is false.
_LISTICLE_MARKERS: tuple[str, ...] = (
    "number 1",
    "number 2",
    "number 3",
    "first up",
    "coming in at",
    "next up on our list",
)


def _has_specificity(narration: str) -> bool:
    """Heuristic: does this narration contain at least one concrete fact?

    A scene passes if it contains any of:
    * a digit (covers years, money amounts, counts)
    * a 4-digit year (1500-2199 sanity range)
    * a capitalised proper noun NOT at sentence start

    spaCy is used when available for NER-quality detection; absent
    spaCy we fall back to the regex heuristics above so the gate works
    on every install without a hard dep bump.
    """
    if not narration:
        return False
    if re.search(r"\d", narration):
        return True

    # Capitalised tokens not at sentence start. Split on .!? then check
    # words 2+. Two-letter or longer to avoid "I" tripping the heuristic.
    sentences = re.split(r"(?<=[.!?])\s+", narration)
    for sentence in sentences:
        words = sentence.strip().split()
        for word in words[1:]:
            stripped = word.strip(".,;:'\"!?()[]")
            if len(stripped) >= 2 and stripped[0].isupper() and stripped[1:].islower():
                return True

    # Best-effort spaCy named-entity check (only runs if installed).
    if importlib.util.find_spec("spacy") is not None:  # pragma: no cover
        try:
            import spacy  # type: ignore[import-not-found]

            nlp = spacy.blank("en")
            doc = nlp(narration)
            if any(ent.label_ for ent in doc.ents):
                return True
        except Exception:  # noqa: BLE001
            pass

    return False


def _split_sentences(text: str) -> list[str]:
    """Split narration on terminal punctuation; trim empties."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in (s.strip() for s in parts) if p]


async def check_script_content(
    script: EpisodeScript,
    tone_profile: dict[str, object] | None = None,
) -> QualityReport:
    """Validate script narration against banned-vocabulary, specificity,
    sentence-length, opening-repetition, and listicle rules.

    Returns a single :class:`QualityReport` whose ``issues`` list scopes
    each finding to a scene number. Async signature matches
    :func:`check_voice_track` so the dispatcher can ``await`` it
    uniformly even though all checks are synchronous today.
    """
    issues: list[str] = []
    metrics: dict[str, float | int | str] = {
        "scene_count": len(script.scenes) if script and script.scenes else 0,
    }

    if not script or not script.scenes:
        return QualityReport(
            gate="script_content",
            passed=False,
            issues=["script has no scenes"],
            metrics=metrics,
        )

    profile = tone_profile if isinstance(tone_profile, dict) else {}
    extra_forbidden = profile.get("forbidden_words") or []
    if not isinstance(extra_forbidden, list):
        extra_forbidden = []

    cap_max_sentence = profile.get("max_sentence_words")
    if not isinstance(cap_max_sentence, int) or cap_max_sentence <= 0:
        cap_max_sentence = 18
    hard_cap = cap_max_sentence + 4

    allow_listicle = bool(profile.get("allow_listicle"))

    # Pre-compile banned-word regexes (word-boundary anchored). Phrases
    # are matched as substrings via lowercased ``in`` checks.
    banned_word_patterns = [
        re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE)
        for w in (
            *_GLOBAL_BANNED_WORDS,
            *(str(w).strip() for w in extra_forbidden if str(w).strip()),
        )
    ]
    banned_phrase_lower = [p.lower() for p in _GLOBAL_BANNED_PHRASES]

    sentence_lengths: list[int] = []
    last_open_words: list[str] | None = None

    for scene in script.scenes:
        scene_no = scene.scene_number
        narration = scene.narration or ""
        narration_lower = narration.lower()

        # 1. Banned phrase scan
        for phrase in banned_phrase_lower:
            if phrase in narration_lower:
                issues.append(f"scene {scene_no}: banned phrase '{phrase}'")
        for pattern in banned_word_patterns:
            match = pattern.search(narration)
            if match:
                issues.append(f"scene {scene_no}: banned word '{match.group(0).lower()}'")

        # 2. Specificity
        if not _has_specificity(narration):
            issues.append(
                f"scene {scene_no}: no concrete fact (no digit, year, or proper noun detected)"
            )

        # 3. Sentence length
        sentences = _split_sentences(narration)
        for sent in sentences:
            words = [w for w in sent.split() if w]
            sentence_lengths.append(len(words))
            if len(words) > hard_cap:
                issues.append(
                    f"scene {scene_no}: sentence exceeds hard cap ({len(words)} > {hard_cap} words)"
                )

        # 4. Opening-repetition. Normalise to lowercased word stems so
        # near-identical openings ("In 1947 NASA's …" vs "In 1947 NASA …")
        # don't slip past on a stray apostrophe — the rule's about the
        # listener-facing rhythm, not exact token equality.
        first_three = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in narration.split()[:3]]
        if (
            last_open_words is not None
            and first_three == last_open_words
            and any(w for w in first_three)
        ):
            issues.append(f"scene {scene_no}: opens with the same 3 words as the previous scene")
        last_open_words = first_three

        # 5. Listicle markers (gated)
        if not allow_listicle:
            for marker in _LISTICLE_MARKERS:
                if marker in narration_lower:
                    issues.append(
                        f"scene {scene_no}: listicle marker '{marker}' (allow_listicle is false)"
                    )

    # Average sentence length across the whole script (informational —
    # only flagged when above the per-profile cap).
    if sentence_lengths:
        avg = sum(sentence_lengths) / len(sentence_lengths)
        metrics["avg_sentence_words"] = round(avg, 2)
        metrics["max_sentence_words_observed"] = max(sentence_lengths)
        if avg > cap_max_sentence:
            issues.append(f"average sentence length {avg:.1f} exceeds cap {cap_max_sentence}")

    return QualityReport(
        gate="script_content",
        passed=not issues,
        issues=issues,
        metrics=metrics,
    )


__all__ = [
    "QualityReport",
    "check_voice_track",
    "check_scene_image",
    "check_caption_density",
    "check_script_content",
]
