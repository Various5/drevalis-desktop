"""Local filesystem storage backend with path-traversal protection.

All generated media is organized under a base directory with the layout::

    {base_path}/episodes/{episode_id}/voice/
    {base_path}/episodes/{episode_id}/scenes/
    {base_path}/episodes/{episode_id}/captions/
    {base_path}/episodes/{episode_id}/output/
    {base_path}/episodes/{episode_id}/temp/

Every public method validates that the resolved path stays within
``base_path`` to prevent directory-traversal attacks.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol
from uuid import UUID

import aiofiles
import aiofiles.os
import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Subdirectories created for every episode.
_EPISODE_SUBDIRS: tuple[str, ...] = ("voice", "scenes", "captions", "output", "temp")


class StorageBackend(Protocol):
    """Abstract storage protocol consumed by other services."""

    async def ensure_episode_dirs(self, episode_id: UUID) -> Path:
        """Create the full episode directory tree and return its root."""
        ...

    async def save_file(self, relative_path: str, content: bytes) -> Path:
        """Persist *content* at *relative_path* (relative to base_path).

        Parent directories are created automatically.  Returns the
        absolute path of the written file.
        """
        ...

    async def read_file(self, relative_path: str) -> bytes:
        """Read and return the raw bytes stored at *relative_path*."""
        ...

    async def delete_file(self, relative_path: str) -> bool:
        """Delete a single file.  Returns ``True`` if it existed."""
        ...

    async def delete_episode_dir(self, episode_id: UUID) -> bool:
        """Recursively delete the entire episode directory tree.

        Returns ``True`` if the directory existed.
        """
        ...

    async def get_episode_path(self, episode_id: UUID) -> Path:
        """Return the root directory for *episode_id* (may not exist yet)."""
        ...

    async def get_total_size_bytes(self) -> int:
        """Walk the entire base_path and return cumulative file size."""
        ...

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve *relative_path* against base_path and validate it."""
        ...


class PathTraversalError(Exception):
    """Raised when a resolved path escapes the storage base directory."""


class LocalStorage:
    """Local filesystem implementation of :class:`StorageBackend`."""

    def __init__(self, base_path: Path) -> None:
        self.base_path: Path = base_path.resolve()

    # ── helpers ─────────────────────────────────────────────────────────

    def _validate_path(self, resolved: Path) -> Path:
        """Ensure *resolved* is inside ``self.base_path``.

        Raises :class:`PathTraversalError` if the path escapes the base.
        """
        try:
            resolved.relative_to(self.base_path)
        except ValueError:
            raise PathTraversalError(
                f"Path {resolved} is outside the storage root {self.base_path}"
            ) from None
        return resolved

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve *relative_path* against base and validate it.

        The path is fully resolved (symlinks followed, ``..`` collapsed)
        before the containment check.
        """
        resolved = (self.base_path / relative_path).resolve()
        return self._validate_path(resolved)

    def _episode_root(self, episode_id: UUID) -> Path:
        """Return the canonical episode directory path."""
        return self.base_path / "episodes" / str(episode_id)

    # ── protocol methods ────────────────────────────────────────────────

    async def ensure_episode_dirs(self, episode_id: UUID) -> Path:
        """Create the full episode directory tree and return its root."""
        root = self._episode_root(episode_id)
        self._validate_path(root.resolve())

        for subdir in _EPISODE_SUBDIRS:
            dir_path = root / subdir
            await aiofiles.os.makedirs(str(dir_path), exist_ok=True)

        logger.info(
            "episode_dirs_ensured",
            episode_id=str(episode_id),
            path=str(root),
        )
        return root

    async def save_file(self, relative_path: str, content: bytes) -> Path:
        """Write *content* to *relative_path*, creating parents as needed."""
        target = self.resolve_path(relative_path)

        # Ensure parent directory exists.
        await aiofiles.os.makedirs(str(target.parent), exist_ok=True)

        async with aiofiles.open(str(target), mode="wb") as fh:
            await fh.write(content)

        logger.debug(
            "file_saved",
            path=str(target),
            size_bytes=len(content),
        )
        return target

    async def read_file(self, relative_path: str) -> bytes:
        """Read the bytes stored at *relative_path*."""
        target = self.resolve_path(relative_path)

        async with aiofiles.open(str(target), mode="rb") as fh:
            data: bytes = await fh.read()

        logger.debug("file_read", path=str(target), size_bytes=len(data))
        return data

    async def delete_file(self, relative_path: str) -> bool:
        """Delete a single file.  Returns ``True`` if the file existed."""
        target = self.resolve_path(relative_path)

        try:
            await aiofiles.os.remove(str(target))
            logger.debug("file_deleted", path=str(target))
            return True
        except FileNotFoundError:
            logger.debug("file_not_found_for_delete", path=str(target))
            return False

    async def delete_episode_dir(self, episode_id: UUID) -> bool:
        """Recursively delete the episode's directory tree."""
        root = self._episode_root(episode_id)
        self._validate_path(root.resolve())

        if not root.exists():
            logger.debug(
                "episode_dir_not_found",
                episode_id=str(episode_id),
            )
            return False

        # shutil.rmtree is blocking but works recursively.  We run it in
        # the default executor to avoid blocking the event loop.
        import asyncio

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, shutil.rmtree, root)

        logger.info(
            "episode_dir_deleted",
            episode_id=str(episode_id),
            path=str(root),
        )
        return True

    async def get_episode_path(self, episode_id: UUID) -> Path:
        """Return the root directory for *episode_id* (may not exist)."""
        root = self._episode_root(episode_id)
        self._validate_path(root.resolve())
        return root

    async def get_total_size_bytes(self) -> int:
        """Walk ``self.base_path`` and sum all file sizes."""
        import asyncio

        loop = asyncio.get_running_loop()

        def _walk_size() -> int:
            total = 0
            for item in self.base_path.rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
            return total

        total = await loop.run_in_executor(None, _walk_size)
        logger.debug("total_storage_size", size_bytes=total)
        return total
