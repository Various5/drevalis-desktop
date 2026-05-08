"""Unit tests for URL and filename validation utilities.

Coverage targets
----------------
* ``validate_safe_url`` -- blocks loopback, private ranges, link-local, and
  non-HTTP schemes; passes valid public URLs.
* ``validate_safe_url_or_localhost`` -- same as above but allows loopback
  (localhost / 127.0.0.1 / ::1).
* ``sanitize_filename`` -- strips path components and dangerous characters.

All tests that target IP-literal inputs avoid network I/O because the
validators short-circuit on IP literals before calling ``socket.getaddrinfo``.
Tests that would require real DNS resolution are skipped in this unit suite
and delegated to integration tests instead.
"""

from __future__ import annotations

import pytest

from drevalis.core.validators import (
    UnsafeURLError,
    sanitize_filename,
    validate_safe_url,
    validate_safe_url_or_localhost,
)

# ---------------------------------------------------------------------------
# validate_safe_url -- scheme checks
# ---------------------------------------------------------------------------


class TestValidateSafeUrlScheme:
    """Non-HTTP(S) schemes must always be rejected."""

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/file.txt",
            "file:///etc/passwd",
            "ssh://user@host",
            "gopher://host/resource",
            "data:text/plain,hello",
        ],
    )
    def test_non_http_scheme_rejected(self, url: str) -> None:
        with pytest.raises(UnsafeURLError, match="scheme must be http or https"):
            validate_safe_url(url)

    def test_http_scheme_not_rejected_on_scheme_check(self) -> None:
        # http with a public IP passes the scheme check (IP check runs after).
        # We verify by using a known public IP; the function returns the URL.
        result = validate_safe_url("http://8.8.8.8/path")
        assert result == "http://8.8.8.8/path"

    def test_https_scheme_accepted(self) -> None:
        result = validate_safe_url("https://8.8.8.8/path")
        assert result == "https://8.8.8.8/path"


# ---------------------------------------------------------------------------
# validate_safe_url -- loopback (127.x.x.x)
# ---------------------------------------------------------------------------


class TestValidateSafeUrlLoopback:
    """Loopback addresses must be blocked by validate_safe_url."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/api",
            "http://127.0.0.1:8080/endpoint",
            "http://127.1.2.3/test",
            "http://127.255.255.255/x",
        ],
    )
    def test_ipv4_loopback_rejected(self, url: str) -> None:
        with pytest.raises(UnsafeURLError, match="Loopback"):
            validate_safe_url(url)

    def test_ipv6_loopback_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="Loopback"):
            validate_safe_url("http://[::1]/api")


# ---------------------------------------------------------------------------
# validate_safe_url -- private IP ranges (RFC 1918)
# ---------------------------------------------------------------------------


class TestValidateSafeUrlPrivateRanges:
    """Private network ranges must be blocked."""

    @pytest.mark.parametrize(
        "url",
        [
            # 10.0.0.0/8
            "http://10.0.0.1/api",
            "http://10.255.255.255/x",
            # 172.16.0.0/12
            "http://172.16.0.1/api",
            "http://172.31.255.255/x",
            # 192.168.0.0/16
            "http://192.168.1.1/api",
            "http://192.168.0.1:9090/endpoint",
        ],
    )
    def test_rfc1918_addresses_rejected(self, url: str) -> None:
        with pytest.raises(UnsafeURLError, match="Private network"):
            validate_safe_url(url)


# ---------------------------------------------------------------------------
# validate_safe_url -- link-local (169.254.x.x)
# ---------------------------------------------------------------------------


class TestValidateSafeUrlLinkLocal:
    """Link-local / cloud metadata addresses must be blocked."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.0.1/",
            "http://169.254.169.254/latest/meta-data/",  # AWS metadata
            "http://169.254.170.2/metadata",
        ],
    )
    def test_link_local_ipv4_rejected(self, url: str) -> None:
        with pytest.raises(UnsafeURLError):
            validate_safe_url(url)

    def test_ipv6_link_local_rejected(self) -> None:
        # fe80::/10 is the IPv6 link-local range
        with pytest.raises(UnsafeURLError):
            validate_safe_url("http://[fe80::1]/api")


# ---------------------------------------------------------------------------
# validate_safe_url -- valid public URLs pass
# ---------------------------------------------------------------------------


class TestValidateSafeUrlPublicAddresses:
    """Public IP addresses and well-known hostnames must be accepted."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://8.8.8.8/dns-query",
            "http://1.1.1.1/",
            "https://93.184.216.34/",  # example.com IP
        ],
    )
    def test_public_ip_accepted(self, url: str) -> None:
        result = validate_safe_url(url)
        assert result == url

    def test_returns_original_url_unchanged(self) -> None:
        url = "https://8.8.8.8/path?query=1"
        assert validate_safe_url(url) == url


# ---------------------------------------------------------------------------
# validate_safe_url_or_localhost -- loopback is ALLOWED here
# ---------------------------------------------------------------------------


class TestValidateSafeUrlOrLocalhost:
    """validate_safe_url_or_localhost must allow loopback but still block cloud
    metadata and other dangerous targets."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/api",
            "http://localhost:8080/path",
            "http://127.0.0.1/api",
            "http://127.0.0.1:1234/v1",
        ],
    )
    def test_loopback_allowed(self, url: str) -> None:
        result = validate_safe_url_or_localhost(url)
        assert result == url

    def test_ipv6_loopback_allowed(self) -> None:
        result = validate_safe_url_or_localhost("http://[::1]/api")
        assert result == "http://[::1]/api"

    def test_cloud_metadata_still_blocked(self) -> None:
        with pytest.raises(UnsafeURLError):
            validate_safe_url_or_localhost("http://169.254.169.254/latest/meta-data/")

    def test_link_local_still_blocked(self) -> None:
        with pytest.raises(UnsafeURLError):
            validate_safe_url_or_localhost("http://169.254.0.1/")

    def test_ipv6_link_local_still_blocked(self) -> None:
        with pytest.raises(UnsafeURLError):
            validate_safe_url_or_localhost("http://[fe80::1]/api")

    def test_non_http_scheme_still_blocked(self) -> None:
        with pytest.raises(UnsafeURLError, match="scheme must be http or https"):
            validate_safe_url_or_localhost("ftp://localhost/file")

    def test_public_ip_accepted(self) -> None:
        result = validate_safe_url_or_localhost("https://8.8.8.8/path")
        assert result == "https://8.8.8.8/path"

    def test_private_ip_allowed_for_local_services(self) -> None:
        # Private ranges (10.x, 192.168.x) are allowed -- they're legitimate
        # for local-first apps reaching LAN services such as ComfyUI.
        result = validate_safe_url_or_localhost("http://192.168.1.50:8188/api")
        assert result == "http://192.168.1.50:8188/api"

    def test_missing_hostname_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="hostname"):
            validate_safe_url_or_localhost("http:///path")


# ---------------------------------------------------------------------------
# validate_safe_url -- edge / boundary cases
# ---------------------------------------------------------------------------


class TestValidateSafeUrlEdgeCases:
    """Boundary and malformed input cases."""

    def test_url_without_hostname_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="hostname"):
            validate_safe_url("http:///no-hostname")

    def test_url_with_port_on_public_ip(self) -> None:
        result = validate_safe_url("http://8.8.8.8:8080/path")
        assert result == "http://8.8.8.8:8080/path"

    def test_172_16_boundary_rejected(self) -> None:
        # First address in 172.16.0.0/12 -- must be blocked.
        with pytest.raises(UnsafeURLError):
            validate_safe_url("http://172.16.0.0/")

    def test_172_32_boundary_accepted(self) -> None:
        # 172.32.0.0 is outside the private range and is public.
        result = validate_safe_url("http://172.32.0.1/")
        assert result == "http://172.32.0.1/"

    def test_multicast_ipv4_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="[Mm]ulticast"):
            validate_safe_url("http://224.0.0.1/stream")


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    """sanitize_filename must strip path components and dangerous characters."""

    def test_plain_filename_unchanged(self) -> None:
        assert sanitize_filename("video.mp4") == "video.mp4"

    def test_filename_with_spaces_replaced(self) -> None:
        result = sanitize_filename("my video file.mp4")
        assert " " not in result
        assert result.endswith(".mp4")

    def test_unix_path_stripped_to_basename(self) -> None:
        result = sanitize_filename("/etc/passwd")
        assert result == "passwd"

    def test_windows_path_stripped_to_basename(self) -> None:
        result = sanitize_filename("C:\\Users\\admin\\secret.txt")
        assert result == "secret.txt"

    def test_relative_traversal_component_stripped(self) -> None:
        # The basename of "../../etc/passwd" is "passwd".
        result = sanitize_filename("../../etc/passwd")
        assert result == "passwd"

    def test_dangerous_characters_replaced_with_underscore(self) -> None:
        result = sanitize_filename("file;rm -rf *.mp4")
        assert ";" not in result
        assert " " not in result
        assert "*" not in result

    def test_allowed_characters_preserved(self) -> None:
        filename = "my-video_v2.final.mp4"
        assert sanitize_filename(filename) == filename

    def test_dot_only_filename_gets_prefix(self) -> None:
        result = sanitize_filename(".")
        assert result.startswith("file_")

    def test_hidden_file_gets_prefix(self) -> None:
        # A filename starting with a dot is potentially problematic.
        result = sanitize_filename(".hidden")
        assert result.startswith("file_")

    def test_empty_string_gets_prefix(self) -> None:
        result = sanitize_filename("")
        assert result.startswith("file_")

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("normal.txt", "normal.txt"),
            ("with spaces.txt", "with_spaces.txt"),
            ("UPPER.MP4", "UPPER.MP4"),
            ("under_score-dash.mp4", "under_score-dash.mp4"),
        ],
    )
    def test_parametrized_common_inputs(self, raw: str, expected: str) -> None:
        assert sanitize_filename(raw) == expected
