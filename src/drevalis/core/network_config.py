"""LAN API exposure config.

A desktop install binds its backend to ``127.0.0.1`` so the API is only
reachable from the machine itself. Some operators (e.g. managing a testing
stage over the LAN) want it reachable from other hosts. This module is the
persisted, UI-toggleable switch for that:

* ``lan_api_enabled`` — when true, uvicorn binds ``0.0.0.0`` instead of
  loopback. Read once at process start (see ``__main__._run_api_inproc``),
  so toggling it requires an app restart to take effect.
* ``api_token`` — a bearer token that ``OptionalAPIKeyMiddleware`` requires
  on **non-loopback** requests once LAN access is on. Loopback (the local
  webview) is always exempt, so the local UI keeps working without it. This
  is what stops "expose to LAN" from meaning "expose to LAN with no auth".

State lives in ``<user_data_dir>/network.json`` rather than the DB so the
bootstrap path can read it before the DB/event-loop exist, and an explicit
``DREVALIS_API_HOST`` env var always overrides it (CI / power users).
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import socket
import threading
from pathlib import Path

from drevalis.core.paths import user_data_dir

_FILENAME = "network.json"
_LOCK = threading.Lock()

# Host this process actually bound to, recorded at startup. Lets the
# settings route tell the UI "restart required" when the persisted toggle
# no longer matches the running bind. ``None`` until recorded (e.g. dev
# source-mode runs that don't go through the in-process launcher).
_runtime_bind_host: str | None = None


def _config_path() -> Path:
    return user_data_dir() / _FILENAME


def load() -> dict:
    """Return the parsed config, or ``{}`` when missing/unreadable."""
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename so a crash mid-write can't leave a truncated file
    # that would wipe the toggle/token on next boot.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def is_lan_enabled() -> bool:
    return bool(load().get("lan_api_enabled", False))


def set_lan_enabled(enabled: bool) -> dict:
    """Flip the toggle and persist. Enabling guarantees a token exists."""
    with _LOCK:
        data = load()
        data["lan_api_enabled"] = bool(enabled)
        if enabled and not data.get("api_token"):
            data["api_token"] = secrets.token_hex(32)
        _save(data)
        return data


def get_api_token() -> str | None:
    """The bearer token remote callers must present.

    Lazily generated and persisted so it survives restarts. Returns
    ``None`` only when generation can't be persisted (read-only FS) — the
    middleware treats that the same as "no token configured".
    """
    with _LOCK:
        data = load()
        token = data.get("api_token")
        if token:
            return str(token)
        token = secrets.token_hex(32)
        data["api_token"] = token
        try:
            _save(data)
        except OSError:
            return None
        return token


def peek_api_token() -> str | None:
    """Read the token WITHOUT generating one. For the request hot-path."""
    token = load().get("api_token")
    return str(token) if token else None


def rotate_api_token() -> str:
    """Generate + persist a fresh LAN token, replacing the old one, and return
    it. Remote callers keep working on the old token until the backend
    restarts (the auth middleware reads the token once at startup), same as the
    bind-host change — so the UI flags ``restart_required`` after a rotate too."""
    with _LOCK:
        data = load()
        token = secrets.token_hex(32)
        data["api_token"] = token
        _save(data)
        return token


def get_bind_host() -> str:
    """Host uvicorn should bind to.

    An explicit ``DREVALIS_API_HOST`` always wins (CI / power-user
    override); otherwise it follows the persisted toggle.
    """
    env = os.environ.get("DREVALIS_API_HOST")
    if env:
        return env
    return "0.0.0.0" if is_lan_enabled() else "127.0.0.1"


def record_runtime_bind_host(host: str) -> None:
    global _runtime_bind_host
    _runtime_bind_host = host


def runtime_bind_host() -> str | None:
    return _runtime_bind_host


# Address ranges never worth advertising as a reachable LAN URL: loopback,
# APIPA link-local, and the 172.16/12 block that Docker, WSL2 and Hyper-V
# "vEthernet" switches carve their virtual adapters out of. Filtering by
# range (not adapter name) keeps this stdlib-only and cross-platform.
_HIDDEN_LAN_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
)


def _is_advertisable(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not any(addr in net for net in _HIDDEN_LAN_NETS)


def lan_ipv4_addresses() -> list[str]:
    """Best-effort list of this host's advertisable LAN IPv4 addresses.

    Used purely to show the operator the reachable URLs in the UI. Both
    lookups are wrapped — neither is allowed to break the settings page.

    Loopback, link-local (169.254/16) and the 172.16/12 block used by
    Docker / WSL2 / Hyper-V vEthernet adapters are filtered out so the panel
    lists only addresses another machine can actually reach. The primary
    outbound interface (the UDP-connect probe below) is kept regardless of
    range — it is by definition the reachable default route.
    """
    addrs: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _is_advertisable(ip):
                addrs.add(ip)
    except OSError:
        pass
    # UDP-connect trick: no packets sent, but the socket picks the primary
    # outbound interface, which getaddrinfo sometimes misses. This is the
    # genuine default route, so keep it even if it falls in a filtered range
    # (only loopback is meaningless to advertise).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                addrs.add(ip)
        finally:
            s.close()
    except OSError:
        pass
    return sorted(addrs)
