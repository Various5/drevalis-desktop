"""Tests for LAN-exposure config — focus on token rotation (Phase 4) and the
soft enable/disable + token-generation invariants it relies on."""

from __future__ import annotations

from pathlib import Path

import pytest

from drevalis.core import network_config as nc


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the config file at a throwaway path so tests don't touch the
    real ``network.json``."""
    cfg = tmp_path / "network.json"
    monkeypatch.setattr(nc, "_config_path", lambda: cfg)


def test_enabling_generates_a_token() -> None:
    assert nc.is_lan_enabled() is False
    nc.set_lan_enabled(True)
    assert nc.is_lan_enabled() is True
    assert nc.get_api_token()  # truthy, persisted


def test_rotate_replaces_and_persists_the_token() -> None:
    nc.set_lan_enabled(True)
    first = nc.get_api_token()
    assert first

    second = nc.rotate_api_token()
    assert second
    assert second != first
    # The new token is what's persisted now.
    assert nc.peek_api_token() == second


def test_rotate_works_even_when_disabled() -> None:
    # Rotating while off still mints a fresh token (it just isn't surfaced in
    # the UI response until enabled).
    token = nc.rotate_api_token()
    assert token
    assert nc.peek_api_token() == token


def test_disable_keeps_the_token_for_next_enable() -> None:
    nc.set_lan_enabled(True)
    token = nc.get_api_token()
    nc.set_lan_enabled(False)
    # Token is retained (peek), so re-enabling reuses it rather than churning.
    assert nc.peek_api_token() == token
