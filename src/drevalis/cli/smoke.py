"""``drevalis smoke`` — exercise the desktop install plumbing end-to-end.

Runs a tiny TTS → FFmpeg round-trip that produces a real WAV file, no
ComfyUI / no LLM / no GPU required. Catches the most common "I just
installed and something's broken" regressions in under 10 seconds.

Steps:

1. Synthesise a 5-word phrase via EdgeTTSProvider (cloud, no API key).
2. EdgeTTSProvider internally calls FFmpeg to convert MP3 → WAV, so the
   smoke implicitly verifies FFmpeg is on the resolved path.
3. ffprobe the resulting WAV to confirm it's a valid audio file with
   non-zero duration.

Exits 0 on success, 1 on any failure with a diagnostic line written to
stderr. Output WAV is written to a temp dir and removed on exit.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Voice constant — locked to the most ubiquitous Edge voice so the smoke
# test doesn't depend on locale availability.
_VOICE_ID = "en-US-AriaNeural"
_TEXT = "Drevalis desktop smoke test."


async def _run_async() -> int:
    print("Drevalis smoke test\n")

    # Late imports — TTS / Settings cost is real on cold start, no point
    # paying it when the user just wants the launcher.
    from drevalis.core.config import Settings
    from drevalis.services.tts import EdgeTTSProvider

    settings = Settings()
    ffmpeg_path = shutil.which(settings.ffmpeg_path) or settings.ffmpeg_path

    # 1) FFmpeg sanity check — Edge TTS needs it for MP3 → WAV.
    if shutil.which("ffmpeg") is None and shutil.which(ffmpeg_path) is None:
        print(
            f"[FAIL] FFmpeg not found at {settings.ffmpeg_path!r} — install ffmpeg first.",
            file=sys.stderr,
        )
        return 1

    with tempfile.TemporaryDirectory(prefix="drevalis-smoke-") as tmp:
        out = Path(tmp) / "smoke.wav"

        print(f"[1/2] Synthesising '{_TEXT}' via Edge TTS …")
        try:
            provider = EdgeTTSProvider()
            result = await provider.synthesize(_TEXT, _VOICE_ID, out)
        except Exception as exc:
            print(f"[FAIL] TTS failed: {exc}", file=sys.stderr)
            return 1

        if not out.exists():
            print(f"[FAIL] TTS reported success but {out} doesn't exist", file=sys.stderr)
            return 1

        size = out.stat().st_size
        if size < 1024:
            print(f"[FAIL] WAV is too small ({size} bytes)", file=sys.stderr)
            return 1

        words = len(result.word_timestamps) if result.word_timestamps else 0
        print(f"      WAV: {size:,} bytes, {words} word timestamps")

        # 2) ffprobe the output to confirm it's a real audio stream.
        print("[2/2] Verifying WAV via ffprobe …")
        try:
            proc = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:stream=codec_type",
                    "-of",
                    "json",
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            print(f"[FAIL] ffprobe failed: {exc}", file=sys.stderr)
            return 1

        if proc.returncode != 0:
            print(f"[FAIL] ffprobe exit {proc.returncode}: {proc.stderr.strip()}", file=sys.stderr)
            return 1

        try:
            payload = json.loads(proc.stdout)
            duration = float(payload["format"]["duration"])
            codec_types = [s["codec_type"] for s in payload.get("streams", [])]
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            print(f"[FAIL] ffprobe output malformed: {exc}", file=sys.stderr)
            return 1

        if "audio" not in codec_types:
            print(f"[FAIL] no audio stream in WAV (streams: {codec_types})", file=sys.stderr)
            return 1
        if duration <= 0:
            print(f"[FAIL] WAV duration <= 0 ({duration})", file=sys.stderr)
            return 1

        print(f"      duration: {duration:.2f}s, streams: {','.join(codec_types)}")

    print("\nPASS — TTS and FFmpeg are wired up.")
    return 0


def main() -> int:
    return asyncio.run(_run_async())
