"""Browser-facing WebSocket gateway — production-hardened.

Improvements over Phase 18:
  - 15 s heartbeat (spec: ping every 15 s)
  - asyncio.Queue backpressure (max 256 messages per client)
  - Redis event replay: last 50 events from each channel replayed on connect
    (uses Redis XREVRANGE on stream channels when available; falls back gracefully)
  - Per-connection message counter tracked in WEBSOCKET_CONNECTIONS gauge

Redis Pub/Sub channels forwarded:
  ssa:signal.created, ssa:signal.updated,
  ssa:order.created,  ssa:order.updated,
  ssa:position.updated,
  ssa:risk.breach,
  ssa:broker.status,
  ssa:kill_switch.activated, ssa:kill_switch.deactivated
"""


import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis

from container import ApplicationContainer
from core.infrastructure.auth.jwt_service import JWTService, TokenError
from core.infrastructure.observability.trading_metrics import (
    WEBSOCKET_CONNECTIONS,
    WEBSOCKET_MESSAGES_SENT_TOTAL,
)

_log = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])

_CHANNELS = [
    "ssa:signal.created",
    "ssa:signal.updated",
    "ssa:order.created",
    "ssa:order.updated",
    "ssa:position.updated",
    "ssa:risk.breach",
    "ssa:broker.status",
    "ssa:kill_switch.activated",
    "ssa:kill_switch.deactivated",
]

_CHANNEL_TO_EVENT: dict[str, str] = {ch: ch.split(":", 1)[1] for ch in _CHANNELS}

_HEARTBEAT_INTERVAL: float = 15.0
_QUEUE_MAX_SIZE: int = 256
_REPLAY_LAST_N: int = 50


async def _authenticate(token: str, jwt_service: JWTService) -> bool:
    try:
        claims = jwt_service.decode_token(token)
    except TokenError:
        return False
    jti = claims.get("jti", "")
    if jti and await jwt_service.is_revoked(jti):
        return False
    return True


async def _replay_recent_events(
    redis_client: Redis,
    queue: asyncio.Queue,
) -> None:
    """Push the last N events from each stream channel into the queue.

    Redis stream keys mirror the Pub/Sub channel names (ssa:signal.created etc.).
    If a stream doesn't exist the XREVRANGE call is silently skipped.
    """
    for channel in _CHANNELS:
        event_type = _CHANNEL_TO_EVENT[channel]
        try:
            raw_messages = await redis_client.xrevrange(channel, count=_REPLAY_LAST_N)
            for _msg_id, fields in reversed(raw_messages):
                data_raw = fields.get("data", fields.get(b"data", "{}"))
                try:
                    payload = json.loads(data_raw)
                except (json.JSONDecodeError, TypeError):
                    payload = {"raw": str(data_raw)}
                envelope = {"type": event_type, "data": payload, "replayed": True}
                try:
                    queue.put_nowait(envelope)
                except asyncio.QueueFull:
                    break
        except Exception:  # noqa: BLE001
            # Stream may not exist; skip silently.
            pass


@router.websocket("/ws")
async def websocket_gateway(
    websocket: WebSocket,
    token: str = Query(default=""),
) -> None:
    container: ApplicationContainer = websocket.app.state.container
    jwt_service: JWTService = container.jwt_service()
    redis_client: Redis = container.redis_client()

    if not token or not await _authenticate(token, jwt_service):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    WEBSOCKET_CONNECTIONS.inc()
    _log.info("ws.client_connected remote=%s", websocket.client)

    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(*_CHANNELS)

    try:
        # Replay recent events so client doesn't miss updates during reconnect gap.
        await _replay_recent_events(redis_client, queue)

        async def _recv_pubsub() -> None:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                channel: str = message["channel"]
                event_type = _CHANNEL_TO_EVENT.get(channel, channel)
                raw = message["data"]
                try:
                    payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                except (json.JSONDecodeError, TypeError):
                    payload = {"raw": str(raw)}
                envelope = {"type": event_type, "data": payload}
                try:
                    queue.put_nowait(envelope)
                except asyncio.QueueFull:
                    # Drop oldest message to make room (head-drop).
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    queue.put_nowait(envelope)

        async def _send_loop() -> None:
            while True:
                envelope = await queue.get()
                await websocket.send_json(envelope)
                event_type = envelope.get("type", "unknown")
                WEBSOCKET_MESSAGES_SENT_TOTAL.labels(event_type=event_type).inc()

        async def _heartbeat() -> None:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                ping = {"type": "ping"}
                try:
                    queue.put_nowait(ping)
                except asyncio.QueueFull:
                    pass

        recv_task = asyncio.create_task(_recv_pubsub())
        send_task = asyncio.create_task(_send_loop())
        heartbeat_task = asyncio.create_task(_heartbeat())

        done, pending = await asyncio.wait(
            [recv_task, send_task, heartbeat_task],
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        _log.info("ws.client_disconnected remote=%s", websocket.client)
    except Exception:
        _log.exception("ws.error remote=%s", websocket.client)
    finally:
        WEBSOCKET_CONNECTIONS.dec()
        await pubsub.unsubscribe(*_CHANNELS)
        await pubsub.close()
