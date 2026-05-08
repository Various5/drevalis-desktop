"""Tests for ``api/routes/backup.py`` — `storage_probe` + hint engine.

The diagnostic surface that drives the Backup → "Why can't I see my
videos?" debug screen. Pin the hint catalogue:

* `storage_base_path` doesn't exist → "Docker volume mount" hint.
* `API_AUTH_TOKEN` configured → "browser <video> can't send Bearer" hint.
* storage or episodes dir is a symlink → StaticFiles follow_symlink hint.
* Sample assets exist on disk but aren't readable → chown hint.
* Sample assets are symlinks → "follow_symlinks=False" hint.
* `host_source_path` looks VM-internal (Docker Desktop labels) → the
  "started compose from a different directory" walkthrough.
* `host_source_path` looks like a real host path → "media must live
  under that directory" hint.
* Container sees ≤2 files at top level + non-backup dirs are empty
  → "containers were started from a different directory" hint.
* Container sees a few files but suspiciously low total bytes → "bind
  source pointing somewhere different" hint.
* No problems detected → fall-through "no obvious problem detected"
  hint pointing the user at DevTools.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.api.routes.backup import (
    _STORAGE_PROBE_CACHE_KEY,
    _STORAGE_PROBE_CACHE_TTL_S,
    _storage_probe_hints,
    storage_probe,
)


def _settings(tmp_path: Path, *, api_auth: str | None = None) -> Any:
    s = MagicMock()
    s.storage_base_path = tmp_path
    s.api_auth_token = api_auth
    return s


def _redis_miss() -> Any:
    """Redis stub that returns None on get and accepts setex calls."""
    r = MagicMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock(return_value=True)
    return r


# ── _storage_probe_hints ───────────────────────────────────────────


class TestStorageProbeHints:
    def test_missing_storage_base_path(self) -> None:
        hints = _storage_probe_hints(
            {
                "storage_base_exists": False,
                "samples": [],
                "top_level_entries": [],
                "total_visible_count": 0,
                "total_visible_bytes": 0,
            }
        )
        assert any("Docker volume mount" in h for h in hints)

    def test_api_auth_token_configured(self) -> None:
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "api_auth_token_configured": True,
                "samples": [],
                "top_level_entries": [{"name": "episodes", "kind": "dir", "child_count": 5}],
                "total_visible_count": 5,
                "total_visible_bytes": 1_000_000,
            }
        )
        assert any("API_AUTH_TOKEN" in h for h in hints)

    def test_storage_base_symlink_hint(self) -> None:
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "storage_base_is_symlink": True,
                "samples": [],
                "top_level_entries": [],
                "total_visible_count": 0,
                "total_visible_bytes": 0,
            }
        )
        assert any("symlink" in h.lower() for h in hints)

    def test_episodes_dir_symlink_hint(self) -> None:
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "episodes_dir_is_symlink": True,
                "samples": [],
                "top_level_entries": [],
                "total_visible_count": 0,
                "total_visible_bytes": 0,
            }
        )
        assert any("symlink" in h.lower() for h in hints)

    def test_unreadable_samples_chown_hint(self) -> None:
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "samples": [
                    {"exists": True, "readable": False, "is_symlink": False},
                    {"exists": True, "readable": True, "is_symlink": False},
                ],
                "process_uid": 1000,
                "process_gid": 1000,
                "top_level_entries": [{"name": "episodes", "kind": "dir", "child_count": 5}],
                "total_visible_count": 5,
                "total_visible_bytes": 1_000_000,
            }
        )
        assert any("chown" in h and "1000:1000" in h for h in hints)

    def test_symlinked_samples_hint(self) -> None:
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "samples": [
                    {"exists": True, "readable": True, "is_symlink": True},
                ],
                "top_level_entries": [{"name": "episodes", "kind": "dir", "child_count": 5}],
                "total_visible_count": 5,
                "total_visible_bytes": 1_000_000,
            }
        )
        assert any("symlinks" in h and "follow_symlinks" in h for h in hints)

    def test_vm_internal_host_source_hint(self) -> None:
        # Pin: Docker Desktop's `/project/` / `/run/desktop/` /
        # `/mnt/host_mnt/` labels surface the multi-line guided
        # walkthrough about `%USERPROFILE%\Drevalis\`.
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "host_source_path": "/project/storage",
                "samples": [],
                "top_level_entries": [{"name": "episodes", "kind": "dir", "child_count": 5}],
                "total_visible_count": 5,
                "total_visible_bytes": 1_000_000,
            }
        )
        assert any("Docker Desktop" in h and "USERPROFILE" in h for h in hints)
        # Sanity-check command also appears.
        assert any("docker inspect" in h for h in hints)

    def test_var_lib_docker_treated_as_vm_internal(self) -> None:
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "host_source_path": "/var/lib/docker/volumes/x",
                "samples": [],
                "top_level_entries": [{"name": "episodes", "kind": "dir", "child_count": 5}],
                "total_visible_count": 5,
                "total_visible_bytes": 1_000_000,
            }
        )
        assert any("Docker Desktop" in h for h in hints)

    def test_real_host_source_hint(self) -> None:
        # Pin: a regular host path emits the simpler "media must live
        # under that directory" hint instead of the Windows walkthrough.
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "host_source_path": "/srv/data/storage",
                "samples": [],
                "top_level_entries": [{"name": "episodes", "kind": "dir", "child_count": 5}],
                "total_visible_count": 5,
                "total_visible_bytes": 1_000_000,
            }
        )
        assert any("/srv/data/storage" in h and "must live under" in h for h in hints)

    def test_empty_container_hint(self) -> None:
        # Pin: container sees ≤2 entries AND non-backup dirs are empty
        # → guides the user toward the "wrong compose directory" answer.
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "samples": [],
                "top_level_entries": [
                    {"name": "episodes", "kind": "dir", "child_count": 0},
                ],
                "total_visible_count": 0,
                "total_visible_bytes": 0,
            }
        )
        assert any("0–1 files" in h and "different directory" in h for h in hints)

    async def test_low_byte_count_hint(self) -> None:
        # Container sees content but it's <1 MB total — likely the wrong
        # bind source on a copied install.
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "samples": [],
                "top_level_entries": [
                    {"name": "episodes", "kind": "dir", "child_count": 3},
                ],
                "total_visible_count": 3,
                "total_visible_bytes": 500_000,  # < 1 MB
            }
        )
        assert any("totalling 500000 bytes" in h for h in hints)

    def test_no_problems_returns_devtools_hint(self) -> None:
        # Pin: when nothing's wrong, the route still returns one hint
        # pointing the user at DevTools — silent passes mean the user
        # has nothing to act on.
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "samples": [{"exists": True, "readable": True, "is_symlink": False}],
                "top_level_entries": [
                    {"name": "episodes", "kind": "dir", "child_count": 100},
                    {"name": "audiobooks", "kind": "dir", "child_count": 10},
                ],
                "total_visible_count": 110,
                "total_visible_bytes": 100_000_000,  # 100 MB — substantial
            }
        )
        assert any("DevTools" in h for h in hints)

    def test_backup_only_dir_treated_as_empty_when_others_zero(
        self,
    ) -> None:
        # Pin: "backups" entries are filtered out of the empty-detection
        # check so a fresh install with only auto-backups doesn't trigger
        # the "wrong directory" warning.
        hints = _storage_probe_hints(
            {
                "storage_base_exists": True,
                "samples": [],
                "top_level_entries": [
                    {"name": "backups", "kind": "dir", "child_count": 5},
                ],
                "total_visible_count": 5,
                "total_visible_bytes": 100_000_000,  # backups are big
            }
        )
        # No empty-container hint (all non-backup dirs filtered out → []
        # → empty_non_backup defaults True → triggered) — but visible_count
        # is > 2, so the "0–1 files" hint should NOT fire.
        assert not any("0–1 files" in h for h in hints)


# ── storage_probe (full route) ─────────────────────────────────────


class TestStorageProbeRoute:
    async def test_missing_storage_base(self, tmp_path: Path) -> None:
        # Storage base doesn't exist on disk — pin: route returns a
        # report flagging that fact rather than 500ing.
        non_existent = tmp_path / "no-storage"
        s = MagicMock()
        s.storage_base_path = non_existent
        s.api_auth_token = None

        # No DB rows; sample_types loop produces no entries.
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await storage_probe(db=db, settings=s, redis=_redis_miss())
        assert out["storage_base_exists"] is False
        assert out["samples"] == []
        # Hints flagged the missing path.
        assert any("Docker volume mount" in h for h in out["hints"])

    async def test_lists_top_level_entries_with_kinds(self, tmp_path: Path) -> None:
        # Build a real storage tree: 1 file, 2 directories.
        (tmp_path / "loose.txt").write_bytes(b"x" * 100)
        (tmp_path / "episodes").mkdir()
        (tmp_path / "episodes" / "ep1.mp4").write_bytes(b"x" * 200)
        (tmp_path / "audiobooks").mkdir()

        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=_redis_miss())

        assert out["storage_base_exists"] is True
        assert out["episodes_dir_exists"] is True
        assert out["audiobooks_dir_exists"] is True
        # Top-level entries include all 3 children.
        names = {e["name"] for e in out["top_level_entries"]}
        assert names == {"loose.txt", "episodes", "audiobooks"}
        # File counted in total_visible_bytes.
        loose_entry = next(e for e in out["top_level_entries"] if e["name"] == "loose.txt")
        assert loose_entry["kind"] == "file"
        assert loose_entry["size_bytes"] == 100
        # Dir count is the bounded subcount.
        ep_entry = next(e for e in out["top_level_entries"] if e["name"] == "episodes")
        assert ep_entry["kind"] == "dir"
        assert ep_entry["child_count"] == 1
        assert ep_entry["child_count_capped"] is False

    async def test_capped_dir_marker_set(self, tmp_path: Path) -> None:
        # Pin: when a child dir has > 1000 entries, child_count_capped
        # is True so the UI can show a "1000+" indicator.
        big_dir = tmp_path / "episodes"
        big_dir.mkdir()
        for i in range(1005):
            (big_dir / f"f{i}.mp4").write_bytes(b"")

        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=_redis_miss())
        ep = next(e for e in out["top_level_entries"] if e["name"] == "episodes")
        assert ep["child_count"] == 1000
        assert ep["child_count_capped"] is True

    async def test_samples_run_real_byte_read(self, tmp_path: Path) -> None:
        # Stage a real video file. The route MUST read the first byte
        # of the file (mimicking StaticFiles.send_file) to confirm the
        # Python process can actually serve it.
        (tmp_path / "episodes").mkdir()
        ep_id = uuid4()
        ep_dir = tmp_path / "episodes" / str(ep_id) / "output"
        ep_dir.mkdir(parents=True)
        video = ep_dir / "final.mp4"
        video.write_bytes(b"\x00" * 1024)

        rel_path = f"episodes/{ep_id}/output/final.mp4"
        row = SimpleNamespace(
            id=uuid4(),
            asset_type="video",
            file_path=rel_path,
            episode_id=ep_id,
        )

        # First lookup yields the row, all others yield none.
        results: list[Any] = []
        for kind in ("video", "thumbnail", "scene", "caption", "voiceover"):
            r = MagicMock()
            scalars = MagicMock()
            scalars.all = MagicMock(return_value=[row] if kind == "video" else [])
            r.scalars = MagicMock(return_value=scalars)
            results.append(r)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=results)

        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=_redis_miss())

        assert len(out["samples"]) == 1
        sample = out["samples"][0]
        assert sample["asset_type"] == "video"
        assert sample["exists"] is True
        assert sample["readable"] is True
        assert sample["size_bytes"] == 1024
        assert sample["is_symlink"] is False
        # URL the route would have served at.
        assert sample["url_served_at"] == f"/storage/{rel_path}"

    async def test_samples_path_does_not_exist(self, tmp_path: Path) -> None:
        # DB row exists but the file is gone (post-restore mismatch) —
        # pin: exists=False, readable=False, no exception.
        row = SimpleNamespace(
            id=uuid4(),
            asset_type="video",
            file_path="episodes/abc/missing.mp4",
            episode_id=uuid4(),
        )
        results: list[Any] = []
        for kind in ("video", "thumbnail", "scene", "caption", "voiceover"):
            r = MagicMock()
            scalars = MagicMock()
            scalars.all = MagicMock(return_value=[row] if kind == "video" else [])
            r.scalars = MagicMock(return_value=scalars)
            results.append(r)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=results)

        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=_redis_miss())
        sample = out["samples"][0]
        assert sample["exists"] is False
        assert sample["readable"] is False

    async def test_iterdir_failure_recorded_as_error_entry(self, tmp_path: Path) -> None:
        # Pin: when listing the top of storage_base raises (e.g.
        # permission denied on the bind mount), the route records an
        # error entry rather than 500ing.
        # We force this by patching Path.iterdir on the storage_base.
        original_iterdir = Path.iterdir

        def _fake_iterdir(self: Path, *args: Any, **kwargs: Any) -> Any:
            if str(self) == str(tmp_path):
                raise OSError("permission denied")
            return original_iterdir(self, *args, **kwargs)

        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        with patch.object(Path, "iterdir", _fake_iterdir):
            out = await storage_probe(db=db, settings=_settings(tmp_path), redis=_redis_miss())

        # The error landed in top_level_entries.
        assert any("error" in e for e in out["top_level_entries"])


# ── Cache layer ────────────────────────────────────────────────────


class TestStorageProbeCache:
    async def test_fresh_compute_marks_cached_false_and_writes_cache(self, tmp_path: Path) -> None:
        # Pin: on a cache miss, the route computes the report, marks
        # ``cached: false``, attaches a ``cached_at`` timestamp, and
        # writes the result back to Redis with the documented TTL.
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        redis = _redis_miss()
        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=redis)

        assert out["cached"] is False
        assert "cached_at" in out
        # setex called with the correct key + TTL.
        redis.setex.assert_awaited_once()
        args = redis.setex.await_args.args
        assert args[0] == _STORAGE_PROBE_CACHE_KEY
        assert args[1] == _STORAGE_PROBE_CACHE_TTL_S
        # JSON payload is parseable and round-trips.
        import json as _json

        cached_payload = _json.loads(args[2])
        assert cached_payload["storage_base_path"] == out["storage_base_path"]

    async def test_cache_hit_short_circuits_db(self, tmp_path: Path) -> None:
        # Pin: when Redis has a cached payload, the route returns it
        # immediately with ``cached: true`` and never touches the DB.
        import json as _json

        cached_payload = {
            "storage_base_path": str(tmp_path),
            "samples": [],
            "hints": ["cached hint"],
        }
        redis = MagicMock()
        redis.get = AsyncMock(return_value=_json.dumps(cached_payload))
        redis.setex = AsyncMock()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=AssertionError("DB hit on cache hit"))

        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=redis)

        assert out["cached"] is True
        assert out["hints"] == ["cached hint"]
        redis.setex.assert_not_called()
        db.execute.assert_not_called()

    async def test_force_bypasses_cache(self, tmp_path: Path) -> None:
        # Pin: ``?force=true`` skips the cache read entirely and always
        # recomputes — even when a cached payload exists. The new
        # report still gets written back to Redis.
        import json as _json

        redis = MagicMock()
        redis.get = AsyncMock(return_value=_json.dumps({"stale": True}))
        redis.setex = AsyncMock()

        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=redis, force=True)

        assert out["cached"] is False
        # get was not consulted.
        redis.get.assert_not_called()
        # Fresh value persisted.
        redis.setex.assert_awaited_once()

    async def test_malformed_cache_falls_through_to_recompute(self, tmp_path: Path) -> None:
        # Pin: a corrupt JSON blob in Redis must not crash the route —
        # the route falls through to a live recompute.
        redis = MagicMock()
        redis.get = AsyncMock(return_value="not-valid-json{{{")
        redis.setex = AsyncMock()

        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=redis)

        assert out["cached"] is False
        assert "storage_base_path" in out

    async def test_redis_get_failure_tolerated(self, tmp_path: Path) -> None:
        # Pin: a Redis hiccup on the read path must not 500 — the route
        # falls through to a live compute.
        redis = MagicMock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        redis.setex = AsyncMock()

        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=redis)

        assert out["cached"] is False

    async def test_redis_setex_failure_tolerated(self, tmp_path: Path) -> None:
        # Pin: a Redis hiccup on the write path is logged at DEBUG and
        # the route still returns the freshly computed report rather
        # than 500ing.
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock(side_effect=ConnectionError("redis down"))

        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await storage_probe(db=db, settings=_settings(tmp_path), redis=redis)

        assert out["cached"] is False
        assert "storage_base_path" in out
