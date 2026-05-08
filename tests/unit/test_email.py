"""Unit tests for drevalis.services.email.

Covers:
* send_email returns False (no raise) when SMTP is not configured.
* send_email returns False (no raise) when smtp_from/smtp_username absent.
* send_email calls _send_sync and returns True on success.
* send_email returns False (no raise) on SMTP exception.
* Recipient masking: the email.send_success log event uses masked address.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from drevalis.services.email import _mask_email, send_email

# ---------------------------------------------------------------------------
# _mask_email
# ---------------------------------------------------------------------------


class TestMaskEmail:
    def test_normal_address_masked(self) -> None:
        assert _mask_email("john.doe@example.com") == "j**@example.com"

    def test_single_char_local(self) -> None:
        assert _mask_email("x@foo.io") == "x**@foo.io"

    def test_no_at_sign_fallback(self) -> None:
        assert _mask_email("notanemail") == "***"

    def test_preserves_domain(self) -> None:
        result = _mask_email("admin@drevalis.com")
        assert result.endswith("@drevalis.com")
        assert "**" in result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _smtp_settings(**overrides: Any) -> Any:
    s = MagicMock()
    s.smtp_host = overrides.get("smtp_host", "smtp.example.com")
    s.smtp_port = overrides.get("smtp_port", 587)
    s.smtp_username = overrides.get("smtp_username", "user@example.com")
    s.smtp_password = overrides.get("smtp_password", "secret")
    s.smtp_use_tls = overrides.get("smtp_use_tls", True)
    s.smtp_from = overrides.get("smtp_from")
    return s


# ---------------------------------------------------------------------------
# Test: SMTP not configured
# ---------------------------------------------------------------------------


class TestSendEmailSmtpNotConfigured:
    async def test_returns_false_when_smtp_host_none(self) -> None:
        settings = _smtp_settings(smtp_host=None)
        result = await send_email(
            settings=settings,
            to="user@example.com",
            subject="Test",
            html="<p>test</p>",
            text="test",
        )
        assert result is False

    async def test_returns_false_when_no_from_address(self) -> None:
        settings = _smtp_settings(smtp_username=None, smtp_from=None)
        result = await send_email(
            settings=settings,
            to="user@example.com",
            subject="Test",
            html="<p>test</p>",
            text="test",
        )
        assert result is False

    async def test_does_not_raise_when_smtp_host_none(self) -> None:
        settings = _smtp_settings(smtp_host=None)
        # Must not raise — callers rely on False return, not exception.
        try:
            await send_email(
                settings=settings,
                to="user@example.com",
                subject="Test",
                html="",
                text="",
            )
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"send_email raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# Test: SMTP exception path
# ---------------------------------------------------------------------------


class TestSendEmailSmtpError:
    async def test_returns_false_on_smtp_exception(self) -> None:
        settings = _smtp_settings()

        with patch(
            "drevalis.services.email.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=Exception("SMTP error"),
        ):
            result = await send_email(
                settings=settings,
                to="user@example.com",
                subject="Test",
                html="<p>test</p>",
                text="test",
            )
        assert result is False

    async def test_does_not_raise_on_smtp_exception(self) -> None:
        settings = _smtp_settings()

        with patch(
            "drevalis.services.email.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            try:
                await send_email(
                    settings=settings,
                    to="user@example.com",
                    subject="Test",
                    html="",
                    text="",
                )
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"send_email raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# Test: successful send
# ---------------------------------------------------------------------------


class TestSendEmailSuccess:
    async def test_returns_true_on_success(self) -> None:
        settings = _smtp_settings()

        with patch(
            "drevalis.services.email.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await send_email(
                settings=settings,
                to="user@example.com",
                subject="Test",
                html="<p>hi</p>",
                text="hi",
            )
        assert result is True

    async def test_uses_smtp_from_when_set(self) -> None:
        settings = _smtp_settings(smtp_from="noreply@drevalis.com")
        captured: dict[str, Any] = {}

        async def _capture(**kwargs: Any) -> None:
            captured.update(kwargs)

        with patch(
            "drevalis.services.email.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_thread:
            # Capture the kwargs passed to _send_sync via to_thread.
            def _side_effect(fn: Any, **kw: Any) -> Any:
                captured.update(kw)
                return AsyncMock(return_value=None)()

            mock_thread.side_effect = _side_effect
            await send_email(
                settings=settings,
                to="user@example.com",
                subject="Test",
                html="<p>hi</p>",
                text="hi",
            )

        # smtp_from wins over smtp_username.
        assert captured.get("from_addr") == "noreply@drevalis.com"

    async def test_falls_back_to_smtp_username_as_from(self) -> None:
        settings = _smtp_settings(smtp_from=None, smtp_username="sender@example.com")
        captured: dict[str, Any] = {}

        with patch(
            "drevalis.services.email.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_thread:

            def _side_effect(fn: Any, **kw: Any) -> Any:
                captured.update(kw)
                return AsyncMock(return_value=None)()

            mock_thread.side_effect = _side_effect
            await send_email(
                settings=settings,
                to="user@example.com",
                subject="Test",
                html="",
                text="",
            )

        assert captured.get("from_addr") == "sender@example.com"


# ---------------------------------------------------------------------------
# Test: masked recipient in log
# ---------------------------------------------------------------------------


class TestSendEmailMaskedLogging:
    async def test_send_success_logs_masked_recipient(self) -> None:
        """email.send_success event must use a masked address, not the real one.

        We verify by patching the logger that lives inside the email module
        (``drevalis.services.email.logger``) and checking that every captured
        call uses the masked form, not the raw address.
        """
        import drevalis.services.email as email_module

        settings = _smtp_settings()
        logged_events: list[dict[str, Any]] = []

        def _capture_info(event: str, **kw: Any) -> None:
            logged_events.append({"event": event, **kw})

        with patch(
            "drevalis.services.email.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch.object(email_module.logger, "info", side_effect=_capture_info):
                await send_email(
                    settings=settings,
                    to="john@example.com",
                    subject="Test",
                    html="",
                    text="",
                )

        # The real address must NOT appear anywhere in the captured calls.
        full_log = str(logged_events)
        assert "john@example.com" not in full_log
        # Masked form IS present.
        assert "j**@example.com" in full_log
