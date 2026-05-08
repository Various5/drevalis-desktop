"""Music-video orchestrator (Phase 2a).

Sibling of :class:`PipelineOrchestrator`. When an episode's series has
``content_format == 'music_video'``, the worker dispatches here instead
of the regular pipeline so the music-video-shaped script + audio + beat
data is produced without trying to TTS the lyrics or feed scene-gen a
narration script.

Phase 2a delivers SCRIPT + AUDIO real:

  1. ``plan_song`` (LLM) → ``SongStructure``
  2. Persist plan to ``episode.script`` (music-video JSONB shape)
  3. ``MusicService.get_music_for_episode`` → instrumental WAV at the
     song's mood + duration. Vocals via ACE Step v3 / ElevenLabs Music
     are Phase 3.
  4. ``detect_beats`` → list of beat times + BPM
  5. ``slice_scenes_to_beats`` → list of ``(start, end, prompt)`` slots
  6. Persist beat data + scene slots to ``episode.script.music_video``
  7. Mark episode ``status='review'`` so the user can preview the
     plan + audio before Phase 2b's visual generation lands

Phase 2b (follow-up) will fill in SCENES + CAPTIONS + ASSEMBLY +
THUMBNAIL by reusing the existing ComfyUI / FFmpeg infrastructure.

The orchestrator deliberately does NOT subclass ``PipelineOrchestrator``
— their step lists differ (no VOICE for music videos; no SCRIPT for
music videos in the narration sense), and inheritance would force
both classes to deal with each other's edge cases.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.services.captions import CaptionService
    from drevalis.services.comfyui import ComfyUIService
    from drevalis.services.ffmpeg import FFmpegService
    from drevalis.services.llm import LLMPool
    from drevalis.services.music import MusicService
    from drevalis.services.storage import LocalStorage

from drevalis.repositories.episode import EpisodeRepository
from drevalis.repositories.media_asset import MediaAssetRepository
from drevalis.services.music_video import (
    SongStructure,
    detect_beats,
    plan_song,
    slice_scenes_to_beats,
)


class MusicVideoOrchestrator:
    """Phase 2a music-video pipeline (SCRIPT + AUDIO)."""

    def __init__(
        self,
        episode_id: UUID,
        db_session: AsyncSession,
        redis: Redis,
        llm_pool: LLMPool,
        music_service: MusicService,
        ffmpeg_service: FFmpegService,
        storage: LocalStorage,
        # Phase 2b deps — visuals + captions + composite. None-safe so
        # Phase 2a-only deployments still work; the orchestrator
        # short-circuits at the SCRIPT/AUDIO boundary if any of these
        # are missing and leaves the episode in ``review``.
        comfyui_service: ComfyUIService | None = None,
        caption_service: CaptionService | None = None,
    ) -> None:
        self.episode_id = episode_id
        self.db = db_session
        self.redis = redis
        self.llm_pool = llm_pool
        self.music_service = music_service
        self.ffmpeg_service = ffmpeg_service
        self.storage = storage
        self.comfyui_service = comfyui_service
        self.caption_service = caption_service
        self.log = structlog.get_logger(__name__).bind(
            episode_id=str(episode_id), pipeline="music_video"
        )
        self.episode_repo = EpisodeRepository(db_session)
        self.asset_repo = MediaAssetRepository(db_session)

    # ── Cancellation ────────────────────────────────────────────────────

    async def _check_cancelled(self) -> None:
        """Raise ``CancelledError`` if a cancel flag is set."""
        try:
            flag = await self.redis.get(f"cancel:{self.episode_id}")
        except Exception:
            return
        if flag:
            self.log.info("music_video.cancelled_by_user")
            raise asyncio.CancelledError(f"Episode {self.episode_id} cancelled")

    # ── Progress broadcast ──────────────────────────────────────────────

    async def _broadcast(self, step: str, pct: int, message: str) -> None:
        import json as _json

        try:
            await self.redis.publish(
                f"progress:{self.episode_id}",
                _json.dumps(
                    {
                        "episode_id": str(self.episode_id),
                        "step": step,
                        "progress_pct": pct,
                        "message": message,
                    }
                ),
            )
        except Exception:
            pass

    # ── Step 1: SCRIPT (song plan) ──────────────────────────────────────

    async def _run_script(self, episode: Any, series: Any) -> SongStructure:
        await self._broadcast("script", 5, "Planning the song...")
        target_seconds = (getattr(series, "target_duration_minutes", None) or 3) * 60.0
        topic = (episode.topic or series.title or "untitled").strip()[:300]
        genre_hint = getattr(series, "music_genre", None)
        mood_hint = getattr(series, "music_mood", None) or getattr(series, "visual_style", None)

        plan = await plan_song(
            self.llm_pool,
            topic=topic,
            target_duration_seconds=target_seconds,
            genre_hint=genre_hint,
            mood_hint=mood_hint,
        )
        await self._broadcast(
            "script",
            30,
            f"Song planned: '{plan.title}' ({len(plan.sections)} sections)",
        )
        return plan

    # ── Step 2: AUDIO (instrumental + beats + slots) ────────────────────

    async def _run_audio(self, episode: Any, series: Any, plan: SongStructure) -> dict[str, Any]:
        await self._check_cancelled()
        await self._broadcast("audio", 40, "Rendering backing track...")

        # Resolve where to save the song.
        episode_dir = Path(self.storage.resolve_path(f"episodes/{self.episode_id}/voice"))
        episode_dir.mkdir(parents=True, exist_ok=True)
        song_path = episode_dir / "song.wav"

        # Use the song's mood as the music-mood key. Fall back to the
        # series' configured mood, then to "calm" so MusicService always
        # has a valid mood string.
        mood = plan.mood or getattr(series, "music_mood", None) or "calm"
        target_seconds = plan.total_duration_seconds or 60.0

        try:
            resolved = await self.music_service.get_music_for_episode(
                mood=mood,
                target_duration=target_seconds,
                episode_id=uuid4(),  # MusicService uses this as a cache key
            )
        except Exception as exc:  # noqa: BLE001
            self.log.warning(
                "music_video.audio.music_service_failed",
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
            resolved = None

        if resolved is None:
            raise RuntimeError(
                "Music backing track could not be resolved. Either populate "
                f"the curated music library for mood '{mood}' or register a "
                "ComfyUI server with AceStep generation enabled."
            )

        # Copy / move the resolved track to the episode-scoped path so
        # downstream steps (Phase 2b assembly) find it deterministically.
        try:
            import shutil as _shutil

            _shutil.copy2(resolved, song_path)
        except Exception as exc:  # noqa: BLE001
            self.log.warning(
                "music_video.audio.copy_failed",
                src=str(resolved),
                dst=str(song_path),
                error=str(exc)[:200],
            )
            song_path = Path(resolved)

        await self._broadcast("audio", 70, "Detecting beats...")
        beat_times, bpm = detect_beats(song_path)

        # Build scene slots even when beat detection failed — the
        # slicer falls back to evenly-spaced cuts.
        scenes_per_section = max(2, int(getattr(series, "scenes_per_chapter", 4) or 4))
        scene_slots = slice_scenes_to_beats(
            beats=beat_times,
            sections=plan.sections,
            scenes_per_section=scenes_per_section,
        )

        rel_song_path = f"episodes/{self.episode_id}/voice/song.wav"
        audio_meta: dict[str, Any] = {
            "song_path": rel_song_path,
            "duration_seconds": plan.total_duration_seconds,
            "bpm": round(bpm, 1) if bpm else 0.0,
            "beat_count": len(beat_times),
            "scene_slots": [
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "visual_prompt": prompt,
                }
                for (start, end, prompt) in scene_slots
            ],
        }
        await self._broadcast(
            "audio",
            90,
            f"Backing track ready · {bpm:.0f} BPM · {len(scene_slots)} scenes",
        )
        return audio_meta

    # ── Persistence ─────────────────────────────────────────────────────

    async def _persist_script(self, plan: SongStructure, audio_meta: dict[str, Any]) -> None:
        """Store the music-video-shaped script blob on the episode row."""
        script_blob = {
            "kind": "music_video",
            "music_video": {
                "song": plan.to_dict(),
                "audio": audio_meta,
            },
        }
        await self.episode_repo.update(
            self.episode_id,
            script=script_blob,
            title=plan.title,
        )
        await self.db.commit()

    # ── Step 3: SCENES (one image per scene slot) ───────────────────────

    async def _select_workflow(self) -> Any:
        """Pick a ComfyUI workflow for music-video scenes.

        Preference: ``content_format='music_video'`` → ``longform`` →
        ``shorts`` → ``any``. Output field must be ``images``. Returns
        ``None`` when no workflow is registered, in which case the
        scenes step skips visual generation and the assembly step
        produces an audio-only video.
        """
        from drevalis.repositories.comfyui import ComfyUIWorkflowRepository

        repo = ComfyUIWorkflowRepository(self.db)
        workflows = await repo.get_all(limit=20)
        # Score each workflow: image-output + matching content_format.
        preference = ["music_video", "longform", "shorts", "any"]

        def _score(wf: Any) -> int:
            mappings = wf.input_mappings or {}
            output_field = mappings.get("output_field_name", "images")
            if output_field != "images":
                return -1
            fmt = (getattr(wf, "content_format", "any") or "any").lower()
            return len(preference) - (
                preference.index(fmt) if fmt in preference else len(preference)
            )

        scored = [(wf, _score(wf)) for wf in workflows]
        scored = [s for s in scored if s[1] >= 0]
        if not scored:
            return None
        scored.sort(key=lambda s: s[1], reverse=True)
        chosen = scored[0][0]
        self.log.info(
            "music_video.scenes.workflow_selected",
            name=chosen.name,
            content_format=getattr(chosen, "content_format", "any"),
        )
        return chosen

    async def _run_scenes(
        self, plan: SongStructure, audio_meta: dict[str, Any], series: Any
    ) -> list[Any]:
        """Generate one ComfyUI image per scene slot.

        Returns a list of generated image objects (each carrying
        ``file_path`` + ``scene_number``). Empty when ComfyUI isn't
        available — caller falls back to audio-only assembly.
        """
        if self.comfyui_service is None:
            self.log.info("music_video.scenes.skipped_no_comfyui")
            return []

        scene_slots = audio_meta.get("scene_slots") or []
        if not scene_slots:
            self.log.warning("music_video.scenes.no_slots")
            return []

        await self._broadcast("scenes", 0, f"Generating {len(scene_slots)} scenes...")
        workflow = await self._select_workflow()
        if workflow is None:
            self.log.warning("music_video.scenes.no_workflow_registered")
            return []

        # Build SceneScript objects from the slot list. Each gets a
        # 1-based scene_number for downstream sorting + filename
        # determinism.
        from drevalis.schemas.script import SceneScript

        scenes_to_generate: list[SceneScript] = []
        for i, slot in enumerate(scene_slots, start=1):
            duration = max(0.5, float(slot["end"]) - float(slot["start"]))
            scenes_to_generate.append(
                SceneScript(
                    scene_number=i,
                    narration="(music)",  # required field; not used for music_video
                    visual_prompt=slot["visual_prompt"],
                    duration_seconds=duration,
                )
            )

        async def _scene_progress(message: str, scene_number: int | None) -> None:
            if scene_number is None:
                return
            pct = int((scene_number / max(1, len(scenes_to_generate))) * 80)
            await self._broadcast("scenes", pct, message)

        try:
            generated_images = await self.comfyui_service.generate_scene_images(
                server_id=None,  # let the pool distribute
                workflow_path=workflow.workflow_json_path,
                input_mappings=workflow.input_mappings,
                scenes=scenes_to_generate,
                visual_style=getattr(series, "visual_style", "") or "",
                character_description="",  # music videos don't carry characters
                episode_id=self.episode_id,
                negative_prompt=getattr(series, "negative_prompt", None),
                progress_callback=_scene_progress,
                base_seed=getattr(series, "base_seed", None),
            )
        except Exception as exc:  # noqa: BLE001
            self.log.warning(
                "music_video.scenes.generation_failed",
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
            return []

        # Persist each as a media_asset so the UI can list them and
        # downstream regenerate-scene flows can locate the files.
        for img in generated_images:
            if img.scene_number is None:
                continue
            img_path = self.storage.resolve_path(img.file_path)
            file_size = img_path.stat().st_size if img_path.exists() else None
            await self.asset_repo.create(
                episode_id=self.episode_id,
                asset_type="scene_image",
                file_path=img.file_path,
                file_size_bytes=file_size,
                scene_number=img.scene_number,
            )
        await self.db.commit()
        await self._broadcast("scenes", 90, f"Generated {len(generated_images)} scene images.")
        return list(generated_images)

    # ── Step 4: CAPTIONS (lyrics burned per section) ────────────────────

    async def _run_captions(self, plan: SongStructure, audio_meta: dict[str, Any]) -> Path | None:
        """Build ASS captions from section lyrics + section start times.

        Distributes each section's words evenly across that section's
        time range to produce ``WordTimestamp`` entries the existing
        :class:`CaptionService` knows how to format. Returns the ASS
        file path or ``None`` when captions aren't available.
        """
        if self.caption_service is None:
            self.log.info("music_video.captions.skipped_no_service")
            return None

        from drevalis.services.captions import CaptionStyle
        from drevalis.services.tts import WordTimestamp

        await self._broadcast("captions", 0, "Building lyric captions...")

        # Walk sections; for each, distribute words across its slot.
        word_timestamps: list[WordTimestamp] = []
        cursor = 0.0
        for section in plan.sections:
            section_end = cursor + section.duration_seconds
            lyric = (section.lyrics or "").strip()
            # Skip instrumental/empty sections — no words to burn.
            if not lyric or lyric.lower().startswith("(instrumental)"):
                cursor = section_end
                continue
            words = [w for w in re.split(r"\s+", lyric) if w]
            if not words:
                cursor = section_end
                continue
            per_word = section.duration_seconds / len(words)
            for i, word in enumerate(words):
                word_timestamps.append(
                    WordTimestamp(
                        word=word,
                        start_seconds=cursor + i * per_word,
                        end_seconds=cursor + (i + 1) * per_word,
                    )
                )
            cursor = section_end

        if not word_timestamps:
            self.log.info("music_video.captions.all_instrumental_no_burn")
            return None

        # Resolve a video resolution that matches the assembly step.
        width, height = 1080, 1920  # vertical default; assembly uses same

        caption_dir = Path(self.storage.resolve_path(f"episodes/{self.episode_id}/captions"))
        style = CaptionStyle(
            preset="youtube_highlight",
            font_size=64,
            position="bottom",
            margin_v=140,
            words_per_line=4,
            uppercase=False,
            play_res_x=width,
            play_res_y=height,
        )
        try:
            result = await self.caption_service.generate_from_timestamps(
                word_timestamps=word_timestamps,
                output_dir=caption_dir,
                style=style,
            )
        except Exception as exc:  # noqa: BLE001
            self.log.warning(
                "music_video.captions.failed",
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
            return None
        await self._broadcast(
            "captions",
            100,
            f"Lyrics rendered ({len(word_timestamps)} words).",
        )
        return Path(result.ass_path)

    # ── Step 5: ASSEMBLY (composite audio + scenes + captions) ──────────

    async def _run_assembly(
        self,
        plan: SongStructure,
        audio_meta: dict[str, Any],
        generated_images: list[Any],
        captions_path: Path | None,
    ) -> Path:
        """Composite the song + scenes + captions into a final MP4."""
        from drevalis.services.ffmpeg import (
            AssemblyConfig,
            AudioMixConfig,
            SceneInput,
        )

        await self._broadcast("assembly", 0, "Composing music video...")

        song_path = Path(self.storage.resolve_path(audio_meta["song_path"]))
        if not song_path.exists():
            raise RuntimeError(f"Song WAV missing at {song_path}; AUDIO step never wrote it.")

        # Map each scene_number → (image_path, duration). Reads
        # durations from the persisted slot list.
        slots = audio_meta.get("scene_slots") or []
        slot_durations = [max(0.5, float(s["end"]) - float(s["start"])) for s in slots]

        # Sort generated images by scene_number so SceneInput list
        # follows the song timeline.
        def _scene_no(img: Any) -> int:
            return int(getattr(img, "scene_number", 0) or 0)

        ordered = sorted(generated_images, key=_scene_no)
        scenes: list[SceneInput] = []
        for img in ordered:
            scene_no = _scene_no(img)
            if scene_no <= 0 or scene_no > len(slot_durations):
                continue
            img_path = Path(self.storage.resolve_path(img.file_path))
            scenes.append(
                SceneInput(
                    image_path=img_path,
                    duration_seconds=slot_durations[scene_no - 1],
                )
            )

        # Audio config: the song is already mastered, so disable voice
        # processing (which would over-compress the music) and skip
        # sidechain ducking (no narration on top).
        audio_cfg = AudioMixConfig(
            voice_normalize=False,
            voice_compressor=False,
            voice_eq=False,
        )
        config = AssemblyConfig(
            width=1080,
            height=1920,
            fps=30,
            ken_burns_enabled=True,
        )

        output_dir = Path(self.storage.resolve_path(f"episodes/{self.episode_id}/output"))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "video.mp4"

        if not scenes:
            # Audio-only fallback: synthesise a single solid-colour
            # frame at the full duration. Better to ship something
            # playable than to fail the assembly because ComfyUI was
            # offline.
            self.log.warning("music_video.assembly.no_scenes_audio_only")
            scenes = [
                SceneInput(
                    image_path=await self._generate_solid_frame(
                        f"episodes/{self.episode_id}/scenes/placeholder.png"
                    ),
                    duration_seconds=plan.total_duration_seconds or 30.0,
                )
            ]

        async def _on_progress(pct: float) -> None:
            await self._broadcast("assembly", min(95, int(pct)), f"Encoding... {int(pct)}%")

        try:
            await self.ffmpeg_service.assemble_video(
                scenes=scenes,
                voiceover_path=song_path,
                output_path=output_path,
                captions_path=captions_path,
                audio_config=audio_cfg,
                config=config,
                on_progress=_on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            self.log.error(
                "music_video.assembly.failed",
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
            )
            raise

        # Persist the final video as a media_asset so the UI player
        # can find it.
        rel_video = f"episodes/{self.episode_id}/output/video.mp4"
        try:
            file_size = output_path.stat().st_size
        except OSError:
            file_size = None
        await self.asset_repo.create(
            episode_id=self.episode_id,
            asset_type="video",
            file_path=rel_video,
            file_size_bytes=file_size,
        )
        await self.db.commit()
        await self._broadcast("assembly", 100, "Music video assembled.")
        return output_path

    async def _generate_solid_frame(self, rel_path: str) -> Path:
        """Produce a 1080x1920 solid-colour frame as a fallback scene.

        Used only when ComfyUI is unavailable so the assembly step
        still has something to feed FFmpeg.
        """
        out = Path(self.storage.resolve_path(rel_path))
        out.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x0f0f1a:s=1080x1920:d=1",
            "-frames:v",
            "1",
            str(out),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return out

    # ── Step 6: THUMBNAIL (use first scene image) ───────────────────────

    async def _run_thumbnail(self, generated_images: list[Any]) -> str | None:
        """Pick the first generated scene image as the thumbnail.

        Music-video thumbnails benefit from being a real frame from
        the video rather than a separate render — the user can
        replace it later via the existing thumbnail-edit endpoint.
        """
        if not generated_images:
            return None
        first = sorted(
            generated_images,
            key=lambda img: int(getattr(img, "scene_number", 0) or 0),
        )[0]
        rel = getattr(first, "file_path", None)
        if not rel:
            return None
        await self.asset_repo.create(
            episode_id=self.episode_id,
            asset_type="thumbnail",
            file_path=rel,
        )
        await self.db.commit()
        return str(rel)

    # ── Run ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Execute the music-video pipeline (Phase 2a: SCRIPT + AUDIO)."""
        episode = await self.episode_repo.get_by_id(self.episode_id)
        if episode is None:
            raise RuntimeError(f"Episode {self.episode_id} not found")

        # Eager-loaded relationship.
        series = episode.series
        if series is None:
            raise RuntimeError(
                f"Episode {self.episode_id} has no series — orchestrator "
                "needs the series for genre / mood / target_duration."
            )

        try:
            await self._check_cancelled()
            await self.episode_repo.update_status(self.episode_id, "generating")
            await self.db.commit()

            plan = await self._run_script(episode, series)
            await self._check_cancelled()
            audio_meta = await self._run_audio(episode, series, plan)
            await self._check_cancelled()

            await self._persist_script(plan, audio_meta)
            await self._check_cancelled()

            # ── Phase 2b: visuals + composite ───────────────────────
            # Each step is best-effort: a missing ComfyUI / Captions /
            # FFmpeg leg falls back so the user always gets *something*
            # rather than a 'failed' status. The exception is the
            # final assembly — that's the deliverable, so it raises.
            generated_images = await self._run_scenes(plan, audio_meta, series)
            await self._check_cancelled()
            captions_path = await self._run_captions(plan, audio_meta)
            await self._check_cancelled()
            output_path = await self._run_assembly(
                plan, audio_meta, generated_images, captions_path
            )
            await self._run_thumbnail(generated_images)

            # Episode is fully rendered — flip to ``review`` (matches
            # the existing PipelineOrchestrator's terminal state for
            # successful generations).
            await self.episode_repo.update_status(self.episode_id, "review")
            await self.db.commit()
            await self._broadcast(
                "done",
                100,
                f"Music video '{plan.title}' rendered ({output_path.name}).",
            )
            self.log.info(
                "music_video.run_done",
                title=plan.title,
                output=str(output_path),
            )
        except asyncio.CancelledError:
            await self.episode_repo.update_status(self.episode_id, "failed")
            await self.db.commit()
            try:
                await self.redis.delete(f"cancel:{self.episode_id}")
            except Exception:
                pass
            raise
        except Exception as exc:  # noqa: BLE001
            self.log.error(
                "music_video.run_failed",
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
                exc_info=True,
            )
            await self.episode_repo.update(
                self.episode_id,
                status="failed",
                error_message=str(exc)[:1000],
            )
            await self.db.commit()
            raise


__all__ = ["MusicVideoOrchestrator"]
