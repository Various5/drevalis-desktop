"""Destructive admin actions — wipe storage, reset database, delete account.

These finish Phase 4's typed-confirm pattern: every operation is owner-gated
where appropriate and emits a WARNING-level audit log so the action surfaces
in the System Log UI (which filters to warning+). The frontend wires each
endpoint to ``ConfirmDangerousDialog`` with an action-specific confirm word
(WIPE / RESET / DELETE) so they can't be triggered by a stray click.

Tables protected from ``reset-database``: ``users``, ``login_events``,
``license_state``, ``alembic_version``. Everything else (episodes, series,
jobs, scheduled posts, API keys, voice/LLM/ComfyUI configs, …) gets dropped
so the user stays logged in but their workspace returns to empty.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.api.routes.auth import _COOKIE_NAME, require_owner, require_user
from drevalis.core.config import Settings
from drevalis.core.deps import get_db, get_settings
from drevalis.models.base import Base
from drevalis.models.user import User

router = APIRouter(prefix="/api/v1/danger", tags=["danger"])

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Identity / license / migration tables that survive a full DB reset so the
# user stays logged in, keeps their license, and the schema-version tracker
# stays in sync with the on-disk migrations. Everything else is content.
PROTECTED_TABLES: frozenset[str] = frozenset(
    {"users", "login_events", "license_state", "alembic_version"}
)


# ── Wipe storage ──────────────────────────────────────────────────────────


def _wipe_storage_tree(root: Path) -> tuple[int, int]:
    """Delete every entry under ``root`` (preserving ``root`` itself).

    Returns ``(files_removed, bytes_freed)``. Errors on individual entries
    are swallowed — wipe is best-effort and the caller already gated this
    behind a typed confirm.
    """
    files_removed = 0
    bytes_freed = 0
    if not root.exists():
        return files_removed, bytes_freed
    for entry in root.iterdir():
        if entry.is_file() or entry.is_symlink():
            try:
                bytes_freed += entry.stat().st_size
            except OSError:
                pass
            try:
                entry.unlink(missing_ok=True)
                files_removed += 1
            except OSError:
                pass
        elif entry.is_dir():
            for f in entry.rglob("*"):
                if f.is_file():
                    try:
                        bytes_freed += f.stat().st_size
                        files_removed += 1
                    except OSError:
                        pass
            shutil.rmtree(entry, ignore_errors=True)
    return files_removed, bytes_freed


@router.post("/wipe-storage", status_code=status.HTTP_200_OK)
async def wipe_storage(
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_owner),
) -> dict[str, int]:
    """Delete the contents of ``storage_base_path`` (preserves the dir).

    Removes every generated artifact (voice, scenes, renders, thumbnails,
    intermediate caches). The DB rows that referenced those files remain;
    use ``/reset-database`` for a coordinated wipe of both.
    """
    root = Path(settings.storage_base_path)
    files_removed, bytes_freed = _wipe_storage_tree(root)
    logger.warning(
        "storage.wiped",
        files_removed=files_removed,
        bytes_freed=bytes_freed,
        source="settings_ui",
    )
    return {"files_removed": files_removed, "bytes_freed": bytes_freed}


# ── Reset database ────────────────────────────────────────────────────────


def _tables_to_reset() -> list[str]:
    """Resolve the ordered list of table names to truncate.

    Uses SQLAlchemy's ``sorted_tables`` in reverse so FK children go before
    parents — the FK constraints are satisfied without disabling them.
    """
    return [
        t.name
        for t in reversed(Base.metadata.sorted_tables)
        if t.name not in PROTECTED_TABLES
    ]


@router.post("/reset-database", status_code=status.HTTP_200_OK)
async def reset_database(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_owner),
) -> dict[str, list[str]]:
    """Truncate every user-data table (keeps auth + license + migration tables).

    Runs in a single transaction so a mid-flight failure rolls back rather
    than leaving the schema half-emptied. The result lists the table names
    in the order they were cleared so the caller can show a confirmation.
    """
    truncated: list[str] = []
    for table_name in _tables_to_reset():
        await db.execute(text(f"DELETE FROM {table_name}"))  # noqa: S608 - table from allowlist
        truncated.append(table_name)
    await db.commit()
    logger.warning(
        "database.reset",
        tables=truncated,
        source="settings_ui",
    )
    return {"truncated": truncated}


# ── Delete account ────────────────────────────────────────────────────────


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> Response:
    """Hard-delete the calling user.

    Owners are protected: the desktop install would be unrecoverable without
    one, so we 403 rather than let the operator brick the app. Non-owner
    users (team mode) can delete themselves; we clear the auth cookie on the
    response so they're signed out immediately.
    """
    if user.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner accounts cannot be deleted from this device. "
            "Use Reset database to clear content while keeping the owner.",
        )
    await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(user.id)})
    await db.commit()
    response.delete_cookie(_COOKIE_NAME, path="/")
    logger.warning(
        "account.deleted",
        user_id=str(user.id),
        email=user.email,
        source="settings_ui",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
