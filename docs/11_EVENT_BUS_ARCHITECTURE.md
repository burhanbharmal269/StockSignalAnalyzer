# 11 — Event Bus Architecture

## Purpose

Define the event-driven communication backbone for all inter-component communication within the platform. This document covers technology selection, event taxonomy, topic design, consumer group model, message envelope schema, delivery guarantees, dead letter handling, and the upgrade path from Phase 1 to distributed scale.

---

## Design Principles

- Every domain state change produces an immutable event.
- Producers never know who consumes their events.
- Consumers are independently deployable and scalable.
- The event log is the source of truth for pipeline replay (backtesting, debugging).
- No component calls another component's method directly across process boundaries.
- The event bus is a dependency of infrastructure, not of the domain layer.

---

## Technology Decision

### Phase 1: Redis Streams

**Rationale:**
- Already in the stack (health check references Redis).
- Zero additional infrastructure.
- Supports consumer groups with at-least-once delivery.
- Supports message acknowledgement and pending entry lists (PEL).
- Supports `XRANGE` for replay.
- Sufficient for single-machine or small-cluster deployment.
- Max throughput: ~100,000 messages/second per stream on a single Redis instance.

**Limitations acknowledged:**
- No built-in cross-datacenter replication.
- Maximum message retention limited by Redis memory (mitigated by capped streams via `MAXLEN`).
- Not suitable for multi-region deployment.

### Phase 2+ Upgrade Path: Apache Kafka

Migrate to Kafka when any of the following conditions are met:
- Instrument coverage exceeds 200 symbols.
- Multiple independent processes need to replay the same event log independently.
- Cross-region replication is required.
- Message retention beyond 24 hours is needed on the hot stream.

The abstraction layer (`IEventBus`) ensures zero application-layer changes on migration. Only the infrastructure adapter changes.

---

## Abstraction Interface

```
IEventBus:
    publish(topic: str, event: DomainEvent) -> None
    subscribe(topic: str, group: str, handler: Callable) -> None
    ack(topic: str, group: str, message_id: str) -> None
    replay(topic: str, from_id: str, to_id: str) -> AsyncIterator[DomainEvent]
```

Implementations:
- `RedisStreamEventBus` — Phase 1
- `KafkaEventBus` — Phase 2+
- `InMemoryEventBus` — Testing only

---

## Message Envelope Schema

Every message on every topic uses this envelope. Application code never constructs raw stream payloads.

```json
{
  "event_id":       "<uuid4>",
  "event_type":     "<EventClassName>",
  "event_version":  "<semver, e.g. 1.0.0>",
  "topic":          "<stream name>",
  "source":         "<service name that emitted>",
  "correlation_id": "<trace ID for distributed tracing>",
  "timestamp":      "<ISO 8601 UTC>",
  "payload":        { "...event-specific fields..." }
}
```

Rules:
- `event_id` is globally unique. Consumers use it for idempotency checks.
- `event_version` follows semver. Minor bumps are backwards-compatible. Major bumps require a new topic or schema migration.
- `correlation_id` propagates the OpenTelemetry trace ID across all stages of a single signal lifecycle.
- `payload` is a flat or shallow-nested structure. No polymorphic payload unions.

---

## Topic / Stream Taxonomy

Topics are named `<domain>.<entity>.<verb>` in snake_case.

### Market Data Domain

| Topic | Producer | Consumers | Retention |
|---|---|---|---|
| `market_data.tick.received` | WebSocketManager | FeatureEngineering, OMS (LTP), PositionMTM | 1 hour |
| `market_data.candle.closed` | CandleAggregator | FeatureEngineering, RegimeEngine | 24 hours |
| `market_data.option_chain.updated` | OptionChainPoller | FeatureEngineering, StrikeSelector | 24 hours |
| `market_data.quote.updated` | QuotePoller | Dashboard, PositionMTM | 30 minutes |

### Feature Domain

| Topic | Producer | Consumers | Retention |
|---|---|---|---|
| `features.technical.computed` | FeatureEngineeringService | StrategyEvaluator | 24 hours |
| `features.regime.detected` | RegimeEngine | ScoringEngine, RiskEngine | 24 hours |
| `features.sentiment.computed` | SentimentService (async) | ScoringEngine | 24 hours |

### Signal Domain

| Topic | Producer | Consumers | Retention |
|---|---|---|---|
| `signal.strategy.evaluated` | StrategyEvaluator | ScoringEngine | 24 hours |
| `signal.score.computed` | ScoringEngine | ConfidenceEngine | 24 hours |
| `signal.confidence.computed` | ConfidenceEngine | RiskEngine | 24 hours |
| `signal.risk.approved` | RiskEngine | OMS, Analytics | 7 days |
| `signal.risk.rejected` | RiskEngine | Analytics, Notification | 7 days |
| `signal.expired` | SignalExpiryWorker | Analytics | 7 days |

### Order Domain

| Topic | Producer | Consumers | Retention |
|---|---|---|---|
| `order.submitted` | OMS | BrokerAdapter, Analytics, Notification | 30 days |
| `order.filled` | BrokerAdapter | OMS, PositionService, Analytics, Notification | 30 days |
| `order.cancelled` | BrokerAdapter | OMS, Analytics, Notification | 30 days |
| `order.rejected` | BrokerAdapter | OMS, RiskEngine, Analytics, Notification | 30 days |
| `order.modified` | BrokerAdapter | OMS, Analytics | 30 days |

### Position Domain

| Topic | Producer | Consumers | Retention |
|---|---|---|---|
| `position.opened` | PositionService | RiskEngine, Analytics, Dashboard | 30 days |
| `position.updated` | PositionMTMService | RiskEngine, Dashboard | 1 hour |
| `position.closed` | PositionService | RiskEngine, Analytics, Notification | 30 days |
| `position.reconciled` | ReconciliationService | Analytics | 30 days |

### Risk Domain

| Topic | Producer | Consumers | Retention |
|---|---|---|---|
| `risk.limit.breached` | RiskEngine | KillSwitch, Notification | 30 days |
| `risk.drawdown.alert` | RiskEngine | Notification, Dashboard | 30 days |
| `risk.margin.alert` | RiskEngine | Notification, Dashboard | 30 days |

### System Domain

| Topic | Producer | Consumers | Retention |
|---|---|---|---|
| `system.kill_switch.activated` | KillSwitchService | OMS, BrokerAdapter, Notification, Dashboard | 90 days |
| `system.kill_switch.deactivated` | KillSwitchService | OMS, BrokerAdapter, Notification | 90 days |
| `system.broker.connected` | WebSocketManager | Dashboard, HealthCheck | 7 days |
| `system.broker.disconnected` | WebSocketManager | KillSwitch (conditional), Notification | 7 days |
| `system.heartbeat` | HeartbeatService | DeadMansSwitch | 1 hour |
| `system.health_check.failed` | HealthCheckService | Notification, Dashboard | 7 days |
| `system.instrument_master.refreshed` | InstrumentMasterService | All services | 7 days |

### News Domain

| Topic | Producer | Consumers | Retention |
|---|---|---|---|
| `news.article.ingested` | NewsPoller | SentimentService | 7 days |
| `news.sentiment.computed` | SentimentService | ScoringEngine (cache write) | 7 days |

---

## Consumer Group Design

Each logical consumer registers a named consumer group. Multiple instances of the same consumer can share a group (competing consumers) — only one instance processes each message.

| Consumer Service | Group Name | Parallelism |
|---|---|---|
| FeatureEngineeringService | `feature-engineering` | 1 per instrument partition |
| RegimeEngine | `regime-engine` | 1 |
| StrategyEvaluator | `strategy-evaluator` | N (one per strategy) |
| ScoringEngine | `scoring-engine` | 1 per symbol |
| ConfidenceEngine | `confidence-engine` | 1 |
| RiskEngine | `risk-engine` | 1 (serialized for correctness) |
| OMS | `oms` | 1 (serialized for correctness) |
| PositionMTMService | `position-mtm` | 1 |
| SentimentService | `sentiment-service` | N (rate-limited by AI budget) |
| Analytics | `analytics-writer` | N |
| Notification | `notification-service` | N |
| Dashboard | `dashboard-broadcaster` | N |
| KillSwitch | `kill-switch` | 1 (must be single consumer) |

---

## Delivery Guarantees

| Guarantee | Mechanism | Applies To |
|---|---|---|
| At-least-once | Consumer acks after processing; re-delivered on crash | All topics |
| Exactly-once (logical) | Consumer checks `event_id` against processed-IDs set in Redis before processing | OMS, PositionService |
| Ordering within symbol | Topic partitioned by `symbol` hash | market_data.*, signal.* |
| No ordering guarantee | Analytics, notification topics | analytics.*, notification.* |

**Idempotency contract:** Every consumer that executes a side-effecting operation (write to DB, call broker) must implement idempotency keyed on `event_id`. If the event has already been processed, the consumer acknowledges it without re-executing.

---

## Dead Letter Stream

Failed events (after N retries) are moved to a Dead Letter Stream (DLS).

- DLS topic name: `dlq.<original_topic>` (e.g., `dlq.signal.risk.approved`)
- Retention: 7 days
- Alert: any DLS write triggers a `system.health_check.failed` event

DLS entry envelope adds:
```json
{
  "original_event":  "...",
  "failure_reason":  "<exception class and message>",
  "attempt_count":   3,
  "first_failed_at": "<ISO 8601 UTC>",
  "last_failed_at":  "<ISO 8601 UTC>"
}
```

DLS entries must be inspectable via the admin dashboard and replayable individually via API.

---

## Retry Policy

| Event Criticality | Max Retries | Backoff | After Max Retries |
|---|---|---|---|
| Order events | 5 | Exponential, 100ms base | DLS + alert |
| Signal events | 3 | Exponential, 200ms base | DLS + alert |
| Feature events | 3 | Fixed 500ms | DLS (no alert) |
| Analytics events | 2 | Fixed 1s | DLS (no alert) |
| Notification events | 3 | Fixed 2s | DLS + log |

---

## Backtesting / Replay Integration

The event bus supports historical replay for the backtesting engine:

1. Backtesting replays `market_data.tick.received` and `market_data.candle.closed` from TimescaleDB via a `HistoricalEventSource` adapter implementing the same `IEventBus.subscribe` contract.
2. The strategy evaluator, scoring engine, and risk engine run unchanged.
3. OMS in backtesting mode uses a `PaperBrokerAdapter` instead of the live broker.
4. All replay events carry `simulation_id` in `correlation_id` to isolate backtest writes.

No component can distinguish live from replay operation — the event interface is identical.

---

## Stream Capping (Memory Management)

All Redis Streams use `MAXLEN ~` (approximate trimming):

| Topic | MAXLEN |
|---|---|
| `market_data.tick.received` | 100,000 |
| `market_data.candle.closed` | 50,000 |
| `signal.*` | 10,000 |
| `order.*` | 50,000 |
| `system.*` | 10,000 |

Approximate trimming (`~`) allows Redis to trim at efficient chunk boundaries.

**Durable storage:** before messages are trimmed from Redis, the `EventArchiveService` reads and persists them to TimescaleDB `signal_events` and `order_events` tables, providing long-term queryability without Redis memory pressure.

---

## Latency Budget Per Stage

| Stage | Budget | Notes |
|---|---|---|
| Tick received → FeatureComputed | 500ms | Incremental indicator update |
| FeatureComputed → StrategyEvaluated | 200ms | All strategies in parallel |
| StrategyEvaluated → SignalScored | 100ms | Pure computation |
| SignalScored → RiskDecision | 200ms | Includes margin API call |
| RiskDecision → OrderSubmitted | 100ms | OMS write |
| OrderSubmitted → BrokerConfirmed | 500ms | Broker API latency budget |
| **End-to-end (tick → broker)** | **< 2s P99** | SLO target |

---

## Phase 1 Implementation Constraints

- Single Redis instance, single process.
- All consumer groups run as `asyncio` tasks within the same process.
- `InMemoryEventBus` used for all unit tests.
- `RedisStreamEventBus` used for integration tests with a test Redis instance.
- No cross-machine event delivery in Phase 1.
- Consumer group lag monitored via `XPENDING` and exposed as a Prometheus gauge.

---

## Observability

| Metric | Type | Labels | Description |
|---|---|---|---|
| `event_bus_published_total` | Counter | `topic` | Events published |
| `event_bus_consumed_total` | Counter | `topic`, `group` | Events consumed |
| `event_bus_consumer_lag` | Gauge | `topic`, `group` | Unprocessed messages |
| `event_bus_dlq_total` | Counter | `topic` | Events sent to DLQ |
| `event_bus_retry_total` | Counter | `topic`, `group` | Retry attempts |
| `event_bus_processing_seconds` | Histogram | `topic`, `group` | Consumer handler duration |
