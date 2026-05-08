"""ID3 tag + chapter writer for audiobook MP3 output.

Adds the metadata commonly required by distribution platforms (Audible,
Apple Books, Google Play Books) onto the final ``.mp3``:

- TIT2, TPE1, TALB, TCON, TYER   standard title / artist / album / genre / year
- APIC                           embedded cover image (JPEG or PNG)
- CHAP + CTOC                    ID3v2.3 chapter frames; each chapter gets a
                                 start/end timecode and a TIT2 sub-frame
                                 carrying its title

Pure I/O on a file already produced by FFmpeg - no audio re-encoding.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _extension_to_mime(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    return "application/octet-stream"


def _write_sync(
    mp3_path: Path,
    *,
    title: str,
    artist: str,
    album: str | None,
    genre: str,
    year: int | None,
    chapters: list[dict[str, Any]] | None,
    cover_bytes: bytes | None,
    cover_mime: str | None,
) -> None:
    """Blocking ID3 write - call inside ``asyncio.to_thread``."""
    from mutagen.id3 import (
        APIC,
        CHAP,
        CTOC,
        ID3,
        TALB,
        TCON,
        TIT2,
        TPE1,
        TYER,
        CTOCFlags,
        ID3NoHeaderError,
    )

    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    tags["TIT2"] = TIT2(encoding=3, text=title)
    tags["TPE1"] = TPE1(encoding=3, text=artist)
    if album:
        tags["TALB"] = TALB(encoding=3, text=album)
    tags["TCON"] = TCON(encoding=3, text=genre)
    if year is not None:
        tags["TYER"] = TYER(encoding=3, text=str(year))

    if cover_bytes and cover_mime:
        tags.delall("APIC")
        tags.add(
            APIC(
                encoding=3,
                mime=cover_mime,
                type=3,  # front cover
                desc="Cover",
                data=cover_bytes,
            )
        )

    # Chapters: one CHAP frame per chapter + a CTOC describing the list.
    if chapters:
        # Drop any previous chapter frames before rewriting.
        tags.delall("CHAP")
        tags.delall("CTOC")

        chapter_ids: list[str] = []
        for i, ch in enumerate(chapters):
            start_ms = int(float(ch.get("start_seconds", 0.0)) * 1000)
            end_ms = int(float(ch.get("end_seconds", start_ms / 1000.0)) * 1000)
            if end_ms <= start_ms:
                end_ms = start_ms + 1  # guard against zero-length frames
            chap_id = f"chp{i:03d}"
            chapter_ids.append(chap_id)
            chap_title = ch.get("title") or f"Chapter {i + 1}"
            tags.add(
                CHAP(
                    element_id=chap_id,
                    start_time=start_ms,
                    end_time=end_ms,
                    sub_frames=[TIT2(encoding=3, text=chap_title)],
                )
            )

        tags.add(
            CTOC(
                element_id="toc",
                flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
                child_element_ids=chapter_ids,
                sub_frames=[TIT2(encoding=3, text="Chapters")],
            )
        )

    # v2.3 is the ID3 dialect most audiobook apps parse reliably.
    tags.save(mp3_path, v2_version=3)


async def write_audiobook_id3(
    mp3_path: Path,
    *,
    title: str,
    artist: str = "Drevalis Creator Studio",
    album: str | None = None,
    genre: str = "Audiobook",
    year: int | None = None,
    chapters: list[dict[str, Any]] | None = None,
    cover_path: Path | None = None,
) -> None:
    """Write ID3 tags + chapter frames onto *mp3_path*.

    Cover image is read from ``cover_path`` if provided and its MIME is
    inferred from the file extension. All I/O happens in a worker thread
    so the async caller isn't blocked.
    """
    cover_bytes: bytes | None = None
    cover_mime: str | None = None
    if cover_path and cover_path.exists():
        try:
            cover_bytes = cover_path.read_bytes()
            cover_mime = _extension_to_mime(cover_path.suffix)
        except OSError as exc:
            logger.warning("audiobook.id3.cover_read_failed", exc_info=exc)

    year_to_use = year if year is not None else datetime.datetime.now(datetime.UTC).year

    await asyncio.to_thread(
        _write_sync,
        mp3_path,
        title=title,
        artist=artist,
        album=album,
        genre=genre,
        year=year_to_use,
        chapters=chapters,
        cover_bytes=cover_bytes,
        cover_mime=cover_mime,
    )
    logger.info(
        "audiobook.id3.written",
        extra={
            "path": str(mp3_path),
            "chapters": len(chapters) if chapters else 0,
            "has_cover": cover_bytes is not None,
        },
    )
