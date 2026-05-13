"""Export + video-editor sub-routes for an episode.

Owns:
  * ``GET  /{episode_id}/export/video``       — friendly-named MP4 download
  * ``GET  /{episode_id}/export/thumbnail``   — friendly-named JPG download
  * ``POST /{episode_id}/thumbnail``          — upload custom thumbnail
  * ``GET  /{episode_id}/export/description`` — plain-text description
  * ``GET  /{episode_id}/export/bundle``      — ZIP (video + thumb + desc + srt)
  * ``GET  /{episode_id}/export/raw-assets``  — ZIP of every scene asset
  * ``POST /{episode_id}/edit``               — apply video edits
  * ``POST /{episode_id}/edit/preview``       — low-res preview render
  * ``POST /{episode_id}/edit/reset``         — restore the assembly output

Extracted from ``_monolith.py`` (alpha.28). ``_sanitize_filename``,
``_load_episode_with_series``, and ``_build_description`` live here
because nothing else uses them.
"""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response

from drevalis.api.routes.episodes._helpers import _episode_service, logger
from drevalis.core.config import Settings
from drevalis.core.deps import get_settings
from drevalis.models.episode import Episode
from drevalis.schemas.episode import VideoEditRequest, VideoEditResponse
from drevalis.schemas.script import EpisodeScript
from drevalis.services.episode import (
    EpisodeNotFoundError,
    EpisodeService,
)

router = APIRouter(prefix="/api/v1/episodes", tags=["episodes"])


# ── Export helpers ────────────────────────────────────────────────────────


def _sanitize_filename(series_name: str, episode_title: str) -> str:
    """Build a filesystem-safe filename from series and episode names."""
    raw = f"{series_name}_{episode_title}"
    safe = re.sub(r"[^\w\s-]", "", raw)
    safe = re.sub(r"\s+", "_", safe.strip())
    return safe[:100] or "export"


async def _load_episode_with_series(episode_id: UUID, svc: EpisodeService) -> Episode:
    """Thin wrapper around ``EpisodeService.get_with_series_or_raise``
    that maps NotFound → 404 so the export endpoints stay terse."""
    try:
        return await svc.get_with_series_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Episode {episode_id} not found",
        ) from exc


def _build_description(episode: Episode) -> str:
    """Build a text description from the episode's script and series metadata."""
    script = None
    if episode.script:
        try:
            script = EpisodeScript.model_validate(episode.script)
        except Exception:
            pass

    lines: list[str] = []
    lines.append(script.title if script else episode.title)
    lines.append("")

    if script and script.description:
        lines.append(script.description)
        lines.append("")

    if script and script.hashtags:
        lines.append(" ".join(f"#{tag}" for tag in script.hashtags))
        lines.append("")

    series_name = episode.series.name if episode.series else "N/A"
    lines.append(f"Series: {series_name}")
    lines.append("")

    lines.append("--- Script ---")
    if script:
        for scene in script.scenes:
            lines.append(f"\n[Scene {scene.scene_number}]")
            lines.append(scene.narration)

    return "\n".join(lines)


# ── Export video ─────────────────────────────────────────────────────────


@router.get(
    "/{episode_id}/export/video",
    status_code=status.HTTP_200_OK,
    summary="Download the final video with a friendly filename",
    tags=["export"],
)
async def export_video(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> FileResponse:
    """Serve the episode's final video file with a sanitized filename."""
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    rel = await svc.get_video_asset_path(episode_id)
    if rel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode",
        )
    video_path = Path(settings.storage_base_path) / rel
    if not video_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file not found on disk",
        )

    logger.info("export_video", episode_id=str(episode_id), path=str(video_path))
    return FileResponse(
        path=str(video_path),
        filename=f"{safe_name}.mp4",
        media_type="video/mp4",
    )


# ── Export thumbnail ─────────────────────────────────────────────────────


@router.get(
    "/{episode_id}/export/thumbnail",
    status_code=status.HTTP_200_OK,
    summary="Download the thumbnail image with a friendly filename",
    tags=["export"],
)
async def export_thumbnail(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> FileResponse:
    """Serve the episode's thumbnail image with a sanitized filename."""
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    rel = await svc.get_thumbnail_asset_path(episode_id)
    if rel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No thumbnail asset found for this episode",
        )
    thumb_path = Path(settings.storage_base_path) / rel
    if not thumb_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail file not found on disk",
        )

    logger.info("export_thumbnail", episode_id=str(episode_id), path=str(thumb_path))
    return FileResponse(
        path=str(thumb_path),
        filename=f"{safe_name}_thumbnail.jpg",
        media_type="image/jpeg",
    )


# ── Upload custom thumbnail ──────────────────────────────────────────────


@router.post(
    "/{episode_id}/thumbnail",
    status_code=status.HTTP_200_OK,
    summary="Replace the episode's thumbnail with a user-uploaded image",
    tags=["thumbnail"],
)
async def upload_thumbnail(
    episode_id: UUID,
    file: UploadFile = File(
        ...,
        description="PNG or JPEG. Max 4 MB. Saved as storage/episodes/{id}/output/thumbnail.jpg.",
    ),
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> dict[str, Any]:
    """Accept a user-edited thumbnail image and replace the episode's
    thumbnail asset.

    Used by the in-app thumbnail editor — the frontend renders the
    composited image (base + text overlay) on a Canvas, exports to PNG,
    and POSTs the blob here. Any previous thumbnail MediaAsset rows are
    deleted so the freshly-uploaded file is the single source of truth.
    """
    content_type = (file.content_type or "").lower()
    if content_type not in ("image/png", "image/jpeg", "image/jpg"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error": "unsupported_image_type",
                "hint": "Upload a PNG or JPEG.",
                "received": content_type or "(missing)",
            },
        )

    MAX_BYTES = 4 * 1024 * 1024
    data = bytearray()
    while chunk := await file.read(64 * 1024):
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "error": "thumbnail_too_large",
                    "hint": f"Max {MAX_BYTES // 1024 // 1024} MB.",
                },
            )

    try:
        await svc.get_or_raise(episode_id)
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="episode_not_found",
        ) from exc

    # CodeQL py/path-injection: textbook ``os.path.realpath`` +
    # ``str.startswith`` containment on strings before any pathlib
    # touches user input. Preserved verbatim from the monolith — see
    # CHANGELOG alpha.16-.20 for the iteration history.
    import os
    import os.path as _osp

    safe_episode_id = _osp.basename(str(episode_id))
    base_real = _osp.realpath(str(settings.storage_base_path))
    candidate_real = _osp.realpath(
        _osp.join(base_real, "episodes", safe_episode_id, "output", "thumbnail.jpg")
    )
    if not (
        candidate_real == base_real
        or candidate_real.startswith(base_real + os.sep)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid episode path",
        )
    rel_path = f"episodes/{safe_episode_id}/output/thumbnail.jpg"
    os.makedirs(_osp.dirname(candidate_real), exist_ok=True)

    from io import BytesIO

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - Pillow ships with the image deps
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pillow not installed; thumbnail editor requires it",
        ) from exc

    try:
        img: Any = Image.open(BytesIO(bytes(data)))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        img.save(candidate_real, format="JPEG", quality=92, optimize=True)
    except Exception as exc:
        logger.error("thumbnail_upload_decode_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not decode uploaded image.",
        ) from exc

    file_size = _osp.getsize(candidate_real)

    new_asset = await svc.replace_thumbnail_asset(
        episode_id, rel_path=rel_path, file_size=file_size
    )

    logger.info(
        "thumbnail_uploaded",
        episode_id=str(episode_id),
        size_bytes=file_size,
        asset_id=str(new_asset.id),
    )
    return {
        "message": "Thumbnail replaced.",
        "asset_id": str(new_asset.id),
        "file_path": rel_path,
        "size_bytes": file_size,
    }


# ── Export description ───────────────────────────────────────────────────


@router.get(
    "/{episode_id}/export/description",
    status_code=status.HTTP_200_OK,
    summary="Download a text description file for the episode",
    tags=["export"],
)
async def export_description(
    episode_id: UUID,
    svc: EpisodeService = Depends(_episode_service),
) -> Response:
    """Generate and serve a plain-text description file with title, description,
    hashtags, series info, and full script narration."""
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    content = _build_description(episode)

    logger.info("export_description", episode_id=str(episode_id))
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_description.txt"',
        },
    )


# ── Export bundle (ZIP) ──────────────────────────────────────────────────


@router.get(
    "/{episode_id}/export/bundle",
    status_code=status.HTTP_200_OK,
    summary="Download a ZIP bundle with video, thumbnail, description, and captions",
    tags=["export"],
)
async def export_bundle(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> Response:
    """Create an in-memory ZIP archive containing the video, thumbnail,
    description text, and SRT captions (when available)."""
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    base = Path(settings.storage_base_path)
    video_rel = await svc.get_video_asset_path(episode_id)
    thumb_rel = await svc.get_thumbnail_asset_path(episode_id)
    caption_rel = await svc.get_caption_asset_path(episode_id)

    if video_rel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode; cannot create bundle",
        )

    description_content = _build_description(episode)
    video_path = base / video_rel
    thumb_path = (base / thumb_rel) if thumb_rel else None
    srt_path = (base / caption_rel) if caption_rel else None

    def _build() -> bytes:
        # MP4/JPG/SRT are already compressed (or tiny); ZIP_STORED keeps
        # the bundle ~the same size and skips the DEFLATE CPU cost
        # which previously blocked the uvicorn event loop for several
        # seconds on a 100 MB+ video.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            if video_path.exists():
                zf.write(str(video_path), f"{safe_name}.mp4")
            if thumb_path and thumb_path.exists():
                zf.write(str(thumb_path), f"{safe_name}_thumbnail.jpg")
            zf.writestr(f"{safe_name}_description.txt", description_content)
            if srt_path and srt_path.exists():
                zf.write(str(srt_path), f"{safe_name}_captions.srt")
        return buf.getvalue()

    payload = await asyncio.to_thread(_build)

    logger.info("export_bundle", episode_id=str(episode_id), zip_size=len(payload))
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_bundle.zip"',
        },
    )


# ── Export raw assets (per-scene ZIP) ─────────────────────────────────────


@router.get(
    "/{episode_id}/export/raw-assets",
    status_code=status.HTTP_200_OK,
    summary="Download a ZIP of every per-scene image, voice segment, and caption asset",
    tags=["export"],
)
async def export_raw_assets(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> Response:
    """Zip every raw generation asset — one file per scene image, per
    voice segment, the final composited assets, and any ASS/SRT caption
    files. Useful for debugging, moving content between installs, or
    cherry-picking scenes for a manual re-edit outside the pipeline.
    """
    episode = await _load_episode_with_series(episode_id, svc)
    series_name = episode.series.name if episode.series else "Short"
    safe_name = _sanitize_filename(series_name, episode.title)

    base = Path(settings.storage_base_path)

    all_assets = await svc.get_all_assets(episode_id)
    if not all_assets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No media assets found for this episode yet",
        )

    per_kind: dict[str, list[Any]] = {}
    for a in all_assets:
        per_kind.setdefault(a.asset_type, []).append(a)

    def _build() -> tuple[bytes, dict[str, int]]:
        included: dict[str, int] = {}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for kind, assets in per_kind.items():
                assets.sort(key=lambda a: (a.scene_number or 0, a.created_at or 0))
                for a in assets:
                    src = base / a.file_path
                    if not src.exists():
                        continue
                    ext = Path(a.file_path).suffix or ""
                    if a.scene_number is not None:
                        entry = f"{safe_name}/{kind}/{kind}_{a.scene_number:02d}{ext}"
                    else:
                        entry = f"{safe_name}/{kind}/{kind}{ext}"
                        if included.get(kind):
                            entry = f"{safe_name}/{kind}/{kind}_{str(a.id)[:8]}{ext}"
                    zf.write(str(src), entry)
                    included[kind] = included.get(kind, 0) + 1

            readme_lines = [
                f"Drevalis raw-assets export for: {series_name} — {episode.title}",
                f"Episode ID: {episode.id}",
                f"Generated: {episode.created_at}",
                "",
                "Contents:",
            ]
            for kind, count in sorted(included.items()):
                readme_lines.append(f"  {kind:<12} {count} file(s)")
            readme_lines.append("")
            readme_lines.append(
                "Regenerating any asset rebuilds the database row with a new "
                "UUID — so re-running an export after edits will overwrite this "
                "archive, not merge with it."
            )
            zf.writestr(f"{safe_name}/README.txt", "\n".join(readme_lines))
        return buf.getvalue(), included

    payload, included = await asyncio.to_thread(_build)
    logger.info(
        "export_raw_assets",
        episode_id=str(episode_id),
        zip_size=len(payload),
        kinds=list(per_kind.keys()),
    )
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_raw_assets.zip"',
        },
    )


# ── Video editing ─────────────────────────────────────────────────────────


@router.post(
    "/{episode_id}/edit",
    response_model=VideoEditResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply video edits (trim, border, effects) and save",
)
async def edit_video(
    episode_id: UUID,
    payload: VideoEditRequest,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> VideoEditResponse:
    """Apply edits to the episode's final video.

    Backs up the original video on first edit so it can be restored via
    the ``/edit/reset`` endpoint.
    """
    from drevalis.services.ffmpeg import FFmpegService

    base = Path(settings.storage_base_path)
    video_asset = await svc.get_latest_video_asset(episode_id)
    if video_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode",
        )
    video_path = base / video_asset.file_path
    if not video_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file not found on disk",
        )

    original_path = video_path.parent / "final_original.mp4"
    if not original_path.exists():
        import shutil

        await asyncio.to_thread(shutil.copy2, str(video_path), str(original_path))

    ffmpeg = FFmpegService(ffmpeg_path=settings.ffmpeg_path)
    edited_path = video_path.parent / "final_edited.mp4"

    await ffmpeg.apply_video_effects(
        input_path=original_path,
        output_path=edited_path,
        start_seconds=payload.trim_start,
        end_seconds=payload.trim_end,
        border_width=payload.border.width if payload.border else 0,
        border_color=payload.border.color if payload.border else "black",
        border_style=payload.border.style if payload.border else "solid",
        color_filter=payload.color_filter,
        speed=payload.speed,
    )

    import shutil

    await asyncio.to_thread(shutil.move, str(edited_path), str(video_path))

    duration = await ffmpeg.get_duration(video_path)
    file_size = video_path.stat().st_size
    await svc.update_asset_metadata(
        video_asset.id, file_size_bytes=file_size, duration_seconds=duration
    )

    logger.info("video_edited", episode_id=str(episode_id))
    return VideoEditResponse(
        episode_id=episode_id,
        message="Video edits applied successfully",
        video_path=video_asset.file_path,
        duration_seconds=duration,
    )


@router.post(
    "/{episode_id}/edit/preview",
    response_model=VideoEditResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a low-quality preview of video edits",
)
async def edit_preview(
    episode_id: UUID,
    payload: VideoEditRequest,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> VideoEditResponse:
    """Generate a quick low-res preview with the requested edits applied."""
    from drevalis.services.ffmpeg import FFmpegService

    base = Path(settings.storage_base_path)

    video_rel = await svc.get_video_asset_path(episode_id)
    if video_rel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode",
        )
    video_path = base / video_rel
    original_path = video_path.parent / "final_original.mp4"
    source_path = original_path if original_path.exists() else video_path

    preview_path = video_path.parent / "preview.mp4"
    ffmpeg = FFmpegService(ffmpeg_path=settings.ffmpeg_path)

    await ffmpeg.generate_preview(
        input_path=source_path,
        output_path=preview_path,
        start_seconds=payload.trim_start,
        end_seconds=payload.trim_end,
        border_width=payload.border.width if payload.border else 0,
        border_color=payload.border.color if payload.border else "black",
        border_style=payload.border.style if payload.border else "solid",
        color_filter=payload.color_filter,
        speed=payload.speed,
    )

    preview_relative = f"episodes/{episode_id}/output/preview.mp4"
    duration = await ffmpeg.get_duration(preview_path)

    return VideoEditResponse(
        episode_id=episode_id,
        message="Preview generated",
        video_path=preview_relative,
        duration_seconds=duration,
    )


@router.post(
    "/{episode_id}/edit/reset",
    response_model=VideoEditResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset video to the original assembly output",
)
async def edit_reset(
    episode_id: UUID,
    settings: Settings = Depends(get_settings),
    svc: EpisodeService = Depends(_episode_service),
) -> VideoEditResponse:
    """Restore the original assembled video, undoing all edits."""
    from drevalis.services.ffmpeg import FFmpegService

    base = Path(settings.storage_base_path)
    video_asset = await svc.get_latest_video_asset(episode_id)
    if video_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video asset found for this episode",
        )

    video_path = base / video_asset.file_path
    original_path = video_path.parent / "final_original.mp4"
    if not original_path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No original video backup found -- video has not been edited",
        )

    import shutil

    await asyncio.to_thread(shutil.copy2, str(original_path), str(video_path))

    ffmpeg = FFmpegService(ffmpeg_path=settings.ffmpeg_path)
    duration = await ffmpeg.get_duration(video_path)
    file_size = video_path.stat().st_size
    await svc.update_asset_metadata(
        video_asset.id, file_size_bytes=file_size, duration_seconds=duration
    )

    preview_path = video_path.parent / "preview.mp4"
    if preview_path.exists():
        preview_path.unlink()

    logger.info("video_edit_reset", episode_id=str(episode_id))
    return VideoEditResponse(
        episode_id=episode_id,
        message="Video restored to original",
        video_path=video_asset.file_path,
        duration_seconds=duration,
    )
