"""Tests for LocalStorage service."""

from __future__ import annotations

from uuid import uuid4

import pytest

from drevalis.services.storage import LocalStorage, PathTraversalError


class TestEnsureEpisodeDirs:
    """Test directory creation for episodes."""

    async def test_ensure_episode_dirs_creates_structure(self, storage: LocalStorage) -> None:
        episode_id = uuid4()
        root = await storage.ensure_episode_dirs(episode_id)

        assert root.exists()
        assert root == storage.base_path / "episodes" / str(episode_id)

        expected_subdirs = {"voice", "scenes", "captions", "output", "temp"}
        actual_subdirs = {d.name for d in root.iterdir() if d.is_dir()}
        assert actual_subdirs == expected_subdirs

    async def test_ensure_episode_dirs_idempotent(self, storage: LocalStorage) -> None:
        episode_id = uuid4()
        root1 = await storage.ensure_episode_dirs(episode_id)
        root2 = await storage.ensure_episode_dirs(episode_id)
        assert root1 == root2
        assert root1.exists()


class TestSaveAndReadFile:
    """Test file persistence and retrieval."""

    async def test_save_and_read_file(self, storage: LocalStorage) -> None:
        content = b"Hello, Drevalis!"
        relative_path = "test/hello.txt"

        saved_path = await storage.save_file(relative_path, content)
        assert saved_path.exists()
        assert saved_path == storage.base_path / "test" / "hello.txt"

        read_content = await storage.read_file(relative_path)
        assert read_content == content

    async def test_save_creates_parent_dirs(self, storage: LocalStorage) -> None:
        content = b"deep nested file"
        relative_path = "a/b/c/d/deep.bin"

        saved_path = await storage.save_file(relative_path, content)
        assert saved_path.exists()

        read_back = await storage.read_file(relative_path)
        assert read_back == content

    async def test_save_overwrites_existing(self, storage: LocalStorage) -> None:
        relative_path = "overwrite_test.txt"
        await storage.save_file(relative_path, b"version 1")
        await storage.save_file(relative_path, b"version 2")

        result = await storage.read_file(relative_path)
        assert result == b"version 2"


class TestDeleteFile:
    """Test file deletion."""

    async def test_delete_file(self, storage: LocalStorage) -> None:
        relative_path = "to_delete.txt"
        await storage.save_file(relative_path, b"delete me")

        assert await storage.delete_file(relative_path) is True

        # Second delete should return False (already gone)
        assert await storage.delete_file(relative_path) is False

    async def test_delete_nonexistent_file(self, storage: LocalStorage) -> None:
        assert await storage.delete_file("nonexistent.txt") is False


class TestDeleteEpisodeDir:
    """Test recursive directory deletion."""

    async def test_delete_episode_dir(self, storage: LocalStorage) -> None:
        episode_id = uuid4()
        root = await storage.ensure_episode_dirs(episode_id)

        # Write a file into one of the subdirectories
        await storage.save_file(f"episodes/{episode_id}/scenes/image.png", b"\x89PNG")

        assert root.exists()
        result = await storage.delete_episode_dir(episode_id)
        assert result is True
        assert not root.exists()

    async def test_delete_nonexistent_episode_dir(self, storage: LocalStorage) -> None:
        result = await storage.delete_episode_dir(uuid4())
        assert result is False


class TestPathTraversalBlocked:
    """Test that relative paths with ../ are blocked."""

    async def test_path_traversal_blocked_save(self, storage: LocalStorage) -> None:
        with pytest.raises(PathTraversalError):
            await storage.save_file("../../etc/passwd", b"malicious")

    async def test_path_traversal_blocked_read(self, storage: LocalStorage) -> None:
        with pytest.raises(PathTraversalError):
            await storage.read_file("../../etc/passwd")

    async def test_path_traversal_blocked_delete(self, storage: LocalStorage) -> None:
        with pytest.raises(PathTraversalError):
            await storage.delete_file("../../../outside.txt")

    def test_path_traversal_blocked_resolve(self, storage: LocalStorage) -> None:
        with pytest.raises(PathTraversalError):
            storage.resolve_path("../../../etc/shadow")


class TestResolvePathWithinBase:
    """Test that resolve_path returns paths within base_path."""

    def test_resolve_path_within_base(self, storage: LocalStorage) -> None:
        resolved = storage.resolve_path("episodes/test/file.txt")
        assert str(storage.base_path) in str(resolved)
        # Must be relative to base
        resolved.relative_to(storage.base_path)

    def test_resolve_path_normalizes(self, storage: LocalStorage) -> None:
        # A path that stays within base after normalization
        resolved = storage.resolve_path("a/b/../c/file.txt")
        assert "a/c" in str(resolved).replace("\\", "/") or "a\\c" in str(resolved)
        resolved.relative_to(storage.base_path)


class TestGetTotalSizeBytes:
    """Test total storage size calculation."""

    async def test_get_total_size_bytes_empty(self, storage: LocalStorage) -> None:
        total = await storage.get_total_size_bytes()
        assert total == 0

    async def test_get_total_size_bytes_with_files(self, storage: LocalStorage) -> None:
        await storage.save_file("a.txt", b"12345")  # 5 bytes
        await storage.save_file("b.txt", b"1234567890")  # 10 bytes

        total = await storage.get_total_size_bytes()
        assert total == 15

    async def test_get_total_size_bytes_nested(self, storage: LocalStorage) -> None:
        episode_id = uuid4()
        await storage.ensure_episode_dirs(episode_id)
        await storage.save_file(f"episodes/{episode_id}/scenes/img.png", b"x" * 100)
        await storage.save_file(f"episodes/{episode_id}/voice/audio.wav", b"y" * 200)

        total = await storage.get_total_size_bytes()
        assert total == 300
