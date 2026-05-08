"""Audiobook-related arq job functions.

Jobs
----
- ``generate_audiobook``            -- TTS + music + assembly from stored text.
- ``generate_ai_audiobook``         -- LLM writes script, then full generation.
- ``regenerate_audiobook_chapter``  -- regenerate a single chapter then re-concat.
- ``generate_script_async``         -- background LLM script generation only.

Helpers
-------
- ``_generate_audiobook_script_text`` -- chunked LLM script generation.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from drevalis.services.llm import LLMPool, LLMProvider

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def _generate_audiobook_script_text(
    provider: LLMProvider | LLMPool,
    concept: str,
    char_list: str,
    mood: str,
    target_words: int,
    target_minutes: float,
    redis_client: Redis | None = None,
    job_id: str | None = None,
    log: structlog.stdlib.BoundLogger | None = None,
) -> str | None:
    """Generate an audiobook script, using chunked generation for long content.

    For short audiobooks (<= 30 min / ~4500 words), uses a single LLM call.
    For longer audiobooks, uses a two-phase approach:
      Phase A: Generate a chapter outline (JSON).
      Phase B: Generate each chapter individually with context.

    Returns the full script text, or None if cancelled.
    """
    import json
    import re

    _log = log or logger

    system_prompt = """You are a professional audiobook scriptwriter.

CRITICAL FORMATTING RULES:
- EVERY single line of text MUST start with [CharacterName]
- Non-dialogue narration MUST use [Narrator]
- NEVER write any text without a [Speaker] tag at the start
- Each speaker change requires a new [Speaker] tag on a new line
- Use ## Chapter Title for chapter breaks

OPTIONAL SOUND EFFECTS:
- Use ``[SFX: description | dur=N]`` on its own line to drop in an
  ambient or impact sound effect (e.g. footsteps, thunder, door slam,
  busy street). The audiobook generator will synthesise a short audio
  clip and splice it in at exactly that point.
- Keep ``dur`` between 1 and 8 seconds for sequential effects.
  Default if omitted: 4s.
- Use SFX sparingly — 1-3 per chapter is plenty. Don't replace
  narration with sound effects; layer them where they enhance a
  scene's atmosphere or punctuate a beat.

OPTIONAL OVERLAY SFX (sound effect UNDER the next dialogue):
- Add ``| under=next`` to layer the SFX UNDER the next voice block
  with sidechain ducking, instead of playing it sequentially.
- Use ``| under=4`` to overlay under multiple voice blocks (here,
  the next 4 blocks).
- Tune the duck depth with ``| duck=-15`` (more negative = quieter
  SFX during dialogue, default -12).
- Great for ambient beds during conversations: rain under a porch
  scene, traffic under a street argument, fireplace crackle under
  a confession.

Example overlay SFX:

[SFX: heavy rain on a tin roof | dur=12 | under=3 | duck=-15]
[Jack] We need to talk.
[Rosie] About what?
[Jack] You know what.

Example format:
## Chapter 1: The Beginning

[Narrator] The rain hadn't stopped for three days. The city was drowning.

[SFX: heavy rain on a city window | dur=3]

[Jack] I need a drink.

[Narrator] He reached for the bottle on his desk, but it was empty. Like everything else in his life.

[Rosie] Mr. Hartley? Are you there?

Write naturally with emotion and tension. Every line tagged."""

    # Short-form: single LLM call
    if target_words <= 4500:
        user_prompt = (
            f"Write an audiobook script:\n\n"
            f"Concept: {concept}\n"
            f"Characters:\n{char_list}\n"
            f"Mood: {mood}\n"
            f"Target: ~{target_words} words ({target_minutes} minutes)\n\n"
            f"Start with a title, then ## Chapter 1, and write the complete story."
        )

        result = await provider.generate(
            system_prompt,
            user_prompt,
            temperature=0.85,
            max_tokens=8000,
            json_mode=False,
        )

        # Check cancellation
        if redis_client and job_id:
            current = await redis_client.get(f"script_job:{job_id}:status")
            if current == "cancelled":
                return None

        return result.content.strip()

    # Long-form: two-phase chunked generation
    # Phase A: Generate outline
    num_chapters = max(3, int(target_minutes / 8))  # ~8 min per chapter
    words_per_chapter = target_words // num_chapters

    outline_prompt = (
        f"Create a detailed chapter outline for an audiobook.\n\n"
        f"Concept: {concept}\n"
        f"Characters:\n{char_list}\n"
        f"Mood: {mood}\n"
        f"Number of chapters: {num_chapters}\n\n"
        f"Output ONLY valid JSON with this exact structure:\n"
        f'{{"title": "Story Title", "chapters": ['
        f'{{"title": "Chapter 1: ...", "summary": "2-3 sentence summary", '
        f'"characters_present": ["Narrator", "Jack"], '
        f'"mood": "tense", '
        f'"visual_prompt": "A dark alley in Victorian London, gas lamps, fog"'
        f"}}]}}"
    )

    outline_result = await provider.generate(
        "You are a story architect. Output only valid JSON.",
        outline_prompt,
        temperature=0.7,
        max_tokens=2000,
        json_mode=True,
    )

    try:
        # Extract JSON from response
        outline_text = outline_result.content.strip()
        # Strip markdown fences if present
        if "```" in outline_text:
            match = re.search(r"```(?:json)?\s*(.*?)```", outline_text, re.DOTALL)
            if match:
                outline_text = match.group(1).strip()
        outline = json.loads(outline_text)
    except (json.JSONDecodeError, ValueError):
        _log.warning("outline_parse_failed, falling back to single call")
        # Fallback to single call
        user_prompt = (
            f"Write an audiobook script:\n\n"
            f"Concept: {concept}\n"
            f"Characters:\n{char_list}\n"
            f"Mood: {mood}\n"
            f"Target: ~{target_words} words ({target_minutes} minutes)\n\n"
            f"Start with a title, then ## Chapter 1, and write the complete story."
        )
        result = await provider.generate(
            system_prompt,
            user_prompt,
            temperature=0.85,
            max_tokens=8000,
            json_mode=False,
        )
        return result.content.strip()

    story_title = outline.get("title", "Untitled")
    chapter_outlines = outline.get("chapters", [])

    if not chapter_outlines:
        _log.warning("outline_empty, falling back to single call")
        result = await provider.generate(
            system_prompt,
            f"Write an audiobook script about: {concept}\nCharacters:\n{char_list}\nMood: {mood}\nTarget: ~{target_words} words",
            temperature=0.85,
            max_tokens=8000,
            json_mode=False,
        )
        return result.content.strip()

    _log.info("outline_generated", title=story_title, chapters=len(chapter_outlines))

    # Phase B: Generate each chapter
    full_outline_summary = "\n".join(
        f"- {ch.get('title', f'Chapter {i + 1}')}: {ch.get('summary', '')}"
        for i, ch in enumerate(chapter_outlines)
    )

    all_chapter_texts: list[str] = []
    previous_ending = ""

    for ch_idx, ch_outline in enumerate(chapter_outlines):
        # Check cancellation
        if redis_client and job_id:
            current = await redis_client.get(f"script_job:{job_id}:status")
            if current == "cancelled":
                return None

        ch_title = ch_outline.get("title", f"Chapter {ch_idx + 1}")
        ch_summary = ch_outline.get("summary", "")
        ch_mood = ch_outline.get("mood", mood)
        ch_chars = ch_outline.get("characters_present", [])

        continuity = ""
        if previous_ending:
            continuity = f"\nPrevious chapter ended with:\n{previous_ending}\n\nContinue the story naturally from this point."

        chapter_prompt = (
            f"Write chapter {ch_idx + 1} of {len(chapter_outlines)} for the audiobook '{story_title}'.\n\n"
            f"Full story outline:\n{full_outline_summary}\n\n"
            f"THIS CHAPTER: {ch_title}\n"
            f"Summary: {ch_summary}\n"
            f"Mood: {ch_mood}\n"
            f"Characters in this chapter: {', '.join(ch_chars) if ch_chars else 'as needed'}\n"
            f"Target: ~{words_per_chapter} words\n"
            f"{continuity}\n\n"
            f"Start with ## {ch_title}\n"
            f"Remember: EVERY line MUST have a [Speaker] tag."
        )

        ch_result = await provider.generate(
            system_prompt,
            chapter_prompt,
            temperature=0.85,
            max_tokens=4000,
            json_mode=False,
        )

        ch_text = ch_result.content.strip()
        all_chapter_texts.append(ch_text)

        # Extract last paragraph for continuity
        paragraphs = [p.strip() for p in ch_text.split("\n\n") if p.strip()]
        previous_ending = paragraphs[-1] if paragraphs else ""

        _log.info(
            "chapter_generated",
            chapter=ch_idx + 1,
            total=len(chapter_outlines),
            words=len(ch_text.split()),
        )

    # Combine all chapters
    script_text = f"# {story_title}\n\n" + "\n\n".join(all_chapter_texts)
    return script_text


async def _build_audiobook_llm_provider(
    ctx: dict[str, Any],
    settings: Any,
) -> Any:
    """Return an ``OpenAICompatibleProvider`` for audiobook LLM calls.

    Resolution order:
    1. First ``LLMConfig`` row from the DB (base_url, model_name, api_key).
    2. LM Studio defaults from application settings.

    Parameters
    ----------
    ctx:
        arq worker context dict (must contain ``session_factory``).
    settings:
        A ``drevalis.core.config.Settings`` instance used for decryption
        and LM Studio fallback values.
    """
    from drevalis.repositories.llm_config import LLMConfigRepository
    from drevalis.services.llm import OpenAICompatibleProvider

    provider = None
    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        llm_repo = LLMConfigRepository(session)
        configs = await llm_repo.get_all()
        if configs:
            cfg = configs[0]
            api_key = "not-needed"
            if cfg.api_key_encrypted:
                api_key = settings.decrypt(cfg.api_key_encrypted)
            provider = OpenAICompatibleProvider(
                base_url=cfg.base_url,
                model=cfg.model_name,
                api_key=api_key,
            )

    if provider is None:
        provider = OpenAICompatibleProvider(
            base_url=settings.lm_studio_base_url,
            model=settings.lm_studio_default_model,
        )

    return provider


async def generate_audiobook(
    ctx: dict[str, Any], audiobook_id: str, generate_video: bool = False
) -> dict[str, Any]:
    """arq job: generate an audiobook from stored text.

    Reads all configuration (output_format, voice_casting, music settings,
    speed/pitch, etc.) from the audiobook database record.  The
    ``generate_video`` parameter is kept for backwards compatibility but
    the ``output_format`` column on the record takes precedence.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    audiobook_id:
        UUID string of the audiobook record.
    generate_video:
        Legacy flag -- prefer ``output_format`` on the audiobook record.

    Returns
    -------
    dict:
        Summary of the generation run including status.
    """
    from drevalis.repositories.audiobook import AudiobookRepository
    from drevalis.repositories.voice_profile import VoiceProfileRepository
    from drevalis.services.audiobook import AudiobookService

    log = logger.bind(audiobook_id=audiobook_id, job="generate_audiobook")
    log.info("job_start")

    parsed_id = uuid.UUID(audiobook_id)

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        ab_repo = AudiobookRepository(session)
        audiobook = await ab_repo.get_by_id(parsed_id)
        if audiobook is None:
            log.error("audiobook_not_found")
            return {"audiobook_id": audiobook_id, "status": "failed", "error": "not found"}

        # Load voice profile
        vp_repo = VoiceProfileRepository(session)
        voice_profile = (
            await vp_repo.get_by_id(audiobook.voice_profile_id)
            if audiobook.voice_profile_id
            else None
        )
        if voice_profile is None:
            await ab_repo.update(
                parsed_id, status="failed", error_message="Voice profile not found"
            )
            await session.commit()
            log.error("voice_profile_not_found")
            return {
                "audiobook_id": audiobook_id,
                "status": "failed",
                "error": "voice profile not found",
            }

        service = AudiobookService(
            tts_service=ctx["tts_service"],
            ffmpeg_service=ctx["ffmpeg_service"],
            storage=ctx["storage"],
            db_session=session,
            comfyui_service=ctx.get("comfyui_service"),
            redis=ctx.get("redis"),
        )

        # Pre-flight audit so the operator gets ALL the bad news up
        # front instead of one issue at a time. Errors abort; warnings
        # are surfaced into the audiobook's error_message field for
        # later reference but generation still runs.
        warnings = await service.preflight(
            text=audiobook.text,
            voice_profile=voice_profile,
            voice_casting=audiobook.voice_casting,
            music_enabled=audiobook.music_enabled,
            music_mood=audiobook.music_mood,
            per_chapter_music=False,
            image_generation_enabled=audiobook.image_generation_enabled,
            output_format=audiobook.output_format,
        )
        errors = [w for w in warnings if w.severity == "error"]
        if errors:
            msg = "; ".join(f"{w.code}: {w.message}" for w in errors)
            await ab_repo.update(parsed_id, status="failed", error_message=msg[:2000])
            await session.commit()
            log.error("preflight_blocked", errors=[w.code for w in errors])
            return {
                "audiobook_id": audiobook_id,
                "status": "failed",
                "error": msg,
            }

        # Task 9: hydrate AudiobookSettings from the JSONB column.
        # Null = "narrative defaults" (the service builds one
        # internally), so legacy rows keep their current behaviour.
        from drevalis.schemas.audiobook import AudiobookSettings

        ab_settings: AudiobookSettings | None = None
        settings_blob = getattr(audiobook, "settings_json", None)
        if settings_blob:
            try:
                ab_settings = AudiobookSettings.model_validate(settings_blob)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "audiobook.settings_json.invalid_falling_back_to_defaults",
                    error=str(exc)[:200],
                )

        # Task 11: hydrate the per-stage DAG and provide a persist
        # callback the service can fire after every state transition.
        # On retry the service skips ``done`` stages, so a worker
        # crash mid-master-mix doesn't redo TTS.
        initial_job_state: dict[str, Any] | None = getattr(audiobook, "job_state", None)

        async def _persist_dag(blob: dict[str, Any]) -> None:
            try:
                async with session_factory() as persist_session:
                    persist_repo = AudiobookRepository(persist_session)
                    await persist_repo.update(parsed_id, job_state=blob)
                    await persist_session.commit()
            except Exception as exc:  # noqa: BLE001
                log.warning("audiobook.job_state.persist_failed", error=str(exc)[:200])

        # Task 13: parallel callback for the RenderPlan snapshot.
        async def _persist_render_plan(blob: dict[str, Any]) -> None:
            try:
                async with session_factory() as persist_session:
                    persist_repo = AudiobookRepository(persist_session)
                    await persist_repo.update(parsed_id, render_plan_json=blob)
                    await persist_session.commit()
            except Exception as exc:  # noqa: BLE001
                log.warning("audiobook.render_plan.persist_failed", error=str(exc)[:200])

        try:
            result = await service.generate(
                audiobook_id=parsed_id,
                text=audiobook.text,
                voice_profile=voice_profile,
                title=audiobook.title,
                generate_video=generate_video,
                background_image_path=audiobook.background_image_path,
                output_format=audiobook.output_format,
                cover_image_path=audiobook.cover_image_path,
                voice_casting=audiobook.voice_casting,
                music_enabled=audiobook.music_enabled,
                music_mood=audiobook.music_mood,
                music_volume_db=float(audiobook.music_volume_db),
                speed=float(audiobook.speed),
                pitch=float(audiobook.pitch),
                video_orientation=audiobook.video_orientation,
                caption_style_preset=audiobook.caption_style_preset,
                image_generation_enabled=audiobook.image_generation_enabled,
                track_mix=getattr(audiobook, "track_mix", None),
                audiobook_settings=ab_settings,
                initial_job_state=initial_job_state,
                persist_job_state_cb=_persist_dag,
                persist_render_plan_cb=_persist_render_plan,
            )

            await ab_repo.update(
                parsed_id,
                status="done",
                audio_path=result["audio_rel_path"],
                video_path=result["video_rel_path"],
                mp3_path=result["mp3_rel_path"],
                duration_seconds=result["duration_seconds"],
                file_size_bytes=result["file_size_bytes"],
                chapters=result["chapters"],
                error_message=None,
            )
            await session.commit()

            # NOTE: TTS chunk files used to be deleted here once the
            # final mix landed in the DB. Removed in v0.25.1 — the
            # multi-track audiobook editor lists / replays / remixes
            # those exact files, so wiping them broke the editor
            # ("No clips found") and forced a full re-TTS for any
            # post-generation tweak. Chunks are tiny (~50 KB each at
            # 24 kHz mono PCM); a 200-chunk audiobook holds ~10 MB
            # of cache — well worth it for instant remix + the
            # editor experience. Trigger an explicit cleanup via a
            # future "Compact" button if disk usage becomes an issue
            # for someone with hundreds of finished audiobooks.

            await service._clear_cancel_flag(parsed_id)
            duration = result["duration_seconds"]
            log.info("job_complete", status="success", duration_seconds=duration)
            return {"audiobook_id": audiobook_id, "status": "success", "duration": duration}
        except asyncio.CancelledError as exc:
            # User hit Cancel — mark as failed with a clean message
            # (not "cancelled" because the audiobook status enum
            # doesn't include that value; failed + explicit message
            # is the convention used by the episode pipeline too).
            await ab_repo.update(
                parsed_id,
                status="failed",
                error_message="Cancelled by user",
            )
            await session.commit()
            await service._clear_cancel_flag(parsed_id)
            log.info("job_cancelled", reason=str(exc)[:200])
            return {"audiobook_id": audiobook_id, "status": "cancelled"}
        except Exception as exc:
            await ab_repo.update(
                parsed_id,
                status="failed",
                error_message=str(exc)[:2000],
            )
            await session.commit()
            await service._clear_cancel_flag(parsed_id)

            log.error("job_failed", error=str(exc), exc_info=True)
            return {"audiobook_id": audiobook_id, "status": "failed", "error": str(exc)}


async def regenerate_audiobook_chapter(
    ctx: dict[str, Any],
    audiobook_id: str,
    chapter_index: int,
    new_chapter_text: str | None = None,
) -> dict[str, Any]:
    """Regenerate audio after a chapter edit. Full re-TTS today.

    .. note::

        Fast path: the chunk cache for the target chapter is dropped
        before calling ``AudiobookService.generate``. The generator
        reuses every chunk WAV that still exists on disk, so only the
        invalidated chapter gets re-synthesised; every other chapter's
        pre-rendered audio is spliced back in. The final concat + post-
        processing still runs end-to-end.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    audiobook_id:
        UUID string of the audiobook record.
    chapter_index:
        0-based chapter index to regenerate.
    new_chapter_text:
        Optional replacement text for the chapter.

    Returns
    -------
    dict:
        Summary including status.
    """
    from drevalis.repositories.audiobook import AudiobookRepository
    from drevalis.repositories.voice_profile import VoiceProfileRepository
    from drevalis.services.audiobook import AudiobookService

    log = logger.bind(
        audiobook_id=audiobook_id,
        chapter_index=chapter_index,
        job="regenerate_audiobook_chapter",
    )
    log.info("job_start")

    parsed_id = uuid.UUID(audiobook_id)

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        ab_repo = AudiobookRepository(session)
        audiobook = await ab_repo.get_by_id(parsed_id)
        if audiobook is None:
            log.error("audiobook_not_found")
            return {"audiobook_id": audiobook_id, "status": "failed", "error": "not found"}

        # If new text was provided, update just the affected chapter in the
        # full text. Prior implementation parsed + re-joined with ``"\n\n"``
        # which flattened user whitespace, always emitted ``## `` headers
        # (converting ``---``-separated audiobooks to ``##``-headered ones
        # on first edit, permanently losing the original style), and
        # dropped the synthetic "Introduction" label producing duplicate
        # intros on the next regenerate.
        #
        # Fix: locate the chapter substring in the ORIGINAL text and
        # replace only those bytes - preserving every other character
        # exactly as the user wrote it.
        text = audiobook.text
        if new_chapter_text is not None:
            from drevalis.services.audiobook import AudiobookService as _Svc

            svc_tmp = _Svc(
                tts_service=ctx["tts_service"],
                ffmpeg_service=ctx["ffmpeg_service"],
                storage=ctx["storage"],
            )
            chapters = svc_tmp._parse_chapters(text)
            if 0 <= chapter_index < len(chapters):
                old_body = chapters[chapter_index]["text"]
                # ``_parse_chapters`` strips the body; search for the
                # stripped form in the original text. str.find returns
                # -1 when the body has been transformed beyond recognition
                # (very rare - e.g. the user inserted trailing whitespace
                # inside the chapter and the parser removed it).
                start = text.find(old_body)
                if start >= 0:
                    text = text[:start] + new_chapter_text + text[start + len(old_body) :]
                else:
                    log.warning(
                        "chapter_body_not_locatable_falling_back_to_rewrite",
                        chapter_index=chapter_index,
                    )
                    # Fallback: rebuild using ## headers. Acceptable as a
                    # last resort; the alternative is silently losing the
                    # user's edit.
                    parts: list[str] = []
                    for i, ch in enumerate(chapters):
                        body = new_chapter_text if i == chapter_index else ch["text"]
                        if ch["title"] not in ("Full Text", "Introduction"):
                            parts.append(f"## {ch['title']}")
                        parts.append(body)
                    text = "\n\n".join(parts)
                await ab_repo.update(parsed_id, text=text)
                await session.commit()
                log.info("chapter_text_updated", chapter_index=chapter_index)

        # Mark as generating
        await ab_repo.update(parsed_id, status="generating")
        await session.commit()

        # Load voice profile
        vp_repo = VoiceProfileRepository(session)
        voice_profile = (
            await vp_repo.get_by_id(audiobook.voice_profile_id)
            if audiobook.voice_profile_id
            else None
        )
        if voice_profile is None:
            await ab_repo.update(
                parsed_id, status="failed", error_message="Voice profile not found"
            )
            await session.commit()
            return {
                "audiobook_id": audiobook_id,
                "status": "failed",
                "error": "voice profile not found",
            }

        service = AudiobookService(
            tts_service=ctx["tts_service"],
            ffmpeg_service=ctx["ffmpeg_service"],
            storage=ctx["storage"],
            db_session=session,
        )

        # Per-chapter fast path: drop ONLY the target chapter's chunk
        # cache. AudiobookService.generate re-uses every existing chunk
        # WAV on disk (``if chunk_path.exists()``) — the regenerated
        # chapter's chunks are the only ones that will actually be
        # re-synthesised. Other chapters get re-used, giving the user
        # a genuinely fast retry instead of re-TTSing everything.
        deleted = await service.invalidate_chapter_chunks(parsed_id, chapter_index)
        log.info("per_chapter_fast_path_invalidation", deleted_chunks=deleted)

        try:
            result = await service.generate(
                audiobook_id=parsed_id,
                text=text,
                voice_profile=voice_profile,
                title=audiobook.title,
                output_format=getattr(audiobook, "output_format", "audio_only"),
                cover_image_path=getattr(audiobook, "cover_image_path", None),
                voice_casting=getattr(audiobook, "voice_casting", None),
                music_enabled=getattr(audiobook, "music_enabled", False),
                music_mood=getattr(audiobook, "music_mood", None),
                music_volume_db=float(getattr(audiobook, "music_volume_db", -14.0)),
                speed=float(getattr(audiobook, "speed", 1.0)),
                pitch=float(getattr(audiobook, "pitch", 1.0)),
                background_image_path=audiobook.background_image_path,
            )

            await ab_repo.update(
                parsed_id,
                status="done",
                audio_path=result["audio_rel_path"],
                video_path=result["video_rel_path"],
                mp3_path=result["mp3_rel_path"],
                duration_seconds=result["duration_seconds"],
                file_size_bytes=result["file_size_bytes"],
                chapters=result["chapters"],
                error_message=None,
            )
            await session.commit()

            log.info("job_complete", status="success")
            return {"audiobook_id": audiobook_id, "status": "success"}
        except Exception as exc:
            await ab_repo.update(
                parsed_id,
                status="failed",
                error_message=str(exc)[:2000],
            )
            await session.commit()
            log.error("job_failed", error=str(exc), exc_info=True)
            return {"audiobook_id": audiobook_id, "status": "failed", "error": str(exc)}


async def generate_script_async(
    ctx: dict[str, Any], job_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Background LLM script generation for audiobooks.

    The LLM logic that was previously inline in the route handler now runs
    here in the arq worker.  Results are stored in Redis with a 1-hour TTL.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    job_id:
        Unique job identifier (stored in Redis as ``script_job:{job_id}:*``).
    payload:
        Dict with keys: concept, characters, target_minutes, mood.
    """
    import json
    import re

    from drevalis.core.config import Settings

    log = logger.bind(job_id=job_id, job="generate_script_async")
    log.info("job_start")

    redis_client = ctx["redis"]

    try:
        # Check for early cancellation
        current_status = await redis_client.get(f"script_job:{job_id}:status")
        if current_status == "cancelled":
            log.info("job_already_cancelled")
            return {"status": "cancelled"}

        settings = Settings()

        provider = await _build_audiobook_llm_provider(ctx, settings)

        target_words = payload["target_minutes"] * 150
        characters = payload.get(
            "characters", [{"name": "Narrator", "description": "Omniscient narrator"}]
        )
        char_list = "\n".join(f"- {c['name']}: {c.get('description', '')}" for c in characters)

        script_text = await _generate_audiobook_script_text(
            provider=provider,
            concept=payload["concept"],
            char_list=char_list,
            mood=payload.get("mood", "neutral"),
            target_words=target_words,
            target_minutes=payload["target_minutes"],
            redis_client=redis_client,
            job_id=job_id,
            log=log,
        )

        if script_text is None:
            log.info("job_cancelled_after_llm")
            return {"status": "cancelled"}

        lines = script_text.split("\n")
        title = lines[0].strip().lstrip("#").strip() if lines else "Untitled"
        chapters = re.findall(r"^##\s+(.+)$", script_text, re.MULTILINE)
        # ``[SFX:...]`` tags are NOT speakers — exclude them from the
        # character list so the auto-voice-assigner doesn't waste a
        # profile on each sound-effect description.
        raw_tags = re.findall(r"^\[([^\]]+)\]", script_text, re.MULTILINE)
        characters_found = sorted(
            {t.strip() for t in raw_tags if not t.strip().lower().startswith("sfx")}
        )
        word_count = len(script_text.split())

        result_dict = {
            "title": title,
            "script": script_text,
            "characters": characters_found,
            "chapters": chapters,
            "word_count": word_count,
            "estimated_minutes": round(word_count / 150, 1),
        }

        await redis_client.set(f"script_job:{job_id}:result", json.dumps(result_dict), ex=3600)
        await redis_client.set(f"script_job:{job_id}:status", "done", ex=3600)

        log.info(
            "job_complete",
            title=title,
            word_count=word_count,
            chapters=len(chapters),
        )
        return {"status": "done"}

    except Exception as exc:
        log.error("job_failed", error=str(exc), exc_info=True)
        await redis_client.set(f"script_job:{job_id}:error", str(exc)[:500], ex=3600)
        await redis_client.set(f"script_job:{job_id}:status", "failed", ex=3600)
        return {"status": "failed", "error": str(exc)}


async def generate_ai_audiobook(
    ctx: dict[str, Any], audiobook_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Combined job: LLM writes script, then TTS generates audio, music, and assembly.

    This is the single-form AI audiobook creator -- the user fills one form,
    submits, and this job handles everything end to end.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    audiobook_id:
        UUID string of the audiobook record (already created with status='generating').
    payload:
        Dict with keys: concept, characters, target_minutes, mood, output_format,
        music_enabled, music_mood, music_volume_db, speed, pitch.
    """
    import re

    from drevalis.core.config import Settings
    from drevalis.repositories.audiobook import AudiobookRepository
    from drevalis.repositories.voice_profile import VoiceProfileRepository
    from drevalis.services.audiobook import AudiobookService

    log = logger.bind(audiobook_id=audiobook_id, job="generate_ai_audiobook")
    log.info("job_start")

    parsed_id = uuid.UUID(audiobook_id)
    session_factory = ctx["session_factory"]
    settings = Settings()

    # ── Step 1: Generate script with LLM (skip if text already exists) ──
    # Check if audiobook already has script text (e.g., from a previous
    # failed attempt that completed LLM but failed during TTS).
    has_existing_text = False
    async with session_factory() as session:
        ab_repo = AudiobookRepository(session)
        ab_check = await ab_repo.get_by_id(parsed_id)
        if ab_check and ab_check.text and len(ab_check.text.strip()) > 100:
            has_existing_text = True
            log.info("script_already_exists", text_length=len(ab_check.text), skip_llm=True)

    if has_existing_text:
        script_text = ""
        title = ""
        chapter_data = None
        log.info("skip_llm_generation", reason="text already exists")

    if not has_existing_text:
        try:
            provider = await _build_audiobook_llm_provider(ctx, settings)

            characters = payload.get(
                "characters",
                [{"name": "Narrator", "description": "Omniscient narrator"}],
            )
            target_minutes = payload.get("target_minutes", 5)
            target_words = int(target_minutes * 150)
            mood = payload.get("mood", "neutral")
            concept = payload.get("concept", "")

            char_list = "\n".join(f"- {c['name']}: {c.get('description', '')}" for c in characters)

            script_text_or_none = await _generate_audiobook_script_text(
                provider=provider,
                concept=concept,
                char_list=char_list,
                mood=mood,
                target_words=target_words,
                target_minutes=target_minutes,
                log=log,
            )
            script_text = script_text_or_none or ""

            # Extract title from first line
            lines = script_text.split("\n")
            title = lines[0].strip().lstrip("#").strip() if lines else "Untitled"

            # Parse chapters
            chapters_found = re.findall(r"^##\s+(.+)$", script_text, re.MULTILINE)
            chapter_data = (
                [{"title": ch, "text": ""} for ch in chapters_found] if chapters_found else None
            )

            log.info(
                "script_generated",
                title=title,
                word_count=len(script_text.split()),
                chapters=len(chapters_found),
            )

        except Exception as exc:
            log.error("script_generation_failed", error=str(exc), exc_info=True)
            async with session_factory() as session:
                ab_repo = AudiobookRepository(session)
                await ab_repo.update(
                    parsed_id,
                    status="failed",
                    error_message=f"Script generation failed: {str(exc)[:500]}",
                )
                await session.commit()
            return {"status": "failed", "audiobook_id": audiobook_id}

    # ── Step 2: Update audiobook with script (skip if already saved) ──
    if not has_existing_text:
        async with session_factory() as session:
            ab_repo = AudiobookRepository(session)
            ab = await ab_repo.get_by_id(parsed_id)
            if not ab:
                log.error("audiobook_not_found")
                return {"status": "failed", "audiobook_id": audiobook_id}
            await ab_repo.update(
                parsed_id,
                text=script_text,
                title=title[:500],
                chapters=chapter_data,
            )
            await session.commit()
            log.info("audiobook_text_updated")
    else:
        log.info("audiobook_text_already_saved", skip_step2=True)

    # ── Step 3: Generate TTS + music + assembly ───────────────────────
    try:
        async with session_factory() as session:
            ab_repo = AudiobookRepository(session)
            vp_repo = VoiceProfileRepository(session)

            ab = await ab_repo.get_by_id(parsed_id)
            if not ab:
                log.error("audiobook_not_found")
                return {"status": "failed", "audiobook_id": audiobook_id}

            voice_profile = (
                await vp_repo.get_by_id(ab.voice_profile_id) if ab.voice_profile_id else None
            )
            if not voice_profile:
                await ab_repo.update(
                    parsed_id,
                    status="failed",
                    error_message="No voice profile configured",
                )
                await session.commit()
                return {"status": "failed", "audiobook_id": audiobook_id}

            service = AudiobookService(
                tts_service=ctx["tts_service"],
                ffmpeg_service=ctx["ffmpeg_service"],
                storage=ctx["storage"],
                db_session=session,
                comfyui_service=ctx.get("comfyui_service"),
                redis=ctx.get("redis"),
            )

            gen_result = await service.generate(
                audiobook_id=parsed_id,
                text=ab.text,
                voice_profile=voice_profile,
                output_format=ab.output_format,
                cover_image_path=ab.cover_image_path,
                voice_casting=ab.voice_casting,
                music_enabled=ab.music_enabled,
                music_mood=ab.music_mood,
                music_volume_db=float(ab.music_volume_db),
                speed=float(ab.speed),
                pitch=float(ab.pitch),
                image_generation_enabled=ab.image_generation_enabled,
            )

            await ab_repo.update(
                parsed_id,
                status="done",
                audio_path=gen_result["audio_rel_path"],
                video_path=gen_result["video_rel_path"],
                mp3_path=gen_result["mp3_rel_path"],
                duration_seconds=gen_result["duration_seconds"],
                file_size_bytes=gen_result["file_size_bytes"],
                chapters=gen_result["chapters"],
                error_message=None,
            )
            await session.commit()

            await service._clear_cancel_flag(parsed_id)
            duration = gen_result["duration_seconds"]
            log.info("job_complete", status="success", duration_seconds=duration)
            return {
                "status": "done",
                "audiobook_id": audiobook_id,
                "duration": duration,
            }

    except asyncio.CancelledError as exc:
        log.info("ai_audiobook_cancelled", reason=str(exc)[:200])
        async with session_factory() as session:
            ab_repo = AudiobookRepository(session)
            await ab_repo.update(
                parsed_id,
                status="failed",
                error_message="Cancelled by user",
            )
            await session.commit()
        # Best-effort flag clear (no service instance handy here).
        try:
            redis_client = ctx.get("redis")
            if redis_client is not None:
                await redis_client.delete(f"cancel:audiobook:{audiobook_id}")
        except Exception:
            pass
        return {"status": "cancelled", "audiobook_id": audiobook_id}
    except Exception as exc:
        log.error("audio_generation_failed", error=str(exc), exc_info=True)
        async with session_factory() as session:
            ab_repo = AudiobookRepository(session)
            await ab_repo.update(
                parsed_id,
                status="failed",
                error_message=f"Audio generation failed: {str(exc)[:500]}",
            )
            await session.commit()
        return {"status": "failed", "audiobook_id": audiobook_id}


async def regenerate_audiobook_chapter_image(
    ctx: dict[str, Any],
    audiobook_id: str,
    chapter_index: int,
    prompt_override: str | None = None,
) -> dict[str, Any]:
    """Regenerate a single chapter's illustration via ComfyUI.

    Faster than ``regenerate_audiobook_chapter`` — that path
    re-synthesises audio + re-assembles the audiobook. This path
    only re-runs the qwen_image_2512 ComfyUI workflow for one
    chapter, then patches ``chapters[idx]["image_path"]`` on the DB
    row. The audiobook video file itself is NOT regenerated, but
    the next assembly run will pick up the new image.

    Parameters
    ----------
    ctx:
        arq context dict.
    audiobook_id:
        UUID string of the audiobook record.
    chapter_index:
        0-based chapter index whose image to regenerate.
    prompt_override:
        Optional ComfyUI prompt to use instead of the auto-derived
        one (chapter title + mood + first 200 chars of text).
    """
    from pathlib import Path

    from drevalis.repositories.audiobook import AudiobookRepository
    from drevalis.services.audiobook import AudiobookService

    log = logger.bind(
        audiobook_id=audiobook_id,
        chapter_index=chapter_index,
        job="regenerate_audiobook_chapter_image",
    )
    log.info("job_start", has_prompt_override=prompt_override is not None)

    parsed_id = uuid.UUID(audiobook_id)

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        ab_repo = AudiobookRepository(session)
        audiobook = await ab_repo.get_by_id(parsed_id)
        if audiobook is None:
            log.error("audiobook_not_found")
            return {
                "audiobook_id": audiobook_id,
                "status": "failed",
                "error": "not found",
            }

        chapters = list(audiobook.chapters or [])
        if chapter_index < 0 or chapter_index >= len(chapters):
            log.error("chapter_index_out_of_range", total=len(chapters))
            return {
                "audiobook_id": audiobook_id,
                "status": "failed",
                "error": "chapter index out of range",
            }

        chapter = dict(chapters[chapter_index])
        if prompt_override:
            chapter["visual_prompt"] = prompt_override

        # Drop any existing image path so the service regenerates
        # rather than skipping. Same dir, same filename.
        old_path_str = chapter.get("image_path")
        if old_path_str:
            try:
                old_path = Path(old_path_str)
                if old_path.exists():
                    old_path.unlink()
            except Exception:  # noqa: BLE001
                # Best-effort delete; the generator will overwrite.
                pass

        svc = AudiobookService(
            tts_service=ctx["tts_service"],
            ffmpeg_service=ctx["ffmpeg_service"],
            storage=ctx["storage"],
            comfyui_service=ctx.get("comfyui_service"),
        )
        if svc.comfyui_service is None:
            log.error("no_comfyui_service")
            return {
                "audiobook_id": audiobook_id,
                "status": "failed",
                "error": "ComfyUI not configured",
            }

        # Resolve the audiobook output dir + the canonical
        # 1080×1920 dimensions used by the original generator.
        output_dir = ctx["storage"].resolve_path(f"audiobooks/{audiobook_id}")
        # Run the existing helper with a single-element chapter list.
        # ``chapter_indices`` keeps the output filename aligned with
        # the original slot (``ch{idx:03d}.png``) instead of always
        # writing to ``ch000.png``.
        results = await svc._generate_chapter_images(
            chapters=[chapter],
            output_dir=output_dir,
            audiobook_id=parsed_id,
            video_width=1080,
            video_height=1920,
            chapter_indices=[chapter_index],
        )
        if not results or results[0] is None:
            log.error("comfyui_returned_no_image")
            return {
                "audiobook_id": audiobook_id,
                "status": "failed",
                "error": "image generation returned no result",
            }

        new_image_path = results[0]
        # Persist the updated chapter record.
        chapters[chapter_index] = {
            **chapters[chapter_index],
            "image_path": str(new_image_path),
        }
        await ab_repo.update(parsed_id, chapters=chapters)
        await session.commit()

        log.info("job_complete", image_path=str(new_image_path))
        return {
            "audiobook_id": audiobook_id,
            "chapter_index": chapter_index,
            "status": "done",
            "image_path": str(new_image_path),
        }
