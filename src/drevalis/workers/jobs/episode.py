"""Episode-related arq job functions.

Jobs
----
- ``generate_episode``     -- full pipeline run for an episode.
- ``retry_episode_step``   -- retry a specific failed pipeline step.
- ``reassemble_episode``   -- re-run captions + assembly + thumbnail only.
- ``regenerate_voice``     -- re-run voice + downstream steps.
- ``regenerate_scene``     -- regenerate a single scene image then reassemble.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def generate_episode(ctx: dict[str, Any], episode_id: str) -> dict[str, Any]:
    """Main arq job: run the full pipeline for an episode.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    episode_id:
        UUID string of the episode to generate.

    Returns
    -------
    dict:
        Summary of the pipeline run including status.
    """
    from drevalis.core.deps import get_settings
    from drevalis.services.pipeline import PipelineOrchestrator

    log = logger.bind(episode_id=episode_id, job="generate_episode")
    log.info("job_start")

    # Demo mode: redirect to the scripted fake pipeline. No GPU, no LLM,
    # no ComfyUI — emits the same WS events a real run would.
    if get_settings().demo_mode:
        from drevalis.workers.jobs.demo_pipeline import generate_episode_demo

        return await generate_episode_demo(ctx, episode_id)

    # License gate: 4th validation site (on_job_start is the first, middleware
    # the second, lifespan bootstrap the third). Duplicating the check here
    # means bypassing the on_job_start hook alone isn't enough to resume
    # generation. Raises a RuntimeError the worker treats as a hard failure.
    from drevalis.core.license.state import get_state as _license_state

    _lic = _license_state()
    if not _lic.is_usable:
        log.warning("generate_episode_blocked_license", status=_lic.status.value)
        raise RuntimeError(f"license_not_usable:{_lic.status.value}")

    parsed_id = uuid.UUID(episode_id)
    session_factory = ctx["session_factory"]

    # ── Priority check: defer longform if shorts are waiting ─────────
    try:
        priority_mode = await ctx["redis"].get("job:priority_mode")
        if priority_mode and isinstance(priority_mode, bytes):
            priority_mode = priority_mode.decode()
    except Exception:
        priority_mode = None

    if priority_mode in ("shorts_first", "longform_first"):
        # Symmetric behaviour: the "preferred" content_format blocks
        # the other from running when the preferred queue is busy.
        # Without this branch, ``longform_first`` was silently FIFO.
        preferred_fmt = "shorts" if priority_mode == "shorts_first" else "longform"
        other_fmt = "longform" if preferred_fmt == "shorts" else "shorts"

        async with session_factory() as _ps:
            from drevalis.repositories.episode import EpisodeRepository as _ER
            from drevalis.repositories.series import SeriesRepository as _SR

            _ep = await _ER(_ps).get_by_id(parsed_id)
            if _ep:
                _series = await _SR(_ps).get_by_id(_ep.series_id)
                this_fmt = getattr(_series, "content_format", "shorts") if _series else "shorts"
                if this_fmt == other_fmt:
                    from sqlalchemy import text as _text

                    _result = await _ps.execute(
                        _text(
                            "SELECT COUNT(*) FROM episodes e JOIN series s ON e.series_id = s.id "
                            "WHERE e.status = 'generating' AND s.content_format = :fmt"
                        ),
                        {"fmt": preferred_fmt},
                    )
                    preferred_generating = _result.scalar() or 0
                    _result2 = await _ps.execute(
                        _text(
                            "SELECT COUNT(*) FROM episodes e JOIN series s ON e.series_id = s.id "
                            "WHERE e.status IN ('draft', 'failed') AND s.content_format = :fmt"
                        ),
                        {"fmt": preferred_fmt},
                    )
                    preferred_waiting = _result2.scalar() or 0
                    if preferred_generating > 0 or preferred_waiting > 2:
                        log.info(
                            "priority_deferred",
                            mode=priority_mode,
                            this_format=this_fmt,
                            preferred_generating=preferred_generating,
                            preferred_waiting=preferred_waiting,
                        )
                        arq_redis = ctx.get("arq_redis")
                        if arq_redis is None:
                            log.warning("priority_deferral_skipped_no_arq_redis")
                        else:
                            await arq_redis.enqueue_job(
                                "generate_episode", episode_id, _defer_by=60
                            )
                            return {
                                "episode_id": episode_id,
                                "status": "deferred",
                                "reason": priority_mode,
                            }

    # Acquire a fresh DB session for this job
    async with session_factory() as session:
        # ── Dispatch by content_format ──────────────────────────────
        # music_video episodes go through their own orchestrator
        # (Phase 2a: SCRIPT + AUDIO; visuals + composite land in
        # Phase 2b). All other formats use the regular pipeline.
        from drevalis.repositories.episode import EpisodeRepository as _EpRepo
        from drevalis.repositories.series import SeriesRepository as _SerRepo

        _ep = await _EpRepo(session).get_by_id(parsed_id)
        _series = await _SerRepo(session).get_by_id(_ep.series_id) if _ep else None
        _fmt = getattr(_series, "content_format", "shorts") if _series else "shorts"

        if _fmt == "music_video":
            from drevalis.repositories.llm_config import LLMConfigRepository
            from drevalis.services.llm import LLMPool
            from drevalis.services.music_video_orchestrator import (
                MusicVideoOrchestrator,
            )

            # Build the LLM pool the same way PipelineOrchestrator does
            # for the longform path. Failures to construct individual
            # providers are skipped so one bad config doesn't block the
            # whole pool.
            llm_service = ctx["llm_service"]
            llm_repo = LLMConfigRepository(session)
            configs = await llm_repo.get_all(limit=10)
            providers = []
            for cfg in configs:
                try:
                    providers.append((cfg.name, llm_service.get_provider(cfg)))
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "music_video.llm_pool_skip_config",
                        name=cfg.name,
                        error=str(exc)[:100],
                    )
            if not providers:
                raise RuntimeError(
                    "No LLM providers available for music-video pipeline. "
                    "Create at least one LLM config in Settings."
                )
            llm_pool: LLMPool = LLMPool(providers)
            music_service = ctx.get("music_service")
            if music_service is None:
                log.error("music_video_dispatch.no_music_service")
                raise RuntimeError(
                    "MusicService is not available — cannot run music-video "
                    "pipeline. Check worker startup configuration."
                )
            mv_orch = MusicVideoOrchestrator(
                episode_id=parsed_id,
                db_session=session,
                redis=ctx["redis"],
                llm_pool=llm_pool,
                music_service=music_service,
                ffmpeg_service=ctx["ffmpeg_service"],
                storage=ctx["storage"],
                comfyui_service=ctx.get("comfyui_service"),
                caption_service=ctx.get("caption_service"),
            )
            try:
                await mv_orch.run()
                log.info(
                    "job_complete",
                    status="success",
                    pipeline="music_video",
                    phase="2a",
                )
                return {
                    "episode_id": episode_id,
                    "status": "success",
                    "pipeline": "music_video",
                }
            except Exception as exc:
                log.error("job_failed", error=str(exc), exc_info=True)
                raise

        orchestrator = PipelineOrchestrator(
            episode_id=parsed_id,
            db_session=session,
            redis=ctx["redis"],
            llm_service=ctx["llm_service"],
            comfyui_service=ctx["comfyui_service"],
            tts_service=ctx["tts_service"],
            ffmpeg_service=ctx["ffmpeg_service"],
            caption_service=ctx["caption_service"],
            storage=ctx["storage"],
            music_service=ctx.get("music_service"),
        )

        try:
            await orchestrator.run()
            log.info("job_complete", status="success")
            return {"episode_id": episode_id, "status": "success"}
        except Exception as exc:
            # Re-raise so arq honours max_tries and backoff. The
            # orchestrator is already responsible for persisting
            # status="failed" on the Episode row, so logging here is
            # enough for observability.
            log.error("job_failed", error=str(exc), exc_info=True)
            raise


async def reassemble_episode(ctx: dict[str, Any], episode_id: str) -> dict[str, Any]:
    """Re-run captions + assembly + thumbnail only.

    Voice and scene assets are kept.  Existing caption/video/thumbnail
    assets for the affected steps are replaced by new ones.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    episode_id:
        UUID string of the episode to reassemble.
    """
    from drevalis.repositories.generation_job import GenerationJobRepository
    from drevalis.services.pipeline import PipelineOrchestrator

    log = logger.bind(episode_id=episode_id, job="reassemble_episode")
    log.info("job_start")

    parsed_id = uuid.UUID(episode_id)

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        from drevalis.repositories.media_asset import MediaAssetRepository

        job_repo = GenerationJobRepository(session)

        # Delete stale downstream media_asset rows before re-running.
        # Without this, every regeneration piles on duplicate caption/
        # video/thumbnail rows; caption lookup then picks the oldest
        # stable-sorted match and can silently use a stale file if
        # filenames are ever timestamped.
        asset_repo = MediaAssetRepository(session)
        removed = await asset_repo.delete_by_episode_and_types(
            parsed_id, ["caption", "video", "thumbnail"]
        )
        log.info("stale_assets_removed", count=removed)

        # Mark any previous done jobs for captions/assembly/thumbnail as non-done
        # so the orchestrator will re-execute them.
        for step_name in ("captions", "assembly", "thumbnail"):
            existing = await job_repo.get_latest_by_episode_and_step(parsed_id, step_name)
            if existing and existing.status == "done":
                await job_repo.update(
                    existing.id,
                    status="queued",
                    progress_pct=0,
                    error_message=None,
                )
        await session.commit()
        log.info("steps_reset", steps=["captions", "assembly", "thumbnail"])

        # Run the full pipeline -- voice and scenes steps are already 'done'
        # and will be skipped automatically.
        orchestrator = PipelineOrchestrator(
            episode_id=parsed_id,
            db_session=session,
            redis=ctx["redis"],
            llm_service=ctx["llm_service"],
            comfyui_service=ctx["comfyui_service"],
            tts_service=ctx["tts_service"],
            ffmpeg_service=ctx["ffmpeg_service"],
            caption_service=ctx["caption_service"],
            storage=ctx["storage"],
            music_service=ctx.get("music_service"),
        )

        try:
            await orchestrator.run()
            log.info("job_complete", status="success")
            return {"episode_id": episode_id, "status": "success"}
        except Exception:
            # Re-raise so arq honours max_tries + exponential backoff.
            # The orchestrator has already persisted status='failed'
            # on the Episode row, so there is no state-loss here;
            # returning status='failed' would make arq consider the
            # job complete and skip every remaining retry.
            log.error("job_failed", exc_info=True)
            raise


async def regenerate_voice(ctx: dict[str, Any], episode_id: str) -> dict[str, Any]:
    """Re-run voice + captions + assembly + thumbnail.

    Scene images are kept.  Useful when changing voice profiles or
    editing narration text.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    episode_id:
        UUID string of the episode.
    """
    from drevalis.repositories.generation_job import GenerationJobRepository
    from drevalis.services.pipeline import PipelineOrchestrator

    log = logger.bind(episode_id=episode_id, job="regenerate_voice")
    log.info("job_start")

    parsed_id = uuid.UUID(episode_id)

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        from drevalis.repositories.media_asset import MediaAssetRepository

        job_repo = GenerationJobRepository(session)

        # Delete stale voice + downstream assets so we don't accumulate
        # orphan rows. Scenes stay.
        asset_repo = MediaAssetRepository(session)
        removed = await asset_repo.delete_by_episode_and_types(
            parsed_id, ["voiceover", "caption", "video", "thumbnail"]
        )
        log.info("stale_assets_removed", count=removed)

        # Mark voice, captions, assembly, thumbnail as queued so the
        # orchestrator will re-execute them.
        for step_name in ("voice", "captions", "assembly", "thumbnail"):
            existing = await job_repo.get_latest_by_episode_and_step(parsed_id, step_name)
            if existing and existing.status == "done":
                await job_repo.update(
                    existing.id,
                    status="queued",
                    progress_pct=0,
                    error_message=None,
                )
        await session.commit()
        log.info("steps_reset", steps=["voice", "captions", "assembly", "thumbnail"])

        orchestrator = PipelineOrchestrator(
            episode_id=parsed_id,
            db_session=session,
            redis=ctx["redis"],
            llm_service=ctx["llm_service"],
            comfyui_service=ctx["comfyui_service"],
            tts_service=ctx["tts_service"],
            ffmpeg_service=ctx["ffmpeg_service"],
            caption_service=ctx["caption_service"],
            storage=ctx["storage"],
            music_service=ctx.get("music_service"),
        )

        try:
            await orchestrator.run()
            log.info("job_complete", status="success")
            return {"episode_id": episode_id, "status": "success"}
        except Exception:
            # Re-raise so arq honours max_tries + exponential backoff.
            # The orchestrator has already persisted status='failed'
            # on the Episode row, so there is no state-loss here;
            # returning status='failed' would make arq consider the
            # job complete and skip every remaining retry.
            log.error("job_failed", exc_info=True)
            raise


async def regenerate_scene(
    ctx: dict[str, Any],
    episode_id: str,
    scene_number: int,
    visual_prompt: str | None = None,
) -> dict[str, Any]:
    """Regenerate a single scene's image/video and then reassemble.

    Parameters
    ----------
    ctx:
        arq context dict populated by ``startup``.
    episode_id:
        UUID string of the episode.
    scene_number:
        1-based scene number to regenerate.
    visual_prompt:
        Optional override for the scene's visual prompt.
    """
    from drevalis.repositories.episode import EpisodeRepository
    from drevalis.repositories.generation_job import GenerationJobRepository
    from drevalis.repositories.media_asset import MediaAssetRepository
    from drevalis.schemas.script import EpisodeScript
    from drevalis.services.pipeline import PipelineOrchestrator

    log = logger.bind(
        episode_id=episode_id,
        scene_number=scene_number,
        job="regenerate_scene",
    )
    log.info("job_start")

    parsed_id = uuid.UUID(episode_id)

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        ep_repo = EpisodeRepository(session)
        job_repo = GenerationJobRepository(session)
        asset_repo = MediaAssetRepository(session)

        # Optionally update the visual prompt.
        if visual_prompt:
            episode = await ep_repo.get_by_id(parsed_id)
            if episode and episode.script:
                script = EpisodeScript.model_validate(episode.script)
                for scene in script.scenes:
                    if scene.scene_number == scene_number:
                        scene.visual_prompt = visual_prompt
                        break
                episode.script = script.model_dump()
                await session.commit()
                log.info("visual_prompt_updated")

        # Delete existing media assets for this scene so they get regenerated.
        deleted = await asset_repo.delete_by_episode_and_scene(parsed_id, scene_number)
        log.info("scene_assets_deleted", count=deleted)

        # Mark scenes, captions, assembly, thumbnail steps as queued.
        for step_name in ("scenes", "captions", "assembly", "thumbnail"):
            existing = await job_repo.get_latest_by_episode_and_step(parsed_id, step_name)
            if existing and existing.status == "done":
                await job_repo.update(
                    existing.id,
                    status="queued",
                    progress_pct=0,
                    error_message=None,
                )
        await session.commit()

        # Run the full pipeline -- script and voice steps remain 'done'
        # and will be skipped.
        orchestrator = PipelineOrchestrator(
            episode_id=parsed_id,
            db_session=session,
            redis=ctx["redis"],
            llm_service=ctx["llm_service"],
            comfyui_service=ctx["comfyui_service"],
            tts_service=ctx["tts_service"],
            ffmpeg_service=ctx["ffmpeg_service"],
            caption_service=ctx["caption_service"],
            storage=ctx["storage"],
            music_service=ctx.get("music_service"),
        )

        try:
            await orchestrator.run()
            log.info("job_complete", status="success")
            return {
                "episode_id": episode_id,
                "scene_number": scene_number,
                "status": "success",
            }
        except Exception as exc:
            log.error("job_failed", error=str(exc), exc_info=True)
            return {
                "episode_id": episode_id,
                "scene_number": scene_number,
                "status": "failed",
                "error": str(exc),
            }


async def retry_episode_step(ctx: dict[str, Any], episode_id: str, step: str) -> dict[str, Any]:
    """Retry a specific failed step for an episode.

    Resets the failed job status to ``queued`` so the orchestrator will
    re-execute it.  Completed steps before it are automatically skipped.

    Parameters
    ----------
    ctx:
        arq context dict.
    episode_id:
        UUID string of the episode.
    step:
        Pipeline step name to retry (e.g. ``"scenes"``).
    """
    from drevalis.repositories.generation_job import GenerationJobRepository
    from drevalis.services.pipeline import PipelineOrchestrator

    log = logger.bind(episode_id=episode_id, step=step, job="retry_episode_step")
    log.info("retry_start")

    parsed_id = uuid.UUID(episode_id)

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        # Reset the specific failed step so the orchestrator picks it up
        job_repo = GenerationJobRepository(session)
        existing = await job_repo.get_latest_by_episode_and_step(parsed_id, step)
        if existing and existing.status == "failed":
            await job_repo.update(
                existing.id,
                status="queued",
                progress_pct=0,
                error_message=None,
            )
            await session.commit()
            log.info("failed_step_reset", job_id=str(existing.id))

        # Run the full pipeline -- completed steps will be skipped
        orchestrator = PipelineOrchestrator(
            episode_id=parsed_id,
            db_session=session,
            redis=ctx["redis"],
            llm_service=ctx["llm_service"],
            comfyui_service=ctx["comfyui_service"],
            tts_service=ctx["tts_service"],
            ffmpeg_service=ctx["ffmpeg_service"],
            caption_service=ctx["caption_service"],
            storage=ctx["storage"],
            music_service=ctx.get("music_service"),
        )

        try:
            await orchestrator.run()
            log.info("retry_complete", status="success")
            return {"episode_id": episode_id, "step": step, "status": "success"}
        except Exception as exc:
            log.error("retry_failed", error=str(exc), exc_info=True)
            return {
                "episode_id": episode_id,
                "step": step,
                "status": "failed",
                "error": str(exc),
            }
