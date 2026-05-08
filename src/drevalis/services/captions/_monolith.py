"""Caption generation service.

Produces SRT and ASS subtitle files from audio or pre-existing word
timestamps.  When no timestamps are available, **faster-whisper** is used
for speech-to-text with word-level alignment (run inside a thread pool to
keep the event loop responsive).

The ASS output is styled for YouTube Shorts playback:
large bold white text with a black outline, centred near the bottom of a
1080 x 1920 frame.  Multiple caption presets are supported for different
visual effects (highlight, karaoke, pop, minimal, classic).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

# Re-use the WordTimestamp dataclass from the TTS module so the two
# services share a single type.
from drevalis.services.tts import WordTimestamp

# Punctuation that looks odd in large caption text (stripped for display).
_CAPTION_STRIP_CHARS = ".,;:!?—–-\"'()[]{}…"


def _clean_caption_word(word: str) -> str:
    """Strip leading/trailing punctuation from a word for cleaner caption display."""
    cleaned = word.strip(_CAPTION_STRIP_CHARS)
    return cleaned if cleaned else word  # keep original if it's ALL punctuation


log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CaptionStyle:
    """Configurable style for ASS subtitle rendering.

    Presets:
    - ``youtube_highlight`` -- all words shown, active word highlighted via
      karaoke tags.
    - ``karaoke`` -- one word at a time with fade in/out.
    - ``tiktok_pop`` -- 1-2 words pop-scaled in from zero.
    - ``minimal`` -- small semi-transparent text, no outline.
    - ``classic`` -- plain white text with black outline (legacy default).
    """

    preset: str = "youtube_highlight"
    font_name: str = "Impact"  # Impact is the standard Shorts/TikTok caption font
    font_size: int = 72  # Larger for mobile readability
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#00D4AA"  # accent teal
    outline_color: str = "#000000"
    outline_width: int = 5  # Thicker outline cuts through any background
    position: str = "bottom"  # bottom | center | top
    margin_v: int = 250  # Higher margin keeps text clear of UI chrome
    animation: str = "fade"  # fade | pop | bounce | none
    words_per_line: int = 2  # 2 words per line: no wrapping, impactful pacing
    uppercase: bool = True
    play_res_x: int = 1080
    play_res_y: int = 1920


@dataclass
class Caption:
    """A single captioned line shown on screen."""

    index: int
    start_seconds: float
    end_seconds: float
    text: str
    word_timestamps: list[WordTimestamp] | None = None


@dataclass
class CaptionResult:
    """Result of a caption generation pass."""

    captions: list[Caption]
    srt_path: str  # relative to storage
    ass_path: str  # relative to storage


# ---------------------------------------------------------------------------
# Color conversion helpers
# ---------------------------------------------------------------------------


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert ``#RRGGBB`` hex colour to ASS ``&H00BBGGRR`` format.

    ASS uses reverse byte order (BGR) with an alpha prefix.  The alpha
    byte ``00`` means fully opaque.
    """
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        # Fallback to white on bad input
        return "&H00FFFFFF"
    r = hex_color[0:2]
    g = hex_color[2:4]
    b = hex_color[4:6]
    return f"&H00{b}{g}{r}".upper()


def _hex_to_ass_color_alpha(hex_color: str, alpha: int = 0) -> str:
    """Convert ``#RRGGBB`` with explicit alpha (0=opaque, 255=transparent)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return f"&H{alpha:02X}FFFFFF"
    r = hex_color[0:2]
    g = hex_color[2:4]
    b = hex_color[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _alignment_from_position(position: str) -> int:
    """Map human-readable position to ASS alignment number.

    ASS alignment uses a numpad layout:
    - 1/2/3 = bottom left/centre/right
    - 4/5/6 = middle left/centre/right
    - 7/8/9 = top left/centre/right
    """
    mapping = {
        "bottom": 2,
        "center": 5,
        "centre": 5,
        "top": 8,
    }
    return mapping.get(position.lower(), 2)


# ---------------------------------------------------------------------------
# ASS header builders
# ---------------------------------------------------------------------------


def _build_ass_header(style: CaptionStyle) -> str:
    """Build a complete ASS header with styles derived from *style*."""
    primary = _hex_to_ass_color(style.primary_color)
    highlight = _hex_to_ass_color(style.highlight_color)
    outline = _hex_to_ass_color(style.outline_color)
    back = _hex_to_ass_color_alpha("#000000", 128)  # semi-transparent background
    alignment = _alignment_from_position(style.position)

    font_size = style.font_size
    font_name = style.font_name
    outline_width = style.outline_width
    margin_v = style.margin_v

    # Preset-specific overrides for the style definitions
    if style.preset == "minimal":
        font_size = 48
        outline_width = 0
        primary = _hex_to_ass_color_alpha(style.primary_color, 40)  # slightly transparent
        alignment = 1  # bottom-left

    lines = [
        "[Script Info]",
        "Title: Drevalis Captions",
        "ScriptType: v4.00+",
        f"PlayResX: {style.play_res_x}",
        f"PlayResY: {style.play_res_y}",
        # WrapStyle 2 = no automatic word-wrapping. We insert explicit \N line
        # breaks ourselves so the renderer never splits a line unpredictably.
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # Default style -- base text appearance
        f"Style: Default,{font_name},{font_size},{primary},&H000000FF,"
        f"{outline},{back},-1,0,0,0,100,100,0,0,1,{outline_width},0,"
        f"{alignment},40,40,{margin_v},1",
        # Highlight style -- for active/spoken words (youtube_highlight preset)
        f"Style: Highlight,{font_name},{font_size},{highlight},&H000000FF,"
        f"{outline},{back},-1,0,0,0,100,100,0,0,1,{outline_width},0,"
        f"{alignment},40,40,{margin_v},1",
        # Inactive style -- for not-yet-spoken words
        f"Style: Inactive,{font_name},{font_size},{primary},&H000000FF,"
        f"{outline},{back},-1,0,0,0,100,100,0,0,1,{outline_width},0,"
        f"{alignment},40,40,{margin_v},1",
    ]

    # Buzzword style -- large Impact font, center-screen pop-in for keyword overlays.
    # Alignment 5 = center-center (numpad layout).  MarginV is unused when \pos
    # is explicit in the Dialogue line, but we set it to ~35 % of frame height
    # as a safe fallback.  Outline 6 and Shadow 3 give strong visibility against
    # any background.
    buzzword_color = _hex_to_ass_color(style.highlight_color)
    buzzword_outline = _hex_to_ass_color(style.outline_color)
    buzzword_margin_v = round(style.play_res_y * 0.35)
    lines.append(
        f"Style: Buzzword,Impact,120,{buzzword_color},&H000000FF,"
        f"{buzzword_outline},{back},1,0,0,0,100,100,2,0,1,6,3,"
        f"5,10,10,{buzzword_margin_v},1"
    )

    lines += [
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Legacy ASS header (classic preset compatibility)
# ---------------------------------------------------------------------------


def _build_ass_header_classic(play_res_x: int = 1080, play_res_y: int = 1920) -> str:
    """Build the classic ASS header with configurable resolution.

    This replaces the old ``_ASS_HEADER_CLASSIC`` string constant so that
    landscape (1920×1080) and vertical (1080×1920) outputs both render
    captions at the correct scale.
    """
    return (
        "[Script Info]\n"
        "Title: Drevalis Captions\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Impact,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,5,0,2,40,40,250,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


# Kept for any external callers that import the old constant directly.
_ASS_HEADER_CLASSIC = _build_ass_header_classic()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CaptionService:
    """Generate captions from audio or word timestamps."""

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self._model: Any | None = None
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type

    # -- Public API ---------------------------------------------------------

    async def generate_from_audio(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        language: str = "en",
        style: CaptionStyle | None = None,
        keywords: list[str] | None = None,
    ) -> CaptionResult:
        """Generate word-level captions from audio via faster-whisper.

        Steps:
        1. Run faster-whisper transcription in a thread pool.
        2. Group words into readable caption segments.
        3. Write SRT and ASS files.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        log.info(
            "captions.generate_from_audio.start",
            audio_path=str(audio_path),
            model_size=self._model_size,
            language=language,
        )

        word_timestamps = await asyncio.to_thread(self._transcribe, audio_path, language)

        effective_style = style or CaptionStyle()
        captions = self._group_words_into_captions(
            word_timestamps,
            max_words_per_line=effective_style.words_per_line,
        )

        srt_path = output_dir / "captions.srt"
        ass_path = output_dir / "captions.ass"

        self._write_srt(captions, srt_path)
        self._write_ass(
            captions,
            ass_path,
            style=effective_style,
            keywords=keywords,
            all_word_timestamps=word_timestamps,
        )

        log.info(
            "captions.generate_from_audio.done",
            caption_count=len(captions),
            srt_path=str(srt_path),
            ass_path=str(ass_path),
        )

        return CaptionResult(
            captions=captions,
            srt_path=str(srt_path),
            ass_path=str(ass_path),
        )

    async def generate_from_timestamps(
        self,
        word_timestamps: list[WordTimestamp],
        output_dir: Path,
        *,
        style: CaptionStyle | None = None,
        keywords: list[str] | None = None,
    ) -> CaptionResult:
        """Generate captions from pre-existing TTS word timestamps.

        This path is much faster than Whisper because the alignment data
        already exists.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        log.info(
            "captions.generate_from_timestamps.start",
            word_count=len(word_timestamps),
        )

        effective_style = style or CaptionStyle()
        captions = self._group_words_into_captions(
            word_timestamps,
            max_words_per_line=effective_style.words_per_line,
        )

        srt_path = output_dir / "captions.srt"
        ass_path = output_dir / "captions.ass"

        self._write_srt(captions, srt_path)
        self._write_ass(
            captions,
            ass_path,
            style=effective_style,
            keywords=keywords,
            all_word_timestamps=word_timestamps,
        )

        log.info(
            "captions.generate_from_timestamps.done",
            caption_count=len(captions),
        )

        return CaptionResult(
            captions=captions,
            srt_path=str(srt_path),
            ass_path=str(ass_path),
        )

    # -- Whisper transcription (CPU-bound, runs in thread) ------------------

    def _get_model(self) -> Any:
        """Lazily initialise the faster-whisper model."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise ImportError(
                    "faster-whisper is required for audio-based caption generation. "
                    "Install it with: pip install faster-whisper"
                ) from exc

            log.info(
                "captions.model.loading",
                model_size=self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            log.info("captions.model.loaded")

        return self._model

    def _transcribe(self, audio_path: Path, language: str) -> list[WordTimestamp]:
        """Run faster-whisper and return word-level timestamps.

        This method is intended to be called via ``asyncio.to_thread``.
        """
        model = self._get_model()

        segments_iter, _info = model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
            vad_filter=False,  # VAD can cut the end of audio — disable for full coverage
        )

        word_timestamps: list[WordTimestamp] = []
        for segment in segments_iter:
            if segment.words is None:
                continue
            for w in segment.words:
                cleaned = w.word.strip()
                if cleaned:
                    word_timestamps.append(
                        WordTimestamp(
                            word=cleaned,
                            start_seconds=round(w.start, 3),
                            end_seconds=round(w.end, 3),
                        )
                    )

        log.debug(
            "captions.transcribe.done",
            word_count=len(word_timestamps),
        )
        return word_timestamps

    # -- Grouping -----------------------------------------------------------

    # Maximum characters per caption line before a forced break is applied.
    # At font size 72 Impact on a 1080px canvas the safe on-screen width is
    # approximately 20 characters (with 5px outline, ~46px per glyph average).
    _MAX_CHARS_PER_LINE: int = 20

    def _group_words_into_captions(
        self,
        words: list[WordTimestamp],
        max_words_per_line: int = 2,
        max_duration: float = 3.0,
    ) -> list[Caption]:
        """Group words into readable caption segments.

        Rules (applied in priority order):
        1. Each caption contains at most *max_words_per_line* words (default 2).
        2. Each caption spans at most *max_duration* seconds.
        3. A new caption starts on a natural speech pause (> 0.6 s gap).
        4. A single word that exceeds ``_MAX_CHARS_PER_LINE`` gets its own
           caption regardless of position — prevents horizontal overflow.
        5. Adding the next word would push the accumulated text past
           ``_MAX_CHARS_PER_LINE`` characters — flush first.

        Rules 4 and 5 guarantee text never wraps or gets clipped at screen
        edges when WrapStyle 2 (no auto-wrap) is active in the ASS header.

        Word timestamps are preserved in each Caption for animated presets.
        """
        if not words:
            return []

        PAUSE_THRESHOLD = 0.6  # seconds

        captions: list[Caption] = []
        current_words: list[WordTimestamp] = [words[0]]

        def _flush() -> None:
            """Append the accumulated words as a Caption and reset the buffer."""
            display_words = [_clean_caption_word(w.word) for w in current_words]
            display_words = [w for w in display_words if w]  # drop empty
            captions.append(
                Caption(
                    index=len(captions) + 1,
                    start_seconds=current_words[0].start_seconds,
                    end_seconds=current_words[-1].end_seconds,
                    text=" ".join(display_words)
                    if display_words
                    else " ".join(w.word for w in current_words),
                    word_timestamps=list(current_words),
                )
            )
            current_words.clear()

        for prev, curr in zip(words, words[1:], strict=False):
            gap = curr.start_seconds - prev.end_seconds
            span = curr.end_seconds - current_words[0].start_seconds

            # Current accumulated text length (including the space separator).
            current_text_len = sum(len(w.word) for w in current_words) + max(
                0, len(current_words) - 1
            )
            next_text_len = current_text_len + 1 + len(curr.word)

            should_break = (
                len(current_words) >= max_words_per_line
                or span + (curr.end_seconds - curr.start_seconds) > max_duration
                or gap > PAUSE_THRESHOLD
                # Adding the next word would overflow the safe character budget.
                or next_text_len > self._MAX_CHARS_PER_LINE
            )

            if should_break:
                _flush()
                current_words.append(curr)
            else:
                current_words.append(curr)

        # Flush remaining words.
        if current_words:
            _flush()

        return captions

    # -- SRT writer ---------------------------------------------------------

    def _write_srt(self, captions: list[Caption], output_path: Path) -> None:
        """Write captions in SRT format."""
        lines: list[str] = []
        for cap in captions:
            lines.append(str(cap.index))
            start_ts = self._format_srt_timestamp(cap.start_seconds)
            end_ts = self._format_srt_timestamp(cap.end_seconds)
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(cap.text)
            lines.append("")  # blank line separator

        output_path.write_text("\n".join(lines), encoding="utf-8")
        log.debug("captions.srt.written", path=str(output_path))

    # -- ASS writer ---------------------------------------------------------

    def _write_ass(
        self,
        captions: list[Caption],
        output_path: Path,
        *,
        style: CaptionStyle | None = None,
        keywords: list[str] | None = None,
        all_word_timestamps: list[WordTimestamp] | None = None,
    ) -> None:
        """Write captions in ASS (Advanced SubStation Alpha) format.

        Dispatches to preset-specific renderers based on ``style.preset``.
        Keyword overlays are appended when *keywords* are provided.
        """
        effective_style = style or CaptionStyle(preset="classic")

        if effective_style.preset == "classic":
            self._write_ass_classic(captions, output_path, effective_style)
        elif effective_style.preset == "youtube_highlight":
            self._write_ass_youtube_highlight(
                captions,
                output_path,
                effective_style,
                keywords=keywords,
                all_word_timestamps=all_word_timestamps,
            )
        elif effective_style.preset == "karaoke":
            self._write_ass_karaoke(
                captions,
                output_path,
                effective_style,
                keywords=keywords,
                all_word_timestamps=all_word_timestamps,
            )
        elif effective_style.preset == "tiktok_pop":
            self._write_ass_tiktok_pop(
                captions,
                output_path,
                effective_style,
                keywords=keywords,
                all_word_timestamps=all_word_timestamps,
            )
        elif effective_style.preset == "minimal":
            self._write_ass_minimal(
                captions,
                output_path,
                effective_style,
                keywords=keywords,
                all_word_timestamps=all_word_timestamps,
            )
        else:
            # Unknown preset -- fall back to classic
            log.warning(
                "captions.ass.unknown_preset",
                preset=effective_style.preset,
            )
            self._write_ass_classic(captions, output_path, effective_style)

    def _write_ass_classic(
        self,
        captions: list[Caption],
        output_path: Path,
        style: CaptionStyle | None = None,
    ) -> None:
        """Write classic ASS -- plain white text, black outline, no animation.

        Accepts an optional *style* so that ``play_res_x``/``play_res_y``
        are respected even for the classic preset.
        """
        if style is not None:
            header = _build_ass_header_classic(style.play_res_x, style.play_res_y)
        else:
            header = _ASS_HEADER_CLASSIC
        lines: list[str] = [header]

        for cap in captions:
            start_ts = self._format_ass_timestamp(cap.start_seconds)
            end_ts = self._format_ass_timestamp(cap.end_seconds)
            # Escape special ASS characters in the text.
            safe_text = cap.text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            lines.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{safe_text}")

        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.debug("captions.ass.written", path=str(output_path), preset="classic")

    def _write_ass_youtube_highlight(
        self,
        captions: list[Caption],
        output_path: Path,
        style: CaptionStyle,
        *,
        keywords: list[str] | None = None,
        all_word_timestamps: list[WordTimestamp] | None = None,
    ) -> None:
        """Write youtube_highlight ASS.

        All words of a caption line are shown at once in primary_color.
        ASS karaoke ``\\k`` tags progressively change each word to
        highlight_color as it is spoken.
        """
        header = _build_ass_header(style)
        highlight_ass = _hex_to_ass_color(style.highlight_color)
        lines: list[str] = [header]

        for cap in captions:
            start_ts = self._format_ass_timestamp(cap.start_seconds)
            end_ts = self._format_ass_timestamp(cap.end_seconds)

            if cap.word_timestamps:
                # Build karaoke-tagged text.
                # \kf<duration> fills each word over its spoken duration.
                # Duration is in centiseconds.
                parts: list[str] = []
                for wt in cap.word_timestamps:
                    word_text = _clean_caption_word(wt.word)
                    if style.uppercase:
                        word_text = word_text.upper()
                    # Safe-escape the word
                    word_text = (
                        word_text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                    )
                    dur_cs = max(1, round((wt.end_seconds - wt.start_seconds) * 100))
                    # \1c is primary fill colour for karaoke highlight
                    parts.append(f"{{\\kf{dur_cs}}}{word_text}")
                tagged_text = " ".join(parts)
                # Use the Highlight style so the karaoke fill colour is
                # the highlight colour.  The Default style primary serves
                # as the "not yet spoken" colour; the SecondaryColour
                # (karaoke fill) is set to highlight.
                lines.append(
                    f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,"
                    f"{{\\1c{_hex_to_ass_color(style.primary_color)}"
                    f"\\2c{highlight_ass}}}"
                    f"{tagged_text}"
                )
            else:
                # No word-level timing -- fall back to plain text
                safe_text = cap.text
                if style.uppercase:
                    safe_text = safe_text.upper()
                safe_text = safe_text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                lines.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{safe_text}")

        # Append keyword overlay lines when keywords are provided.
        if keywords and all_word_timestamps:
            lines.extend(self._generate_keyword_overlays(keywords, all_word_timestamps, style))

        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.debug(
            "captions.ass.written",
            path=str(output_path),
            preset="youtube_highlight",
        )

    def _write_ass_karaoke(
        self,
        captions: list[Caption],
        output_path: Path,
        style: CaptionStyle,
        *,
        keywords: list[str] | None = None,
        all_word_timestamps: list[WordTimestamp] | None = None,
    ) -> None:
        """Write karaoke ASS -- one word at a time with fade in/out.

        Each word gets its own Dialogue line with a fade effect.
        """
        header = _build_ass_header(style)
        alignment = _alignment_from_position(style.position)
        lines: list[str] = [header]

        for cap in captions:
            if cap.word_timestamps:
                for wt in cap.word_timestamps:
                    start_ts = self._format_ass_timestamp(wt.start_seconds)
                    end_ts = self._format_ass_timestamp(wt.end_seconds)
                    word_text = _clean_caption_word(wt.word)
                    if not word_text.strip():
                        continue
                    if style.uppercase:
                        word_text = word_text.upper()
                    word_text = (
                        word_text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                    )
                    lines.append(
                        f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,"
                        f"{{\\fad(150,100)\\an{alignment}}}{word_text}"
                    )
            else:
                # No word-level timing -- show full caption line
                start_ts = self._format_ass_timestamp(cap.start_seconds)
                end_ts = self._format_ass_timestamp(cap.end_seconds)
                safe_text = cap.text
                if style.uppercase:
                    safe_text = safe_text.upper()
                safe_text = safe_text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                lines.append(
                    f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,"
                    f"{{\\fad(150,100)\\an{alignment}}}{safe_text}"
                )

        # Append keyword overlay lines when keywords are provided.
        if keywords and all_word_timestamps:
            lines.extend(self._generate_keyword_overlays(keywords, all_word_timestamps, style))

        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.debug("captions.ass.written", path=str(output_path), preset="karaoke")

    def _write_ass_tiktok_pop(
        self,
        captions: list[Caption],
        output_path: Path,
        style: CaptionStyle,
        *,
        keywords: list[str] | None = None,
        all_word_timestamps: list[WordTimestamp] | None = None,
    ) -> None:
        """Write tiktok_pop ASS -- 1-2 words at a time with scale-pop animation.

        Each word pops in from zero scale to full scale.
        """
        header = _build_ass_header(style)
        _alignment_from_position(style.position)
        lines: list[str] = [header]

        # tiktok_pop always positions captions at the vertical center of the
        # frame (an5) using an explicit \pos tag so \an from the style is
        # overridden. Center placement separates this preset visually from the
        # default bottom-third position used by youtube_highlight/karaoke.
        center_x = style.play_res_x // 2
        # 55 % down the frame: below the subject's face, above the bottom UI.
        center_y = round(style.play_res_y * 0.55)

        for cap in captions:
            if cap.word_timestamps:
                # Show words in pairs (max 2 per chunk), matching the
                # words_per_line grouping used during caption segmentation.
                chunk_size = 2
                for i in range(0, len(cap.word_timestamps), chunk_size):
                    chunk = cap.word_timestamps[i : i + chunk_size]
                    chunk_start = chunk[0].start_seconds
                    chunk_end = chunk[-1].end_seconds
                    start_ts = self._format_ass_timestamp(chunk_start)
                    end_ts = self._format_ass_timestamp(chunk_end)

                    clean_words = [_clean_caption_word(w.word) for w in chunk]
                    clean_words = [w for w in clean_words if w]
                    chunk_text = (
                        " ".join(clean_words) if clean_words else " ".join(w.word for w in chunk)
                    )
                    if style.uppercase:
                        chunk_text = chunk_text.upper()
                    chunk_text = (
                        chunk_text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                    )
                    # Pop-in: 80 % → 100 % over 120 ms (less jarring than 0→100).
                    # \shad2 adds a subtle drop shadow for depth and legibility.
                    lines.append(
                        f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,"
                        f"{{\\an5\\pos({center_x},{center_y})"
                        f"\\shad2"
                        f"\\fscx80\\fscy80\\t(0,120,\\fscx100\\fscy100)}}"
                        f"{chunk_text}"
                    )
            else:
                start_ts = self._format_ass_timestamp(cap.start_seconds)
                end_ts = self._format_ass_timestamp(cap.end_seconds)
                safe_text = cap.text
                if style.uppercase:
                    safe_text = safe_text.upper()
                safe_text = safe_text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                lines.append(
                    f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,"
                    f"{{\\an5\\pos({center_x},{center_y})"
                    f"\\shad2"
                    f"\\fscx80\\fscy80\\t(0,120,\\fscx100\\fscy100)}}"
                    f"{safe_text}"
                )

        # Append keyword overlay lines when keywords are provided.
        if keywords and all_word_timestamps:
            lines.extend(self._generate_keyword_overlays(keywords, all_word_timestamps, style))

        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.debug("captions.ass.written", path=str(output_path), preset="tiktok_pop")

    def _write_ass_minimal(
        self,
        captions: list[Caption],
        output_path: Path,
        style: CaptionStyle,
        *,
        keywords: list[str] | None = None,
        all_word_timestamps: list[WordTimestamp] | None = None,
    ) -> None:
        """Write minimal ASS -- small, no outline, semi-transparent, bottom-left.

        Uses a smaller font (48pt by default via the style header) and
        minimal visual presence.
        """
        header = _build_ass_header(style)
        lines: list[str] = [header]

        for cap in captions:
            start_ts = self._format_ass_timestamp(cap.start_seconds)
            end_ts = self._format_ass_timestamp(cap.end_seconds)
            safe_text = cap.text
            if style.uppercase:
                safe_text = safe_text.upper()
            safe_text = safe_text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            lines.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{safe_text}")

        # Append keyword overlay lines when keywords are provided.
        if keywords and all_word_timestamps:
            lines.extend(self._generate_keyword_overlays(keywords, all_word_timestamps, style))

        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.debug("captions.ass.written", path=str(output_path), preset="minimal")

    # -- Buzzword overlay generation -----------------------------------------

    def _generate_keyword_overlays(
        self,
        keywords: list[str],
        word_timestamps: list[WordTimestamp],
        style: CaptionStyle,
    ) -> list[str]:
        """Generate dual-layer ASS Dialogue lines for buzzword center overlays.

        Each keyword is matched (case-insensitively) against the transcribed
        word timestamps.  On first match the word is rendered at the vertical
        center of the frame using the ``Buzzword`` style -- entirely separate
        from the bottom-of-frame caption lines so the two tracks never overlap.

        Two Dialogue lines are emitted per match to produce a glow effect:

        - **Layer 0 (glow)** -- same text with ``\\blur6`` and reduced alpha
          (gold/cyan glow halo behind the sharp word).
        - **Layer 1 (sharp)** -- the legible foreground word with the full
          scale-pop animation.

        Animation sequence (milliseconds):

        - 0 → 150 ms : scale 0 % → 130 % (overshoot)
        - 150 → 300 ms : scale 130 % → 100 % (settle)
        - 900 → 1 200 ms : scale 100 % → 0 % (pop-out)

        The ``\\pos`` tag pins both layers to the exact horizontal and vertical
        center of the configured resolution so the position is resolution-
        independent.  Duplicate start times are skipped to prevent stacked
        overlays when a keyword appears multiple times close together.

        The bottom caption track is intentionally unmodified: the word still
        appears there in the regular highlight flow, giving viewers two
        simultaneous but spatially distinct cues.
        """
        lines: list[str] = []
        used_times: set[float] = set()

        # Center position in ASS pixel coordinates.
        center_x = style.play_res_x // 2
        # Place buzzwords at ~38 % from the top so they sit comfortably above
        # the bottom captions (which live in the bottom ~15 % of the frame).
        center_y = round(style.play_res_y * 0.38)

        # Glow colour: use the highlight colour at reduced opacity for the halo.
        # ASS BackColour alpha: 0x40 ≈ 75 % opaque (25 % transparent).
        glow_color = _hex_to_ass_color(style.highlight_color)

        for kw in keywords:
            kw_clean = kw.strip().lower()
            if not kw_clean:
                continue

            for wt in word_timestamps:
                wt_clean = wt.word.strip().lower().strip(".,!?;:'\"")
                if wt_clean != kw_clean and kw_clean not in wt_clean:
                    continue

                # Guard against stacking two overlays that start within 100 ms
                # of each other (rounded to one decimal = 100 ms buckets).
                rounded_start = round(wt.start_seconds, 1)
                if rounded_start in used_times:
                    continue
                used_times.add(rounded_start)

                word_duration = wt.end_seconds - wt.start_seconds
                # Keep the overlay on screen slightly longer than the spoken
                # word so the pop-out animation has time to play.
                display_duration = min(1.5, max(0.8, word_duration * 2.5))
                start = self._format_ass_timestamp(wt.start_seconds)
                end = self._format_ass_timestamp(wt.start_seconds + display_duration)

                display_text = kw.upper() if style.uppercase else kw
                # Escape ASS special characters.
                display_text = (
                    display_text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                )

                pos_tag = rf"\an5\pos({center_x},{center_y})"

                # --- Layer 0: blurred glow halo ----------------------------
                # \blur6 spreads the glyph edges into a soft halo.
                # \alpha&H60& sets the overall opacity to ~62 % for subtlety.
                # \3c sets the border/glow colour to the highlight (teal/gold).
                # Scale animation is identical to the sharp layer so both
                # layers stay perfectly registered during the pop.
                glow_tag = (
                    rf"{{\{pos_tag}"
                    rf"\blur6\alpha&H60&\3c{glow_color}"
                    rf"\fscx0\fscy0"
                    rf"\t(0,150,\fscx130\fscy130)"
                    rf"\t(150,300,\fscx100\fscy100)"
                    rf"\t(900,1200,\fscx0\fscy0)}}"
                )
                lines.append(f"Dialogue: 0,{start},{end},Buzzword,,0,0,0,,{glow_tag}{display_text}")

                # --- Layer 1: sharp foreground text ------------------------
                # No blur.  Full opacity.  Same scale-pop animation.
                sharp_tag = (
                    rf"{{\{pos_tag}"
                    rf"\fscx0\fscy0"
                    rf"\t(0,150,\fscx130\fscy130)"
                    rf"\t(150,300,\fscx100\fscy100)"
                    rf"\t(900,1200,\fscx0\fscy0)}}"
                )
                lines.append(
                    f"Dialogue: 1,{start},{end},Buzzword,,0,0,0,,{sharp_tag}{display_text}"
                )

                break  # Only use the first timestamp match per keyword.

        if lines:
            log.debug(
                "captions.buzzword_overlays.generated",
                keyword_count=len(keywords),
                overlay_count=len(lines),
            )

        return lines

    # -- Timestamp formatting -----------------------------------------------

    @staticmethod
    def _format_srt_timestamp(seconds: float) -> str:
        """Format seconds as ``HH:MM:SS,mmm`` for SRT files."""
        if seconds < 0:
            seconds = 0.0
        total_ms = round(seconds * 1000)
        hours, remainder = divmod(total_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, ms = divmod(remainder, 1_000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    @staticmethod
    def _format_ass_timestamp(seconds: float) -> str:
        """Format seconds as ``H:MM:SS.cc`` for ASS files.

        ASS uses centiseconds (hundredths of a second) and a single-digit
        hour field.
        """
        if seconds < 0:
            seconds = 0.0
        total_cs = round(seconds * 100)
        hours, remainder = divmod(total_cs, 360_000)
        minutes, remainder = divmod(remainder, 6_000)
        secs, cs = divmod(remainder, 100)
        return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"
