"""``drevalis healthcheck`` — verify desktop install plumbing.

Probes each external service the pipeline needs and prints a pass/fail
summary. Exits 0 if every required service is reachable, 1 otherwise.

This is the "preflight" the user runs after install / before the first
generation. The first-run wizard (Phase 5) will eventually run the same
checks and surface them inline; until then, the CLI is the entry point.

Each probe times out fast (3s) so a missing service doesn't hang the
report. Optional services are reported as SKIP rather than FAIL.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

import httpx

# ── Output formatting ─────────────────────────────────────────────────────────


class Status(Enum):
    OK = "OK"
    FAIL = "FAIL"
    SKIP = "SKIP"


_COLOURS_ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_GREEN = "\033[92m" if _COLOURS_ENABLED else ""
_RED = "\033[91m" if _COLOURS_ENABLED else ""
_YELLOW = "\033[93m" if _COLOURS_ENABLED else ""
_RESET = "\033[0m" if _COLOURS_ENABLED else ""


def _badge(status: Status) -> str:
    if status is Status.OK:
        return f"{_GREEN}[OK]{_RESET}  "
    if status is Status.FAIL:
        return f"{_RED}[FAIL]{_RESET}"
    return f"{_YELLOW}[SKIP]{_RESET}"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: Status
    detail: str = ""
    required: bool = True


def _print_result(r: CheckResult) -> None:
    line = f"{_badge(r.status)}  {r.name:<14} {r.detail}".rstrip()
    print(line)


# ── Probes ────────────────────────────────────────────────────────────────────


async def _probe_database(database_url: str) -> CheckResult:
    """Verify the DB is reachable and migrated."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    try:
        engine = create_async_engine(database_url, connect_args={"timeout": 3})
        try:
            async with engine.connect() as conn:
                row = await conn.execute(text("SELECT version_num FROM alembic_version"))
                version = row.scalar_one_or_none()
        finally:
            await engine.dispose()
    except Exception as exc:
        return CheckResult("Database", Status.FAIL, _short_url(database_url) + " — " + str(exc)[:80])

    if version is None:
        return CheckResult(
            "Database",
            Status.FAIL,
            f"{_short_url(database_url)} — alembic_version empty (run `alembic upgrade head`)",
        )
    return CheckResult("Database", Status.OK, f"{_short_url(database_url)} -> {version}")


async def _probe_redis(redis_url: str) -> CheckResult:
    """Verify Redis reachable + report version."""
    from redis.asyncio import Redis

    try:
        r = Redis.from_url(redis_url, socket_connect_timeout=3)
        try:
            info = await r.info(section="server")
            version = info.get("redis_version", "unknown")
        finally:
            await r.aclose()
    except Exception as exc:
        return CheckResult("Redis", Status.FAIL, f"{redis_url} — {str(exc)[:80]}")
    return CheckResult("Redis", Status.OK, f"{redis_url} -> v{version}")


async def _probe_comfyui(url: str) -> CheckResult:
    """Hit ComfyUI's /system_stats — required for video generation."""
    endpoint = url.rstrip("/") + "/system_stats"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(endpoint)
            resp.raise_for_status()
            data = resp.json()
            gpu_count = len(data.get("devices", []))
        return CheckResult("ComfyUI", Status.OK, f"{url} -> {gpu_count} device(s)")
    except Exception as exc:
        return CheckResult("ComfyUI", Status.FAIL, f"{url} — {str(exc)[:80]}")


async def _probe_lm_studio(base_url: str) -> CheckResult:
    """Check LM Studio (or any OpenAI-compatible local LLM) /v1/models."""
    endpoint = base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(endpoint)
            resp.raise_for_status()
            data = resp.json()
            count = len(data.get("data", []))
    except Exception as exc:
        return CheckResult(
            "LM Studio",
            Status.FAIL,
            f"{base_url} — {str(exc)[:80]}",
            required=False,
        )
    return CheckResult("LM Studio", Status.OK, f"{base_url} -> {count} model(s)")


def _probe_anthropic(api_key: str) -> CheckResult:
    """Verify the Anthropic key shape — no actual API hit."""
    if not api_key:
        return CheckResult("Anthropic", Status.SKIP, "no api key set", required=False)
    if not api_key.startswith("sk-ant-"):
        return CheckResult("Anthropic", Status.FAIL, "key doesn't look like sk-ant-…", required=False)
    return CheckResult("Anthropic", Status.OK, f"key set ({len(api_key)} chars)")


def _probe_ffmpeg(path: str) -> CheckResult:
    """Check FFmpeg is on PATH or at the configured path."""
    resolved = shutil.which(path) or path
    try:
        result = subprocess.run(
            [resolved, "-version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return CheckResult("FFmpeg", Status.FAIL, f"{path} — {exc}")
    if result.returncode != 0:
        return CheckResult("FFmpeg", Status.FAIL, f"{path} -> exit {result.returncode}")
    first_line = result.stdout.splitlines()[0] if result.stdout else "(no output)"
    return CheckResult("FFmpeg", Status.OK, first_line[:80])


def _probe_piper(piper_models_path: str) -> CheckResult:
    """Check Piper voices are present.

    Piper itself is optional — installs that use ElevenLabs / OpenAI
    TTS / etc. for voice never need a local Piper voice file. Missing
    voices report as SKIP (non-required) so the overall healthcheck
    still passes; the message points at the docs for installing
    voices when the user wants offline TTS.
    """
    from pathlib import Path

    p = Path(piper_models_path)
    if not p.exists():
        return CheckResult(
            "Piper",
            Status.SKIP,
            f"{p} — directory missing (offline TTS off)",
            required=False,
        )
    voices = list(p.rglob("*.onnx"))
    if not voices:
        return CheckResult(
            "Piper",
            Status.SKIP,
            f"{p} — no .onnx voices yet (drop one in to enable offline TTS)",
            required=False,
        )
    return CheckResult("Piper", Status.OK, f"{len(voices)} voice(s) in {p}")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _short_url(url: str) -> str:
    """Compact a SQLAlchemy URL for display (don't leak file paths past the basename)."""
    if "sqlite" in url:
        # sqlite+aiosqlite:///<path>  -> sqlite://…/<basename>
        path = url.split(":///", 1)[-1]
        return f"sqlite://…/{path.rsplit('/', 1)[-1]}"
    return url.split("@")[-1] if "@" in url else url


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run_async() -> int:
    from drevalis.core.config import Settings

    settings = Settings()

    print("Drevalis healthcheck\n")

    # Sync probes first (cheap, no event-loop work).
    sync_results = [
        _probe_ffmpeg(settings.ffmpeg_path),
        _probe_piper(str(settings.piper_models_path)),
        _probe_anthropic(settings.anthropic_api_key),
    ]

    # Async probes in parallel.
    async_results = await asyncio.gather(
        _probe_database(settings.database_url),
        _probe_redis(settings.redis_url),
        _probe_comfyui(settings.comfyui_default_url),
        _probe_lm_studio(settings.lm_studio_base_url),
        return_exceptions=False,
    )

    # Order: DB / Redis / ComfyUI / LM Studio / Anthropic / FFmpeg / Piper
    ordered: list[CheckResult] = [
        async_results[0],  # DB
        async_results[1],  # Redis
        async_results[2],  # ComfyUI
        async_results[3],  # LM Studio
        sync_results[2],  # Anthropic
        sync_results[0],  # FFmpeg
        sync_results[1],  # Piper
    ]

    for r in ordered:
        _print_result(r)

    ok = sum(1 for r in ordered if r.status is Status.OK)
    fail = sum(1 for r in ordered if r.status is Status.FAIL)
    skip = sum(1 for r in ordered if r.status is Status.SKIP)
    print(f"\n{ok} OK, {fail} fail, {skip} skip")

    # Exit non-zero if any *required* check failed.
    required_failures = sum(1 for r in ordered if r.status is Status.FAIL and r.required)
    return 1 if required_failures else 0


def main() -> int:
    return asyncio.run(_run_async())
