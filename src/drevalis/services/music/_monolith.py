"""Background music selection and generation for episodes.

Supports three sources for background music, tried in this priority order:

1. **ComfyUI / AceStep 1.5** (preferred) -- submits an AceStep 1.5 workflow to
   ComfyUI and downloads the resulting MP3.  Produces the highest-quality,
   mood-matched instrumental tracks.  Requires a running ComfyUI instance with
   the AceStep 1.5 model weights installed.

2. **Curated library** -- pre-existing audio files organised by mood under
   ``storage/music/library/{mood}/``.  A random track is selected, looped/trimmed
   to the target duration, and faded out.

3. **AI generation** (optional) -- if Meta's ``audiocraft`` / MusicGen package is
   installed, a short instrumental track is generated from a mood-derived text
   prompt.

All sources are optional.  When none is available the service returns ``None``
and the pipeline proceeds without background music.
"""

from __future__ import annotations

import asyncio
import copy
import random
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# AceStep 1.5 workflow template
# ---------------------------------------------------------------------------

# Node IDs that receive runtime parameters:
#   "94" -- TextEncodeAceStepAudio1.5  (tags, duration, seed)
#   "98" -- EmptyAceStep1.5LatentAudio (seconds)
#   "3"  -- KSampler                   (seed)
#   "107"-- SaveAudioMP3               (output node)
_ACESTEP_WORKFLOW_TEMPLATE: dict[str, Any] = {
    "3": {
        "inputs": {
            "seed": 0,
            "steps": 8,
            "cfg": 1,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1,
            "model": ["78", 0],
            "positive": ["94", 0],
            "negative": ["47", 0],
            "latent_image": ["98", 0],
        },
        "class_type": "KSampler",
    },
    "18": {
        "inputs": {"samples": ["3", 0], "vae": ["106", 0]},
        "class_type": "VAEDecodeAudio",
    },
    "47": {
        "inputs": {"conditioning": ["94", 0]},
        "class_type": "ConditioningZeroOut",
    },
    "78": {
        "inputs": {"shift": 3, "model": ["104", 0]},
        "class_type": "ModelSamplingAuraFlow",
    },
    "94": {
        "inputs": {
            "tags": "",
            "lyrics": "",  # empty = instrumental
            "seed": 0,
            "bpm": 120,
            "duration": 30,
            "timesignature": "4",
            "language": "en",
            "keyscale": "C major",
            "generate_audio_codes": True,
            "cfg_scale": 2,
            "temperature": 0.85,
            "top_p": 0.9,
            "top_k": 0,
            "min_p": 0,
            "clip": ["105", 0],
        },
        "class_type": "TextEncodeAceStepAudio1.5",
    },
    "98": {
        "inputs": {"seconds": 30, "batch_size": 1},
        "class_type": "EmptyAceStep1.5LatentAudio",
    },
    "104": {
        "inputs": {
            "unet_name": "acestep_v1.5_turbo.safetensors",
            "weight_dtype": "default",
        },
        "class_type": "UNETLoader",
    },
    "105": {
        "inputs": {
            "clip_name1": "qwen_0.6b_ace15.safetensors",
            "clip_name2": "qwen_1.7b_ace15.safetensors",
            "type": "ace",
            "device": "default",
        },
        "class_type": "DualCLIPLoader",
    },
    "106": {
        "inputs": {"vae_name": "ace_1.5_vae.safetensors"},
        "class_type": "VAELoader",
    },
    "107": {
        "inputs": {
            "filename_prefix": "audio/music",
            "quality": "V0",
            "audioUI": "",
            "audio": ["18", 0],
        },
        "class_type": "SaveAudioMP3",
    },
}

# AceStep hard-caps generation at 120 seconds per request.
_ACESTEP_MAX_DURATION: float = 120.0

# ---------------------------------------------------------------------------
# Mood-to-music-params mappings
# ---------------------------------------------------------------------------

# BPM, key, and time signature for each mood — injected into the AceStep
# TextEncodeAceStepAudio1.5 node at workflow-build time.  Providing accurate
# musical parameters improves generation consistency versus leaving the model
# to infer them from tags alone.
_MOOD_MUSIC_PARAMS: dict[str, dict[str, str | int]] = {
    "epic": {"bpm": 140, "key": "D minor", "timesig": "4"},
    "calm": {"bpm": 72, "key": "C major", "timesig": "4"},
    "dark": {"bpm": 90, "key": "E minor", "timesig": "4"},
    "happy": {"bpm": 128, "key": "G major", "timesig": "4"},
    "sad": {"bpm": 68, "key": "A minor", "timesig": "3"},
    "mysterious": {"bpm": 100, "key": "F# minor", "timesig": "4"},
    "action": {"bpm": 150, "key": "B minor", "timesig": "4"},
    "romantic": {"bpm": 90, "key": "Ab major", "timesig": "4"},
    "tense": {"bpm": 110, "key": "C minor", "timesig": "4"},
    "horror": {"bpm": 80, "key": "Eb minor", "timesig": "4"},
    "comedy": {"bpm": 135, "key": "F major", "timesig": "4"},
    "inspiring": {"bpm": 120, "key": "Bb major", "timesig": "4"},
    "chill": {"bpm": 85, "key": "F major", "timesig": "4"},
}
"""Per-mood BPM, key, and time-signature defaults for AceStep 1.5 generation."""

# ---------------------------------------------------------------------------
# Mood-to-tags mappings
# ---------------------------------------------------------------------------

# Used by the AceStep / ComfyUI path.
_MOOD_TAGS: dict[str, str] = {
    "epic": (
        "Epic cinematic orchestral: dramatic strings, powerful brass, "
        "thundering percussion, heroic theme"
    ),
    "calm": ("Ambient calm: soft piano, gentle pads, atmospheric textures, peaceful meditation"),
    "dark": (
        "Dark atmospheric: deep bass drones, eerie synths, tension-building percussion, suspenseful"
    ),
    "happy": (
        "Upbeat happy: bright acoustic guitar, cheerful melody, light percussion, positive energy"
    ),
    "sad": ("Melancholic emotional: slow piano, gentle strings, minor key, reflective mood"),
    "mysterious": (
        "Mystery suspense: ethereal pads, subtle percussion, dissonant harmonics, investigative"
    ),
    "action": ("High-energy action: driving drums, aggressive synths, fast tempo, intense bass"),
    "romantic": ("Romantic ballad: warm piano, soft strings, gentle melody, intimate atmosphere"),
    "horror": (
        "Horror dark ambient: deep drones, unsettling textures, "
        "sparse percussion, creepy atmosphere"
    ),
    "comedy": ("Playful comedy: bouncy bass, quirky synths, light pizzicato, humorous staccato"),
    "inspiring": (
        "Inspirational uplifting: soaring strings, building drums, hopeful piano, triumphant brass"
    ),
    "chill": ("Lo-fi chill: mellow beats, warm keys, vinyl crackle, relaxed jazzy chords"),
    # Legacy moods carried over from the MusicGen prompt table.
    "upbeat": ("Upbeat energetic: bright pop melody, driving beat, positive energy, no vocals"),
    "dramatic": ("Dramatic cinematic orchestral: epic strings, powerful brass, no vocals"),
    "energetic": ("High-energy electronic: driving synth bass, propulsive beat, no vocals"),
    "playful": ("Playful fun: light bouncy melody, happy rhythm, no vocals"),
    "tense": ("Tense thriller: dark synths, building suspense, ominous underscore, no vocals"),
    "inspirational": ("Inspirational uplifting: orchestral swells, hopeful piano, no vocals"),
}


class MusicService:
    """Select or generate background music for an episode.

    Priority order:
    1. ComfyUI / AceStep 1.5 (best quality, requires running ComfyUI)
    2. Curated library (instant, pre-existing files)
    3. AudioCraft / MusicGen (optional dependency)
    """

    def __init__(
        self,
        storage_base_path: Path,
        ffmpeg_path: str = "ffmpeg",
        comfyui_base_url: str | None = None,
        comfyui_api_key: str | None = None,
    ) -> None:
        self.storage_base_path = storage_base_path
        self.ffmpeg_path = ffmpeg_path
        self.library_path = storage_base_path / "music" / "library"
        # ComfyUI connection details for AceStep generation.
        # Both are optional; if either is absent the ComfyUI path is skipped.
        self.comfyui_base_url = comfyui_base_url
        self.comfyui_api_key = comfyui_api_key

    # ── Public API ---------------------------------------------------------

    async def get_music_for_episode(
        self,
        mood: str,
        target_duration: float,
        episode_id: UUID,
    ) -> Path | None:
        """Get a background music track for an episode.

        Tries ComfyUI AceStep generation first, then the curated library,
        then AudioCraft.  Returns the path to the prepared music file, or
        ``None`` if no music is available.

        Args:
            mood: Mood keyword (e.g. ``"epic"``, ``"calm"``).
            target_duration: Desired track length in seconds.
            episode_id: UUID of the episode (used to derive output paths).

        Returns:
            Absolute path to an audio file, or ``None``.
        """
        log.info(
            "music.get_music_start",
            mood=mood,
            target_duration=target_duration,
            episode_id=str(episode_id),
        )

        # 0. User-uploaded custom track — e.g. ``custom:mytrack.mp3``.
        # Bypass all discovery / generation when the creator has picked
        # their own bed; loop/trim to target duration like the library path.
        if mood and mood.startswith("custom:"):
            filename = mood.split(":", 1)[1].strip()
            if filename:
                source = self.storage_base_path / "music" / "custom" / filename
                if source.exists():
                    output_dir = self.storage_base_path / "episodes" / str(episode_id) / "audio"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output = output_dir / "background_music.wav"
                    await self._loop_trim(source, output, target_duration)
                    log.info("music.source", source="custom_upload", path=str(output))
                    return output
                log.warning(
                    "music.custom.not_found",
                    filename=filename,
                    path=str(source),
                )
                return None  # don't silently fall through to a random library track

        # 1. Try ComfyUI / AceStep 1.5 (highest quality)
        if self.comfyui_base_url:
            track = await self._generate_via_comfyui(mood, target_duration, episode_id)
            if track:
                log.info("music.source", source="comfyui_acestep", path=str(track))
                return track

        # 2. Try curated library
        track = await self._select_from_library(mood, target_duration, episode_id)
        if track:
            log.info("music.source", source="library", path=str(track))
            return track

        # 3. Try AudioCraft / MusicGen
        track = await self._generate_music(mood, target_duration, episode_id)
        if track:
            log.info("music.source", source="generated", path=str(track))
            return track

        log.info("music.no_music_available", mood=mood)
        return None

    # ── ComfyUI / AceStep 1.5 generation ----------------------------------

    async def _generate_via_comfyui(
        self,
        mood: str,
        target_duration: float,
        episode_id: UUID,
    ) -> Path | None:
        """Generate music via the AceStep 1.5 workflow in ComfyUI.

        Builds a workflow from the template, injects the mood tags, duration,
        and a random seed, submits it to ComfyUI, polls for completion, and
        downloads the resulting MP3.

        Args:
            mood: Mood keyword used to look up descriptive tags.
            target_duration: Desired track length in seconds (capped at 120).
            episode_id: UUID of the episode (used to derive output paths).

        Returns:
            Absolute path to the downloaded MP3, or ``None`` on any failure.
        """
        # Import lazily so this module remains importable without comfyui.
        try:
            from drevalis.services.comfyui import ComfyUIClient
        except ImportError:
            log.debug("music.comfyui_import_failed")
            return None

        assert self.comfyui_base_url is not None  # guarded by caller

        tags = _MOOD_TAGS.get(mood.lower(), f"{mood} instrumental background music")
        # AceStep caps at 120 s; requesting more produces silence or errors.
        duration_seconds = min(target_duration, _ACESTEP_MAX_DURATION)
        seed = random.randint(0, 2**31)

        workflow = self._build_acestep_workflow(tags, duration_seconds, seed, mood=mood)

        output_dir = self.storage_base_path / "music" / "generated" / mood.lower()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{episode_id}_{seed}.mp3"

        log.info(
            "music.comfyui_acestep.start",
            mood=mood,
            duration=duration_seconds,
            seed=seed,
            url=self.comfyui_base_url,
        )

        client = ComfyUIClient(
            base_url=self.comfyui_base_url,
            api_key=self.comfyui_api_key,
        )
        try:
            from drevalis.services.tts import build_comfyui_auth_extra_data

            extra_data: dict[str, str] = dict(build_comfyui_auth_extra_data(self.comfyui_api_key))

            try:
                prompt_id = await client.queue_prompt(workflow, extra_data=extra_data or None)
            except Exception as exc:  # noqa: BLE001
                # The most common AceStep failure is a missing model
                # file — ComfyUI rejects the prompt at validation
                # time with ``Value not in list: clip_name2: 'X'
                # not in [...]`` etc. Surface it with the env-var
                # override hint so the operator can fix without
                # editing source.
                err_text = str(exc)
                if (
                    "Value not in list" in err_text
                    or "prompt_outputs_failed_validation" in err_text
                ):
                    log.error(
                        "music.comfyui_acestep.model_missing",
                        error=err_text[:600],
                        hint=(
                            "ComfyUI doesn't have one of the AceStep model "
                            "files this workflow expects. Either install "
                            "the missing files (see the AceStep README) or "
                            "override the names via env vars: "
                            "ACESTEP_CLIP_NAME_1, ACESTEP_CLIP_NAME_2, "
                            "ACESTEP_UNET_NAME, ACESTEP_VAE_NAME — set "
                            "each to a filename ComfyUI actually has."
                        ),
                    )
                    return None
                log.error(
                    "music.comfyui_acestep.queue_failed",
                    error=err_text[:400],
                )
                return None

            # Poll with exponential backoff.  AceStep can take several minutes
            # on slower hardware; use a 10-minute ceiling to match the pipeline.
            delay = 2.0
            total_waited = 0.0
            history: dict[str, Any] | None = None
            while total_waited < 600.0:
                await asyncio.sleep(delay)
                total_waited += delay
                history = await client.get_history(prompt_id)
                if history is not None:
                    break
                delay = min(delay * 1.5, 30.0)

            if history is None:
                log.error(
                    "music.comfyui_acestep.timeout",
                    prompt_id=prompt_id,
                    waited=total_waited,
                )
                return None

            # Check for workflow-level errors reported by ComfyUI.
            exec_status = history.get("status", {})
            if exec_status.get("status_str") == "error":
                messages = exec_status.get("messages", [])
                error_detail = "unknown error"
                for msg_type, msg_data in messages:
                    if msg_type == "execution_error" and isinstance(msg_data, dict):
                        error_detail = (
                            f"node '{msg_data.get('node_type', '?')}': "
                            f"{msg_data.get('exception_message', 'unknown error')}"
                        )
                        break
                log.error(
                    "music.comfyui_acestep.workflow_error",
                    detail=error_detail,
                    prompt_id=prompt_id,
                )
                return None

            # Locate the audio file in the ComfyUI output tree.
            audio_info = self._extract_audio_output(history.get("outputs", {}))
            if audio_info is None:
                log.error(
                    "music.comfyui_acestep.no_output",
                    outputs=history.get("outputs", {}),
                    prompt_id=prompt_id,
                )
                return None

            filename = audio_info.get("filename", "")
            subfolder = audio_info.get("subfolder", "")
            folder_type = audio_info.get("type", "output")

            audio_bytes = await client.download_image(filename, subfolder, folder_type)
            output_path.write_bytes(audio_bytes)

            log.info(
                "music.comfyui_acestep.done",
                path=str(output_path),
                size_bytes=len(audio_bytes),
            )
            return output_path

        except Exception as exc:
            log.warning(
                "music.comfyui_acestep.failed",
                error=str(exc),
                exc_info=True,
            )
            return None
        finally:
            await client.close()

    @staticmethod
    def _build_acestep_workflow(
        tags: str,
        duration_seconds: float,
        seed: int,
        mood: str = "",
    ) -> dict[str, Any]:
        """Return a deep-copied AceStep workflow with parameters injected.

        Args:
            tags: Descriptive music tags for the ``TextEncodeAceStepAudio1.5``
                node.
            duration_seconds: Track length in seconds (floored to int for the
                node inputs that expect an integer).
            seed: Random seed for the KSampler and text encoder.
            mood: Optional mood keyword used to look up BPM, key, and time
                signature from ``_MOOD_MUSIC_PARAMS``.  Falls back to
                ``bpm=120``, ``key="C major"``, ``timesig="4"`` when the
                mood is unknown or omitted.

        Returns:
            A workflow dict ready to pass to ``ComfyUIClient.queue_prompt()``.
        """
        workflow = copy.deepcopy(_ACESTEP_WORKFLOW_TEMPLATE)
        duration_int = int(duration_seconds)

        # AceStep DualCLIPLoader picks two qwen-ace15 clip files. The
        # template hard-coded ``qwen_1.7b_ace15.safetensors`` for the
        # second slot, which 400'd on installs that only have the
        # 0.6b + 4b pair (the more common AceStep distribution since
        # late 2025). Both filenames are now overridable via env so
        # operators with different model layouts don't have to fork
        # this code:
        #
        #   ACESTEP_CLIP_NAME_1   default ``qwen_0.6b_ace15.safetensors``
        #   ACESTEP_CLIP_NAME_2   default ``qwen_4b_ace15.safetensors``
        #   ACESTEP_UNET_NAME     default ``acestep_v1.5_turbo.safetensors``
        #   ACESTEP_VAE_NAME      default ``ace_1.5_vae.safetensors``
        import os as _os

        clip_1 = _os.environ.get("ACESTEP_CLIP_NAME_1", "qwen_0.6b_ace15.safetensors")
        clip_2 = _os.environ.get("ACESTEP_CLIP_NAME_2", "qwen_4b_ace15.safetensors")
        unet_name = _os.environ.get("ACESTEP_UNET_NAME", "acestep_v1.5_turbo.safetensors")
        vae_name = _os.environ.get("ACESTEP_VAE_NAME", "ace_1.5_vae.safetensors")
        workflow["105"]["inputs"]["clip_name1"] = clip_1
        workflow["105"]["inputs"]["clip_name2"] = clip_2
        workflow["104"]["inputs"]["unet_name"] = unet_name
        workflow["106"]["inputs"]["vae_name"] = vae_name

        # TextEncodeAceStepAudio1.5 -- mood tags, duration, seed
        workflow["94"]["inputs"]["tags"] = tags
        workflow["94"]["inputs"]["lyrics"] = ""  # always instrumental
        workflow["94"]["inputs"]["duration"] = duration_int
        workflow["94"]["inputs"]["seed"] = seed

        # Inject mood-aware BPM / key / time signature so AceStep produces a
        # more tonally coherent result than the template defaults.
        params = _MOOD_MUSIC_PARAMS.get(
            mood.lower(),
            {"bpm": 120, "key": "C major", "timesig": "4"},
        )
        workflow["94"]["inputs"]["bpm"] = params["bpm"]
        workflow["94"]["inputs"]["keyscale"] = params["key"]
        workflow["94"]["inputs"]["timesignature"] = params["timesig"]

        # EmptyAceStep1.5LatentAudio -- must match the encoder duration
        workflow["98"]["inputs"]["seconds"] = duration_int

        # KSampler -- independent seed for diffusion sampling
        workflow["3"]["inputs"]["seed"] = seed

        return workflow

    @staticmethod
    def _extract_audio_output(outputs: dict[str, Any]) -> dict[str, Any] | None:
        """Find the first audio file entry in a ComfyUI history outputs dict.

        ComfyUI nodes report outputs under varying keys (``audio``,
        ``audios``, ``files``, ``gifs``).  This helper checks all known
        keys and returns the first dict that has a ``filename`` ending in
        a recognised audio extension.

        Args:
            outputs: The ``outputs`` dict from ``ComfyUIClient.get_history()``.

        Returns:
            A dict with at minimum a ``"filename"`` key, or ``None``.
        """
        audio_extensions = {".mp3", ".wav", ".ogg", ".flac"}
        candidate: dict[str, Any] | None = None

        for _node_id, node_output in outputs.items():
            for key in ("audio", "audios", "files", "gifs", "images", "videos"):
                items = node_output.get(key, [])
                if not isinstance(items, list) or not items:
                    continue
                for item in items:
                    if not isinstance(item, dict) or "filename" not in item:
                        continue
                    fname = item["filename"].lower()
                    if any(fname.endswith(ext) for ext in audio_extensions):
                        return item
                    # Keep as fallback if no audio-extension match found yet.
                    if candidate is None:
                        candidate = item

        return candidate

    # ── Curated library ----------------------------------------------------

    async def _select_from_library(
        self,
        mood: str,
        duration: float,
        episode_id: UUID,
    ) -> Path | None:
        """Find a matching track in the curated library and loop/trim to *duration*."""
        mood_dir = self.library_path / mood
        if not mood_dir.exists():
            log.debug("music.library.mood_dir_missing", mood=mood, path=str(mood_dir))
            return None

        # Collect audio files (common formats)
        tracks: list[Path] = []
        for ext in ("*.mp3", "*.wav", "*.ogg", "*.flac"):
            tracks.extend(mood_dir.glob(ext))

        if not tracks:
            log.debug("music.library.no_tracks", mood=mood)
            return None

        source = random.choice(tracks)
        log.debug("music.library.selected", track=str(source))

        # Prepare output path
        output_dir = self.storage_base_path / "episodes" / str(episode_id) / "audio"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "background_music.wav"

        # Loop/trim to target duration using FFmpeg
        await self._loop_trim(source, output, duration)
        return output

    # ── AI generation (optional) -------------------------------------------

    async def _generate_music(
        self,
        mood: str,
        duration: float,
        episode_id: UUID,
    ) -> Path | None:
        """Generate music using AudioCraft / MusicGen if available.

        This is a CPU/GPU-bound operation, so it runs inside
        ``asyncio.to_thread``.
        """
        try:
            return await asyncio.to_thread(self._generate_music_sync, mood, duration, episode_id)
        except Exception as exc:
            log.warning("music.generation_failed", error=str(exc))
            return None

    def _generate_music_sync(
        self,
        mood: str,
        duration: float,
        episode_id: UUID,
    ) -> Path | None:
        """Synchronous MusicGen generation (runs in a thread)."""
        try:
            from audiocraft.data.audio import audio_write
            from audiocraft.models import MusicGen
        except ImportError:
            log.debug("music.audiocraft_not_installed")
            return None

        log.info(
            "music.generating",
            mood=mood,
            duration=min(duration, 30),
        )

        model = MusicGen.get_pretrained("facebook/musicgen-small")
        model.set_generation_params(duration=min(duration, 30))

        prompt = self._mood_to_prompt(mood)
        wav = model.generate([prompt])

        output_dir = self.storage_base_path / "episodes" / str(episode_id) / "audio"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_stem = output_dir / "background_music"

        audio_write(
            str(output_stem),
            wav[0].cpu(),
            model.sample_rate,
            strategy="loudness",
        )

        # audio_write appends the format extension
        output_path = Path(str(output_stem) + ".wav")
        if not output_path.exists():
            log.warning("music.generated_file_missing", path=str(output_path))
            return None

        return output_path

    # ── Mood-to-prompt mapping (MusicGen legacy) ---------------------------

    @staticmethod
    def _mood_to_prompt(mood: str) -> str:
        """Convert a mood keyword into a MusicGen text prompt."""
        prompts = {
            "upbeat": ("upbeat energetic background music, modern pop, positive vibes, no vocals"),
            "dramatic": ("dramatic cinematic background music, orchestral, epic, no vocals"),
            "calm": ("calm relaxing background music, ambient, gentle piano, no vocals"),
            "energetic": ("high energy electronic background music, driving beat, no vocals"),
            "mysterious": ("mysterious dark ambient background music, suspenseful, no vocals"),
            "playful": ("playful fun background music, light and bouncy, no vocals"),
            "tense": ("tense thriller background music, dark synths, building suspense, no vocals"),
            "inspirational": (
                "inspirational uplifting background music, orchestral swells, no vocals"
            ),
        }
        return prompts.get(
            mood.lower(),
            f"{mood} background music, instrumental, no vocals",
        )

    # ── FFmpeg loop/trim helper --------------------------------------------

    async def _loop_trim(
        self,
        source: Path,
        output: Path,
        duration: float,
    ) -> None:
        """Loop a music track to fill *duration* seconds, with a 2 s fade-out."""
        fade_start = max(0.0, duration - 2.0)

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-stream_loop",
            "-1",  # loop source infinitely
            "-i",
            str(source),
            "-t",
            str(duration),  # trim to target duration
            "-af",
            f"afade=t=out:st={fade_start}:d=2",  # 2 s fade-out
            "-ar",
            "44100",
            "-ac",
            "2",
            str(output),
        ]

        log.debug(
            "music.loop_trim",
            source=str(source),
            output=str(output),
            duration=duration,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")
            log.error(
                "music.loop_trim_failed",
                return_code=proc.returncode,
                stderr=stderr_text[-500:],
            )
            raise RuntimeError(
                f"FFmpeg loop/trim failed (rc={proc.returncode}): {stderr_text[-300:]}"
            )

        log.debug("music.loop_trim_done", output=str(output))
