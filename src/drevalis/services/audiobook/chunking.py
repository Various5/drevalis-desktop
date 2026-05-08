"""Text-chunking utilities for the audiobook TTS render phase.

Splits raw audiobook text into provider-sized chunks that fit within
each TTS provider's per-request character ceiling.  The bracket
invariant guarantees that ``[Speaker]`` and ``[SFX: ...]`` tags never
straddle a chunk boundary.

Symbols exported from this module:

    CHUNK_LIMITS         — per-provider max-chars map
    _chunk_limit         — look up the per-provider max_chars limit
    _split_text          — split text into chunks ≤ max_chars
    _split_long_sentence — comma-fallback for overlong sentences
    _repair_bracket_splits — post-pass: merge any split ``[...]`` tokens
"""

from __future__ import annotations

import re

# ── Per-provider chunk size (Task 12) ────────────────────────────────────────
# Pre-Task-12 every provider got ``max_chars=500``, which shipped ElevenLabs
# (Creator plan ceiling 2500 chars) ~5× more requests than necessary. Larger
# chunks also cut cache-key churn on text edits because changes touch fewer
# chunks. ``_DEFAULT_CHUNK_LIMIT`` is the conservative fallback for any
# provider not in the map.
_DEFAULT_CHUNK_LIMIT = 700

CHUNK_LIMITS: dict[str, int] = {
    "piper": 700,
    "kokoro": 900,
    "edge": 1200,
    # Longest-key-wins: ``comfyui_elevenlabs`` resolves before plain
    # ``elevenlabs``. The ComfyUI route also accepts 2200 — its
    # back-end is ElevenLabs, just a different request shape.
    "comfyui_elevenlabs": 2200,
    "elevenlabs": 2200,
}


def _chunk_limit(provider_name: str) -> int:
    """Return the per-provider ``max_chars`` (case-insensitive)."""
    name = provider_name.lower().replace("_", "")
    best: tuple[int, int] | None = None  # (key length, limit)
    for key, limit in CHUNK_LIMITS.items():
        normalised_key = key.replace("_", "")
        if normalised_key in name and (best is None or len(normalised_key) > best[0]):
            best = (len(normalised_key), limit)
    return best[1] if best is not None else _DEFAULT_CHUNK_LIMIT


def _split_text(text: str, max_chars: int) -> list[str]:
    """Split text into chunks ≤ *max_chars*, bracket-safe (Task 12).

    Priority:

      1. Paragraph boundaries (``\\n\\n``) — pack whole paragraphs
         when they fit.
      2. Sentence boundaries (``. ! ?``) inside any oversize
         paragraph.
      3. Comma fallback for sentences that themselves exceed
         ``max_chars`` (rare).

    Bracket invariant: split points that fall *inside* a ``[...]``
    group are skipped so a ``[SFX: ...]`` or ``[Speaker]`` tag
    never lands across two chunks.
    """
    text = text.strip()
    if not text:
        return [""]
    if len(text) <= max_chars:
        return [text]

    # 1. Paragraph split → list of paragraph strings.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    # 2. Within each paragraph, sentence-split if too long.
    units: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            units.append(para)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", para)
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) <= max_chars:
                units.append(sent)
            else:
                # 3. Comma fallback for runaway sentences.
                units.extend(_split_long_sentence(sent, max_chars))

    # Greedy pack units, preferring ``\n\n`` between paragraph
    # units that started on a paragraph boundary. We approximate
    # that with a single space — the TTS provider doesn't see
    # paragraph spacing as a pause cue; the audiobook's silence
    # gaps come from the inter-chunk silence files anyway.
    chunks: list[str] = []
    current = ""
    for unit in units:
        if not unit:
            continue
        if current and len(current) + 1 + len(unit) > max_chars:
            chunks.append(current)
            current = unit
        else:
            current = f"{current} {unit}" if current else unit
    if current:
        chunks.append(current)

    # Bracket invariant: shift any boundary that splits a
    # ``[...]`` token. Walk pairwise, repair in-place.
    chunks = _repair_bracket_splits(chunks)

    return chunks or [text]


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """Comma-fallback for a sentence longer than *max_chars*.

    Falls all the way back to a hard character split if even the
    comma-separated pieces exceed *max_chars* on their own (e.g.
    a URL or a long quoted block with no internal punctuation).
    """
    pieces = [p.strip() for p in re.split(r",\s+", sentence) if p.strip()]
    out: list[str] = []
    current = ""
    for piece in pieces:
        if len(piece) > max_chars:
            # Hard split — no smaller boundary available.
            if current:
                out.append(current)
                current = ""
            for i in range(0, len(piece), max_chars):
                out.append(piece[i : i + max_chars])
            continue
        if current and len(current) + 2 + len(piece) > max_chars:
            out.append(current)
            current = piece
        else:
            current = f"{current}, {piece}" if current else piece
    if current:
        out.append(current)
    return out or [sentence[:max_chars]]


def _repair_bracket_splits(chunks: list[str]) -> list[str]:
    """Ensure no chunk boundary splits a ``[...]`` token.

    Walk pairwise. If chunk N has an unclosed ``[`` and chunk N+1
    starts with the closing portion (contains a ``]`` before the
    next ``[``), shift the unclosed prefix forward into chunk N+1.
    Pathological inputs (deeply nested brackets, unmatched ``]``)
    return unchanged — bracket safety is a best-effort guarantee.
    """
    if len(chunks) < 2:
        return chunks
    out = list(chunks)
    i = 0
    while i < len(out) - 1:
        current = out[i]
        nxt = out[i + 1]
        # Find the last unmatched '[' in current.
        depth = 0
        last_open = -1
        for k, c in enumerate(current):
            if c == "[":
                depth += 1
                last_open = k
            elif c == "]":
                depth -= 1
        if depth > 0 and last_open >= 0 and "]" in nxt:
            # Move the trailing ``[...`` from current into nxt.
            tail = current[last_open:]
            out[i] = current[:last_open].rstrip()
            out[i + 1] = f"{tail} {nxt}".strip()
            if not out[i]:
                # Current is empty after the shift — drop it.
                del out[i]
                continue
        i += 1
    return out
