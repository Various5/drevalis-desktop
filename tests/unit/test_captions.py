"""Tests for CaptionService -- grouping, SRT/ASS formatting, timestamp generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from drevalis.services.captions import Caption, CaptionService
from drevalis.services.tts import WordTimestamp


@pytest.fixture
def caption_service() -> CaptionService:
    """Return a CaptionService instance (model not loaded for unit tests)."""
    return CaptionService(model_size="base", device="cpu")


@pytest.fixture
def basic_words() -> list[WordTimestamp]:
    """Return a simple list of word timestamps for testing."""
    return [
        WordTimestamp(word="Hello", start_seconds=0.0, end_seconds=0.3),
        WordTimestamp(word="world", start_seconds=0.35, end_seconds=0.7),
        WordTimestamp(word="this", start_seconds=0.75, end_seconds=1.0),
        WordTimestamp(word="is", start_seconds=1.05, end_seconds=1.2),
        WordTimestamp(word="a", start_seconds=1.25, end_seconds=1.35),
        WordTimestamp(word="test", start_seconds=1.4, end_seconds=1.8),
    ]


@pytest.fixture
def words_with_pause() -> list[WordTimestamp]:
    """Return word timestamps with a significant pause in the middle."""
    return [
        WordTimestamp(word="First", start_seconds=0.0, end_seconds=0.3),
        WordTimestamp(word="part", start_seconds=0.35, end_seconds=0.6),
        # Gap of 0.8s (> PAUSE_THRESHOLD of 0.6s)
        WordTimestamp(word="Second", start_seconds=1.4, end_seconds=1.7),
        WordTimestamp(word="part", start_seconds=1.75, end_seconds=2.0),
    ]


class TestGroupWordsIntoCaptions:
    """Test _group_words_into_captions."""

    def test_group_words_into_captions_basic(
        self, caption_service: CaptionService, basic_words: list[WordTimestamp]
    ) -> None:
        captions = caption_service._group_words_into_captions(basic_words)

        assert len(captions) >= 1
        # All words should be present across captions
        all_text = " ".join(c.text for c in captions)
        for w in basic_words:
            assert w.word in all_text

        # Indices should be sequential starting from 1
        for i, cap in enumerate(captions):
            assert cap.index == i + 1

        # Start of first caption should be the start of the first word
        assert captions[0].start_seconds == 0.0

        # End of last caption should be the end of the last word
        assert captions[-1].end_seconds == 1.8

    def test_group_words_respects_max_words(self, caption_service: CaptionService) -> None:
        # Create 12 words with minimal gaps (all within timing)
        words = [
            WordTimestamp(
                word=f"word{i}",
                start_seconds=i * 0.2,
                end_seconds=i * 0.2 + 0.15,
            )
            for i in range(12)
        ]

        captions = caption_service._group_words_into_captions(words, max_words_per_line=4)

        # With max_words_per_line=4, 12 words should produce at least 3 captions
        assert len(captions) >= 3

        for cap in captions:
            word_count = len(cap.text.split())
            assert word_count <= 4, f"Caption has {word_count} words, max is 4"

    def test_group_words_breaks_on_pause(
        self, caption_service: CaptionService, words_with_pause: list[WordTimestamp]
    ) -> None:
        captions = caption_service._group_words_into_captions(words_with_pause)

        # The pause should force a break, producing at least 2 captions
        assert len(captions) >= 2

        # First caption should contain "First part"
        assert "First" in captions[0].text
        assert "part" in captions[0].text

        # Second caption should contain "Second part"
        assert "Second" in captions[1].text

    def test_group_words_empty_input(self, caption_service: CaptionService) -> None:
        captions = caption_service._group_words_into_captions([])
        assert captions == []

    def test_group_words_single_word(self, caption_service: CaptionService) -> None:
        words = [WordTimestamp(word="Hello", start_seconds=0.0, end_seconds=0.5)]
        captions = caption_service._group_words_into_captions(words)
        assert len(captions) == 1
        assert captions[0].text == "Hello"
        assert captions[0].start_seconds == 0.0
        assert captions[0].end_seconds == 0.5


class TestWriteSrtFormat:
    """Test SRT file output."""

    def test_write_srt_format(self, caption_service: CaptionService, tmp_path: Path) -> None:
        captions = [
            Caption(index=1, start_seconds=0.0, end_seconds=2.5, text="Hello world"),
            Caption(index=2, start_seconds=3.0, end_seconds=5.0, text="Testing captions"),
        ]
        output_path = tmp_path / "test.srt"
        caption_service._write_srt(captions, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        # First caption block
        assert lines[0] == "1"
        assert lines[1] == "00:00:00,000 --> 00:00:02,500"
        assert lines[2] == "Hello world"
        assert lines[3] == ""  # blank separator

        # Second caption block
        assert lines[4] == "2"
        assert lines[5] == "00:00:03,000 --> 00:00:05,000"
        assert lines[6] == "Testing captions"


class TestWriteAssFormat:
    """Test ASS file output."""

    def test_write_ass_format(self, caption_service: CaptionService, tmp_path: Path) -> None:
        captions = [
            Caption(index=1, start_seconds=0.0, end_seconds=2.5, text="Hello world"),
            Caption(index=2, start_seconds=3.1, end_seconds=5.55, text="Testing ASS"),
        ]
        output_path = tmp_path / "test.ass"
        caption_service._write_ass(captions, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")

        # Should contain ASS header markers
        assert "[Script Info]" in content
        assert "Drevalis Captions" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content

        # Should contain Dialogue lines with correct format
        assert "Dialogue: 0," in content
        assert "Hello world" in content
        assert "Testing ASS" in content

    def test_write_ass_escapes_special_chars(
        self, caption_service: CaptionService, tmp_path: Path
    ) -> None:
        captions = [
            Caption(
                index=1,
                start_seconds=0.0,
                end_seconds=1.0,
                text="Test {braces} and \\backslash",
            ),
        ]
        output_path = tmp_path / "special.ass"
        caption_service._write_ass(captions, output_path)

        content = output_path.read_text(encoding="utf-8")
        # Braces should be escaped in ASS format
        assert "\\{braces\\}" in content
        assert "\\\\backslash" in content


class TestFormatSrtTimestamp:
    """Test SRT timestamp formatting."""

    def test_format_srt_timestamp(self, caption_service: CaptionService) -> None:
        assert CaptionService._format_srt_timestamp(0.0) == "00:00:00,000"
        assert CaptionService._format_srt_timestamp(1.5) == "00:00:01,500"
        assert CaptionService._format_srt_timestamp(61.123) == "00:01:01,123"
        assert CaptionService._format_srt_timestamp(3661.999) == "01:01:01,999"

    def test_format_srt_timestamp_negative(self, caption_service: CaptionService) -> None:
        # Negative values should clamp to 0
        assert CaptionService._format_srt_timestamp(-1.0) == "00:00:00,000"

    def test_format_srt_timestamp_rounding(self, caption_service: CaptionService) -> None:
        # 2.9995 rounds to 3000ms = 3.000s
        result = CaptionService._format_srt_timestamp(2.9995)
        assert result == "00:00:03,000" or result == "00:00:02,999"


class TestFormatAssTimestamp:
    """Test ASS timestamp formatting."""

    def test_format_ass_timestamp(self, caption_service: CaptionService) -> None:
        assert CaptionService._format_ass_timestamp(0.0) == "0:00:00.00"
        assert CaptionService._format_ass_timestamp(1.5) == "0:00:01.50"
        assert CaptionService._format_ass_timestamp(61.12) == "0:01:01.12"
        assert CaptionService._format_ass_timestamp(3661.99) == "1:01:01.99"

    def test_format_ass_timestamp_negative(self, caption_service: CaptionService) -> None:
        assert CaptionService._format_ass_timestamp(-5.0) == "0:00:00.00"

    def test_format_ass_timestamp_single_digit_hour(self, caption_service: CaptionService) -> None:
        # ASS uses single-digit hours
        result = CaptionService._format_ass_timestamp(3600.0)
        assert result.startswith("1:")


class TestGenerateFromTimestamps:
    """Test end-to-end caption generation from pre-existing timestamps."""

    async def test_generate_from_timestamps(
        self, caption_service: CaptionService, tmp_path: Path
    ) -> None:
        words = [
            WordTimestamp(word="Hello", start_seconds=0.0, end_seconds=0.3),
            WordTimestamp(word="world", start_seconds=0.35, end_seconds=0.7),
            WordTimestamp(word="this", start_seconds=0.8, end_seconds=1.0),
            WordTimestamp(word="is", start_seconds=1.05, end_seconds=1.2),
            WordTimestamp(word="caption", start_seconds=1.25, end_seconds=1.6),
            WordTimestamp(word="test", start_seconds=1.65, end_seconds=2.0),
        ]

        result = await caption_service.generate_from_timestamps(
            word_timestamps=words,
            output_dir=tmp_path,
        )

        assert len(result.captions) >= 1
        assert Path(result.srt_path).exists()
        assert Path(result.ass_path).exists()

        srt_content = Path(result.srt_path).read_text(encoding="utf-8")
        assert "-->" in srt_content  # SRT timestamp separator

        ass_content = Path(result.ass_path).read_text(encoding="utf-8")
        assert "Dialogue:" in ass_content

    async def test_generate_from_timestamps_creates_output_dir(
        self, caption_service: CaptionService, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "nested" / "captions"
        words = [
            WordTimestamp(word="Test", start_seconds=0.0, end_seconds=0.5),
        ]

        result = await caption_service.generate_from_timestamps(
            word_timestamps=words,
            output_dir=output_dir,
        )
        assert output_dir.exists()
        assert len(result.captions) == 1
