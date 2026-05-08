"""Safety-branch tests for ``workers/jobs/social.py``.

Pin the cron-lock guard + per-upload validation gates that decide
which SocialUpload rows actually reach the platform-specific
uploader. The HTTP transport for each platform (TikTok / Instagram /
Facebook / X) is integration-tested separately.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from drevalis.workers.jobs.social import (
    _compose_caption,
    _compose_caption_multiline,
    _publish_pending_social_uploads_locked,
    _relative_storage_url,
    publish_pending_social_uploads,
)


def _ctx_with_pending(uploads: list[Any], video_asset: Any | None = None) -> Any:
    session = AsyncMock()
    session.commit = AsyncMock()

    # Two execute calls per upload: pending fetch + video lookup.
    # The first call returns the pending list; subsequent calls return
    # video assets per upload.
    pending_result = MagicMock()
    pending_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=uploads)))

    def _video_result_for(_upload: Any) -> Any:
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=video_asset)
        return r

    results: list[Any] = [pending_result]
    for u in uploads:
        results.append(_video_result_for(u))

    session.execute = AsyncMock(side_effect=results)

    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    settings = MagicMock()
    settings.storage_base_path = Path("/tmp")
    import base64

    settings.encryption_key = base64.urlsafe_b64encode(b"\x00" * 32).decode()

    ctx: dict[str, Any] = {
        "session_factory": _sf,
        "settings": settings,
        "redis": AsyncMock(),
    }
    return ctx, session


def _platform(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "platform": "tiktok",
        "is_active": True,
        "access_token_encrypted": "enc",
        "refresh_token_encrypted": None,
        "account_id": "acc-1",
        "account_metadata": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _upload_row(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "platform_id": uuid4(),
        "episode_id": uuid4(),
        "title": "T",
        "description": "",
        "hashtags": "",
        "upload_status": "pending",
        "error_message": None,
        "platform_content_id": None,
        "platform_url": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── publish_pending_social_uploads (cron entrypoint) ───────────────


class TestPublishPendingCronGuard:
    async def test_lock_not_owned_returns_zero_counts(self) -> None:
        # Pin: when another worker holds the cron lock, this worker
        # returns 0 across all counters and does NOT touch the DB.
        @asynccontextmanager
        async def _lock(*_args: Any, **_kwargs: Any) -> Any:
            yield False  # didn't acquire

        with patch("drevalis.workers.cron_lock.cron_lock", _lock):
            out = await publish_pending_social_uploads({})
        assert out == {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped_other_platforms": 0,
        }

    async def test_lock_owned_proceeds_to_locked_function(self) -> None:
        @asynccontextmanager
        async def _lock(*_args: Any, **_kwargs: Any) -> Any:
            yield True  # owned

        with (
            patch("drevalis.workers.cron_lock.cron_lock", _lock),
            patch(
                "drevalis.workers.jobs.social._publish_pending_social_uploads_locked",
                AsyncMock(
                    return_value={
                        "processed": 5,
                        "succeeded": 3,
                        "failed": 1,
                        "skipped_other_platforms": 1,
                    }
                ),
            ) as locked,
        ):
            out = await publish_pending_social_uploads({})
        locked.assert_awaited_once()
        assert out["processed"] == 5


# ── _publish_pending_social_uploads_locked ─────────────────────────


class TestLockedBody:
    async def test_no_pending_returns_all_zeros(self) -> None:
        ctx, _ = _ctx_with_pending([])
        out = await _publish_pending_social_uploads_locked(ctx)
        assert out == {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped_other_platforms": 0,
        }

    async def test_inactive_platform_marks_failed(self) -> None:
        u = _upload_row()
        ctx, session = _ctx_with_pending([u])
        # Platform exists but is_active=False.
        plat = _platform(is_active=False)
        session.get = AsyncMock(return_value=plat)
        out = await _publish_pending_social_uploads_locked(ctx)
        assert out["failed"] == 1
        assert u.upload_status == "failed"
        assert "missing or inactive" in u.error_message

    async def test_unknown_platform_skipped(self) -> None:
        # Pin: platforms outside the known set (tiktok / instagram /
        # facebook / x) are counted as `skipped_other_platforms` and
        # left in pending — operator can connect a real account later.
        u = _upload_row()
        ctx, session = _ctx_with_pending([u])
        plat = _platform(platform="snapchat")
        session.get = AsyncMock(return_value=plat)
        out = await _publish_pending_social_uploads_locked(ctx)
        assert out["skipped_other_platforms"] == 1
        # Status NOT changed — left as pending so a future deploy
        # adding snapchat support picks it up cleanly.
        assert u.upload_status == "pending"

    async def test_no_video_asset_marks_failed(self, tmp_path: Path) -> None:
        u = _upload_row()
        ctx, session = _ctx_with_pending([u], video_asset=None)
        plat = _platform()
        session.get = AsyncMock(return_value=plat)
        out = await _publish_pending_social_uploads_locked(ctx)
        assert out["failed"] == 1
        assert u.upload_status == "failed"
        assert "No final video" in u.error_message

    async def test_video_file_missing_on_disk_marks_failed(self, tmp_path: Path) -> None:
        # Asset row points at a path that doesn't exist.
        u = _upload_row()
        video = SimpleNamespace(file_path="missing/x.mp4")
        ctx, session = _ctx_with_pending([u], video_asset=video)
        ctx["settings"].storage_base_path = tmp_path
        plat = _platform()
        session.get = AsyncMock(return_value=plat)
        out = await _publish_pending_social_uploads_locked(ctx)
        assert out["failed"] == 1
        assert "Video file missing" in u.error_message

    async def test_uploader_failure_marks_failed_with_capped_message(self, tmp_path: Path) -> None:
        # Pin: any exception raised inside the platform-specific
        # uploader is caught, the row is marked failed, and the
        # error_message is capped at 500 chars.
        u = _upload_row()
        video_path = tmp_path / "v.mp4"
        video_path.write_bytes(b"\x00")
        video = SimpleNamespace(file_path="v.mp4")
        ctx, session = _ctx_with_pending([u], video_asset=video)
        ctx["settings"].storage_base_path = tmp_path
        plat = _platform(platform="tiktok")
        session.get = AsyncMock(return_value=plat)

        long_msg = "X" * 800
        ctx["settings"].decrypt = MagicMock(return_value="decrypted-token")
        with patch(
            "drevalis.workers.jobs.social._tiktok_upload",
            AsyncMock(side_effect=RuntimeError(long_msg)),
        ):
            out = await _publish_pending_social_uploads_locked(ctx)
        assert out["failed"] == 1
        assert u.upload_status == "failed"
        assert len(u.error_message) == 500


# ── _compose_caption (TikTok 150-char) ─────────────────────────────


class TestComposeCaption:
    def test_truncates_to_150_chars(self) -> None:
        out = _compose_caption("X" * 100, "Y" * 200, "#a #b")
        assert len(out) == 150

    def test_strips_each_part(self) -> None:
        out = _compose_caption("  Title  ", "  desc  ", "  #tag  ")
        # No leading/trailing whitespace inside the joined string.
        assert "  Title" not in out
        assert "Title desc" in out or "Title #tag" in out

    def test_omits_empty_parts(self) -> None:
        out = _compose_caption("Title", "", "")
        assert out == "Title"


# ── _compose_caption_multiline (Instagram / X) ─────────────────────


class TestComposeCaptionMultiline:
    def test_blank_lines_between_parts(self) -> None:
        out = _compose_caption_multiline("Title", "Description", "#a #b", limit=500)
        assert out == "Title\n\nDescription\n\n#a #b"

    def test_truncates_to_limit(self) -> None:
        out = _compose_caption_multiline("X" * 100, "Y" * 100, "Z" * 100, limit=50)
        assert len(out) == 50

    def test_omits_blanks(self) -> None:
        out = _compose_caption_multiline("Title", "", "#tag", limit=500)
        # Two parts means one separator: "Title\n\n#tag".
        assert out == "Title\n\n#tag"


# ── _relative_storage_url ──────────────────────────────────────────


class TestRelativeStorageUrl:
    def test_strips_path_up_to_storage(self) -> None:
        out = _relative_storage_url(Path("/app/storage/episodes/abc/output/video.mp4"))
        assert out == "episodes/abc/output/video.mp4"

    def test_no_storage_segment_falls_back_to_last_three(self) -> None:
        # Pin: when the path doesn't contain a `storage` segment,
        # the helper falls back to the last 3 path components — better
        # than crashing.
        out = _relative_storage_url(Path("/var/lib/drevalis/episodes/abc/video.mp4"))
        # 3 components: abc/video.mp4 (the helper joins from idx+1).
        assert "video.mp4" in out
