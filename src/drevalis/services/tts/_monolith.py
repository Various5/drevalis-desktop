"""TTS service with protocol-based provider abstraction.

Supports four backends:
- **PiperTTSProvider** -- local ONNX-based TTS via the ``piper`` CLI.
- **ElevenLabsTTSProvider** -- cloud TTS via the ElevenLabs REST API.
- **KokoroTTSProvider** -- local high-quality ONNX-based TTS via Kokoro.
- **EdgeTTSProvider** -- cloud-quality TTS via Microsoft Edge neural voices (free, no API key).

``TTSService`` is the high-level entry-point used by the generation
pipeline.  It resolves the correct provider from a ``VoiceProfile`` ORM
object and produces a single WAV voiceover for an entire episode script.
"""

from __future__ import annotations

import asyncio
import json
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

import httpx
import structlog

if TYPE_CHECKING:
    from drevalis.models.voice_profile import VoiceProfile
    from drevalis.schemas.script import EpisodeScript

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WordTimestamp:
    """A single word with its start/end time in seconds."""

    word: str
    start_seconds: float
    end_seconds: float


@dataclass
class TTSResult:
    """Result of a TTS synthesis call."""

    audio_path: str  # relative to storage base
    duration_seconds: float
    sample_rate: int
    word_timestamps: list[WordTimestamp] | None = None


@dataclass
class VoiceInfo:
    """Descriptor for an available voice."""

    voice_id: str
    name: str
    language: str
    provider: str


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class TTSProvider(Protocol):
    """Minimal interface every TTS backend must satisfy."""

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        *,
        speed: float = 1.0,
        pitch: float = 1.0,
    ) -> TTSResult: ...

    async def list_voices(self) -> list[VoiceInfo]: ...


# ---------------------------------------------------------------------------
# Piper (local) provider
# ---------------------------------------------------------------------------


class PiperTTSProvider:
    """Local TTS using Piper (ONNX-based).

    Piper is invoked as a subprocess::

        echo "<text>" | piper --model <model.onnx> --output_file <out.wav> --json

    The ``--json`` flag causes Piper to emit a JSON object per input line
    on *stdout* containing phoneme-level timestamps when the model
    supports it.
    """

    def __init__(self, models_path: Path, piper_executable: str = "piper") -> None:
        self.models_path = models_path
        self.piper_executable = piper_executable

    # -- public interface ---------------------------------------------------

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        *,
        speed: float = 1.0,
        pitch: float = 1.0,
    ) -> TTSResult:
        model_path = self._resolve_model(voice_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.piper_executable,
            "--model",
            str(model_path),
            "--output_file",
            str(output_path),
            "--length_scale",
            str(1.0 / speed),
            "--json",
        ]

        log.debug("piper.synthesize.start", command=cmd, text_length=len(text))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate(input=text.encode("utf-8"))

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            log.error(
                "piper.synthesize.failed",
                return_code=proc.returncode,
                stderr=stderr_text,
            )
            raise RuntimeError(f"Piper exited with code {proc.returncode}: {stderr_text}")

        if not output_path.exists():
            raise FileNotFoundError(f"Piper did not produce output file: {output_path}")

        # Parse word-level timestamps from JSON stdout when available.
        word_timestamps = self._parse_piper_json(stdout_bytes)

        duration, sample_rate = _wav_info(output_path)

        log.info(
            "piper.synthesize.done",
            voice_id=voice_id,
            duration_seconds=duration,
            sample_rate=sample_rate,
        )

        return TTSResult(
            audio_path=str(output_path),
            duration_seconds=duration,
            sample_rate=sample_rate,
            word_timestamps=word_timestamps,
        )

    async def list_voices(self) -> list[VoiceInfo]:
        voices: list[VoiceInfo] = []
        if not self.models_path.exists():
            log.warning("piper.models_path.missing", path=str(self.models_path))
            return voices

        for onnx_file in sorted(self.models_path.glob("*.onnx")):
            config_file = onnx_file.with_suffix(".onnx.json")
            language = "en"
            if config_file.exists():
                try:
                    cfg = json.loads(config_file.read_text(encoding="utf-8"))
                    language = cfg.get("language", {}).get("code", "en")
                except (json.JSONDecodeError, KeyError):
                    pass

            voices.append(
                VoiceInfo(
                    voice_id=onnx_file.stem,
                    name=onnx_file.stem.replace("-", " ").replace("_", " ").title(),
                    language=language,
                    provider="piper",
                )
            )
        return voices

    # -- private helpers ----------------------------------------------------

    @staticmethod
    def _sanitize_voice_id(voice_id: str) -> str:
        """Sanitize voice_id to prevent path traversal.

        Only allows alphanumeric characters, hyphens, underscores, and dots.
        Rejects any path separators or '..' sequences.
        """
        import re

        if ".." in voice_id or "/" in voice_id or "\\" in voice_id:
            raise ValueError(
                f"Invalid voice_id: must not contain path separators or '..': {voice_id!r}"
            )
        if not re.match(r"^[a-zA-Z0-9._-]+$", voice_id):
            raise ValueError(f"Invalid voice_id: contains disallowed characters: {voice_id!r}")
        return voice_id

    def _resolve_model(self, voice_id: str) -> Path:
        """Return the full path to a ``.onnx`` model file."""
        voice_id = self._sanitize_voice_id(voice_id)

        model = self.models_path / f"{voice_id}.onnx"
        if not model.exists():
            # Also try treating voice_id as a filename within models_path.
            model = self.models_path / voice_id
        if not model.exists():
            raise FileNotFoundError(f"Piper model not found for voice_id={voice_id!r}")

        # Final containment check: ensure resolved path is within models_path
        resolved = model.resolve()
        models_resolved = self.models_path.resolve()
        try:
            resolved.relative_to(models_resolved)
        except ValueError:
            raise ValueError(
                f"Resolved model path escapes the models directory for voice_id={voice_id!r}"
            ) from None

        return model

    @staticmethod
    def _parse_piper_json(stdout_bytes: bytes) -> list[WordTimestamp] | None:
        """Parse Piper ``--json`` output into ``WordTimestamp`` objects.

        Piper emits one JSON line per input line.  Each line may contain a
        ``word_phonemes`` array whose entries carry word text and start/end
        times in *seconds*.  If the output cannot be parsed we silently
        return ``None`` rather than failing the whole synthesis.
        """
        if not stdout_bytes.strip():
            return None

        timestamps: list[WordTimestamp] = []
        try:
            for raw_line in stdout_bytes.decode("utf-8").strip().splitlines():
                data = json.loads(raw_line)
                # Piper JSON output structure varies by version.  We try
                # several known keys.
                words_data = data.get("word_phonemes") or data.get("words") or []
                for entry in words_data:
                    word = entry.get("word") or entry.get("text", "")
                    start = float(entry.get("start", entry.get("start_seconds", 0)))
                    end = float(entry.get("end", entry.get("end_seconds", 0)))
                    if word:
                        timestamps.append(
                            WordTimestamp(word=word, start_seconds=start, end_seconds=end)
                        )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            log.debug("piper.json_parse.skipped", reason="unrecognised format")
            return None

        return timestamps if timestamps else None


# ---------------------------------------------------------------------------
# Kokoro (local, high-quality) provider
# ---------------------------------------------------------------------------


class KokoroTTSProvider:
    """Local TTS using Kokoro (high-quality ONNX-based).

    Kokoro produces natural-sounding speech at 24 kHz.  The heavy
    generation work is offloaded to a thread pool via
    ``asyncio.to_thread`` so the event loop stays responsive.

    The ``kokoro`` package is an optional dependency -- if it is not
    installed the provider will raise ``RuntimeError`` on first use
    rather than at import time.
    """

    def __init__(self, models_path: Path) -> None:
        self.models_path = models_path
        self._pipeline: object | None = None  # lazy init

    # -- lazy pipeline loader -----------------------------------------------

    def _get_pipeline(self) -> object:
        """Lazy-load the Kokoro pipeline.

        Returns the ``KPipeline`` instance.  Raises ``RuntimeError`` if
        the ``kokoro`` package is not installed.
        """
        if self._pipeline is None:
            try:
                from kokoro import KPipeline

                self._pipeline = KPipeline(lang_code="a")  # 'a' = American English
            except ImportError:
                raise RuntimeError(
                    "Kokoro TTS is not installed. Install with: pip install kokoro soundfile"
                ) from None
        return self._pipeline

    # -- public interface ---------------------------------------------------

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        *,
        speed: float = 1.0,
        pitch: float = 1.0,
    ) -> TTSResult:
        """Synthesize speech using Kokoro.

        The generation itself is CPU-bound, so we run it inside
        ``asyncio.to_thread``.  The output is a 24 kHz WAV file.
        """
        pipeline = self._get_pipeline()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        log.debug(
            "kokoro.synthesize.start",
            voice_id=voice_id,
            text_length=len(text),
        )

        def _generate() -> tuple[object, int, list[WordTimestamp]]:
            try:
                import numpy as np  # used on line ~382 to concat chunk samples
                import soundfile as sf
            except ImportError as exc:
                raise RuntimeError(
                    "Kokoro TTS requires numpy + soundfile. "
                    "Install with: pip install soundfile numpy"
                ) from exc

            samples: list[Any] = []
            word_timestamps: list[WordTimestamp] = []
            current_time = 0.0

            for result in pipeline(text, voice=voice_id, speed=speed):  # type: ignore[operator]
                audio = result.audio
                sr = 24000  # Kokoro outputs at 24 kHz
                duration = len(audio) / sr

                # Try to extract word-level timestamps when the API
                # exposes token-level timing information.
                if hasattr(result, "tokens") and result.tokens:
                    for token in result.tokens:
                        token_text = getattr(token, "text", "")
                        if isinstance(token_text, str) and token_text.strip():
                            start_t = current_time + getattr(token, "start_time", 0.0)
                            end_t = current_time + getattr(token, "end_time", duration)
                            word_timestamps.append(
                                WordTimestamp(
                                    word=token_text.strip(),
                                    start_seconds=start_t,
                                    end_seconds=end_t,
                                )
                            )

                samples.append(audio)
                current_time += duration

            if not samples:
                raise RuntimeError("Kokoro produced no audio output")

            full_audio: Any = np.concatenate(samples)
            sf.write(str(output_path), full_audio, 24000)

            return full_audio, 24000, word_timestamps

        audio, sample_rate, word_timestamps = await asyncio.to_thread(_generate)

        duration = len(audio) / sample_rate  # type: ignore[arg-type]

        log.info(
            "kokoro.synthesize.done",
            voice_id=voice_id,
            duration_seconds=duration,
            sample_rate=sample_rate,
        )

        return TTSResult(
            audio_path=str(output_path),
            duration_seconds=duration,
            sample_rate=sample_rate,
            word_timestamps=word_timestamps or None,
        )

    async def list_voices(self) -> list[VoiceInfo]:
        """Return available Kokoro voice presets.

        This is a static list of the well-known built-in voices
        shipped with Kokoro.
        """
        kokoro_voices = [
            ("af_heart", "Heart (American Female)", "en"),
            ("af_alloy", "Alloy (American Female)", "en"),
            ("af_aoede", "Aoede (American Female)", "en"),
            ("am_michael", "Michael (American Male)", "en"),
            ("am_fenrir", "Fenrir (American Male)", "en"),
            ("bf_emma", "Emma (British Female)", "en"),
            ("bm_george", "George (British Male)", "en"),
        ]
        return [
            VoiceInfo(voice_id=vid, name=name, language=lang, provider="kokoro")
            for vid, name, lang in kokoro_voices
        ]


# ---------------------------------------------------------------------------
# ElevenLabs (cloud) provider
# ---------------------------------------------------------------------------


_ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


class ElevenLabsTTSProvider:
    """Cloud TTS using the ElevenLabs REST API.

    The provider uses ``httpx.AsyncClient`` for all HTTP communication.
    """

    def __init__(
        self,
        api_key: str,
        model_id: str = "eleven_monolingual_v1",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ) -> None:
        self.api_key = api_key
        self.model_id = model_id
        self.stability = stability
        self.similarity_boost = similarity_boost
        self._client: httpx.AsyncClient | None = None

    # -- HTTP client lifecycle ----------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=_ELEVENLABS_BASE,
                headers={
                    "xi-api-key": self.api_key,
                    "Accept": "audio/mpeg",
                },
                timeout=httpx.Timeout(120.0, connect=15.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def upload_voice_sample(
        self,
        *,
        name: str,
        sample_path: Path,
        description: str | None = None,
    ) -> str:
        """Upload an audio sample via ElevenLabs Instant Voice Cloning.

        Returns the new ``voice_id`` on success. Requires an IVC-enabled
        plan; raises ``httpx.HTTPStatusError`` on API rejection so the
        caller can surface a useful message.
        """
        client = self._get_client()
        # /voices/add uses multipart/form-data, but the shared client
        # expects JSON — issue a one-off request using the underlying
        # transport so we don't disturb the Accept/content-type defaults.
        with sample_path.open("rb") as fh:
            files = {"files": (sample_path.name, fh, "audio/mpeg")}
            data = {"name": name}
            if description:
                data["description"] = description
            # Override Accept for this request — the API returns JSON here.
            r = await client.post(
                "/voices/add",
                files=files,
                data=data,
                headers={"Accept": "application/json"},
            )
        r.raise_for_status()
        body = r.json()
        voice_id = body.get("voice_id")
        if not voice_id:
            raise ValueError(f"unexpected IVC response shape: {body!r}")
        return str(voice_id)

    # -- public interface ---------------------------------------------------

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        *,
        speed: float = 1.0,
        pitch: float = 1.0,
    ) -> TTSResult:
        client = self._get_client()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": self.stability,
                "similarity_boost": self.similarity_boost,
            },
        }

        log.debug(
            "elevenlabs.synthesize.start",
            voice_id=voice_id,
            text_length=len(text),
        )

        # -- audio synthesis ------------------------------------------------
        # Honour ElevenLabs' rate-limit / upstream-overload responses
        # via request_with_retry so a single 429 no longer flips the
        # whole pipeline step to "failed".
        from drevalis.core.http_retry import request_with_retry

        resp = await request_with_retry(
            client,
            "POST",
            f"/text-to-speech/{voice_id}",
            json=payload,
            headers={"Accept": "audio/mpeg"},
            label="elevenlabs.tts",
        )
        if resp.status_code != 200:
            body = resp.text
            log.error(
                "elevenlabs.synthesize.failed",
                status=resp.status_code,
                body=body[:500],
            )
            raise RuntimeError(f"ElevenLabs TTS failed ({resp.status_code}): {body[:300]}")

        output_path.write_bytes(resp.content)

        # -- word-level timestamps via alignment endpoint -------------------
        word_timestamps = await self._fetch_alignment(client, text, voice_id)

        # Determine duration.  For MP3 we fall back to a rough estimate
        # based on file size and bitrate.
        duration = _estimate_mp3_duration(output_path)

        log.info(
            "elevenlabs.synthesize.done",
            voice_id=voice_id,
            duration_seconds=duration,
            file_size=output_path.stat().st_size,
        )

        return TTSResult(
            audio_path=str(output_path),
            duration_seconds=duration,
            sample_rate=44100,  # ElevenLabs default
            word_timestamps=word_timestamps,
        )

    async def list_voices(self) -> list[VoiceInfo]:
        client = self._get_client()
        resp = await client.get(
            "/voices",
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            log.error("elevenlabs.list_voices.failed", status=resp.status_code)
            raise RuntimeError(f"ElevenLabs list voices failed ({resp.status_code})")

        data = resp.json()
        voices: list[VoiceInfo] = []
        for v in data.get("voices", []):
            labels = v.get("labels", {})
            language = labels.get("language", "en")
            voices.append(
                VoiceInfo(
                    voice_id=v["voice_id"],
                    name=v.get("name", v["voice_id"]),
                    language=language,
                    provider="elevenlabs",
                )
            )
        return voices

    # -- private helpers ----------------------------------------------------

    async def _fetch_alignment(
        self, client: httpx.AsyncClient, text: str, voice_id: str
    ) -> list[WordTimestamp] | None:
        """Attempt to fetch word-level timestamps from the alignment endpoint.

        This is a best-effort operation; if it fails we simply return
        ``None`` so the caller can fall back to Whisper-based alignment.
        """
        try:
            resp = await client.post(
                f"/text-to-speech/{voice_id}/with-timestamps",
                json={
                    "text": text,
                    "model_id": self.model_id,
                    "voice_settings": {
                        "stability": self.stability,
                        "similarity_boost": self.similarity_boost,
                    },
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                log.debug(
                    "elevenlabs.alignment.unavailable",
                    status=resp.status_code,
                )
                return None

            data = resp.json()
            alignment = data.get("alignment") or {}
            characters = alignment.get("characters", [])
            char_starts = alignment.get("character_start_times_seconds", [])
            char_ends = alignment.get("character_end_times_seconds", [])

            if not characters or len(characters) != len(char_starts):
                return None

            # Reconstruct word-level timestamps from character data.
            return _chars_to_words(characters, char_starts, char_ends)

        except Exception:
            log.debug("elevenlabs.alignment.error", exc_info=True)
            return None


# ---------------------------------------------------------------------------
# Edge TTS (cloud, free) provider
# ---------------------------------------------------------------------------


class EdgeTTSProvider:
    """Cloud-quality TTS via Microsoft Edge neural voices (free, no API key).

    Uses the ``edge-tts`` package to stream audio and word-level timestamps
    from Microsoft's neural TTS service.  The output is converted from MP3
    to WAV via FFmpeg so the rest of the pipeline receives a consistent
    format.

    Requires internet connectivity -- errors are raised rather than
    silently swallowed so the pipeline can surface them clearly.
    """

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        *,
        speed: float = 1.0,
        pitch: float = 1.0,
    ) -> TTSResult:
        try:
            import edge_tts
        except ImportError:
            raise RuntimeError(
                "edge-tts is not installed. Install with: pip install edge-tts"
            ) from None

        rate_str = f"{int((speed - 1) * 100):+d}%"
        pitch_str = f"{int((pitch - 1) * 50):+d}Hz"
        communicate = edge_tts.Communicate(text, voice_id, rate=rate_str, pitch=pitch_str)

        mp3_path = output_path.with_suffix(".mp3")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        log.debug(
            "edge.synthesize.start",
            voice_id=voice_id,
            text_length=len(text),
        )

        word_timestamps: list[WordTimestamp] = []
        audio_chunks: list[bytes] = []

        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    word_timestamps.append(
                        WordTimestamp(
                            word=chunk["text"],
                            start_seconds=chunk["offset"] / 10_000_000,
                            end_seconds=(chunk["offset"] + chunk["duration"]) / 10_000_000,
                        )
                    )
        except Exception as exc:
            log.error("edge.synthesize.stream_failed", error=str(exc), exc_info=True)
            raise RuntimeError(f"Edge TTS streaming failed (requires internet): {exc}") from exc

        # Write MP3
        with open(mp3_path, "wb") as f:
            for c in audio_chunks:
                f.write(c)

        # Convert MP3 -> WAV via ffmpeg (pipeline expects WAV)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(mp3_path),
            "-ar",
            "24000",
            "-ac",
            "1",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")
            log.error("edge.synthesize.ffmpeg_failed", stderr=stderr_text[:500])
            raise RuntimeError(f"FFmpeg MP3->WAV conversion failed: {stderr_text[:300]}")

        mp3_path.unlink(missing_ok=True)

        # Get duration from WAV and verify sample rate
        duration, sample_rate = _wav_info(output_path)

        if sample_rate != 24000:
            log.warning(
                "edge.synthesize.unexpected_sample_rate",
                expected=24000,
                actual=sample_rate,
                path=str(output_path),
            )

        log.info(
            "edge.synthesize.done",
            voice_id=voice_id,
            duration_seconds=duration,
            sample_rate=sample_rate,
            word_count=len(word_timestamps),
        )

        return TTSResult(
            audio_path=str(output_path),
            duration_seconds=duration,
            sample_rate=sample_rate,
            word_timestamps=word_timestamps or None,
        )

    async def list_voices(self) -> list[VoiceInfo]:
        """Return available English Edge TTS voices."""
        try:
            import edge_tts
        except ImportError:
            log.warning("edge.list_voices.not_installed")
            return []

        try:
            voices = await edge_tts.list_voices()
        except Exception:
            log.warning("edge.list_voices.failed", exc_info=True)
            return []

        return [
            VoiceInfo(
                voice_id=v["ShortName"],
                name=v["FriendlyName"],
                language=v["Locale"],
                provider="edge",
            )
            for v in voices
            if v["Locale"].startswith("en")
        ]


# ---------------------------------------------------------------------------
# ComfyUI ElevenLabs provider (cloud via ComfyUI nodes)
# ---------------------------------------------------------------------------

# Surfaced when the ElevenLabs API node returns
# ``Unauthorized: Please login first to use this node.``
# Two distinct ComfyUI-Org credentials exist; the user has to put
# the *right one* in the right place:
#   - ``api_key_comfy_org``   long-lived string, ``comfyui-XXX…``
#                             form. Issued from comfy.org dashboard
#                             → "API Keys" → Create. Tied to the
#                             account's credit balance.
#   - ``auth_token_comfy_org`` short-lived JWT (3 dot-separated
#                             base64 segments). Issued by Google
#                             SSO; rotates hourly. Browser-session
#                             only — not usable from a worker.
# v0.23.5 auto-detects the token shape and only sends it as the
# matching field; sending both as the same string actively breaks
# auth when the node validates the wrong one first.
_AUTH_HINT = (
    "ComfyUI API node refused authentication: {raw}. "
    "Most common cause: the token in Settings → ComfyUI Servers → "
    "API Key is not the same identity that holds the credits. "
    "Action: at https://platform.comfy.org → Account → API Keys, "
    "create a NEW api key while logged in with the SAME account "
    "that has credits, copy the ``comfyui-XXX...`` value, paste it "
    "into the API Key field, save, retry. If that still fails the "
    "key may need its own credit topup (some accounts pool credits, "
    "some require per-key topups — check the dashboard)."
)


def _classify_comfyui_token(token: str) -> str:
    """Decide whether a token looks like an ``api_key_comfy_org``
    (long-lived dashboard key) or an ``auth_token_comfy_org`` (JWT).

    Returns one of: ``"api_key"``, ``"auth_token"``, ``"unknown"``.
    """
    if not token:
        return "unknown"
    s = token.strip()
    # JWT shape: three base64url segments separated by dots, each
    # at least 5 chars, often starting with eyJ...
    if s.count(".") == 2 and s.startswith("eyJ"):
        return "auth_token"
    # ComfyUI api keys conventionally have a ``comfyui-`` /
    # ``comfy-`` prefix. Accept anything else without dots as a key.
    if s.startswith(("comfyui-", "comfy-")):
        return "api_key"
    if "." not in s and len(s) >= 16:
        return "api_key"
    return "unknown"


def build_comfyui_auth_extra_data(token: str | None) -> dict[str, str]:
    """Build the ``extra_data`` dict for a ComfyUI ``/prompt``.

    Only inserts the field whose shape the token matches, so the
    node's auth check doesn't fail on the wrong-shape value and
    short-circuit before ever looking at the right one. When the
    shape is ambiguous, sends both (same as v0.23.3) — better than
    sending neither.
    """
    if not token:
        return {}
    kind = _classify_comfyui_token(token)
    if kind == "api_key":
        return {"api_key_comfy_org": token}
    if kind == "auth_token":
        return {"auth_token_comfy_org": token}
    # Unknown shape — fall back to sending both so SOMETHING gets
    # through. Logged at the call site so the operator can tell.
    return {"api_key_comfy_org": token, "auth_token_comfy_org": token}


class ComfyUIElevenLabsTTSProvider:
    """ElevenLabs TTS routed through ComfyUI custom nodes.

    Uses the ``ElevenLabsVoiceSelector`` + ``ElevenLabsTextToDialogue`` +
    ``SaveAudioMP3`` nodes installed in ComfyUI.  The ElevenLabs API key
    is managed on the ComfyUI side, so no key is needed here.

    The ``voice_id`` parameter is the full ElevenLabs voice name as shown
    in ComfyUI (e.g. ``"Roger (male, american)"``).
    """

    def __init__(
        self,
        comfyui_base_url: str = "http://localhost:8188",
        comfyui_api_key: str | None = None,
        model: str = "eleven_v3",
        stability: float = 0.5,
        output_format: str = "mp3_44100_192",
        extra_servers: list[tuple[str, str | None]] | None = None,
    ) -> None:
        # Build server list: (url, api_key) tuples for round-robin
        self._servers: list[tuple[str, str | None]] = [(comfyui_base_url, comfyui_api_key)]
        if extra_servers:
            self._servers.extend(extra_servers)
        self._server_index = 0
        # Keep these for backwards compat with logging
        self.comfyui_base_url = comfyui_base_url
        self.comfyui_api_key = comfyui_api_key
        self.model = model
        self.stability = stability
        self.output_format = output_format

    def _build_workflow(self, text: str, voice_name: str) -> dict[str, Any]:
        """Build a ComfyUI workflow for ElevenLabs TTS.

        Note on the unusual parameter names: the
        ``ElevenLabsTextToDialogue`` node accepts a numeric
        ``inputs`` count plus dotted keys (``inputs.text1``,
        ``inputs.voice1``, ``inputs.text2``, ...) — that's the
        node's actual signature, not a widget-export artifact. An
        earlier "cleanup" to plain ``text``/``voice`` field names
        broke runs with:

            ElevenLabsTextToDialogue.execute() got an
            unexpected keyword argument 'voice'

        Stick with the documented dotted-key schema.
        """
        return {
            "1": {
                "inputs": {"voice": voice_name},
                "class_type": "ElevenLabsVoiceSelector",
                "_meta": {"title": "ElevenLabs Voice Selector"},
            },
            "2": {
                "inputs": {
                    "stability": self.stability,
                    "apply_text_normalization": "auto",
                    "model": self.model,
                    "inputs": "1",
                    "inputs.text1": text,
                    "language_code": "",
                    "seed": 0,
                    "output_format": self.output_format,
                    "inputs.voice1": ["1", 0],
                },
                "class_type": "ElevenLabsTextToDialogue",
                "_meta": {"title": "ElevenLabs Text to Dialogue"},
            },
            "3": {
                "inputs": {
                    "filename_prefix": "audio/tts_output",
                    "quality": "V0",
                    "audioUI": "",
                    "audio": ["2", 0],
                },
                "class_type": "SaveAudioMP3",
                "_meta": {"title": "Save Audio (MP3)"},
            },
        }

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        *,
        speed: float = 1.0,
        pitch: float = 1.0,
    ) -> TTSResult:
        from drevalis.services.comfyui import ComfyUIClient

        output_path.parent.mkdir(parents=True, exist_ok=True)
        log.info(
            "comfyui_elevenlabs.synthesize.start",
            voice=voice_id,
            text_length=len(text),
        )

        workflow = self._build_workflow(text, voice_id)

        # Round-robin server selection for load balancing
        idx = self._server_index % len(self._servers)
        self._server_index += 1
        server_url, server_key = self._servers[idx]

        log.info(
            "comfyui_elevenlabs.client_config",
            base_url=server_url,
            has_api_key=bool(server_key),
            api_key_prefix=(server_key[:4] + "...") if server_key else None,
            server_index=idx,
            total_servers=len(self._servers),
        )
        client = ComfyUIClient(base_url=server_url, api_key=server_key)
        try:
            extra_data = dict(build_comfyui_auth_extra_data(server_key))
            kind = _classify_comfyui_token(server_key) if server_key else "unknown"
            log.debug(
                "comfyui_elevenlabs.auth",
                token_kind=kind,
                fields_sent=list(extra_data.keys()),
            )
            prompt_id = await client.queue_prompt(workflow, extra_data=extra_data)

            # Poll for completion (exponential backoff)
            delay = 1.0
            total_waited = 0.0
            history = None
            while total_waited < 1200:  # 20 min timeout (queue backs up when busy)
                await asyncio.sleep(delay)
                total_waited += delay
                history = await client.get_history(prompt_id)
                if history is not None:
                    break
                delay = min(delay * 1.5, 10.0)

            if history is None:
                raise RuntimeError(f"ComfyUI ElevenLabs TTS timed out after {total_waited:.0f}s")

            # Check for execution errors first
            exec_status = history.get("status", {})
            if exec_status.get("status_str") == "error":
                messages = exec_status.get("messages", [])
                error_msg = "ComfyUI workflow execution failed"
                for msg_type, msg_data in messages:
                    if msg_type == "execution_error" and isinstance(msg_data, dict):
                        raw = msg_data.get("exception_message", "unknown error")
                        # ComfyUI API-node auth failures come back as
                        # ``Unauthorized: Please login first to use this
                        # node.`` — a confusing message because the user
                        # IS logged into ComfyUI in their browser, but
                        # the worker's HTTP call is a separate session.
                        # Surface a clear actionable hint instead of
                        # the bare upstream string.
                        if "Unauthorized" in raw or "login first" in raw.lower():
                            raise RuntimeError(_AUTH_HINT.format(raw=raw))
                        error_msg = (
                            f"ComfyUI ElevenLabs error on node "
                            f"'{msg_data.get('node_type', '?')}': {raw}"
                        )
                        break
                raise RuntimeError(error_msg)

            # Extract output audio file info from history.
            # ComfyUI may return history before outputs are fully populated,
            # so retry a few times if outputs dict is empty.
            outputs = history.get("outputs", {})
            if not outputs:
                for _retry in range(5):
                    await asyncio.sleep(2.0)
                    history = await client.get_history(prompt_id)
                    if history:
                        outputs = history.get("outputs", {})
                        if outputs:
                            break
                log.debug(
                    "comfyui_elevenlabs.outputs_after_retry",
                    has_outputs=bool(outputs),
                    keys=list(outputs.keys()) if outputs else [],
                )

            audio_info = None
            for node_id, node_output in outputs.items():
                # Try all known output keys used by ComfyUI audio nodes
                for key in ("audio", "audios", "files", "gifs", "images", "videos"):
                    items = node_output.get(key, [])
                    if isinstance(items, list) and items:
                        # Find an item that looks like an audio file
                        for item in items:
                            if isinstance(item, dict) and "filename" in item:
                                fname = item["filename"].lower()
                                if any(
                                    fname.endswith(ext) for ext in (".mp3", ".wav", ".ogg", ".flac")
                                ):
                                    audio_info = item
                                    break
                                # Accept any file if no audio extension found yet
                                if audio_info is None:
                                    audio_info = item
                    if audio_info:
                        break
                if audio_info:
                    break

            if audio_info is None:
                # Last resort: dump the full outputs for debugging
                log.error(
                    "comfyui_elevenlabs.no_audio_output",
                    full_outputs=outputs,
                )
                raise RuntimeError(
                    "ComfyUI ElevenLabs TTS completed but no audio output found. "
                    f"Output nodes: {list(outputs.keys())}"
                )

            # Download the audio file
            filename = audio_info.get("filename", "")
            subfolder = audio_info.get("subfolder", "")
            folder_type = audio_info.get("type", "output")

            audio_bytes = await client.download_image(filename, subfolder, folder_type)

            # Write MP3 to disk
            mp3_path = output_path.with_suffix(".mp3")
            mp3_path.write_bytes(audio_bytes)

            # Convert MP3 -> WAV (pipeline expects WAV)
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(mp3_path),
                "-ar",
                "24000",
                "-ac",
                "1",
                str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                stderr_text = stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"FFmpeg MP3->WAV conversion failed: {stderr_text[:300]}")

            mp3_path.unlink(missing_ok=True)

            # Clean up the generated file on the ComfyUI server to prevent disk fill
            try:
                await client._client.post(
                    "/api/clear-output", json={"subfolder": subfolder, "filename": filename}
                )
            except Exception:
                # Not all ComfyUI versions support this — also try clearing history
                try:
                    await client._client.post("/history", json={"clear": True})
                except Exception:
                    pass

            # Get duration from WAV
            duration, sample_rate = _wav_info(output_path)

            log.info(
                "comfyui_elevenlabs.synthesize.done",
                voice=voice_id,
                duration_seconds=duration,
            )

            return TTSResult(
                audio_path=str(output_path),
                duration_seconds=duration,
                sample_rate=sample_rate,
                word_timestamps=None,
            )
        finally:
            await client.close()

    async def list_voices(self) -> list[VoiceInfo]:
        """Return the list of ElevenLabs voices available in ComfyUI."""
        voices = [
            ("Roger (male, american)", "Roger", "male"),
            ("Sarah (female, american)", "Sarah", "female"),
            ("Laura (female, american)", "Laura", "female"),
            ("Charlie (male, australian)", "Charlie", "male"),
            ("George (male, british)", "George", "male"),
            ("Callum (male, american)", "Callum", "male"),
            ("River (neutral, american)", "River", "neutral"),
            ("Harry (male, american)", "Harry", "male"),
            ("Liam (male, american)", "Liam", "male"),
            ("Alice (female, british)", "Alice", "female"),
            ("Matilda (female, american)", "Matilda", "female"),
            ("Will (male, american)", "Will", "male"),
            ("Jessica (female, american)", "Jessica", "female"),
            ("Eric (male, american)", "Eric", "male"),
            ("Bella (female, american)", "Bella", "female"),
            ("Chris (male, american)", "Chris", "male"),
            ("Brian (male, american)", "Brian", "male"),
            ("Daniel (male, british)", "Daniel", "male"),
            ("Lily (female, british)", "Lily", "female"),
            ("Adam (male, american)", "Adam", "male"),
            ("Bill (male, american)", "Bill", "male"),
        ]
        return [
            VoiceInfo(
                voice_id=vid,
                name=name,
                language="en",
                provider="comfyui_elevenlabs",
            )
            for vid, name, _gender in voices
        ]


# ---------------------------------------------------------------------------
# ElevenLabs Text-to-Sound-Effects via ComfyUI
# ---------------------------------------------------------------------------


class ComfyUIElevenLabsSoundEffectsProvider:
    """Generate sound effects (NOT speech) via the ElevenLabs SFX node.

    Uses the ``ElevenLabsTextToSoundEffects`` + ``SaveAudioMP3`` node
    pair installed in ComfyUI. Returns the path to a WAV file (we
    convert the MP3 ComfyUI hands back so the audiobook concat path
    can use the result directly).

    Unlike a TTS provider this is NOT a ``TTSProvider`` Protocol
    implementation — the call signature is intentionally different
    (``description + duration`` rather than ``text + voice``).
    """

    def __init__(
        self,
        comfyui_base_url: str,
        comfyui_api_key: str | None = None,
        model: str = "eleven_sfx_v2",
        output_format: str = "mp3_44100_192",
        prompt_influence: float = 0.3,
    ) -> None:
        self.comfyui_base_url = comfyui_base_url
        self.comfyui_api_key = comfyui_api_key
        self.model = model
        self.output_format = output_format
        self.prompt_influence = prompt_influence

    def _build_workflow(
        self,
        description: str,
        duration: float,
        loop: bool,
    ) -> dict[str, Any]:
        """Build the ComfyUI workflow JSON.

        Mirrors the dotted-key schema the SFX node expects (``model``
        plus ``model.duration`` / ``model.loop`` / ``model.prompt_influence``).
        Same widget-export convention as the TextToDialogue node — see
        ``ComfyUIElevenLabsTTSProvider._build_workflow`` for the
        cautionary tale on "cleaning these up".
        """
        # Clamp duration to ElevenLabs' 22s SFX cap.
        clamped = max(0.5, min(float(duration), 22.0))
        return {
            "136": {
                "inputs": {
                    "text": description,
                    "model": self.model,
                    "model.duration": clamped,
                    "model.loop": bool(loop),
                    "model.prompt_influence": float(self.prompt_influence),
                    "output_format": self.output_format,
                },
                "class_type": "ElevenLabsTextToSoundEffects",
                "_meta": {"title": "ElevenLabs Text to Sound Effects"},
            },
            "137": {
                "inputs": {
                    "filename_prefix": "audio/sfx_output",
                    "quality": "V0",
                    "audioUI": "",
                    "audio": ["136", 0],
                },
                "class_type": "SaveAudioMP3",
                "_meta": {"title": "Save Audio (MP3)"},
            },
        }

    async def synthesize_sfx(
        self,
        description: str,
        duration: float,
        output_path: Path,
        *,
        loop: bool = False,
        prompt_influence: float | None = None,
    ) -> TTSResult:
        """Generate an SFX clip and write it to ``output_path`` as WAV.

        Returns a TTSResult so the caller can stitch the clip
        alongside voice chunks using the same downstream code paths.
        """
        from drevalis.services.comfyui import ComfyUIClient

        output_path.parent.mkdir(parents=True, exist_ok=True)
        log.info(
            "comfyui_elevenlabs_sfx.synthesize.start",
            description=description[:120],
            duration=duration,
            loop=loop,
        )

        if prompt_influence is not None:
            saved = self.prompt_influence
            self.prompt_influence = prompt_influence
            try:
                workflow = self._build_workflow(description, duration, loop)
            finally:
                self.prompt_influence = saved
        else:
            workflow = self._build_workflow(description, duration, loop)

        client = ComfyUIClient(base_url=self.comfyui_base_url, api_key=self.comfyui_api_key)
        try:
            extra_data = dict(build_comfyui_auth_extra_data(self.comfyui_api_key))
            kind = (
                _classify_comfyui_token(self.comfyui_api_key) if self.comfyui_api_key else "unknown"
            )
            log.debug(
                "comfyui_elevenlabs_sfx.auth",
                token_kind=kind,
                fields_sent=list(extra_data.keys()),
            )
            prompt_id = await client.queue_prompt(workflow, extra_data=extra_data)

            delay = 1.0
            total_waited = 0.0
            history = None
            # SFX runs much faster than voice; 5min cap is plenty.
            while total_waited < 300:
                await asyncio.sleep(delay)
                total_waited += delay
                history = await client.get_history(prompt_id)
                if history is not None:
                    break
                delay = min(delay * 1.5, 5.0)

            if history is None:
                raise RuntimeError(f"ComfyUI ElevenLabs SFX timed out after {total_waited:.0f}s")

            exec_status = history.get("status", {})
            if exec_status.get("status_str") == "error":
                messages = exec_status.get("messages", [])
                error_msg = "ComfyUI workflow execution failed"
                for msg_type, msg_data in messages:
                    if msg_type == "execution_error" and isinstance(msg_data, dict):
                        raw = msg_data.get("exception_message", "unknown error")
                        if "Unauthorized" in raw or "login first" in raw.lower():
                            raise RuntimeError(_AUTH_HINT.format(raw=raw))
                        error_msg = (
                            f"ComfyUI ElevenLabs SFX error on node "
                            f"'{msg_data.get('node_type', '?')}': {raw}"
                        )
                        break
                raise RuntimeError(error_msg)

            outputs = history.get("outputs", {})
            audio_info: dict[str, Any] | None = None
            for _node_id, node_output in outputs.items():
                for key in ("audio", "audios", "files"):
                    items = node_output.get(key, [])
                    if isinstance(items, list) and items:
                        for item in items:
                            if isinstance(item, dict) and "filename" in item:
                                audio_info = item
                                break
                    if audio_info:
                        break
                if audio_info:
                    break

            if audio_info is None:
                raise RuntimeError("ComfyUI ElevenLabs SFX completed but no audio output found")

            filename = audio_info.get("filename", "")
            subfolder = audio_info.get("subfolder", "")
            folder_type = audio_info.get("type", "output")
            audio_bytes = await client.download_image(filename, subfolder, folder_type)

            mp3_path = output_path.with_suffix(".mp3")
            mp3_path.write_bytes(audio_bytes)

            # MP3 → WAV @ 24kHz mono so it slots into the audiobook
            # concat pipeline without a second pass.
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(mp3_path),
                "-ar",
                "24000",
                "-ac",
                "1",
                str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg MP3->WAV conversion failed: {stderr.decode('utf-8', errors='replace')[:300]}"
                )
            mp3_path.unlink(missing_ok=True)

            duration_actual, sample_rate = _wav_info(output_path)
            log.info(
                "comfyui_elevenlabs_sfx.synthesize.done",
                duration_seconds=duration_actual,
            )
            return TTSResult(
                audio_path=str(output_path),
                duration_seconds=duration_actual,
                sample_rate=sample_rate,
                word_timestamps=None,
            )
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# TTSService -- high-level orchestrator
# ---------------------------------------------------------------------------


class TTSService:
    """High-level TTS service that resolves provider from VoiceProfile.

    Typical usage in the generation pipeline::

        result = await tts_service.generate_voiceover(voice_profile, script, episode_id)
    """

    PAUSE_BETWEEN_SCENES_MS: int = 400  # silence gap between scene narrations

    def __init__(
        self,
        piper: PiperTTSProvider,
        elevenlabs: ElevenLabsTTSProvider | None,
        kokoro: KokoroTTSProvider | None = None,
        edge: EdgeTTSProvider | None = None,
        comfyui_elevenlabs: ComfyUIElevenLabsTTSProvider | None = None,
        storage_base_path: Path = Path("."),
    ) -> None:
        self.piper = piper
        self.elevenlabs = elevenlabs
        self.kokoro = kokoro
        self.edge = edge
        self.comfyui_elevenlabs = comfyui_elevenlabs
        self.storage_base_path = storage_base_path

    def get_provider(self, voice_profile: VoiceProfile) -> TTSProvider:
        """Return the concrete provider matching *voice_profile.provider*."""
        if voice_profile.provider == "piper":
            return self.piper
        if voice_profile.provider == "elevenlabs":
            if self.elevenlabs is None:
                raise RuntimeError("ElevenLabs provider is not configured (missing API key)")
            return self.elevenlabs
        if voice_profile.provider == "kokoro":
            if self.kokoro is None:
                raise RuntimeError(
                    "Kokoro TTS provider is not configured. "
                    "Install with: pip install kokoro soundfile"
                )
            return self.kokoro
        if voice_profile.provider == "edge":
            if self.edge is None:
                raise RuntimeError(
                    "Edge TTS provider is not configured. Install with: pip install edge-tts"
                )
            return self.edge
        if voice_profile.provider == "comfyui_elevenlabs":
            if self.comfyui_elevenlabs is None:
                raise RuntimeError(
                    "ComfyUI ElevenLabs provider is not configured. "
                    "Ensure a ComfyUI server with ElevenLabs nodes is running."
                )
            return self.comfyui_elevenlabs
        raise ValueError(f"Unknown TTS provider: {voice_profile.provider!r}")

    async def generate_voiceover(
        self,
        voice_profile: VoiceProfile,
        script: EpisodeScript,
        episode_id: UUID,
        *,
        speed_override: float | None = None,
        pitch_override: float | None = None,
    ) -> TTSResult:
        """Generate a full voiceover WAV for the given episode script.

        Steps:
        1. Synthesise each scene narration as a separate WAV segment.
        2. Concatenate segments with short silences in between.
        3. Return a single ``TTSResult`` pointing at the final file.

        Per-episode speed/pitch overrides (written by the regenerate-voice
        endpoint into ``episode.metadata_["tts_overrides"]``) are passed
        in via the keyword-only ``speed_override`` / ``pitch_override``
        arguments. When absent, the profile's default values are used.
        Before this, the overrides were stored on the episode but the TTS
        service never read them — users tweaking speed/pitch on a regen
        saw zero change in the output.
        """
        provider = self.get_provider(voice_profile)

        # Resolve voice_id from profile.
        voice_id = self._voice_id_for(voice_profile)

        speed = float(speed_override) if speed_override is not None else float(voice_profile.speed)
        pitch = float(pitch_override) if pitch_override is not None else float(voice_profile.pitch)

        episode_dir = self.storage_base_path / "episodes" / str(episode_id)
        audio_dir = episode_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Build the full narration text: hook + scene narrations + outro.
        # Prefer ``scene.narration_tts`` when populated — it carries the
        # provider-specific formatting (numbers spelled out, acronyms
        # expanded, parentheticals split) produced by the script step's
        # narration_formatter pass. The original ``scene.narration`` stays
        # untouched for the editor + UI; only the synthesiser sees the
        # rewrite.
        segments: list[str] = [script.hook]
        for scene in script.scenes:
            tts_text = scene.narration_tts if scene.narration_tts else scene.narration
            segments.append(tts_text)
        if script.outro:
            segments.append(script.outro)

        log.info(
            "tts.generate_voiceover.start",
            episode_id=str(episode_id),
            provider=voice_profile.provider,
            segment_count=len(segments),
        )

        # Build list of segments to synthesize (skip empty and cached)
        import asyncio as _asyncio

        to_synthesize: list[tuple[int, str, Path]] = []
        cached_results: dict[int, TTSResult] = {}

        for idx, text in enumerate(segments):
            if not text.strip():
                continue
            seg_path = audio_dir / f"segment_{idx:03d}.wav"

            if seg_path.exists() and seg_path.stat().st_size > 100:
                try:
                    with wave.open(str(seg_path), "rb") as wf:
                        cached_duration = wf.getnframes() / wf.getframerate()
                        cached_sample_rate = wf.getframerate()
                except Exception:
                    cached_duration = 0.0
                    cached_sample_rate = 22050
                log.debug("tts.segment_cached", idx=idx)
                cached_results[idx] = TTSResult(
                    audio_path=str(seg_path),
                    duration_seconds=cached_duration,
                    sample_rate=cached_sample_rate,
                    word_timestamps=[],
                )
                continue

            to_synthesize.append((idx, text, seg_path))

        # Parallel TTS: process segments concurrently across multiple servers
        # Concurrency limited by number of ComfyUI servers (for ComfyUI TTS)
        # or 2 for other providers to avoid overloading
        max_parallel = 2
        if hasattr(provider, "_servers"):
            max_parallel = max(2, len(provider._servers))

        sem = _asyncio.Semaphore(max_parallel)
        synth_results: dict[int, TTSResult] = {}

        async def _synth_one(idx: int, text: str, seg_path: Path) -> None:
            async with sem:
                try:
                    result = await provider.synthesize(
                        text,
                        voice_id,
                        seg_path,
                        speed=speed,
                        pitch=pitch,
                    )
                    synth_results[idx] = result
                except Exception as exc:
                    log.warning(
                        "tts.segment_failed",
                        idx=idx,
                        error=str(exc)[:200] or repr(exc),
                        exc_type=type(exc).__name__,
                    )

        if to_synthesize:
            log.info("tts.parallel_synthesis", total=len(to_synthesize), parallel=max_parallel)
            tasks = [_synth_one(idx, text, path) for idx, text, path in to_synthesize]
            await _asyncio.gather(*tasks)

        # Merge cached + synthesized results in order
        all_indices = sorted(set(cached_results.keys()) | set(synth_results.keys()))
        segment_results: list[TTSResult] = []
        for idx in all_indices:
            if idx in cached_results:
                segment_results.append(cached_results[idx])
            elif idx in synth_results:
                segment_results.append(synth_results[idx])

        if not segment_results:
            failed_count = len(to_synthesize) - len(synth_results)
            raise RuntimeError(
                f"TTS failed: all {failed_count} segments failed to synthesize. "
                f"Check if ComfyUI is running and ElevenLabs nodes are available."
            )

        if len(segment_results) == 1:
            single = segment_results[0]
            final_path = audio_dir / "voiceover.wav"
            # Rename single segment to final path.
            Path(single.audio_path).rename(final_path)
            single.audio_path = str(final_path)
            log.info(
                "tts.generate_voiceover.done",
                episode_id=str(episode_id),
                duration=single.duration_seconds,
            )
            return single

        # Concatenate segments with silence gaps.
        final_path = audio_dir / "voiceover.wav"
        total_duration, merged_timestamps = _concatenate_wav_segments(
            [Path(r.audio_path) for r in segment_results],
            final_path,
            pause_ms=self.PAUSE_BETWEEN_SCENES_MS,
            timestamps_per_segment=[r.word_timestamps for r in segment_results],
        )

        sample_rate = segment_results[0].sample_rate

        log.info(
            "tts.generate_voiceover.done",
            episode_id=str(episode_id),
            duration=total_duration,
        )

        return TTSResult(
            audio_path=str(final_path),
            duration_seconds=total_duration,
            sample_rate=sample_rate,
            word_timestamps=merged_timestamps,
        )

    # -- private helpers ----------------------------------------------------

    @staticmethod
    def _voice_id_for(voice_profile: VoiceProfile) -> str:
        """Extract the provider-specific voice identifier."""
        if voice_profile.provider == "piper":
            # Use model path stem or speaker_id.
            if voice_profile.piper_model_path:
                return Path(voice_profile.piper_model_path).stem
            if voice_profile.piper_speaker_id:
                return voice_profile.piper_speaker_id
            raise ValueError(
                f"VoiceProfile {voice_profile.name!r} (piper) has no model path or speaker id"
            )
        if voice_profile.provider == "elevenlabs":
            if voice_profile.elevenlabs_voice_id:
                return voice_profile.elevenlabs_voice_id
            raise ValueError(
                f"VoiceProfile {voice_profile.name!r} (elevenlabs) has no elevenlabs_voice_id"
            )
        if voice_profile.provider == "kokoro":
            if voice_profile.kokoro_voice_name:
                return voice_profile.kokoro_voice_name
            raise ValueError(f"VoiceProfile {voice_profile.name!r} (kokoro) has no voice name")
        if voice_profile.provider == "edge":
            if voice_profile.edge_voice_id:
                return voice_profile.edge_voice_id
            raise ValueError(f"VoiceProfile {voice_profile.name!r} (edge) has no edge_voice_id")
        if voice_profile.provider == "comfyui_elevenlabs":
            if voice_profile.elevenlabs_voice_id:
                return voice_profile.elevenlabs_voice_id
            raise ValueError(
                f"VoiceProfile {voice_profile.name!r} (comfyui_elevenlabs) has no elevenlabs_voice_id"
            )
        raise ValueError(f"Unknown provider: {voice_profile.provider!r}")


# ---------------------------------------------------------------------------
# Utility helpers (module-private)
# ---------------------------------------------------------------------------


def _wav_info(path: Path) -> tuple[float, int]:
    """Return (duration_seconds, sample_rate) for a WAV file."""
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        duration = frames / rate if rate else 0.0
    return duration, rate


def _estimate_mp3_duration(path: Path) -> float:
    """Estimate MP3 duration from file size assuming 128 kbps CBR.

    This is a coarse fallback; callers should prefer ``ffprobe`` when
    available for accurate durations.
    """
    file_size = path.stat().st_size
    bitrate_bps = 128_000  # 128 kbps
    return (file_size * 8) / bitrate_bps


def _generate_silence_wav(
    num_samples: int, sample_rate: int, channels: int, sample_width: int
) -> bytes:
    """Return raw PCM silence bytes."""
    return b"\x00" * (num_samples * channels * sample_width)


def _concatenate_wav_segments(
    segment_paths: list[Path],
    output_path: Path,
    *,
    pause_ms: int = 400,
    timestamps_per_segment: list[list[WordTimestamp] | None] | None = None,
) -> tuple[float, list[WordTimestamp] | None]:
    """Concatenate WAV segments with silence gaps.

    Returns ``(total_duration_seconds, merged_word_timestamps)``.
    """
    if not segment_paths:
        raise ValueError("No segments to concatenate")

    # Read the first segment to learn audio parameters.
    with wave.open(str(segment_paths[0]), "rb") as ref:
        channels = ref.getnchannels()
        sample_width = ref.getsampwidth()
        sample_rate = ref.getframerate()

    pause_samples = int(sample_rate * pause_ms / 1000)
    silence_bytes = _generate_silence_wav(pause_samples, sample_rate, channels, sample_width)

    merged_timestamps: list[WordTimestamp] = []
    has_any_timestamps = False
    current_offset = 0.0

    with wave.open(str(output_path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(sample_width)
        out.setframerate(sample_rate)

        for idx, seg_path in enumerate(segment_paths):
            with wave.open(str(seg_path), "rb") as seg:
                seg_channels = seg.getnchannels()
                seg_sw = seg.getsampwidth()
                seg_rate = seg.getframerate()
                seg_frames = seg.getnframes()
                seg_data = seg.readframes(seg_frames)

            if seg_rate != sample_rate or seg_channels != channels or seg_sw != sample_width:
                log.warning(
                    "tts.concat.format_mismatch",
                    segment=str(seg_path),
                    expected_rate=sample_rate,
                    actual_rate=seg_rate,
                )

            seg_duration = seg_frames / sample_rate

            # Offset word timestamps for this segment.
            if timestamps_per_segment and idx < len(timestamps_per_segment):
                seg_ts = timestamps_per_segment[idx]
                if seg_ts:
                    has_any_timestamps = True
                    for wt in seg_ts:
                        merged_timestamps.append(
                            WordTimestamp(
                                word=wt.word,
                                start_seconds=wt.start_seconds + current_offset,
                                end_seconds=wt.end_seconds + current_offset,
                            )
                        )

            out.writeframes(seg_data)
            current_offset += seg_duration

            # Insert silence between segments (not after the last one).
            if idx < len(segment_paths) - 1:
                out.writeframes(silence_bytes)
                current_offset += pause_ms / 1000.0

    total_duration = current_offset
    return total_duration, merged_timestamps if has_any_timestamps else None


def _chars_to_words(
    characters: list[str],
    starts: list[float],
    ends: list[float],
) -> list[WordTimestamp]:
    """Reconstruct word timestamps from character-level alignment data."""
    words: list[WordTimestamp] = []
    current_word_chars: list[str] = []
    word_start: float | None = None
    word_end: float = 0.0

    for char, cs, ce in zip(characters, starts, ends, strict=False):
        if char == " ":
            if current_word_chars:
                words.append(
                    WordTimestamp(
                        word="".join(current_word_chars),
                        start_seconds=word_start or 0.0,
                        end_seconds=word_end,
                    )
                )
                current_word_chars = []
                word_start = None
            continue

        if word_start is None:
            word_start = cs
        current_word_chars.append(char)
        word_end = ce

    # Flush last word.
    if current_word_chars:
        words.append(
            WordTimestamp(
                word="".join(current_word_chars),
                start_seconds=word_start or 0.0,
                end_seconds=word_end,
            )
        )

    return words
