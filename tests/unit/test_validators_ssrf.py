"""Tests for SSRF validator — DNS rebinding fix and pin_dns feature."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from drevalis.core.validators import UnsafeURLError, validate_safe_url


class TestPinDnsFeature:
    """Test the pin_dns parameter added to prevent DNS rebinding."""

    @patch("drevalis.core.validators.socket.getaddrinfo")
    def test_pin_dns_returns_tuple(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0)),
        ]
        result = validate_safe_url("https://example.com", pin_dns=True)
        assert isinstance(result, tuple)
        assert result[0] == "https://example.com"
        assert result[1] == "93.184.216.34"

    @patch("drevalis.core.validators.socket.getaddrinfo")
    def test_no_pin_dns_returns_string(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0)),
        ]
        result = validate_safe_url("https://example.com", pin_dns=False)
        assert isinstance(result, str)
        assert result == "https://example.com"

    @patch("drevalis.core.validators.socket.getaddrinfo")
    def test_default_pin_dns_is_false(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0)),
        ]
        result = validate_safe_url("https://example.com")
        assert isinstance(result, str)


class TestUnsafeURLErrorNotSwallowed:
    """Critical regression test: UnsafeURLError (a ValueError subclass)
    must NOT be silently caught by except ValueError in _check_hostname.
    """

    @patch("drevalis.core.validators.socket.getaddrinfo")
    def test_private_ip_raises_unsafe(self, mock_getaddrinfo):
        """Hostname resolving to 10.x.x.x must raise UnsafeURLError."""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0)),
        ]
        with pytest.raises(UnsafeURLError, match="Private"):
            validate_safe_url("https://evil-rebind.example.com")

    @patch("drevalis.core.validators.socket.getaddrinfo")
    def test_loopback_raises_unsafe(self, mock_getaddrinfo):
        """Hostname resolving to 127.0.0.1 must raise UnsafeURLError."""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
        ]
        with pytest.raises(UnsafeURLError, match="Loopback"):
            validate_safe_url("https://evil-rebind.example.com")

    @patch("drevalis.core.validators.socket.getaddrinfo")
    def test_link_local_raises_unsafe(self, mock_getaddrinfo):
        """Hostname resolving to 169.254.x.x must raise UnsafeURLError."""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0)),
        ]
        with pytest.raises(UnsafeURLError, match="Link-local"):
            validate_safe_url("https://metadata.example.com")

    def test_ip_literal_private_raises(self):
        """Direct private IP literal must raise UnsafeURLError."""
        with pytest.raises(UnsafeURLError, match="Private"):
            validate_safe_url("https://192.168.1.1/admin")

    def test_unsafe_url_error_is_value_error_subclass(self):
        """Confirm UnsafeURLError inherits ValueError — the fix ensures
        this subclass relationship doesn't cause silent swallowing."""
        assert issubclass(UnsafeURLError, ValueError)
