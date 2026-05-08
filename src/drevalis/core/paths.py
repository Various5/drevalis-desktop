"""OS-aware default paths for the desktop install.

Wraps ``platformdirs`` so the rest of the app can read defaults from a
single place. Resolved paths follow the standard per-OS conventions:

- Windows: ``%LOCALAPPDATA%\\Drevalis``
- macOS:   ``~/Library/Application Support/Drevalis``
- Linux:   ``~/.local/share/Drevalis``

Environment variables (or a ``.env`` file) still override every default
via :class:`drevalis.core.config.Settings`. These functions only supply
the fallback when the user hasn't configured a value.

Directories are **not** created at import time — call
:func:`ensure_user_dirs` once during application startup (e.g. in the
FastAPI lifespan or worker startup) so test imports stay side-effect-free.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

# ``appauthor`` would normally be the company name; on Windows it shows up
# as the parent directory under %LOCALAPPDATA%. Using the same value as
# ``appname`` keeps the on-disk layout flat: ``%LOCALAPPDATA%\Drevalis\``
# rather than ``%LOCALAPPDATA%\Drevalis\Drevalis\``.
_DIRS = PlatformDirs(appname="Drevalis", appauthor=False)


def user_data_dir() -> Path:
    """Per-OS user data directory (root of the Drevalis install)."""
    return Path(_DIRS.user_data_dir)


def user_log_dir() -> Path:
    """Per-OS user log directory.

    On Windows / Linux this is the same as ``user_data_dir``; on macOS
    platformdirs picks ``~/Library/Logs/Drevalis`` per Apple convention.
    """
    return Path(_DIRS.user_log_dir)


def storage_dir() -> Path:
    """Generated-asset storage root (`<user_data>/storage`)."""
    return user_data_dir() / "storage"


def sqlite_db_path() -> Path:
    """Default SQLite database file path."""
    return user_data_dir() / "drevalis.db"


def log_file_path() -> Path:
    """Default rotating log file path."""
    return user_log_dir() / "drevalis.log"


def piper_models_dir() -> Path:
    return storage_dir() / "models" / "piper"


def kokoro_models_dir() -> Path:
    return storage_dir() / "models" / "kokoro"


def backup_dir() -> Path:
    return user_data_dir() / "backups"


def default_database_url() -> str:
    """Default ``DATABASE_URL`` for desktop installs (SQLite under user data dir)."""
    return f"sqlite+aiosqlite:///{sqlite_db_path().as_posix()}"


def ensure_user_dirs() -> None:
    """Create the directories the desktop install expects on first run.

    Idempotent. Safe to call on every startup. Creates parents recursively.
    """
    for path in (
        user_data_dir(),
        user_log_dir(),
        storage_dir(),
        piper_models_dir(),
        kokoro_models_dir(),
        backup_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)
