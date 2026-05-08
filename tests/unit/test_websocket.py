"""Tests for ``api/websocket.py``.

Real-time progress streaming. Pin:

* `_validate_ws_token`: auth disabled (empty / whitespace-only env)
  → True; configured token + matching query param → True; mismatch
  → False; **CRLF-mangled blank token** (Windows installer footgun)
  is treated as auth-disabled, NOT auth-on (the v0.20.13 fix).
* `ConnectionManager`: per-episode lists, broadcast to all peers,
  prune stale connections that raise on send, drop empty lists.
* `websocket_progress` rejects bad-UUID episode_ids with 1008 + a
  human reason string; rejects unauthenticated handshakes with 4001.
* Terminal-message detection in the listener (``pipeline_complete``
  and ``done @ 100``) breaks the loop so the listener cleanly exits.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from drevalis.api.websocket import (
    ConnectionManager,
    _listen_redis_pubsub,
    _validate_ws_token,
    websocket_all_progress,
    websocket_audiobook_progress,
    websocket_progress,
)


def _ws(token: str | None = None) -> Any:
    """Build a minimal WebSocket double."""
    ws = MagicMock(spec=WebSocket)
    ws.query_params = {"token": token} if token is not None else {}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


# ── _validate_ws_token ─────────────────────────────────────────────


class TestValidateWsToken:
    async def test_auth_disabled_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
        assert await _validate_ws_token(_ws()) is True

    async def test_auth_disabled_when_env_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_AUTH_TOKEN", "")
        assert await _validate_ws_token(_ws()) is True

    async def test_crlf_mangled_blank_token_treated_as_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pin the v0.20.13 fix: Windows installer's CRLF-mangled blank
        # slot (`API_AUTH_TOKEN=\r`) MUST NOT force auth on. Without
        # `.strip()` every browser WebSocket would close with 4001.
        monkeypatch.setenv("API_AUTH_TOKEN", "\r")
        assert await _validate_ws_token(_ws()) is True

    async def test_whitespace_only_treated_as_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("API_AUTH_TOKEN", "   \n\t")
        assert await _validate_ws_token(_ws()) is True

    async def test_matching_query_token_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_AUTH_TOKEN", "secret-tok")
        assert await _validate_ws_token(_ws(token="secret-tok")) is True

    async def test_mismatched_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_AUTH_TOKEN", "secret-tok")
        assert await _validate_ws_token(_ws(token="wrong")) is False

    async def test_query_token_stripped_before_compare(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Frontend appends a trailing newline by accident — pin: route
        # strips so a legitimate caller still passes auth.
        monkeypatch.setenv("API_AUTH_TOKEN", "tok")
        assert await _validate_ws_token(_ws(token="tok\n")) is True

    async def test_missing_query_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_AUTH_TOKEN", "tok")
        assert await _validate_ws_token(_ws(token=None)) is False


# ── ConnectionManager ──────────────────────────────────────────────


class TestConnectionManager:
    async def test_connect_registers_websocket(self) -> None:
        mgr = ConnectionManager()
        ws = _ws()
        await mgr.connect("ep1", ws)
        ws.accept.assert_awaited_once()
        assert "ep1" in mgr.get_episode_ids()
        assert mgr.active_connections == 1

    async def test_disconnect_removes_websocket(self) -> None:
        mgr = ConnectionManager()
        ws = _ws()
        await mgr.connect("ep1", ws)
        mgr.disconnect("ep1", ws)
        # Empty episode bucket is cleaned up.
        assert "ep1" not in mgr.get_episode_ids()
        assert mgr.active_connections == 0

    def test_disconnect_unknown_episode_noop(self) -> None:
        mgr = ConnectionManager()
        ws = _ws()
        # Must not raise.
        mgr.disconnect("never-registered", ws)

    def test_disconnect_unknown_websocket_noop(self) -> None:
        mgr = ConnectionManager()
        ws_a, ws_b = _ws(), _ws()
        # Manually populate the registry without the helper to test
        # the ws-not-in-list branch.
        mgr._connections["ep1"] = [ws_a]
        # Removing ws_b (never registered) is a no-op.
        mgr.disconnect("ep1", ws_b)
        assert ws_a in mgr._connections["ep1"]

    async def test_broadcast_to_no_connections_noop(self) -> None:
        mgr = ConnectionManager()
        # No-op: must not raise.
        await mgr.broadcast("nobody", "{}")

    async def test_broadcast_sends_to_all_subscribers(self) -> None:
        mgr = ConnectionManager()
        a, b = _ws(), _ws()
        await mgr.connect("ep1", a)
        await mgr.connect("ep1", b)
        await mgr.broadcast("ep1", "hello")
        a.send_text.assert_awaited_once_with("hello")
        b.send_text.assert_awaited_once_with("hello")

    async def test_broadcast_prunes_stale_connections(self) -> None:
        # Pin: a peer that raises on send_text gets removed from the
        # list so the next broadcast doesn't waste cycles on a dead
        # socket.
        mgr = ConnectionManager()
        good = _ws()
        stale = _ws()
        stale.send_text = AsyncMock(side_effect=ConnectionResetError("dead"))
        await mgr.connect("ep1", good)
        await mgr.connect("ep1", stale)
        await mgr.broadcast("ep1", "x")
        # Stale removed; good still present.
        assert mgr.active_connections == 1
        # Second broadcast only hits the good peer.
        good.send_text.reset_mock()
        await mgr.broadcast("ep1", "y")
        good.send_text.assert_awaited_once_with("y")

    async def test_broadcast_drops_empty_episode_bucket(self) -> None:
        # All connections turned stale → episode bucket is removed
        # entirely so it doesn't leak.
        mgr = ConnectionManager()
        ws = _ws()
        ws.send_text = AsyncMock(side_effect=ConnectionResetError("dead"))
        await mgr.connect("ep1", ws)
        await mgr.broadcast("ep1", "x")
        assert "ep1" not in mgr.get_episode_ids()


# ── _listen_redis_pubsub ───────────────────────────────────────────


class TestListenRedisPubsub:
    async def test_terminal_pipeline_complete_breaks_loop(self) -> None:
        # Build a pubsub that emits one terminal message then would
        # block. The listener MUST break after seeing it.
        ws = _ws()
        msgs = [
            {"type": "message", "data": json.dumps({"message": "pipeline_complete"})},
        ]

        async def _get_message(*, ignore_subscribe_messages: bool, timeout: float) -> Any:
            return msgs.pop(0) if msgs else None

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.get_message = AsyncMock(side_effect=_get_message)

        client = MagicMock()
        client.pubsub = MagicMock(return_value=pubsub)
        client.aclose = AsyncMock()

        with (
            patch("drevalis.api.websocket.Redis", return_value=client),
            patch("drevalis.api.websocket.get_pool", return_value=MagicMock()),
        ):
            stop = asyncio.Event()
            await _listen_redis_pubsub("eid", ws, stop)

        ws.send_text.assert_awaited_once()
        pubsub.unsubscribe.assert_awaited_once()
        pubsub.aclose.assert_awaited_once()
        client.aclose.assert_awaited_once()

    async def test_terminal_audiobook_done_breaks_loop(self) -> None:
        ws = _ws()
        msgs = [
            {
                "type": "message",
                "data": json.dumps({"step": "done", "progress_pct": 100}),
            },
        ]

        async def _get_message(*, ignore_subscribe_messages: bool, timeout: float) -> Any:
            return msgs.pop(0) if msgs else None

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.get_message = AsyncMock(side_effect=_get_message)

        client = MagicMock()
        client.pubsub = MagicMock(return_value=pubsub)
        client.aclose = AsyncMock()

        with (
            patch("drevalis.api.websocket.Redis", return_value=client),
            patch("drevalis.api.websocket.get_pool", return_value=MagicMock()),
        ):
            await _listen_redis_pubsub("eid", ws, asyncio.Event())

        ws.send_text.assert_awaited_once()

    async def test_send_failure_breaks_loop_cleanly(self) -> None:
        # WS disconnect mid-stream: send_text raises → listener exits
        # without leaving the pubsub subscription open.
        ws = _ws()
        ws.send_text = AsyncMock(side_effect=ConnectionResetError("client gone"))
        msgs = [{"type": "message", "data": "hello"}]

        async def _get_message(*, ignore_subscribe_messages: bool, timeout: float) -> Any:
            return msgs.pop(0) if msgs else None

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.get_message = AsyncMock(side_effect=_get_message)

        client = MagicMock()
        client.pubsub = MagicMock(return_value=pubsub)
        client.aclose = AsyncMock()

        with (
            patch("drevalis.api.websocket.Redis", return_value=client),
            patch("drevalis.api.websocket.get_pool", return_value=MagicMock()),
        ):
            await _listen_redis_pubsub("eid", ws, asyncio.Event())

        # Cleanup ran despite the send failure.
        pubsub.unsubscribe.assert_awaited_once()

    async def test_bytes_data_decoded_to_utf8(self) -> None:
        ws = _ws()
        msgs = [
            {
                "type": "message",
                "data": json.dumps({"message": "pipeline_complete"}).encode(),
            }
        ]

        async def _get_message(*, ignore_subscribe_messages: bool, timeout: float) -> Any:
            return msgs.pop(0) if msgs else None

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.get_message = AsyncMock(side_effect=_get_message)

        client = MagicMock()
        client.pubsub = MagicMock(return_value=pubsub)
        client.aclose = AsyncMock()

        with (
            patch("drevalis.api.websocket.Redis", return_value=client),
            patch("drevalis.api.websocket.get_pool", return_value=MagicMock()),
        ):
            await _listen_redis_pubsub("eid", ws, asyncio.Event())

        # send_text called with the decoded JSON, not the raw bytes.
        sent = ws.send_text.call_args.args[0]
        assert isinstance(sent, str)
        assert "pipeline_complete" in sent

    async def test_non_terminal_json_continues(self) -> None:
        # Pin: a JSON message that's neither terminal AND a non-JSON
        # text message both keep the loop alive (until stop_event).
        ws = _ws()
        msgs = [
            {"type": "message", "data": json.dumps({"step": "voice", "progress_pct": 30})},
            {"type": "message", "data": "not json"},
        ]
        delivered = 0

        async def _get_message(*, ignore_subscribe_messages: bool, timeout: float) -> Any:
            nonlocal delivered
            if msgs:
                delivered += 1
                return msgs.pop(0)
            # Once messages drained, signal stop.
            stop.set()
            return None

        stop = asyncio.Event()
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.get_message = AsyncMock(side_effect=_get_message)

        client = MagicMock()
        client.pubsub = MagicMock(return_value=pubsub)
        client.aclose = AsyncMock()

        with (
            patch("drevalis.api.websocket.Redis", return_value=client),
            patch("drevalis.api.websocket.get_pool", return_value=MagicMock()),
        ):
            await _listen_redis_pubsub("eid", ws, stop)

        assert delivered == 2
        assert ws.send_text.await_count == 2

    async def test_subscribe_failure_still_runs_finally(self) -> None:
        # If pubsub.subscribe raises, the finally block must still
        # try to clean up (and tolerate the un-subscribed state).
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock(side_effect=ConnectionError("redis down"))
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()

        client = MagicMock()
        client.pubsub = MagicMock(return_value=pubsub)
        client.aclose = AsyncMock()

        with (
            patch("drevalis.api.websocket.Redis", return_value=client),
            patch("drevalis.api.websocket.get_pool", return_value=MagicMock()),
        ):
            # Should NOT raise.
            await _listen_redis_pubsub("eid", _ws(), asyncio.Event())

        client.aclose.assert_awaited_once()


# ── websocket_progress endpoint ────────────────────────────────────


class TestWebsocketProgress:
    async def test_unauthenticated_closed_with_4001(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_AUTH_TOKEN", "tok")
        ws = _ws(token="wrong")
        await websocket_progress(ws, "00000000-0000-0000-0000-000000000001")
        ws.close.assert_awaited_once()
        kwargs = ws.close.call_args.kwargs
        assert kwargs["code"] == 4001
        # No accept() — handshake refused before that.
        ws.accept.assert_not_called()

    async def test_invalid_uuid_closed_with_1008(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: malformed episode_id is rejected with 1008 (Policy
        # Violation), NOT 4001 — the auth was fine, the path was bad.
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
        ws = _ws()
        await websocket_progress(ws, "not-a-uuid")
        ws.close.assert_awaited_once()
        kwargs = ws.close.call_args.kwargs
        assert kwargs["code"] == 1008
        assert "UUID" in kwargs["reason"]

    async def test_disconnect_cancels_listener_and_unregisters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Happy path: client connects, sends one ping, disconnects.
        # Pin: listener task is cancelled in finally + manager
        # disconnect runs.
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)

        ws = _ws()
        # Receive: ping then disconnect.
        receive_calls = ["ping"]

        async def _recv() -> str:
            if receive_calls:
                return receive_calls.pop(0)
            raise WebSocketDisconnect()

        ws.receive_text = AsyncMock(side_effect=_recv)

        # Make _listen_redis_pubsub a no-op coroutine so we don't open
        # a real Redis connection in unit tests.
        async def _fake_listener(*_args: Any, **_kwargs: Any) -> None:
            await asyncio.sleep(60)  # block until cancelled

        with patch("drevalis.api.websocket._listen_redis_pubsub", _fake_listener):
            await websocket_progress(ws, "11111111-1111-1111-1111-111111111111")

        # Ping echoed as pong.
        ws.send_text.assert_awaited_once()
        sent = ws.send_text.call_args.args[0]
        assert json.loads(sent) == {"type": "pong"}


# ── websocket_audiobook_progress ───────────────────────────────────


class TestAudiobookProgress:
    async def test_unauthenticated_closed_with_4001(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_AUTH_TOKEN", "tok")
        ws = _ws(token="wrong")
        await websocket_audiobook_progress(ws, "11111111-1111-1111-1111-111111111111")
        ws.close.assert_awaited_once()
        assert ws.close.call_args.kwargs["code"] == 4001

    async def test_bad_uuid_closed_with_1008(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
        ws = _ws()
        await websocket_audiobook_progress(ws, "not-a-uuid")
        assert ws.close.call_args.kwargs["code"] == 1008

    async def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
        ws = _ws()
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        async def _fake_listener(*_args: Any, **_kwargs: Any) -> None:
            await asyncio.sleep(60)

        with patch("drevalis.api.websocket._listen_redis_pubsub", _fake_listener):
            await websocket_audiobook_progress(ws, "22222222-2222-2222-2222-222222222222")

        # Manager must register + cleanup; ws.accept was called inside
        # connect(). No raise.

    async def test_ping_round_trip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
        ws = _ws()
        recv = ["ping"]

        async def _r() -> str:
            if recv:
                return recv.pop(0)
            raise WebSocketDisconnect()

        ws.receive_text = AsyncMock(side_effect=_r)

        async def _fake_listener(*_args: Any, **_kwargs: Any) -> None:
            await asyncio.sleep(60)

        with patch("drevalis.api.websocket._listen_redis_pubsub", _fake_listener):
            await websocket_audiobook_progress(ws, "33333333-3333-3333-3333-333333333333")

        ws.send_text.assert_awaited_once()
        assert "pong" in ws.send_text.call_args.args[0]


# ── websocket_all_progress (pattern subscription) ──────────────────


class TestAllProgress:
    async def test_unauthenticated_closed_with_4001(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_AUTH_TOKEN", "tok")
        ws = _ws(token="wrong")
        await websocket_all_progress(ws)
        ws.close.assert_awaited_once()
        assert ws.close.call_args.kwargs["code"] == 4001

    async def test_pmessage_forwarded_to_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
        ws = _ws()

        forwarded_event = asyncio.Event()

        # Outer receive: block until the inner listener has delivered
        # the pmessage, then disconnect cleanly.
        async def _recv() -> str:
            await asyncio.wait_for(forwarded_event.wait(), timeout=2.0)
            raise WebSocketDisconnect()

        ws.receive_text = AsyncMock(side_effect=_recv)

        # Override send_text to also set the event so the outer loop
        # can exit after the first pmessage.
        original_send = ws.send_text

        async def _send(payload: str) -> None:
            await original_send(payload)
            forwarded_event.set()

        ws.send_text = AsyncMock(side_effect=_send)

        msgs = [
            {"type": "pmessage", "data": b'{"step":"voice"}'},
            {"type": "subscribe", "data": "ignored"},
        ]

        async def _get_message(*, ignore_subscribe_messages: bool, timeout: float) -> Any:
            if msgs:
                return msgs.pop(0)
            # Yield control so the outer loop's WebSocketDisconnect can fire.
            await asyncio.sleep(0)
            return None

        pubsub = MagicMock()
        pubsub.psubscribe = AsyncMock()
        pubsub.punsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.get_message = AsyncMock(side_effect=_get_message)

        client = MagicMock()
        client.pubsub = MagicMock(return_value=pubsub)
        client.aclose = AsyncMock()

        with (
            patch("drevalis.api.websocket.Redis", return_value=client),
            patch("drevalis.api.websocket.get_pool", return_value=MagicMock()),
        ):
            await websocket_all_progress(ws)

        assert ws.send_text.await_count >= 1
        forwarded = ws.send_text.call_args_list[0].args[0]
        assert "voice" in forwarded
