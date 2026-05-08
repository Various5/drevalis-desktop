"""Demo-mode fake pipeline.

Runs in place of ``generate_episode`` when ``settings.demo_mode=True``.
Emits the same WebSocket progress events a real run would, with
realistic step timings, then copies pre-baked sample media into the
episode's storage dir and marks the episode ``review``.

No GPU, no LLM, no ComfyUI, no FFmpeg. Safe to run on a $5 VPS.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from drevalis.schemas.progress import ProgressMessage

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Step timings deliberately vary so the progress bar doesn't look scripted.
DEMO_STEPS: tuple[tuple[str, float, int], ...] = (
    ("script", 2.5, 8),  # (name, duration seconds, tick count)
    ("voice", 6.0, 12),
    ("scenes", 18.0, 20),
    ("captions", 4.5, 8),
    ("assembly", 7.5, 12),
    ("thumbnail", 2.0, 6),
)


async def generate_episode_demo(ctx: dict[str, Any], episode_id: str) -> dict[str, Any]:
    """Scripted fake run of the 6-step pipeline.

    Drop-in replacement for ``generate_episode``. The frontend WebSocket
    handler treats the emitted messages identically to a real run.
    """
    from drevalis.core.deps import get_settings
    from drevalis.repositories.episode import EpisodeRepository
    from drevalis.repositories.generation_job import GenerationJobRepository
    from drevalis.services.storage import LocalStorage

    log = logger.bind(episode_id=episode_id, job="generate_episode_demo")
    log.info("demo_job_start")

    settings = get_settings()
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]
    storage: LocalStorage = ctx["storage"]

    parsed_id = uuid.UUID(episode_id)
    channel = f"progress:{episode_id}"

    async def publish(
        step: str,
        pct: int,
        status: str,
        message: str,
        job_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        payload = ProgressMessage(
            episode_id=episode_id,
            job_id=job_id,
            step=step,
            status=status,
            progress_pct=pct,
            message=message,
            detail=detail,
        )
        try:
            await redis.publish(channel, payload.model_dump_json())
        except Exception:
            log.debug("demo_broadcast_failed", exc_info=True)

    # Mark generating + create fake job rows that look like the real thing.
    async with session_factory() as session:
        ep_repo = EpisodeRepository(session)
        job_repo = GenerationJobRepository(session)
        await ep_repo.update_status(parsed_id, "generating")
        await session.commit()

        for step_name, _dur, _ticks in DEMO_STEPS:
            existing = await job_repo.get_latest_by_episode_and_step(parsed_id, step_name)
            if existing is None:
                await job_repo.create(
                    episode_id=parsed_id,
                    step=step_name,
                    status="queued",
                    progress_pct=0,
                )
        await session.commit()

    # Now run each step for its scripted duration, bumping progress.
    for step_name, duration, ticks in DEMO_STEPS:
        async with session_factory() as session:
            job_repo = GenerationJobRepository(session)
            job = await job_repo.get_latest_by_episode_and_step(parsed_id, step_name)
            job_id = str(job.id) if job else ""
            if job:
                await job_repo.update(
                    job.id,
                    status="running",
                    progress_pct=0,
                    started_at=datetime.now(UTC),
                    error_message=None,
                )
                await session.commit()

        await publish(step_name, 0, "running", f"Starting {step_name}...", job_id)

        # Emit progress pings across the simulated duration.
        tick_sleep = max(0.2, duration / ticks)
        for t in range(1, ticks + 1):
            await asyncio.sleep(tick_sleep)
            pct = int(100 * t / ticks)
            await publish(step_name, pct, "running", f"{step_name}: {pct}%", job_id)

        async with session_factory() as session:
            job_repo = GenerationJobRepository(session)
            job = await job_repo.get_latest_by_episode_and_step(parsed_id, step_name)
            if job:
                await job_repo.update(
                    job.id,
                    status="done",
                    progress_pct=100,
                    completed_at=datetime.now(UTC),
                )
                await session.commit()

        await publish(step_name, 100, "done", f"{step_name} complete", job_id)

    # ── Copy pre-baked media into the episode dir so the UI has content.
    await _stage_demo_assets(
        session_factory=session_factory,
        storage=storage,
        demo_assets_path=settings.demo_assets_path,
        episode_id=parsed_id,
    )

    # Mark episode ready for review.
    async with session_factory() as session:
        ep_repo = EpisodeRepository(session)
        await ep_repo.update_status(parsed_id, "review")
        await session.commit()

    log.info("demo_job_complete")
    return {"episode_id": episode_id, "status": "success", "mode": "demo"}


async def _stage_demo_assets(
    *,
    session_factory: Any,
    storage: Any,
    demo_assets_path: Path,
    episode_id: uuid.UUID,
) -> None:
    """Copy pre-baked video / thumbnail / scene images into the episode
    folder and create matching ``media_assets`` rows.

    Missing source files are tolerated silently — the demo still shows
    progress events even on a fresh install without the sample pack.
    """
    from drevalis.repositories.media_asset import MediaAssetRepository

    src = Path(demo_assets_path)
    if not src.exists():
        logger.info("demo_assets_missing", path=str(src))
        return

    episode_dir = Path(storage.base_path) / "episodes" / str(episode_id)
    video_dir = episode_dir / "output"
    thumb_dir = episode_dir / "output"
    scenes_dir = episode_dir / "scenes"
    for p in (video_dir, thumb_dir, scenes_dir):
        p.mkdir(parents=True, exist_ok=True)

    async with session_factory() as session:
        repo = MediaAssetRepository(session)

        for spec in (
            ("video.mp4", video_dir / "final.mp4", "video"),
            ("thumbnail.jpg", thumb_dir / "thumbnail.jpg", "thumbnail"),
        ):
            src_name, dest, asset_type = spec
            src_path = src / src_name
            if not src_path.exists():
                continue
            shutil.copyfile(src_path, dest)
            rel = dest.relative_to(storage.base_path).as_posix()
            await repo.create(
                episode_id=episode_id,
                asset_type=asset_type,
                file_path=rel,
                file_size_bytes=dest.stat().st_size,
            )

        # Copy scene images (scene_01.jpg .. scene_NN.jpg) if present.
        scene_idx = 1
        for scene_src in sorted(src.glob("scene_*.jpg")):
            dest = scenes_dir / f"scene_{scene_idx:02d}.jpg"
            shutil.copyfile(scene_src, dest)
            rel = dest.relative_to(storage.base_path).as_posix()
            await repo.create(
                episode_id=episode_id,
                asset_type="scene_image",
                scene_number=scene_idx,
                file_path=rel,
                file_size_bytes=dest.stat().st_size,
            )
            scene_idx += 1

        await session.commit()
