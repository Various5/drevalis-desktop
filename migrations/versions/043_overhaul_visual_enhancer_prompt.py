"""Overhaul the ``Scene Visual Enhancer`` prompt template.

Phase 2.4 of the content quality overhaul. Pairs with the
``_DefaultPromptDict`` substitution fix in
``services/pipeline/_monolith.py`` — the new user template uses
``{scene_prompt}``, ``{style}``, ``{character}``, which the orchestrator
substitutes via ``format_map``.

The old prompt content is stored as constants below so the
down-migration restores the prior state.

Revision ID: 043
Revises: 042
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "043"
down_revision: str | None = "042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ──────────────────────────────────────────────────────────────────────
# New prompt content (Phase 2.4) — what we WRITE on upgrade.
# ──────────────────────────────────────────────────────────────────────

_NEW_VISUAL_ENHANCER_SYSTEM = """You rewrite a single image generation prompt to be specific, voiced, and free of cargo-cult tokens.

REQUIRED — every output prompt contains:
1. CAMERA FRAMING — exactly one of: close-up, medium, wide, overhead, low-angle, over-the-shoulder, eye-level, three-quarter
2. LIGHTING — named: golden hour, overcast soft, harsh midday, candlelit, neon, sodium streetlight, blue hour, fluorescent flicker, single-bulb practical
3. CONCRETE SUBJECT NOUN — name the literal thing being shown ("a brass sextant on stained linen" not "a scene of seafaring")
4. ATMOSPHERE OR DETAIL — one specific texture, weather, or material (rain on tarmac, dust motes, salt rust, wet cobblestone)

BANNED TOKENS — remove these from the input if present, never add them:
masterpiece, 8k, 4k, ultra detailed, ultra realistic, ultrarealistic, hyper realistic, hyperrealistic, high quality, best quality, professional, trending on artstation, award winning. Use "cinematic" only when followed by a specific lens or technique (anamorphic, shallow DOF, Dutch angle, lens flare).

STYLE — match the style parameter provided. If "noir" → contrast, hard shadows, rain. If "kodachrome 70s" → warm cast, slight grain, period-correct subjects. If empty, omit a style descriptor entirely.

OUTPUT — only the rewritten prompt, one line, no quotes, no commentary, no preamble."""


_NEW_VISUAL_ENHANCER_USER = """Original prompt:
{scene_prompt}

Style target: {style}

Character appearance (only relevant if a person is shown): {character}

Rewrite the prompt."""


# ──────────────────────────────────────────────────────────────────────
# Old prompt content (best-known prior state) — what we RESTORE on
# downgrade. Matches the row that shipped before the overhaul.
# ──────────────────────────────────────────────────────────────────────

_OLD_VISUAL_ENHANCER_SYSTEM = """You are a visual prompt engineer. Refine the given image generation prompt to be more specific, detailed, and visually striking.
Output ONLY the refined prompt text — no quotes, no commentary."""


_OLD_VISUAL_ENHANCER_USER = """Refine this prompt: {scene_prompt}"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE prompt_templates SET system_prompt = :sp, user_prompt_template = :up "
            "WHERE template_type = 'visual' AND name = 'Scene Visual Enhancer'"
        ),
        {"sp": _NEW_VISUAL_ENHANCER_SYSTEM, "up": _NEW_VISUAL_ENHANCER_USER},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE prompt_templates SET system_prompt = :sp, user_prompt_template = :up "
            "WHERE template_type = 'visual' AND name = 'Scene Visual Enhancer'"
        ),
        {"sp": _OLD_VISUAL_ENHANCER_SYSTEM, "up": _OLD_VISUAL_ENHANCER_USER},
    )
