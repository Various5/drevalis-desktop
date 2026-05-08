"""Tests for the per-user preferences endpoints.

Mirrors the existing ``test_auth_route`` pattern (MagicMock for db
+ session_version-aware fixture user) so we don't need the conftest
SQLite seam.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from drevalis.api.routes.auth import get_preferences, update_preferences
from drevalis.models.user import User


def _make_user(prefs: dict[str, object] | None = None) -> User:
    u = User(
        email="t@example.com",
        password_hash="x",
        role="owner",
        is_active=True,
        last_login_at=datetime.now(tz=UTC),
        session_version=0,
        totp_confirmed_at=None,
    )
    u.id = uuid4()
    # ``preferences`` is a NOT NULL column with server default ``{}`` —
    # the ORM exposes whatever we set; default to an empty dict for the
    # test seam since no migration runs in unit tests.
    u.preferences = prefs if prefs is not None else {}
    return u


@pytest.mark.asyncio
async def test_get_preferences_empty_for_new_user() -> None:
    user = _make_user()
    result = await get_preferences(user=user)
    assert result == {}


@pytest.mark.asyncio
async def test_get_preferences_returns_existing() -> None:
    user = _make_user({"theme": "dark", "dashboard_layout": {"widgets": ["a"]}})
    result = await get_preferences(user=user)
    assert result == {"theme": "dark", "dashboard_layout": {"widgets": ["a"]}}


@pytest.mark.asyncio
async def test_update_preferences_merges_into_existing() -> None:
    user = _make_user({"theme": "dark", "calendar_view": "week"})
    db = MagicMock()
    db.commit = AsyncMock()

    result = await update_preferences(
        body={"dashboard_layout": {"widgets": ["a", "b"]}},
        user=user,
        db=db,
    )
    # Existing keys preserved; new key added.
    assert result == {
        "theme": "dark",
        "calendar_view": "week",
        "dashboard_layout": {"widgets": ["a", "b"]},
    }
    assert user.preferences == result
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_preferences_null_value_deletes_top_level_key() -> None:
    user = _make_user({"theme": "dark", "calendar_view": "week"})
    db = MagicMock()
    db.commit = AsyncMock()

    result = await update_preferences(
        body={"theme": None},
        user=user,
        db=db,
    )
    assert "theme" not in result
    assert result == {"calendar_view": "week"}


@pytest.mark.asyncio
async def test_update_preferences_overwrites_top_level_key_value() -> None:
    """Top-level keys are REPLACED on PUT, not deep-merged.

    Clients are expected to read-modify-write the whole namespaced
    blob if they want partial updates inside a feature's prefs.
    """
    user = _make_user({"dashboard_layout": {"widgets": ["a"], "hidden": []}})
    db = MagicMock()
    db.commit = AsyncMock()

    result = await update_preferences(
        body={"dashboard_layout": {"widgets": ["b"]}},
        user=user,
        db=db,
    )
    # ``hidden`` is gone — the top-level value was replaced.
    assert result == {"dashboard_layout": {"widgets": ["b"]}}


@pytest.mark.asyncio
async def test_update_preferences_with_empty_body_is_noop() -> None:
    user = _make_user({"theme": "dark"})
    db = MagicMock()
    db.commit = AsyncMock()

    result = await update_preferences(body={}, user=user, db=db)
    assert result == {"theme": "dark"}
    # Commit still fires — clients can use this as a "ping" to refresh
    # the materialized view, and the no-op write is cheap.
    db.commit.assert_awaited_once()
