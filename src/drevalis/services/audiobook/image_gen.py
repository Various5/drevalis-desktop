"""Per-chapter image generation for audiobooks.

Handles two image-generation strategies:

- ``_generate_chapter_images``: submits one ComfyUI job per chapter using
  the ``qwen_image_2512`` workflow, with a concurrency semaphore of 3.
  Falls back to a title card when ComfyUI is unavailable or the job fails.
- ``_generate_title_card``: renders a plain FFmpeg drawtext title card (or a
  solid-colour fallback) so the video assembler always has a real image input.

Both are pure functions — ``AudiobookService`` delegates to them via thin
shims so existing callers that patch instance methods continue to work.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from drevalis.services.comfyui import ComfyUIService

log = structlog.get_logger(__name__)


async def _generate_title_card(
    output_dir: Path,
    title: str,
    width: int = 1920,
    height: int = 1080,
) -> Path:
    """Generate a simple title card image using FFmpeg.

    The previous version returned the output path even when
    ffmpeg's drawtext filter rejected the title (titles with
    ``:``, ``\\``, ``%`` or other drawtext-meta characters
    crashed the filter). The path then got passed into the
    Ken-Burns assembler which choked on the missing input file:

        Error opening input file .../title_card.jpg

    The new flow:

      1. Properly escape drawtext-meta in the title (``\\``,
         ``:`` and ``'``).
      2. Try drawtext first; if ffmpeg returns non-zero OR the
         output file isn't on disk, fall back to a plain
         solid-color image so the assembler always has a real
         input.
      3. Defensive ``mkdir(parents=True)`` so a missing parent
         directory can never be the cause again.
      4. The first call writes ``title_card.jpg`` (preserved as
         the legacy filename) but subsequent calls get a unique
         slug-suffixed filename so concurrent fallbacks for
         different chapters don't race-overwrite each other.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Make the output filename unique per title so chapter-N's
    # fallback doesn't clobber chapter-(N-1)'s. Hash keeps it
    # deterministic for the "regenerate same chapter" retry case.
    slug = hashlib.sha1(
        title.encode("utf-8", errors="replace"),
        usedforsecurity=False,
    ).hexdigest()[:8]
    card_path = output_dir / f"title_card_{slug}.jpg"

    # Drawtext escaping rules: backslash escapes itself; the
    # filter argument is single-quoted so single quotes inside
    # have to be replaced (drawtext can't escape quotes inside a
    # quoted value); ``:`` is the parameter separator and must
    # be escaped; ``%`` triggers expansion and must be doubled.
    # Truncate AFTER escaping so we don't cut a half-escape.
    safe_title = (
        title.replace("\\", "\\\\")
        .replace("'", "")
        .replace('"', "")
        .replace(":", "\\:")
        .replace("%", "%%")
    )[:50] or "Audiobook"

    async def _run(cmd: list[str]) -> tuple[int, bytes]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        return proc.returncode or 0, err

    primary_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x0f0f1a:s={width}x{height}:d=1",
        "-vf",
        f"drawtext=text='{safe_title}':fontsize=64:fontcolor=white"
        f":x=(w-text_w)/2:y=(h-text_h)/2:borderw=3:bordercolor=black",
        "-frames:v",
        "1",
        str(card_path),
    ]
    rc, err = await _run(primary_cmd)
    if rc == 0 and card_path.exists() and card_path.stat().st_size > 0:
        return card_path

    log.warning(
        "audiobook.title_card.drawtext_failed",
        title=title[:80],
        rc=rc,
        stderr=err.decode("utf-8", errors="replace")[:400],
    )

    # Fallback: solid-color frame with no text. Always succeeds
    # as long as ffmpeg is on PATH and the disk has space.
    fallback_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x0f0f1a:s={width}x{height}:d=1",
        "-frames:v",
        "1",
        str(card_path),
    ]
    rc, err = await _run(fallback_cmd)
    if rc != 0 or not card_path.exists():
        raise RuntimeError(
            "Title card generation failed even with the no-text fallback. "
            f"ffmpeg rc={rc}; stderr={err.decode('utf-8', errors='replace')[:200]}"
        )
    return card_path


async def _generate_chapter_images(
    comfyui_service: ComfyUIService | None,
    cancel_fn: Callable[[], Coroutine[Any, Any, None]],
    title_card_fn: Callable[..., Coroutine[Any, Any, Path]],
    chapters: list[dict[str, Any]],
    output_dir: Path,
    audiobook_id: Any,
    video_width: int,
    video_height: int,
    chapter_indices: list[int] | None = None,
) -> list[Path]:
    """Generate an image for each chapter via ComfyUI.

    Uses the qwen_image_2512 workflow. Chapters that already have an
    ``image_path`` are skipped. Generation is parallelised with a
    concurrency semaphore of 3.

    Parameters
    ----------
    comfyui_service:
        ComfyUI service pool.  When ``None`` the function returns ``[]``
        immediately and logs a warning.
    cancel_fn:
        Awaitable that raises ``asyncio.CancelledError`` if the audiobook
        has been cancelled.  Typically ``AudiobookService._cancel``.
    title_card_fn:
        Awaitable fallback: ``_generate_title_card(output_dir, title,
        width, height)``.
    chapters:
        List of chapter dicts.
    chapter_indices:
        Optional explicit indices to use when naming output files
        (``ch{idx:03d}.png``). When ``None``, indices are derived
        from ``enumerate(chapters)``. Pass explicit indices when
        re-generating a single chapter so its existing image at
        the right index is overwritten rather than writing to
        ``ch000.png``.
    """
    if not comfyui_service:
        log.warning("audiobook.images.no_comfyui_service")
        return []

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(3)

    async def _gen_one(ch_idx: int, chapter: dict[str, Any]) -> Path | None:
        async with sem:
            # Task 10: cancel poll before each ComfyUI submit.
            await cancel_fn()
            img_path = images_dir / f"ch{ch_idx:03d}.png"

            # Skip if already exists (user-uploaded or previous run)
            if img_path.exists():
                return img_path

            # Build visual prompt from chapter content
            visual_prompt = chapter.get("visual_prompt")
            if not visual_prompt:
                title = chapter.get("title", "Scene")
                text_preview = chapter.get("text", "")[:200].replace("\n", " ")
                mood = chapter.get("music_mood", "cinematic")
                visual_prompt = (
                    f"Cinematic illustration, {title}, {mood} atmosphere, "
                    f"{text_preview}, masterpiece, ultra detailed, "
                    f"professional digital art"
                )

            try:
                # Use ComfyUI pool to generate image. Audiobooks
                # without a configured ComfyUI server have no way
                # to render chapter art — fall back to title cards
                # rather than crash with AttributeError.
                if comfyui_service is None:
                    log.info(
                        "audiobook.image_generation_skipped_no_comfyui",
                        chapter=ch_idx,
                    )
                    return None
                workflow = await comfyui_service._load_workflow("workflows/qwen_image_2512.json")

                # Inject prompt into the workflow
                if "238:227" in workflow:
                    workflow["238:227"]["inputs"]["text"] = visual_prompt
                if "238:232" in workflow:
                    workflow["238:232"]["inputs"]["width"] = video_width
                    workflow["238:232"]["inputs"]["height"] = video_height
                # Drop sampler steps from the template's 20 → 10
                # by default. Qwen-Image-2512 with the Auraflow
                # shift produces production-quality output at 10
                # steps; 20 was safety-padded and roughly doubled
                # generation time. ``AUDIOBOOK_QWEN_STEPS`` env
                # var lets power users dial it back up.
                qwen_steps = int(os.environ.get("AUDIOBOOK_QWEN_STEPS", "10"))
                if "238:230" in workflow:
                    workflow["238:230"]["inputs"]["steps"] = qwen_steps

                async with comfyui_service._pool.acquire() as (_, client):
                    prompt_id = await client.queue_prompt(workflow)
                    history = await comfyui_service._poll_until_complete(client, prompt_id)

                    output_images = comfyui_service._extract_output_images(history, "60", "images")
                    if output_images:
                        img_data = await client.download_image(
                            output_images[0]["filename"],
                            output_images[0].get("subfolder", ""),
                            output_images[0].get("type", "output"),
                        )
                        img_path.write_bytes(img_data)
                        log.info(
                            "audiobook.images.chapter_done",
                            chapter_index=ch_idx,
                            path=str(img_path),
                        )
                        return img_path

            except Exception as exc:
                log.warning(
                    "audiobook.images.chapter_failed",
                    chapter_index=ch_idx,
                    error=str(exc),
                )

            # Fallback: generate a title card
            return await title_card_fn(
                images_dir,
                chapter.get("title", f"Chapter {ch_idx + 1}"),
                width=video_width,
                height=video_height,
            )

    # Use explicit indices when given (single-chapter regen case)
    # so the output filename targets the correct slot.
    effective_indices = (
        chapter_indices if chapter_indices is not None else list(range(len(chapters)))
    )
    tasks = [_gen_one(idx, ch) for idx, ch in zip(effective_indices, chapters, strict=True)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    image_paths: list[Path] = []
    for i, result in enumerate(results):
        chapter_idx = effective_indices[i]
        if isinstance(result, Path) and result.exists():
            image_paths.append(result)
        elif isinstance(result, Exception):
            log.warning(
                "audiobook.images.chapter_exception",
                chapter_index=chapter_idx,
                error=str(result),
            )
            # Generate title card as fallback
            fallback = await title_card_fn(
                images_dir,
                chapters[i].get("title", f"Chapter {chapter_idx + 1}"),
                width=video_width,
                height=video_height,
            )
            image_paths.append(fallback)
        else:
            fallback = await title_card_fn(
                images_dir,
                chapters[i].get("title", f"Chapter {i + 1}"),
                width=video_width,
                height=video_height,
            )
            image_paths.append(fallback)

    return image_paths
