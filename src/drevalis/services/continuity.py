"""LLM-driven continuity checker.

Runs on an episode's script BEFORE generation. For each adjacent scene
pair, asks the LLM whether the transition makes narrative and visual
sense. Returns a list of issues the frontend can surface between scene
cards as yellow warning dots.

No-op (returns []) when no LLM config is available.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any

from drevalis.schemas.script import EpisodeScript, SceneScript
from drevalis.services.llm import LLMService, extract_json


@dataclass(frozen=True)
class ContinuityIssue:
    """One flagged transition between two adjacent scenes."""

    from_scene: int
    to_scene: int
    severity: str  # "info" | "warn" | "fail"
    issue: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_scene": self.from_scene,
            "to_scene": self.to_scene,
            "severity": self.severity,
            "issue": self.issue,
            "suggestion": self.suggestion,
        }


_SYSTEM = (
    "You are a shot-list continuity editor. For each adjacent scene pair "
    "you're given, decide whether the transition is coherent. Look for "
    "tense / POV / location / character jumps, unresolved pronoun "
    "references, visual-prompt contradictions, and pacing whiplash.\n\n"
    "Return ONLY valid JSON in this exact shape:\n"
    "{\n"
    '  "issues": [\n'
    '    {"from_scene": 1, "to_scene": 2, "severity": "warn",\n'
    '     "issue": "<one short sentence>",\n'
    '     "suggestion": "<one short fix>"}\n'
    "  ]\n"
    "}\n"
    "Only emit an issue if the transition is genuinely off — silence is "
    "fine. Severity: 'info' minor, 'warn' noticeable, 'fail' would confuse "
    "the viewer."
)


async def check_continuity(
    *,
    script: EpisodeScript,
    llm_service: LLMService,
    llm_config: Any,
) -> list[ContinuityIssue]:
    """Ask the LLM to flag bad transitions in the script.

    Returns an empty list when the LLM returns non-JSON, when no issues
    are found, or on any transport error (best-effort pre-flight check).
    """
    if len(script.scenes) < 2:
        return []

    provider = llm_service.get_provider(llm_config)
    user_prompt = "Scenes:\n\n" + "\n\n".join(_format_scene(s) for s in script.scenes)

    try:
        result = await provider.generate(
            _SYSTEM,
            user_prompt,
            temperature=0.2,
            max_tokens=1500,
            json_mode=True,
        )
    except Exception:
        return []

    text = getattr(result, "content", None) or getattr(result, "text", "") or ""
    try:
        data = _json.loads(extract_json(text))
    except Exception:
        return []

    out: list[ContinuityIssue] = []
    for raw in (data.get("issues") or [])[:20]:
        try:
            fs = int(raw["from_scene"])
            ts = int(raw["to_scene"])
        except (KeyError, TypeError, ValueError):
            continue
        sev = str(raw.get("severity") or "warn").lower()
        if sev not in ("info", "warn", "fail"):
            sev = "warn"
        out.append(
            ContinuityIssue(
                from_scene=fs,
                to_scene=ts,
                severity=sev,
                issue=str(raw.get("issue") or "")[:240],
                suggestion=str(raw.get("suggestion") or "")[:240],
            )
        )
    return out


def _format_scene(s: SceneScript) -> str:
    return (
        f"Scene {s.scene_number}:\n"
        f"  narration: {s.narration[:300]}\n"
        f"  visual: {s.visual_prompt[:200]}\n"
        f"  duration: {s.duration_seconds:.1f}s"
    )
