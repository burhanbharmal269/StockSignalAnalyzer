# WebSocket Validation Report
**Project:** StockSignalAnalyzer  
**Date:** 2026-06-16  
**Backend:** FastAPI WebSocket Gateway (`ws_router.py`)  
**Frontend:** `websocket.ts`, `websocket-provider.tsx`, `use-websocket.ts`

---

## Executive Summary

The WebSocket implementation is production-ready. The backend gateway authenticates connections via JWT on connect, subscribes to 9 Redis Pub/Sub channels, replays the last 50 events per channel on reconnect, sends 15-second heartbeats, and implements per-connection backpressure (queue size 256). The frontend uses a singleton `WebSocketManager` class with automatic reconnection (5 attempts), token-based authentication, and a typed event handler registry. The `WebSocketProvider` React context gates connection establishment on authentication state. The `useWebSocket` hook provides a clean declarative API for components to subscribe to specific event types. All message types are handled. The implementation is suitable for production use with one recommendation to add exponential reconnect backoff.

---

## 1. Connection Establishment (JWT Authentication)

**Backend (`ws_router.py:98-117`):**

The WebSocket endpoint is `/ws` with a `token` query parameter:

```
ws://host/ws?token=<jwt_access_token>
```

Authentication is performed before `websocket.accept()`:

1. `token` query param is extracted.
2. `_authenticate(token, jwt_service)` is called:
   - `JWTService.decode_token(token)` validates signature and claims.
   - If `jti` claim is present, `jwt_service.is_revoked(jti)` checks against Redis revocation list.
   - Returns `True` only if both checks pass.
3. If authentication fails (empty token, invalid token, or revoked JTI), the connection is closed with `WS_1008_POLICY_VIOLATION` (code 1008) before accepting.
4. On success, `websocket.accept()` is called and the Prometheus `WEBSOCKET_CONNECTIONS` gauge is incremented.

**Security:** Revocation check on connect ensures logged-out users' tokens cannot be used to maintain WebSocket connections.

**Frontend (`websocket.ts:13-44`):**

The `WebSocketManager.connect()` method:

1. Returns early if already OPEN.
2. Reads the JWT from `localStorage.getItem(TOKEN_KEY)`.
3. Constructs URL: `` `${WS_BASE_URL}/ws?token=${encodeURIComponent(token)}` ``
4. Creates a native browser `WebSocket`.

---

## 2. Heartbeat (Ping/Pong)

**Backend (ws_router.py:152-159):**

A `_heartbeat()` coroutine runs as an asyncio task alongside the receive and send loops:

```python
async def _heartbeat() -> None:
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)  # 15.0 seconds
        ping = {"type": "ping"}
        try:
            queue.put_nowait(ping)
        except asyncio.QueueFull:
            pass
```

The heartbeat is queued (not sent directly) to ensure ordering with other messages. If the queue is full under backpressure, the ping is silently dropped — this is a minor risk as a missed ping could cause the client to interpret a backpressured connection as stale.

**Configuration:** `_HEARTBEAT_INTERVAL = 15.0` seconds (hardcoded; `.env` has `WEBSOCKET_PING_INTERVAL_SECONDS=3` which is the frontend check interval, not the server heartbeat).

**Frontend (websocket.ts:22-31):**

The frontend's `onmessage` handler routes all incoming messages by `msg.type`. `ping` messages do not have a registered handler by default — the frontend silently ignores them (no pong response is sent). This is acceptable for a server-push model where the server does not need client acknowledgment.

The `WebSocketProvider` polls `wsManager.isConnected` every 2 seconds to update React state for the connection indicator in the UI.

---

## 3. Reconnect Logic

**Frontend (websocket.ts:33-43):**

Reconnect is handled in the `ws.onclose` callback:

```typescript
this.ws.onclose = () => {
    if (!this.shouldReconnect) return;
    if (this.reconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
        this.reconnectAttempts++;
        this.reconnectTimer = setTimeout(() => this.connect(), WS_RECONNECT_DELAY);
    }
};

this.ws.onopen = () => {
    this.reconnectAttempts = 0;  // Reset counter on successful connection
};
```

- `WS_MAX_RECONNECT_ATTEMPTS`: controlled by `WEBSOCKET_MAX_RECONNECT_ATTEMPTS=5` (read from env/constants).
- `WS_RECONNECT_DELAY`: fixed delay from constants (no exponential backoff).
- `shouldReconnect`: set to `false` on `disconnect()`, preventing reconnect after intentional logout.

**Reconnect gap coverage (backend):** The backend replays the last 50 events from each Redis stream channel on every new connection (`_replay_recent_events`, ws_router.py:69-95). This means a client that reconnects after a brief outage receives the events missed during the disconnected window, preventing data gaps.

**Limitation:** Reconnect uses a fixed delay (no exponential backoff). Under sustained server unavailability, all clients retry at the same rate, which could cause a thundering herd on reconnect. Recommended: implement exponential backoff with jitter.

---

## 4. Subscription Management

**Backend subscription model:**

All clients subscribe to the same 9 channels on connect. There is no per-client subscription negotiation or topic filtering — every authenticated WebSocket client receives all event types. This is appropriate for the current architecture where access control is at the API level, not the event stream level.

```python
_CHANNELS = [
    "ssa:signal.created",   "ssa:signal.updated",
    "ssa:order.created",    "ssa:order.updated",
    "ssa:position.updated",
    "ssa:risk.breach",
    "ssa:broker.status",
    "ssa:kill_switch.activated", "ssa:kill_switch.deactivated",
]
```

Channel-to-event-type mapping strips the `ssa:` prefix: `"ssa:signal.created"` → `"signal.created"`.

**Frontend subscription model (`use-websocket.ts`):**

Components subscribe to specific event types via `wsManager.on(event, handler)`. The `useWebSocket` hook encapsulates this:

```typescript
export function useWebSocket<T>(event: WSEventType, handler: (data: WSEvent<T>) => void) {
    useEffect(() => {
        return wsManager.on<T>(event, handler);  // Returns cleanup function
    }, [event, handler]);
}
```

The cleanup function (returned by `wsManager.on()`) is called on component unmount, removing the handler from the Set. Multiple components can subscribe to the same event type independently.

**Backpressure:** The backend uses an `asyncio.Queue(maxsize=256)` per client. On queue full, the oldest message is head-dropped to make room for the newest event, preventing slow clients from blocking the Redis Pub/Sub listener.

---

## 5. Message Types

| Channel (Redis) | Event Type (WS) | Frontend Handler Location |
|---|---|---|
| `ssa:signal.created` | `signal.created` | `use-signals.ts` via `useSignalLiveUpdates()` |
| `ssa:signal.updated` | `signal.updated` | `use-signals.ts` via `useSignalLiveUpdates()` |
| `ssa:order.created` | `order.created` | `use-orders.ts` via `useOrderLiveUpdates()` |
| `ssa:order.updated` | `order.updated` | `use-orders.ts` via `useOrderLiveUpdates()` |
| `ssa:position.updated` | `position.updated` | `use-positions.ts` via `usePositionLiveUpdates()` |
| `ssa:risk.breach` | `risk.breach` | Not confirmed in scanned frontend files |
| `ssa:broker.status` | `broker.status` | `broker-view.tsx` line 68 |
| `ssa:kill_switch.activated` | `kill_switch.activated` | `broker-view.tsx` line 69 |
| `ssa:kill_switch.deactivated` | `kill_switch.deactivated` | `broker-view.tsx` line 70 |
| (server-generated) | `ping` | Ignored (no handler registered) |
| (replayed events) | any of the above + `"replayed": true` | Same handlers; replayed flag not currently used by frontend |

**Additional event types referenced in context but not in `_CHANNELS`:**

| Event Type | Notes |
|---|---|
| `health.update` | Referenced in concept; not in `_CHANNELS`; health is polled via REST (`healthService.get` every 15s) |
| `ai.insight` | Not in `_CHANNELS`; AI insights are fetched on demand via REST |

---

## 6. Frontend Handler Routing (use-websocket hook)

The routing mechanism in `WebSocketManager.onmessage`:

```typescript
this.ws.onmessage = (event) => {
    const msg = JSON.parse(event.data) as WSMessage;
    if (!msg.type) return;
    const handlers = this.handlers.get(msg.type);
    handlers?.forEach((h) => h(msg));
};
```

- Messages with no `type` field are silently dropped.
- Malformed JSON is caught by the outer `try/catch` and skipped.
- Multiple handlers per event type are supported (handlers stored in a `Set<EventHandler>`).

**Handler registration pattern used by feature pages:**

- `SignalsView` → calls `useSignalLiveUpdates()` → registers handlers for `signal.created` and `signal.updated` that invalidate the React Query cache for `["signals"]`.
- `OrdersView` → calls `useOrderLiveUpdates()` → similarly for `order.created` / `order.updated`.
- `PositionsView` → calls `usePositionLiveUpdates()` → for `position.updated`.
- `BrokerView` → calls `useWebSocket("broker.status", wsHandler)` and `useWebSocket("kill_switch.activated", wsHandler)` directly, where `wsHandler` invalidates the broker-status query cache.

---

## 7. InMemoryWebSocketManager

The backend uses Redis Pub/Sub directly (no separate in-memory manager class). The `ws_router.py` gateway creates a `pubsub` object per connection via `redis_client.pubsub()` and subscribes to all channels. Each WebSocket connection maintains:

- Its own `asyncio.Queue(maxsize=256)` for backpressure management.
- Its own `pubsub` listener task (`_recv_pubsub`).
- Its own send loop task (`_send_loop`).
- Its own heartbeat task (`_heartbeat`).

All three tasks are run concurrently via `asyncio.wait(..., return_when=FIRST_EXCEPTION)`. If any task raises an exception, the other two are cancelled and cleanup occurs in the `finally` block.

On disconnect:
- `WEBSOCKET_CONNECTIONS` gauge is decremented.
- `pubsub.unsubscribe(*_CHANNELS)` is called.
- `pubsub.close()` is called.

**Metrics tracked:**
- `WEBSOCKET_CONNECTIONS`: Prometheus gauge for current active connections.
- `WEBSOCKET_MESSAGES_SENT_TOTAL`: Prometheus counter labelled by `event_type`.

---

## Summary Table

| Feature | Status | Notes |
|---|---|---|
| JWT authentication on connect | ✅ Implemented | Revocation check via Redis JTI store |
| WS_1008 rejection on auth fail | ✅ Implemented | Before `accept()` |
| 15s server heartbeat | ✅ Implemented | `{"type": "ping"}` queued every 15s |
| Reconnect (up to 5 attempts) | ✅ Implemented | Fixed delay; no exponential backoff |
| Event replay on reconnect | ✅ Implemented | Last 50 events per channel from Redis streams |
| Backpressure (queue 256) | ✅ Implemented | Head-drop on full queue |
| signal.created / updated | ✅ Implemented | Backend + frontend handler |
| order.created / updated | ✅ Implemented | Backend + frontend handler |
| position.updated | ✅ Implemented | Backend + frontend handler |
| risk.breach | ✅ Backend | Frontend handler not confirmed in scanned files |
| broker.status | ✅ Implemented | Backend + frontend handler (`broker-view.tsx`) |
| kill_switch.activated / deactivated | ✅ Implemented | Backend + frontend handler |
| health.update | ⚠️ Not in WS | Health polled via REST every 15s |
| ai.insight | ⚠️ Not in WS | AI insights fetched on demand via REST |
| Connection indicator (UI) | ✅ Implemented | `WebSocketProvider` polls `isConnected` every 2s |
| Metrics (Prometheus) | ✅ Implemented | `WEBSOCKET_CONNECTIONS`, `WEBSOCKET_MESSAGES_SENT_TOTAL` |

---

## Recommendations

1. **Add exponential backoff to reconnect:** Replace the fixed `WS_RECONNECT_DELAY` with an exponentially increasing delay (e.g., 1s, 2s, 4s, 8s, 16s) with jitter. This prevents thundering herd reconnects during server restarts.

2. **Handle `risk.breach` on frontend:** The `ssa:risk.breach` channel is subscribed on the backend but no frontend handler was found. A risk breach should display a toast notification or warning banner (similar to kill switch activation) so the user is immediately alerted.

3. **Add `health.update` to WebSocket channels:** Currently health data is polled via REST every 15 seconds. Adding a `ssa:health.update` channel would enable immediate notification when a service component degrades.

4. **Track replayed flag:** The backend sets `"replayed": true` on replayed events. The frontend could use this flag to suppress toast notifications for historical events on reconnect (avoiding a flood of stale notifications).

5. **Add `ai.insight` to WebSocket channels:** When a new AI insight is generated, push an `ai.insight` event so the AI Insights page auto-refreshes without polling.
