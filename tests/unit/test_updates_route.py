"""Tests for ``api/routes/updates.py``.

Self-update surface — pin:

* `/status` delegates to ``check_for_updates`` with the cache-bypass
  flag plumbed through.
* `/progress` reads the sidecar's status file; missing file → idle
  defaults; unreadable JSON → idle with a clarifying detail (so the
  UI doesn't crash on transient write-tear races).
* `/changelog` is the most defensive surface: serves stale cache on
  403, surfaces network errors as `error=...` (never raises 500),
  caches successful fetches for 1h.
* `/apply` 500s when the updater can't queue the request — the UI
  shows "we couldn't reach the sidecar" instead of crashing.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from drevalis.api.routes.updates import (
    apply_update,
    get_changelog,
    get_progress,
    get_status,
)


def _settings() -> Any:
    s = MagicMock()
    s.license_server_url = "https://license.test"
    return s


# ── GET /status ────────────────────────────────────────────────────


class TestGetStatus:
    async def test_returns_manifest(self) -> None:
        redis = AsyncMock()
        manifest = {
            "current_installed": "0.29.71",
            "current_stable": "0.29.72",
            "update_available": True,
            "image_tags": {"app": "drevalis/app:0.29.72"},
        }
        with patch(
            "drevalis.api.routes.updates.check_for_updates",
            AsyncMock(return_value=manifest),
        ) as cf:
            out = await get_status(force=False, settings=_settings(), redis=redis)
        assert out.update_available is True
        assert out.current_stable == "0.29.72"
        # Force flag is plumbed through verbatim.
        cf.assert_awaited_once()
        kwargs = cf.call_args.kwargs
        assert kwargs["force"] is False

    async def test_force_flag_passed_through(self) -> None:
        redis = AsyncMock()
        with patch(
            "drevalis.api.routes.updates.check_for_updates",
            AsyncMock(return_value={"update_available": False}),
        ) as cf:
            await get_status(force=True, settings=_settings(), redis=redis)
        assert cf.call_args.kwargs["force"] is True


# ── GET /progress ──────────────────────────────────────────────────


class TestGetProgress:
    async def test_idle_defaults_when_file_missing(self, tmp_path: Any) -> None:
        # Path is imported lazily inside the function; patch pathlib.Path
        # so the route's local lookup picks our stub up.
        bogus = tmp_path / "no-such-file.json"
        with patch("pathlib.Path", return_value=bogus):
            out = await get_progress()
        assert out.phase == "idle"
        assert out.detail == ""

    async def test_returns_phase_payload(self, tmp_path: Any) -> None:
        status_file = tmp_path / "update_status.json"
        status_file.write_text(
            json.dumps(
                {
                    "phase": "pulling",
                    "detail": "fetching app:0.29.72",
                    "ts": "2026-05-02T10:00:00Z",
                    "started_at": "2026-05-02T09:59:30Z",
                }
            )
        )
        with patch("pathlib.Path", return_value=status_file):
            out = await get_progress()
        assert out.phase == "pulling"
        assert "0.29.72" in out.detail

    async def test_unreadable_json_falls_back_to_idle_with_detail(self, tmp_path: Any) -> None:
        # File exists but contains garbage — pin: route returns idle with
        # an explanatory detail rather than 500.
        status_file = tmp_path / "update_status.json"
        status_file.write_text("{ not-json")
        with patch("pathlib.Path", return_value=status_file):
            out = await get_progress()
        assert out.phase == "idle"
        assert "unreadable" in out.detail


# ── GET /changelog ─────────────────────────────────────────────────


class TestChangelog:
    async def test_cached_short_circuits_github(self) -> None:
        redis = AsyncMock()
        cached = json.dumps(
            {
                "entries": [
                    {
                        "version": "v0.29.71",
                        "name": "v0.29.71",
                        "body": "auth route",
                    }
                ]
            }
        )
        redis.get = AsyncMock(return_value=cached)

        async def _no_http(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("GitHub must not be hit when cached")

        with patch("httpx.AsyncClient", side_effect=_no_http):
            out = await get_changelog(limit=20, force=False, redis=redis)
        assert out.cached is True
        assert out.entries[0].version == "v0.29.71"

    async def test_force_bypasses_cache(self) -> None:
        # Pin: when force=True we MUST NOT call redis.get for a cached
        # entry on the way in. (The route still tries to write back
        # later but that's a different concern.)
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b'{"entries": []}')
        redis.setex = AsyncMock()

        # Build a real httpx response via MockTransport to keep the test
        # fully deterministic.
        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v0.29.72",
                        "name": "v0.29.72",
                        "body": "release notes",
                        "published_at": "2026-05-02T10:00:00Z",
                        "html_url": "https://github.com/x/y/releases/tag/v0.29.72",
                        "prerelease": False,
                    }
                ],
            )

        real_client = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await get_changelog(limit=20, force=True, redis=redis)
        # force=True path doesn't call redis.get for the cache lookup.
        # (It may still call setex on the way out — that's fine.)
        assert out.cached is False
        assert len(out.entries) == 1
        assert out.entries[0].version == "v0.29.72"
        # Successful fetches are cached for an hour.
        redis.setex.assert_awaited_once()
        ttl = redis.setex.call_args.args[1]
        assert ttl == 3600

    async def test_403_serves_stale_cache(self) -> None:
        # GitHub returned 403 (rate limited / corp proxy). If we have
        # stale cache, return it with an explanatory error rather than
        # an empty list.
        redis = AsyncMock()
        # First .get is the live-cache lookup; route must skip it on
        # force=True. We're testing force=True so only the fallback
        # cache lookup at 403 fires. Make redis.get always return cache.
        cached = json.dumps(
            {"entries": [{"version": "v0.29.50", "name": "v0.29.50", "body": "old"}]}
        )
        redis.get = AsyncMock(return_value=cached)

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "rate limit"})

        real_client = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await get_changelog(limit=20, force=True, redis=redis)
        assert out.cached is True
        assert out.error is not None
        assert "rate limited" in out.error

    async def test_403_no_cache_returns_helpful_error(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        real_client = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await get_changelog(limit=20, force=True, redis=redis)
        assert out.entries == []
        assert "rate limited" in out.error  # type: ignore[operator]

    async def test_non_200_non_403_status_returns_error(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        real_client = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await get_changelog(limit=20, force=True, redis=redis)
        assert out.error is not None
        assert "500" in out.error

    async def test_network_error_surfaces_as_error_field(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        def _h(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns down")

        real_client = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await get_changelog(limit=20, force=True, redis=redis)
        assert out.error is not None
        assert "ConnectError" in out.error

    async def test_unexpected_error_does_not_crash(self) -> None:
        # Pin: an unexpected exception type must STILL produce a
        # ChangelogResponse(error=...) instead of 500.
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        def _h(_request: httpx.Request) -> httpx.Response:
            raise RuntimeError("kaboom")

        real_client = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await get_changelog(limit=20, force=True, redis=redis)
        assert out.error is not None

    async def test_403_with_redis_failure_returns_helpful_error(self) -> None:
        # 403 fallback path also has its own try/except around redis.get
        # — pin: a redis failure inside the fallback still yields the
        # helpful error string rather than crashing.
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        real_client = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await get_changelog(limit=20, force=True, redis=redis)
        assert out.error is not None
        assert "rate limited" in out.error

    async def test_cache_value_is_empty_falls_through(self) -> None:
        # Pin the 144→151 partial-branch: cache key exists but is empty
        # / falsy — must NOT short-circuit. Route must still hit GitHub.
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"")
        redis.setex = AsyncMock()

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[{"tag_name": "v0.29.72", "name": "v0.29.72", "body": ""}],
            )

        real_client = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await get_changelog(limit=20, force=False, redis=redis)
        assert out.cached is False
        assert len(out.entries) == 1

    async def test_redis_get_failure_falls_through_to_live_fetch(self) -> None:
        # Redis GET raises (server flaky) — route must still produce a
        # response by hitting GitHub, not 500.
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        redis.setex = AsyncMock(side_effect=ConnectionError("redis down"))

        def _h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[{"tag_name": "v0.29.72", "name": "v0.29.72", "body": ""}],
            )

        real_client = httpx.AsyncClient

        def _patched(*args: Any, **kwargs: Any) -> Any:
            kwargs["transport"] = httpx.MockTransport(_h)
            return real_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=_patched):
            out = await get_changelog(limit=20, force=False, redis=redis)
        assert len(out.entries) == 1


# ── POST /apply ────────────────────────────────────────────────────


class TestApplyUpdate:
    async def test_success(self) -> None:
        with patch(
            "drevalis.api.routes.updates.request_update_apply",
            AsyncMock(),
        ):
            out = await apply_update()
        assert out.queued is True
        assert "60 seconds" in out.hint or "sidecar" in out.hint

    async def test_oserror_maps_to_500(self) -> None:
        # Updater sidecar isn't running / shared volume isn't mounted →
        # the IO that creates the flag file fails. Pin: 500 with a
        # structured detail the UI can render.
        with patch(
            "drevalis.api.routes.updates.request_update_apply",
            AsyncMock(side_effect=OSError("read-only filesystem")),
        ):
            with pytest.raises(HTTPException) as exc:
                await apply_update()
        assert exc.value.status_code == 500
        assert exc.value.detail["error"] == "could_not_queue_update"
