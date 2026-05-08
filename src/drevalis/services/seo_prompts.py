"""Shared SEO prompt + narration extraction.

Both ``YouTubeAdminService.get_or_generate_seo`` (inline at upload
time) and ``workers/jobs/seo.py:generate_seo_async`` (background) used
to ship near-duplicate prompts. They drifted: the worker version added
``hook`` and ``virality_score`` fields; the inline version did not.
Both also pre-dated the Phase 2.3 banned-vocab + specificity rules,
so the SEO description could land on YouTube as cargo-cult prose even
when the script's own description was clean.

This module is the single source of truth for both flows. The prompt
text mirrors the shorts script template's banned-vocab section so any
expansion happens in one place — the gate (``check_script_content``)
matches the same rule set, so a description that passes the prompt
should also pass the gate.

Behaviour notes:

* The ``hook`` and ``virality_score`` fields stay (the background job
  surfaces them to the UI) — the inline-at-upload-time call simply
  ignores them when they're not in its return shape.
* Description rules: never start with "In this video...", first 125
  characters mirror the script's hook (or topic) so YouTube's
  truncated preview still reads as a cold-open, total ≤ 500 chars.
* Hashtag rules match the longform sanitiser: max 8, no
  ``#viral``/``#fyp``/``#subscribe``, prefer 2–3 word phrases.
"""

from __future__ import annotations

# Mirror the shorts script template's rule blocks so the SEO output
# obeys the same constraints. Keeping the strings here (and not just
# import-from-prompts) avoids a runtime DB hit on every SEO call.
BANNED_VOCAB_BLOCK = (
    "BANNED VOCABULARY (do not output any of these AI tells):\n"
    "delve, tapestry, navigate, realm, journey, embark, elevate, "
    "unleash, leverage, harness, intricate, nuanced, foster, cultivate, "
    "robust, seamless, meticulously, profoundly, fundamentally, "
    "essentially, ultimately, in conclusion, moreover, furthermore, "
    "it's worth noting, the world of."
)


SEO_SYSTEM_PROMPT = (
    "You are a YouTube SEO writer. Generate optimised metadata for an "
    "uploaded video.\n\n"
    f"{BANNED_VOCAB_BLOCK}\n\n"
    "DESCRIPTION RULES:\n"
    '- Never begin with "In this video..." or any "In this <noun>..." '
    "opener. Open with the most concrete claim or named thing in the "
    "narration.\n"
    "- First 125 characters land before YouTube's read-more cut. They "
    "should read as a cold-open hook, not a description-of-a-video.\n"
    "- Total length ≤ 500 characters.\n"
    "- No CTAs unless the input narration explicitly contains one.\n\n"
    "HASHTAG RULES:\n"
    '- Max 8 items. No "#viral", "#fyp", "#subscribe" — they will be '
    "stripped downstream anyway.\n"
    "- Prefer 2–3 word long-tail phrases over single broad terms.\n\n"
    "Output ONLY valid JSON with this structure:\n"
    '{"title": "SEO title (≤ 60 chars, contains a specific name/number/date)", '
    '"description": "≤ 500 chars, see rules above", '
    '"hashtags": ["#tag1", "#tag2"], '
    '"tags": ["keyword1", "keyword2"], '
    '"hook": "single-sentence opening hook for the video itself", '
    '"virality_score": 1-10, '
    '"virality_reasoning": "one-sentence diagnosis"}'
)


def build_seo_user_prompt(
    *,
    title: str,
    narration: str,
    script_description: str = "",
) -> str:
    """Render the user-side SEO prompt with the script's existing
    description carried as a "preferred draft".

    When the script step has populated ``description`` (which it does
    starting in Phase 2.3 for shorts and from the outline for longform),
    we hand it to the LLM as a starting point so the SEO call doesn't
    discard the script step's careful work. Empty input narration falls
    back to the title so we never ship a literal empty user message.
    """
    body = narration.strip()[:1000] or title

    parts = [
        f"Video title: {title}",
        f"Narration: {body}",
    ]
    if script_description.strip():
        parts.append(
            "Existing description draft (already vetted — keep its "
            "phrasing where possible, only rewrite when it violates a "
            "rule above):\n"
            f"{script_description.strip()[:500]}"
        )
    parts.append("Generate the JSON now:")
    return "\n\n".join(parts)


__all__ = [
    "BANNED_VOCAB_BLOCK",
    "SEO_SYSTEM_PROMPT",
    "build_seo_user_prompt",
]
