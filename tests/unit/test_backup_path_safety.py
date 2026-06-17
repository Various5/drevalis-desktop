"""Unit tests for restore-time path containment (CWE-22 guard).

``_is_unsafe_stored_path`` drops restored ``file_path`` values that are
absolute or escape the storage tree before they reach the DB, so a crafted
backup archive can't seed traversal paths that downstream export/render
sinks would later read.
"""

from __future__ import annotations

from drevalis.services.backup import _is_unsafe_stored_path


class TestIsUnsafeStoredPath:
    def test_relative_contained_is_safe(self) -> None:
        assert _is_unsafe_stored_path("episodes/abc/output/final.mp4") is False
        assert _is_unsafe_stored_path("voice_previews/x.wav") is False

    def test_absolute_posix_rejected(self) -> None:
        assert _is_unsafe_stored_path("/etc/passwd") is True

    def test_absolute_windows_rejected(self) -> None:
        assert _is_unsafe_stored_path("C:/Windows/win.ini") is True
        assert _is_unsafe_stored_path("C:\\Windows\\win.ini") is True

    def test_dotdot_escape_rejected(self) -> None:
        assert _is_unsafe_stored_path("../../secret.txt") is True
        assert _is_unsafe_stored_path("episodes/../../../etc/passwd") is True

    def test_non_string_or_empty_is_safe(self) -> None:
        assert _is_unsafe_stored_path(None) is False
        assert _is_unsafe_stored_path("") is False
        assert _is_unsafe_stored_path(123) is False
