"""Resolve sidecar binaries (FFmpeg, Redis) for the desktop install.

Lookup order:

1. ``resources/bin/<platform>/<name>(.exe)`` inside the running bundle
   or repo. PyInstaller-frozen runs use ``sys._MEIPASS``; source runs
   use the repository root.
2. The system ``PATH`` via :func:`shutil.which`.
3. ``None`` if neither finds the binary — the caller decides whether
   that's a hard failure or just degrades behavior.

Why this lives in ``core`` and not ``services``: it's policy about
binary resolution that ``Settings`` consumes via default_factory, and
that the launcher uses to point ``redis-server`` invocations at the
right path. Keeping it dependency-free (stdlib only) lets it import
during the Settings model_validator without circulars.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

__all__ = [
    "find_ffmpeg",
    "find_redis_server",
    "prepend_bundled_bin_to_path",
    "resources_root",
]


def _platform_dir() -> str:
    """Return the per-OS subdirectory name under resources/bin/."""
    if sys.platform == "win32":
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def _binary_filename(name: str) -> str:
    """Append .exe on Windows; otherwise return ``name`` unchanged."""
    return f"{name}.exe" if sys.platform == "win32" else name


def resources_root() -> Path:
    """Return the directory holding ``resources/bin/<platform>/``.

    For PyInstaller-frozen builds (``sys.frozen`` is True), the data
    directory lives at ``sys._MEIPASS`` (one-file) or alongside the
    executable (one-folder — the default for this project). The spec
    file's ``datas`` map places ``resources/`` at the top of that root.

    For source runs (uv / pip-installed editable), the repo root is the
    parent of ``src/``.
    """
    if getattr(sys, "frozen", False):
        # ``_MEIPASS`` is set in both one-file (extracted temp dir) and
        # one-folder (the binary's parent _internal directory) modes.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).parent

    # Source layout: this file lives at src/drevalis/core/binaries.py
    # → repo root is three parents up.
    return Path(__file__).resolve().parents[3]


def _bundled_binary(name: str) -> Path | None:
    """Return the bundled path for *name* if it exists, else ``None``."""
    candidate = resources_root() / "resources" / "bin" / _platform_dir() / _binary_filename(name)
    return candidate if candidate.is_file() else None


def find_ffmpeg() -> str:
    """Return an absolute FFmpeg path, falling back to the literal string ``"ffmpeg"``.

    The fallback string keeps backwards compatibility with the original
    config default (``Settings.ffmpeg_path = "ffmpeg"``); subprocess
    callers will still hit PATH if the binary isn't found here. We
    return a string (not Path) because most subprocess call sites pass
    it directly as ``argv[0]``.
    """
    bundled = _bundled_binary("ffmpeg")
    if bundled is not None:
        return str(bundled)
    on_path = shutil.which("ffmpeg")
    if on_path is not None:
        return on_path
    return "ffmpeg"


def prepend_bundled_bin_to_path() -> None:
    """Prepend ``resources/bin/<platform>/`` to ``$PATH`` for this process.

    Idempotent. The desktop port has many subprocess call sites that
    hardcode ``"ffmpeg"`` (rather than ``settings.ffmpeg_path``); rather
    than refactor every site, we prepend the bundle directory to PATH
    at process startup so the bundled binaries win over anything the
    user's shell happened to have. Child processes inherit this PATH
    via the default subprocess env.

    Safe no-op when the bundle directory doesn't exist (developer
    install with no sidecars, CI before fetch_sidecars.py, etc.).
    """
    bin_dir = resources_root() / "resources" / "bin" / _platform_dir()
    if not bin_dir.is_dir():
        return
    bin_str = str(bin_dir)
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if bin_str in parts:
        return
    os.environ["PATH"] = bin_str + (os.pathsep + current if current else "")


def find_redis_server() -> str | None:
    """Return an absolute Redis-server path, or ``None`` if no binary is reachable.

    Returns ``None`` (not a fallback string) because Redis is a Phase 3
    bundled-sidecar dependency: callers that need to spawn Redis must
    handle absence explicitly (e.g. point at a system-managed Redis,
    or surface a setup error). A bare ``"redis-server"`` fallback would
    paper over a misconfigured install.
    """
    bundled = _bundled_binary("redis-server")
    if bundled is not None:
        return str(bundled)
    on_path = shutil.which("redis-server")
    if on_path is not None:
        return on_path
    return None
