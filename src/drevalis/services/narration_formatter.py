"""Phase 2.10 — TTS-formatted narration.

Most TTS engines mishandle the same set of inputs:

* **Bare digits** — Edge TTS reads ``1947`` correctly in the en-US
  voices but stumbles on ``$1.7M`` (saying "dollar one point seven em");
  Piper's ONNX models often read short numbers as the literal Unicode
  codepoints when sentence-final.
* **Acronyms** — ``NASA`` is fine, ``IPO`` is fine, but ``COVID-19`` is
  "kuvid-nineteen" on most local voices and ``UAW`` is read letter-by-
  letter intermittently. Spelling on first use is the standard fix.
* **Parentheticals** — TTS reads them flat; the prompt explicitly bans
  them, but if one slips through we split into a separate sentence.
* **Em-dashes** — phrasing-level beats; convert to commas with a brief
  pause cue so synthesizers honour the breath rather than reading the
  literal character.
* **Ellipses** — trailing pause; same rationale.
* **Phonetic respelling** — only Edge TTS and ElevenLabs support
  ``<phoneme>`` / SSML escapes reliably. Piper / Kokoro ignore them.

The :func:`format_for_tts` entry point dispatches on the resolved
provider name and returns a new string. Both ``narration`` and
``narration_tts`` live on every scene; only the latter is rewritten so
the editor and frontend always show the original copy.

Rules are intentionally conservative — we never change meaning, only
phonetic delivery. A scene that's already TTS-clean returns ``None``
so callers can avoid persisting redundant data.
"""

from __future__ import annotations

import re

# ── Shared rules (applied for every provider) ────────────────────────


_PARENTHETICAL_RE = re.compile(r"\s*\(([^()]+)\)")
_EM_DASH_RE = re.compile(r"\s*[—–]\s*")
_ELLIPSIS_RE = re.compile(r"\.{3,}|…")


def _split_parentheticals(text: str) -> str:
    """Lift ``(parenthetical)`` out into its own sentence.

    "He arrived in 1947 (the same year as the Roswell incident)."
        → "He arrived in 1947. The same year as the Roswell incident."
    """

    def _replace(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if not inner:
            return ""
        # Capitalise the first character of the lifted clause.
        inner = inner[0].upper() + inner[1:]
        return f". {inner}"

    out = _PARENTHETICAL_RE.sub(_replace, text)
    # Collapse the synthesised double-period when the parenthetical
    # appeared at sentence-end (".. The same year." → ". The same year.")
    out = re.sub(r"\.{2,}", ".", out)
    return out


def _normalise_dashes(text: str) -> str:
    """Em-/en-dashes → comma + space. Honours TTS phrasing better than
    the literal character."""
    return _EM_DASH_RE.sub(", ", text)


def _normalise_ellipsis(text: str) -> str:
    """Ellipses → period + trailing space; the synthesiser then renders
    it as a single sentence-final pause rather than the three-dot beat
    most voices read as a stutter."""
    return _ELLIPSIS_RE.sub(". ", text)


# ── Number / acronym helpers ─────────────────────────────────────────


_MONEY_RE = re.compile(
    r"\$(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(million|billion|trillion|m|b|t)?\b", re.IGNORECASE
)
_DOLLAR_PLAIN_RE = re.compile(r"\$(\d+(?:\.\d+)?)\b")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _expand_money(text: str) -> str:
    """Render dollar amounts as words.

    "$1.7M" → "1.7 million dollars"
    "$50" → "50 dollars"
    """

    def _suffix(amount: str, scale: str | None) -> str:
        scale_map = {
            "m": "million",
            "b": "billion",
            "t": "trillion",
        }
        if scale:
            scale_word = scale_map.get(scale.lower(), scale.lower())
            return f"{amount} {scale_word} dollars"
        return f"{amount} dollars"

    def _replace_full(match: re.Match[str]) -> str:
        return _suffix(match.group(1), match.group(2))

    out = _MONEY_RE.sub(_replace_full, text)
    out = _DOLLAR_PLAIN_RE.sub(lambda m: f"{m.group(1)} dollars", out)
    return out


def _expand_pct(text: str) -> str:
    return _PCT_RE.sub(lambda m: f"{m.group(1)} percent", text)


# Acronyms that benefit from explicit dotted spelling on first use.
# Limited to the ones we've actually observed mispronounced — adding
# every acronym would over-correct (NASA, FBI, CEO are fine).
_PROBLEMATIC_ACRONYMS: tuple[str, ...] = (
    "COVID-19",
    "UAW",
    "ICBM",
    "DARPA",
    "JPEG",
    "MPEG",
)


def _spell_acronyms_first_use(text: str) -> str:
    """On the first occurrence of a known-problematic acronym, append a
    parenthetical-free dotted spelling. We don't strip subsequent uses
    — the cost of saying it twice is low; the cost of saying ``UAW`` as
    one syllable on every appearance is high."""
    for acronym in _PROBLEMATIC_ACRONYMS:
        # Word-boundary match, case-sensitive (acronyms are uppercase).
        pattern = re.compile(rf"\b{re.escape(acronym)}\b")
        match = pattern.search(text)
        if match:
            spelled = ". ".join(acronym.replace("-", "")) + "."
            text = text[: match.end()] + f" ({spelled})" + text[match.end() :]
            # Only do the first occurrence per acronym.
            text = re.sub(rf"\b{re.escape(acronym)} \(([^)]+)\)\s+\1", acronym, text)
    return text


# ── Per-provider rule sets ────────────────────────────────────────────


def _format_edge(text: str) -> str:
    """Edge TTS — supports SSML; strong number reading; weak on
    ``$X.YM`` patterns and ellipses."""
    out = text
    out = _split_parentheticals(out)
    out = _normalise_dashes(out)
    out = _normalise_ellipsis(out)
    out = _expand_money(out)
    out = _expand_pct(out)
    out = _spell_acronyms_first_use(out)
    return out


def _format_elevenlabs(text: str) -> str:
    """ElevenLabs — best-in-class number reading; mostly the shared
    parenthetical/dash/ellipsis cleanup."""
    out = text
    out = _split_parentheticals(out)
    out = _normalise_dashes(out)
    out = _normalise_ellipsis(out)
    # ElevenLabs handles money + pct natively; only spell out the
    # genuinely-problematic acronyms.
    out = _spell_acronyms_first_use(out)
    return out


def _format_piper(text: str) -> str:
    """Piper — local ONNX, very literal. Spell out everything."""
    out = text
    out = _split_parentheticals(out)
    out = _normalise_dashes(out)
    out = _normalise_ellipsis(out)
    out = _expand_money(out)
    out = _expand_pct(out)
    out = _spell_acronyms_first_use(out)
    return out


def _format_kokoro(text: str) -> str:
    """Kokoro — better than Piper at numbers, similar to Edge for
    parentheticals and dashes."""
    out = text
    out = _split_parentheticals(out)
    out = _normalise_dashes(out)
    out = _normalise_ellipsis(out)
    out = _expand_money(out)
    out = _expand_pct(out)
    out = _spell_acronyms_first_use(out)
    return out


_PROVIDER_FORMATTERS = {
    "edge": _format_edge,
    "edge_tts": _format_edge,
    "elevenlabs": _format_elevenlabs,
    "comfyui_elevenlabs": _format_elevenlabs,
    "piper": _format_piper,
    "kokoro": _format_kokoro,
}


def format_for_tts(narration: str, provider: str | None) -> str | None:
    """Return a TTS-formatted variant of *narration*, or ``None`` when
    the rewrite would be identical to the input.

    *provider* is the resolved provider key (``edge`` / ``piper`` /
    ``kokoro`` / ``elevenlabs`` / ``comfyui_elevenlabs``). Unknown
    providers return ``None`` — we'd rather fall back to the original
    narration than ship a half-applied rewrite.
    """
    if not narration or not provider:
        return None

    formatter = _PROVIDER_FORMATTERS.get(provider.lower())
    if formatter is None:
        return None

    cleaned = formatter(narration)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned == narration.strip():
        return None
    return cleaned


__all__ = ["format_for_tts"]
