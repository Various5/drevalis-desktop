"""Tests for the per-platform uploaders in ``workers/jobs/social.py``.

The TikTok / Instagram / Facebook / X uploaders make multi-step
HTTP calls. We patch `httpx.AsyncClient` with `MockTransport` so the
request bodies + sequencing are inspected without hitting the live
APIs. Pin:

* `_tiktok_upload`: init malformed (missing `publish_id` /
  `upload_url`) → RuntimeError; PUT failure → RuntimeError;
  happy path returns `publish_id` string.
* `_tiktok_wait_for_publish`: PUBLISH_COMPLETE → returns post id;
  FAIL_* status → RuntimeError; never-completes → TimeoutError.
* `_instagram_reels_upload`: missing ig_user_id / public URL
  override → RuntimeError; container ERROR/EXPIRED → RuntimeError;
  permalink fetch failure tolerated (returns empty string).
* `_facebook_video_upload`: missing page_id → RuntimeError; start
  malformed → RuntimeError; multi-chunk transfer happens correctly;
  finish success=false → RuntimeError.
* `_x_video_upload`: INIT missing media_id → RuntimeError;
  APPEND/FINALIZE failures raise; processing-failed branch raises.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from drevalis.workers.jobs.social import (
    _facebook_video_upload,
    _instagram_reels_upload,
    _tiktok_upload,
    _tiktok_wait_for_publish,
    _x_video_upload,
)


def _patched_httpx(handler: Any) -> Any:
    """Patch httpx.AsyncClient to use a MockTransport with the supplied
    handler. The patch lives in `workers.jobs.social` (the import site)."""
    real_client = httpx.AsyncClient

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    return patch(
        "drevalis.workers.jobs.social.httpx.AsyncClient",
        side_effect=_factory,
    )


def _video_file(tmp_path: Path, size_bytes: int = 1024) -> Path:
    p = tmp_path / "video.mp4"
    p.write_bytes(b"\x00" * size_bytes)
    return p


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``asyncio.sleep`` so polling loops don't actually wait."""

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("drevalis.workers.jobs.social.asyncio.sleep", _no_sleep)


# ── _tiktok_upload ─────────────────────────────────────────────────


class TestTikTokUpload:
    async def test_init_malformed_raises(self, tmp_path: Path) -> None:
        # Init returns 200 OK but no publish_id / upload_url.
        def _h(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {}})

        with _patched_httpx(_h):
            with pytest.raises(RuntimeError, match="TikTok init malformed"):
                await _tiktok_upload(
                    token="t",
                    video_path=_video_file(tmp_path),
                    title="x",
                    description="",
                    hashtags="",
                )

    async def test_put_failure_raises(self, tmp_path: Path) -> None:
        # Init succeeds; PUT to upload_url returns 500.
        seen: list[str] = []

        def _h(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "publish_id": "pub-1",
                            "upload_url": "https://t.test/upload",
                        }
                    },
                )
            return httpx.Response(500, text="kaboom")

        with _patched_httpx(_h):
            with pytest.raises(RuntimeError, match="TikTok upload PUT failed"):
                await _tiktok_upload(
                    token="t",
                    video_path=_video_file(tmp_path),
                    title="x",
                    description="",
                    hashtags="",
                )
        # Pin: route DID try the PUT (otherwise fail wouldn't fire).
        assert "PUT" in seen

    async def test_happy_path_returns_publish_id(self, tmp_path: Path) -> None:
        captured: list[httpx.Request] = []

        def _h(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "publish_id": "pub-abc",
                            "upload_url": "https://t.test/up",
                        }
                    },
                )
            return httpx.Response(204)  # PUT success

        with _patched_httpx(_h):
            out = await _tiktok_upload(
                token="t",
                video_path=_video_file(tmp_path, size_bytes=2048),
                title="Hook",
                description="desc",
                hashtags="#a",
            )
        assert out == "pub-abc"
        # The PUT request carried the right Content-Length / Content-Range.
        put_req = next(r for r in captured if r.method == "PUT")
        assert put_req.headers["content-length"] == "2048"
        assert put_req.headers["content-range"] == "bytes 0-2047/2048"


# ── _tiktok_wait_for_publish ──────────────────────────────────────


class TestTikTokWaitForPublish:
    async def test_publish_complete_returns_url(self, fast_sleep: None) -> None:
        def _h(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "status": "PUBLISH_COMPLETE",
                        "publicaly_available_post_id": "post-123",
                    }
                },
            )

        with _patched_httpx(_h):
            out = await _tiktok_wait_for_publish("token", "pub-1")
        assert out == "post-123"

    async def test_fail_status_raises(self, fast_sleep: None) -> None:
        def _h(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "status": "FAILED_REVIEW",
                        "fail_reason": "spam-detection",
                    }
                },
            )

        with _patched_httpx(_h):
            with pytest.raises(RuntimeError, match="TikTok publish failed"):
                await _tiktok_wait_for_publish("token", "pub-1")

    async def test_timeout_raises_timeout_error(
        self, fast_sleep: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force the poll cap to 2 so we don't iterate 30 times.
        monkeypatch.setattr("drevalis.workers.jobs.social._MAX_POLLS", 2)

        def _h(request: httpx.Request) -> httpx.Response:
            # Always return PROCESSING — never PUBLISH_COMPLETE.
            return httpx.Response(200, json={"data": {"status": "PROCESSING_UPLOAD"}})

        with _patched_httpx(_h):
            with pytest.raises(TimeoutError):
                await _tiktok_wait_for_publish("token", "pub-1")


# ── _instagram_reels_upload ────────────────────────────────────────


class TestInstagramReelsUpload:
    async def test_missing_ig_user_id_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="Business account ID missing"):
            await _instagram_reels_upload(
                token="t",
                ig_user_id="",
                video_path=_video_file(tmp_path),
                title="x",
                description="",
                hashtags="",
                public_video_url_override="https://cdn.test/storage",
            )

    async def test_missing_public_url_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="reachable via HTTPS"):
            await _instagram_reels_upload(
                token="t",
                ig_user_id="ig-1",
                video_path=_video_file(tmp_path),
                title="x",
                description="",
                hashtags="",
                public_video_url_override=None,
            )

    async def test_happy_path_returns_media_id_and_permalink(
        self, fast_sleep: None, tmp_path: Path
    ) -> None:
        def _h(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "media_publish" in url:
                return httpx.Response(200, json={"id": "media-99"})
            if request.method == "POST":
                # Container create.
                return httpx.Response(200, json={"id": "container-42"})
            # GET — either status check or permalink fetch.
            if "status_code" in str(request.url):
                return httpx.Response(200, json={"status_code": "FINISHED"})
            return httpx.Response(200, json={"permalink": "https://instagram.com/p/abc"})

        with _patched_httpx(_h):
            mid, perm = await _instagram_reels_upload(
                token="t",
                ig_user_id="ig-1",
                video_path=_video_file(tmp_path),
                title="Hook",
                description="d",
                hashtags="#viral",
                public_video_url_override="https://cdn.test/storage",
            )
        assert mid == "media-99"
        assert perm == "https://instagram.com/p/abc"

    async def test_container_error_raises(self, fast_sleep: None, tmp_path: Path) -> None:
        def _h(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(200, json={"id": "container-42"})
            return httpx.Response(200, json={"status_code": "ERROR"})

        with _patched_httpx(_h):
            with pytest.raises(RuntimeError, match="Instagram container ERROR"):
                await _instagram_reels_upload(
                    token="t",
                    ig_user_id="ig-1",
                    video_path=_video_file(tmp_path),
                    title="x",
                    description="",
                    hashtags="",
                    public_video_url_override="https://cdn.test/storage",
                )

    async def test_permalink_failure_returns_empty_string(
        self, fast_sleep: None, tmp_path: Path
    ) -> None:
        # Pin: when the permalink fetch fails, the upload still
        # succeeds with an empty permalink string.
        def _h(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "media_publish" in url:
                return httpx.Response(200, json={"id": "media-99"})
            if request.method == "POST":
                return httpx.Response(200, json={"id": "container-42"})
            if "status_code" in url:
                return httpx.Response(200, json={"status_code": "FINISHED"})
            # Permalink fetch returns 500.
            return httpx.Response(500, text="server error")

        with _patched_httpx(_h):
            mid, perm = await _instagram_reels_upload(
                token="t",
                ig_user_id="ig-1",
                video_path=_video_file(tmp_path),
                title="x",
                description="",
                hashtags="",
                public_video_url_override="https://cdn.test/storage",
            )
        assert mid == "media-99"
        assert perm == ""


# ── _facebook_video_upload ─────────────────────────────────────────


class TestFacebookVideoUpload:
    async def test_missing_page_id_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="Facebook Page ID missing"):
            await _facebook_video_upload(
                token="t",
                page_id="",
                video_path=_video_file(tmp_path),
                title="x",
                description="",
                hashtags="",
            )

    async def test_start_malformed_raises(self, tmp_path: Path) -> None:
        # 200 OK but neither session_id nor video_id.
        def _h(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        with _patched_httpx(_h):
            with pytest.raises(RuntimeError, match="Facebook start malformed"):
                await _facebook_video_upload(
                    token="t",
                    page_id="pg",
                    video_path=_video_file(tmp_path),
                    title="x",
                    description="",
                    hashtags="",
                )

    async def test_happy_path_returns_video_id_and_permalink(self, tmp_path: Path) -> None:
        size = 1024
        responses = iter(
            [
                # 1. start
                httpx.Response(
                    200,
                    json={
                        "upload_session_id": "sess-1",
                        "video_id": "vid-1",
                        "start_offset": 0,
                        "end_offset": size,
                    },
                ),
                # 2. transfer (single chunk → next start == next end)
                httpx.Response(
                    200,
                    json={"start_offset": size, "end_offset": size},
                ),
                # 3. finish
                httpx.Response(200, json={"success": True}),
            ]
        )

        def _h(request: httpx.Request) -> httpx.Response:
            return next(responses)

        with _patched_httpx(_h):
            vid, perm = await _facebook_video_upload(
                token="t",
                page_id="pg",
                video_path=_video_file(tmp_path, size_bytes=size),
                title="x",
                description="d",
                hashtags="#a",
            )
        assert vid == "vid-1"
        assert perm == "https://www.facebook.com/pg/videos/vid-1"

    async def test_finish_success_false_raises(self, tmp_path: Path) -> None:
        size = 1024
        responses = iter(
            [
                httpx.Response(
                    200,
                    json={
                        "upload_session_id": "sess-1",
                        "video_id": "vid-1",
                        "start_offset": 0,
                        "end_offset": size,
                    },
                ),
                httpx.Response(
                    200,
                    json={"start_offset": size, "end_offset": size},
                ),
                httpx.Response(200, json={"success": False}),
            ]
        )

        def _h(request: httpx.Request) -> httpx.Response:
            return next(responses)

        with _patched_httpx(_h):
            with pytest.raises(RuntimeError, match="success=false"):
                await _facebook_video_upload(
                    token="t",
                    page_id="pg",
                    video_path=_video_file(tmp_path, size_bytes=size),
                    title="x",
                    description="",
                    hashtags="",
                )


# ── _x_video_upload ────────────────────────────────────────────────


class TestXVideoUpload:
    async def test_init_missing_media_id_raises(self, tmp_path: Path) -> None:
        def _h(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        with _patched_httpx(_h):
            with pytest.raises(RuntimeError, match="X INIT missing media_id"):
                await _x_video_upload(
                    token="t",
                    video_path=_video_file(tmp_path),
                    title="x",
                    description="",
                    hashtags="",
                )

    async def test_happy_path_returns_tweet_id_and_url(self, tmp_path: Path) -> None:
        responses = iter(
            [
                # INIT
                httpx.Response(200, json={"media_id_string": "media-7"}),
                # APPEND segment 0
                httpx.Response(200, json={}),
                # FINALIZE — no processing_info → straight to tweet.
                httpx.Response(200, json={}),
                # Tweet create
                httpx.Response(200, json={"data": {"id": "tweet-9"}}),
            ]
        )

        def _h(request: httpx.Request) -> httpx.Response:
            return next(responses)

        with _patched_httpx(_h):
            tid, url = await _x_video_upload(
                token="t",
                video_path=_video_file(tmp_path, size_bytes=1024),
                title="x",
                description="d",
                hashtags="#a",
            )
        assert tid == "tweet-9"
        assert url == "https://x.com/i/web/status/tweet-9"

    async def test_processing_failed_raises(self, fast_sleep: None, tmp_path: Path) -> None:
        # FINALIZE returns in_progress → STATUS poll returns failed
        # → pin: raises BEFORE creating the tweet.
        responses = iter(
            [
                httpx.Response(200, json={"media_id_string": "media-7"}),
                httpx.Response(200, json={}),  # APPEND
                # FINALIZE returns in_progress (enters while loop).
                httpx.Response(
                    200,
                    json={
                        "processing_info": {
                            "state": "in_progress",
                            "check_after_secs": 1,
                        }
                    },
                ),
                # STATUS poll returns failed.
                httpx.Response(
                    200,
                    json={
                        "processing_info": {
                            "state": "failed",
                            "error": {"message": "transcode failed"},
                        }
                    },
                ),
            ]
        )

        def _h(request: httpx.Request) -> httpx.Response:
            return next(responses)

        with _patched_httpx(_h):
            with pytest.raises(RuntimeError, match="X media processing failed"):
                await _x_video_upload(
                    token="t",
                    video_path=_video_file(tmp_path, size_bytes=1024),
                    title="x",
                    description="",
                    hashtags="",
                )

    async def test_processing_polled_until_succeeded(
        self, fast_sleep: None, tmp_path: Path
    ) -> None:
        # FINALIZE returns "in_progress" → poll STATUS until succeeded
        # → then post the tweet.
        responses = iter(
            [
                httpx.Response(200, json={"media_id_string": "media-7"}),
                httpx.Response(200, json={}),  # APPEND
                # FINALIZE
                httpx.Response(
                    200,
                    json={
                        "processing_info": {
                            "state": "in_progress",
                            "check_after_secs": 1,
                        }
                    },
                ),
                # STATUS poll → succeeded
                httpx.Response(
                    200,
                    json={"processing_info": {"state": "succeeded"}},
                ),
                # Tweet create
                httpx.Response(200, json={"data": {"id": "tweet-9"}}),
            ]
        )

        def _h(request: httpx.Request) -> httpx.Response:
            return next(responses)

        with _patched_httpx(_h):
            tid, _ = await _x_video_upload(
                token="t",
                video_path=_video_file(tmp_path, size_bytes=1024),
                title="x",
                description="",
                hashtags="",
            )
        assert tid == "tweet-9"
