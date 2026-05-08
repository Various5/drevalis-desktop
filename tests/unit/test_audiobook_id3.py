"""Tests for ID3 + chapter writer (services/audiobook/id3.py).

The writer attaches metadata audiobook stores need (Audible, Apple
Books, Google Play). Misses cause silent metadata loss after upload.
Each branch is pinned by writing into a tiny synthesized MP3 and
re-reading the tags via mutagen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from drevalis.services.audiobook.id3 import (
    _extension_to_mime,
    write_audiobook_id3,
)

# ── _extension_to_mime ───────────────────────────────────────────────


class TestExtensionToMime:
    @pytest.mark.parametrize(
        ("ext", "mime"),
        [
            ("jpg", "image/jpeg"),
            ("jpeg", "image/jpeg"),
            ("png", "image/png"),
            ("webp", "image/webp"),
            (".jpg", "image/jpeg"),  # leading-dot tolerated
            (".PNG", "image/png"),  # case-insensitive
        ],
    )
    def test_known_extensions(self, ext: str, mime: str) -> None:
        assert _extension_to_mime(ext) == mime

    def test_unknown_extension_falls_back(self) -> None:
        assert _extension_to_mime("xyz") == "application/octet-stream"

    def test_empty_extension_falls_back(self) -> None:
        assert _extension_to_mime("") == "application/octet-stream"


# ── Real-MP3 synth helper ───────────────────────────────────────────


def _make_minimal_mp3(path: Path) -> None:
    """Write a tiny but valid MPEG-1 Layer III file.

    mutagen.id3 needs a valid MPEG header to attach tags to; a single
    silent frame is enough. Header bits:
      sync=0xFFFB (MPEG-1 layer III, no CRC), bitrate index=9 (128 kbps),
      sample rate index=0 (44.1 kHz), padding=0, channel mode=stereo.
    Frame size at 128/44.1 = 417 bytes (rounded; mutagen won't choke on
    a slightly short file as long as the header parses).
    """
    # Frame header bytes for 128 kbps / 44.1 kHz / stereo MPEG-1 Layer III.
    header = bytes([0xFF, 0xFB, 0x90, 0x64])
    # Pad with silence to make a plausible-looking frame.
    payload = b"\x00" * 412
    path.write_bytes(header + payload)


# ── write_audiobook_id3 ──────────────────────────────────────────────


class TestWriteAudiobookId3:
    async def test_basic_tags_written(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)

        await write_audiobook_id3(
            mp3,
            title="My Book",
            artist="Test Author",
            album="Volume 1",
            genre="Fiction",
            year=2026,
        )

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        assert tags["TIT2"].text[0] == "My Book"
        assert tags["TPE1"].text[0] == "Test Author"
        assert tags["TALB"].text[0] == "Volume 1"
        assert tags["TCON"].text[0] == "Fiction"
        # Mutagen normalises TYER → TDRC on read regardless of v2_version
        # at write time. Match against whichever shape is present.
        year_frame = tags.get("TYER") or tags.get("TDRC")
        assert year_frame is not None
        assert "2026" in str(year_frame.text[0])

    async def test_default_artist_is_drevalis(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(mp3, title="X")

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        assert tags["TPE1"].text[0] == "Drevalis Creator Studio"

    async def test_default_genre_is_audiobook(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(mp3, title="X")

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        assert tags["TCON"].text[0] == "Audiobook"

    async def test_album_omitted_when_none(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(mp3, title="X", album=None)

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        assert "TALB" not in tags

    async def test_year_defaults_to_current(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(mp3, title="X")

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        # Either 2025 or 2026 — don't pin a specific year, just confirm
        # it's a 4-digit year string and not empty. Mutagen may store
        # under TYER or TDRC depending on its internal normalisation.
        year_frame = tags.get("TYER") or tags.get("TDRC")
        assert year_frame is not None
        year_str = str(year_frame.text[0])
        # TDRC parses to a date object; first 4 chars are the year.
        assert year_str[:4].isdigit()
        assert len(year_str) >= 4

    async def test_chapters_written(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        chapters = [
            {"title": "Intro", "start_seconds": 0.0, "end_seconds": 30.0},
            {"title": "Chapter 1", "start_seconds": 30.0, "end_seconds": 120.5},
            {"title": "Chapter 2", "start_seconds": 120.5, "end_seconds": 200.0},
        ]
        await write_audiobook_id3(mp3, title="X", chapters=chapters)

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        chap_keys = [k for k in tags if k.startswith("CHAP:")]
        assert len(chap_keys) == 3
        # CTOC frame describes the chapter list.
        assert any(k.startswith("CTOC:") for k in tags)

    async def test_chapter_timecodes_milliseconds(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(
            mp3,
            title="X",
            chapters=[
                {"title": "C1", "start_seconds": 1.5, "end_seconds": 3.25},
            ],
        )

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        chap = next(v for k, v in tags.items() if k.startswith("CHAP:"))
        assert chap.start_time == 1500
        assert chap.end_time == 3250

    async def test_chapter_with_zero_length_extended_to_one_ms(self, tmp_path: Path) -> None:
        # Defensive: end <= start is invalid in ID3 chapter frames; the
        # writer must clamp end = start + 1ms so the file still parses.
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(
            mp3,
            title="X",
            chapters=[{"title": "C1", "start_seconds": 5.0, "end_seconds": 5.0}],
        )

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        chap = next(v for k, v in tags.items() if k.startswith("CHAP:"))
        assert chap.end_time > chap.start_time

    async def test_chapter_default_title_uses_index(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(
            mp3,
            title="X",
            chapters=[
                {"start_seconds": 0.0, "end_seconds": 10.0},  # no title
                {"title": "", "start_seconds": 10.0, "end_seconds": 20.0},
            ],
        )

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        # Both chapters got auto-titled "Chapter 1" / "Chapter 2".
        chap_titles = [
            v.sub_frames["TIT2"].text[0] for k, v in sorted(tags.items()) if k.startswith("CHAP:")
        ]
        assert chap_titles == ["Chapter 1", "Chapter 2"]

    async def test_chapter_rewrite_replaces_previous(self, tmp_path: Path) -> None:
        # Calling twice must NOT accumulate chapters — the second call
        # replaces the first set.
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(
            mp3,
            title="X",
            chapters=[{"title": "Old", "start_seconds": 0.0, "end_seconds": 10.0}],
        )
        await write_audiobook_id3(
            mp3,
            title="X",
            chapters=[
                {"title": "New1", "start_seconds": 0.0, "end_seconds": 5.0},
                {"title": "New2", "start_seconds": 5.0, "end_seconds": 10.0},
            ],
        )

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        chap_keys = sorted(k for k in tags if k.startswith("CHAP:"))
        assert len(chap_keys) == 2

    async def test_cover_image_attached(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        cover = tmp_path / "cover.jpg"
        # 1x1 white JPEG is fine — mutagen doesn't validate bytes.
        cover.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        await write_audiobook_id3(mp3, title="X", cover_path=cover)

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        apics = tags.getall("APIC")
        assert len(apics) == 1
        assert apics[0].mime == "image/jpeg"
        assert apics[0].type == 3  # front cover
        assert apics[0].data.startswith(b"\xff\xd8\xff\xe0")

    async def test_cover_image_replaced_on_rewrite(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        cover_a = tmp_path / "a.png"
        cover_a.write_bytes(b"AAA" + b"\x00" * 100)
        cover_b = tmp_path / "b.jpg"
        cover_b.write_bytes(b"BBB" + b"\x00" * 100)

        await write_audiobook_id3(mp3, title="X", cover_path=cover_a)
        await write_audiobook_id3(mp3, title="X", cover_path=cover_b)

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        apics = tags.getall("APIC")
        assert len(apics) == 1
        assert apics[0].mime == "image/jpeg"
        assert apics[0].data.startswith(b"BBB")

    async def test_missing_cover_path_silently_skipped(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(
            mp3,
            title="X",
            cover_path=tmp_path / "ghost.jpg",  # doesn't exist
        )

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        assert tags.getall("APIC") == []

    async def test_id3_v2_3_dialect(self, tmp_path: Path) -> None:
        # Audiobook apps (Audible) parse v2.3 most reliably; the writer
        # pins version=3.
        mp3 = tmp_path / "book.mp3"
        _make_minimal_mp3(mp3)
        await write_audiobook_id3(mp3, title="X")

        from mutagen.id3 import ID3

        tags = ID3(mp3)
        # version is a tuple like (2, 3, 0).
        assert tags.version[0] == 2
        assert tags.version[1] == 3
