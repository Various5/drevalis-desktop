"""URL and path validation utilities for SSRF and traversal prevention."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a URL targets a private/internal network or uses a blocked scheme."""


def validate_safe_url(url: str, *, pin_dns: bool = False) -> str | tuple[str, str]:
    """Validate that *url* is a safe HTTP(S) URL not targeting internal networks.

    Blocks:
    - Non-HTTP(S) schemes
    - Private/internal IP ranges: 10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x
    - IPv6 loopback (::1) and unique-local (fc00::/7)
    - Unresolvable hostnames

    Args:
        url: The URL to validate.
        pin_dns: If True, returns ``(url, resolved_ip)`` so callers can connect
            to the resolved IP directly, preventing DNS rebinding attacks.

    Returns:
        The original URL string if safe (when ``pin_dns=False``), or a tuple
        of ``(url, resolved_ip)`` when ``pin_dns=True``.

    Raises:
        UnsafeURLError: if the URL targets a blocked destination or scheme.
    """
    parsed = urlparse(url)

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"URL scheme must be http or https, got {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URL must include a hostname")

    # Resolve hostname to IP addresses and check each one
    resolved_ip = _check_hostname(hostname)

    if pin_dns:
        return url, resolved_ip
    return url


def _check_hostname(hostname: str) -> str:
    """Resolve *hostname* and verify none of its addresses are private/internal.

    Returns the first resolved IP address string for DNS pinning.
    """
    # First, check if hostname is already an IP literal
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # Not an IP literal, resolve it below
    else:
        _check_ip(addr)  # UnsafeURLError propagates up
        return str(addr)

    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURLError(f"Could not resolve hostname: {hostname!r}") from None

    if not addr_infos:
        raise UnsafeURLError(f"Could not resolve hostname: {hostname!r}")

    first_ip: str = ""
    for family, _, _, _, sockaddr in addr_infos:
        ip_str = str(sockaddr[0])
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue  # Malformed IP string — skip this entry
        _check_ip(addr)  # UnsafeURLError propagates up — NOT caught
        if not first_ip:
            first_ip = ip_str

    return first_ip


def _check_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Raise UnsafeURLError if *addr* is a private/internal address.

    Order matters: Python's ``ipaddress`` classifies 169.254/16 as BOTH
    private and link-local. If the private check ran first every cloud
    metadata endpoint would surface to the operator as "private
    network address" — technically correct, but useless for debugging
    SSRF attempts against metadata services. Link-local runs first so
    the error message points at the real category.
    """
    if addr.is_loopback:
        raise UnsafeURLError(f"Loopback addresses are not allowed: {addr}")
    if addr.is_link_local:
        raise UnsafeURLError(f"Link-local addresses are not allowed: {addr}")
    # Additional explicit 169.254/16 guard covers any edge where
    # is_link_local returns False but the address is still in range.
    if isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.IPv4Network("169.254.0.0/16"):
        raise UnsafeURLError(f"Link-local addresses are not allowed: {addr}")
    if addr.is_private:
        raise UnsafeURLError(f"Private network addresses are not allowed: {addr}")
    if addr.is_reserved:
        raise UnsafeURLError(f"Reserved addresses are not allowed: {addr}")
    if addr.is_multicast:
        raise UnsafeURLError(f"Multicast addresses are not allowed: {addr}")


def validate_safe_url_or_localhost(url: str) -> str:
    """Like validate_safe_url but also allows localhost/127.0.0.1 for local-first apps.

    This is the default validator used by Drevalis since it is a
    local-first application that legitimately needs to reach local services
    (ComfyUI, LM Studio, etc.).

    Still blocks:
    - Non-HTTP(S) schemes
    - Cloud metadata endpoints (169.254.x.x)
    - Private ranges other than loopback (10.x, 172.16-31.x, 192.168.x)
    - IPv6 unique-local (fc00::/7) except ::1
    """
    parsed = urlparse(url)

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"URL scheme must be http or https, got {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URL must include a hostname")

    # Allow localhost explicitly
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return url

    # For non-localhost, check for dangerous targets
    _check_hostname_local_first(hostname)

    return url


def _check_hostname_local_first(hostname: str) -> None:
    """Resolve *hostname* and block metadata/dangerous endpoints but allow private."""
    # Check if hostname is an IP literal
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # Not an IP literal, resolve below
    else:
        _check_ip_local_first(addr)  # UnsafeURLError propagates
        return

    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURLError(f"Could not resolve hostname: {hostname!r}") from None

    if not addr_infos:
        raise UnsafeURLError(f"Could not resolve hostname: {hostname!r}")

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue  # Malformed IP string — skip
        _check_ip_local_first(addr)  # UnsafeURLError propagates


def _check_ip_local_first(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Block link-local/metadata addresses but allow loopback and private for local-first apps."""
    if addr.is_link_local:
        raise UnsafeURLError(f"Link-local addresses are not allowed: {addr}")
    if isinstance(addr, ipaddress.IPv4Address):
        if addr in ipaddress.IPv4Network("169.254.0.0/16"):
            raise UnsafeURLError(f"Cloud metadata endpoint addresses are not allowed: {addr}")
    if addr.is_multicast:
        raise UnsafeURLError(f"Multicast addresses are not allowed: {addr}")


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename by stripping path components and dangerous characters.

    Cross-platform: treats both ``/`` and ``\\`` as path separators regardless
    of the host OS (``os.path.basename`` alone does not, so a Windows path
    like ``C:\\Users\\x\\f.txt`` would survive into the basename on Linux).
    Also strips any Windows drive prefix (``C:``).

    Returns only the final segment, with non-alphanumeric chars (except
    ``._-``) replaced by ``_``.
    """
    # Take the last component after EITHER separator, regardless of host OS.
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    # Strip any residual Windows drive prefix (e.g., "C:file.txt").
    if len(basename) >= 2 and basename[1] == ":":
        basename = basename[2:]
    # Only allow safe characters
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", basename)
    # Prevent empty or dot-only filenames
    if not sanitized or sanitized.startswith("."):
        sanitized = "file_" + sanitized
    return sanitized
