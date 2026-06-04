"""Tests for ``api/routes/system.py`` — the decoupled desktop update check.

This endpoint deliberately bypasses the Tauri updater IPC (see the module
docstring), so the behaviour worth pinning is:

* SemVer-precedence comparison across the formats the project ships
  (``1.0.0``, ``1.0.0-rc.4``, ``0.1.0-alpha.50``) — numeric, not lexical.
* The version source precedence (``DREVALIS_RELEASE`` wins on desktop).
* The endpoint always returns 200 and degrades to ``update_available=False``
  with a ``reason`` when the manifest can't be fetched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from drevalis.api.routes.system import (
    _current_app_version,
    _is_newer,
    update_status,
)


class TestVersionComparison:
    @pytest.mark.parametrize(
        ("latest", "current"),
        [
            ("1.0.0-rc.4", "1.0.0-rc.3"),  # later rc
            ("1.0.0", "1.0.0-rc.4"),  # final outranks its pre-release
            ("1.0.0-rc.1", "0.1.0-alpha.99"),  # higher release line wins
            ("1.0.0-rc.10", "1.0.0-rc.9"),  # numeric identifiers, not lexical
            ("1.2.0", "1.1.9"),
            ("v1.0.0", "1.0.0-rc.4"),  # leading 'v' tolerated
            ("1.0.0-beta.1", "1.0.0-alpha.1"),  # beta > alpha
        ],
    )
    def test_newer(self, latest: str, current: str) -> None:
        assert _is_newer(latest, current) is True

    @pytest.mark.parametrize(
        ("latest", "current"),
        [
            ("1.0.0-rc.4", "1.0.0-rc.4"),  # equal → not newer (no banner)
            ("1.0.0-rc.3", "1.0.0-rc.4"),  # older
            ("1.0.0-rc.4", "1.0.0"),  # rc is behind the final
            ("0.1.0-alpha.99", "1.0.0-rc.1"),  # lower release line
            ("1.0.0-rc.9", "1.0.0-rc.10"),  # numeric: 9 < 10
        ],
    )
    def test_not_newer(self, latest: str, current: str) -> None:
        assert _is_newer(latest, current) is False


class TestCurrentVersion:
    def test_prefers_drevalis_release(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DREVALIS_RELEASE", "1.2.3")
        monkeypatch.setenv("APP_VERSION", "9.9.9")
        assert _current_app_version() == "1.2.3"

    def test_falls_back_to_app_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DREVALIS_RELEASE", raising=False)
        monkeypatch.setenv("APP_VERSION", "4.5.6")
        assert _current_app_version() == "4.5.6"


class TestUpdateStatusEndpoint:
    async def test_update_available_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DREVALIS_RELEASE", "1.0.0-rc.3")
        manifest = {
            "version": "1.0.0-rc.4",
            "notes": "Bug fixes",
            "pub_date": "2026-06-01T00:00:00Z",
        }
        with patch(
            "drevalis.api.routes.system._fetch_manifest",
            AsyncMock(return_value=manifest),
        ):
            resp = await update_status(channel="stable", redis=AsyncMock())
        assert resp.update_available is True
        assert resp.current_version == "1.0.0-rc.3"
        assert resp.latest_version == "1.0.0-rc.4"
        assert resp.channel == "stable"
        assert resp.download_url.endswith("/releases/latest")
        assert resp.notes == "Bug fixes"
        assert resp.reason is None

    async def test_no_update_when_on_latest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DREVALIS_RELEASE", "1.0.0-rc.4")
        with patch(
            "drevalis.api.routes.system._fetch_manifest",
            AsyncMock(return_value={"version": "1.0.0-rc.4"}),
        ):
            resp = await update_status(channel="stable", redis=AsyncMock())
        assert resp.update_available is False
        assert resp.latest_version == "1.0.0-rc.4"
        assert resp.reason is None

    async def test_graceful_when_manifest_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DREVALIS_RELEASE", "1.0.0-rc.4")
        with patch(
            "drevalis.api.routes.system._fetch_manifest",
            AsyncMock(return_value=None),
        ):
            resp = await update_status(channel="rc", redis=AsyncMock())
        assert resp.update_available is False
        assert resp.reason == "unavailable"
        assert resp.channel == "rc"
        assert resp.latest_version is None

    async def test_unknown_channel_normalizes_to_stable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DREVALIS_RELEASE", "1.0.0-rc.4")
        captured: dict[str, str] = {}

        async def fake_fetch(channel: str, redis: object) -> dict:
            captured["channel"] = channel
            return {"version": "1.0.0-rc.4"}

        with patch("drevalis.api.routes.system._fetch_manifest", fake_fetch):
            resp = await update_status(channel="garbage", redis=AsyncMock())
        assert captured["channel"] == "stable"
        assert resp.channel == "stable"
