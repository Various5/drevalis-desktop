"""FFmpeg service -- command builder and async executor.

Provides ``FFmpegService`` which wraps all FFmpeg / ffprobe operations
behind a clean async interface.  Every external call is dispatched via
``asyncio.create_subprocess_exec`` and properly logged with structlog.
"""

from __future__ import annotations

import asyncio
import json
import random as _random
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AssemblyConfig:
    """Encoding parameters for the final assembled video."""

    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    video_bitrate: str = "4M"
    pixel_format: str = "yuv420p"
    preset: str = "medium"
    ken_burns_enabled: bool = True
    transition_duration: float = 0.4

    # -- Watermark / logo overlay ------------------------------------------
    watermark_path: str | None = None
    """Absolute path to a PNG logo file.  ``None`` disables the watermark."""
    watermark_position: str = "bottom-right"
    """Corner placement: bottom-right | bottom-left | top-right | top-left."""
    watermark_opacity: float = 0.5
    """Compositing opacity — 0.0 (invisible) to 1.0 (fully opaque)."""
    watermark_scale: float = 0.08
    """Logo width as a fraction of the output video width (default 8 %)."""
    watermark_margin: int = 30
    """Pixel gap between the logo edge and the nearest video border."""


@dataclass
class AudioMixConfig:
    """Audio mastering parameters for voice + music mixing.

    Controls the full signal chain applied to voice and optional background
    music before they reach the final output stream:

    Voice chain:  highpass -> EQ presence boost -> compressor -> loudnorm
    Music chain:  volume -> optional reverb -> optional low-pass
    Mix:          sidechain duck -> amix -> optional brick-wall limiter
    """

    # -- Voice processing ---------------------------------------------------
    voice_normalize: bool = True
    """Apply two-pass loudnorm to voice (target integrated loudness)."""
    voice_target_lufs: float = -14.0
    """Target integrated loudness in LUFS (EBU R128 broadcast standard)."""
    voice_compressor: bool = True
    """Apply dynamic range compression to reduce loud/quiet variance."""
    voice_comp_threshold: float = -20.0
    """Compressor threshold in dB."""
    voice_comp_ratio: float = 3.0
    """Compressor ratio (e.g. 3 means 3:1)."""
    voice_comp_attack: float = 5.0
    """Compressor attack time in milliseconds."""
    voice_comp_release: float = 50.0
    """Compressor release time in milliseconds."""
    voice_eq: bool = True
    """Apply EQ: high-pass rumble cut + presence boost."""
    voice_eq_low_cut: int = 80
    """High-pass filter cutoff frequency in Hz (removes low-frequency rumble)."""
    voice_eq_presence_freq: int = 3000
    """Presence boost center frequency in Hz."""
    voice_eq_presence_gain: float = 3.0
    """Presence boost gain in dB."""

    # -- Music processing ---------------------------------------------------
    music_volume_db: float = -14.0
    """Music volume adjustment in dB relative to the input file level."""
    music_reverb: bool = False
    """Add reverb/hall effect to background music."""
    music_reverb_delay: int = 40
    """Reverb delay in milliseconds."""
    music_reverb_decay: float = 0.3
    """Reverb decay amount (0.0 = dry, 1.0 = very wet)."""
    music_low_pass: int = 0
    """Low-pass filter cutoff in Hz (0 = disabled). Use e.g. 8000 for muffled effect."""

    # -- Sidechain ducking --------------------------------------------------
    duck_threshold: float = 0.05
    """Sidechain compressor activation threshold (linear amplitude)."""
    duck_ratio: float = 3.5
    """Sidechain compression ratio applied to music when voice is present."""
    duck_attack: float = 100.0
    """Sidechain compressor attack time in milliseconds."""
    duck_release: float = 800.0
    """Sidechain compressor release time in milliseconds."""

    # -- Master bus ---------------------------------------------------------
    master_limiter: bool = True
    """Apply a brick-wall limiter on the master output to prevent clipping."""
    master_true_peak: float = -1.0
    """True-peak ceiling in dBTP (e.g. -1.0 dBTP = 0.891 linear)."""


AUDIO_PRESETS: dict[str, dict[str, float]] = {
    "podcast": {"duck_ratio": 4.0, "duck_threshold": 0.04, "music_volume_db": -18.0},
    "cinematic": {"duck_ratio": 2.5, "duck_threshold": 0.06, "music_volume_db": -10.0},
    "energetic": {"duck_ratio": 3.0, "duck_threshold": 0.05, "music_volume_db": -12.0},
    "ambient": {"duck_ratio": 2.0, "duck_threshold": 0.08, "music_volume_db": -8.0},
}
"""Named audio preset overrides for ``AudioMixConfig`` sidechain and volume parameters.

Each entry maps a preset name to a partial ``AudioMixConfig`` field dict.  Apply
with::

    preset_values = AUDIO_PRESETS["podcast"]
    for field, value in preset_values.items():
        setattr(audio_config, field, value)
"""

XFADE_TRANSITIONS: list[str] = [
    "fade",
    "slideright",
    "slideleft",
    "slideup",
    "slidedown",
    "circlecrop",
    "dissolve",
    "wipeleft",
    "wiperight",
    "diagtl",
    "diagtr",
    "pixelize",
]
"""Supported FFmpeg xfade transition names for Ken Burns assembly."""


@dataclass
class SceneInput:
    """A single scene image and its display duration."""

    image_path: Path
    duration_seconds: float


@dataclass
class AssemblyResult:
    """Result of the video assembly step."""

    output_path: str  # relative to storage
    duration_seconds: float
    file_size_bytes: int


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class FFmpegService:
    """Async wrapper around FFmpeg and ffprobe CLI tools."""

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
    ) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    # -- Public API ---------------------------------------------------------

    async def assemble_video(
        self,
        scenes: list[SceneInput],
        voiceover_path: Path,
        output_path: Path,
        *,
        captions_path: Path | None = None,
        background_music_path: Path | None = None,
        audio_config: AudioMixConfig | None = None,
        config: AssemblyConfig | None = None,
        on_progress: Callable[[float], Awaitable[None]] | None = None,
        base_seed: int | None = None,
        transition_style: str = "fade",
    ) -> AssemblyResult:
        """Assemble scenes + voiceover + optional captions/music into MP4.

        Pipeline:
        1. If Ken Burns is enabled and all inputs are images, use the
           zoompan+xfade filtergraph approach.
        2. Otherwise, create an FFmpeg concat-demuxer file for the timed
           image sequence and use the legacy pipeline.
        3. Execute FFmpeg.
        4. Verify output and return result.

        Args:
            scenes: Ordered list of scene images with per-scene durations.
            voiceover_path: Path to the synthesised voiceover audio.
            output_path: Destination path for the final MP4.
            captions_path: Optional ASS subtitle file for burn-in.
            background_music_path: Optional background music file.
            audio_config: Audio mastering parameters.  Uses defaults when ``None``.
            config: Video encoding parameters.  Uses defaults when ``None``.
            on_progress: Async callback receiving encoding progress (0–100 %).
            base_seed: Seed for reproducible Ken Burns motion and xfade
                selection.  Forwarded to ``_build_kenburns_command``.
            transition_style: xfade transition selection strategy.
                See ``_build_kenburns_command`` for accepted values.
        """
        if config is None:
            config = AssemblyConfig()
        if audio_config is None:
            audio_config = AudioMixConfig()

        if not scenes:
            raise ValueError("At least one SceneInput is required")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure scenes cover the full audio duration — if the voiceover
        # is longer than the total scene time, scale all scene durations
        # proportionally so images rotate throughout the entire video.
        audio_duration = await self.get_duration(voiceover_path)
        total_scene_dur = sum(s.duration_seconds for s in scenes)
        if audio_duration > total_scene_dur + 0.5:
            # Cap the per-scene stretch at 3×. A runaway voice track
            # (TTS provider glitch, user pasted a 10-minute monologue
            # into a Shorts episode) could otherwise push each 3s scene
            # to 60s+, yielding a zero-motion "frozen frame" video.
            # The raw cap-triggered case is rare, but silent. Log
            # loudly when we hit it so the operator has a trail.
            raw_scale = (audio_duration + 1.0) / total_scene_dur
            scale = min(raw_scale, 3.0)
            scenes = [
                SceneInput(
                    image_path=s.image_path,
                    duration_seconds=s.duration_seconds * scale,
                )
                for s in scenes
            ]
            log.info(
                "ffmpeg.scenes_scaled",
                audio_dur=round(audio_duration, 1),
                original_scene_dur=round(total_scene_dur, 1),
                scale=round(scale, 2),
                clamped=raw_scale > 3.0,
            )
            if raw_scale > 3.0:
                log.warning(
                    "ffmpeg.scenes_scale_clamped_to_3x",
                    audio_dur=round(audio_duration, 1),
                    requested_scale=round(raw_scale, 2),
                    message=(
                        "Voice track is much longer than the sum of scene "
                        "durations. Scenes stretched to 3x only; video will "
                        "end before audio. Consider adding scenes or tightening "
                        "the narration."
                    ),
                )

        # Determine whether to use Ken Burns filtergraph or concat demuxer.
        use_kenburns = (
            config.ken_burns_enabled
            and len(scenes) >= 1
            and all(self._is_image(s.image_path) for s in scenes)
        )

        if use_kenburns:
            cmd = self._build_kenburns_command(
                scenes=scenes,
                voiceover_path=voiceover_path,
                output_path=output_path,
                captions_path=captions_path,
                background_music_path=background_music_path,
                audio_mix_config=audio_config,
                config=config,
                base_seed=base_seed,
                transition_style=transition_style,
            )
            await self._run_ffmpeg(
                cmd,
                description="assemble_video_kenburns",
                total_duration=audio_duration,
                on_progress=on_progress,
            )
        else:
            concat_file = await self._create_concat_file(scenes, output_path.parent)

            try:
                cmd = self._build_assembly_command(
                    concat_file=concat_file,
                    voiceover_path=voiceover_path,
                    output_path=output_path,
                    captions_path=captions_path,
                    background_music_path=background_music_path,
                    audio_mix_config=audio_config,
                    config=config,
                )

                await self._run_ffmpeg(
                    cmd,
                    description="assemble_video",
                    total_duration=audio_duration,
                    on_progress=on_progress,
                )
            finally:
                # Clean up temp concat file.
                try:
                    concat_file.unlink(missing_ok=True)
                except OSError:
                    pass

        if not output_path.exists():
            raise FileNotFoundError(f"FFmpeg did not produce output file: {output_path}")

        file_size = output_path.stat().st_size
        duration = await self.get_duration(output_path)

        log.info(
            "ffmpeg.assemble_video.done",
            output=str(output_path),
            duration=duration,
            file_size=file_size,
        )

        return AssemblyResult(
            output_path=str(output_path),
            duration_seconds=duration,
            file_size_bytes=file_size,
        )

    async def get_duration(self, file_path: Path) -> float:
        """Get duration of an audio or video file using ffprobe."""
        cmd = [
            self.ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(file_path),
        ]

        log.debug("ffprobe.get_duration", path=str(file_path))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")
            log.error(
                "ffprobe.get_duration.failed",
                path=str(file_path),
                stderr=stderr_text,
            )
            raise RuntimeError(f"ffprobe failed for {file_path}: {stderr_text}")

        try:
            info = json.loads(stdout.decode("utf-8"))
            return float(info["format"]["duration"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise RuntimeError(
                f"Could not parse duration from ffprobe output for {file_path}"
            ) from exc

    async def convert_audio(
        self,
        input_path: Path,
        output_path: Path,
        *,
        codec: str = "aac",
        bitrate: str = "192k",
    ) -> Path:
        """Convert audio format (e.g. WAV to AAC)."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
            "-c:a",
            codec,
            "-b:a",
            bitrate,
            "-vn",
            str(output_path),
        ]

        await self._run_ffmpeg(cmd, description="convert_audio")

        if not output_path.exists():
            raise FileNotFoundError(f"Audio conversion did not produce output: {output_path}")

        log.info(
            "ffmpeg.convert_audio.done",
            input=str(input_path),
            output=str(output_path),
        )
        return output_path

    async def extract_thumbnail(
        self,
        video_path: Path,
        output_path: Path,
        *,
        timestamp_seconds: float = 0.5,
    ) -> Path:
        """Extract a single frame from a video as a thumbnail image."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss",
            str(timestamp_seconds),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]

        await self._run_ffmpeg(cmd, description="extract_thumbnail")

        if not output_path.exists():
            raise FileNotFoundError(f"Thumbnail extraction did not produce output: {output_path}")

        log.info(
            "ffmpeg.extract_thumbnail.done",
            video=str(video_path),
            output=str(output_path),
        )
        return output_path

    async def extract_best_thumbnail(
        self,
        video_path: Path,
        output_path: Path,
        candidate_count: int = 10,
    ) -> None:
        """Extract the best-quality frame as thumbnail by sampling multiple candidates.

        Probes the video duration, then samples *candidate_count* frames evenly
        distributed across the middle 80 % of the video (skipping the first and
        last 10 %).  Each candidate JPEG is written to a temporary directory and
        its file size is used as a sharpness proxy — larger compressed files
        generally encode more high-frequency detail.  The largest-file candidate
        is copied to *output_path*.  If any part of the analysis fails, the
        method falls back to a simple mid-point extraction.

        Args:
            video_path: Absolute path to the source video file.
            output_path: Destination path for the chosen thumbnail JPEG.
            candidate_count: Number of candidate frames to sample (default 10).
        """
        try:
            duration = await self.get_duration(video_path)
        except Exception:
            duration = 0.0

        if duration <= 0:
            log.warning(
                "extract_best_thumbnail.invalid_duration",
                video=str(video_path),
                duration=duration,
            )
            await self.extract_thumbnail(
                video_path=video_path,
                output_path=output_path,
                timestamp_seconds=0.5,
            )
            return

        # Sample evenly across the middle 80 % to avoid black frames at
        # the very start/end of the clip.
        start = duration * 0.1
        end = duration * 0.9
        step = (end - start) / max(candidate_count - 1, 1)
        timestamps = [start + i * step for i in range(candidate_count)]

        best_path: Path | None = None
        best_size: int = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            for i, ts in enumerate(timestamps):
                candidate = Path(tmpdir) / f"frame_{i}.jpg"
                try:
                    await self.extract_thumbnail(
                        video_path=video_path,
                        output_path=candidate,
                        timestamp_seconds=ts,
                    )
                    size = candidate.stat().st_size
                    if size > best_size:
                        best_size = size
                        best_path = candidate
                except Exception as exc:
                    log.debug(
                        "extract_best_thumbnail.candidate_failed",
                        index=i,
                        timestamp=ts,
                        error=str(exc),
                    )
                    continue

            if best_path is not None and best_path.exists():
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(best_path), str(output_path))
                log.info(
                    "extract_best_thumbnail.done",
                    video=str(video_path),
                    output=str(output_path),
                    best_size_bytes=best_size,
                    candidates_tried=len(timestamps),
                )
            else:
                # All candidates failed — fall back to the exact midpoint.
                log.warning(
                    "extract_best_thumbnail.all_candidates_failed",
                    video=str(video_path),
                )
                await self.extract_thumbnail(
                    video_path=video_path,
                    output_path=output_path,
                    timestamp_seconds=duration / 2,
                )

    async def compose_thumbnail(
        self,
        base_image_path: Path,
        output_path: Path,
        title: str,
        subtitle: str = "",
        font_size: int = 72,
    ) -> None:
        """Overlay title text on a thumbnail image with a semi-transparent bar.

        Draws a darkened gradient bar across the bottom 35 % of the image,
        then renders *title* centred in Impact font.  An optional *subtitle*
        is rendered at half the *font_size* below the title.  If the FFmpeg
        drawtext filter fails for any reason, the base image is copied as-is
        so the pipeline always produces a thumbnail.

        Args:
            base_image_path: Source JPEG/PNG image to annotate.
            output_path: Destination path for the composed thumbnail.
            title: Primary headline text rendered over the image.
            subtitle: Optional secondary text rendered below the title.
            font_size: Point size for the title text (default 72).
        """

        # Escape characters that have special meaning inside FFmpeg drawtext
        # filter expressions.  Single quotes are the most dangerous because
        # they terminate the filter string.
        def _esc(text: str) -> str:
            return text.replace("\\", "\\\\").replace("'", "'\\''").replace(":", "\\:")

        safe_title = _esc(title)
        safe_subtitle = _esc(subtitle)

        filters: list[str] = []
        # Semi-transparent dark bar across the bottom third.
        filters.append("drawbox=y=ih*0.65:w=iw:h=ih*0.35:c=black@0.6:t=fill")
        # Primary title, centred horizontally at ~72 % down.
        filters.append(
            f"drawtext=text='{safe_title}':fontsize={font_size}:fontcolor=white:"
            f"x=(w-tw)/2:y=h*0.72:font=Impact"
        )
        # Optional subtitle at half the font size, ~85 % down.
        if subtitle:
            sub_size = font_size // 2
            filters.append(
                f"drawtext=text='{safe_subtitle}':fontsize={sub_size}:fontcolor=white@0.7:"
                f"x=(w-tw)/2:y=h*0.85:font=Impact"
            )

        filter_str = ",".join(filters)
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(base_image_path),
            "-vf",
            filter_str,
            "-q:v",
            "2",
            str(output_path),
        ]

        output_path.parent.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_text = stderr.decode("utf-8", errors="replace")[:300]
            log.warning(
                "compose_thumbnail.failed",
                base=str(base_image_path),
                error=error_text,
            )
            # Non-fatal: copy the base image so the pipeline still has a thumbnail.
            shutil.copy2(str(base_image_path), str(output_path))
            return

        log.info(
            "ffmpeg.compose_thumbnail.done",
            base=str(base_image_path),
            output=str(output_path),
            has_subtitle=bool(subtitle),
        )

    # -- Audio mastering filtergraph builder --------------------------------

    def _build_audio_filtergraph(
        self,
        voice_input_label: str,
        music_input_label: str | None,
        audio_mix_config: AudioMixConfig,
    ) -> tuple[list[str], str]:
        """Build the professional audio mastering filter chain.

        Constructs FFmpeg filter segments for the voice processing chain,
        optional music chain, sidechain ducking, and master limiter.  The
        caller appends the returned segment list to the overall
        ``filter_complex`` string (joined with ``";"``).

        Args:
            voice_input_label: FFmpeg stream label for the raw voice input,
                e.g. ``"1:a"`` or ``"3:a"``.  Must NOT include brackets.
            music_input_label: FFmpeg stream label for background music, or
                ``None`` when no music is present.
            audio_mix_config: Mastering parameters.

        Returns:
            A tuple of ``(filter_segments, output_label)`` where
            ``filter_segments`` is a list of semicolon-free filter strings
            ready to be joined, and ``output_label`` is the bracket-free
            label of the final audio stream (e.g. ``"amaster"``).
        """
        cfg = audio_mix_config
        has_music = music_input_label is not None

        # ── Voice processing chain ─────────────────────────────────────────
        # Build the voice filter as a single comma-joined chain so it stays
        # as one filter_complex segment from the voice input to [vo_processed].
        voice_filters: list[str] = []

        if cfg.voice_eq:
            # High-pass filter removes low-frequency rumble (HVAC, mic proximity).
            voice_filters.append(f"highpass=f={cfg.voice_eq_low_cut}")
            # Parametric EQ presence boost makes voice cut through the mix.
            voice_filters.append(
                f"equalizer=f={cfg.voice_eq_presence_freq}:t=q:w=1.5:g={cfg.voice_eq_presence_gain}"
            )

        if cfg.voice_compressor:
            # Dynamic range compression evens out loud/quiet passages.
            voice_filters.append(
                f"acompressor"
                f"=threshold={cfg.voice_comp_threshold}dB"
                f":ratio={cfg.voice_comp_ratio}"
                f":attack={cfg.voice_comp_attack}"
                f":release={cfg.voice_comp_release}"
            )

        if cfg.voice_normalize:
            # EBU R128 integrated loudness normalization.
            voice_filters.append(f"loudnorm=I={cfg.voice_target_lufs}:LRA=11:TP=-1")

        # Both branches historically produced the same label — the asplit
        # used for sidechain happens further down, not here. Kept as a
        # single assignment for clarity; the original if/else was dead.
        voice_chain_out = "vo_processed"
        _ = has_music  # reserved for future branch-specific logic

        # Emit the voice processing segment.
        segments: list[str] = []
        if voice_filters:
            chain_str = ",".join(voice_filters)
            segments.append(f"[{voice_input_label}]{chain_str}[{voice_chain_out}]")
        else:
            # No voice processing — pass through with a rename label.
            segments.append(f"[{voice_input_label}]acopy[{voice_chain_out}]")

        # ── Route voice into sidechain split or direct output ──────────────
        if has_music:
            # Split voice into two streams: sidechain detector + mix input.
            segments.append(f"[{voice_chain_out}]asplit=2[vo_sc][vo_mix]")

            # ── Music processing chain ─────────────────────────────────────
            music_filters: list[str] = []

            # Volume adjustment relative to input level.
            music_filters.append(f"volume={cfg.music_volume_db}dB")

            if cfg.music_reverb:
                # aecho syntax: in_gain:out_gain:delay_ms:decay
                # A subtle reverb adds space and depth to the music bed.
                music_filters.append(
                    f"aecho=0.8:0.8:{cfg.music_reverb_delay}:{cfg.music_reverb_decay}"
                )

            if cfg.music_low_pass > 0:
                # Low-pass filter creates a muffled/distance effect.
                music_filters.append(f"lowpass=f={cfg.music_low_pass}")

            music_chain_str = ",".join(music_filters)
            segments.append(f"[{music_input_label}]{music_chain_str}[bgm]")

            # ── Sidechain ducking ──────────────────────────────────────────
            # sidechaincompress: [main_signal][sidechain_key]
            # [bgm] is the stream to be compressed (ducked).
            # [vo_sc] is the detector signal (voice).
            segments.append(
                f"[bgm][vo_sc]sidechaincompress"
                f"=threshold={cfg.duck_threshold}"
                f":ratio={cfg.duck_ratio}"
                f":attack={cfg.duck_attack}"
                f":release={cfg.duck_release}"
                f":level_in=1:level_sc=1[ducked]"
            )

            # ── Mix voice + ducked music ───────────────────────────────────
            segments.append(
                "[vo_mix][ducked]amix=inputs=2:duration=first:dropout_transition=2[amixed]"
            )
            pre_limiter_label = "amixed"
        else:
            # No music — voice output goes directly to limiter or final output.
            pre_limiter_label = voice_chain_out

        # ── Master limiter ─────────────────────────────────────────────────
        if cfg.master_limiter:
            # Convert dBTP to linear amplitude: 10^(dBTP/20).
            limit_linear = 10.0 ** (cfg.master_true_peak / 20.0)
            segments.append(
                f"[{pre_limiter_label}]"
                f"alimiter=limit={limit_linear:.6f}:attack=5:release=50"
                f"[amaster]"
            )
            output_label = "amaster"
        else:
            output_label = pre_limiter_label

        return segments, output_label

    # -- Watermark filter helper -------------------------------------------

    @staticmethod
    def _build_watermark_filter(
        config: AssemblyConfig,
        input_label: str,
        output_label: str,
    ) -> str | None:
        """Return a self-contained filter_complex segment that overlays a logo.

        Uses the FFmpeg ``movie`` source filter so the logo is loaded inline
        without requiring an extra ``-i`` input, keeping the input index
        accounting in the three command builders unchanged.

        The logo is:
        1. Decoded from *config.watermark_path*.
        2. Scaled to ``watermark_scale * video_width`` pixels wide,
           height derived automatically (``-1`` = preserve aspect ratio).
        3. Converted to ``rgba`` so the alpha channel is available.
        4. Alpha-multiplied to ``watermark_opacity`` via ``colorchannelmixer``.
        5. Overlaid on the video stream at the configured corner position.

        Returns ``None`` when ``config.watermark_path`` is unset or the file
        does not exist, so callers can guard with a simple ``if`` check.

        Args:
            config: Assembly config carrying watermark parameters.
            input_label: Bracket-free label of the incoming video stream,
                e.g. ``"vout"`` or ``"last_label"``.
            output_label: Bracket-free label for the resulting composite stream.

        Returns:
            A semicolon-free filter string ready to append to a
            ``filter_complex`` segment list, or ``None``.
        """
        if not config.watermark_path:
            return None

        wm_path = Path(config.watermark_path)
        if not wm_path.exists():
            log.warning(
                "ffmpeg.watermark.file_not_found",
                path=config.watermark_path,
            )
            return None

        # Pixel width of the logo; height derived automatically.
        wm_w = round(config.width * config.watermark_scale)
        # Clamp opacity to valid range.
        opacity = max(0.0, min(1.0, config.watermark_opacity))
        margin = config.watermark_margin

        # Overlay position expressed in FFmpeg overlay filter syntax where
        # ``W``/``H`` are the main stream dimensions and ``w``/``h`` are the
        # watermark overlay dimensions.
        position_map: dict[str, str] = {
            "bottom-right": f"W-w-{margin}:H-h-{margin}",
            "bottom-left": f"{margin}:H-h-{margin}",
            "top-right": f"W-w-{margin}:{margin}",
            "top-left": f"{margin}:{margin}",
        }
        pos = position_map.get(config.watermark_position, position_map["bottom-right"])

        # Forward slashes required inside the movie= path argument on all
        # platforms; escape colons that would otherwise confuse the filter
        # option parser.
        safe_path = config.watermark_path.replace("\\", "/").replace(":", "\\:")

        return (
            f"movie='{safe_path}'"
            f",scale={wm_w}:-1"
            f",format=rgba"
            # colorchannelmixer aa=<opacity> scales the alpha channel uniformly.
            f",colorchannelmixer=aa={opacity:.4f}"
            f"[wm_overlay];"
            f"[{input_label}][wm_overlay]overlay={pos}[{output_label}]"
        )

    # -- Ken Burns filtergraph builder -------------------------------------

    def _build_kenburns_command(
        self,
        scenes: list[SceneInput],
        voiceover_path: Path,
        output_path: Path,
        captions_path: Path | None,
        background_music_path: Path | None,
        audio_mix_config: AudioMixConfig,
        config: AssemblyConfig,
        *,
        base_seed: int | None = None,
        transition_style: str = "fade",
    ) -> list[str]:
        """Build an FFmpeg command with zoompan + xfade transitions.

        Each scene image is loaded as a looped input with ``-t`` to bound
        its duration.  A zoompan filter creates the Ken Burns effect using
        seeded-random variable zoom (6-15 %) across four motion directions
        (zoom_in, zoom_out, pan_left, pan_right), and xfade provides
        crossfade transitions between adjacent scenes.

        Args:
            scenes: Per-scene image paths and display durations.
            voiceover_path: Path to the voiceover WAV/AAC file.
            output_path: Destination MP4 path.
            captions_path: Optional ASS subtitle file for burn-in.
            background_music_path: Optional background music file.
            audio_mix_config: Mastering parameters for the audio chain.
            config: Video encoding / assembly parameters.
            base_seed: Optional integer seed for reproducible Ken Burns
                motion and xfade selection.  ``None`` means unseeded (uses
                index-only for zoom direction, ``fade`` for xfade).
            transition_style: Controls xfade transition selection.
                ``"fade"`` (default) — always use fade.
                ``"random"`` — seeded-random pick per transition.
                ``"variety"`` — round-robin through XFADE_TRANSITIONS.
                Any name in XFADE_TRANSITIONS — use that transition always.

        Filtergraph structure:

        1. Per-image: scale to target resolution, pad, zoompan, format.
        2. Chain zoompan outputs with xfade crossfades.
        3. Burn-in ASS subtitles at the end of the video chain.
        4. Mix audio (voiceover + optional background music with ducking).
        """
        cmd: list[str] = [self.ffmpeg_path, "-y"]

        w = config.width
        h = config.height
        fps = config.fps
        td = config.transition_duration
        has_music = background_music_path is not None

        # -- inputs: one per scene image, duration-bounded ------------------
        for scene in scenes:
            cmd += [
                "-loop",
                "1",
                "-t",
                str(scene.duration_seconds),
                "-i",
                str(scene.image_path),
            ]

        # Audio input index starts after all images
        audio_input_idx = len(scenes)
        cmd += ["-i", str(voiceover_path)]

        music_input_idx: int | None = None
        if has_music:
            music_input_idx = audio_input_idx + 1
            cmd += ["-i", str(background_music_path)]

        # -- build filtergraph ---------------------------------------------
        filter_parts: list[str] = []

        # Step 1: For each image, apply scale + pad + zoompan + format.
        # Upscale source image 2x for smoother zoompan (avoids pixelation/stutter).
        src_w = w * 2
        src_h = h * 2

        for idx, scene in enumerate(scenes):
            total_frames = max(1, round(scene.duration_seconds * fps))

            # Seeded RNG per scene for reproducible results across retries.
            rng = _random.Random(idx + (base_seed or 0))
            zoom_pct = rng.uniform(0.06, 0.15)
            zoom_speed = round(zoom_pct / total_frames, 8)

            direction = rng.choice(["zoom_in", "zoom_out", "pan_left", "pan_right"])

            if direction == "zoom_in":
                zoom_expr = f"min(zoom+{zoom_speed},{1 + zoom_pct:.6f})"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"
            elif direction == "zoom_out":
                zoom_expr = f"if(eq(on,0),{1 + zoom_pct:.6f},max(zoom-{zoom_speed},1.0))"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"
            elif direction == "pan_left":
                zoom_expr = "1.08"
                pan_speed = round(0.15 / total_frames, 8)
                x_expr = f"iw*0.15-iw*{pan_speed}*on"
                y_expr = "ih/2-(ih/zoom/2)"
            else:  # pan_right
                zoom_expr = "1.08"
                pan_speed = round(0.15 / total_frames, 8)
                x_expr = f"iw*{pan_speed}*on"
                y_expr = "ih/2-(ih/zoom/2)"

            filter_parts.append(
                f"[{idx}:v]scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
                f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"zoompan=z='{zoom_expr}':"
                f"x='{x_expr}':y='{y_expr}':"
                f"d={total_frames}:s={w}x{h}:fps={fps},"
                f"format={config.pixel_format}[v{idx}]"
            )

        # Step 2: Chain zoompan outputs with xfade transitions.
        if len(scenes) == 1:
            last_label = "v0"
        else:
            # Resolve the transition name for scene pair 0→1 (xfade index 0).
            transition = self._resolve_xfade_transition(
                idx=0, style=transition_style, base_seed=base_seed
            )
            # First xfade: between scene 0 and scene 1
            offset = scenes[0].duration_seconds - td
            offset = max(0.0, offset)
            filter_parts.append(
                f"[v0][v1]xfade=transition={transition}:duration={td}:offset={offset:.3f}[vt0]"
            )

            # Track the cumulative duration of the combined stream so far.
            # After the first xfade the combined length is d0 + d1 - td.
            cumulative = scenes[0].duration_seconds + scenes[1].duration_seconds - td

            # Subsequent xfades
            for i in range(2, len(scenes)):
                transition = self._resolve_xfade_transition(
                    idx=i - 1, style=transition_style, base_seed=base_seed
                )
                offset = cumulative - td
                offset = max(0.0, offset)
                in_label = f"vt{i - 2}"
                out_label = f"vt{i - 1}"
                filter_parts.append(
                    f"[{in_label}][v{i}]xfade=transition={transition}"
                    f":duration={td}:offset={offset:.3f}[{out_label}]"
                )
                cumulative = offset + scenes[i].duration_seconds

            last_label = f"vt{len(scenes) - 2}"

        # Step 3: Burn-in subtitles (if provided) + ensure yuv420p output
        if captions_path is not None:
            escaped = str(captions_path).replace("\\", "/")
            escaped = escaped.replace(":", "\\:")
            escaped = escaped.replace("'", "'\\''")
            escaped = escaped.replace("[", "\\[")
            escaped = escaped.replace("]", "\\]")
            escaped = escaped.replace(";", "\\;")
            escaped = escaped.replace(",", "\\,")
            # subtitles filter can change pixel format to yuv444p;
            # force back to yuv420p for browser compatibility
            filter_parts.append(
                f"[{last_label}]subtitles='{escaped}',format={config.pixel_format}[vout]"
            )
            video_out_label = "vout"
        else:
            video_out_label = last_label

        # Step 3b: Watermark overlay (applied after subtitles are burned in)
        wm_segment = self._build_watermark_filter(
            config=config,
            input_label=video_out_label,
            output_label="vout_wm",
        )
        if wm_segment is not None:
            filter_parts.append(wm_segment)
            video_out_label = "vout_wm"

        # Step 4: Audio filtergraph — professional mastering chain
        music_label = (
            f"{music_input_idx}:a" if (has_music and music_input_idx is not None) else None
        )
        audio_filter_parts, audio_out_label = self._build_audio_filtergraph(
            voice_input_label=f"{audio_input_idx}:a",
            music_input_label=music_label,
            audio_mix_config=audio_mix_config,
        )
        filter_parts.extend(audio_filter_parts)

        # Assemble the full filter_complex string
        full_filter = ";".join(filter_parts)
        cmd += ["-filter_complex", full_filter]

        # -- mapping --------------------------------------------------------
        cmd += ["-map", f"[{video_out_label}]"]
        if audio_out_label:
            cmd += ["-map", f"[{audio_out_label}]"]
        else:
            cmd += ["-map", f"{audio_input_idx}:a"]

        # -- encoding -------------------------------------------------------
        cmd += [
            "-c:v",
            config.video_codec,
            "-profile:v",
            "high",
            "-pix_fmt",
            config.pixel_format,
            "-preset",
            config.preset,
            "-b:v",
            config.video_bitrate,
            "-c:a",
            config.audio_codec,
            "-b:a",
            config.audio_bitrate,
            "-ar",
            "48000",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        log.debug(
            "ffmpeg.kenburns_command.built",
            scene_count=len(scenes),
            filter_length=len(full_filter),
        )

        return cmd

    # -- xfade transition resolver ------------------------------------------

    @staticmethod
    def _resolve_xfade_transition(
        idx: int,
        style: str,
        base_seed: int | None,
    ) -> str:
        """Return an FFmpeg xfade transition name for a given transition index.

        Args:
            idx: Zero-based index of the transition (used for seeding and
                round-robin selection).
            style: Transition style token — ``"fade"`` (always fade),
                ``"random"`` (seeded random from XFADE_TRANSITIONS),
                ``"variety"`` (round-robin through XFADE_TRANSITIONS), or
                any literal name in XFADE_TRANSITIONS.
            base_seed: Optional base seed for reproducible random selection.

        Returns:
            A valid FFmpeg xfade transition name string.
        """
        if style == "random":
            rng = _random.Random(idx + (base_seed or 0))
            return rng.choice(XFADE_TRANSITIONS)
        if style == "variety":
            return XFADE_TRANSITIONS[idx % len(XFADE_TRANSITIONS)]
        if style in XFADE_TRANSITIONS:
            return style
        return "fade"

    # -- Legacy command builder (concat-demuxer approach) -------------------

    def _build_assembly_command(
        self,
        concat_file: Path,
        voiceover_path: Path,
        output_path: Path,
        captions_path: Path | None,
        background_music_path: Path | None,
        audio_mix_config: AudioMixConfig,
        config: AssemblyConfig,
    ) -> list[str]:
        """Build the FFmpeg command-line arguments for video assembly.

        Inputs:
        - ``[0]``  concat demuxer  (timed image slideshow)
        - ``[1]``  voiceover audio
        - ``[2]``  (optional) background music

        Filtergraph:
        - Scale each image to ``config.width x config.height`` with
          padding (black letterbox) to preserve aspect ratio.
        - Burn-in ASS subtitles if *captions_path* is provided.
        - Mix voiceover + ducked background music if music is provided.
        """
        cmd: list[str] = [self.ffmpeg_path, "-y"]

        # -- inputs ---------------------------------------------------------
        # Input 0: concat demuxer for images
        cmd += [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
        ]
        # Input 1: voiceover
        cmd += ["-i", str(voiceover_path)]

        # Input 2 (optional): background music
        has_music = background_music_path is not None
        if has_music:
            cmd += ["-i", str(background_music_path)]

        # -- filtergraph ----------------------------------------------------
        video_filters: list[str] = []

        # Scale to target resolution, preserving aspect ratio with padding.
        video_filters.append(
            f"scale={config.width}:{config.height}:force_original_aspect_ratio=decrease"
        )
        video_filters.append(f"pad={config.width}:{config.height}:(ow-iw)/2:(oh-ih)/2:color=black")

        # Set frame rate.
        video_filters.append(f"fps={config.fps}")

        # Extend last video frame to cover full audio duration.
        video_filters.append("tpad=stop_mode=clone:stop_duration=120")

        # Set pixel format.
        video_filters.append(f"format={config.pixel_format}")

        # Burn-in ASS subtitles.
        if captions_path is not None:
            escaped = str(captions_path).replace("\\", "/")
            escaped = escaped.replace(":", "\\:")
            escaped = escaped.replace("'", "'\\''")
            escaped = escaped.replace("[", "\\[")
            escaped = escaped.replace("]", "\\]")
            escaped = escaped.replace(";", "\\;")
            escaped = escaped.replace(",", "\\,")
            video_filters.append(f"subtitles='{escaped}'")

        video_chain = ",".join(video_filters)

        # -- audio filtergraph ----------------------------------------------
        music_label: str | None = "2:a" if has_music else None
        audio_filter_parts, audio_out_label = self._build_audio_filtergraph(
            voice_input_label="1:a",
            music_input_label=music_label,
            audio_mix_config=audio_mix_config,
        )
        audio_filter_str = ";".join(audio_filter_parts)

        # Watermark overlay appended after the main video chain.
        video_final_label = "vout"
        wm_segment = self._build_watermark_filter(
            config=config,
            input_label="vout",
            output_label="vout_wm",
        )
        if wm_segment is not None:
            full_filter = f"[0:v]{video_chain}[vout];{wm_segment};{audio_filter_str}"
            video_final_label = "vout_wm"
        else:
            full_filter = f"[0:v]{video_chain}[vout];{audio_filter_str}"

        cmd += ["-filter_complex", full_filter]
        cmd += ["-map", f"[{video_final_label}]", "-map", f"[{audio_out_label}]"]

        # -- encoding -------------------------------------------------------
        cmd += [
            "-c:v",
            config.video_codec,
            "-preset",
            config.preset,
            "-b:v",
            config.video_bitrate,
            "-c:a",
            config.audio_codec,
            "-b:a",
            config.audio_bitrate,
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        return cmd

    # -- Subprocess runner --------------------------------------------------

    async def _run_ffmpeg(
        self,
        args: list[str],
        description: str,
        *,
        total_duration: float | None = None,
        on_progress: Callable[[float], Awaitable[None]] | None = None,
    ) -> str:
        """Execute an FFmpeg/ffprobe command and return stderr output.

        If *total_duration* and *on_progress* are provided, FFmpeg's
        stderr is parsed in real time and on_progress(pct) is called
        periodically with the encoding progress percentage.

        Raises ``RuntimeError`` if the process exits with a non-zero code.
        """
        log.debug(
            "ffmpeg.exec",
            description=description,
            command=" ".join(args),
        )

        # If progress tracking requested, read stderr line-by-line
        if total_duration and on_progress and total_duration > 10:
            import re as _re

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stderr_lines: list[str] = []
            last_pct = -1
            assert proc.stderr is not None  # PIPE'd above; mypy can't narrow

            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                stderr_lines.append(text)

                # Parse "time=HH:MM:SS.xx" from FFmpeg progress output
                m = _re.search(r"time=(\d+):(\d+):(\d+\.\d+)", text)
                if m:
                    t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    pct = min(99, int(t / total_duration * 100))
                    if pct > last_pct + 2:  # throttle updates
                        last_pct = pct
                        try:
                            await on_progress(pct)
                        except Exception:
                            pass

            await proc.wait()
            stderr_text = "\n".join(stderr_lines)
        else:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            stderr_text = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            log.error(
                "ffmpeg.exec.failed",
                description=description,
                return_code=proc.returncode,
                stderr=stderr_text[-2000:],
            )
            raise RuntimeError(
                f"FFmpeg {description} failed (rc={proc.returncode}): {stderr_text[-500:]}"
            )

        log.debug(
            "ffmpeg.exec.done",
            description=description,
            return_code=proc.returncode,
        )
        return stderr_text

    # -- Concat file builder ------------------------------------------------

    async def _create_concat_file(
        self,
        scenes: list[SceneInput],
        output_dir: Path,
    ) -> Path:
        """Create an FFmpeg concat-demuxer input file.

        Each entry specifies an image and the duration it should be shown::

            file '/absolute/path/to/image.png'
            duration 5.0
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Use a deterministic temp name within the output directory so the
        # caller can clean it up easily.
        concat_path = output_dir / "_concat_list.txt"

        lines: list[str] = []
        for scene in scenes:
            # FFmpeg concat demuxer expects forward slashes and single-quoted paths.
            safe_path = str(scene.image_path).replace("\\", "/")
            lines.append(f"file '{safe_path}'")
            lines.append(f"duration {scene.duration_seconds}")

        # Repeat the last image entry so FFmpeg shows it for the full duration.
        if scenes:
            last_safe = str(scenes[-1].image_path).replace("\\", "/")
            lines.append(f"file '{last_safe}'")

        content = "\n".join(lines) + "\n"

        # Write using asyncio.to_thread to avoid blocking the event loop
        # on very long scene lists, though in practice this is trivial.
        await asyncio.to_thread(concat_path.write_text, content, "utf-8")

        log.debug(
            "ffmpeg.concat_file.created",
            path=str(concat_path),
            scene_count=len(scenes),
        )
        return concat_path

    # -- Video clip concatenation -------------------------------------------

    async def concat_videos(
        self,
        video_clips: list[Path],
        output_path: Path,
    ) -> Path:
        """Concatenate video clips into a single MP4 with no audio mixing.

        Used by the edit-session render path which mixes voice and music
        in later stages. Uses the concat demuxer with stream copy when
        all inputs share codec/parameters; falls back to re-encode otherwise.
        """
        if not video_clips:
            raise ValueError("At least one video clip is required")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        concat_path = output_path.parent / "_video_only_concat_list.txt"
        lines = [f"file '{str(clip).replace(chr(92), '/')}'" for clip in video_clips]
        await asyncio.to_thread(concat_path.write_text, "\n".join(lines) + "\n", "utf-8")

        try:
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(output_path),
            ]
            await self._run_ffmpeg(cmd, description="concat_videos")
        finally:
            try:
                concat_path.unlink(missing_ok=True)
            except OSError:
                pass

        if not output_path.exists():
            raise FileNotFoundError(f"FFmpeg did not produce output file: {output_path}")
        return output_path

    async def concat_video_clips(
        self,
        video_clips: list[Path],
        voiceover_path: Path,
        output_path: Path,
        *,
        captions_path: Path | None = None,
        background_music_path: Path | None = None,
        audio_config: AudioMixConfig | None = None,
        config: AssemblyConfig | None = None,
    ) -> AssemblyResult:
        """Concatenate video clips with voiceover, optional captions and music.

        Uses FFmpeg's concat demuxer to join pre-rendered video clips
        (e.g. from Wan 2.6 text-to-video) into a single output, then
        mixes in the voiceover audio and optional background music.
        ASS subtitles are burned in when *captions_path* is provided.

        Pipeline:
        1. Write a concat-demuxer input file listing each video clip.
        2. Build the FFmpeg command with audio mixing and subtitle burn-in.
        3. Execute and verify the output.
        """
        if config is None:
            config = AssemblyConfig()
        if audio_config is None:
            audio_config = AudioMixConfig()

        if not video_clips:
            raise ValueError("At least one video clip is required")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Step 1: Create the concat file
        concat_path = output_path.parent / "_video_concat_list.txt"
        lines: list[str] = []
        for clip in video_clips:
            safe_path = str(clip).replace("\\", "/")
            lines.append(f"file '{safe_path}'")
        content = "\n".join(lines) + "\n"
        await asyncio.to_thread(concat_path.write_text, content, "utf-8")

        log.debug(
            "ffmpeg.video_concat_file.created",
            path=str(concat_path),
            clip_count=len(video_clips),
        )

        try:
            # Step 2: Get voiceover duration to set output length
            voiceover_duration = await self.get_duration(voiceover_path)

            # Step 3: Build the FFmpeg command
            cmd = self._build_video_concat_command(
                concat_file=concat_path,
                voiceover_path=voiceover_path,
                output_path=output_path,
                captions_path=captions_path,
                background_music_path=background_music_path,
                audio_mix_config=audio_config,
                config=config,
            )

            # Add -t to limit output to exact voiceover duration
            # Insert before the output path (last element)
            cmd.insert(-1, "-t")
            cmd.insert(-1, f"{voiceover_duration:.2f}")

            # Step 4: Execute
            await self._run_ffmpeg(cmd, description="concat_video_clips")
        finally:
            try:
                concat_path.unlink(missing_ok=True)
            except OSError:
                pass

        if not output_path.exists():
            raise FileNotFoundError(f"FFmpeg did not produce output file: {output_path}")

        file_size = output_path.stat().st_size
        duration = await self.get_duration(output_path)

        log.info(
            "ffmpeg.concat_video_clips.done",
            output=str(output_path),
            duration=duration,
            file_size=file_size,
            clip_count=len(video_clips),
        )

        return AssemblyResult(
            output_path=str(output_path),
            duration_seconds=duration,
            file_size_bytes=file_size,
        )

    def _build_video_concat_command(
        self,
        concat_file: Path,
        voiceover_path: Path,
        output_path: Path,
        captions_path: Path | None,
        background_music_path: Path | None,
        audio_mix_config: AudioMixConfig,
        config: AssemblyConfig,
    ) -> list[str]:
        """Build FFmpeg command to concatenate video clips with audio.

        Inputs:
        - ``[0]``  concat demuxer (video clips)
        - ``[1]``  voiceover audio
        - ``[2]``  (optional) background music

        The concatenated video is scaled to the target resolution and
        optionally has ASS subtitles burned in.  Audio is mixed with
        optional sidechain-ducked background music.
        """
        cmd: list[str] = [self.ffmpeg_path, "-y"]

        # -- inputs -----------------------------------------------------
        # Input 0: concat demuxer for video clips
        cmd += [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
        ]
        # Input 1: voiceover
        cmd += ["-i", str(voiceover_path)]

        # Input 2 (optional): background music
        has_music = background_music_path is not None
        if has_music:
            cmd += ["-i", str(background_music_path)]

        # -- filtergraph ------------------------------------------------
        video_filters: list[str] = []

        # Scale to target resolution, preserving aspect ratio with padding.
        video_filters.append(
            f"scale={config.width}:{config.height}:force_original_aspect_ratio=decrease"
        )
        video_filters.append(f"pad={config.width}:{config.height}:(ow-iw)/2:(oh-ih)/2:color=black")

        # Set frame rate.
        video_filters.append(f"fps={config.fps}")

        # Extend last video frame to cover full audio duration.
        # Use tpad with a generous fixed duration (120s) — the -t flag
        # on the output will trim to exact voiceover length.
        video_filters.append("tpad=stop_mode=clone:stop_duration=120")

        # Set pixel format.
        video_filters.append(f"format={config.pixel_format}")

        # Burn-in ASS subtitles.
        if captions_path is not None:
            escaped = str(captions_path).replace("\\", "/")
            escaped = escaped.replace(":", "\\:")
            escaped = escaped.replace("'", "'\\''")
            escaped = escaped.replace("[", "\\[")
            escaped = escaped.replace("]", "\\]")
            escaped = escaped.replace(";", "\\;")
            escaped = escaped.replace(",", "\\,")
            video_filters.append(f"subtitles='{escaped}'")

        video_chain = ",".join(video_filters)

        # -- audio filtergraph ------------------------------------------
        music_label_vc: str | None = "2:a" if has_music else None
        audio_filter_parts, audio_out_label = self._build_audio_filtergraph(
            voice_input_label="1:a",
            music_input_label=music_label_vc,
            audio_mix_config=audio_mix_config,
        )
        audio_filter_str = ";".join(audio_filter_parts)

        # Watermark overlay appended after the main video chain.
        video_final_label_vc = "vout"
        wm_segment_vc = self._build_watermark_filter(
            config=config,
            input_label="vout",
            output_label="vout_wm",
        )
        if wm_segment_vc is not None:
            full_filter = f"[0:v]{video_chain}[vout];{wm_segment_vc};{audio_filter_str}"
            video_final_label_vc = "vout_wm"
        else:
            full_filter = f"[0:v]{video_chain}[vout];{audio_filter_str}"

        cmd += ["-filter_complex", full_filter]
        cmd += ["-map", f"[{video_final_label_vc}]", "-map", f"[{audio_out_label}]"]

        # -- encoding ---------------------------------------------------
        cmd += [
            "-c:v",
            config.video_codec,
            "-preset",
            config.preset,
            "-b:v",
            config.video_bitrate,
            "-c:a",
            config.audio_codec,
            "-b:a",
            config.audio_bitrate,
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        return cmd

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _is_image(path: Path) -> bool:
        """Check if a path looks like an image file by extension."""
        return path.suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".bmp",
            ".tiff",
            ".tif",
        }

    # -- Video editing operations -------------------------------------------

    async def trim_video(
        self,
        input_path: Path,
        output_path: Path,
        *,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> Path:
        """Trim a video to the specified start/end times.

        Uses ``-ss`` / ``-to`` with re-encoding so filters and keyframes
        are clean.  Returns the output path.
        """
        cmd: list[str] = [self.ffmpeg_path, "-y"]

        if start_seconds is not None and start_seconds > 0:
            cmd += ["-ss", f"{start_seconds:.3f}"]

        cmd += ["-i", str(input_path)]

        if end_seconds is not None and end_seconds > 0:
            cmd += ["-to", f"{end_seconds - (start_seconds or 0):.3f}"]

        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-b:v",
            "4M",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        await self._run_ffmpeg(cmd, "trim_video")
        return output_path

    async def apply_video_effects(
        self,
        input_path: Path,
        output_path: Path,
        *,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        border_width: int = 0,
        border_color: str = "black",
        border_style: str = "solid",
        color_filter: str | None = None,
        speed: float = 1.0,
    ) -> Path:
        """Apply visual effects to a video and write the result.

        Supports: trimming, borders, colour grading presets, and speed
        adjustment.  All operations are chained in a single FFmpeg pass.
        """
        cmd: list[str] = [self.ffmpeg_path, "-y"]

        # Seek / trim on input
        if start_seconds is not None and start_seconds > 0:
            cmd += ["-ss", f"{start_seconds:.3f}"]
        cmd += ["-i", str(input_path)]
        if end_seconds is not None and end_seconds > 0:
            cmd += ["-to", f"{end_seconds - (start_seconds or 0):.3f}"]

        # Build video filter chain
        vf_parts: list[str] = []

        # -- Colour filter presets --
        colour_filters = {
            "warm": "colortemperature=temperature=7500",
            "cool": "colortemperature=temperature=4000",
            "bw": "hue=s=0",
            "vintage": "curves=vintage",
            "vivid": "eq=saturation=1.5:contrast=1.1",
            "dramatic": "eq=contrast=1.3:brightness=-0.05:saturation=0.8",
            "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
        }
        if color_filter and color_filter in colour_filters:
            vf_parts.append(colour_filters[color_filter])

        # -- Speed adjustment --
        if speed != 1.0:
            speed = max(0.25, min(4.0, speed))  # Clamp to sensible range
            vf_parts.append(f"setpts={1 / speed}*PTS")

        # -- Border / frame --
        if border_width > 0:
            # Ensure the border colour is valid for FFmpeg
            safe_color = border_color.lstrip("#") if border_color.startswith("#") else border_color
            if border_color.startswith("#"):
                safe_color = f"0x{safe_color}"

            if border_style == "glow":
                # Glow: pad with border, then apply a soft glow blur to the border area
                inner_w = 1080 - 2 * border_width
                inner_h = 1920 - 2 * border_width
                vf_parts.append(
                    f"scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease,"
                    f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color={safe_color}"
                )
            else:
                # Solid or rounded: shrink video and pad with border
                inner_w = 1080 - 2 * border_width
                inner_h = 1920 - 2 * border_width
                vf_parts.append(
                    f"scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease,"
                    f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color={safe_color}"
                )

                if border_style == "rounded":
                    # Draw rounded corners using geq (approximate with drawbox overlay)
                    corner_radius = min(border_width * 2, 40)
                    vf_parts.append(
                        f"drawbox=x=0:y=0:w={corner_radius}:h={corner_radius}:color={safe_color}:t=fill,"
                        f"drawbox=x=iw-{corner_radius}:y=0:w={corner_radius}:h={corner_radius}:color={safe_color}:t=fill,"
                        f"drawbox=x=0:y=ih-{corner_radius}:w={corner_radius}:h={corner_radius}:color={safe_color}:t=fill,"
                        f"drawbox=x=iw-{corner_radius}:y=ih-{corner_radius}:w={corner_radius}:h={corner_radius}:color={safe_color}:t=fill"
                    )

        # Audio speed
        af_parts: list[str] = []
        if speed != 1.0:
            af_parts.append(f"atempo={speed}")

        # Assemble command
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        if af_parts:
            cmd += ["-af", ",".join(af_parts)]

        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-b:v",
            "4M",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        await self._run_ffmpeg(cmd, "apply_video_effects")
        return output_path

    async def generate_preview(
        self,
        input_path: Path,
        output_path: Path,
        *,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        border_width: int = 0,
        border_color: str = "black",
        border_style: str = "solid",
        color_filter: str | None = None,
        speed: float = 1.0,
        max_duration: float = 10.0,
    ) -> Path:
        """Generate a fast low-quality preview of video edits.

        Uses low bitrate and fast preset for quick turnaround.
        """
        cmd: list[str] = [self.ffmpeg_path, "-y"]

        if start_seconds is not None and start_seconds > 0:
            cmd += ["-ss", f"{start_seconds:.3f}"]
        cmd += ["-i", str(input_path)]

        # Limit preview duration
        effective_end = end_seconds
        if effective_end is not None and start_seconds is not None:
            preview_dur = min(effective_end - start_seconds, max_duration)
        elif effective_end is not None:
            preview_dur = min(effective_end, max_duration)
        else:
            preview_dur = max_duration
        cmd += ["-t", f"{preview_dur:.3f}"]

        # Apply same effects pipeline but at lower quality
        vf_parts: list[str] = ["scale=540:960"]  # Half resolution for speed

        colour_filters = {
            "warm": "colortemperature=temperature=7500",
            "cool": "colortemperature=temperature=4000",
            "bw": "hue=s=0",
            "vintage": "curves=vintage",
            "vivid": "eq=saturation=1.5:contrast=1.1",
            "dramatic": "eq=contrast=1.3:brightness=-0.05:saturation=0.8",
            "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
        }
        if color_filter and color_filter in colour_filters:
            vf_parts.append(colour_filters[color_filter])

        if border_width > 0:
            hw = border_width // 2  # Half border for half-res preview
            safe_color = border_color.lstrip("#") if border_color.startswith("#") else border_color
            if border_color.startswith("#"):
                safe_color = f"0x{safe_color}"
            inner_w = 540 - 2 * hw
            inner_h = 960 - 2 * hw
            vf_parts.append(
                f"scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease,"
                f"pad=540:960:(ow-iw)/2:(oh-ih)/2:color={safe_color}"
            )

        if speed != 1.0:
            speed = max(0.25, min(4.0, speed))
            vf_parts.append(f"setpts={1 / speed}*PTS")

        af_parts: list[str] = []
        if speed != 1.0:
            af_parts.append(f"atempo={speed}")

        cmd += ["-vf", ",".join(vf_parts)]
        if af_parts:
            cmd += ["-af", ",".join(af_parts)]

        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-b:v",
            "500k",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        await self._run_ffmpeg(cmd, "generate_preview")
        return output_path
