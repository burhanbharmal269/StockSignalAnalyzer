# 12 — WebSocket Manager

## Purpose

Define the architecture for managing persistent WebSocket connections to broker streaming APIs. The WebSocket Manager is the single point of entry for all real-time market data. It owns the connection lifecycle, subscription management, message normalization, and fan-out to the internal event bus. All other components consume events; none interact with the WebSocket layer directly.

---

## Design Principles

- The WebSocket Manager is infrastructure. The domain layer has no knowledge of it.
- The manager publishes normalized domain events. It never leaks broker-specific data structures.
- Connection state is observable. Every state transition is logged and metriced.
- Reconnection is automatic and self-healing within defined bounds. Beyond those bounds, it alerts and activates the kill switch.
- Subscription management is declarative. Components declare what they need; the manager handles batching and broker limits.

---

## Interface Definition

```
IWebSocketManager:
    start() -> None
    stop() -> None
    subscribe(instruments: list[InstrumentToken], mode: SubscriptionMode) -> None
    unsubscribe(instruments: list[InstrumentToken]) -> None
    get_connection_state() -> ConnectionState
    get_subscription_count() -> int
    get_last_tick_time(instrument: InstrumentToken) -> datetime | None
```

```
SubscriptionMode (Enum):
    LTP    — last traded price only (minimal bandwidth)
    QUOTE  — LTP + OHLC + volume + best bid/ask
    FULL   — QUOTE + market depth (5 levels) + OI (for FnO)
```

Kite-specific mode mapping (inside the adapter, never exposed to application layer):
- `LTP` → Kite mode `ltp`
- `QUOTE` → Kite mode `quote`
- `FULL` → Kite mode `full`

Future brokers implement their own internal mapping.

---

## Connection State Machine

```
DISCONNECTED
    │
    │  start() called
    ▼
CONNECTING
    │
    │  TCP + WebSocket handshake complete
    ▼
AUTHENTICATING
    │
    │  Access token validated by broker
    ▼
CONNECTED
    │
    │  subscribe() called with instrument list
    ▼
SUBSCRIBING
    │
    │  Subscription acknowledgement received
    ▼
STREAMING  ◄──────────────────────────────────────────┐
    │                                                  │
    │  Network error / broker timeout / ping failure   │
    ▼                                                  │
RECONNECTING ──── backoff wait ─────────────────────── ┘
    │
    │  Max retries exceeded
    ▼
FAILED
    │
    │  Alert sent, kill switch evaluated
    ▼
DISCONNECTED (manual restart required)
```

Illegal transitions raise a `WebSocketStateError` and are logged at ERROR level.

---

## Reconnection Policy

Reconnection uses exponential backoff with full jitter to prevent thundering herd on broker infrastructure.

| Attempt | Base Delay | Jitter Range | Max Delay |
|---|---|---|---|
| 1 | 1s | 0–1s | 2s |
| 2 | 2s | 0–2s | 4s |
| 3 | 4s | 0–4s | 8s |
| 4 | 8s | 0–8s | 16s |
| 5 | 16s | 0–16s | 32s |
| > 5 | — | — | FAILED |

On reconnect (RECONNECTING → STREAMING):
1. Re-authenticate using the current broker session token.
2. Re-subscribe to all previously active instruments in the same modes.
3. Publish `system.broker.connected` event with `reconnect=true` flag.
4. Trigger `ReconciliationService` to diff OMS positions against broker positions.
5. Flush any buffered ticks that arrived during the reconnect window.

If the access token has expired during reconnection, the manager enters `FAILED` state and raises `BrokerSessionExpiredError`. It does not attempt further reconnects. The operator must re-authenticate.

---

## Market Hours Awareness

The WebSocket Manager is aware of NSE market hours. It will not attempt reconnection outside trading hours:

| Segment | Session |
|---|---|
| NSE Equity / FnO (pre-open) | 09:00–09:15 IST |
| NSE Equity / FnO (regular) | 09:15–15:30 IST |
| NSE Currency Derivatives | 09:00–17:00 IST |
| MCX Commodity | 09:00–23:30 IST |

Outside active session hours:
- No reconnection attempted if the session ends naturally.
- No reconnection attempted after 15:35 IST for NSE equity/FnO.
- Next-day reconnection window opens at 09:00 IST.
- Market holiday calendar is sourced from the `InstrumentMasterService`.

---

## Heartbeat / Keep-Alive

Kite sends a ping frame every 3 seconds. The manager must respond with a pong within 2 seconds or the connection is considered dead.

**Application-level heartbeat:**
- Every 5 seconds: verify that at least one tick has been received in the last 10 seconds for at least one subscribed instrument (during market hours).
- If no tick received in 10 seconds during market hours: log WARNING, increment `websocket_stale_ticks_total`.
- If no tick received in 30 seconds: transition to RECONNECTING.

---

## Subscription Management

### Capacity Limits

Kite WebSocket supports a maximum of 3,000 instrument subscriptions per connection. For coverage beyond 3,000 instruments, the manager creates multiple parallel connections.

```
ConnectionPool:
    connections: list[WebSocketConnection]     — one per 3,000 instruments
    instrument_map: dict[InstrumentToken, WebSocketConnection]
```

Each connection in the pool independently manages its own state machine and reconnect policy.

### Subscription Batching

Subscriptions are not sent individually. Requests are debounced for 100ms and coalesced:
- A new subscription triggers a 100ms timer.
- All subscribe/unsubscribe calls within that window are batched into a single request.
- This prevents subscription storms when 50 instruments are subscribed at startup.

### Default Subscription Mode by Instrument Type

| Instrument Type | Default Mode |
|---|---|
| FnO instruments (actively traded) | FULL |
| Underlying indices (NIFTY, BANKNIFTY) | QUOTE |
| Watchlist instruments (not currently traded) | LTP |

Mode upgrades and downgrades are applied at runtime by sending a new subscribe request with the desired mode. No unsubscription is needed — the broker replaces the existing subscription.

---

## Message Normalization

Kite delivers ticks in a binary packet format. The `KiteWebSocketManager` decodes and normalizes each tick into a canonical `TickEvent` before publishing to the event bus.

```
TickEvent:
    instrument_token:    int
    tradingsymbol:       str
    exchange:            Exchange
    last_price:          Decimal
    last_quantity:       int
    buy_quantity:        int
    sell_quantity:       int
    volume:              int
    open_interest:       int | None         (FnO only)
    change:              Decimal
    last_trade_time:     datetime
    timestamp:           datetime           (tick arrival time, UTC)
    depth:               MarketDepth | None (FULL mode only)
    ohlc:                OHLC | None        (QUOTE mode and above)
```

**Normalization rules:**
- All prices are `Decimal` (not `float`) to avoid floating-point precision loss.
- All timestamps are UTC-aware. Broker timestamps in IST are converted on ingestion.
- `open_interest` is `None` for equity instruments — never defaulted to 0 to avoid ambiguity.
- Missing fields from lower-mode ticks are `None`.

---

## Fan-Out to Event Bus

On receiving a normalized tick, the manager publishes to `market_data.tick.received`. It does not know what consumes the tick.

Fan-out is non-blocking. If the event bus publish is slow (Redis backpressure), the manager drops the tick and increments `websocket_ticks_dropped_total`. Dropping stale ticks is preferable to blocking the WebSocket read loop, which would cause missed ticks.

**Backpressure threshold:** if the event bus queue depth exceeds 10,000 unprocessed ticks, the manager logs ERROR and emits a `system.health_check.failed` event.

---

## Candle Aggregation

The WebSocket Manager does not aggregate candles. A separate `CandleAggregatorService` consumes `market_data.tick.received` and publishes `market_data.candle.closed` when a time boundary is crossed (1m, 5m, 15m, 1h).

The aggregator maintains an in-memory OHLCV accumulator per instrument per interval. On interval boundary:
1. Emit `market_data.candle.closed` with the completed candle.
2. Reset the accumulator.
3. Write the candle to TimescaleDB asynchronously (non-blocking via queue).

---

## Option Chain Polling

Real-time option chain updates for the full chain are not available via the Kite WebSocket. The manager uses a hybrid approach:

- **Individual strike prices:** subscribed via WebSocket in FULL mode (OI + price).
- **Full chain snapshot** (for Max Pain, PCR): polled every 60 seconds via REST API.

The `OptionChainPoller` service handles REST polling and publishes `market_data.option_chain.updated`. The WebSocket Manager handles per-strike tick updates via `market_data.tick.received`.

---

## Broker Session Token Refresh

Kite access tokens expire daily at 06:00 IST. The WebSocket Manager coordinates with the `BrokerSessionService`:

1. At 05:50 IST: transition to DISCONNECTED gracefully.
2. Block all new subscriptions.
3. Alert operator: manual re-authentication required.
4. Once new token is available: transition through full state machine back to STREAMING.
5. Re-subscribe to all previously active instruments.

If trading is live and the token expires unexpectedly mid-session (rare but possible):
- Manager enters FAILED state immediately.
- Kill switch is evaluated (if positions are open, activate kill switch).
- Operator is alerted with CRITICAL severity.

---

## Kill Switch Integration

The WebSocket Manager listens on `system.kill_switch.activated`:
- On activation: unsubscribe all instruments, transition to DISCONNECTED, do not reconnect.
- Resume only after `system.kill_switch.deactivated` is received.
- Publishes `system.broker.disconnected` with `reason="kill_switch"` on activation.

---

## Observability

### Prometheus Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `websocket_connected` | Gauge | `broker`, `connection_id` | 1 if connected, 0 otherwise |
| `websocket_reconnect_total` | Counter | `broker`, `reason` | Total reconnection attempts |
| `websocket_reconnect_failed_total` | Counter | `broker` | Reconnections that exhausted retries |
| `websocket_ticks_received_total` | Counter | `broker`, `mode` | Total ticks received |
| `websocket_ticks_dropped_total` | Counter | `broker`, `reason` | Ticks dropped (backpressure/error) |
| `websocket_subscriptions_active` | Gauge | `broker`, `mode` | Current subscription count |
| `websocket_last_tick_age_seconds` | Gauge | `broker` | Seconds since last tick received |
| `websocket_message_processing_seconds` | Histogram | `broker` | Decode + normalize + publish latency |

### Structured Log Events

Every state transition emits a structured log at INFO level:
```json
{
  "event": "websocket_state_change",
  "from_state": "STREAMING",
  "to_state": "RECONNECTING",
  "reason": "ping_timeout",
  "broker": "kite",
  "connection_id": "conn_1",
  "attempt": 1,
  "next_retry_in_seconds": 1.4
}
```

---

## Testing Strategy

- Unit tests use a mock WebSocket server that replays binary Kite tick payloads from fixtures.
- Integration tests run against a local mock Kite WebSocket server in replay mode.
- Connection state machine is unit-tested for all legal and illegal transitions.
- Reconnect policy is unit-tested with simulated failures.
- The `InMemoryEventBus` is used for all tests; tick events are verified by consuming from the bus.
