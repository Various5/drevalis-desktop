"""SEO + cross-platform publish + quality-report sub-routes.

Owns:
  * ``GET  /{episode_id}/seo-score``      — deterministic SEO heuristics
  * ``POST /{episode_id}/seo``            — enqueue LLM SEO generation
  * ``POST /{episode_id}/seo-preflight``  — richer pre-upload checks
  * ``POST /{episode_id}/seo-variants``   — LLM A/B title/desc/thumb prompts
  * ``POST /{episode_id}/publish-all``    — fan-out publish to YouTube + socials
  * ``POST /{episode_id}/continuity``     — LLM continuity check
  * ``POST /{episode_id}/quality-report`` — run quality gates against stored script

Extracted from ``_monolith.py`` (alpha.28). Inline response models live
here because they're not consumed outside the route file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.api.routes.episodes._helpers import _episode_service, logger
from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.core.license.deprecation import apply_deprecation_headers
from drevalis.core.redis import get_arq_pool
from drevalis.services.episode import (
    EpisodeNoScriptError,
    EpisodeNotFoundError,
    EpisodeService,
)

router = APIRouter(prefix="/api/v1/episodes", tags=["episodes"])


# ── Models ────────────────────────────────────────────────────────────────


class SEOCheck(BaseModel):
    id: str
    label: str
    pass_: bool = Field(alias="pass")
    severity: str  # "ok" | "warn" | "error" | "info"
    hint: str

    model_config = {"populate_by_name": True}


class SEOScoreResponse(BaseModel):
    overall_score: int  # 0 - 100
    grade: str  # "A" | "B" | "C" | "D"
    summary: str
    has_seo_metadata: bool
    checks: list[SEOCheck]


class PublishAllRequest(BaseModel):
    """Fan-out publish to every selected platform."""

    platforms: list[Literal["youtube", "tiktok", "instagram", "facebook", "x"]] = Field(
        ...,
        min_length=1,
        description="Platforms to publish to. Only platforms the episode's series + connected "
        "accounts cover will actually be enqueued; the rest are returned as skipped.",
    )
    title: str | None = Field(
        default=None,
        description="Override title. Defaults to the episode's SEO title or raw title.",
    )
    description: str | None = Field(
        default=None,
        description="Override description. Defaults to episode.metadata.seo.description or topic.",
    )
    privacy: Literal["public", "unlisted", "private"] = "public"


class PublishAllResponse(BaseModel):
    episode_id: str
    accepted: list[dict[str, Any]]
    skipped: list[dict[str, Any]]


class PreflightCheck(BaseModel):
    id: str
    severity: str  # "pass" | "warn" | "fail" | "info"
    title: str
    message: str
    suggestion: str | None = None


class PreflightResponse(BaseModel):
    score: int
    grade: str
    blocking: bool
    checks: list[PreflightCheck]


class VariantResponse(BaseModel):
    titles: list[str]
    thumbnail_prompts: list[str]
    descriptions: list[str]


class ContinuityIssueResponse(BaseModel):
    from_scene: int
    to_scene: int
    severity: str
    issue: str
    suggestion: str


class ContinuityResponse(BaseModel):
    issues: list[ContinuityIssueResponse]


class QualityReportResponse(BaseModel):
    """Result of running ``check_script_content`` against a stored script."""

    gate: str
    passed: bool
    issues: list[str]
    metrics: dict[str, Any]


def _grade_for(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 55:
        return "C"
    return "D"


# ── SEO heuristics (no LLM call) ─────────────────────────────────────────


@router.get(
    "/{episode_id}/seo-score",
    response_model=SEOScoreResponse,
    tags=["seo"],
    summary="Deterministic SEO heuristics for the current episode metadata",
)
async def get_seo_score(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> SEOScoreResponse:
    """Pure heuristics — no LLM call. Returns a list of pass/fail checks
    against YouTube-style SEO best practices."""
    try:
        episode = await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="episode_not_found",
        ) from exc

    meta = episode.metadata_ or {}
    seo = meta.get("seo") if isinstance(meta, dict) else None
    has_seo = isinstance(seo, dict)

    title = (seo or {}).get("title") or episode.title or ""
    description = (seo or {}).get("description") or (episode.topic or "")
    hashtags = list((seo or {}).get("hashtags") or [])
    tags = list((seo or {}).get("tags") or [])
    hook = (seo or {}).get("hook") or ""

    checks: list[SEOCheck] = []
    score = 0

    # Title length — YouTube shows the first 60-70 chars in search.
    tlen = len(title)
    if 45 <= tlen <= 70:
        checks.append(
            SEOCheck(
                id="title_length",
                label="Title length",
                pass_=True,
                severity="ok",
                hint=f"{tlen} chars — in the sweet spot.",
            )
        )
        score += 20
    elif tlen < 20:
        checks.append(
            SEOCheck(
                id="title_length",
                label="Title length",
                pass_=False,
                severity="error",
                hint=f"Only {tlen} chars — likely to underperform. Aim for 45-70.",
            )
        )
    elif tlen < 45:
        checks.append(
            SEOCheck(
                id="title_length",
                label="Title length",
                pass_=False,
                severity="warn",
                hint=f"{tlen} chars — try expanding toward 45-70 for better CTR.",
            )
        )
        score += 10
    else:  # > 70
        checks.append(
            SEOCheck(
                id="title_length",
                label="Title length",
                pass_=False,
                severity="warn",
                hint=f"{tlen} chars — will be truncated in search. Trim toward 60-65.",
            )
        )
        score += 10

    # Description length — >= 125 chars fills the visible snippet; >= 400 is ideal.
    dlen = len(description)
    if dlen >= 400:
        checks.append(
            SEOCheck(
                id="desc_length",
                label="Description depth",
                pass_=True,
                severity="ok",
                hint=f"{dlen} chars — plenty of room for context + links.",
            )
        )
        score += 20
    elif dlen >= 125:
        checks.append(
            SEOCheck(
                id="desc_length",
                label="Description depth",
                pass_=False,
                severity="warn",
                hint=f"{dlen} chars — enough for search snippet; expand toward 400 for more keyword coverage.",
            )
        )
        score += 12
    else:
        checks.append(
            SEOCheck(
                id="desc_length",
                label="Description depth",
                pass_=False,
                severity="error",
                hint=f"Only {dlen} chars. YouTube shows ~125 chars in search; add context, keywords, and a CTA.",
            )
        )

    # Tag count — 5-15 keywords is healthy.
    tag_count = len(tags)
    if 5 <= tag_count <= 15:
        checks.append(
            SEOCheck(
                id="tag_count",
                label="Keyword tags",
                pass_=True,
                severity="ok",
                hint=f"{tag_count} tags — good spread.",
            )
        )
        score += 15
    elif 1 <= tag_count < 5:
        checks.append(
            SEOCheck(
                id="tag_count",
                label="Keyword tags",
                pass_=False,
                severity="warn",
                hint=f"Only {tag_count} tags. Aim for 5-15 to help discovery.",
            )
        )
        score += 7
    elif tag_count > 15:
        checks.append(
            SEOCheck(
                id="tag_count",
                label="Keyword tags",
                pass_=False,
                severity="warn",
                hint=f"{tag_count} tags is over-tagging territory. Trim to 5-15 strongest.",
            )
        )
        score += 8
    else:
        checks.append(
            SEOCheck(
                id="tag_count",
                label="Keyword tags",
                pass_=False,
                severity="error",
                hint="No keyword tags — add 5-15 to help YouTube's algorithm place this.",
            )
        )

    # Hashtags — 3-5 is YouTube's own recommendation.
    htag_count = len(hashtags)
    if 3 <= htag_count <= 5:
        checks.append(
            SEOCheck(
                id="hashtag_count",
                label="Hashtags",
                pass_=True,
                severity="ok",
                hint=f"{htag_count} hashtags — matches YouTube's own guidance.",
            )
        )
        score += 10
    elif 1 <= htag_count < 3:
        checks.append(
            SEOCheck(
                id="hashtag_count",
                label="Hashtags",
                pass_=False,
                severity="warn",
                hint=f"Only {htag_count} hashtag(s). YouTube recommends 3-5 — add one or two more.",
            )
        )
        score += 5
    elif htag_count > 5:
        checks.append(
            SEOCheck(
                id="hashtag_count",
                label="Hashtags",
                pass_=False,
                severity="warn",
                hint=f"{htag_count} hashtags — YouTube caps at 15, but only the first 3 render in the title bar. Keep the strongest 3-5.",
            )
        )
        score += 5
    else:
        checks.append(
            SEOCheck(
                id="hashtag_count",
                label="Hashtags",
                pass_=False,
                severity="warn",
                hint="No hashtags set. Add 3-5 to appear in topical feeds.",
            )
        )

    # Hook — must be non-empty and fit in ~8 seconds of speech (~25 words).
    hook_words = len(hook.split())
    if 6 <= hook_words <= 25 and hook.strip():
        checks.append(
            SEOCheck(
                id="hook",
                label="Opening hook",
                pass_=True,
                severity="ok",
                hint=f"{hook_words}-word hook — fits the first 8-10 seconds.",
            )
        )
        score += 15
    elif hook.strip() and hook_words > 25:
        checks.append(
            SEOCheck(
                id="hook",
                label="Opening hook",
                pass_=False,
                severity="warn",
                hint=f"Hook is {hook_words} words — too long to land in the first 8 seconds. Tighten to 10-20.",
            )
        )
        score += 7
    elif hook.strip():
        checks.append(
            SEOCheck(
                id="hook",
                label="Opening hook",
                pass_=False,
                severity="warn",
                hint=f"Hook is only {hook_words} words — add a concrete claim or question.",
            )
        )
        score += 7
    else:
        checks.append(
            SEOCheck(
                id="hook",
                label="Opening hook",
                pass_=False,
                severity="error",
                hint="No hook set. Generate SEO metadata or write a 10-20 word opener — this is the single biggest retention lever.",
            )
        )

    # CTA — at least one of (subscribe, comment, like, follow) in the description.
    cta_patterns = ("subscribe", "comment", "like", "follow", "share")
    cta_hits = [w for w in cta_patterns if w in description.lower()]
    if cta_hits:
        checks.append(
            SEOCheck(
                id="cta",
                label="Call to action",
                pass_=True,
                severity="ok",
                hint=f"Found: {', '.join(cta_hits)}.",
            )
        )
        score += 10
    else:
        checks.append(
            SEOCheck(
                id="cta",
                label="Call to action",
                pass_=False,
                severity="warn",
                hint="No CTA in description. Add 'Subscribe for more…' or 'Comment if this helped' to lift engagement signals.",
            )
        )

    # Keyword density — at least one of the top-3 tags should appear in the description.
    if tags and description:
        d_lower = description.lower()
        matched = [t for t in tags[:5] if t.lower() in d_lower]
        if matched:
            checks.append(
                SEOCheck(
                    id="keyword_density",
                    label="Keyword reuse",
                    pass_=True,
                    severity="ok",
                    hint=f"Top tag(s) appear in description: {', '.join(matched)}.",
                )
            )
            score += 10
        else:
            checks.append(
                SEOCheck(
                    id="keyword_density",
                    label="Keyword reuse",
                    pass_=False,
                    severity="warn",
                    hint="None of your top tags appear in the description. Weave 1-2 in naturally to reinforce the topic.",
                )
            )
    else:
        checks.append(
            SEOCheck(
                id="keyword_density",
                label="Keyword reuse",
                pass_=False,
                severity="info",
                hint="Set keyword tags + description first, then this check will score.",
            )
        )

    # SEO-metadata freshness flag — info-only, doesn't move the score.
    if not has_seo:
        checks.append(
            SEOCheck(
                id="seo_generated",
                label="SEO metadata",
                pass_=False,
                severity="info",
                hint="Run 'Generate SEO' to replace these heuristics with LLM-optimised title/description/tags.",
            )
        )
    else:
        vs = (seo or {}).get("virality_score")
        if isinstance(vs, (int, float)) and vs > 0:
            checks.append(
                SEOCheck(
                    id="seo_generated",
                    label="SEO metadata",
                    pass_=True,
                    severity="info",
                    hint=f"LLM virality estimate: {vs}/10.",
                )
            )

    score = max(0, min(100, score))
    grade = _grade_for(score)

    error_count = sum(1 for c in checks if c.severity == "error")
    warn_count = sum(1 for c in checks if c.severity == "warn")

    if error_count:
        summary = f"{error_count} blocking issue(s) and {warn_count} improvement(s) flagged."
    elif warn_count:
        summary = f"Looks solid — {warn_count} optional improvement(s)."
    else:
        summary = "All heuristics green. Ready to publish."

    return SEOScoreResponse(
        overall_score=score,
        grade=grade,
        summary=summary,
        has_seo_metadata=has_seo,
        checks=checks,
    )


# ── LLM-driven SEO generation ────────────────────────────────────────────


@router.post(
    "/{episode_id}/seo",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Generate SEO-optimized metadata using AI",
)
async def generate_seo(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Enqueue SEO generation as a background job."""
    try:
        await svc.get_with_script_or_raise(episode_id)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(404, "Episode not found or has no script") from exc

    # Enqueue via the arq pool singleton (the plain Redis from get_redis has
    # no enqueue_job — using it here previously raised AttributeError -> 500).
    try:
        arq = get_arq_pool()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background worker not ready yet; try again in a moment.",
        ) from exc
    await arq.enqueue_job("generate_seo_async", str(episode_id))
    return {"status": "queued", "message": "SEO generation started in background"}


# ── SEO Pre-flight (Phase C) ─────────────────────────────────────────────


@router.post(
    "/{episode_id}/seo-preflight",
    response_model=PreflightResponse,
    tags=["seo"],
    summary="Pre-upload SEO pre-flight scoring",
)
async def seo_preflight(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> PreflightResponse:
    """Run the richer pre-upload checks on the current episode state.

    Does NOT hit the LLM. Combines stored SEO metadata (from
    ``generate_seo_async``) with the live script fields.
    """
    from drevalis.services.seo_preflight import preflight as run_preflight

    try:
        episode = await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc

    meta = episode.metadata_ or {}
    seo = meta.get("seo") if isinstance(meta, dict) else None
    seo = seo or {}

    script_payload = episode.script or {}
    hook_text: str = str((seo.get("hook") or script_payload.get("hook") or "") or "")

    content_format = getattr(episode, "content_format", "shorts") or "shorts"
    platform = "youtube_longform" if content_format == "longform" else "youtube_shorts"

    thumb_rel = await svc.get_thumbnail_asset_path(episode_id)
    thumb_path = Path(settings.storage_base_path) / thumb_rel if thumb_rel else None

    result = run_preflight(
        title=str(seo.get("title") or episode.title or ""),
        description=str(seo.get("description") or episode.topic or ""),
        hashtags=list(seo.get("hashtags") or []),
        tags=list(seo.get("tags") or []),
        hook_text=hook_text,
        hook_duration_seconds=None,
        thumbnail_path=thumb_path,
        platform=platform,  # type: ignore[arg-type]
    )
    return PreflightResponse.model_validate(result.to_dict())


# ── SEO variants (LLM-generated A/B options) ─────────────────────────────


@router.post(
    "/{episode_id}/seo-variants",
    response_model=VariantResponse,
    tags=["seo"],
    summary="Ask the LLM for alternate titles / thumbnails / descriptions",
)
async def seo_variants(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> VariantResponse:
    """Quick A/B options without mutating the episode. The frontend's
    pre-flight dialog offers one-click "Apply" for each suggestion.
    """
    import json as _json

    from drevalis.services.llm import LLMService, extract_json
    from drevalis.services.llm_config import LLMConfigService

    try:
        episode, _script = await svc.get_with_script_or_raise(episode_id)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc

    configs = (
        await LLMConfigService(
            db,
            settings.encryption_key,
            encryption_keys=settings.get_encryption_keys(),
        ).list_all()
    )[:1]
    if not configs:
        base_title = episode.title or "Untitled"
        return VariantResponse(
            titles=[
                base_title,
                f"{base_title} (you won't believe it)",
                f"I tried {base_title.lower()} — here's what happened",
                f"The real reason {base_title.lower()}",
                f"{base_title} explained in 60 seconds",
            ],
            thumbnail_prompts=[
                f"{base_title}, close-up, high contrast, 3-point lighting",
                f"{base_title}, split-screen before/after, bold text overlay",
                f"{base_title}, face-forward with shocked expression, bright colors",
            ],
            descriptions=[
                (episode.topic or base_title)[:200],
            ],
        )

    llm_service = LLMService(
        encryption_key=settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )
    provider = llm_service.get_provider(configs[0])
    narration = " ".join(
        (s.get("narration") or "") for s in (episode.script or {}).get("scenes") or []
    )

    system = (
        "You are a short-form video SEO editor. Return ONLY valid JSON in this shape:\n"
        '{"titles": ["...","...","...","...","..."],'
        '"thumbnail_prompts": ["...","...","..."],'
        '"descriptions": ["...","...","..."]}\n'
        "Titles: 5 alternates, ≤60 chars each, each with a different psychological angle "
        "(curiosity, outcome, contradiction, specificity, direct-benefit). "
        "Thumbnail prompts: 3 stills, each visually distinct, describe the shot not the title. "
        "Descriptions: 3 alternates ≤500 chars, first sentence is the hook."
    )
    user = (
        f"Original title: {episode.title}\n"
        f"Narration excerpt: {narration[:900]}\n\n"
        "Return the JSON now."
    )
    result = await provider.generate(system, user, temperature=0.8, max_tokens=1200, json_mode=True)
    try:
        data = _json.loads(extract_json(result.content))
    except Exception:
        data = {"titles": [], "thumbnail_prompts": [], "descriptions": []}

    return VariantResponse(
        titles=[str(t)[:100] for t in (data.get("titles") or [])][:5],
        thumbnail_prompts=[str(t)[:400] for t in (data.get("thumbnail_prompts") or [])][:5],
        descriptions=[str(t)[:500] for t in (data.get("descriptions") or [])][:5],
    )


# ── Cross-platform bulk publish ──────────────────────────────────────────


@router.post(
    "/{episode_id}/publish-all",
    response_model=PublishAllResponse,
    summary="Publish the finished episode to YouTube + connected social platforms in one shot",
    tags=["publishing"],
)
async def publish_all(
    episode_id: UUID,
    body: PublishAllRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    svc: EpisodeService = Depends(_episode_service),
) -> PublishAllResponse:
    """Cross-platform bulk publish.

    Iterates the platforms the caller selected. For each:

    - **youtube**: requires the episode's series to have ``youtube_channel_id``
      set. Creates a YouTubeUpload row; the worker's upload cron picks it up.
    - **tiktok** / **instagram**: requires a connected SocialPlatform row
      for that platform. Creates a SocialUpload row; the social worker picks
      it up.

    Each platform that can't be fulfilled (no connection, missing video,
    tier gate, etc.) is returned in ``skipped`` with a human-readable
    reason rather than aborting the whole request.
    """
    apply_deprecation_headers(response, "cross_platform_bulk")
    from drevalis.models.social_platform import SocialPlatform, SocialUpload
    from drevalis.models.youtube_channel import YouTubeUpload

    try:
        episode = await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc
    if episode.status not in ("review", "exported", "editing"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Episode must be in review/exported/editing; current status is '{episode.status}'.",
        )

    if await svc.get_video_asset_path(episode_id) is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Episode has no finished video yet. Generate / reassemble first.",
        )

    seo = (episode.metadata_ or {}).get("seo") if isinstance(episode.metadata_, dict) else None
    effective_title = body.title or (seo or {}).get("title") or episode.title
    effective_description = (
        body.description or (seo or {}).get("description") or (episode.topic or "")
    )
    effective_tags = (seo or {}).get("tags") or []
    effective_hashtags = (seo or {}).get("hashtags") or []

    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    if "youtube" in body.platforms:
        await db.refresh(episode, attribute_names=["series"])
        yt_channel_id = (
            getattr(episode.series, "youtube_channel_id", None) if episode.series else None
        )
        if not yt_channel_id:
            skipped.append(
                {
                    "platform": "youtube",
                    "reason": "The episode's series has no assigned YouTube channel. "
                    "Set one in Settings → YouTube or on the series.",
                }
            )
        else:
            from drevalis.repositories.youtube import YouTubeUploadRepository

            existing = await YouTubeUploadRepository(db).get_existing_done(
                episode.id, yt_channel_id
            )
            if existing is not None:
                skipped.append(
                    {
                        "platform": "youtube",
                        "reason": (
                            "Already published on this channel. "
                            f"Existing upload {existing.id} → "
                            f"{existing.youtube_url or existing.youtube_video_id}."
                        ),
                    }
                )
            else:
                upload = YouTubeUpload(
                    episode_id=episode.id,
                    channel_id=yt_channel_id,
                    title=effective_title,
                    description=effective_description,
                    privacy_status=body.privacy,
                    upload_status="pending",
                )
                db.add(upload)
                await db.flush()
                accepted.append(
                    {
                        "platform": "youtube",
                        "upload_id": str(upload.id),
                        "channel_id": str(yt_channel_id),
                    }
                )

    for plat_name in ("tiktok", "instagram", "facebook", "x"):
        if plat_name not in body.platforms:
            continue

        from sqlalchemy import select as _select

        row = await db.execute(
            _select(SocialPlatform).where(
                SocialPlatform.platform == plat_name,
                SocialPlatform.is_active.is_(True),
            )
        )
        plat = row.scalar_one_or_none()
        if not plat:
            tier_hint = "Pro tier" if plat_name == "tiktok" else "Studio tier"
            skipped.append(
                {
                    "platform": plat_name,
                    "reason": f"No active {plat_name} account connected. Connect one in "
                    f"Settings → Social Platforms ({tier_hint}).",
                }
            )
            continue

        hashtags_str = " ".join(effective_hashtags) if effective_hashtags else None
        su = SocialUpload(
            platform_id=plat.id,
            episode_id=episode.id,
            content_type="episode",
            title=effective_title,
            description=effective_description,
            hashtags=hashtags_str,
            upload_status="pending",
        )
        db.add(su)
        await db.flush()
        accepted.append(
            {
                "platform": plat_name,
                "upload_id": str(su.id),
                "platform_account_id": str(plat.id),
            }
        )

    await db.commit()

    logger.info(
        "episode_publish_all",
        episode_id=str(episode_id),
        accepted=[a["platform"] for a in accepted],
        skipped=[s["platform"] for s in skipped],
    )

    _ = effective_tags  # reserved for future YouTube Data-API tag upload
    return PublishAllResponse(
        episode_id=str(episode_id),
        accepted=accepted,
        skipped=skipped,
    )


# ── Continuity check (LLM-driven) ────────────────────────────────────────


@router.post(
    "/{episode_id}/continuity",
    response_model=ContinuityResponse,
    tags=["scenes"],
    summary="Flag jarring transitions in the script before generation",
)
async def check_script_continuity(
    episode_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> ContinuityResponse:
    """Run the LLM-driven continuity check over the current script.

    No-op (returns issues=[]) when no LLM config exists. Non-destructive —
    the caller decides whether to act on the warnings.
    """
    apply_deprecation_headers(response, "continuity_check")
    from drevalis.services.continuity import check_continuity
    from drevalis.services.llm import LLMService
    from drevalis.services.llm_config import LLMConfigService

    try:
        _episode, script = await svc.get_with_script_or_raise(episode_id)
    except (EpisodeNotFoundError, EpisodeNoScriptError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode or script missing") from exc

    configs = (
        await LLMConfigService(
            db,
            settings.encryption_key,
            encryption_keys=settings.get_encryption_keys(),
        ).list_all()
    )[:1]
    if not configs:
        return ContinuityResponse(issues=[])

    llm_service = LLMService(
        encryption_key=settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )
    issues = await check_continuity(script=script, llm_service=llm_service, llm_config=configs[0])
    return ContinuityResponse(
        issues=[ContinuityIssueResponse.model_validate(i.to_dict()) for i in issues]
    )


# ── Script content quality report ────────────────────────────────────────


@router.post(
    "/{episode_id}/quality-report",
    response_model=QualityReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Run the script-content quality gate against this episode's stored script",
)
async def episode_quality_report(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    svc: EpisodeService = Depends(_episode_service),
) -> QualityReportResponse:
    """Re-runs :func:`check_script_content` against the persisted script
    so already-generated episodes can be graded without regeneration.

    The series' ``tone_profile`` (when set) parameterises the gate the
    same way it would during the generation step.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from drevalis.models.episode import Episode as EpisodeModel
    from drevalis.services.quality_gates import check_script_content

    try:
        _episode, script = await svc.get_with_script_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "episode_not_found") from exc
    except EpisodeNoScriptError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "episode has no script yet — generate first",
        ) from exc

    stmt = (
        select(EpisodeModel)
        .where(EpisodeModel.id == episode_id)
        .options(selectinload(EpisodeModel.series))
    )
    res = await db.execute(stmt)
    eager = res.scalar_one_or_none()
    tone_profile: dict[str, Any] | None = None
    if eager is not None and eager.series is not None:
        tone_profile = getattr(eager.series, "tone_profile", None)

    report = await check_script_content(script, tone_profile)
    return QualityReportResponse(
        gate=report.gate,
        passed=report.passed,
        issues=list(report.issues),
        metrics=dict(report.metrics),
    )
