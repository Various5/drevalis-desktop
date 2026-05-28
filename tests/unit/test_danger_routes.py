"""Tests for ``api/routes/danger.py`` — wipe-storage / reset-database /
delete-account.

These finish Phase 4's typed-confirm pattern; the tests pin the dangerous
behaviour to its safety rails:

* ``_wipe_storage_tree`` clears everything under the root, preserves the
  root directory itself, and reports a non-zero ``bytes_freed`` count.
* ``_tables_to_reset`` excludes the auth/license/migration substrate so a
  reset never logs the owner out.
* ``delete_account`` 403s for owners and clears the auth cookie for
  non-owners.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Response

from drevalis.api.routes.danger import (
    PROTECTED_TABLES,
    _tables_to_reset,
    _wipe_storage_tree,
    delete_account,
)


# ── _wipe_storage_tree ────────────────────────────────────────────────────


def test_wipe_storage_clears_files_and_subdirs(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"x" * 100)
    (tmp_path / "sub" / "deep").mkdir()
    (tmp_path / "sub" / "deep" / "c.dat").write_bytes(b"y" * 50)

    files_removed, bytes_freed = _wipe_storage_tree(tmp_path)

    # Root dir is preserved; everything inside it is gone.
    assert tmp_path.exists()
    assert list(tmp_path.iterdir()) == []
    assert files_removed == 3  # a.txt + b.bin + c.dat
    assert bytes_freed == len(b"hello") + 100 + 50


def test_wipe_storage_on_missing_root_is_a_noop(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    files_removed, bytes_freed = _wipe_storage_tree(missing)
    assert files_removed == 0
    assert bytes_freed == 0
    assert not missing.exists()


def test_wipe_storage_on_empty_root_returns_zero(tmp_path: Path) -> None:
    files_removed, bytes_freed = _wipe_storage_tree(tmp_path)
    assert files_removed == 0
    assert bytes_freed == 0
    assert tmp_path.exists()


# ── _tables_to_reset ──────────────────────────────────────────────────────


def test_tables_to_reset_excludes_the_auth_substrate() -> None:
    names = set(_tables_to_reset())
    assert names.isdisjoint(PROTECTED_TABLES)
    # Sanity: the protected set is what we expect — guards against someone
    # quietly removing a table from PROTECTED_TABLES.
    assert PROTECTED_TABLES == frozenset(
        {"users", "login_events", "license_state", "alembic_version"}
    )


def test_tables_to_reset_includes_known_user_data_tables() -> None:
    names = set(_tables_to_reset())
    # A few load-bearing user-data tables that must always end up wiped on a
    # reset (a regression here would mean "reset" leaks content silently).
    for required in ("episodes", "series", "generation_jobs", "scheduled_posts"):
        assert required in names, f"reset is missing {required}"


# ── delete_account ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_account_forbids_owners() -> None:
    owner = SimpleNamespace(id="abc", email="owner@example.com", role="owner")
    db = MagicMock()
    response = Response()
    with pytest.raises(HTTPException) as exc:
        await delete_account(response=response, db=db, user=owner)
    assert exc.value.status_code == 403
    # Nothing was executed — DB stayed untouched.
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_delete_account_clears_session_cookie_for_non_owner() -> None:
    user = SimpleNamespace(id="def", email="editor@example.com", role="editor")
    db = MagicMock()
    db.execute = MagicMock(return_value=None)

    async def _async_noop(*_args, **_kwargs):
        return None

    db.execute = _async_noop
    db.commit = _async_noop

    response = Response()
    out = await delete_account(response=response, db=db, user=user)
    assert out is response
    # delete_cookie sets a Set-Cookie header with the expired Max-Age.
    cookies = out.raw_headers
    assert any(
        b"drevalis_session=" in v and b"Max-Age=0" in v for k, v in cookies if k == b"set-cookie"
    )
