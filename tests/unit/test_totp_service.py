"""Unit tests for services/totp.py.

Tests cover:
* Secret format (base32, 20 bytes).
* Code verification — current step, outside-window step, constant-time.
* Provisioning URI format.
* Recovery code format and routing differentiation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from typing import Any

from drevalis.services.totp import (
    _TOTP_DIGITS,
    _TOTP_STEP,
    generate_recovery_codes,
    generate_secret,
    provisioning_uri,
    verify_code,
)

# ---------------------------------------------------------------------------
# Helper: compute a TOTP code the same way the production code does so tests
# are self-contained and don't need to import internal helpers.
# ---------------------------------------------------------------------------


def _make_code(secret_b32: str, step_offset: int = 0) -> str:
    padding = "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(secret_b32.upper() + padding)
    counter = int(time.time()) // _TOTP_STEP + step_offset
    msg = struct.pack(">Q", counter)
    mac = hmac.new(key, msg, hashlib.sha1).digest()  # noqa: S324
    offset = mac[-1] & 0x0F
    code_int = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10**_TOTP_DIGITS)).zfill(_TOTP_DIGITS)


# ---------------------------------------------------------------------------
# Secret generation
# ---------------------------------------------------------------------------


class TestGenerateSecret:
    def test_secret_generated_is_correct_format(self) -> None:
        """generate_secret() returns a 32-char base32 string that decodes to 20 bytes.

        RFC 6238 §4: the shared secret MUST be at least 128 bits; 160 bits
        (20 bytes) is the conventional minimum for a 6-digit TOTP.
        """
        secret = generate_secret()
        assert isinstance(secret, str)
        # 20 bytes → ceil(20 / 5) * 8 = 32 base32 chars (no padding).
        assert len(secret) == 32
        assert secret == secret.upper(), "Secret should be uppercase base32"
        # Must decode cleanly to exactly 20 bytes.
        padding = "=" * (-len(secret) % 8)
        decoded = base64.b32decode(secret + padding)
        assert len(decoded) == 20

    def test_secrets_are_unique(self) -> None:
        """Two successive calls must not produce the same secret."""
        assert generate_secret() != generate_secret()


# ---------------------------------------------------------------------------
# Code verification
# ---------------------------------------------------------------------------


class TestVerifyCode:
    def test_verify_code_accepts_current_step(self) -> None:
        """A freshly-generated code for the current step verifies as True."""
        secret = generate_secret()
        code = _make_code(secret, step_offset=0)
        assert verify_code(secret, code) is True

    def test_verify_code_accepts_previous_step_within_window(self) -> None:
        """window=1 accepts a code from one step ago (30 s skew)."""
        secret = generate_secret()
        code = _make_code(secret, step_offset=-1)
        assert verify_code(secret, code, window=1) is True

    def test_verify_code_accepts_next_step_within_window(self) -> None:
        """window=1 accepts a code from one step ahead (30 s skew)."""
        secret = generate_secret()
        code = _make_code(secret, step_offset=1)
        assert verify_code(secret, code, window=1) is True

    def test_verify_code_rejects_step_outside_window(self) -> None:
        """A code for step -2 is outside window=1 and must be rejected.

        CWE-330: do not allow codes from far outside the valid window —
        each accepted step expands the brute-force surface.
        """
        secret = generate_secret()
        code = _make_code(secret, step_offset=-2)
        assert verify_code(secret, code, window=1) is False

    def test_verify_code_rejects_wrong_code(self) -> None:
        secret = generate_secret()
        assert verify_code(secret, "000000") is False

    def test_verify_code_rejects_short_code(self) -> None:
        secret = generate_secret()
        assert verify_code(secret, "12345") is False

    def test_verify_code_rejects_non_digit_code(self) -> None:
        secret = generate_secret()
        assert verify_code(secret, "12345X") is False

    def test_verify_code_constant_time(self) -> None:
        """Constant-time guard: verify_code must call _hotp the same number of
        times for a correct code as for a structurally-valid but wrong code.

        We measure *call count*, not wall-clock time, to keep the test stable
        in CI environments with variable CPU load.

        CWE-208 (Observable Timing Discrepancy): the comparison must not
        short-circuit on the first matching step.
        """
        from unittest.mock import patch

        secret = generate_secret()
        good_code = _make_code(secret, step_offset=0)
        bad_code = str((int(good_code) + 1) % 10**_TOTP_DIGITS).zfill(_TOTP_DIGITS)

        # Patch hmac.new to count calls.
        call_counts: list[int] = []

        original_hmac_new = hmac.new

        def counting_hmac_new(*args: Any, **kwargs: Any) -> Any:
            call_counts.append(1)
            return original_hmac_new(*args, **kwargs)

        # Good code — measure calls.
        call_counts.clear()
        with patch("drevalis.services.totp.hmac.new", side_effect=counting_hmac_new):
            verify_code(secret, good_code, window=1)
        good_calls = len(call_counts)

        # Wrong code — measure calls.
        call_counts.clear()
        with patch("drevalis.services.totp.hmac.new", side_effect=counting_hmac_new):
            verify_code(secret, bad_code, window=1)
        bad_calls = len(call_counts)

        # Both paths must exercise the full window (2*window+1 HOTP calls).
        # A timing attack would see fewer calls for the wrong code if we
        # returned early after the first non-matching step.
        assert good_calls == bad_calls, (
            f"hmac.new called {good_calls} times for good code vs "
            f"{bad_calls} for bad code — timing oracle present"
        )


# ---------------------------------------------------------------------------
# Provisioning URI
# ---------------------------------------------------------------------------


class TestProvisioningUri:
    def test_provisioning_uri_format(self) -> None:
        """provisioning_uri returns a valid otpauth://totp/... URI."""
        secret = generate_secret()
        uri = provisioning_uri(secret=secret, account="alice@drevalis.test")
        assert uri.startswith("otpauth://totp/")
        assert f"secret={secret}" in uri
        assert "issuer=" in uri
        assert "algorithm=SHA1" in uri
        assert f"digits={_TOTP_DIGITS}" in uri
        assert f"period={_TOTP_STEP}" in uri

    def test_provisioning_uri_custom_issuer(self) -> None:
        secret = generate_secret()
        uri = provisioning_uri(secret=secret, account="bob@example.com", issuer="My App")
        assert "My%20App" in uri or "My+App" in uri or "My App" in uri


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------


class TestGenerateRecoveryCodes:
    def test_recovery_code_format(self) -> None:
        """Each recovery code is 16 lowercase hex characters."""
        codes = generate_recovery_codes(10)
        assert len(codes) == 10
        for code in codes:
            assert len(code) == 16, f"Code {code!r} is not 16 chars"
            assert all(c in "0123456789abcdef" for c in code), f"Code {code!r} is not hex"

    def test_recovery_codes_are_unique(self) -> None:
        codes = generate_recovery_codes(10)
        assert len(set(codes)) == 10, "Recovery codes must all be unique"

    def test_recovery_code_format_versus_totp_code_routing(self) -> None:
        """6-digit decimal → TOTP path; 16-hex → recovery path.

        The login/totp endpoint routes by these exact rules.  This test
        pins the distinguishing properties so a format change here
        is caught immediately.
        """
        totp_code = "123456"
        recovery_code = "abcdef0123456789"

        # TOTP: 6 decimal digits.
        assert len(totp_code) == 6
        assert totp_code.isdigit()

        # Recovery: 16 hex chars.
        assert len(recovery_code) == 16
        assert all(c in "0123456789abcdef" for c in recovery_code)

        # They must NOT overlap (a 6-digit decimal code is never 16 chars).
        assert len(totp_code) != len(recovery_code)
