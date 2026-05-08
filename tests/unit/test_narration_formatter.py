"""Unit tests for Phase 2.10 narration formatter.

Verifies:
* Provider routing — unknown providers return ``None``.
* Idempotency — clean text returns ``None`` rather than an identical
  rewrite (so callers can skip persistence).
* Per-rule application — money expansion, percent expansion, em-dash
  rewriting, ellipsis collapsing, parenthetical lifting, problematic-
  acronym dotted-spelling on first use.
"""

from __future__ import annotations

from drevalis.services.narration_formatter import format_for_tts


class TestProviderRouting:
    def test_unknown_provider_returns_none(self) -> None:
        assert format_for_tts("In 1947 NASA paid 1.7 million dollars.", "fictional") is None

    def test_empty_inputs_return_none(self) -> None:
        assert format_for_tts("", "edge") is None
        assert format_for_tts("hi", None) is None
        assert format_for_tts(None, "edge") is None  # type: ignore[arg-type]


class TestIdempotency:
    def test_clean_text_returns_none(self) -> None:
        # No symbols, no parentheticals, no acronyms. Already TTS-clean.
        assert format_for_tts("Jonathan James broke into NASA at fifteen.", "edge") is None

    def test_repeated_format_stable(self) -> None:
        text = "He stole $1.7M of NASA source code."
        first = format_for_tts(text, "piper")
        assert first is not None
        # Running the formatter again should not produce yet another rewrite.
        assert format_for_tts(first, "piper") is None


class TestMoneyExpansion:
    def test_dollar_with_million_suffix(self) -> None:
        out = format_for_tts("He stole $1.7M from NASA.", "piper")
        assert out is not None
        assert "1.7 million dollars" in out
        assert "$1.7M" not in out

    def test_dollar_with_billion_suffix(self) -> None:
        out = format_for_tts("The IPO raised $50B in 1998.", "piper")
        assert out is not None
        assert "50 billion dollars" in out

    def test_plain_dollar(self) -> None:
        out = format_for_tts("Tickets cost $50 in 1947.", "piper")
        assert out is not None
        assert "50 dollars" in out


class TestPercentExpansion:
    def test_percent_to_word(self) -> None:
        out = format_for_tts("Stock fell 23% in one day.", "piper")
        assert out is not None
        assert "23 percent" in out
        assert "23%" not in out


class TestEmDashAndEllipsis:
    def test_em_dash_becomes_comma(self) -> None:
        out = format_for_tts("He arrived in 1947 — three years late.", "edge")
        assert out is not None
        assert "—" not in out
        assert "1947, three" in out

    def test_ellipsis_collapses(self) -> None:
        out = format_for_tts("He waited... and waited...", "edge")
        assert out is not None
        assert "..." not in out
        assert "…" not in out


class TestParentheticalLifting:
    def test_parenthetical_becomes_separate_sentence(self) -> None:
        out = format_for_tts("He arrived in 1947 (the same year as Roswell).", "edge")
        assert out is not None
        assert "(" not in out and ")" not in out
        # The lifted clause becomes its own sentence with a capitalised first letter.
        assert "The same year" in out


class TestProblematicAcronyms:
    def test_uaw_dotted_spelling_first_use(self) -> None:
        out = format_for_tts("The UAW pickets started in 1947.", "edge")
        assert out is not None
        # Spelled-out form is appended in parentheses.
        assert "U. A. W." in out

    def test_safe_acronyms_untouched(self) -> None:
        # NASA, FBI, CEO are read correctly by every voice — the formatter
        # leaves them alone.
        out = format_for_tts("NASA fired the FBI's CEO in 1947.", "edge")
        # Non-trivial rewrite may or may not happen via other rules; just
        # confirm we didn't insert dotted spellings for these.
        if out is not None:
            assert "N. A. S. A." not in out
            assert "F. B. I." not in out


class TestProviderSpecificRules:
    def test_elevenlabs_skips_money_expansion(self) -> None:
        # ElevenLabs handles money natively — formatter leaves it alone,
        # only doing the dash/parenthetical cleanup.
        out = format_for_tts("He stole $1.7M from NASA.", "elevenlabs")
        # Either None (no rewrite needed) or doesn't expand money.
        if out is not None:
            assert "million dollars" not in out
            assert "$1.7M" in out

    def test_piper_aggressive_normalisation(self) -> None:
        # Piper expands everything.
        out = format_for_tts("$50 in 1947 — what's that today?", "piper")
        assert out is not None
        assert "50 dollars" in out
        assert "—" not in out
