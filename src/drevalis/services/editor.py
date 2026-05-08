"""EditorService — video edit-session orchestration.

Layering: keeps the route file free of repository imports, FFmpeg
subprocess invocation, and on-disk JSON I/O for captions (audit F-A-01).

The service exposes plain async methods; the route wraps the heavier
ones (session lookup, seeding) in try/except to preserve the rich
``migration_missing`` / ``session_lookup_failed`` error shapes that
ops engineers rely on for diagnosis.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.repositories.episode import EpisodeRepository
from drevalis.repositories.media_asset import MediaAssetRepository
from drevalis.repositories.video_edit_session import VideoEditSessionRepository
from drevalis.schemas.script import EpisodeScript

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from drevalis.models.video_edit_session import VideoEditSession

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class WaveformRenderError(Exception):
    """Raised when ffmpeg returned non-zero rendering a waveform PNG."""


class EditorService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        storage_base_path: Path,
        ffmpeg_path: str,
    ) -> None:
        self._db = db
        self._storage = Path(storage_base_path)
        self._ffmpeg = ffmpeg_path
        self._episodes = EpisodeRepository(db)
        self._sessions = VideoEditSessionRepository(db)
        self._assets = MediaAssetRepository(db)

    # ── Session CRUD + auto-seed ─────────────────────────────────────────

    async def get_or_create(self, episode_id: UUID) -> tuple[VideoEditSession, str | None]:
        """Return the session for *episode_id*, creating it from current
        scene state if absent. Also returns the final-video asset path
        (or None) so the route can include it in the response.
        """
        episode = await self._episodes.get_by_id(episode_id)
        if episode is None:
            raise NotFoundError("Episode", episode_id)

        session = await self._sessions.get_by_episode(episode_id)
        if session is None:
            try:
                timeline = await self._seed_timeline(episode_id)
            except Exception as exc:
                logger.warning(
                    "editor_fell_back_to_empty_timeline",
                    episode_id=str(episode_id),
                    reason=f"{type(exc).__name__}: {exc}",
                )
                timeline = {"duration_s": 0.0, "tracks": []}
            session = await self._sessions.create(
                episode_id=episode_id, version=1, timeline=timeline
            )
            await self._db.commit()

        final_video_path = await self._final_video_path(episode_id)
        return session, final_video_path

    async def save(
        self, episode_id: UUID, timeline: dict[str, Any]
    ) -> tuple[VideoEditSession, str | None]:
        session = await self._sessions.get_by_episode(episode_id)
        if session is None:
            session = await self._sessions.create(
                episode_id=episode_id, version=1, timeline=timeline
            )
        else:
            session = await self._sessions.update(session.id, timeline=timeline) or session
        await self._db.commit()

        final_video_path = await self._final_video_path(episode_id)
        return session, final_video_path

    async def enqueue_render(self, episode_id: UUID) -> None:
        from drevalis.core.redis import get_arq_pool

        session = await self._sessions.get_by_episode(episode_id)
        if session is None:
            raise NotFoundError("VideoEditSession", episode_id)

        arq = get_arq_pool()
        await arq.enqueue_job("render_from_edit", str(episode_id))
        await self._sessions.update(session.id, last_rendered_at=datetime.now(tz=UTC))
        await self._db.commit()
        logger.info("editor_render_enqueued", episode_id=str(episode_id))

    async def enqueue_preview(self, episode_id: UUID) -> None:
        from drevalis.core.redis import get_arq_pool

        session = await self._sessions.get_by_episode(episode_id)
        if session is None:
            raise NotFoundError("VideoEditSession", episode_id)
        arq = get_arq_pool()
        await arq.enqueue_job("render_from_edit", str(episode_id), proxy=True)
        logger.info("preview_enqueued", episode_id=str(episode_id))

    # ── Captions (file-backed JSON) ──────────────────────────────────────

    def _captions_path(self, episode_id: UUID) -> Path:
        return self._storage / "episodes" / str(episode_id) / "captions" / "words.json"

    async def get_captions(self, episode_id: UUID) -> list[dict[str, Any]]:
        if await self._episodes.get_by_id(episode_id) is None:
            raise NotFoundError("Episode", episode_id)

        path = self._captions_path(episode_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                words: list[dict[str, Any]] = list(data.get("words", []))
                return words
            except Exception:
                pass
        return []

    async def put_captions(self, episode_id: UUID, words: list[dict[str, Any]]) -> None:
        if await self._episodes.get_by_id(episode_id) is None:
            raise NotFoundError("Episode", episode_id)
        path = self._captions_path(episode_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"words": words}, ensure_ascii=False), encoding="utf-8")
        logger.info("captions_overwritten", episode_id=str(episode_id), words=len(words))

    # ── Waveform render ──────────────────────────────────────────────────

    async def render_waveform(self, episode_id: UUID, track: str) -> Path:
        if track not in ("voice", "music"):
            raise ValidationError("track must be 'voice' or 'music'")

        asset_type = "voiceover" if track == "voice" else "music"
        assets = await self._assets.get_by_episode_and_type(episode_id, asset_type)
        if not assets:
            # Music may live in episode.metadata_.selected_music_path instead.
            if track == "music":
                ep = await self._episodes.get_by_id(episode_id)
                if ep:
                    meta = ep.metadata_ or {}
                    path = meta.get("selected_music_path") if isinstance(meta, dict) else None
                    if path:
                        src_path = self._storage / path
                        return await self._render_waveform_png(src_path, track)
            raise NotFoundError("AudioAsset", episode_id)

        src_path = self._storage / assets[-1].file_path
        return await self._render_waveform_png(src_path, track)

    async def _render_waveform_png(self, src: Path, track: str) -> Path:
        """Idempotent ffmpeg ``showwavespic`` render. Cached next to the
        source by mtime — regenerates only when the source is newer."""
        out = src.parent / f"waveform_{track}.png"
        if out.exists() and src.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return out

        cmd = [
            self._ffmpeg,
            "-y",
            "-i",
            str(src),
            "-filter_complex",
            "showwavespic=s=1600x160:colors=#7c8cff",
            "-frames:v",
            "1",
            str(out),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        if rc != 0 or not out.exists():
            raise WaveformRenderError("waveform render failed")
        return out

    # ── Internal: timeline seed + final-video lookup ─────────────────────

    async def _final_video_path(self, episode_id: UUID) -> str | None:
        final_videos = await self._assets.get_by_episode_and_type(episode_id, "video")
        return final_videos[-1].file_path if final_videos else None

    async def _seed_timeline(self, episode_id: UUID) -> dict[str, Any]:
        episode = await self._episodes.get_by_id(episode_id)
        if episode is None:
            return {"duration_s": 0.0, "tracks": []}

        video_clips: list[dict[str, Any]] = []
        voice_clips: list[dict[str, Any]] = []
        music_clips: list[dict[str, Any]] = []

        running = 0.0
        script: EpisodeScript | None = None
        if episode.script:
            raw_script = dict(episode.script) if isinstance(episode.script, dict) else {}
            if not raw_script.get("title"):
                raw_script["title"] = episode.title or "Untitled episode"
            try:
                script = EpisodeScript.model_validate(raw_script)
            except Exception as exc:
                logger.warning(
                    "editor_seed_script_invalid",
                    episode_id=str(episode_id),
                    error=str(exc)[:200],
                )
                script = None

        if script:
            scene_assets_by_number: dict[int, Any] = {}
            for a in await self._assets.get_by_episode_and_type(episode_id, "scene"):
                if a.scene_number is not None:
                    scene_assets_by_number[a.scene_number] = a
            for a in await self._assets.get_by_episode_and_type(episode_id, "scene_video"):
                if a.scene_number is not None:
                    scene_assets_by_number[a.scene_number] = a

            for scene in script.scenes:
                dur = float(scene.duration_seconds or 0)
                asset = scene_assets_by_number.get(scene.scene_number)
                video_clips.append(
                    {
                        "id": f"v-{scene.scene_number}",
                        "scene_number": scene.scene_number,
                        "source": "scene",
                        "asset_path": asset.file_path if asset else None,
                        "in_s": 0.0,
                        "out_s": dur,
                        "start_s": round(running, 3),
                        "end_s": round(running + dur, 3),
                        "speed": 1.0,
                    }
                )
                running += dur

        voiceovers = await self._assets.get_by_episode_and_type(episode_id, "voiceover")
        if voiceovers:
            va = voiceovers[-1]
            dur_s = (
                float(va.duration_seconds) if va.duration_seconds is not None else float(running)
            )
            voice_clips.append(
                {
                    "id": "voice-main",
                    "asset_path": va.file_path,
                    "in_s": 0.0,
                    "out_s": dur_s,
                    "start_s": 0.0,
                    "end_s": dur_s,
                    "gain_db": 0.0,
                }
            )

        meta = episode.metadata_ or {}
        selected_music_path = meta.get("selected_music_path") if isinstance(meta, dict) else None
        if selected_music_path:
            music_clips.append(
                {
                    "id": "music-main",
                    "asset_path": selected_music_path,
                    "in_s": 0.0,
                    "out_s": running,
                    "start_s": 0.0,
                    "end_s": running,
                    "gain_db": -18.0,
                    "duck_to_voice": True,
                }
            )

        timeline: dict[str, Any] = {
            "duration_s": round(running, 3),
            "tracks": [
                {"id": "video", "kind": "video", "clips": video_clips},
                {"id": "voice", "kind": "audio", "clips": voice_clips},
                {"id": "music", "kind": "audio", "clips": music_clips},
                {"id": "overlay", "kind": "overlay", "clips": []},
                {"id": "captions", "kind": "captions", "clips": []},
            ],
        }
        cleaned = _jsonable(timeline)
        assert isinstance(cleaned, dict), "timeline must remain a dict after coercion"
        return cleaned


def _jsonable(obj: Any) -> Any:
    """Coerce Decimal → float recursively (JSONB serialization barfs on Decimal)."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return [_jsonable(v) for v in obj]
    return obj


__all__ = ["EditorService", "WaveformRenderError"]
