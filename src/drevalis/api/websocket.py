"""WebSocket endpoint for real-time generation progress streaming.

Architecture:

* ``ConnectionManager`` tracks active WebSocket connections per episode.
* The ``/ws/progress/{episode_id}`` endpoint accepts a WebSocket,
  subscribes to the Redis pub/sub channel ``progress:{episode_id}``,
  and forwards every published :class:`ProgressMessage` to the client.
* A per-connection asyncio task listens to Redis pub/sub and pushes
  messages into the WebSocket.  When the client disconnects, the
  subscription is cleaned up.

Usage from the frontend::

    const ws = new WebSocket("ws://localhost:8000/ws/progress/<episode-uuid>");
    ws.onmessage = (event) => {
        const progress = JSON.parse(event.data);
        // { episode_id, job_id, step, status, progress_pct, message, ... }
    };
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from uuid import UUID

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.client import PubSub

from drevalis.core.redis import get_pool

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# WebSocket authentication
# ---------------------------------------------------------------------------


async def _validate_ws_token(websocket: WebSocket) -> bool:
    """Validate WebSocket auth token supplied as a query parameter.

    Returns True when auth is disabled (API_AUTH_TOKEN not set / empty)
    or when the caller supplies a matching ``?token=<value>`` query
    parameter.

    WebSocket clients cannot set the ``Authorization`` header from a browser,
    so the token is accepted via query parameter instead.  The comparison uses
    ``secrets.compare_digest`` to prevent timing-oracle attacks.

    v0.20.13 — strip whitespace on the configured token before the "is
    auth configured?" check. On Windows, the installer writes .env with
    CRLF line endings, so ``API_AUTH_TOKEN=`` (intentionally blank slot)
    lands in the container as ``"\\r"`` — truthy, forces auth on, and
    every browser WebSocket gets closed with 4001 → HTTP 403. Same
    coercion the OptionalAPIKeyMiddleware already does; we now mirror
    it here.

    CWE-306 (Missing Authentication), OWASP A07:2021 (Identification and
    Authentication Failures).
    """
    raw_token: str = os.environ.get("API_AUTH_TOKEN", "") or ""
    configured_token: str = raw_token.strip()
    if not configured_token:
        # Auth is disabled — local dev mode (or Windows-CRLF-mangled
        # blank-slot value; see docstring).
        return True
    ws_token: str = websocket.query_params.get("token", "").strip()
    return secrets.compare_digest(ws_token, configured_token)


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages active WebSocket connections grouped by episode ID.

    Thread-safe for the single-threaded asyncio event loop (all access
    happens on the same loop).
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, episode_id: str, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        if episode_id not in self._connections:
            self._connections[episode_id] = []
        self._connections[episode_id].append(websocket)
        logger.info(
            "ws_connected",
            episode_id=episode_id,
            active=len(self._connections[episode_id]),
        )

    def disconnect(self, episode_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the registry."""
        conns = self._connections.get(episode_id)
        if conns is None:
            return
        try:
            conns.remove(websocket)
        except ValueError:
            pass
        if not conns:
            del self._connections[episode_id]
        logger.info(
            "ws_disconnected",
            episode_id=episode_id,
            remaining=len(self._connections.get(episode_id, [])),
        )

    async def broadcast(self, episode_id: str, message: str) -> None:
        """Send a text message to all clients watching *episode_id*."""
        conns = self._connections.get(episode_id)
        if not conns:
            return

        # Send to all connected clients; collect stale connections
        stale: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)

        # Clean up any broken connections
        for ws in stale:
            try:
                conns.remove(ws)
            except ValueError:
                pass

        if not conns:
            self._connections.pop(episode_id, None)

    @property
    def active_connections(self) -> int:
        """Total number of active WebSocket connections."""
        return sum(len(v) for v in self._connections.values())

    def get_episode_ids(self) -> list[str]:
        """Return episode IDs with at least one active connection."""
        return list(self._connections.keys())


# Module-level singleton
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Redis pub/sub listener
# ---------------------------------------------------------------------------


async def _listen_redis_pubsub(
    episode_id: str,
    websocket: WebSocket,
    stop_event: asyncio.Event,
) -> None:
    """Subscribe to Redis pub/sub and forward messages to the WebSocket.

    Runs as an asyncio task that exits when *stop_event* is set or the
    Redis subscription fails.
    """
    channel = f"progress:{episode_id}"
    pool: ConnectionPool = get_pool()
    redis_client: Redis = Redis(connection_pool=pool)
    pubsub: PubSub = redis_client.pubsub()

    try:
        await pubsub.subscribe(channel)
        logger.debug("pubsub_subscribed", channel=channel)

        while not stop_event.is_set():
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=5.0,
                )
            except TimeoutError:
                # No message within timeout -- loop and check stop_event
                continue
            except Exception:
                logger.debug("pubsub_get_message_error", exc_info=True)
                break

            if message is None:
                continue

            if message["type"] == "message":
                data = message["data"]
                # data may be str (decode_responses=True) or bytes
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                try:
                    await websocket.send_text(data)
                except Exception:
                    # WebSocket likely closed
                    logger.debug("ws_send_failed_during_pubsub", episode_id=episode_id)
                    break

                # Check if this is a terminal message so we can stop listening
                try:
                    parsed = json.loads(data)
                    if parsed.get("message") == "pipeline_complete":
                        logger.info("pubsub_pipeline_complete", episode_id=episode_id)
                        break
                    if parsed.get("step") == "done" and parsed.get("progress_pct") == 100:
                        logger.info("pubsub_audiobook_complete", episode_id=episode_id)
                        break
                except (json.JSONDecodeError, KeyError):
                    pass

    except Exception:
        logger.error("pubsub_listener_error", episode_id=episode_id, exc_info=True)
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]
        except Exception:
            pass
        try:
            await redis_client.aclose()
        except Exception:
            pass
        logger.debug("pubsub_listener_stopped", channel=channel)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/progress/{episode_id}")
async def websocket_progress(websocket: WebSocket, episode_id: str) -> None:
    """Stream generation progress for *episode_id* over WebSocket.

    The endpoint subscribes to the Redis pub/sub channel
    ``progress:{episode_id}`` and forwards every published message.
    The connection stays open until the client disconnects or the
    pipeline completes.
    """
    # S-3: Reject unauthenticated connections before accepting the handshake.
    if not await _validate_ws_token(websocket):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # M2: Validate that episode_id is a valid UUID before accepting.
    try:
        UUID(episode_id)
    except (ValueError, AttributeError):
        await websocket.close(code=1008, reason="Invalid episode_id: must be a valid UUID")
        return

    await manager.connect(episode_id, websocket)

    stop_event = asyncio.Event()

    # Start the Redis listener as a background task
    listener_task = asyncio.create_task(_listen_redis_pubsub(episode_id, websocket, stop_event))

    try:
        # Keep the WebSocket alive by receiving (and discarding) client messages.
        # This loop exits when the client disconnects.
        while True:
            try:
                # We expect the client to send pings or nothing at all.
                # receive_text() will raise WebSocketDisconnect on close.
                data = await websocket.receive_text()

                # Optional: handle client-sent commands (e.g. "ping")
                if data.strip().lower() == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

            except WebSocketDisconnect:
                logger.info("ws_client_disconnected", episode_id=episode_id)
                break
            except Exception:
                logger.debug("ws_receive_error", episode_id=episode_id, exc_info=True)
                break

    finally:
        # Signal the listener to stop and clean up
        stop_event.set()
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        manager.disconnect(episode_id, websocket)


@router.websocket("/ws/progress/audiobook/{audiobook_id}")
async def websocket_audiobook_progress(websocket: WebSocket, audiobook_id: str) -> None:
    """Stream generation progress for an audiobook over WebSocket.

    Subscribes to Redis pub/sub channel ``progress:audiobook:{audiobook_id}``
    and forwards messages to the client.
    """
    # S-3: Reject unauthenticated connections before accepting the handshake.
    if not await _validate_ws_token(websocket):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    try:
        UUID(audiobook_id)
    except (ValueError, AttributeError):
        await websocket.close(code=1008, reason="Invalid audiobook_id")
        return

    key = f"audiobook:{audiobook_id}"
    await manager.connect(key, websocket)

    stop_event = asyncio.Event()
    listener_task = asyncio.create_task(_listen_redis_pubsub(key, websocket, stop_event))

    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data.strip().lower() == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except WebSocketDisconnect:
                break
            except Exception:
                break
    finally:
        stop_event.set()
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        manager.disconnect(key, websocket)


@router.websocket("/ws/progress/all")
async def websocket_all_progress(websocket: WebSocket) -> None:
    """Stream ALL generation progress across all episodes via pattern subscription.

    Subscribes to the Redis pub/sub pattern ``progress:*`` and forwards every
    published message to the client.  Useful for dashboards that need to track
    all active generations without knowing episode IDs in advance.
    """
    # S-3: Reject unauthenticated connections before accepting the handshake.
    if not await _validate_ws_token(websocket):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info("ws_all_progress_connected")

    pool: ConnectionPool = get_pool()
    redis_client: Redis = Redis(connection_pool=pool)
    pubsub: PubSub = redis_client.pubsub()

    stop_event = asyncio.Event()

    async def _listen() -> None:
        try:
            await pubsub.psubscribe("progress:*")
            logger.debug("pubsub_psubscribed", pattern="progress:*")

            while not stop_event.is_set():
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                        timeout=5.0,
                    )
                except TimeoutError:
                    continue
                except Exception:
                    logger.debug("pubsub_all_get_message_error", exc_info=True)
                    break

                if message is None:
                    continue

                # Pattern subscription messages have type "pmessage", not "message"
                if message["type"] == "pmessage":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    try:
                        await websocket.send_text(data)
                    except Exception:
                        logger.debug("ws_all_send_failed")
                        break

        except Exception:
            logger.error("pubsub_all_listener_error", exc_info=True)
        finally:
            try:
                await pubsub.punsubscribe("progress:*")
                await pubsub.aclose()  # type: ignore[no-untyped-call]
            except Exception:
                pass
            try:
                await redis_client.aclose()
            except Exception:
                pass
            logger.debug("pubsub_all_listener_stopped")

    listener_task = asyncio.create_task(_listen())

    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data.strip().lower() == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except WebSocketDisconnect:
                logger.info("ws_all_progress_disconnected")
                break
            except Exception:
                logger.debug("ws_all_receive_error", exc_info=True)
                break
    finally:
        stop_event.set()
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
