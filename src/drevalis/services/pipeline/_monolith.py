"""Pipeline orchestrator -- state-machine generation engine.

Runs as a single arq job.  Each of the six pipeline steps is executed
sequentially.  Completed steps are skipped on retry so the pipeline is
fully resumable.  Progress is broadcast via Redis pub/sub for WebSocket
delivery to the frontend.

Observability:
- Each step's duration and success/failure are recorded in the in-process
  metrics collector.
- structlog context-vars (episode_id, step, job_id) are bound before each
  step so all downstream log lines carry that context automatically.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from drevalis.core.logging import bind_pipeline_context, clear_pipeline_context
from drevalis.core.metrics import metrics
from drevalis.models.generation_job import GenerationJob
from drevalis.repositories.episode import EpisodeRepository
from drevalis.repositories.generation_job import GenerationJobRepository
from drevalis.repositories.media_asset import MediaAssetRepository
from drevalis.schemas.comfyui import WorkflowInputMapping
from drevalis.schemas.progress import ProgressMessage
from drevalis.schemas.script import EpisodeScript, SceneScript
from drevalis.services.ffmpeg import AssemblyConfig, AudioMixConfig, SceneInput

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.models.episode import Episode
    from drevalis.models.prompt_template import PromptTemplate
    from drevalis.models.series import Series
    from drevalis.services.captions import CaptionService
    from drevalis.services.comfyui import ComfyUIService
    from drevalis.services.ffmpeg import FFmpegService
    from drevalis.services.llm import LLMPool, LLMProvider, LLMService
    from drevalis.services.music import MusicService  # noqa: TCH004
    from drevalis.services.storage import LocalStorage
    from drevalis.services.tts import TTSService


logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pipeline step enumeration and ordering
# ---------------------------------------------------------------------------


class PipelineStep(StrEnum):
    SCRIPT = "script"
    VOICE = "voice"
    SCENES = "scenes"
    CAPTIONS = "captions"
    ASSEMBLY = "assembly"
    THUMBNAIL = "thumbnail"


PIPELINE_ORDER: list[PipelineStep] = [
    PipelineStep.SCRIPT,
    PipelineStep.VOICE,
    PipelineStep.SCENES,
    PipelineStep.CAPTIONS,
    PipelineStep.ASSEMBLY,
    PipelineStep.THUMBNAIL,
]


class _DefaultPromptDict(dict[str, str]):
    """``str.format_map``-friendly dict that returns ``""`` for missing keys.

    Lets the visual-refiner template substitute any subset of
    ``{scene_prompt} {style} {character} {prompt}`` without raising on
    placeholders the caller didn't pass. Falsy result is intentional —
    we'd rather leak an empty string than crash the whole script.
    """

    def __missing__(self, key: str) -> str:
        return ""


_VISUAL_REFINER_FALLBACK_SYSTEM = """You rewrite a single image generation prompt to be specific, voiced, and free of cargo-cult tokens.

REQUIRED — every output prompt contains:
1. CAMERA FRAMING — exactly one of: close-up, medium, wide, overhead, low-angle, over-the-shoulder, eye-level, three-quarter
2. LIGHTING — named: golden hour, overcast soft, harsh midday, candlelit, neon, sodium streetlight, blue hour, fluorescent flicker, single-bulb practical
3. CONCRETE SUBJECT NOUN — name the literal thing being shown ("a brass sextant on stained linen" not "a scene of seafaring")
4. ATMOSPHERE OR DETAIL — one specific texture, weather, or material (rain on tarmac, dust motes, salt rust, wet cobblestone)

BANNED TOKENS — remove these from the input if present, never add them:
masterpiece, 8k, 4k, ultra detailed, ultra realistic, ultrarealistic, hyper realistic, hyperrealistic, high quality, best quality, professional, trending on artstation, award winning. Use "cinematic" only when followed by a specific lens or technique (anamorphic, shallow DOF, Dutch angle, lens flare).

STYLE — match the style parameter provided. If "noir" → contrast, hard shadows, rain. If "kodachrome 70s" → warm cast, slight grain, period-correct subjects. If empty, omit a style descriptor entirely.

OUTPUT — only the rewritten prompt, one line, no quotes, no commentary, no preamble."""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class PipelineOrchestrator:
    """Orchestrates the full episode generation pipeline.

    Runs as a single arq job.  Each step is executed sequentially.
    Completed steps are skipped on retry (resumability).
    Progress is broadcast via Redis pub/sub for WebSocket delivery.
    """

    def __init__(
        self,
        episode_id: UUID,
        db_session: AsyncSession,
        redis: Redis,
        llm_service: LLMService,
        comfyui_service: ComfyUIService,
        tts_service: TTSService,
        ffmpeg_service: FFmpegService,
        caption_service: CaptionService,
        storage: LocalStorage,
        music_service: MusicService | None = None,
    ) -> None:
        self.episode_id = episode_id
        self.db = db_session
        self.redis = redis
        self.llm_service = llm_service
        self.comfyui_service = comfyui_service
        self.tts_service = tts_service
        self.ffmpeg_service = ffmpeg_service
        self.caption_service = caption_service
        self.storage = storage
        self.music_service = music_service

        self.log = structlog.get_logger(__name__).bind(
            episode_id=str(episode_id),
        )

        # Repositories
        self.episode_repo = EpisodeRepository(db_session)
        self.job_repo = GenerationJobRepository(db_session)
        self.asset_repo = MediaAssetRepository(db_session)

        # Current job id -- set before each step for progress broadcasts.
        self._current_job_id: UUID | None = None

    # ── Cancellation check ──────────────────────────────────────────────

    async def _check_cancelled(self) -> None:
        """Check Redis for a cancel signal.

        Called at the start of the ``run()`` loop before each step.
        If the ``cancel:{episode_id}`` key is set, the pipeline raises
        :class:`asyncio.CancelledError` to abort cleanly.

        The cancel key is **not deleted here** — if an exception fires
        between the delete and the status flip, the signal would be
        lost and the UI would show "still generating" until the arq
        timeout kicked in. The ``run()`` finaliser clears it after
        the status update commits, under a ``try/except`` so a Redis
        hiccup during cleanup doesn't mask the cancellation itself.
        """
        cancel_key = f"cancel:{self.episode_id}"
        result = await self.redis.get(cancel_key)
        if result:
            self.log.info("pipeline_cancelled_by_user")
            raise asyncio.CancelledError(f"Episode {self.episode_id} cancelled by user")

    async def _clear_cancel_flag(self) -> None:
        """Drop the Redis cancel key once the episode's final status is
        persisted, so a subsequent generation of the same episode
        doesn't see the stale flag and abort immediately."""
        try:
            await self.redis.delete(f"cancel:{self.episode_id}")
        except Exception as exc:  # noqa: BLE001
            self.log.warning("cancel_flag_cleanup_failed", error=str(exc)[:120])

    # ── Error suggestions ────────────────────────────────────────────────

    @staticmethod
    def _get_error_suggestion(step: PipelineStep, exc: Exception) -> str:
        """Map common errors to actionable suggestions for the user."""
        error_str = str(exc).lower()
        if "comfyui" in error_str or "connection" in error_str:
            return "Check if ComfyUI is running and accessible"
        if "timeout" in error_str:
            return "The generation timed out. Try again or check GPU load"
        if "piper" in error_str or "edge_tts" in error_str:
            return "TTS service error. Check voice profile configuration"
        if "ffmpeg" in error_str:
            return "Video assembly failed. Check FFmpeg installation"
        if "cancelled" in error_str:
            return "Generation was cancelled by user"
        if "llm" in error_str or "openai" in error_str or "anthropic" in error_str:
            return "LLM service error. Check LLM config and API key"
        if "whisper" in error_str:
            return "Caption generation failed. Check faster-whisper installation"
        if "no " in error_str and "found" in error_str:
            return f"Missing required asset for step '{step.value}'. Run previous steps first"
        return "Try retrying this step"

    # ── Public entry point ────────────────────────────────────────────────

    async def run(self) -> None:
        """Execute the full pipeline, skipping completed steps."""
        # Refresh ComfyUI pool from DB so retries always see current servers
        await self._refresh_comfyui_pool()

        episode = await self._load_episode()

        series = episode.series  # eager-loaded

        # Bind top-level pipeline context so all log lines include episode_id
        bind_pipeline_context(episode_id=str(self.episode_id))

        self.log.info(
            "pipeline_start",
            series_id=str(series.id),
            title=episode.title,
        )

        # Check cancellation BEFORE flipping the episode to "generating".
        # Otherwise a cancel issued while the job was queued would be
        # observed here, we'd exit cleanly — but the status would already
        # have been flipped back to "generating", leaving the episode
        # stuck until the next worker restart triggered orphan cleanup.
        try:
            await self._check_cancelled()
        except asyncio.CancelledError:
            self.log.info("pipeline_cancelled_before_start")
            await self.episode_repo.update_status(self.episode_id, "failed")
            await self.db.commit()
            # Only clear the Redis flag AFTER the DB commit succeeded —
            # a mid-step crash between delete+commit previously lost
            # the cancellation signal.
            await self._clear_cancel_flag()
            await metrics.record_generation(self.redis, success=False)
            clear_pipeline_context()
            return

        await self.episode_repo.update_status(self.episode_id, "generating")
        await self.db.commit()

        for step in PIPELINE_ORDER:
            # Check for user-initiated cancellation before each step.
            try:
                await self._check_cancelled()
            except asyncio.CancelledError:
                self.log.info("pipeline_cancelled_before_step", step=step.value)
                await self._broadcast_progress(
                    step,
                    0,
                    "failed",
                    "Generation cancelled by user",
                    error="Cancelled by user",
                )
                # Episode status stays "failed" (set by the cancel endpoint).
                # Defensive: flip it again here so a cancel-mid-run also
                # leaves a consistent record on disk.
                await self.episode_repo.update_status(self.episode_id, "failed")
                await self.db.commit()
                await self._clear_cancel_flag()
                await metrics.record_generation(self.redis, success=False)
                clear_pipeline_context()
                return  # Exit cleanly.

            # Check if step already completed
            existing_job = await self.job_repo.get_latest_by_episode_and_step(
                self.episode_id, step.value
            )
            if existing_job and existing_job.status == "done":
                self.log.info("step_already_complete", step=step.value)
                continue

            # Create or update job record
            job = await self._ensure_job(step, existing_job)
            self._current_job_id = job.id

            # Bind step-level context
            bind_pipeline_context(
                episode_id=str(self.episode_id),
                step=step.value,
                job_id=str(job.id),
            )

            step_start = time.perf_counter()

            # Install a per-step LLM token accumulator. Every
            # provider.generate() call during this step bumps the
            # counters via contextvar; we persist them on the job row
            # when the step finishes successfully.
            from drevalis.core.usage import end_accumulator, start_accumulator

            token_acc, token_reset = start_accumulator()

            try:
                await self._broadcast_progress(step, 0, "running", f"Starting {step.value}...")
                await self._execute_step(step, episode, series, job)
                # Persist accumulated token spend before marking done —
                # _mark_step_done commits, so the UPDATE goes in the
                # same transaction.
                if token_acc.prompt_tokens or token_acc.completion_tokens:
                    await self.job_repo.update(
                        job.id,
                        tokens_prompt=token_acc.prompt_tokens,
                        tokens_completion=token_acc.completion_tokens,
                    )
                await self._mark_step_done(job)
                await self._broadcast_progress(step, 100, "done", f"{step.value} complete")

                # Run quality gates (best-effort, never raises). Failed
                # gates surface as warnings on the progress channel; the
                # operator decides whether to retry the step.
                await self._run_quality_gates(step, episode)

                # Record successful step metric
                step_duration = time.perf_counter() - step_start
                await metrics.record_step(
                    self.redis,
                    step=step.value,
                    duration=step_duration,
                    success=True,
                    episode_id=str(self.episode_id),
                )
                self.log.info(
                    "step_completed",
                    step=step.value,
                    duration_seconds=round(step_duration, 3),
                )

            except asyncio.CancelledError:
                # Cancellation during a step execution.
                step_duration = time.perf_counter() - step_start
                self.log.info(
                    "step_cancelled",
                    step=step.value,
                    duration_seconds=round(step_duration, 3),
                )
                await metrics.record_step(
                    self.redis,
                    step=step.value,
                    duration=step_duration,
                    success=False,
                    episode_id=str(self.episode_id),
                )
                await self._broadcast_progress(
                    step,
                    0,
                    "failed",
                    "Generation cancelled by user",
                    error="Cancelled by user",
                )
                await metrics.record_generation(self.redis, success=False)
                clear_pipeline_context()
                return  # Exit cleanly.

            except Exception as exc:
                # Record failed step metric
                step_duration = time.perf_counter() - step_start
                await metrics.record_step(
                    self.redis,
                    step=step.value,
                    duration=step_duration,
                    success=False,
                    episode_id=str(self.episode_id),
                )

                # Even on failure, persist any tokens the step did
                # consume — the user still paid for them.
                if token_acc.prompt_tokens or token_acc.completion_tokens:
                    try:
                        await self.job_repo.update(
                            job.id,
                            tokens_prompt=token_acc.prompt_tokens,
                            tokens_completion=token_acc.completion_tokens,
                        )
                    except Exception:  # noqa: BLE001 — don't mask original exc
                        pass

                suggestion = self._get_error_suggestion(step, exc)
                self.log.error(
                    "step_failed_with_duration",
                    step=step.value,
                    duration_seconds=round(step_duration, 3),
                    error=str(exc),
                    suggestion=suggestion,
                    exc_info=True,
                )

                await self._handle_step_failure(job, step, exc, suggestion=suggestion)

                # Record failed generation
                await metrics.record_generation(self.redis, success=False)
                clear_pipeline_context()
                end_accumulator(token_reset)
                raise  # Let arq handle retry
            finally:
                # Always tear down the contextvar so the next step
                # gets a clean accumulator — except on the already-handled
                # raise-path above which already called it.
                try:
                    end_accumulator(token_reset)
                except Exception:  # noqa: BLE001
                    pass

        # All steps done
        await self.episode_repo.update_status(self.episode_id, "review")
        await self.db.commit()
        await self._broadcast_progress(PipelineStep.THUMBNAIL, 100, "done", "pipeline_complete")

        # Record successful generation
        await metrics.record_generation(self.redis, success=True)
        self.log.info("pipeline_complete")
        clear_pipeline_context()

    # ── Quality gates ─────────────────────────────────────────────────────

    async def _run_quality_gates(self, step: PipelineStep, episode: Episode) -> None:
        """Run post-step QA. Best-effort — exceptions are swallowed."""
        try:
            from drevalis.repositories.media_asset import MediaAssetRepository
            from drevalis.services import quality_gates as qg

            asset_repo = MediaAssetRepository(self.db)

            if step == PipelineStep.SCRIPT:
                # Reload the persisted script — _step_script committed
                # the new value; the in-memory ``episode`` from the
                # outer ``run()`` is the pre-write version (script={}).
                # _load_episode also eager-loads series so the gate has
                # a tone_profile without an extra round-trip.
                fresh = await self._load_episode()
                # Defensive isinstance — under unit-test mocks ``fresh``
                # may be a MagicMock and ``fresh.script`` a magic
                # attribute that's truthy but not a dict; we'd rather
                # short-circuit than walk a phantom script.
                if not isinstance(fresh.script, dict) or not fresh.script:
                    return
                tone_profile: dict[str, Any] | None = None
                series_obj = fresh.series if fresh.series is not None else None
                if series_obj is not None:
                    raw_tp = getattr(series_obj, "tone_profile", None)
                    if isinstance(raw_tp, dict):
                        tone_profile = raw_tp
                try:
                    script_obj = EpisodeScript.model_validate(fresh.script)
                except Exception:  # noqa: BLE001
                    return
                report = await qg.check_script_content(script_obj, tone_profile)
                if not report.passed:
                    summary = "; ".join(report.issues[:6])
                    if len(report.issues) > 6:
                        summary += f"; …and {len(report.issues) - 6} more"
                    self.log.info(
                        "script_quality_warnings",
                        issues=report.issues,
                        metrics=report.metrics,
                    )
                    await self._broadcast_progress(
                        step,
                        100,
                        "warning",
                        f"Script quality: {summary}",
                    )

            elif step == PipelineStep.VOICE:
                voice_assets = await asset_repo.get_by_episode_and_type(episode.id, "voice")
                for asset in voice_assets:
                    full = self.storage.resolve_path(asset.file_path)
                    report = await qg.check_voice_track(full)
                    if not report.passed:
                        await self._broadcast_progress(
                            step,
                            100,
                            "warning",
                            f"Voice quality: {'; '.join(report.issues)}",
                        )

            elif step == PipelineStep.SCENES:
                scene_assets = await asset_repo.get_by_episode_and_type(episode.id, "scene_image")
                # Sample a handful of scenes — gating every scene image on every
                # generation is slow on long-form. Always check the first and
                # last; sample three from the middle when there are many.
                if scene_assets:
                    sample_idx = {0, len(scene_assets) - 1}
                    if len(scene_assets) > 5:
                        mid = len(scene_assets) // 2
                        sample_idx |= {mid - 1, mid, mid + 1}
                    for idx in sorted(sample_idx):
                        asset = scene_assets[idx]
                        full = self.storage.resolve_path(asset.file_path)
                        report = await qg.check_scene_image(full)
                        if not report.passed:
                            await self._broadcast_progress(
                                step,
                                100,
                                "warning",
                                f"Scene {idx + 1} quality: {'; '.join(report.issues)}",
                            )
        except Exception as exc:  # noqa: BLE001
            self.log.debug("quality_gate_failed", step=step.value, error=str(exc)[:200])

    # ── Step dispatcher ───────────────────────────────────────────────────

    async def _execute_step(
        self,
        step: PipelineStep,
        episode: Episode,
        series: Series,
        job: GenerationJob,
    ) -> None:
        """Dispatch to the correct step handler."""
        handlers = {
            PipelineStep.SCRIPT: self._step_script,
            PipelineStep.VOICE: self._step_voice,
            PipelineStep.SCENES: self._step_scenes,
            PipelineStep.CAPTIONS: self._step_captions,
            PipelineStep.ASSEMBLY: self._step_assembly,
            PipelineStep.THUMBNAIL: self._step_thumbnail,
        }
        await handlers[step](episode, series, job)

    # ── Step implementations ──────────────────────────────────────────────

    async def _step_script(
        self,
        episode: Episode,
        series: Series,
        job: GenerationJob,
    ) -> None:
        """Step 1: Generate script via LLM."""
        self.log.info("step_script_start")

        # Resolve LLM config (episode override > series default > first available)
        llm_config = episode.override_llm_config or series.llm_config
        if llm_config is None:
            llm_config = await self._auto_select_llm_config()
            if llm_config is None:
                raise ValueError("No LLM config available -- create one in Settings.")

        prompt_template = series.script_prompt_template
        if prompt_template is None:
            prompt_template = await self._auto_select_prompt_template("script")
            if prompt_template is None:
                raise ValueError("No script prompt template available -- create one in Settings.")

        topic = episode.topic or episode.title
        character_description = series.character_description or ""

        # Use series content_format as the source of truth — episodes inherit it
        content_format = getattr(series, "content_format", "shorts") or "shorts"

        # music_video is a superset of the longform path: same chunked
        # script, chapter metadata, and assembly. Format-specific
        # behaviour (lyric-aware audio) layers on top of the longform
        # output further down.
        effective_longform = content_format in ("longform", "music_video")

        await self._broadcast_progress(
            PipelineStep.SCRIPT, 10, "running", "Generating episode script..."
        )

        if effective_longform:
            # Long-form: chunked multi-chapter generation
            from drevalis.services.llm import LLMPool as _LLMPool
            from drevalis.services.longform_script import LongFormScriptService

            # Respect episode-level override — users who pin "use Claude
            # for this specific premium long-form episode" expect that
            # exact provider, not a round-robin across every configured
            # LLM. Fall back to the full pool only when no override is
            # set, so load balancing + retries across backends still
            # happens for standard generations.
            if episode.override_llm_config is not None:
                override_provider = self.llm_service.get_provider(episode.override_llm_config)
                pool: _LLMPool = _LLMPool([(episode.override_llm_config.name, override_provider)])
            else:
                pool = await self._build_llm_pool()
            lf_service = LongFormScriptService(
                provider=pool,
                visual_consistency_prompt=getattr(series, "visual_consistency_prompt", "") or "",
                character_description=character_description,
                tone_profile=getattr(series, "tone_profile", None),
                language_code=getattr(series, "default_language", None) or "en-US",
            )

            target_minutes = getattr(series, "target_duration_minutes", None) or 30
            chapter_count = None  # auto-calculate from duration
            scenes_per_chapter = getattr(series, "scenes_per_chapter", 8)

            result = await lf_service.generate(
                topic=topic,
                series_description=series.description or "",
                target_duration_minutes=target_minutes,
                chapter_count=chapter_count,
                scenes_per_chapter=scenes_per_chapter,
                visual_style=series.visual_style or "",
                negative_prompt=series.negative_prompt or "",
            )

            # Best-effort visual prompt refinement via template (longform path).
            # Failures are swallowed to preserve the generated script.
            if series.visual_prompt_template:
                await self._refine_visual_prompts(
                    script_data=result["script"],
                    provider=pool,
                    template=series.visual_prompt_template,
                    visual_style=series.visual_style or "",
                    character_description=character_description,
                )

            await self._broadcast_progress(PipelineStep.SCRIPT, 80, "running", "Saving script...")

            # Phase 2.10 — populate ``narration_tts`` per scene on the
            # raw script dict before persistence. Same provider-quirk
            # rules as the shorts branch.
            await self._populate_narration_tts_dict(result["script"], episode, series)

            # Preserve the episode's actual ``content_format`` —
            # music_video also takes the long-form path, but overwriting
            # it with "longform" would misclassify the episode for every
            # downstream query (priority sort, workflow selection, UI
            # badge).
            await self.episode_repo.update(
                self.episode_id,
                script=result["script"],
                chapters=result["chapters"],
                title=result["title"] or episode.title,
                content_format=content_format,
            )
            await self.db.commit()

            self.log.info(
                "step_script_done",
                content_format=content_format,
                scenes=len(result["script"].get("scenes", [])),
                chapters=len(result["chapters"]),
            )
        else:
            # Shorts: existing single-call generation
            target_duration = series.target_duration_seconds

            script: EpisodeScript = await self.llm_service.generate_script(
                config=llm_config,
                prompt_template=prompt_template,
                topic=topic,
                character_description=character_description,
                target_duration=target_duration,
                language_code=getattr(series, "default_language", None),
                tone_profile=getattr(series, "tone_profile", None),
                visual_style=series.visual_style or "",
                negative_prompt=series.negative_prompt or "",
            )

            # Best-effort visual prompt refinement via template (shorts path).
            # Failures are swallowed to preserve the generated script.
            if series.visual_prompt_template:
                script_data_shorts: dict[str, Any] = script.model_dump()
                shorts_provider = self.llm_service.get_provider(llm_config)
                await self._refine_visual_prompts(
                    script_data=script_data_shorts,
                    provider=shorts_provider,
                    template=series.visual_prompt_template,
                    visual_style=series.visual_style or "",
                    character_description=character_description,
                )
                # Re-validate so the refined dict is used for persistence.
                from drevalis.schemas.script import EpisodeScript as _EpisodeScript

                script = _EpisodeScript.model_validate(script_data_shorts)

            # Phase 2.10 — populate ``narration_tts`` per scene based on
            # the resolved voice profile's provider quirks. Best-effort:
            # any failure leaves ``narration_tts`` unset and the TTS step
            # falls back to the original ``narration``.
            await self._populate_narration_tts(script, episode, series)

            await self._broadcast_progress(PipelineStep.SCRIPT, 80, "running", "Saving script...")

            await self.episode_repo.update(
                self.episode_id,
                script=script.model_dump(),
                title=script.title if script.title else episode.title,
            )
            await self.db.commit()

            self.log.info(
                "step_script_done",
                content_format="shorts",
                scenes=len(script.scenes),
                total_duration=script.total_duration_seconds,
            )

    async def _refine_visual_prompts(
        self,
        script_data: dict[str, Any],
        provider: LLMProvider,
        template: PromptTemplate | None,
        visual_style: str,
        character_description: str,
    ) -> None:
        """Best-effort refinement of every scene's visual_prompt via a template.

        Iterates over scenes in *script_data* and replaces each ``visual_prompt``
        value with the LLM-refined version.  Any per-scene failure is caught and
        logged; the original prompt is preserved so a single bad scene cannot
        abort the entire script.

        This method mutates *script_data* in place and returns nothing.

        Args:
            script_data: The raw script dict (contains a ``"scenes"`` list).
            provider: An object satisfying the LLMProvider protocol.
            template: A ``PromptTemplate`` ORM instance with ``system_prompt``
                and ``user_prompt_template`` attributes.
            visual_style: Optional series visual style appended to the prompt.
            character_description: Optional character context appended to the prompt.
        """
        scenes = script_data.get("scenes", [])
        if not scenes:
            return

        # Resolve system prompt: fall back to a sensible default when the
        # template's system_prompt is blank.
        refine_system: str = (
            getattr(template, "system_prompt", "") or _VISUAL_REFINER_FALLBACK_SYSTEM
        )

        user_template: str = getattr(template, "user_prompt_template", "") or (
            "Original prompt:\n{scene_prompt}\n\nStyle target: {style}\n\n"
            "Character appearance (only relevant if a person is shown): {character}\n\n"
            "Rewrite the prompt."
        )

        async def _refine_one(scene_data: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            raw_vp: str = scene_data.get("visual_prompt", "")
            if not raw_vp:
                return scene_data, None
            substitutions: dict[str, str] = {
                "scene_prompt": raw_vp,
                "style": visual_style or "",
                "character": character_description or "",
                # Legacy alias — old templates that pre-date the
                # ``{scene_prompt}`` rename still substitute correctly.
                "prompt": raw_vp,
            }
            try:
                refine_user = user_template.format_map(_DefaultPromptDict(substitutions))
            except (KeyError, ValueError, IndexError):
                # Template has unrecognised placeholders or malformed
                # format spec. Fall back to the legacy ``{prompt}``
                # behaviour so an out-of-band template doesn't break
                # the whole script.
                refine_user = user_template.replace("{prompt}", raw_vp)
                if visual_style:
                    refine_user += f"\nVisual style: {visual_style}"
                if character_description:
                    refine_user += f"\nCharacter: {character_description}"
            try:
                result = await provider.generate(
                    refine_system,
                    refine_user,
                    temperature=0.5,
                    max_tokens=256,
                )
                refined = result.content.strip().strip('"')
                if len(refined) > 20:
                    return scene_data, refined
            except Exception as exc:
                # Refinement failure means the scene falls back to the
                # raw LLM-generated prompt — visible quality degradation
                # the user can't otherwise diagnose. Log at warning so
                # the cause (provider 5xx, timeout, rate limit) is in
                # the operator's normal log stream.
                self.log.warning(
                    "step_script.visual_prompt_refine_failed",
                    scene=scene_data.get("scene_number"),
                    error=str(exc)[:120],
                )
            return scene_data, None

        results = await asyncio.gather(*(_refine_one(s) for s in scenes), return_exceptions=False)
        refined_count = 0
        for scene_data, refined in results:
            if refined is not None:
                scene_data["visual_prompt"] = refined
                refined_count += 1

        self.log.info(
            "step_script.visual_prompts_refined",
            total_scenes=len(scenes),
            refined=refined_count,
        )

    # ── Phase 2.10 narration TTS formatting ─────────────────────────────

    def _resolve_voice_provider_key(
        self,
        episode: Episode,
        series: Series,
    ) -> str | None:
        """Resolve which TTS provider will synthesise this episode so the
        narration formatter can pick the right rule set.

        Episode override beats series default. Returns ``None`` when no
        voice profile is set yet — narration_tts stays unset and the TTS
        step falls back to ``narration``.
        """
        voice_profile = getattr(episode, "override_voice_profile", None) or series.voice_profile
        if voice_profile is None:
            return None
        provider = getattr(voice_profile, "provider", None)
        return str(provider).lower() if provider else None

    async def _populate_narration_tts(
        self,
        script: EpisodeScript,
        episode: Episode,
        series: Series,
    ) -> None:
        """Mutate ``script.scenes`` in place, setting ``narration_tts``
        when the formatter produces a non-trivial rewrite. No-op when no
        voice profile is resolvable yet."""
        provider_key = self._resolve_voice_provider_key(episode, series)
        if provider_key is None:
            return
        from drevalis.services.narration_formatter import format_for_tts

        rewritten = 0
        for scene in script.scenes:
            try:
                tts_text = format_for_tts(scene.narration, provider_key)
            except Exception as exc:  # noqa: BLE001
                self.log.warning(
                    "step_script.narration_tts_failed",
                    scene=scene.scene_number,
                    error=str(exc)[:120],
                )
                continue
            if tts_text:
                scene.narration_tts = tts_text
                rewritten += 1
        self.log.info(
            "step_script.narration_tts_populated",
            provider=provider_key,
            total_scenes=len(script.scenes),
            rewritten=rewritten,
        )

    async def _populate_narration_tts_dict(
        self,
        script_dict: dict[str, Any],
        episode: Episode,
        series: Series,
    ) -> None:
        """Same as :meth:`_populate_narration_tts` but operates on the
        raw script dict (the longform path persists from this rather
        than from an EpisodeScript instance)."""
        provider_key = self._resolve_voice_provider_key(episode, series)
        if provider_key is None:
            return
        from drevalis.services.narration_formatter import format_for_tts

        scenes = script_dict.get("scenes", [])
        if not isinstance(scenes, list):
            return
        rewritten = 0
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            narration = scene.get("narration") or ""
            try:
                tts_text = format_for_tts(narration, provider_key)
            except Exception as exc:  # noqa: BLE001
                self.log.warning(
                    "step_script.narration_tts_failed",
                    scene=scene.get("scene_number"),
                    error=str(exc)[:120],
                )
                continue
            if tts_text:
                scene["narration_tts"] = tts_text
                rewritten += 1
        self.log.info(
            "step_script.narration_tts_populated",
            provider=provider_key,
            total_scenes=len(scenes),
            rewritten=rewritten,
        )

    async def _step_voice(
        self,
        episode: Episode,
        series: Series,
        job: GenerationJob,
    ) -> None:
        """Step 2: Generate voiceover via TTS."""
        self.log.info("step_voice_start")

        # Reload episode to get the script persisted in step 1
        episode = await self._load_episode()
        if not episode.script:
            raise ValueError("Episode has no script -- run the script step first.")

        script = EpisodeScript.model_validate(episode.script)

        # Resolve voice profile (episode override > series default > first available)
        voice_profile = episode.override_voice_profile or series.voice_profile
        if voice_profile is None:
            voice_profile = await self._auto_select_voice_profile()
            if voice_profile is None:
                raise ValueError("No voice profile available -- create one in Settings.")

        await self._broadcast_progress(
            PipelineStep.VOICE, 10, "running", "Synthesising voiceover..."
        )

        # Extract per-episode TTS overrides written by regenerate-voice
        # (api/routes/episodes). Shape: ``metadata_["tts_overrides"] =
        # {"speed": 1.1, "pitch": 0.95}``. Values outside these bounds
        # are ignored so a malformed metadata row can't break synthesis.
        tts_overrides: dict[str, Any] = {}
        if isinstance(episode.metadata_, dict):
            raw = episode.metadata_.get("tts_overrides")
            if isinstance(raw, dict):
                tts_overrides = raw
        speed_override: float | None = None
        pitch_override: float | None = None
        try:
            if "speed" in tts_overrides:
                v = float(tts_overrides["speed"])
                if 0.25 <= v <= 4.0:
                    speed_override = v
            if "pitch" in tts_overrides:
                # The UI / API accept semitones in [-12.0, +12.0]; translate
                # to the internal multiplier [0.5, 2.0] (±1 octave) so the
                # two don't drift. Only Edge TTS honours this today; Piper /
                # Kokoro / ElevenLabs ignore ``pitch_override`` — logged once
                # so users aren't surprised by a silent no-op.
                v = float(tts_overrides["pitch"])
                if -12.0 <= v <= 12.0 and abs(v) > 0.01:
                    # 2^(semitones/12) → multiplier; clamp to the internal
                    # range just in case a caller sends the multiplier form.
                    import math as _math

                    if 0.5 <= v <= 2.0 and abs(v - 1.0) > 0.01:
                        pitch_override = v  # already in multiplier form
                    else:
                        pitch_override = max(0.5, min(2.0, _math.pow(2.0, v / 12.0)))
        except (TypeError, ValueError):
            self.log.warning("tts_overrides_malformed", overrides=tts_overrides)

        tts_result = await self.tts_service.generate_voiceover(
            voice_profile=voice_profile,
            script=script,
            episode_id=self.episode_id,
            speed_override=speed_override,
            pitch_override=pitch_override,
        )

        await self._broadcast_progress(
            PipelineStep.VOICE, 80, "running", "Saving voiceover asset..."
        )

        # Compute file size
        audio_path = Path(tts_result.audio_path)
        file_size = audio_path.stat().st_size if audio_path.exists() else None

        # Store relative path for the media asset
        relative_path = f"episodes/{self.episode_id}/audio/voiceover.wav"

        await self.asset_repo.create(
            episode_id=self.episode_id,
            asset_type="voiceover",
            file_path=relative_path,
            file_size_bytes=file_size,
            duration_seconds=tts_result.duration_seconds,
            generation_job_id=job.id,
        )
        await self.db.commit()

        # Save word timestamps as sidecar JSON for the captions step
        if tts_result.word_timestamps:
            import json as _json

            ts_path = self.storage.resolve_path(
                f"episodes/{self.episode_id}/audio/word_timestamps.json"
            )
            ts_data = [
                {
                    "word": wt.word,
                    "start_seconds": wt.start_seconds,
                    "end_seconds": wt.end_seconds,
                }
                for wt in tts_result.word_timestamps
            ]
            ts_path.parent.mkdir(parents=True, exist_ok=True)
            ts_path.write_text(_json.dumps(ts_data))
            self.log.info(
                "word_timestamps_saved",
                count=len(ts_data),
                path=str(ts_path),
            )

        self.log.info(
            "step_voice_done",
            duration=tts_result.duration_seconds,
            has_timestamps=tts_result.word_timestamps is not None,
            word_count=len(tts_result.word_timestamps) if tts_result.word_timestamps else 0,
        )

    async def _step_scenes(
        self,
        episode: Episode,
        series: Series,
        job: GenerationJob,
    ) -> None:
        """Step 3: Generate scene visuals via ComfyUI (parallel).

        Supports two modes controlled by ``series.scene_mode``:
        - ``"image"`` (default): generates still images via the image workflow.
        - ``"video"``: generates ~5 s video clips via the Wan 2.6 video workflow.
        """
        self.log.info("step_scenes_start")

        # Reload episode for latest script
        episode = await self._load_episode()
        if not episode.script:
            raise ValueError("Episode has no script -- run the script step first.")

        script = EpisodeScript.model_validate(episode.script)

        # Resolve ComfyUI config from the series, but only if still active.
        # On retries the series FK may point to a server that was deactivated
        # or removed since the original generation — always validate.
        comfyui_server = series.comfyui_server
        if comfyui_server is not None and not comfyui_server.is_active:
            self.log.warning(
                "comfyui_server_inactive_fallback",
                server_id=str(comfyui_server.id),
                name=comfyui_server.name,
            )
            comfyui_server = None
        if comfyui_server is None:
            comfyui_server = await self._auto_select_comfyui_server()
            if comfyui_server is None:
                raise ValueError("No ComfyUI server available -- add one in Settings.")

        # Determine scene mode (default to "image" for backwards compat)
        scene_mode = getattr(series, "scene_mode", "image") or "image"
        is_video_mode = scene_mode == "video"

        if is_video_mode:
            # Video mode: use the video-specific workflow
            video_workflow = getattr(series, "video_comfyui_workflow", None)
            if video_workflow is None:
                raise ValueError(
                    "Video scene mode requires a video ComfyUI workflow. "
                    "Set video_comfyui_workflow_id on the series."
                )
            comfyui_workflow = video_workflow
        else:
            comfyui_workflow = series.comfyui_workflow
            if comfyui_workflow is None:
                comfyui_workflow = await self._auto_select_comfyui_workflow()
                if comfyui_workflow is None:
                    raise ValueError("No ComfyUI workflow available -- add one in Settings.")

        input_mappings = WorkflowInputMapping.model_validate(comfyui_workflow.input_mappings)

        visual_style = series.visual_style or ""
        character_description = series.character_description or ""

        # Prepend visual_consistency_prompt for ALL content formats (shorts and
        # long-form alike) so every series benefits from consistent framing.
        visual_consistency = getattr(series, "visual_consistency_prompt", None)
        if visual_consistency:
            visual_style = (
                f"{visual_consistency}, {visual_style}" if visual_style else visual_consistency
            )

        # base_seed for deterministic seeded RNG inside ComfyUI prompt building.
        base_seed = getattr(series, "base_seed", None)

        total_scenes = len(script.scenes)

        # Check for existing scene assets from a partial previous run so we
        # can skip already-completed scenes instead of re-generating them.
        existing_asset_type = "scene_video" if is_video_mode else "scene"
        existing_scene_assets = await self.asset_repo.get_by_episode_and_type(
            self.episode_id, existing_asset_type
        )
        existing_scene_numbers: set[int] = {
            a.scene_number for a in existing_scene_assets if a.scene_number is not None
        }

        # ── Phase B: per-scene source-asset override ────────────────────
        # Copy the user-provided asset straight into the episode scenes
        # dir and record a media_asset for it, then exclude that scene
        # from ComfyUI generation. This is the "I already have the image
        # / video clip for this scene" path.
        await self._apply_scene_asset_overrides(
            episode_id=self.episode_id,
            scenes=script.scenes,
            existing_scene_numbers=existing_scene_numbers,
            is_video_mode=is_video_mode,
            job_id=job.id,
        )

        scenes_to_generate = [
            s
            for s in script.scenes
            if s.scene_number not in existing_scene_numbers
            and not getattr(s, "source_asset_id", None)
        ]

        # ── Phase B: reference asset resolution (IPAdapter conditioning)
        # Episode-level wins over series-level. The list is passed down
        # to the ComfyUI service; workflows that don't declare an
        # ``ipadapter_reference`` input slot simply ignore it.
        reference_asset_ids = (
            getattr(episode, "reference_asset_ids", None)
            or getattr(series, "reference_asset_ids", None)
            or []
        )
        reference_asset_paths = await self._resolve_reference_asset_paths(reference_asset_ids)
        if reference_asset_paths:
            self.log.info(
                "scenes_reference_assets",
                count=len(reference_asset_paths),
                source="episode" if getattr(episode, "reference_asset_ids", None) else "series",
            )

        # ── Phase E: character / style locks ─────────────────────────
        # Each lock is ``{"asset_ids": [...], "strength": float, "lora": str}``.
        # We resolve asset IDs → absolute paths here and hand the tuple
        # off to ComfyUI. Workflows that don't declare matching named
        # inputs silently ignore them.
        character_lock = getattr(series, "character_lock", None) or None
        style_lock = getattr(series, "style_lock", None) or None
        character_lock_paths = await self._resolve_reference_asset_paths(
            (character_lock or {}).get("asset_ids") or []
        )
        style_lock_paths = await self._resolve_reference_asset_paths(
            (style_lock or {}).get("asset_ids") or []
        )
        if character_lock_paths or style_lock_paths:
            self.log.info(
                "scenes_phase_e_locks",
                character_refs=len(character_lock_paths),
                style_refs=len(style_lock_paths),
            )

        if existing_scene_numbers:
            self.log.info(
                "scenes_partial_resume",
                existing=len(existing_scene_numbers),
                remaining=len(scenes_to_generate),
                total=total_scenes,
            )

        media_label = "video clips" if is_video_mode else "scene images"
        await self._broadcast_progress(
            PipelineStep.SCENES,
            5,
            "running",
            f"Generating {len(scenes_to_generate)} {media_label} "
            f"({len(existing_scene_numbers)} already done)..."
            if existing_scene_numbers
            else f"Generating {total_scenes} {media_label}...",
            detail={"total_scenes": total_scenes, "completed": len(existing_scene_numbers)},
        )

        # Ensure the resolved server is registered in the pool.
        # sync_from_db (called at pipeline start) handles this, but if the
        # auto-selected server was picked after the sync we need a safety net.
        # Only register if the server is still marked active.
        if comfyui_server.is_active:
            from drevalis.services.comfyui import ComfyUIClient

            pool = self.comfyui_service._pool
            if comfyui_server.id not in pool._servers:
                client = ComfyUIClient(
                    base_url=comfyui_server.url,
                    api_key=None,
                )
                pool.register_server(
                    server_id=comfyui_server.id,
                    client=client,
                    max_concurrent=comfyui_server.max_concurrent,
                )

        # Ensure episode directories exist
        await self.storage.ensure_episode_dirs(self.episode_id)

        # Per-series negative prompt override (None falls back to default).
        negative_prompt = getattr(series, "negative_prompt", None) or None

        # Build a progress callback for per-scene updates.
        async def _scene_progress(message: str, scene_number: int) -> None:
            pct = 5 + int(85 * scene_number / total_scenes)
            await self._broadcast_progress(
                PipelineStep.SCENES,
                pct,
                "running",
                message,
                detail={
                    "scene_number": scene_number,
                    "total_scenes": total_scenes,
                },
            )

        if is_video_mode:
            # ── Video mode ──────────────────────────────────────────────
            # For i2v workflows, pass the image workflow so we generate
            # a scene image first, then animate it.
            image_wf = series.comfyui_workflow  # the standard image workflow
            image_wf_path = image_wf.workflow_json_path if image_wf else None
            image_mappings = None
            if image_wf and image_wf.input_mappings:
                image_mappings = WorkflowInputMapping.model_validate(image_wf.input_mappings)

            # Phase E: resolve per-scene motion-reference video assets
            # (workflows without a matching input slot ignore this).
            motion_ref_paths: dict[int, str] = {}
            for s in scenes_to_generate:
                ref_id = getattr(s, "motion_reference_asset_id", None)
                if not ref_id:
                    continue
                try:
                    paths = await self._resolve_reference_asset_paths([ref_id], kinds=("video",))
                except Exception:
                    paths = []
                if paths:
                    motion_ref_paths[s.scene_number] = paths[0]

            generated_videos = await self.comfyui_service.generate_scene_videos(
                server_id=None,  # Let the pool distribute across all servers
                workflow_path=comfyui_workflow.workflow_json_path,
                input_mappings=input_mappings,
                scenes=scenes_to_generate,
                visual_style=visual_style,
                character_description=character_description,
                episode_id=self.episode_id,
                negative_prompt=negative_prompt,
                image_workflow_path=image_wf_path,
                image_input_mappings=image_mappings,
                progress_callback=_scene_progress,
                base_seed=base_seed,
                motion_reference_paths_by_scene=motion_ref_paths or None,
            )

            for vid in generated_videos:
                # Use the scene_number carried by the result so partial
                # failures (some scenes raised, filtered out) don't shift
                # remaining successes onto the wrong scene_number.
                if vid.scene_number is None:
                    self.log.warning(
                        "scene_video_missing_scene_number",
                        file_path=vid.file_path,
                    )
                    continue
                scene_number = vid.scene_number

                # Skip if an asset already exists for this scene number to avoid
                # duplicate DB rows when partial results were already committed.
                if scene_number in existing_scene_numbers:
                    continue

                vid_path = self.storage.resolve_path(vid.file_path)
                file_size = vid_path.stat().st_size if vid_path.exists() else None

                await self.asset_repo.create(
                    episode_id=self.episode_id,
                    asset_type="scene_video",
                    file_path=vid.file_path,
                    file_size_bytes=file_size,
                    duration_seconds=vid.duration_seconds,
                    scene_number=scene_number,
                    generation_job_id=job.id,
                )

                pct = 10 + int(80 * scene_number / total_scenes)
                await self._broadcast_progress(
                    PipelineStep.SCENES,
                    pct,
                    "running",
                    f"Video clip {scene_number}/{total_scenes} saved",
                    detail={"scene_number": scene_number, "total_scenes": total_scenes},
                )

            await self.db.commit()

            self.log.info(
                "step_scenes_done",
                videos_generated=len(generated_videos),
                scene_mode="video",
            )
        else:
            # ── Image mode (original path) ──────────────────────────────
            generated_images = await self.comfyui_service.generate_scene_images(
                server_id=None,  # Let the pool distribute across all servers
                workflow_path=comfyui_workflow.workflow_json_path,
                input_mappings=input_mappings,
                scenes=scenes_to_generate,
                visual_style=visual_style,
                character_description=character_description,
                episode_id=self.episode_id,
                negative_prompt=negative_prompt,
                progress_callback=_scene_progress,
                base_seed=base_seed,
                reference_asset_paths=reference_asset_paths,
                character_lock=character_lock,
                style_lock=style_lock,
                character_lock_paths=character_lock_paths,
                style_lock_paths=style_lock_paths,
            )

            for img in generated_images:
                # Use the scene_number carried by the result so partial
                # failures don't shift remaining successes onto the wrong scene.
                if img.scene_number is None:
                    self.log.warning(
                        "scene_image_missing_scene_number",
                        file_path=img.file_path,
                    )
                    continue
                scene_number = img.scene_number

                # Skip if an asset already exists for this scene number to avoid
                # duplicate DB rows when partial results were already committed.
                if scene_number in existing_scene_numbers:
                    continue

                img_path = self.storage.resolve_path(img.file_path)
                file_size = img_path.stat().st_size if img_path.exists() else None

                await self.asset_repo.create(
                    episode_id=self.episode_id,
                    asset_type="scene",
                    file_path=img.file_path,
                    file_size_bytes=file_size,
                    scene_number=scene_number,
                    generation_job_id=job.id,
                )

                pct = 10 + int(80 * scene_number / total_scenes)
                await self._broadcast_progress(
                    PipelineStep.SCENES,
                    pct,
                    "running",
                    f"Scene {scene_number}/{total_scenes} saved",
                    detail={"scene_number": scene_number, "total_scenes": total_scenes},
                )

            await self.db.commit()

            self.log.info(
                "step_scenes_done",
                images_generated=len(generated_images),
                scene_mode="image",
            )

    # ── Phase B helpers ──────────────────────────────────────────────

    async def _apply_scene_asset_overrides(
        self,
        *,
        episode_id: UUID,
        scenes: list[SceneScript],
        existing_scene_numbers: set[int],
        is_video_mode: bool,
        job_id: UUID,
    ) -> None:
        """For any scene whose script carries a ``source_asset_id``,
        copy that asset's file into the episode's scenes dir and
        register a media_asset row. Mutates ``existing_scene_numbers``
        so the ComfyUI batch below treats these scenes as done.
        """
        import shutil as _shutil
        from pathlib import Path as _Path
        from uuid import UUID as _UUID

        from drevalis.repositories.asset import AssetRepository as _AssetRepo

        asset_repo = _AssetRepo(self.db)
        episode_path = await self.storage.get_episode_path(episode_id)
        scenes_dir = episode_path / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)

        for scene in scenes:
            src_id = getattr(scene, "source_asset_id", None)
            if not src_id or scene.scene_number in existing_scene_numbers:
                continue
            try:
                asset_uuid = _UUID(str(src_id))
            except ValueError:
                self.log.warning("scene_source_asset_invalid_uuid", value=src_id)
                continue
            asset = await asset_repo.get_by_id(asset_uuid)
            if asset is None:
                self.log.warning("scene_source_asset_missing", asset_id=src_id)
                continue
            src_abs = _Path(self.storage.base_path) / asset.file_path
            if not src_abs.exists():
                self.log.warning("scene_source_asset_file_missing", asset_id=src_id)
                continue

            # Preserve the asset's extension so downstream FFmpeg routing
            # (image vs video) picks the right demux.
            ext = src_abs.suffix.lower() or (".mp4" if asset.kind == "video" else ".jpg")
            # Keep naming scheme aligned with ComfyUI-generated scenes.
            dest_name = f"scene_{scene.scene_number:02d}{ext}"
            dest_abs = scenes_dir / dest_name
            _shutil.copyfile(src_abs, dest_abs)

            rel = dest_abs.relative_to(_Path(self.storage.base_path)).as_posix()
            asset_type = "scene_video" if (is_video_mode or asset.kind == "video") else "scene"
            await self.asset_repo.create(
                episode_id=episode_id,
                asset_type=asset_type,
                file_path=rel,
                file_size_bytes=dest_abs.stat().st_size,
                duration_seconds=asset.duration_seconds,
                scene_number=scene.scene_number,
                generation_job_id=job_id,
            )
            existing_scene_numbers.add(scene.scene_number)
            self.log.info(
                "scene_source_asset_applied",
                scene_number=scene.scene_number,
                asset_id=src_id,
                asset_type=asset_type,
            )
        await self.db.commit()

    async def _resolve_reference_asset_paths(
        self,
        reference_asset_ids: list[str] | None,
        *,
        kinds: tuple[str, ...] = ("image",),
    ) -> list[str]:
        """Resolve asset UUIDs → absolute filesystem paths.

        By default returns image assets only — suitable for IPAdapter-style
        reference inputs. Pass ``kinds=("video",)`` to resolve motion
        references for video-to-video workflows, etc.
        """
        from pathlib import Path as _Path
        from uuid import UUID as _UUID

        from drevalis.repositories.asset import AssetRepository as _AssetRepo

        out: list[str] = []
        if not reference_asset_ids:
            return out
        # Parse all UUIDs first; skip strings that don't parse so the
        # IN-clause stays clean and we still preserve insertion order
        # for the existing-asset lookup.
        parsed: list[_UUID] = []
        for raw_id in reference_asset_ids:
            try:
                parsed.append(_UUID(str(raw_id)))
            except ValueError:
                continue
        if not parsed:
            return out
        asset_repo = _AssetRepo(self.db)
        # One query for the whole list instead of one per id.
        assets_by_id = await asset_repo.get_by_ids(parsed)
        for asset_uuid in parsed:
            asset = assets_by_id.get(asset_uuid)
            if asset is None or asset.kind not in kinds:
                continue
            abs_path = _Path(self.storage.base_path) / asset.file_path
            if abs_path.exists():
                out.append(str(abs_path))
        return out

    async def _step_captions(
        self,
        episode: Episode,
        series: Series,
        job: GenerationJob,
    ) -> None:
        """Step 4: Generate captions from voiceover."""
        self.log.info("step_captions_start")

        # Find the voiceover asset
        voiceover_assets = await self.asset_repo.get_by_episode_and_type(
            self.episode_id, "voiceover"
        )
        if not voiceover_assets:
            raise ValueError("No voiceover asset found -- run the voice step first.")

        voiceover_asset = voiceover_assets[-1]  # most recent
        voiceover_abs_path = self.storage.resolve_path(voiceover_asset.file_path)

        # Determine the captions output directory
        episode_path = await self.storage.get_episode_path(self.episode_id)
        captions_dir = episode_path / "captions"
        captions_dir.mkdir(parents=True, exist_ok=True)

        await self._broadcast_progress(
            PipelineStep.CAPTIONS, 10, "running", "Generating captions..."
        )

        # Build CaptionStyle from series configuration (if any).
        # Per-episode override takes priority over series default.
        from drevalis.services.captions import CaptionStyle

        style = CaptionStyle(**series.caption_style) if series.caption_style else CaptionStyle()

        # Apply per-episode caption style override
        episode_caption_style = getattr(episode, "override_caption_style", None)
        if episode_caption_style:
            style.preset = episode_caption_style

        # Try to recover TTS word timestamps from the voiceover step.
        # We re-generate the voiceover result info by checking if the TTS
        # service cached timestamps.  If not available, fall back to
        # faster-whisper transcription.
        #
        # The TTS result word_timestamps are not persisted in the DB;
        # we always use audio-based caption generation as the reliable path.
        # If the TTS provider returned timestamps they are embedded in the
        # audio directory as a sidecar JSON file by the TTS service.
        timestamps_path = episode_path / "audio" / "word_timestamps.json"
        word_timestamps = None

        if timestamps_path.exists():
            try:
                import json as _json

                from drevalis.services.tts import WordTimestamp

                raw = _json.loads(timestamps_path.read_text(encoding="utf-8"))
                word_timestamps = [
                    WordTimestamp(
                        word=w["word"],
                        start_seconds=w["start_seconds"],
                        end_seconds=w["end_seconds"],
                    )
                    for w in raw
                ]
                self.log.info(
                    "captions_using_tts_timestamps",
                    word_count=len(word_timestamps),
                )
            except Exception:
                self.log.debug("captions_timestamps_parse_failed", exc_info=True)
                word_timestamps = None

        # Collect keywords from all scenes for animated overlays.
        episode = await self._load_episode()
        all_keywords: list[str] = []
        if episode.script:
            try:
                kw_script = EpisodeScript.model_validate(episode.script)
                for scene in kw_script.scenes:
                    all_keywords.extend(getattr(scene, "keywords", []))
            except Exception:
                self.log.debug("captions_keywords_parse_failed", exc_info=True)

        caption_keywords = all_keywords or None

        if word_timestamps:
            caption_result = await self.caption_service.generate_from_timestamps(
                word_timestamps=word_timestamps,
                output_dir=captions_dir,
                style=style,
                keywords=caption_keywords,
            )
        else:
            await self._broadcast_progress(
                PipelineStep.CAPTIONS,
                20,
                "running",
                "Transcribing audio with Whisper...",
            )
            raw_lang = (series.default_language or "en-US").strip("'\"")
            language = raw_lang.split("-")[0]
            caption_result = await self.caption_service.generate_from_audio(
                audio_path=voiceover_abs_path,
                output_dir=captions_dir,
                language=language,
                style=style,
                keywords=caption_keywords,
            )

        await self._broadcast_progress(
            PipelineStep.CAPTIONS, 80, "running", "Saving caption assets..."
        )

        # Save SRT asset
        srt_abs = Path(caption_result.srt_path)
        srt_relative = f"episodes/{self.episode_id}/captions/{srt_abs.name}"
        srt_size = srt_abs.stat().st_size if srt_abs.exists() else None
        await self.asset_repo.create(
            episode_id=self.episode_id,
            asset_type="caption",
            file_path=srt_relative,
            file_size_bytes=srt_size,
            generation_job_id=job.id,
        )

        # Save ASS asset
        ass_abs = Path(caption_result.ass_path)
        ass_relative = f"episodes/{self.episode_id}/captions/{ass_abs.name}"
        ass_size = ass_abs.stat().st_size if ass_abs.exists() else None
        await self.asset_repo.create(
            episode_id=self.episode_id,
            asset_type="caption",
            file_path=ass_relative,
            file_size_bytes=ass_size,
            generation_job_id=job.id,
        )

        await self.db.commit()

        self.log.info(
            "step_captions_done",
            caption_count=len(caption_result.captions),
        )

    async def _step_assembly(
        self,
        episode: Episode,
        series: Series,
        job: GenerationJob,
    ) -> None:
        """Step 5: Assemble final video from scenes + voiceover + captions.

        Supports two assembly paths:
        - **Video mode**: if ``scene_video`` assets exist (from Wan 2.6 or
          similar text-to-video workflows), concatenate the pre-rendered
          video clips with voiceover, captions, and optional music via
          :meth:`FFmpegService.concat_video_clips`.
        - **Image mode** (default): compose still images with Ken Burns
          effects via :meth:`FFmpegService.assemble_video`.
        """
        self.log.info("step_assembly_start")

        # Reload episode for script
        episode = await self._load_episode()
        if not episode.script:
            raise ValueError("Episode has no script.")

        script = EpisodeScript.model_validate(episode.script)

        # ── Determine assembly mode: check for video clips first ─────────
        scene_video_assets = await self.asset_repo.get_by_episode_and_type(
            self.episode_id, "scene_video"
        )
        use_video_concat = bool(scene_video_assets)

        if use_video_concat:
            scene_video_assets.sort(key=lambda a: (a.scene_number or 0, a.created_at))
            video_clip_paths: list[Path] = [
                self.storage.resolve_path(a.file_path) for a in scene_video_assets
            ]
            self.log.info(
                "step_assembly_video_mode",
                clip_count=len(video_clip_paths),
            )
        else:
            # Fall back to scene image assets
            scene_assets = await self.asset_repo.get_by_episode_and_type(self.episode_id, "scene")
            if not scene_assets:
                raise ValueError(
                    "No scene assets found (neither scene_video nor scene) "
                    "-- run the scenes step first."
                )

            scene_assets.sort(key=lambda a: (a.scene_number or 0, a.created_at))

            # Build SceneInput list. Look up duration by scene_number, not
            # by positional index — the user may have deleted a scene from
            # the script (DELETE /scenes/{num}) without the corresponding
            # media_asset being removed, which shifts the positional match
            # and zips the wrong duration onto the wrong image.
            scene_inputs: list[SceneInput] = []
            num_to_duration: dict[int, float] = {
                s.scene_number: s.duration_seconds for s in script.scenes
            }
            for asset in scene_assets:
                abs_path = self.storage.resolve_path(asset.file_path)
                duration = num_to_duration.get(asset.scene_number or -1, 5.0)
                scene_inputs.append(SceneInput(image_path=abs_path, duration_seconds=duration))

        # Gather voiceover
        voiceover_assets = await self.asset_repo.get_by_episode_and_type(
            self.episode_id, "voiceover"
        )
        if not voiceover_assets:
            raise ValueError("No voiceover asset found.")
        voiceover_path = self.storage.resolve_path(voiceover_assets[-1].file_path)

        # Gather ASS captions (prefer ASS over SRT for burned-in subtitles)
        caption_assets = await self.asset_repo.get_by_episode_and_type(self.episode_id, "caption")
        captions_path: Path | None = None
        for cap_asset in caption_assets:
            if cap_asset.file_path.endswith(".ass"):
                captions_path = self.storage.resolve_path(cap_asset.file_path)
                break

        # Output path
        episode_path = await self.storage.get_episode_path(self.episode_id)
        output_dir = episode_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "final.mp4"

        await self._broadcast_progress(PipelineStep.ASSEMBLY, 10, "running", "Assembling video...")

        # ── Prepare background music ────────────────────────────────────
        background_music_path: Path | None = None
        music_volume_db = -14.0

        content_format = getattr(episode, "content_format", "shorts") or "shorts"
        chapters = getattr(episode, "chapters", None)
        is_longform_with_chapters = (
            content_format == "longform"
            and chapters
            and isinstance(chapters, list)
            and len(chapters) > 1
        )

        # Check whether the user pre-selected a specific track via the Music tab.
        user_selected_music: Path | None = None
        if episode.metadata_ and episode.metadata_.get("selected_music_path"):
            candidate = self.storage.resolve_path(episode.metadata_["selected_music_path"])
            if candidate.exists():
                user_selected_music = candidate

        vol = float(getattr(series, "music_volume_db", -14.0) or -14.0)
        music_volume_db = -abs(vol) if vol != 0 else -14.0

        if user_selected_music is not None:
            background_music_path = user_selected_music
            ep_vol = (episode.metadata_ or {}).get("music_volume_db")
            if ep_vol is not None:
                music_volume_db = -abs(float(ep_vol))
        elif (
            self.music_service is not None
            and getattr(series, "music_enabled", False)
            and getattr(series, "music_mood", None)
        ):
            if use_video_concat:
                total_duration = sum(a.duration_seconds or 5.0 for a in scene_video_assets)
            else:
                total_duration = sum(si.duration_seconds for si in scene_inputs)

            if is_longform_with_chapters:
                # ── Per-chapter music for longform ──────────────────────
                await self._broadcast_progress(
                    PipelineStep.ASSEMBLY,
                    15,
                    "running",
                    "Generating per-chapter background music...",
                )
                try:
                    background_music_path = await self._prepare_chapter_music(
                        episode=episode,
                        series=series,
                        chapters=chapters or [],
                        scene_inputs=scene_inputs if not use_video_concat else None,
                        video_assets=scene_video_assets if use_video_concat else None,
                        voiceover_path=voiceover_path,
                        music_volume_db=music_volume_db,
                    )
                except Exception as exc:
                    self.log.warning(
                        "chapter_music_failed_fallback_single",
                        error=str(exc)[:200],
                    )
                    # Fall back to single track
                    background_music_path = None

            if background_music_path is None:
                # Single track (shorts or fallback)
                try:
                    bg_path = await self.music_service.get_music_for_episode(
                        mood=series.music_mood or "",
                        target_duration=float(total_duration),
                        episode_id=self.episode_id,
                    )
                    if bg_path and bg_path.exists():
                        background_music_path = bg_path
                except Exception as exc:
                    self.log.warning("music_preparation_failed", error=str(exc))

        # Determine resolution from aspect ratio (longform = 16:9, shorts = 9:16)
        aspect_ratio = getattr(series, "aspect_ratio", "9:16") or "9:16"
        if aspect_ratio == "16:9":
            asm_width, asm_height = 1920, 1080
        elif aspect_ratio == "1:1":
            asm_width, asm_height = 1080, 1080
        else:
            asm_width, asm_height = 1080, 1920

        # Transition duration from series config (longform may use different values)
        transition_dur = getattr(series, "transition_duration", 0.4) or 0.4

        # Transition style and seed for Ken Burns variety / xfade selection.
        # transition_style is passed through to _build_kenburns_command so the
        # series-level setting ("fade", "random", "variety", or any named xfade)
        # is honoured without requiring a new AssemblyConfig field.
        transition_style: str = getattr(series, "transition_style", "fade") or "fade"
        base_seed: int | None = getattr(series, "base_seed", None)

        assembly_config = AssemblyConfig(
            width=asm_width,
            height=asm_height,
            fps=30,
            transition_duration=transition_dur,
        )

        # Auto-detect a watermark/logo: if ``storage/watermark.png`` exists at
        # the storage root it is overlaid on every assembled video at the
        # bottom-right corner at 50 % opacity.  No configuration needed — just
        # drop the file in place.
        try:
            watermark_file = self.storage.resolve_path("watermark.png")
            if watermark_file.exists():
                assembly_config.watermark_path = str(watermark_file)
                self.log.info(
                    "step_assembly.watermark_detected",
                    path=str(watermark_file),
                )
        except Exception:
            # resolve_path raises on path-traversal; any other unexpected
            # error must not abort the pipeline.
            pass

        # ── Build audio mastering config ──────────────────────────────────
        # Start with the resolved music_volume_db from the music-selection
        # block above, then apply any per-episode audio overrides stored in
        # episode.metadata_["audio_settings"].
        audio_config = AudioMixConfig(music_volume_db=music_volume_db)

        ep_audio = (episode.metadata_ or {}).get("audio_settings", {})
        if ep_audio:
            if "music_volume_db" in ep_audio:
                # Always keep music volume negative (dB attenuation).
                audio_config.music_volume_db = -abs(float(ep_audio["music_volume_db"]))
            if "music_reverb" in ep_audio:
                audio_config.music_reverb = bool(ep_audio["music_reverb"])
            if "music_reverb_decay" in ep_audio:
                audio_config.music_reverb_decay = float(ep_audio["music_reverb_decay"])
            if "voice_eq" in ep_audio:
                audio_config.voice_eq = bool(ep_audio["voice_eq"])
            if "voice_compressor" in ep_audio:
                audio_config.voice_compressor = bool(ep_audio["voice_compressor"])
            if "duck_ratio" in ep_audio:
                audio_config.duck_ratio = float(ep_audio["duck_ratio"])
            if "duck_release" in ep_audio:
                audio_config.duck_release = float(ep_audio["duck_release"])
            if "master_limiter" in ep_audio:
                audio_config.master_limiter = bool(ep_audio["master_limiter"])
            if "music_low_pass" in ep_audio:
                audio_config.music_low_pass = int(ep_audio["music_low_pass"])

        self.log.info(
            "step_assembly_audio_config",
            voice_eq=audio_config.voice_eq,
            voice_compressor=audio_config.voice_compressor,
            voice_normalize=audio_config.voice_normalize,
            music_volume_db=audio_config.music_volume_db,
            music_reverb=audio_config.music_reverb,
            master_limiter=audio_config.master_limiter,
        )

        # ── Execute assembly ─────────────────────────────────────────────
        if use_video_concat:
            assembly_result = await self.ffmpeg_service.concat_video_clips(
                video_clips=video_clip_paths,
                voiceover_path=voiceover_path,
                output_path=output_path,
                captions_path=captions_path,
                background_music_path=background_music_path,
                audio_config=audio_config,
                config=assembly_config,
            )
        else:
            assembly_result = await self.ffmpeg_service.assemble_video(
                scenes=scene_inputs,
                voiceover_path=voiceover_path,
                output_path=output_path,
                captions_path=captions_path,
                background_music_path=background_music_path,
                audio_config=audio_config,
                config=assembly_config,
                base_seed=base_seed,
                transition_style=transition_style,
            )

        await self._broadcast_progress(
            PipelineStep.ASSEMBLY, 80, "running", "Saving video asset..."
        )

        # Save video as MediaAsset
        relative_output = f"episodes/{self.episode_id}/output/{output_path.name}"
        await self.asset_repo.create(
            episode_id=self.episode_id,
            asset_type="video",
            file_path=relative_output,
            file_size_bytes=assembly_result.file_size_bytes,
            duration_seconds=assembly_result.duration_seconds,
            generation_job_id=job.id,
        )

        # Update episode base_path
        await self.episode_repo.update(
            self.episode_id,
            base_path=f"episodes/{self.episode_id}",
        )
        await self.db.commit()

        self.log.info(
            "step_assembly_done",
            duration=assembly_result.duration_seconds,
            file_size=assembly_result.file_size_bytes,
            mode="video_concat" if use_video_concat else "image_kenburns",
        )

    async def _prepare_chapter_music(
        self,
        episode: Episode,
        series: Series,
        chapters: list[dict[str, Any]],
        scene_inputs: list[SceneInput] | None,
        video_assets: list[Any] | None,
        voiceover_path: Path,
        music_volume_db: float,
    ) -> Path | None:
        """Generate per-chapter music tracks with different moods, crossfade, and combine.

        Returns the path to a single combined music WAV that can be passed
        to ``assemble_video`` as ``background_music_path``.
        """
        import asyncio as _asyncio
        from uuid import uuid4

        if not self.music_service:
            return None

        episode_dir = await self.storage.get_episode_path(self.episode_id)
        music_dir = episode_dir / "music"
        music_dir.mkdir(parents=True, exist_ok=True)

        # Calculate chapter durations from scene inputs
        chapter_durations: list[float] = []
        for ch in chapters:
            ch_scenes = ch.get("scenes", [])
            if ch_scenes and isinstance(ch_scenes, list) and isinstance(ch_scenes[0], int):
                # scenes is a list of scene indices
                ch_dur = 0.0
                for s_idx in ch_scenes:
                    if scene_inputs and s_idx - 1 < len(scene_inputs):
                        ch_dur += scene_inputs[s_idx - 1].duration_seconds
                    elif video_assets and s_idx - 1 < len(video_assets):
                        ch_dur += video_assets[s_idx - 1].duration_seconds or 10.0
                    else:
                        ch_dur += 10.0
                chapter_durations.append(ch_dur)
            else:
                # Fallback: estimate from target_scene_count
                n_scenes = ch.get("target_scene_count", 8)
                chapter_durations.append(n_scenes * 10.0)

        # Mood rotation for variety
        mood_rotation = ["mysterious", "calm", "dramatic", "tense", "epic", "dark", "inspiring"]
        getattr(series, "music_mood", "mysterious") or "mysterious"

        # Generate music per chapter
        chapter_music_paths: list[Path | None] = []
        for i, (ch, dur) in enumerate(zip(chapters, chapter_durations, strict=False)):
            ch_mood = (
                ch.get("music_mood") or ch.get("mood") or mood_rotation[i % len(mood_rotation)]
            )

            self.log.info(
                "chapter_music_generating",
                chapter=i + 1,
                mood=ch_mood,
                duration=round(dur, 1),
            )

            try:
                music_path = await self.music_service.get_music_for_episode(
                    mood=ch_mood,
                    target_duration=dur + 2.0,  # +2s for crossfade overlap
                    episode_id=uuid4(),  # unique ID per chapter
                )
                if music_path and music_path.exists():
                    # Trim and fade
                    trimmed = music_dir / f"ch{i:02d}_music.wav"
                    fade_start = max(0, dur - 2.0)
                    proc = await _asyncio.create_subprocess_exec(
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(music_path),
                        "-t",
                        str(dur + 2.0),
                        "-af",
                        f"afade=t=in:d=1.5,afade=t=out:st={fade_start}:d=2.0",
                        "-c:a",
                        "pcm_s16le",
                        str(trimmed),
                        stdout=_asyncio.subprocess.PIPE,
                        stderr=_asyncio.subprocess.PIPE,
                    )
                    _, stderr_b = await proc.communicate()
                    if proc.returncode != 0:
                        self.log.warning(
                            "chapter_music_trim_ffmpeg_failed",
                            chapter=i,
                            rc=proc.returncode,
                            error=stderr_b.decode("utf-8", errors="replace")[:200],
                        )
                        chapter_music_paths.append(None)
                    else:
                        chapter_music_paths.append(trimmed if trimmed.exists() else None)
                else:
                    chapter_music_paths.append(None)
            except Exception as exc:
                self.log.warning("chapter_music_gen_failed", chapter=i, error=str(exc)[:100])
                chapter_music_paths.append(None)

        # Concatenate chapter music tracks into one continuous track
        valid = [(i, p) for i, p in enumerate(chapter_music_paths) if p and p.exists()]
        if not valid:
            return None

        if len(valid) == 1:
            return valid[0][1]

        concat_list = music_dir / "_concat.txt"
        lines = [f"file '{str(p).replace(chr(92), '/')}'" for _, p in valid]
        concat_list.write_text("\n".join(lines), encoding="utf-8")

        combined = music_dir / "combined_chapter_music.wav"
        proc = await _asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:a",
            "pcm_s16le",
            str(combined),
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        _, stderr_b = await proc.communicate()
        concat_list.unlink(missing_ok=True)
        if proc.returncode != 0:
            self.log.warning(
                "chapter_music_concat_ffmpeg_failed",
                rc=proc.returncode,
                error=stderr_b.decode("utf-8", errors="replace")[:200],
            )
            return None

        if combined.exists():
            self.log.info(
                "chapter_music_combined",
                chapters=len(valid),
                path=str(combined),
            )
            return combined

        return None

    async def _step_thumbnail(
        self,
        episode: Episode,
        series: Series,
        job: GenerationJob,
    ) -> None:
        """Step 6: Generate thumbnail from the assembled video.

        Three modes are selected via ``series.thumbnail_mode``:

        * ``"simple"`` -- extract a single frame at 0.5 s (legacy behaviour).
        * ``"smart_frame"`` -- sample 10 candidate frames, pick the sharpest
          (highest JPEG file size).  This is the default.
        * ``"text_overlay"`` -- smart frame selection followed by FFmpeg
          drawtext compositing of the episode title.
        """
        self.log.info("step_thumbnail_start")

        # Find the assembled video
        video_assets = await self.asset_repo.get_by_episode_and_type(self.episode_id, "video")
        if not video_assets:
            raise ValueError("No video asset found -- run the assembly step first.")

        video_asset = video_assets[-1]
        video_path = self.storage.resolve_path(video_asset.file_path)

        # Output thumbnail
        episode_path = await self.storage.get_episode_path(self.episode_id)
        output_dir = episode_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = output_dir / "thumbnail.jpg"

        # Resolve mode; default to "smart_frame" when the column is absent or
        # blank so the feature activates without a schema migration on existing
        # deployments.
        thumbnail_mode: str = getattr(series, "thumbnail_mode", None) or "smart_frame"

        await self._broadcast_progress(
            PipelineStep.THUMBNAIL, 20, "running", "Extracting thumbnail..."
        )

        # The thumbnail step is non-critical: the video and captions are
        # already assembled at this point. A flaky drawtext filter or a
        # weird FFmpeg build shouldn't flip the whole episode to
        # ``failed`` — try the requested mode, then fall through to the
        # cheapest possible "grab any frame" path, and only raise if
        # even that fails.
        async def _try_modes() -> None:
            if thumbnail_mode == "simple":
                await self.ffmpeg_service.extract_thumbnail(
                    video_path=video_path,
                    output_path=thumbnail_path,
                    timestamp_seconds=0.5,
                )
                return
            if thumbnail_mode == "text_overlay":
                await self._broadcast_progress(
                    PipelineStep.THUMBNAIL, 30, "running", "Selecting best frame..."
                )
                await self.ffmpeg_service.extract_best_thumbnail(
                    video_path=video_path,
                    output_path=thumbnail_path,
                )
                await self._broadcast_progress(
                    PipelineStep.THUMBNAIL, 60, "running", "Compositing title text..."
                )
                await self.ffmpeg_service.compose_thumbnail(
                    base_image_path=thumbnail_path,
                    output_path=thumbnail_path,
                    title=episode.title or "",
                    subtitle=getattr(episode, "topic", "") or "",
                )
                return
            # smart_frame (default) and any unknown future value
            await self.ffmpeg_service.extract_best_thumbnail(
                video_path=video_path,
                output_path=thumbnail_path,
            )

        try:
            await _try_modes()
        except Exception as thumb_exc:
            self.log.warning(
                "thumbnail_mode_failed_falling_back",
                mode=thumbnail_mode,
                error=str(thumb_exc)[:200],
            )
            try:
                # Cheapest fallback — grab a mid-video frame.
                await self.ffmpeg_service.extract_thumbnail(
                    video_path=video_path,
                    output_path=thumbnail_path,
                    timestamp_seconds=0.5,
                )
            except Exception as final_exc:
                # Even the fallback failed. Don't kill the episode — the
                # video is already usable; just warn and carry on without
                # a thumbnail. The operator can regenerate one from the
                # Episode detail page.
                self.log.error(
                    "thumbnail_generation_skipped",
                    error=str(final_exc)[:200],
                )
                return

        await self._broadcast_progress(
            PipelineStep.THUMBNAIL, 80, "running", "Saving thumbnail asset..."
        )

        # Save thumbnail MediaAsset
        file_size = thumbnail_path.stat().st_size if thumbnail_path.exists() else None
        relative_thumb = f"episodes/{self.episode_id}/output/thumbnail.jpg"
        await self.asset_repo.create(
            episode_id=self.episode_id,
            asset_type="thumbnail",
            file_path=relative_thumb,
            file_size_bytes=file_size,
            generation_job_id=job.id,
        )

        # Update episode metadata with thumbnail path
        current_metadata = episode.metadata_ or {}
        current_metadata["thumbnail_path"] = relative_thumb
        await self.episode_repo.update(
            self.episode_id,
            metadata_=current_metadata,
        )
        await self.db.commit()

        self.log.info("step_thumbnail_done", path=relative_thumb)

    # ── Progress broadcasting ─────────────────────────────────────────────

    async def _broadcast_progress(
        self,
        step: PipelineStep,
        pct: int,
        status: str,
        message: str = "",
        *,
        detail: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Publish progress to Redis pub/sub for WebSocket delivery."""
        progress = ProgressMessage(
            episode_id=str(self.episode_id),
            job_id=str(self._current_job_id) if self._current_job_id else "",
            step=step.value,
            status=status,
            progress_pct=pct,
            message=message,
            error=error,
            detail=detail,
        )

        channel = f"progress:{self.episode_id}"
        try:
            await self.redis.publish(channel, progress.model_dump_json())
        except Exception:
            # Non-fatal -- log and continue.  Progress delivery is best-effort.
            self.log.warning(
                "broadcast_progress_failed",
                channel=channel,
                exc_info=True,
            )

        # Also update the job record progress in the database. Don't commit
        # per call — progress pings happen 3-5× per step, and a full commit
        # each time previously amounted to ~30 synchronous fsyncs per
        # pipeline run. Step-boundary commits (_ensure_job, _mark_step_done)
        # already persist status transitions; in-between progress updates
        # ride on the next step-level commit for durability that's plenty
        # for a progress bar.
        if self._current_job_id:
            try:
                await self.job_repo.update_progress(self._current_job_id, pct)
            except Exception:
                self.log.debug("job_progress_update_failed", exc_info=True)

    # ── Job lifecycle helpers ─────────────────────────────────────────────

    async def _ensure_job(
        self,
        step: PipelineStep,
        existing_job: GenerationJob | None,
    ) -> GenerationJob:
        """Create new job record or reset an existing failed one."""
        now = datetime.now(UTC)

        if existing_job is not None:
            # Reset the failed/queued job to running
            await self.job_repo.update(
                existing_job.id,
                status="running",
                progress_pct=0,
                error_message=None,
                started_at=now,
                completed_at=None,
            )
            await self.db.commit()
            # Refresh
            refreshed = await self.job_repo.get_by_id(existing_job.id)
            if refreshed is None:
                raise RuntimeError(f"Job {existing_job.id} disappeared after update.")
            return refreshed

        # Create a fresh job record
        job = await self.job_repo.create(
            episode_id=self.episode_id,
            step=step.value,
            status="running",
            progress_pct=0,
            started_at=now,
        )
        await self.db.commit()
        return job

    async def _mark_step_done(self, job: GenerationJob) -> None:
        """Mark job as done with 100% progress."""
        now = datetime.now(UTC)
        await self.job_repo.update(
            job.id,
            status="done",
            progress_pct=100,
            completed_at=now,
        )
        await self.db.commit()
        self.log.info("step_done", job_id=str(job.id), step=job.step)

    async def _handle_step_failure(
        self,
        job: GenerationJob,
        step: PipelineStep,
        error: Exception,
        *,
        suggestion: str | None = None,
    ) -> None:
        """Mark job as failed, increment retry count, log error."""
        error_msg = f"{type(error).__name__}: {error}"
        tb = traceback.format_exc()

        if suggestion is None:
            suggestion = self._get_error_suggestion(step, error)

        self.log.error(
            "step_failed",
            step=step.value,
            error=error_msg,
            suggestion=suggestion,
            traceback=tb,
            exc_info=True,
        )

        try:
            await self.job_repo.update(
                job.id,
                status="failed",
                error_message=error_msg[:2000],  # Truncate for DB
                retry_count=job.retry_count + 1,
            )

            # Also mirror the error onto the episode so the detail view
            # has something to render even in the corner case where
            # ``job`` is not what the frontend looked up first (happens
            # when a job row is created-then-failed within a single
            # request cycle).
            await self.episode_repo.update(
                self.episode_id,
                status="failed",
                error_message=f"{step.value}: {error_msg[:1900]}",
            )
            await self.db.commit()
        except Exception:
            self.log.error("handle_step_failure_db_error", exc_info=True)

        # Include the suggestion in the error broadcast detail so the
        # frontend can display it to the user.
        fail_detail = {"suggestion": suggestion}
        await self._broadcast_progress(
            step,
            job.progress_pct,
            "failed",
            f"Step {step.value} failed: {suggestion}",
            error=error_msg,
            detail=fail_detail,
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    # Atomic round-robin counter. ``itertools.count`` is thread- and
    # asyncio-safe: each ``next()`` hands back a fresh integer with no
    # read-modify-write window across ``await``s.
    _llm_rr_counter: Any = __import__("itertools").count()

    async def _auto_select_llm_config(self) -> Any:
        """Select an LLM config using round-robin across all available configs.

        With multiple LLM servers, different episodes get distributed to
        different servers for parallel script generation.
        """
        from drevalis.repositories.llm_config import LLMConfigRepository

        repo = LLMConfigRepository(self.db)
        configs = await repo.get_all(limit=10)
        if not configs:
            return None

        idx = next(PipelineOrchestrator._llm_rr_counter) % len(configs)
        selected = configs[idx]
        self.log.info("auto_selected_llm_config", name=selected.name, index=idx, total=len(configs))
        return selected

    async def _build_llm_pool(self) -> LLMPool:
        """Build an :class:`LLMPool` from all available LLM configs.

        Queries every :class:`LLMConfig` row (up to 10) and wraps each one in
        the appropriate provider via :meth:`LLMService.get_provider`.  Configs
        that fail provider construction (e.g. missing API key) are skipped
        silently so a single misconfigured entry never blocks the pool.

        Returns:
            A ready-to-use :class:`LLMPool`.

        Raises:
            ValueError: When no providers could be built at all.
        """
        from drevalis.repositories.llm_config import LLMConfigRepository
        from drevalis.services.llm import LLMPool

        repo = LLMConfigRepository(self.db)
        configs = await repo.get_all(limit=10)

        providers = []
        for cfg in configs:
            try:
                provider = self.llm_service.get_provider(cfg)
                providers.append((cfg.name, provider))
            except Exception as exc:  # noqa: BLE001
                self.log.warning(
                    "llm_pool_skip_config",
                    name=cfg.name,
                    error=str(exc)[:100],
                )

        if not providers:
            raise ValueError("No LLM providers available — create at least one in Settings.")

        self.log.info("llm_pool_built", provider_count=len(providers))
        return LLMPool(providers)

    async def _auto_select_voice_profile(self) -> Any:
        """Fall back to the first available voice profile in the database."""
        from drevalis.repositories.voice_profile import VoiceProfileRepository

        repo = VoiceProfileRepository(self.db)
        profiles = await repo.get_all(limit=1)
        if profiles:
            self.log.info("auto_selected_voice_profile", name=profiles[0].name)
            return profiles[0]
        return None

    async def _auto_select_prompt_template(self, template_type: str) -> Any:
        """Fall back to the first available prompt template of the given type."""
        from drevalis.repositories.prompt_template import PromptTemplateRepository

        repo = PromptTemplateRepository(self.db)
        templates = await repo.get_by_type(template_type)
        if templates:
            self.log.info(
                "auto_selected_prompt_template",
                name=templates[0].name,
                type=template_type,
            )
            return templates[0]
        return None

    async def _refresh_comfyui_pool(self) -> None:
        """Re-sync the ComfyUI pool with currently active servers from the DB.

        Called at the start of every pipeline ``run()`` so that retries and
        fresh generations always use the current server list instead of the
        stale snapshot from worker startup.
        """
        try:
            pool = self.comfyui_service._pool
            await pool.sync_from_db(self.db)
        except Exception:
            self.log.warning("comfyui_pool_refresh_failed", exc_info=True)

    async def _auto_select_comfyui_server(self) -> Any:
        """Fall back to the first active ComfyUI server in the database."""
        from drevalis.repositories.comfyui import ComfyUIServerRepository

        repo = ComfyUIServerRepository(self.db)
        servers = await repo.get_active_servers()
        if servers:
            self.log.info("auto_selected_comfyui_server", name=servers[0].name)
            return servers[0]
        return None

    async def _auto_select_comfyui_workflow(self) -> Any:
        """Fall back to the first available image workflow in the database.

        Skips video-only and longform-only workflows for shorts episodes.
        """
        from drevalis.repositories.comfyui import ComfyUIWorkflowRepository

        repo = ComfyUIWorkflowRepository(self.db)
        workflows = await repo.get_all(limit=20)
        # Prefer image workflows (output_field_name=images, content_format=shorts/any)
        for wf in workflows:
            mappings = wf.input_mappings or {}
            output_field = mappings.get("output_field_name", "images")
            content_fmt = getattr(wf, "content_format", "any") or "any"
            if output_field == "images" and content_fmt in ("shorts", "any"):
                self.log.info("auto_selected_comfyui_workflow", name=wf.name)
                return wf
        # Fallback to any workflow
        if workflows:
            self.log.info("auto_selected_comfyui_workflow_fallback", name=workflows[0].name)
            return workflows[0]
        return None

    async def _load_episode(self) -> Episode:
        """Load the episode with eager-loaded series and relationships."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from drevalis.models.episode import Episode as EpisodeModel
        from drevalis.models.series import Series as SeriesModel

        stmt = (
            select(EpisodeModel)
            .where(EpisodeModel.id == self.episode_id)
            .options(
                selectinload(EpisodeModel.media_assets),
                selectinload(EpisodeModel.generation_jobs),
                selectinload(EpisodeModel.override_voice_profile),
                selectinload(EpisodeModel.override_llm_config),
                selectinload(EpisodeModel.series).selectinload(SeriesModel.voice_profile),
                selectinload(EpisodeModel.series).selectinload(SeriesModel.llm_config),
                selectinload(EpisodeModel.series).selectinload(SeriesModel.comfyui_server),
                selectinload(EpisodeModel.series).selectinload(SeriesModel.comfyui_workflow),
                selectinload(EpisodeModel.series).selectinload(SeriesModel.video_comfyui_workflow),
                selectinload(EpisodeModel.series).selectinload(SeriesModel.script_prompt_template),
                selectinload(EpisodeModel.series).selectinload(SeriesModel.visual_prompt_template),
            )
        )
        result = await self.db.execute(stmt)
        episode = result.scalar_one_or_none()

        if episode is None:
            raise ValueError(f"Episode {self.episode_id} not found")

        return episode
