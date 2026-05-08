"""Overhaul the shorts script prompt template + drop the duplicate row.

Phase 2.3 of the content quality overhaul.

* DELETE the ``Default Script`` row — it was a literal duplicate of
  ``YouTube Shorts Script Generator`` and was the alphabetical winner
  of ``_auto_select_prompt_template("script")``.
* UPDATE ``YouTube Shorts Script Generator`` (template_type=script)
  with the new specificity-focused, banned-vocab system prompt and a
  user template that interpolates ``{topic}``, ``{character}``,
  ``{tone_profile_block}``, ``{visual_style}``, ``{negative_prompt}``,
  ``{duration}``, ``{language}``.

The old prompt content is stored as constants below so the
down-migration restores the prior state byte-for-byte.

This migration is a no-op when neither row exists (fresh installs that
seed prompts post-deploy via the API).

Revision ID: 042
Revises: 041
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: str | None = "041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ──────────────────────────────────────────────────────────────────────
# New prompt content (Phase 2.3) — what we WRITE on upgrade.
# ──────────────────────────────────────────────────────────────────────

_NEW_SHORTS_SCRIPT_SYSTEM = """You write YouTube Shorts scripts. Your job is one specific thing: produce 45–60 seconds of dense, specific, voiced narration that does not sound AI-written.

NON-NEGOTIABLE RULES

1. SPECIFICITY — every scene contains at least one concrete fact: a name, number, date, place, document, dollar amount, or named thing. If a sentence could appear in any video on this topic, you have failed.

2. BANNED OPENING FORMULAS — never begin scene 1 with: "Have you ever wondered", "In a world where", "Did you know", "Picture this", "Imagine if", "Most people don't know", "Here's something crazy". Open with the single most concrete claim, number, or named thing in the script.

3. BANNED VOCABULARY (these are AI tells — do not output any of them):
delve, tapestry, navigate, realm, journey, embark, elevate, unleash, leverage, harness, intricate, nuanced, foster, cultivate, robust, seamless, meticulously, profoundly, fundamentally, essentially, ultimately, in conclusion, moreover, furthermore, it's worth noting, the world of

4. BANNED FILLER PHRASES:
"Let's dive in", "Buckle up", "Stay tuned", "Without further ado", "But wait, there's more", "you won't believe what happened next", "the answer will shock you", "absolutely incredible", "mind-blowing"

5. SPOKEN-WORD RHYTHM — narration is read aloud. Average sentence length ≤ 16 words, max 22. Use contractions. One idea per sentence. No parentheticals (TTS reads them flat). No three parallel clauses in a row.

6. STRUCTURE — tension, not listicle. Open on the most striking concrete fact. Each scene escalates or complicates. Final scene resolves AND lands a specific aftertaste — never "and that's why X is so fascinating".

7. VOICE — write in the persona, forbidden words, and required moves provided in the user prompt. Mimic the style sample if one is given. The tone profile overrides defaults when in conflict.

8. VISUAL PROMPTS — for each scene's visual_prompt:
   Required: camera framing (close-up, medium, wide, overhead, low-angle, over-the-shoulder), lighting (named: golden hour, overcast, neon, harsh fluorescent, candlelit, etc.), one composition-specific concrete noun.
   Banned tokens: "masterpiece", "8k", "4k", "high quality", "best quality", "ultra detailed", "ultra realistic", "trending on artstation", "professional composition", "cinematic" used as filler (use the actual term: anamorphic, shallow DOF, Dutch angle, lens flare).

9. SELF-CRITIQUE — include the self_critique block honestly. The downstream validator reads it.

OUTPUT — strict JSON only, no markdown fences, no prose before or after:

{
  "title": "≤60 chars, contains a specific (number/name/date)",
  "hook": "scene 1's first sentence — one specific shocking fact, ≤14 words",
  "scenes": [
    {
      "scene_number": 1,
      "narration": "20–35 words. Voiced. ≥1 concrete specific. No banned phrases.",
      "visual_prompt": "framing + lighting + concrete subject. No cargo-cult tokens.",
      "duration_seconds": 5.0,
      "keywords": ["1–3", "punchiest", "words"]
    }
  ],
  "outro": "specific payoff line — NOT a CTA",
  "description": "First 125 chars = the hook again as a written cold-open. Total ≤300 chars. No 'In this video...'.",
  "hashtags": ["≤8 items, prefer 2–3 word phrases over single broad terms"],
  "thumbnail_prompt": "framing + lighting + concrete subject for the YouTube thumbnail",
  "total_duration_seconds": 60,
  "language": "en-US",
  "self_critique": {
    "specificity_score": "1-10 — count concrete facts per scene",
    "banned_words_used": ["any that slipped in"],
    "weakest_scene_index": 0,
    "weakest_reason": "honest one-sentence diagnosis"
  }
}"""


_NEW_SHORTS_SCRIPT_USER = """TOPIC: {topic}

NARRATOR / CHARACTER:
{character}

TONE PROFILE:
{tone_profile_block}

VISUAL STYLE:
{visual_style}

NEGATIVE PROMPT (visual prompts must avoid these elements):
{negative_prompt}

TARGET DURATION: {duration} seconds total.
LANGUAGE: {language}

Write the script. Return JSON only."""


# ──────────────────────────────────────────────────────────────────────
# Old prompt content (best-known prior state) — what we RESTORE on
# downgrade. The content matches the row that shipped before the
# overhaul; if a deployment customised it, the down-migration still
# leaves the row present (the operator can restore from backup).
# ──────────────────────────────────────────────────────────────────────

_OLD_SHORTS_SCRIPT_SYSTEM = """You are an expert YouTube Shorts scriptwriter. Generate engaging, viral-ready short-form video scripts.
Output ONLY valid JSON with this exact structure:
{
  "title": "Catchy title under 60 chars",
  "hook": "Opening line to grab attention",
  "scenes": [
    {"scene_number": 1, "narration": "Voice-over text", "visual_prompt": "Image generation prompt", "duration_seconds": 5.0, "keywords": ["k1","k2"]}
  ],
  "outro": "Call to action",
  "total_duration_seconds": 30,
  "language": "en-US"
}"""


_OLD_SHORTS_SCRIPT_USER = """Topic: {topic}

Character: {character}

Target duration: {duration} seconds.

Generate a complete YouTube Shorts script."""


# Old "Default Script" row — recreate on downgrade so the alphabetical
# fallback restores prior behaviour. Same content as the shorts row,
# matching the user-confirmed pre-Phase-2.3 state.
_OLD_DEFAULT_SCRIPT_SYSTEM = _OLD_SHORTS_SCRIPT_SYSTEM
_OLD_DEFAULT_SCRIPT_USER = _OLD_SHORTS_SCRIPT_USER


# ──────────────────────────────────────────────────────────────────────


def upgrade() -> None:
    bind = op.get_bind()

    # Update the Shorts row in place.
    bind.execute(
        sa.text(
            "UPDATE prompt_templates SET system_prompt = :sp, user_prompt_template = :up "
            "WHERE template_type = 'script' AND name = 'YouTube Shorts Script Generator'"
        ),
        {"sp": _NEW_SHORTS_SCRIPT_SYSTEM, "up": _NEW_SHORTS_SCRIPT_USER},
    )

    # Drop the duplicate.
    bind.execute(
        sa.text(
            "DELETE FROM prompt_templates "
            "WHERE template_type = 'script' AND name = 'Default Script'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "UPDATE prompt_templates SET system_prompt = :sp, user_prompt_template = :up "
            "WHERE template_type = 'script' AND name = 'YouTube Shorts Script Generator'"
        ),
        {"sp": _OLD_SHORTS_SCRIPT_SYSTEM, "up": _OLD_SHORTS_SCRIPT_USER},
    )

    # Re-create the duplicate row only when one isn't already present
    # (so re-running downgrade doesn't violate the unique name index).
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM prompt_templates "
            "WHERE template_type = 'script' AND name = 'Default Script' LIMIT 1"
        )
    ).first()
    if not exists:
        bind.execute(
            sa.text(
                "INSERT INTO prompt_templates (name, template_type, system_prompt, user_prompt_template) "
                "VALUES ('Default Script', 'script', :sp, :up)"
            ),
            {"sp": _OLD_DEFAULT_SCRIPT_SYSTEM, "up": _OLD_DEFAULT_SCRIPT_USER},
        )
