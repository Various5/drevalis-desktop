"""Video-ingest pipeline worker.

Takes an uploaded raw video asset and produces a ranked list of candidate
short-form clips the user can pick from. Pipeline:

1. FFmpeg extracts a mono 16 kHz WAV from the video.
2. faster-whisper transcribes → word-level timestamps.
3. An LLM reads the transcript and returns ``[{start_s, end_s, title,
   reason, score}]`` for the top candidate clips (30-60s).
4. Results land on the ``video_ingest_jobs`` row as ``candidate_clips``.

The caller commits to a clip via
``POST /api/v1/video-ingest/{job_id}/pick`` which creates a draft
``Episode`` whose script is pre-populated with scenes derived from the
selected range.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# Asks the LLM to pick candidates. Strict JSON so we can parse without
# regex gymnastics. ``max_count`` controls how many the LLM returns.
_PICKER_SYSTEM = (
    "You are a short-form video editor. The user pastes a transcript "
    "with word-level timestamps. Pick the {max_count} best 30-60 second "
    "moments suitable for a YouTube Short / TikTok clip. Good moments "
    "are self-contained, have a hook, and end on a punchline or insight.\n\n"
    "Return ONLY valid JSON in this exact shape:\n"
    "{{\n"
    '  "clips": [\n'
    '    {{"start_s": 12.4, "end_s": 57.9, "title": "...", "reason": "...", "score": 0.87}}\n'
    "  ]\n"
    "}}\n"
    "Keep clips non-overlapping. Scores 0-1. No text outside the JSON."
)

_PICKER_USER = (
    "Transcript (word-level, seconds.milliseconds):\n\n"
    "{transcript}\n\n"
    "Video total duration: {duration_s:.1f}s. Return the JSON now."
)


async def analyze_video_ingest(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Worker job — transcribe + pick candidate clips for a VideoIngestJob."""
    from drevalis.core.deps import get_settings
    from drevalis.repositories.asset import AssetRepository, VideoIngestJobRepository
    from drevalis.repositories.llm_config import LLMConfigRepository
    from drevalis.services.captions import CaptionService

    log = logger.bind(job_id=job_id, job="analyze_video_ingest")
    log.info("video_ingest_start")

    session_factory = ctx["session_factory"]
    settings = get_settings()
    parsed_id = uuid.UUID(job_id)

    async with session_factory() as session:
        job_repo = VideoIngestJobRepository(session)
        asset_repo = AssetRepository(session)
        llm_repo = LLMConfigRepository(session)

        job = await job_repo.get_by_id(parsed_id)
        if job is None:
            log.warning("video_ingest_job_missing")
            return {"status": "not_found"}

        asset = await asset_repo.get_by_id(job.asset_id)
        if asset is None or asset.kind != "video":
            await _fail(session, job_repo, job.id, "source asset missing or not a video")
            return {"status": "failed", "error": "source_asset_missing"}

        source_path = Path(settings.storage_base_path) / asset.file_path
        if not source_path.exists():
            await _fail(session, job_repo, job.id, "source file not on disk")
            return {"status": "failed", "error": "source_file_missing"}

        await job_repo.update(
            job.id,
            status="running",
            stage="transcribing",
            progress_pct=5,
        )
        await session.commit()

        # ── 1. Extract 16 kHz mono WAV for whisper ──────────────────
        await job_repo.update(job.id, stage="extracting_audio", progress_pct=10)
        await session.commit()
        audio_out = source_path.with_suffix(".whisper.wav")
        rc = await _ffmpeg_extract_audio(source_path, audio_out)
        if rc != 0 or not audio_out.exists():
            await _fail(session, job_repo, job.id, "ffmpeg audio extraction failed")
            return {"status": "failed", "error": "ffmpeg_failed"}

        await job_repo.update(job.id, stage="audio_extracted", progress_pct=25)
        await session.commit()

        # ── 2. Whisper transcribe ──────────────────────────────────
        await job_repo.update(job.id, stage="transcribing", progress_pct=30)
        await session.commit()

        caption_svc: CaptionService = ctx["caption_service"]
        word_ts = await asyncio.to_thread(caption_svc._transcribe, audio_out, "en")
        transcript_payload = [
            {"w": w.word, "s": round(w.start_seconds, 2), "e": round(w.end_seconds, 2)}
            for w in word_ts
        ]
        await job_repo.update(
            job.id,
            stage="analyzing",
            progress_pct=60,
            transcript=transcript_payload,
        )
        await session.commit()

        # ── 3. LLM picks candidate clips ───────────────────────────
        await job_repo.update(job.id, stage="picking_clips", progress_pct=75)
        await session.commit()

        llm_configs = await llm_repo.get_all(limit=10)
        llm_config = llm_configs[0] if llm_configs else None
        if llm_config is None:
            # Fall back to a naive duration-based split so the feature
            # still works without an LLM configured.
            candidates = _naive_candidates(word_ts, asset.duration_seconds or 0.0)
        else:
            candidates = await _llm_pick(
                ctx["llm_service"],
                llm_config,
                transcript_payload,
                asset.duration_seconds or 0.0,
                log=log,
            )

        await job_repo.update(
            job.id,
            status="done",
            stage="done",
            progress_pct=100,
            candidate_clips=candidates,
        )
        await session.commit()

    log.info("video_ingest_done", candidates=len(candidates))
    return {"job_id": job_id, "status": "done", "candidates": len(candidates)}


async def _fail(session: Any, repo: Any, job_id: uuid.UUID, message: str) -> None:
    await repo.update(
        job_id,
        status="failed",
        stage="failed",
        error_message=message,
    )
    await session.commit()


async def _ffmpeg_extract_audio(src: Path, dst: Path) -> int:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-vn",
        str(dst),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await proc.wait()


async def _llm_pick(
    llm_service: Any,
    llm_config: Any,
    word_ts: list[dict[str, Any]],
    duration_s: float,
    *,
    max_count: int = 5,
    log: Any,
) -> list[dict[str, Any]]:
    """Ask the LLM for candidate clips. Tolerant of malformed JSON."""
    provider = llm_service.get_provider(llm_config)

    # Keep the prompt under the model's context by capping the word
    # list. 10k words ≈ ~45 min of speech which is plenty for one shot.
    transcript_text = "\n".join(f"[{w['s']:.2f}-{w['e']:.2f}] {w['w']}" for w in word_ts[:10_000])
    try:
        result = await provider.generate(
            system_prompt=_PICKER_SYSTEM.format(max_count=max_count),
            user_prompt=_PICKER_USER.format(
                transcript=transcript_text,
                duration_s=duration_s,
            ),
            temperature=0.2,
            max_tokens=2000,
            json_mode=True,
        )
    except Exception as exc:
        log.warning("video_ingest_llm_failed", error=str(exc))
        return _naive_candidates(word_ts, duration_s)

    text = getattr(result, "text", None) or ""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        log.warning("video_ingest_llm_non_json", preview=text[:160])
        return _naive_candidates(word_ts, duration_s)

    clips = data.get("clips") or []
    cleaned: list[dict[str, Any]] = []
    for c in clips[:max_count]:
        try:
            s = float(c["start_s"])
            e = float(c["end_s"])
        except (KeyError, TypeError, ValueError):
            continue
        if e <= s or e - s < 10 or e - s > 120:
            continue
        cleaned.append(
            {
                "start_s": round(s, 2),
                "end_s": round(e, 2),
                "title": str(c.get("title") or "")[:120],
                "reason": str(c.get("reason") or "")[:240],
                "score": float(c.get("score") or 0.0),
            }
        )
    return cleaned or _naive_candidates(word_ts, duration_s)


def _naive_candidates(word_ts: list[Any], duration_s: float) -> list[dict[str, Any]]:
    """Fallback picker — splits the video into 45 s windows, no LLM needed."""
    if duration_s <= 0:
        return []
    window = 45.0
    hop = 60.0
    out: list[dict[str, Any]] = []
    t = 0.0
    idx = 1
    while t + window <= duration_s and len(out) < 5:
        out.append(
            {
                "start_s": round(t, 2),
                "end_s": round(t + window, 2),
                "title": f"Clip {idx}",
                "reason": "Automatic window (no LLM configured)",
                "score": 0.5,
            }
        )
        t += hop
        idx += 1
    return out


# ── Clip → Episode commit ───────────────────────────────────────────


async def commit_video_ingest_clip(
    ctx: dict[str, Any],
    job_id: str,
    clip_index: int,
    series_id: str,
) -> dict[str, Any]:
    """Create a draft Episode from a selected candidate clip.

    The episode's scenes are a single scene pointing at the uploaded
    video asset, windowed to the selected clip's range via a new
    ``clip_start_s`` / ``clip_end_s`` on the scene (interpreted by
    the assembly step).
    """
    from drevalis.repositories.asset import AssetRepository, VideoIngestJobRepository
    from drevalis.repositories.episode import EpisodeRepository

    log = logger.bind(job_id=job_id, clip_index=clip_index, job="commit_video_ingest")
    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        job = await VideoIngestJobRepository(session).get_by_id(uuid.UUID(job_id))
        if job is None or job.status != "done":
            raise ValueError("video ingest job is not ready")
        clips = job.candidate_clips or []
        if not 0 <= clip_index < len(clips):
            raise ValueError("clip_index out of range")
        chosen = clips[clip_index]

        asset = await AssetRepository(session).get_by_id(job.asset_id)
        if asset is None:
            raise ValueError("source asset disappeared")

        # Minimal script — one scene pointing at the source asset and
        # windowed to the picked clip range. The editor (Phase D) takes
        # over from here for trimming, overlays, etc.
        script = {
            "title": chosen.get("title") or "Ingested clip",
            "hook": chosen.get("reason") or "",
            "outro": "",
            "scenes": [
                {
                    "scene_number": 1,
                    "narration": "",
                    "visual_prompt": "source clip",
                    "duration_seconds": float(chosen["end_s"]) - float(chosen["start_s"]),
                    "keywords": [],
                    "source_asset_id": str(asset.id),
                    "clip_start_s": float(chosen["start_s"]),
                    "clip_end_s": float(chosen["end_s"]),
                }
            ],
            "total_duration_seconds": float(chosen["end_s"]) - float(chosen["start_s"]),
            "language": "en-US",
        }

        ep_repo = EpisodeRepository(session)
        episode = await ep_repo.create(
            series_id=uuid.UUID(series_id),
            title=script["title"],
            topic=chosen.get("reason") or "Ingested from uploaded video",
            script=script,
            status="review",
            video_ingest_source_asset_id=asset.id,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        await VideoIngestJobRepository(session).update(
            job.id,
            selected_clip_index=clip_index,
            resulting_episode_id=episode.id,
        )
        await session.commit()

    log.info("video_ingest_committed", episode_id=str(episode.id))
    return {"episode_id": str(episode.id)}
