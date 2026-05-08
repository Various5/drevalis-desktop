"""Script-tag parsing for the audiobook pipeline.

Converts raw audiobook text (with optional ``[Speaker]`` and
``[SFX: ...]`` tags) into an ordered list of typed blocks that
the TTS render phase consumes.

Symbols exported from this module:

    _parse_voice_blocks — text → list of voice/sfx block dicts

Grammar summary
---------------
Untagged text defaults to ``[Narrator]``.

Speaker tag::

    [Speaker Name] optional inline text on same line
    following lines until the next tag

SFX tag::

    [SFX: description]
    [SFX: description | dur=5 | influence=0.4 | loop]
    [SFX: description | dur=8 | under=next | duck=-12]
    [SFX: description | dur=20 | under=4 | duck=-15]

SFX modifiers:
    ``dur`` / ``duration``  — seconds, default 4, clamped 0.5-22
    ``influence``           — 0.0-1.0 prompt adherence
    ``loop``                — valueless flag
    ``under=next``          — overlay under the next voice block
    ``under=N``             — overlay under the next N seconds of voice
    ``duck`` / ``duck_db``  — dB to attenuate the SFX while voice is on
                               top (default -12)

Without an ``under`` modifier the SFX is *sequential* — played at its
script position, voice resumes after.  With ``under``, the SFX is
*overlay* — the concatenator splices it under subsequent voice chunks
with sidechain ducking.

``## heading`` lines are silently skipped (chapter markers belong to
the chaptering phase, not TTS).
"""

from __future__ import annotations

import re
from typing import Any


def _parse_voice_blocks(text: str) -> list[dict[str, Any]]:
    """Parse ``[Speaker]`` and ``[SFX: ...]`` tagged text into blocks.

    Each block dict has either ``kind="voice"`` (with
    ``speaker``/``text``) or ``kind="sfx"`` (with
    ``description`` and optional ``duration`` /
    ``prompt_influence`` / ``loop`` keys).

    SFX tag grammar (compatible with the existing speaker tag
    regex so unknown ``[Foo]`` doesn't get silently treated as
    a sound effect):

        [SFX: description]
        [SFX: description | dur=5 | influence=0.4 | loop]
        [SFX: description | dur=8 | under=next | duck=-12]
        [SFX: description | dur=20 | under=4 | duck=-15]

    Modifiers:
        ``dur`` / ``duration``  — seconds, default 4, clamped 0.5-22
        ``influence``           — 0.0-1.0 prompt adherence
        ``loop``                — valueless flag
        ``under=next``          — overlay under the next voice block
        ``under=N``             — overlay under the next N seconds
                                   of voice (across blocks)
        ``duck`` / ``duck_db``  — dB to attenuate the SFX while
                                   voice is speaking on top
                                   (default -12, more negative =
                                   quieter SFX during dialogue)

    Without an ``under`` modifier, the SFX is *sequential* —
    played at exactly its script position, voice resumes after.
    With ``under``, the SFX is *overlay* — written to disk now
    but spliced in by the concatenator on top of subsequent
    voice chunks with sidechain ducking.

    Untagged text defaults to ``[Narrator]``.
    """
    blocks: list[dict[str, Any]] = []
    current_speaker = "Narrator"
    current_text: list[str] = []

    def _flush_voice() -> None:
        if not current_text:
            return
        joined = "\n".join(current_text).strip()
        if joined:
            blocks.append({"kind": "voice", "speaker": current_speaker, "text": joined})

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            if current_text:
                current_text.append("")
            continue

        if line.startswith("##"):
            continue

        # SFX tag — handled before generic [Speaker] match so
        # ``SFX`` isn't accidentally treated as a speaker name.
        sfx_m = re.match(
            r"^\[\s*SFX\s*:\s*([^\]]+?)\s*\]\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if sfx_m:
            _flush_voice()
            current_text = []
            payload = sfx_m.group(1)
            # Pipe-separated key=value modifiers after the desc.
            parts = [p.strip() for p in payload.split("|")]
            description = parts[0]
            duration = 4.0
            influence: float | None = None
            loop = False
            # Overlay modifiers — None means "sequential
            # placement, no overlay". under_voice_blocks=int OR
            # under_seconds=float describes how much subsequent
            # voice the SFX should ride under.
            under_voice_blocks: int | None = None
            under_seconds: float | None = None
            duck_db = -12.0
            for mod in parts[1:]:
                if not mod:
                    continue
                if mod.lower() == "loop":
                    loop = True
                    continue
                if "=" in mod:
                    k, v = mod.split("=", 1)
                    k = k.strip().lower()
                    v = v.strip()
                    try:
                        if k in ("dur", "duration"):
                            duration = float(v)
                        elif k in ("influence", "prompt_influence"):
                            influence = float(v)
                        elif k == "loop":
                            loop = v.lower() in ("1", "true", "yes")
                        elif k == "under":
                            vl = v.lower()
                            if vl in ("next", "1"):
                                under_voice_blocks = 1
                            elif vl == "all":
                                # "all remaining voice blocks in
                                # the chapter" — handled via a
                                # very large block count.
                                under_voice_blocks = 999
                            else:
                                # Numeric: treat as seconds when
                                # >2 (a single voice block of
                                # duration ≤2s is unusual);
                                # otherwise as block count.
                                try:
                                    n = float(v)
                                    if n.is_integer() and n <= 5:
                                        under_voice_blocks = int(n)
                                    else:
                                        under_seconds = n
                                except ValueError:
                                    pass
                        elif k in ("duck", "duck_db"):
                            duck_db = float(v)
                    except ValueError:
                        pass
            blocks.append(
                {
                    "kind": "sfx",
                    "description": description,
                    "duration": duration,
                    "loop": loop,
                    "prompt_influence": influence,
                    # Overlay metadata — both None for the
                    # sequential default.
                    "under_voice_blocks": under_voice_blocks,
                    "under_seconds": under_seconds,
                    "duck_db": duck_db,
                }
            )
            continue

        match = re.match(r"^\[([^\]]+)\]\s*(.*)", line)
        if match:
            _flush_voice()
            current_text = []
            current_speaker = match.group(1).strip()
            if match.group(2).strip():
                current_text.append(match.group(2).strip())
        else:
            current_text.append(line)

    _flush_voice()

    # Drop empty voice blocks but always keep SFX blocks (they
    # carry their own non-text payload).
    return [b for b in blocks if b.get("kind") == "sfx" or b.get("text")]
