"""Pre-upload SEO pre-flight scoring.

Runs on an episode right before upload. Scores title, description, hook,
tags, and thumbnail against per-platform rules. Returns a list of
structured ``Check`` results the frontend renders traffic-light style.

Intentionally dependency-free — no LLM call, no HTTP. This lets it run
inline on every keystroke in the upload dialog.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# Platform-specific targets. Tuned against YouTube Studio recommendations
# (60-70 char titles) and creator community benchmarks.
_TITLE_MAX = {"youtube_shorts": 100, "youtube_longform": 70, "tiktok": 100}
_TITLE_IDEAL_MAX = {"youtube_shorts": 60, "youtube_longform": 60, "tiktok": 60}
_DESC_MIN = {"youtube_shorts": 100, "youtube_longform": 300, "tiktok": 80}
_DESC_MAX = {"youtube_shorts": 500, "youtube_longform": 5000, "tiktok": 2200}
_HASHTAG_IDEAL_MIN = {"youtube_shorts": 3, "youtube_longform": 2, "tiktok": 3}
_HASHTAG_IDEAL_MAX = {"youtube_shorts": 5, "youtube_longform": 5, "tiktok": 8}
_TAG_IDEAL_MIN = 5
_TAG_IDEAL_MAX = 15
_HOOK_MAX_SECONDS = 3.0

Severity = Literal["pass", "warn", "fail", "info"]
Platform = Literal["youtube_shorts", "youtube_longform", "tiktok"]


@dataclass(frozen=True)
class Check:
    """Single pre-flight check result."""

    id: str
    severity: Severity
    title: str
    message: str
    suggestion: str | None = None


@dataclass
class PreflightResult:
    """Aggregated score + checks for a single preflight run."""

    score: int  # 0-100
    grade: Literal["A", "B", "C", "D", "F"]
    checks: list[Check]
    blocking: bool  # any ``fail`` severity = blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "grade": self.grade,
            "blocking": self.blocking,
            "checks": [
                {
                    "id": c.id,
                    "severity": c.severity,
                    "title": c.title,
                    "message": c.message,
                    "suggestion": c.suggestion,
                }
                for c in self.checks
            ],
        }


def preflight(
    *,
    title: str,
    description: str,
    hashtags: list[str],
    tags: list[str],
    hook_text: str,
    hook_duration_seconds: float | None,
    thumbnail_path: Path | None,
    platform: Platform = "youtube_shorts",
) -> PreflightResult:
    """Run every check and roll up a score."""
    checks: list[Check] = []

    checks.append(_check_title(title, platform))
    checks.append(_check_description(description, platform))
    checks.append(_check_hashtags(hashtags, platform))
    checks.append(_check_tags(tags))
    checks.append(_check_hook(hook_text, hook_duration_seconds))
    checks.append(_check_thumbnail(thumbnail_path))
    checks.extend(_check_clickbait(title, hook_text))

    # Score: each pass = full weight, warn = half, fail = zero.
    weights = {
        "title": 20,
        "description": 15,
        "hashtags": 10,
        "tags": 10,
        "hook": 20,
        "thumbnail": 15,
        "clickbait_caps": 5,
        "clickbait_emoji": 5,
    }
    total = 0
    for c in checks:
        w = weights.get(c.id, 0)
        if c.severity == "pass":
            total += w
        elif c.severity == "warn":
            total += w // 2
    # Normalise.
    total = min(100, total)

    grade: Literal["A", "B", "C", "D", "F"]
    if total >= 90:
        grade = "A"
    elif total >= 75:
        grade = "B"
    elif total >= 60:
        grade = "C"
    elif total >= 45:
        grade = "D"
    else:
        grade = "F"

    blocking = any(c.severity == "fail" for c in checks)
    return PreflightResult(score=total, grade=grade, checks=checks, blocking=blocking)


# ── Individual checks ───────────────────────────────────────────────


def _check_title(title: str, platform: Platform) -> Check:
    t = title.strip()
    n = len(t)
    if n == 0:
        return Check(
            id="title",
            severity="fail",
            title="Title",
            message="Title is empty.",
            suggestion="Write a 40–60 character title with the primary keyword up front.",
        )
    if n < 10:
        return Check(
            id="title",
            severity="fail",
            title="Title",
            message=f"Title is too short ({n} chars).",
            suggestion="Expand to at least 20 characters so search can index it.",
        )
    if n > _TITLE_MAX[platform]:
        return Check(
            id="title",
            severity="fail",
            title="Title",
            message=f"Title is {n} chars — platform limit is {_TITLE_MAX[platform]}.",
            suggestion=f"Trim to under {_TITLE_IDEAL_MAX[platform]} chars.",
        )
    if n > _TITLE_IDEAL_MAX[platform]:
        return Check(
            id="title",
            severity="warn",
            title="Title",
            message=f"Title is {n} chars — may truncate in mobile feed.",
            suggestion=f"Ideal: ≤{_TITLE_IDEAL_MAX[platform]} chars.",
        )
    return Check(id="title", severity="pass", title="Title", message=f"{n} chars, clean length.")


def _check_description(description: str, platform: Platform) -> Check:
    d = description.strip()
    n = len(d)
    if n < _DESC_MIN[platform]:
        return Check(
            id="description",
            severity="warn" if n > 20 else "fail",
            title="Description",
            message=f"Description is short ({n} chars).",
            suggestion=(
                f"First 150 chars show in feed — write at least {_DESC_MIN[platform]} chars "
                "starting with the hook + primary keyword."
            ),
        )
    if n > _DESC_MAX[platform]:
        return Check(
            id="description",
            severity="fail",
            title="Description",
            message=f"Description is {n} chars — exceeds {_DESC_MAX[platform]} limit.",
            suggestion="Trim — excess is clipped by the platform.",
        )
    first_line = d.split("\n", 1)[0].strip()
    if len(first_line) < 40:
        return Check(
            id="description",
            severity="warn",
            title="Description",
            message="First line is short — that's the only part most viewers see.",
            suggestion="Lead with a 60–120 char hook that restates the value.",
        )
    return Check(
        id="description",
        severity="pass",
        title="Description",
        message=f"{n} chars, first line {len(first_line)} chars.",
    )


def _check_hashtags(hashtags: list[str], platform: Platform) -> Check:
    n = len(hashtags)
    if n == 0:
        return Check(
            id="hashtags",
            severity="warn",
            title="Hashtags",
            message="No hashtags.",
            suggestion=f"Add {_HASHTAG_IDEAL_MIN[platform]}–{_HASHTAG_IDEAL_MAX[platform]} "
            "relevant hashtags for discovery.",
        )
    if n < _HASHTAG_IDEAL_MIN[platform]:
        return Check(
            id="hashtags",
            severity="warn",
            title="Hashtags",
            message=f"Only {n} hashtag — may miss discovery.",
            suggestion=f"Add {_HASHTAG_IDEAL_MIN[platform] - n} more.",
        )
    if n > _HASHTAG_IDEAL_MAX[platform]:
        return Check(
            id="hashtags",
            severity="warn",
            title="Hashtags",
            message=f"{n} hashtags — excess looks spammy.",
            suggestion=f"Trim to {_HASHTAG_IDEAL_MAX[platform]} or fewer.",
        )
    return Check(id="hashtags", severity="pass", title="Hashtags", message=f"{n} tags, in range.")


def _check_tags(tags: list[str]) -> Check:
    n = len(tags)
    if n == 0:
        return Check(
            id="tags",
            severity="warn",
            title="Keyword tags",
            message="No keyword tags — YouTube uses these for indexing.",
            suggestion=f"Add {_TAG_IDEAL_MIN}–{_TAG_IDEAL_MAX} broad → specific keywords.",
        )
    if n < _TAG_IDEAL_MIN:
        return Check(
            id="tags",
            severity="warn",
            title="Keyword tags",
            message=f"Only {n} tag — consider adding more.",
            suggestion="Mix broad ('productivity') with specific ('notion templates 2026').",
        )
    if n > _TAG_IDEAL_MAX:
        return Check(
            id="tags",
            severity="warn",
            title="Keyword tags",
            message=f"{n} tags — YouTube recommends fewer, higher-quality.",
            suggestion=f"Trim to ≤{_TAG_IDEAL_MAX}.",
        )
    return Check(
        id="tags",
        severity="pass",
        title="Keyword tags",
        message=f"{n} tags, in range.",
    )


def _check_hook(hook_text: str, hook_duration_s: float | None) -> Check:
    text = hook_text.strip()
    if not text:
        return Check(
            id="hook",
            severity="fail",
            title="Hook (first 3 seconds)",
            message="No opening hook detected.",
            suggestion=(
                "First 3 seconds decide retention — open with a question, "
                "contradiction, or visible payoff."
            ),
        )
    words = text.split()
    wc = len(words)
    # ~2.5 words/second for natural narration.
    est_seconds = hook_duration_s if hook_duration_s else wc / 2.5
    if est_seconds > _HOOK_MAX_SECONDS + 1.0:
        return Check(
            id="hook",
            severity="warn",
            title="Hook (first 3 seconds)",
            message=f"Hook takes ~{est_seconds:.1f}s to deliver.",
            suggestion="Trim to fit under 3 seconds — viewers decide that fast.",
        )
    if wc < 4:
        return Check(
            id="hook",
            severity="warn",
            title="Hook (first 3 seconds)",
            message="Hook is only a few words — may not set context.",
            suggestion="Expand to 6–10 words so viewers know what they're watching.",
        )
    return Check(
        id="hook",
        severity="pass",
        title="Hook (first 3 seconds)",
        message=f"~{est_seconds:.1f}s, {wc} words.",
    )


def _check_thumbnail(thumb_path: Path | None) -> Check:
    if thumb_path is None:
        return Check(
            id="thumbnail",
            severity="warn",
            title="Thumbnail",
            message="No thumbnail provided.",
            suggestion="Upload a 1280×720 (16:9) or 1080×1920 (9:16) high-contrast thumbnail.",
        )
    if not thumb_path.exists():
        return Check(
            id="thumbnail",
            severity="fail",
            title="Thumbnail",
            message="Thumbnail file is missing on disk.",
            suggestion="Re-run the thumbnail step or upload a replacement.",
        )
    size = thumb_path.stat().st_size
    if size < 10 * 1024:
        return Check(
            id="thumbnail",
            severity="warn",
            title="Thumbnail",
            message=f"Thumbnail is very small ({size / 1024:.0f} KB).",
            suggestion="Low-size thumbnails often mean low resolution. Regenerate at higher quality.",
        )
    if size > 2 * 1024 * 1024:
        return Check(
            id="thumbnail",
            severity="warn",
            title="Thumbnail",
            message=f"Thumbnail is {size / (1024 * 1024):.1f} MB — YouTube caps at 2 MB.",
            suggestion="Re-export at quality 85 JPEG.",
        )
    return Check(
        id="thumbnail",
        severity="pass",
        title="Thumbnail",
        message=f"{size / 1024:.0f} KB on disk.",
    )


def _check_clickbait(title: str, hook_text: str) -> list[Check]:
    """Quick heuristics against the two most common over-used signals.

    Not meant as absolute rules — just surfaces patterns creators tend
    to regret after upload.
    """
    out: list[Check] = []
    if not title:
        return out
    letters = [c for c in title if c.isalpha()]
    if letters:
        caps_pct = sum(1 for c in letters if c.isupper()) / len(letters)
    else:
        caps_pct = 0
    if caps_pct > 0.6:
        out.append(
            Check(
                id="clickbait_caps",
                severity="warn",
                title="ALL-CAPS title",
                message=f"{caps_pct:.0%} of title letters are uppercase.",
                suggestion="Over-capitalised titles flag as clickbait. Use sentence case.",
            )
        )
    else:
        out.append(
            Check(
                id="clickbait_caps",
                severity="pass",
                title="ALL-CAPS title",
                message="Normal capitalisation.",
            )
        )

    emoji_chars = sum(1 for c in title if ord(c) > 0x2600)
    if emoji_chars > 3:
        out.append(
            Check(
                id="clickbait_emoji",
                severity="warn",
                title="Emoji density",
                message=f"{emoji_chars} emoji in the title.",
                suggestion="Cap at 1–2 emoji. Too many read as spam.",
            )
        )
    else:
        out.append(
            Check(
                id="clickbait_emoji",
                severity="pass",
                title="Emoji density",
                message=f"{emoji_chars} emoji, reasonable.",
            )
        )
    return out
