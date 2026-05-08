"""Chapter detection for the audiobook pipeline.

Scored heading-pattern cascade (Task 8): each candidate pattern
is matched against the full text, post-filtered, and scored by
mean-segment-length / (1 + CV).  The highest-scoring candidate
above ``_SCORE_THRESHOLD`` wins; unscored fallbacks (``---``
separators, single-chapter) apply when no scored pattern fires.

Symbols exported from this module:

    _CHAPTER_PATTERN_MARKDOWN  — ``## Title`` pattern
    _CHAPTER_PATTERN_PROSE     — ``Chapter N`` / ``CHAPTER IV`` pattern
    _CHAPTER_PATTERN_ROMAN     — Roman numeral pattern
    _CHAPTER_PATTERN_ALLCAPS   — All-caps heading pattern
    _SCORE_THRESHOLD           — Minimum score for a candidate to win
    _MIN_SEGMENT_CHARS         — Minimum chars per segment (false-positive guard)
    _score_chapter_split       — Score a list of regex matches
    _filter_markdown_matches   — Post-filter for markdown headings
    _filter_allcaps_matches    — Post-filter for all-caps headings
    _parse_chapters            — Public entry point: text → chapter dicts
"""

from __future__ import annotations

import re
from typing import Any

# ── Chapter heading patterns (Task 8) ────────────────────────────────────────
# Each pattern exposes a ``title`` named group; matches are scored by
# ``_score_chapter_split`` and the highest-scoring pattern above
# threshold wins, so the cascade is "best fit" rather than first-fit.
#
# Tightened regex notes:
#   * Markdown: ``\S`` after the hashes blocks bare ``## ``; the
#     post-filter requires a blank line above (or BOF) and below.
#   * Prose chapter: word-number form added (one..twelve), ``CHAP``
#     short form added, dollar-anchored.
#   * Roman: length min 2 — lone ``I`` no longer counts.
#   * All-caps: post-filter rejects rows ending in punctuation that
#     suggests dialogue / scene cue, and enforces ≥ 80% alpha ratio.
_CHAPTER_PATTERN_MARKDOWN = r"(?m)^##\s+(?P<title>\S[^\n]{0,80})$"
_CHAPTER_PATTERN_PROSE = (
    r"(?im)^\s*(?P<title>(?:chapter|chap\.?)\s+"
    r"(?:\d+|[IVXLCDM]+|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"\b[^\n]{0,80})$"
)
_CHAPTER_PATTERN_ROMAN = r"(?m)^\s{0,3}(?P<title>[IVXLCDM]{2,8}\s*[.:)]?)\s*$"
_CHAPTER_PATTERN_ALLCAPS = r"(?m)^\s*(?P<title>[A-Z][A-Z0-9 '\-:,]{3,60})\s*$"

_SCORE_THRESHOLD = 800.0
_MIN_SEGMENT_CHARS = 500


def _score_chapter_split(matches: list[re.Match[str]], text: str) -> float:
    """Score a candidate chapter split.

    Higher is better. Two splits are required at minimum; any
    segment shorter than ``_MIN_SEGMENT_CHARS`` returns 0 (false-
    positive guard). Otherwise the score is mean segment length
    divided by ``1 + coefficient_of_variation`` so consistent chunk
    sizes (real chapters) win against noisy ones (false splits).
    """
    if len(matches) < 2:
        return 0.0
    boundaries = [m.start() for m in matches] + [len(text)]
    segs = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)]
    if min(segs) < _MIN_SEGMENT_CHARS:
        return 0.0
    import statistics as _stats

    mean = _stats.mean(segs)
    if mean == 0:
        return 0.0
    cv = _stats.stdev(segs) / mean if len(segs) > 1 else 0.0
    return mean / (1.0 + cv)


def _filter_markdown_matches(matches: list[re.Match[str]], text: str) -> list[re.Match[str]]:
    """Markdown-heading post-filter: require blank line above + below.

    The regex matches every ``## Foo`` line; a heading inside a
    prose paragraph (``some sentence.\n## Note: ...``) shouldn't
    count as a chapter break.
    """
    kept: list[re.Match[str]] = []
    for m in matches:
        start = m.start()
        end = m.end()
        # Above: BOF, or the previous non-newline char is preceded
        # by a blank line.
        above_ok = start == 0 or text[max(0, start - 2) : start] == "\n\n"
        # Below: EOF, or the next char chain is ``\n\n`` or just ``\n``
        # at end of text.
        tail = text[end : end + 2]
        below_ok = end == len(text) or tail.startswith("\n\n") or tail == "\n"
        if above_ok and below_ok:
            kept.append(m)
    return kept


def _filter_allcaps_matches(matches: list[re.Match[str]]) -> list[re.Match[str]]:
    """All-caps post-filter: reject screenplay scene cues + low alpha ratio.

    Real chapter headers (``THE FIRST ENCOUNTER``) are mostly letters.
    Screenplay scene cues (``INT. KITCHEN — DAY``) end in a content
    word but are short enough that the regex would still bite; the
    ratio guard rejects them when the alpha share dips below 80%.
    Rows ending in ``,;:`` are usually mid-sentence fragments.
    """
    kept: list[re.Match[str]] = []
    for m in matches:
        title = m.group("title").strip()
        if not title:
            continue
        if title[-1] in ",;":
            continue
        alpha = sum(1 for c in title if c.isalpha())
        if alpha == 0 or alpha / len(title) < 0.8:
            continue
        kept.append(m)
    return kept


def _parse_chapters(text: str) -> list[dict[str, Any]]:
    """Split text into chapters via scored heading patterns + fallbacks.

    Pattern set tried (Task 8 — scoring, not first-match):
      1. Markdown ``## Title`` headings (blank-line-anchored)
      2. Prose ``Chapter 1`` / ``CHAPTER IV`` / ``chap. one``
      3. Roman numerals ``II.`` (length ≥ 2 — no lone ``I``)
      4. All-caps single-line headings (≥ 80% alpha, no trailing
         ``,;``)
      5. ``---`` horizontal-rule separators (unscored fallback)
      6. Single chapter (final fallback)

    Highest-scoring pattern above ``_SCORE_THRESHOLD`` wins. The
    score is mean-segment-length / (1 + CV); shorter than 500 chars
    per segment automatically scores 0.
    """
    candidates: list[tuple[float, list[re.Match[str]]]] = []

    # Inlined dispatch: post-filters have different signatures
    # (markdown wants ``(matches, text)``; all-caps wants
    # ``(matches,)``; the others take no post-filter), so keep the
    # call sites explicit instead of trying to unify them through a
    # shared callable.
    for pattern in (
        _CHAPTER_PATTERN_MARKDOWN,
        _CHAPTER_PATTERN_PROSE,
        _CHAPTER_PATTERN_ROMAN,
        _CHAPTER_PATTERN_ALLCAPS,
    ):
        compiled = re.compile(pattern)
        matches = list(compiled.finditer(text))
        if pattern is _CHAPTER_PATTERN_MARKDOWN:
            matches = _filter_markdown_matches(matches, text)
        elif pattern is _CHAPTER_PATTERN_ALLCAPS:
            matches = _filter_allcaps_matches(matches)
        score = _score_chapter_split(matches, text)
        if score > 0:
            candidates.append((score, matches))

    if candidates:
        best_score, best_matches = max(candidates, key=lambda c: c[0])
        if best_score >= _SCORE_THRESHOLD:
            chapters: list[dict[str, Any]] = []
            prologue = text[: best_matches[0].start()].strip()
            if prologue:
                chapters.append({"title": "Introduction", "text": prologue})
            for i, m in enumerate(best_matches):
                start = m.end()
                end = best_matches[i + 1].start() if i + 1 < len(best_matches) else len(text)
                body = text[start:end].strip()
                if body:
                    chapters.append(
                        {
                            "title": (m.group("title") or "").strip()[:120],
                            "text": body,
                        }
                    )
            if chapters:
                return chapters

    # Horizontal-rule separators (unscored fallback — they're
    # explicit and rarely false-positive).
    sections = re.split(r"^---+$", text, flags=re.MULTILINE)
    if len(sections) > 1:
        return [
            {"title": f"Part {i + 1}", "text": s.strip()}
            for i, s in enumerate(sections)
            if s.strip()
        ]

    # Single-chapter final fallback.
    return [{"title": "Full Text", "text": text}]
