"""TTS chunk synthesis helpers.

Extracted from ``_monolith.py`` as part of the round-3 audiobook service
decomposition.  The public surface consumed by ``AudiobookService`` is:

  * ``PROVIDER_CONCURRENCY`` — re-exported alias (tests import it from here
    and from the class)
  * ``_PROVIDER_SEMAPHORES`` — module-level registry (process-wide)
  * ``_provider_semaphore``  — lazily initialises and returns the semaphore
  * ``synthesize_chunk_with_retry``  — free-function TTS synthesis with retry
  * ``safety_filter_chunk``          — free-function peak-safety ffmpeg pass
  * ``generate_silence``             — free-function silence WAV generator
  * ``generate_single_voice``        — free-function single-speaker gather
  * ``generate_multi_voice``         — free-function multi-speaker gather

``AudiobookService`` shims in ``_monolith.py`` delegate to these helpers,
passing ``self.tts``, ``self._cancel``, etc. as explicit parameters so the
helpers themselves have no coupling to the class.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from drevalis.services.audiobook.chunking import _chunk_limit, _split_text

if TYPE_CHECKING:
    from drevalis.models.voice_profile import VoiceProfile
    from drevalis.services.tts import TTSService

log = structlog.get_logger(__name__)

# ── Per-provider TTS concurrency (Task 4) ────────────────────────────────────
# Within-chapter chunks used to render strictly sequentially even though most
# providers happily handle parallel requests. This map sets the per-provider
# in-flight cap; ElevenLabs is intentionally conservative (Creator plan = 2
# concurrent), Edge / Kokoro can take more, ComfyUI-routed SFX is serialised
# because the underlying ComfyUI pool already manages concurrency. Unknown
# providers default to 2 — safe for any cloud TTS.
#
# ELEVENLABS_CONCURRENCY env var overrides the ElevenLabs cap at lookup time
# so operators on Pro/Scale plans don't need a code change.
_DEFAULT_ELEVENLABS_CONCURRENCY = 2

# Re-exported as PROVIDER_CONCURRENCY so callers that import it by that name
# (tests, _monolith re-export) continue to work.
PROVIDER_CONCURRENCY: dict[str, int] = {
    "piper": 2,
    "kokoro": 4,
    "edge": 6,
    "comfyui_elevenlabs": 1,
    "elevenlabs": _DEFAULT_ELEVENLABS_CONCURRENCY,
}

# Module-level semaphore registry. Created lazily on first lookup so importing
# this module doesn't require a running event loop.
_PROVIDER_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _provider_concurrency(provider_name: str) -> int:
    """Return the in-flight cap for *provider_name* (case-insensitive).

    Substring match, longest-key-wins so ``ComfyUIElevenLabsProvider``
    binds to the ComfyUI cap rather than the plain ElevenLabs cap.
    Underscores are stripped on both sides because provider class
    names don't contain them but the keys are written for readability.
    Unknown providers fall back to 2 — safe for any cloud TTS.
    """
    name = provider_name.lower().replace("_", "")
    best: tuple[int, int] | None = None  # (key length, concurrency)
    for key, cap in PROVIDER_CONCURRENCY.items():
        normalised_key = key.replace("_", "")
        if normalised_key in name and (best is None or len(normalised_key) > best[0]):
            best = (len(normalised_key), cap)
    if best is not None:
        cap = best[1]
        # Env override applies only to the ElevenLabs cap.
        if "elevenlabs" in name and "comfyui" not in name:
            import os as _os

            override = _os.environ.get("ELEVENLABS_CONCURRENCY")
            if override and override.isdigit() and int(override) > 0:
                return int(override)
        return cap
    return 2


def _provider_semaphore(provider_name: str) -> asyncio.Semaphore:
    """Singleton ``asyncio.Semaphore`` for the provider's in-flight cap.

    Multiple ``AudiobookService`` instances share one rate budget per
    provider — the worker process is single-threaded async, so a
    process-wide semaphore is the natural unit for "ElevenLabs is at
    its rate limit" coordination.
    """
    name = provider_name.lower()
    sem = _PROVIDER_SEMAPHORES.get(name)
    if sem is None:
        sem = asyncio.Semaphore(_provider_concurrency(name))
        _PROVIDER_SEMAPHORES[name] = sem
    return sem


async def safety_filter_chunk(chunk_path: Path) -> None:
    """Run lightweight peak-safety filtering on the chunk, in place.

    Replaces the previous per-chunk EBU R128 loudnorm pass.  The new pass
    does only what's safe to apply at the chunk level:

      * ``aresample=24000`` — canonical 24 kHz mono PCM
      * ``highpass=f=60``   — kills sub-60 Hz rumble
      * ``alimiter=limit=0.95`` — clamps inter-sample peaks

    Failure here is non-fatal — the un-filtered chunk is better than no chunk.
    """
    tmp = chunk_path.with_suffix(".norm.wav")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(chunk_path),
        "-af",
        "aresample=24000,highpass=f=60,alimiter=limit=0.95",
        "-ar",
        "24000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(tmp),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 100:
        try:
            tmp.replace(chunk_path)
        except OSError as exc:
            log.warning(
                "audiobook.tts.safety_replace_failed",
                error=str(exc)[:120],
            )
            tmp.unlink(missing_ok=True)
    else:
        log.warning(
            "audiobook.tts.safety_filter_failed",
            rc=proc.returncode,
            stderr=err.decode("utf-8", errors="replace")[:200],
        )
        tmp.unlink(missing_ok=True)


async def synthesize_chunk_with_retry(
    provider: Any,
    text: str,
    voice_id: str,
    chunk_path: Path,
    *,
    speed: float,
    pitch: float,
    max_attempts: int = 3,
    cancel_fn: Any = None,
) -> bool:
    """Run ``provider.synthesize`` with bounded retry + post-loudnorm.

    Per-chunk retry isolates a single transient failure (cloud TTS 5xx,
    ComfyUI queue eviction, brief network blip) from torpedoing the whole
    chapter.

    After a successful synth, runs ``safety_filter_chunk`` on the chunk in
    place (24 kHz resample + highpass + alimiter).

    Returns True if a real audio file landed on disk; False if we exhausted
    retries (caller is expected to fall back to ``generate_silence`` so the
    timing structure stays intact).

    ``cancel_fn`` is an optional ``async def () -> None`` cancel-check
    coroutine that is awaited at the top of every retry iteration.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        if cancel_fn is not None:
            await cancel_fn()
        try:
            await provider.synthesize(
                text,
                voice_id,
                chunk_path,
                speed=speed,
                pitch=pitch,
            )
            if chunk_path.exists() and chunk_path.stat().st_size > 100:
                await safety_filter_chunk(chunk_path)
                if attempt > 1:
                    log.info(
                        "audiobook.tts.chunk_recovered",
                        attempt=attempt,
                        chunk_path=str(chunk_path),
                    )
                return True
            last_exc = RuntimeError("Provider returned but no audio file was written")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        if attempt < max_attempts:
            delay = min(0.5 * (2 ** (attempt - 1)), 5.0)
            log.warning(
                "audiobook.tts.chunk_retry",
                attempt=attempt,
                next_delay=delay,
                error=f"{type(last_exc).__name__}: {str(last_exc)[:160]}",
            )
            await asyncio.sleep(delay)

    log.error(
        "audiobook.tts.chunk_exhausted",
        max_attempts=max_attempts,
        chunk_path=str(chunk_path),
        error=f"{type(last_exc).__name__}: {str(last_exc)[:200]}" if last_exc else "unknown",
    )
    return False


async def generate_silence(output_path: Path, duration: float = 0.5) -> None:
    """Generate a short silence WAV file as a TTS fallback."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=24000:cl=mono",
        "-t",
        str(duration),
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


def _chunk_cache_hash_import() -> Any:
    """Lazy import to avoid circular imports at module load time."""
    from drevalis.services.audiobook._monolith import _chunk_cache_hash, _provider_identity

    return _chunk_cache_hash, _provider_identity


async def generate_single_voice(
    *,
    tts_service: TTSService,
    text: str,
    voice_profile: VoiceProfile,
    output_dir: Path,
    chapter_index: int,
    speed: float,
    pitch: float,
    cancel_fn: Any = None,
) -> list[Any]:
    """Generate TTS for a single voice, splitting text into chunks.

    Chunks render concurrently up to the per-provider cap from
    ``PROVIDER_CONCURRENCY``. Cache hits short-circuit before the semaphore
    so they don't burn a slot.

    Returns a list of ``AudioChunk`` instances sorted by ``chunk_index``.
    ``AudioChunk`` is imported lazily to avoid circular references at module
    load time.
    """
    from drevalis.services.audiobook._monolith import (
        AudioChunk,
        _chunk_cache_hash,
        _provider_identity,
    )

    provider = tts_service.get_provider(voice_profile)
    voice_id = tts_service._voice_id_for(voice_profile)
    provider_name, model_name = _provider_identity(provider, voice_profile)
    voice_profile_id = str(getattr(voice_profile, "id", "") or "")
    sem = _provider_semaphore(provider_name)
    max_chars = _chunk_limit(provider_name)

    chunks = _split_text(text, max_chars=max_chars)

    async def _render_chunk(i: int, text_chunk: str) -> AudioChunk | None:
        stripped = text_chunk.strip()
        if not stripped or len(stripped) < 2:
            return None

        chunk_hash = _chunk_cache_hash(
            text=text_chunk,
            speaker_id="Narrator",
            voice_profile_id=voice_profile_id,
            provider=provider_name,
            model=model_name,
            speed=speed,
            pitch=pitch,
            sample_rate=24000,
        )
        chunk_path = output_dir / f"ch{chapter_index:03d}_chunk_{i:04d}_{chunk_hash}.wav"
        if chunk_path.exists() and chunk_path.stat().st_size > 100:
            log.debug(
                "audiobook.generate.chunk_cached",
                chapter_index=chapter_index,
                chunk_index=i,
            )
        else:
            async with sem:
                ok = await synthesize_chunk_with_retry(
                    provider,
                    text_chunk,
                    voice_id,
                    chunk_path,
                    speed=speed,
                    pitch=pitch,
                    cancel_fn=cancel_fn,
                )
            if not ok:
                log.warning(
                    "audiobook.generate.tts_chunk_failed",
                    chapter_index=chapter_index,
                    chunk_index=i,
                    chunk_length=len(text_chunk),
                )
                await generate_silence(chunk_path)

        if not chunk_path.exists():
            return None
        return AudioChunk(
            path=chunk_path,
            chapter_index=chapter_index,
            speaker="Narrator",
            block_index=0,
            chunk_index=i,
        )

    outcomes = await asyncio.gather(
        *(_render_chunk(i, c) for i, c in enumerate(chunks)),
        return_exceptions=True,
    )

    for outcome in outcomes:
        if isinstance(outcome, asyncio.CancelledError):
            raise outcome

    result: list[Any] = []
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            log.warning(
                "audiobook.generate.chunk_exception",
                chapter_index=chapter_index,
                error=f"{type(outcome).__name__}: {str(outcome)[:160]}",
            )
        elif outcome is not None:
            result.append(outcome)
    result.sort(key=lambda c: c.chunk_index)
    return result


async def generate_multi_voice(
    *,
    tts_service: TTSService,
    blocks: list[dict[str, Any]],
    voice_casting: dict[str, str],
    default_voice_profile: VoiceProfile,
    output_dir: Path,
    chapter_index: int,
    speed: float,
    pitch: float,
    cancel_fn: Any = None,
    get_voice_profile_fn: Any = None,
    generate_sfx_chunk_fn: Any = None,
) -> list[Any]:
    """Generate TTS for each speaker block with their assigned voice.

    Falls back to the default voice profile for speakers not in the casting
    map.

    ``get_voice_profile_fn`` is ``async def (id: str) -> VoiceProfile | None``
    supplied by the caller (``AudiobookService._get_voice_profile``).

    ``generate_sfx_chunk_fn`` is ``async def (block, output_dir, chapter_index,
    block_index) -> AudioChunk | None`` supplied by the caller.
    """
    from drevalis.services.audiobook._monolith import (
        AudioChunk,
        _chunk_cache_hash,
        _provider_identity,
    )

    def _normalise_speaker(name: str) -> str:
        import re as _re

        return _re.sub(r"[^a-z0-9]+", "", name.strip().lower())

    normalised_cast: dict[str, str] = {
        _normalise_speaker(k): v for k, v in voice_casting.items() if k
    }

    result: list[Any] = []

    for i, block in enumerate(blocks):
        if block.get("kind") == "sfx":
            if generate_sfx_chunk_fn is not None:
                sfx_chunk = await generate_sfx_chunk_fn(
                    block=block,
                    output_dir=output_dir,
                    chapter_index=chapter_index,
                    block_index=i,
                )
                if sfx_chunk is not None:
                    result.append(sfx_chunk)
            continue

        speaker = block["speaker"]
        voice_profile_id = (
            voice_casting.get(speaker)
            or voice_casting.get(speaker.strip())
            or normalised_cast.get(_normalise_speaker(speaker))
        )

        voice_profile: Any = default_voice_profile
        if voice_profile_id:
            if get_voice_profile_fn is not None:
                loaded = await get_voice_profile_fn(voice_profile_id)
                if loaded is None:
                    log.warning(
                        "audiobook.generate.voice_profile_not_found",
                        speaker=speaker,
                        voice_profile_id=voice_profile_id,
                        detail="Falling back to default voice profile",
                    )
                else:
                    voice_profile = loaded

        provider = tts_service.get_provider(voice_profile)
        voice_id = tts_service._voice_id_for(voice_profile)
        provider_name, model_name = _provider_identity(provider, voice_profile)
        voice_profile_id_str = str(getattr(voice_profile, "id", "") or "")
        sem = _provider_semaphore(provider_name)
        max_chars = _chunk_limit(provider_name)

        text_chunks = _split_text(block["text"], max_chars=max_chars)

        async def _render_block_chunk(
            j: int,
            text_chunk: str,
            _block_index: int = i,
            _speaker: str = speaker,
            _provider: Any = provider,
            _voice_id: str = voice_id,
            _provider_name: str = provider_name,
            _model_name: str = model_name,
            _voice_profile_id_str: str = voice_profile_id_str,
            _sem: asyncio.Semaphore = sem,
        ) -> AudioChunk | None:
            stripped = text_chunk.strip()
            if not stripped or len(stripped) < 2:
                return None

            chunk_hash = _chunk_cache_hash(
                text=text_chunk,
                speaker_id=_speaker,
                voice_profile_id=_voice_profile_id_str,
                provider=_provider_name,
                model=_model_name,
                speed=speed,
                pitch=pitch,
                sample_rate=24000,
            )
            chunk_path = (
                output_dir / f"ch{chapter_index:03d}_block_{_block_index:04d}"
                f"_chunk_{j:04d}_{chunk_hash}.wav"
            )
            if chunk_path.exists() and chunk_path.stat().st_size > 100:
                log.debug(
                    "audiobook.generate.chunk_cached",
                    chapter_index=chapter_index,
                    block_index=_block_index,
                    chunk_index=j,
                )
            else:
                async with _sem:
                    ok = await synthesize_chunk_with_retry(
                        _provider,
                        text_chunk,
                        _voice_id,
                        chunk_path,
                        speed=speed,
                        pitch=pitch,
                        cancel_fn=cancel_fn,
                    )
                if not ok:
                    log.warning(
                        "audiobook.generate.tts_chunk_failed",
                        chapter_index=chapter_index,
                        block_index=_block_index,
                        speaker=_speaker,
                        chunk_index=j,
                        chunk_length=len(text_chunk),
                    )
                    await generate_silence(chunk_path)

            if not chunk_path.exists():
                return None
            return AudioChunk(
                path=chunk_path,
                chapter_index=chapter_index,
                speaker=_speaker,
                block_index=_block_index,
                chunk_index=j,
            )

        block_outcomes = await asyncio.gather(
            *(_render_block_chunk(j, c) for j, c in enumerate(text_chunks)),
            return_exceptions=True,
        )

        for outcome in block_outcomes:
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome

        block_chunks: list[Any] = []
        for outcome in block_outcomes:
            if isinstance(outcome, AudioChunk):
                block_chunks.append(outcome)
            elif isinstance(outcome, Exception):
                log.warning(
                    "audiobook.generate.chunk_exception",
                    chapter_index=chapter_index,
                    block_index=i,
                    error=f"{type(outcome).__name__}: {str(outcome)[:160]}",
                )
        block_chunks.sort(key=lambda c: c.chunk_index)
        result.extend(block_chunks)

    return result
