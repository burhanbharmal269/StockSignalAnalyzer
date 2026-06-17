# Implementation Plan

**Platform:** NSE · Indian Equity FnO Trading Platform  
**Architecture Version:** V1 (Post-Audit, All Conflicts Resolved)  
**Date:** 2026-06-11  
**Prerequisite:** All 23 architecture documents read before any phase begins.

---

## Pre-Implementation Architecture Baseline

The following conflicts from the architecture audit have been resolved:

| Conflict | Resolution |
|----------|-----------|
| Three weight systems (Doc 16 vs 19 vs 21) | Doc 19/21 V1 weights are authoritative. Doc 16 updated. |
| Two confidence formulas | Doc 21's 9-component model is canonical. Doc 16 updated. |
| admin/admin in roadmap | Removed. First-run generates random password. |
| Signal state machine mismatch | Doc 16 unified to Doc 21/22 state machine. |
| Kill switch cancellation deadlock | Cancellations bypass OMS kill switch gate (Doc 14 + 22). |
| Missing OMS design | Doc 22 created. |
| Missing secrets management | Doc 23 created. |
| Missing `signal_performance_stats` schema | Added to Doc 18. |
| Daily loss same-day deactivation edge case | Explicit override flow with PAPER-only resume (Doc 14). |
| DMS + kill switch interaction | Documented: DMS gates on kill switch inactive (Doc 14). |

**Authoritative document set for implementation:** Docs 09, 11–23 (inclusive).  
Docs 01–08 and 10 are superseded by the detailed documents. Read them for intent only.

---

## Completed Phases

```
Phase 1:  Project Foundation                  ✓ COMPLETE
Phase 2:  Security & Configuration Layer      ✓ COMPLETE
Phase 3:  Domain Layer                        ✓ COMPLETE
Phase 4:  Database Layer (TimescaleDB)        ✓ COMPLETE
Phase 5:  Observability Foundation            ✓ COMPLETE
Phase 6:  Authentication & Authorization      ✓ COMPLETE
Phase 7:  Instrument Master & Market Data     ✓ COMPLETE
Phase 8:  Broker & WebSocket Abstraction      ✓ COMPLETE
Phase 9:  Market Regime Engine                ✓ COMPLETE
```

## Remaining Phase Structure

```
Phase 10: Strategy Framework                  — all IScoreComponent implementations
Phase 11: Scoring Engine                      — aggregation, regime multipliers, penalties
Phase 12: Confidence Engine                   — 9-component formula, calibration, fingerprint
Phase 13: Risk Engine                         — 15 pre-trade checks, position sizing
Phase 14: Signal Engine                       — full pipeline: strategy → score → risk → OMS
Phase 15: Dashboard                           — API + Next.js frontend
Phase 16: Paper Trading Validation            — 30 trading days minimum
Phase 17: AI Layer                            — IAIProvider, OpenAI, sentiment (AFTER paper validation)
Phase 18: Live Trading                        — all Phase 16 exit criteria required
```

**Design intent:** The deterministic trading edge (Phases 10–14) must be complete and paper-validated
before any AI sentiment layer is added. AI is an optional input to the Scoring Engine only —
it never touches OMS, Risk Engine, Position Sizer, or Kill Switch.

**What changed from the original plan:**
- OMS, Kill Switch, and AI Provider are no longer blocking the Strategy/Scoring/Risk pipeline.
- OMS is now part of Phase 14 (Signal Engine integration) — it only needs to exist as a thin
  paper-mode forwarder at that stage.
- Kill Switch wires into the Risk Engine check (Phase 13) without being a standalone phase.
- AI Layer is deferred to Phase 17 — after paper trading proves the deterministic edge works.
- News Intelligence (original Phase 10) is absorbed into the AI Layer as one AI use case,
  not a standalone phase.
- Feature Engineering (original Phase 9) was already implemented as part of the regime engine
  FeatureSnapshot contract. The full indicator computation pipeline remains pending but is
  consumed by Phase 10 strategies via FeatureSnapshot.

---

## Phase 1 — Project Foundation

**Goal:** Establish the project skeleton, tooling, and CI pipeline. No business logic.

**Deliverables:**
```
src/
  core/
    domain/
    application/
    infrastructure/
    presentation/
  config/
    scoring_weights.yaml      ← V1 weights from Doc 19/21
    risk.yaml                 ← limits from Doc 17
    prompts/                  ← AI prompt YAML files from Doc 15
  tests/
    unit/
    integration/
    fixtures/
.env.example                  ← template; no real secrets
pyproject.toml
Dockerfile
.github/workflows/ci.yml
```

**Acceptance criteria:**
- `pytest` runs with zero tests (but the test runner works).
- `ruff` and `mypy` pass on empty stubs.
- Docker container builds.
- CI pipeline runs on every push: lint → type-check → test → security audit (`pip-audit`).
- No `.env` file committed. `.env.example` shows all required variables with placeholder values.

**Key architecture decisions:**
- Python 3.12+ with full type hints everywhere.
- `uv` for dependency management (faster than pip).
- `pyproject.toml` as the single project configuration file.
- `structlog` configured from day one — no `print()` statements ever.
- Secrets: `pydantic-settings` reads from environment variables + `.env` (local dev only).

---

## Phase 2 — Security & Configuration Layer

**Goal:** Configuration and secrets management. Every value that the docs say should be configurable must come from config — zero hardcoded values from this point forward.

**Reference docs:** Doc 09 (forbidden practices), Doc 23 (security baseline).

**Deliverables:**
```
src/core/infrastructure/config/
  settings.py        ← pydantic-settings BaseSettings subclass
  risk_config.py     ← risk limits (from Doc 17)
  scoring_config.py  ← weights loader (from Doc 16/19)
  ai_config.py       ← provider settings, budget limits (from Doc 15)
  security_config.py ← JWT settings, allowed admin IPs, Redis auth

src/core/infrastructure/secrets/
  secrets_client.py  ← ISecretsClient interface
  env_secrets.py     ← EnvSecretsClient (dev/test)
  aws_secrets.py     ← AWSSecretsManagerClient (staging/prod, stub)
```

**Acceptance criteria:**
- `from config.settings import get_settings()` works in every layer.
- Changing a risk limit in `config/risk.yaml` is picked up on restart without code changes.
- `scoring_weights.yaml` loads V1 weights, computes SHA-256 hash on load.
- No value from Doc 09's "forbidden list" appears in source code (CI lint rule enforces this).
- `mypy --strict` passes on all config modules.

---

## Phase 3 — Domain Layer

**Goal:** Pure Python domain entities, value objects, and enums. Zero infrastructure dependencies.

**Reference docs:** Doc 01, Doc 09, Doc 12 (TickEvent), Doc 13 (Instrument), Doc 16 (Signal), Doc 17 (RiskDecision), Doc 22 (Order, Position).

**Deliverables:**
```
src/core/domain/
  entities/
    signal.py          ← Signal with state machine (unified Doc 16/21/22 states)
    order.py           ← Order with state machine (Doc 22)
    position.py        ← Position (Doc 22)
    instrument.py      ← Instrument (Doc 13)

  value_objects/
    price.py           ← Decimal wrapper; never float
    symbol.py          ← Symbol with exchange normalization
    score.py           ← Score (0–100 range enforcement)
    confidence.py      ← Confidence (0–100)
    signal_fingerprint.py ← SHA-256 computation

  enums/
    asset_type.py      ← AssetType (Doc 09)
    signal_type.py     ← SignalType
    order_status.py    ← OrderState (unified state machine)
    market_regime.py   ← MarketRegime (5 values, Doc 20)
    strategy_type.py   ← StrategyType

  events/
    domain_events.py   ← Base DomainEvent + all domain event types
    signal_events.py   ← SignalGenerated, SignalScored, etc.
    order_events.py    ← OrderSubmitted, OrderFilled, etc.
    risk_events.py     ← RiskApproved, RiskRejected, LimitBreached
    system_events.py   ← KillSwitchActivated, HeartbeatPublished

  exceptions/
    domain_exceptions.py ← SignalStateError, OrderStateError, KillSwitchActiveError, etc.
```

**Acceptance criteria:**
- Zero imports from `infrastructure` or `presentation` in any domain file.
- Signal state machine enforces all valid/invalid transitions (unit tested for every edge).
- Order state machine enforces all valid/invalid transitions.
- `Price` value object refuses float inputs at construction time.
- All enums are string-backed (serializable to/from JSON without custom encoders).
- 100% unit test coverage on all state machine transition logic.

---

## Phase 4 — Database Layer

**Goal:** TimescaleDB schema, migrations, connection pool, and repository pattern.

**Reference docs:** Doc 03, Doc 09, Doc 13 (instruments schema), Doc 17 (risk_decisions), Doc 18 (hypertables), Doc 22 (orders, positions), Doc 23 (permission model).

**Deliverables:**
```
src/core/infrastructure/database/
  connection.py        ← SQLAlchemy async engine factory (write + read engines)
  pool.py              ← PgBouncer-aware pool config (from Doc 18)
  models/              ← SQLAlchemy ORM models (separate from domain entities)
    market_data.py
    option_chain.py
    instruments.py
    signals.py
    orders.py
    positions.py
    risk_decisions.py
    kill_switch_events.py
    signal_performance_stats.py   ← NEW (from Doc 18 audit fix)
    audit_log.py
  repositories/
    i_signal_repository.py       ← interface
    i_order_repository.py
    i_position_repository.py
    i_instrument_repository.py
    signal_repository.py
    order_repository.py
    position_repository.py
    instrument_repository.py

alembic/
  env.py               ← TimescaleDB-aware (CREATE EXTENSION, create_hypertable)
  versions/
    20260101_0730_phase4_initial_schema.py
```

**Acceptance criteria:**
- `alembic upgrade head` on a fresh PostgreSQL+TimescaleDB instance creates the full schema.
- `SELECT * FROM timescaledb_information.hypertables` returns 5 tables.
- `SELECT * FROM timescaledb_information.continuous_aggregates` returns ohlcv_1min through ohlcv_1d.
- `SELECT * FROM timescaledb_information.compression_settings` returns settings for all 4 hypertables.
- All repository methods are async and return domain entities (not ORM models).
- `trading_app` DB user has no DDL or DELETE rights (verified via SQL permission query in CI).
- Integration tests use a dedicated test database; no test ever touches the development DB.

---

## Phase 5 — Observability Foundation

**Goal:** Structured logging, distributed tracing, and Prometheus metrics — all wired in before any business logic is written.

**Reference docs:** Doc 09 (logging rules), Doc 11 (correlation_id), Doc 23 (secrets scrubbing).

**Deliverables:**
```
src/core/infrastructure/observability/
  logging.py           ← structlog configuration + secrets scrubber processor
  tracing.py           ← OpenTelemetry setup; correlation_id propagation
  metrics.py           ← Prometheus registry; common metric factory functions

src/core/infrastructure/middleware/
  request_logging.py   ← log every request/response with correlation_id
  error_handler.py     ← global exception handler; no silent failures
```

**Acceptance criteria:**
- Every log line is valid JSON (verified by `jq` in CI test).
- Secrets scrubber tested: a log line containing `password=secret` outputs `password=[REDACTED]`.
- `correlation_id` flows from incoming HTTP request → event bus message → DB writes.
- Prometheus `/metrics` endpoint serves all standard process metrics plus a test counter.
- Zero `print()` statements anywhere in source (CI lint rule).

---

## Phase 6 — Authentication & Authorization

**Goal:** JWT authentication with first-run random credential generation. No admin/admin ever.

**Reference docs:** Doc 09, Doc 23 (first-run protocol, JWT RS256, rate limiting, IP allowlist).

**Deliverables:**
```
src/core/infrastructure/auth/
  jwt_service.py       ← RS256 sign/verify; token revocation via Redis jti blocklist
  password_service.py  ← Argon2id hash/verify
  rate_limiter.py      ← login rate limiter (5 failures / 10 min → 30 min lockout)
  first_run.py         ← first-run credential generation + stdout print

src/core/presentation/api/v1/
  auth_router.py       ← POST /login, POST /logout, POST /refresh, POST /change-password
  middleware/
    auth_middleware.py  ← JWT validation on every authenticated route
    ip_allowlist.py     ← admin endpoint IP gate
```

**Acceptance criteria:**
- Fresh startup with empty DB generates random admin password, prints to stdout, sets `force_change=True`.
- Second startup does NOT regenerate the password (idempotent).
- Login with wrong password 5 times → 403 for 30 minutes from same IP.
- Kill switch endpoint called from non-allowlisted IP → 403.
- JWT RS256 verified: tampered token → 401.
- Token revoked on logout: subsequent request with same token → 401.
- `force_change=True` account cannot call any other endpoint until password changed.

---

## Phase 7 — Instrument Master & Market Data Infrastructure

**Goal:** Instrument registry, daily refresh lifecycle, expiry calendar, and base data provider abstraction.

**Reference docs:** Doc 12 (IDataProvider, NSE hours), Doc 13 (Instrument Master — all of it).

**Deliverables:**
```
src/core/domain/interfaces/
  i_data_provider.py    ← IDataProvider interface (Doc 12)
  i_instrument_master.py ← IInstrumentMasterService (Doc 13)

src/core/infrastructure/data/
  kite_data_provider.py
  nse_provider.py
  instrument_master_service.py  ← refresh, cache, expiry calendar
  expiry_calendar.py

src/core/infrastructure/scheduler/
  pre_market_tasks.py   ← 07:30 instrument refresh, 07:40 diff, 07:50 cache, 07:55 event
```

**Acceptance criteria:**
- `instrument_master_service.refresh()` downloads from Kite, validates (>10,000 rows), diffs, upserts.
- Lot size change detected → CRITICAL alert, does not auto-apply without operator confirmation.
- `get_next_expiry(NIFTY, NSE_FO)` returns next Thursday (or adjusted Wednesday if holiday).
- `is_trading_day(date)` correctly handles NSE holidays.
- Redis cache populated with `instrument:{token}` hashes after refresh.
- Cache miss during market hours logs WARNING.
- Platform refuses to start if instrument refresh has not completed successfully today.

---

## Phase 8 — Broker Abstraction & WebSocket Manager

**Goal:** IBroker and IWebSocketManager with full Kite implementation. Broker token encrypted at rest.

**Reference docs:** Doc 04, Doc 12 (WebSocket Manager — all of it).

**Deliverables:**
```
src/core/domain/interfaces/
  i_broker.py            ← IBroker (Doc 04)
  i_websocket_manager.py ← IWebSocketManager (Doc 12)

src/core/infrastructure/broker/
  kite_broker.py         ← composition (not inheritance) of KiteConnect
  kite_websocket.py      ← KiteWebSocketManager; binary frame decode; Decimal prices
  kite_data_provider.py  ← KiteDataProvider; hybrid option chain (WS + REST 60s poll)
  paper_broker.py        ← PaperBrokerAdapter (for paper trading mode)
  token_encryptor.py     ← AES-256-GCM encryption; key from ISecretsClient

src/core/infrastructure/data/
  candle_aggregator.py   ← in-memory OHLCV accumulator + 15-min crash-recovery via Redis snapshot
  option_chain_poller.py ← 60-second REST poll for full chain snapshot
```

**Acceptance criteria:**
- `KiteBroker.place_order()` maps INTRADAY→MIS, OVERNIGHT→NRML correctly.
- Kite access token survives restart: encrypt → store in DB → restart → decrypt → use.
- WebSocket reconnect logic: 5 attempts with exponential backoff; enters FAILED state correctly.
- Subscription batching: 100 `subscribe()` calls within 100ms → single broker request.
- `CandleAggregator` snapshots in-progress candle to Redis every 30 seconds; recovers on restart.
- `PaperBrokerAdapter.place_order()` simulates fill at LTP ± 0.05%.
- Zero Kite-specific symbols in domain layer (verified by `grep -r "kite\|zerodha" src/core/domain/`).

---

## Phase 9 — Market Regime Engine  ✓ COMPLETE

**Deliverables (done):**
- `config/regime.yaml` — all thresholds, no magic numbers in source
- `FeatureSnapshot`, `RegimeSnapshot` value objects
- `MarketRegimeEvaluatedEvent`, `MarketRegimeChangedEvent`
- `TrendLayer`, `VolatilityLayer`, `RegimeResolver` (8-rule matrix), `RegimeSmoother` (α-blend), `ConfidenceCalculator`
- `RegimeEvaluationUseCase` — pure stateless
- `MarketRegimeService` — subscribes to 15m candle, caches features, publishes events, persists
- `IMarketRegimeEngine` — extensibility interface for Phase 10 strategies
- `regime_router.py` — GET latest + history endpoints
- 89 tests passing

---

## Phase 9 (original) — Feature Engineering Service

**Goal:** Compute all technical indicators on every candle close and store in `market_features`.

**Reference docs:** Doc 09 (feature list), Doc 11 (feature domain events), Doc 18 (market_features schema).

**Deliverables:**
```
src/core/application/services/
  feature_engineering_service.py  ← consumes market_data.candle.closed; publishes features.technical.computed

src/core/domain/indicators/
  trend.py         ← EMA(9/21/50/200), ADX(14), Supertrend(10,3), MACD
  volatility.py    ← ATR(14), Bollinger Bands, BB Width Percentile
  volume.py        ← Relative Volume, OBV, Cumulative Delta
  vwap.py          ← Session VWAP with standard deviations
  options.py       ← PCR, Max Pain, IV Rank, IV Percentile, GEX
```

**Acceptance criteria:**
- All indicators produce identical values to a reference implementation (TA-Lib or pandas-ta) on the same input data.
- ADX(14) on a 15-minute candle series produces correct Wilder smoothing.
- EMA(200) requires exactly 200 candles before producing a valid reading; returns `None` before that.
- Feature computation for one instrument and one timeframe completes in < 50ms.
- `market_features` written asynchronously after computation; does not block the event bus reader.
- If tick data has a gap (missed candles), feature computation flags the affected timeframes as stale.

---

## Phase 10 — Event Bus Infrastructure

**Goal:** IEventBus with Redis Streams implementation. All 27 topics from Doc 11. Consumer groups wired.

**Reference docs:** Doc 11 (all of it).

**Deliverables:**
```
src/core/domain/interfaces/
  i_event_bus.py          ← IEventBus (publish, subscribe, ack, replay)

src/core/infrastructure/events/
  redis_event_bus.py      ← RedisStreamEventBus
  in_memory_event_bus.py  ← InMemoryEventBus (testing only)
  event_archive_service.py ← pre-drop hook → Parquet → object storage
  dlq_handler.py          ← dead letter queue monitoring and alerting
  message_envelope.py     ← canonical message envelope schema (Doc 11)
```

**Acceptance criteria:**
- `InMemoryEventBus` is used in all unit tests — no Redis required.
- `RedisStreamEventBus` is used in integration tests with a test Redis instance.
- MAXLEN configured for all 27 streams (Doc 11 table).
- Consumer group lag exposed as `event_bus_consumer_lag` Prometheus gauge.
- DLQ write triggers `system.health_check.failed` event within 1 second.
- Replay: `event_bus.replay(topic, from_id, to_id)` returns historical events from Redis stream.
- Idempotency: delivering same message twice to OMS consumer produces exactly one order.

---

## Phase 11 — Market Regime Engine

**Goal:** Two-layer regime detection producing RegimeState on every 15-minute candle close.

**Reference docs:** Doc 20 (all of it).

**Deliverables:**
```
src/core/application/services/
  regime_engine.py              ← Layer 1 (trend) + Layer 2 (volatility) → RegimeState

src/core/domain/regime/
  trend_detector.py             ← ADX + EMA + Supertrend + Breadth
  volatility_detector.py        ← VIX + ATR ratio + BB Width + IV Percentile
  regime_resolver.py            ← resolution priority matrix (Doc 20)
  regime_smoother.py            ← α-blending for smooth multiplier transitions
```

**Acceptance criteria:**
- ADX < 20 in a flat market produces SIDEWAYS with confidence >= 55.
- India VIX > 28 always produces HIGH_VOLATILITY as primary regime regardless of trend.
- Regime multiplier at first bar of new regime (stability = 0): effective multiplier = previous (no abrupt switch).
- Full multiplier transition requires >= 10 bars + confidence >= 90%.
- `features.regime.detected` published within 200ms of `market_data.candle.closed`.
- Unit tests cover all 8 regime resolution combinations from the priority matrix.

---

## Phase 10 — Strategy Framework

**Goal:** All scoring components from Doc 19/21 implementing `IScoreComponent`. Pure, stateless, deterministic. No AI, no sentiment at this stage.

**Reference docs:** Doc 19 (strategy definitions), Doc 21 (component formulas), Doc 16 (IScoreComponent interface), Doc 20 (regime integration).

**Deliverables:**
```
src/core/domain/strategies/
  i_score_component.py           ← IScoreComponent(ABC): evaluate(ctx) → ComponentResult
  score_context.py               ← ScoreContext value object (regime + features + market data)
  oi_buildup_component.py        ← OI quadrant + PCR + Max Pain + FII (Doc 21)
  trend_component.py             ← ADX gate + EMA + DI + Supertrend + MTF (Doc 21)
  option_chain_component.py      ← IV Percentile + Skew + GEX + OI walls (Doc 21)
  volume_component.py            ← Volume ratio + divergence + OBV + delta (Doc 21)
  vwap_component.py              ← Mode A (reversion) / Mode B (trend) (Doc 21)
  iv_analysis_component.py       ← IV Percentile + IVR + HV/IV ratio (Doc 21)
  momentum_modifier.py           ← confidence modifier only (+5 / 0 / -5)
  breakout_modifier.py           ← confidence modifier only (+5 / 0 / -8)

config/strategy.yaml             ← all component weights and thresholds
```

**Acceptance criteria:**
- Trend component returns `long_score=0, short_score=0` when ADX < 20. No override possible.
- VWAP component switches to Mode A when regime is SIDEWAYS, Mode B when TRENDING.
- Each component has `is_available=False` when data is missing — returns zero, never raises.
- All components independently unit-tested with mocked `ScoreContext` inputs.
- No component imports from another component.
- `IScoreComponent` is the only interface — future strategies register by implementing it.

---

## Phase 11 — Scoring Engine

**Goal:** Aggregate component scores into a single 0–100 signal score with regime multipliers, direction voting, and penalty calculations.

**Reference docs:** Doc 16 (updated), Doc 21 (Stage 2), Doc 19 (V1 weights).

**Deliverables:**
```
src/core/application/services/
  scoring_engine.py       ← direction vote + aggregation + regime multipliers + penalties → adjusted_score
  signal_dedup_service.py ← Redis dedup key; TTL enforcement

src/core/domain/scoring/
  direction_voter.py      ← weighted vote; direction_conviction calculation
  score_aggregator.py     ← weighted sum with regime multipliers; normalization
  penalty_calculator.py   ← staleness, conviction, hours, regime mismatch, expiry

config/scoring.yaml       ← V1 weights (already exists), penalty magnitudes
```

**Acceptance criteria:**
- Counter-regime LONG in TRENDING_BEARISH: score penalty −15.
- Stale OI component (> 5 min): −10 to score. NSE structural 3–5 min lag: no penalty.
- Signal with score 69: not forwarded to OMS (gate = 70).
- Direction conviction computed as weighted ratio; neutral when < 0.55 threshold.
- All weight values come from `config/scoring.yaml` — no literals in source.

---

## Phase 12 — Confidence Engine

**Goal:** 9-component confidence formula, calibration factor, and signal fingerprinting.

**Reference docs:** Doc 21 (Stage 3), Doc 16 (confidence model).

**Deliverables:**
```
src/core/application/services/
  confidence_engine.py    ← 9-component confidence; calibration factor; fingerprint lookup
  signal_expiry_worker.py ← 60-second poll; invalidation triggers; publishes signal.expired
  calibration_service.py  ← weekly Sunday calibration runner

src/core/domain/scoring/
  signal_fingerprint.py   ← SHA-256 of (regime, score_bucket, direction, top2, vix_bucket)
```

**Acceptance criteria:**
- Score of 100 with no penalties → base_confidence = 60 (ceiling verified).
- Confidence −20 for counter-regime signal.
- Calibration with synthetic over-confident data produces calibration_factor < 1.0.
- `NeutralSentimentProvider` used in place of AI at this phase — sentiment component returns 50.

---

## Phase 13 — Risk Engine

**Goal:** All 15 pre-trade checks + real-time portfolio monitor + position sizing.

**Reference docs:** Doc 17 (all of it).

**Deliverables:**
```
src/core/application/services/
  risk_engine.py              ← 15 checks serialized; any failure → REJECTED
  portfolio_monitor.py        ← 30-second async loop; graduated response; kill switch trigger
  position_sizer.py           ← ATR-based + fractional Kelly; min(ATR_lots, Kelly_lots)
  kill_switch_service.py      ← 6-step activation; integrated here (not a separate phase)
  dead_mans_switch.py         ← 120-second watchdog

src/core/domain/risk/
  risk_checks/
    kill_switch_check.py      ← check 1
    daily_loss_check.py
    weekly_loss_check.py
    drawdown_check.py
    open_positions_check.py
    symbol_concentration_check.py
    capital_concentration_check.py
    net_delta_check.py
    correlation_check.py
    margin_check.py
    risk_reward_check.py
    position_size_check.py
    order_rate_check.py
    theta_decay_check.py      ← warn-only
    vega_exposure_check.py
```

**Acceptance criteria:**
- All 15 checks in declared order; first failure stops evaluation.
- Every `RiskDecision` written to `risk_decisions` (append-only verified).
- Graduated response: at 50% daily loss → `position_size_multiplier = 0.5` in Redis.
- IAIProvider is NOT injectable into RiskEngine (DI container test).
- Kill switch activation sets Redis BEFORE any other step.

---

## Phase 14 — Signal Engine (Full Pipeline)

**Goal:** End-to-end pipeline integration. System generates real paper-mode signals.

**Reference docs:** Doc 21 (all), Doc 19, Doc 20, Doc 22 (OMS — paper mode only at this stage).

**Deliverables:**
```
src/core/application/services/
  signal_engine.py              ← orchestrates: strategy → score → confidence → risk → OMS
  signal_explanation_service.py ← template-based explanation (5 sections, no AI)
  signal_outcome_recorder.py    ← writes signal_performance_stats on position close
  oms.py                        ← paper-mode OMS; routes to PaperBrokerAdapter
  stoploss_manager.py           ← SL_MARKET within 2s of fill
  reconciliation_service.py     ← broker vs DB diff; rogue order → kill switch
```

**Acceptance criteria:**
- End-to-end: synthetic market data → regime → strategies → signal → risk approved → paper order.
- Signal with score 68: WEAK_SIGNAL; not forwarded to OMS.
- Signal explanation generated in < 10ms (template-based, no AI).
- Signal fingerprint deterministic: same inputs → same fingerprint on repeated runs.
- Full pipeline latency tick → paper order: P99 < 2s.

---

## Phase 15 — Dashboard

**Goal:** REST API + Next.js frontend. Operator monitoring interface for paper trading.

**Reference docs:** Doc 09 (dashboard pages).

**Backend deliverables:**
```
src/core/presentation/api/v1/
  signals_router.py
  orders_router.py
  positions_router.py
  health_router.py          ← GET /health/detailed (7 components)
  analytics_router.py
  market_router.py
  kill_switch_router.py
  websocket_router.py       ← WS /ws/live-feed
```

**Frontend (Next.js):**
```
frontend/
  src/app/
    page.tsx                ← Dashboard
    signals/page.tsx        ← Live Signals
    option-chain/page.tsx
    trades/page.tsx
    analytics/page.tsx
    health/page.tsx         ← Operator daily check — all green before market open
    settings/page.tsx       ← Read-only
```

**Acceptance criteria:**
- Health page shows 🔴 banner on any unhealthy component; blocks trading start.
- WebSocket feed delivers regime changes and signal events to UI within 500ms.
- All API endpoints return 401 without valid JWT.

---

## Phase 16 — Paper Trading Validation

**Goal:** 30 trading days proving the deterministic trading edge is real.

**Exit criteria for Phase 17+ (AI + Live Trading):**

| Metric | Required |
|--------|----------|
| System uptime during market hours | >= 99.5% |
| Zero unhandled exceptions in signal pipeline | Required |
| Signal win rate | >= 45% |
| Risk Engine correct rejection rate | 100% of manual test cases |
| Kill switch activation + recovery | Tested successfully |
| Stop-loss within 2s of fill | >= 99% |
| Paper P&L vs manual calculation | Within 0.1% |
| All architecture docs match implementation | Verified |
| Security checklist (Doc 23) | All items checked |

**30 trading days minimum. No exceptions. AI Layer is blocked until this passes.**

---

## Phase 17 — AI Layer

**Enabled only after Phase 16 paper trading validation is complete.**

**Goal:** Add AI-assisted sentiment as one optional input to the Scoring Engine.

**Reference docs:** Doc 15 (all of it), Doc 07.

**Rationale for deferral:** The deterministic trading edge (strategy + scoring + risk) must be
validated in isolation first. If signals are not profitable without AI, adding AI will not fix
the underlying strategy. If signals ARE profitable, AI sentiment is additive — not foundational.

**Deliverables:**
```
src/core/domain/interfaces/
  i_ai_provider.py             ← IAIProvider interface

src/core/infrastructure/ai/
  openai_provider.py
  anthropic_provider.py        ← stub
  neutral_sentiment_provider.py ← deterministic fallback; always active before Phase 17
  ai_provider_factory.py
  prompt_registry.py           ← versioned YAML prompts; fatal on missing file
  sentiment_cache.py           ← Redis; keyed by SHA-256(provider+prompt+text)
  cost_tracker.py              ← daily token budget enforcement

src/core/application/services/
  news_intelligence_service.py ← News API → AI classify → sentiment score
```

**AI is strictly limited to:**
- Providing a score to `sentiment_component.py` in the Scoring Engine.
- News summarization and classification.
- Market summary generation for the Dashboard.

**AI is FOREVER FORBIDDEN from:**
- Order placement of any kind
- Risk management decisions
- Position sizing
- Stop loss calculation
- Overriding any output from the deterministic pipeline
- Being injected into: OMS, RiskEngine, PositionSizer, KillSwitchService

**Acceptance criteria:**
- Primary AI provider unavailable → automatic fallback → NeutralSentimentProvider.
- `NeutralSentimentProvider` returns `is_fallback=True`; confidence reduced by 5.
- Daily budget at 100%: all calls return NeutralSentimentProvider.
- AI NOT injectable into OMS/Risk/PositionSizer/KillSwitch (DI container test).
- System operates correctly with AI disabled — NeutralSentimentProvider is always the baseline.

---

## Phase 18 — Live Trading

**Reference docs:** Doc 08 Phase 21.

**Go-live prerequisites:**
1. All Phase 16 exit criteria met and documented.
2. Phase 17 AI layer validated in paper mode (optional but strongly recommended).
3. Security checklist (Doc 23) complete.
4. Incident response runbook written.
5. Risk limits set to 50% of configured limits for first 5 live days.
6. Dedicated monitoring session by a human operator for first 5 live trading days.
7. Kill switch tested manually on live environment before first order.

---

## Phase 12 — Strategy Layer (original — superseded)

**Goal:** All 7 scoring components from Doc 19/21, each implementing IScoreComponent.

**Reference docs:** Doc 19 (strategy definitions), Doc 21 (component formulas), Doc 16 (IScoreComponent interface).

**Deliverables:**
```
src/core/domain/strategies/
  i_score_component.py           ← IScoreComponent interface
  oi_buildup_component.py        ← OI quadrant classification + PCR + Max Pain + FII (Doc 21)
  trend_component.py             ← ADX gate + EMA + DI + Supertrend + MTF (Doc 21)
  option_chain_component.py      ← IV Percentile + Skew + GEX + OI walls (Doc 21)
  volume_component.py            ← Volume ratio + divergence + OBV + delta (Doc 21)
  vwap_component.py              ← Mode A (reversion) / Mode B (trend) (Doc 21)
  sentiment_component.py         ← IAIProvider result → score mapping (Doc 21)
  iv_analysis_component.py       ← IV Percentile + IVR + HV/IV ratio (Doc 21)
  momentum_modifier.py           ← confidence modifier only (+5 / 0 / -5)
  breakout_modifier.py           ← confidence modifier only (+5 / 0 / -8)
```

**Acceptance criteria:**
- Trend component returns `long_score=0, short_score=0` when ADX < 20. No override possible.
- VWAP component switches to Mode A when regime is SIDEWAYS, Mode B when TRENDING.
- Touch count degradation in Mode A: 3rd touch of same VWAP level = score × 0.50.
- OI quadrant classification: all 4 quadrants correctly classified with test fixtures.
- Each component implements `is_available=False` when data is missing (does not raise; returns zero).
- All 7 components individually unit-tested with mocked ScoreContext inputs.
- No component imports from another component (strictly independent).

---

## Phase 13 — Signal Scoring & Confidence Engine

**Goal:** Score aggregation, regime multipliers, direction voting, penalties, and confidence computation.

**Reference docs:** Doc 16 (updated), Doc 21 (Stage 2 + Stage 3).

**Deliverables:**
```
src/core/application/services/
  scoring_engine.py       ← direction vote + aggregation + regime multipliers + penalties → adjusted_score
  confidence_engine.py    ← 9-component confidence formula; calibration factor; fingerprint lookup
  signal_dedup_service.py ← Redis dedup key; TTL enforcement
  signal_expiry_worker.py ← 60-second poll; invalidation triggers; publishes signal.expired

src/core/domain/scoring/
  direction_voter.py      ← weighted vote; direction_conviction calculation
  score_aggregator.py     ← weighted sum with regime multipliers; normalization
  penalty_calculator.py   ← 5 penalty types (staleness, conviction, hours, regime, expiry)
  signal_fingerprint.py   ← SHA-256 of (regime, score_bucket, direction, top2, vix_bucket)
```

**Acceptance criteria:**
- Score of 100 with no penalties produces base_confidence = 60 (ceiling verified by test).
- Counter-regime LONG signal in TRENDING_BEARISH: score penalty −15 + confidence −20.
- Stale OI component (> 5 min): −10 to score, −10 to confidence. NSE structural 3–5 min lag: no penalty.
- Signal with score 69 at confidence 80: not forwarded to OMS (score gate = 70).
- Dedup: two identical signals within 30 minutes → second suppressed; first's score updated if delta > 5.
- Weekly calibration (tested with synthetic data): overconfident bucket gets multiplier < 1.0.

---

## Phase 14 — Portfolio Risk Engine

**Goal:** All 15 pre-trade checks + real-time portfolio monitor + position sizing.

**Reference docs:** Doc 17 (all of it).

**Deliverables:**
```
src/core/application/services/
  risk_engine.py              ← pre-trade check orchestrator (15 checks, serialized)
  portfolio_monitor.py        ← 30-second async loop; graduated response; kill switch trigger
  position_sizer.py           ← ATR-based + fractional Kelly; min(ATR_lots, Kelly_lots)
  greeks_calculator.py        ← Black-Scholes delta/gamma/theta/vega; r=0.065 (configurable)
  correlation_service.py      ← 60-day rolling correlation matrix; daily update at 07:45

src/core/domain/risk/
  risk_checks/
    kill_switch_check.py
    daily_loss_check.py
    weekly_loss_check.py
    drawdown_check.py
    open_positions_check.py
    symbol_concentration_check.py
    capital_concentration_check.py
    net_delta_check.py
    correlation_check.py
    margin_check.py
    risk_reward_check.py
    position_size_check.py
    order_rate_check.py
    theta_decay_check.py    ← warn-only (check 14)
    vega_exposure_check.py
```

**Acceptance criteria:**
- All 15 checks executed in declared order; first failure stops evaluation.
- Every `RiskDecision` written to `risk_decisions` table (append-only verified).
- ATR sizing: `Capital_at_Risk / (Stop_Distance × lot_size)` matches manual calculation to nearest lot.
- Fractional Kelly = 0.25 × (win_rate − (1−win_rate)/win_loss_ratio); negative Kelly → 0 lots.
- Graduated response: at 50% daily loss consumed → `position_size_multiplier = 0.5` in Redis within 1 cycle.
- Risk engine P99 < 200ms including margin API call (integration test with mock broker returning in 100ms).
- Weekly loss tracks rolling 5 trading days (not calendar week) — test spanning a Monday.

---

## Phase 15 — Kill Switch System

**Goal:** Atomic kill switch with 6-step activation, Dead Man's Switch, and full recovery flow.

**Reference docs:** Doc 14 (all of it, including audit fixes).

**Deliverables:**
```
src/core/application/services/
  kill_switch_service.py   ← 6-step activation; cancellation bypass rule enforced
  heartbeat_service.py     ← 30-second heartbeat publisher
  dead_mans_switch.py      ← 120-second watchdog; gated on kill_switch_active == False

src/core/presentation/api/v1/
  kill_switch_router.py    ← POST /activate, POST /deactivate; IP allowlist; override_loss_check
```

**Acceptance criteria:**
- Kill switch activation sets Redis key BEFORE any other step.
- Process crash after Redis write but before DB write: restart reads kill switch from Redis (blocked state).
- OMS `place_order()` blocked after kill switch; `cancel_order()` NOT blocked.
- `cancel_all_orders()` completes within 15 seconds of activation (3 retries × 3s intervals + buffer).
- DMS does NOT re-trigger when kill switch is already active.
- Same-day deactivation with `override_loss_check=True`: platform resumes in PAPER mode only.
- Integration test: activate kill switch → verify OMS blocks new orders → verify cancellations succeed → deactivate → verify OMS resumes.
- Chaos test: kill the process after Redis write (Step 1) + before kill_switch_events write (Step 5) → restart → blocked state confirmed.

---

## Phase 16 — OMS

**Goal:** Full order lifecycle management with paper mode, stop-loss automation, and reconciliation.

**Reference docs:** Doc 22 (all of it).

**Deliverables:**
```
src/core/application/services/
  oms.py                    ← order lifecycle; pre-submission checks; state machine
  stoploss_manager.py       ← places SL_MARKET within 2s of fill; monitors SL orders
  target_manager.py         ← places LIMIT at T1; partial scale logic
  reconciliation_service.py ← broker vs DB diff; rogue order detection → kill switch

src/core/infrastructure/broker/
  paper_broker.py           ← tick-driven fill simulation (already in Phase 8 stub)
```

**Acceptance criteria:**
- signal.risk.approved → broker.place_order() within 500ms P99.
- Stop-loss order placed within 2 seconds of fill confirmation.
- Rogue order detected (order at broker not in DB) → kill switch activates within 30 seconds.
- Paper mode: all orders simulated; P&L tracked identically to live.
- Idempotency: same signal_id received twice → one order in DB (second is idempotency-blocked).
- Partial fill tracked: `filled_quantity` updated on every partial; `FILLED` state only when `filled_quantity == quantity`.
- 30-day retention on `orders` table verified via retention policy test.

---

## Phase 17 — AI Provider Abstraction

**Goal:** IAIProvider with OpenAI, fallback chain, caching, rate limiting, cost controls.

**Reference docs:** Doc 15 (all of it).

**Deliverables:**
```
src/core/domain/interfaces/
  i_ai_provider.py             ← IAIProvider interface (Doc 15)

src/core/infrastructure/ai/
  openai_provider.py
  anthropic_provider.py        ← stub (future)
  gemini_provider.py           ← stub (future)
  ollama_provider.py           ← for local testing only
  neutral_sentiment_provider.py ← deterministic fallback
  ai_provider_factory.py       ← provider selection from config
  prompt_registry.py           ← loads versioned YAML prompts; fatal on missing file
  sentiment_cache.py           ← Redis keyed by SHA-256(provider+prompt_version+text)
  cost_tracker.py              ← token counting; daily budget enforcement
```

**Acceptance criteria:**
- Primary provider unavailable → automatic fallback to next provider → NeutralSentimentProvider.
- `NeutralSentimentProvider` returns `is_fallback=True`; scoring engine reduces confidence by 5.
- Cache hit: AI call not made; latency < 2ms (Redis read only).
- Daily budget at 80%: model downgraded to cheapest variant.
- Daily budget at 100%: all calls return NeutralSentimentProvider; CRITICAL log on each.
- AI is NOT injectable into OMS, RiskEngine, PositionSizer, KillSwitchService (DI container test).
- All AI responses validated by Pydantic before use; 3 consecutive failures → NeutralSentimentProvider.

---

## Phase 18 — Signal Engine (Full Pipeline Integration)

**Goal:** End-to-end signal generation wiring all stages together. The system generates real signals.

**Reference docs:** Doc 21 (all of it), Doc 19 (strategy specifics), Doc 20 (regime integration).

**Deliverables:**
```
src/core/application/services/
  signal_engine.py           ← orchestrates: strategy eval → score → confidence → risk → OMS
  signal_explanation_service.py ← template-based explanation (5 sections, Doc 21)
  signal_outcome_recorder.py ← writes to signal_performance_stats on position close
  calibration_service.py     ← weekly Sunday 05:00 IST calibration runner
```

**Acceptance criteria:**
- End-to-end test: inject synthetic market data → regime detected → strategies evaluated → signal generated → risk approved → OMS receives order.
- Signal with score 68: WEAK_SIGNAL state; not forwarded to OMS.
- Signal with ADX = 15: Trend component returns 0; signal can still pass if other components strong.
- Signal explanation generated in < 10ms (template-based, no AI).
- Signal fingerprint matches on re-run with same inputs (determinism test).
- `signal_performance_stats` written correctly after paper-mode fill + position close.
- Calibration with synthetic over-confident data produces calibration_factor < 1.0.
- Full pipeline latency tick → broker: P99 < 2s (end-to-end integration test with mock broker).

---

## Phase 19 — Dashboard API

---

## Phase 19.5 — Frontend Application

**Goal:** Browser UI that consumes Phase 19 REST API and WebSocket feed. Must be complete before Paper Trading begins — operators need a real monitoring interface during Phase 20 validation.

**Stack (locked):**

| Technology | Version | Role |
|---|---|---|
| Next.js | 15 (App Router) | Framework — SSR/SSG/Static |
| TypeScript | 5.x strict mode | Type safety |
| TailwindCSS | 3.x | Styling |
| shadcn/ui | latest | Component library |
| TanStack Query | v5 | Server state — REST polling |
| WebSocket | Native browser API | Live feed from `/ws/live-feed` |
| Recharts | 2.x | Charts (P&L, regime, win rate) |

**Location:** `frontend/` at monorepo root. Zero Python imports. Communicates exclusively via REST API and WebSocket.

**Architecture rule:** `frontend/` is a separate deployment unit. It is NOT part of the Python Clean Architecture layers. It is a consumer of the API, not an inner layer.

**Routes (locked):**

| Route | Page Title | Description |
|---|---|---|
| `/` | Dashboard | Market overview — regime badge, VIX gauge, top 5 live signals, P&L summary card |
| `/signals` | Live Signals | Full signal table with state, score, confidence, direction; click for detail drawer |
| `/option-chain` | Live Option Chain | Strike × expiry matrix; OI, IV, PCR; auto-refreshes every 5s via WebSocket |
| `/trades` | Trade Journal | Orders list, open positions, closed trades, realized P&L; sortable/filterable |
| `/analytics` | Performance Analytics | P&L chart (Recharts), win rate gauge, regime breakdown bar chart, signal accuracy heatmap |
| `/news` | Market News | AI-analyzed news cards with sentiment badge; per-symbol filtering |
| `/health` | System Health | Component status grid (see below) — used daily by operator |
| `/settings` | Configuration | Read-only view of active config: risk limits, scoring weights, AI provider, environment |

**Health Page — Component Status Grid:**

This page is the operator's daily starting point. Before market open, every component must show green.

```
┌─────────────────────────────────────────────────────────────────┐
│  System Health                          Last checked: 09:14:32  │
├─────────────────────────────────────────────────────────────────┤
│  Kite API          🟢 Connected    Latency: 12ms                │
│  NSE API           🟢 Connected    Last tick: 2s ago            │
│  OpenAI            🟢 Available    Budget: ₹180 / ₹400 today   │
│  Redis             🟢 Connected    Memory: 42MB                 │
│  TimescaleDB       🟢 Connected    Pool: 4/10 connections       │
│  WebSocket         🟢 Active       Subscriptions: 47            │
│  Instrument Master 🟢 Loaded       12,847 instruments (today)   │
├─────────────────────────────────────────────────────────────────┤
│  Kill Switch       ⚪ INACTIVE                                  │
│  Trading Mode      📄 PAPER                                     │
│  Market Session    🟡 PRE-MARKET (opens in 14m)                │
└─────────────────────────────────────────────────────────────────┘
```

Status indicator rules:
- 🟢 Green — component healthy and responsive
- 🟡 Yellow — degraded (high latency, partial data, fallback active)
- 🔴 Red — unreachable or failing health check — trading MUST NOT start
- ⚪ Grey — not applicable / explicitly inactive

The Health page polls `GET /api/v1/health/detailed` every 10 seconds. On any 🔴 component, the page header turns red and a banner appears: **"SYSTEM NOT READY — do not start trading"**.

**Deliverables:**
```
frontend/
├── src/
│   ├── app/                         ← Next.js App Router
│   │   ├── layout.tsx               ← Root layout with sidebar nav
│   │   ├── page.tsx                 ← / Dashboard
│   │   ├── signals/
│   │   │   └── page.tsx             ← /signals Live Signals
│   │   ├── option-chain/
│   │   │   └── page.tsx             ← /option-chain Live Option Chain
│   │   ├── trades/
│   │   │   └── page.tsx             ← /trades Trade Journal
│   │   ├── analytics/
│   │   │   └── page.tsx             ← /analytics Performance Analytics
│   │   ├── news/
│   │   │   └── page.tsx             ← /news Market News + AI Sentiment
│   │   ├── health/
│   │   │   └── page.tsx             ← /health System Health (daily operator check)
│   │   └── settings/
│   │       └── page.tsx             ← /settings Configuration (read-only)
│   ├── components/
│   │   ├── ui/                      ← shadcn/ui primitives (Button, Card, Badge, Table…)
│   │   ├── charts/                  ← Recharts wrappers (typed props, responsive)
│   │   ├── signals/                 ← SignalCard, SignalTable, SignalDetailDrawer
│   │   ├── health/                  ← ComponentStatusRow, HealthGrid, StatusBadge
│   │   ├── market/                  ← RegimeBadge, VixGauge, MarketSessionBanner
│   │   └── shared/                  ← Sidebar, TopBar, ThemeProvider, ErrorBoundary
│   ├── lib/
│   │   ├── api/                     ← Typed fetch wrappers per endpoint group
│   │   │   ├── health.ts            ← getHealthDetailed()
│   │   │   ├── signals.ts           ← getSignals(), getSignal(id)
│   │   │   ├── trades.ts            ← getOrders(), getPositions()
│   │   │   ├── analytics.ts         ← getPnl(), getWinRate()
│   │   │   ├── market.ts            ← getOptionChain(), getLtp()
│   │   │   └── news.ts              ← getNewsItems()
│   │   └── websocket/
│   │       ├── client.ts            ← WebSocket singleton with reconnect + backoff
│   │       └── useWebSocket.ts      ← hook; dispatches typed events to subscribers
│   ├── hooks/
│   │   ├── useSignals.ts            ← TanStack Query, 30s refetch
│   │   ├── usePositions.ts          ← TanStack Query, 10s refetch
│   │   ├── useHealth.ts             ← TanStack Query, 10s refetch
│   │   ├── useOptionChain.ts        ← TanStack Query + WebSocket merge
│   │   └── useLiveFeed.ts           ← WebSocket live events → React state
│   └── types/
│       ├── api.ts                   ← All API response types (matches FastAPI OpenAPI schema)
│       ├── signals.ts               ← SignalState, SignalType, Signal
│       ├── health.ts                ← ComponentHealth, HealthStatus, SystemHealth
│       └── market.ts                ← MarketRegime, OptionChainRow, Tick
├── public/
├── package.json
├── tsconfig.json                    ← strict: true, noUncheckedIndexedAccess: true
├── tailwind.config.ts
├── next.config.ts
├── components.json                  ← shadcn/ui config
└── .env.local.example
```

**Acceptance criteria:**
- `npm run build` completes with zero TypeScript errors (`tsc --noEmit`).
- `npm run lint` passes with zero errors.
- All 8 pages render without runtime errors in browser.
- Health page polls every 10 seconds; shows 🔴 banner when any component unhealthy.
- WebSocket client reconnects with exponential backoff (max 5 attempts, then shows error state).
- TanStack Query: signals refresh every 30s, positions every 10s, health every 10s.
- All API calls go through `lib/api/` — no direct `fetch()` in page or component files.
- Settings page is read-only — no forms that modify backend configuration.
- `types/` kept in sync with FastAPI OpenAPI schema (verified manually or via codegen).
- No Python imports, no `src/` imports — `frontend/` is fully self-contained.
- `frontend/` has its own CI job in `.github/workflows/ci.yml` (build + lint + type check).

---

## Phase 19 — Dashboard API

**Goal:** REST API and WebSocket feed for the dashboard. Read-heavy. Uses read replica.

**Reference docs:** Doc 09 (dashboard pages: Market Overview, Signals, Option Chain, Trades, Sentiment, Health Checks, Analytics).

**Deliverables:**
```
src/core/presentation/api/v1/
  signals_router.py         ← GET /signals, GET /signals/{id}
  orders_router.py          ← GET /orders, GET /orders/{id}
  positions_router.py       ← GET /positions
  health_router.py          ← GET /health, GET /health/detailed (all 7 component checks)
  analytics_router.py       ← GET /analytics/pnl, /analytics/signals, /analytics/regime
  market_router.py          ← GET /market/option-chain, /market/ltp
  kill_switch_router.py     ← (moved from Phase 15 stub; now complete)
  websocket_router.py       ← WS /ws/live-feed (signals, orders, positions real-time)
```

**Acceptance criteria:**
- All read endpoints query the read replica; verified by checking which SQLAlchemy engine was called.
- `GET /health/detailed` returns status for: Kite, NSE, OpenAI, PostgreSQL, Redis, WebSocket, InstrumentMaster.
- WebSocket feed: signal.risk.approved event received by dashboard within 500ms.
- All endpoints return 401 for unauthenticated requests.
- Kill switch endpoints return 403 from non-allowlisted IP.
- API rate limiting: 100 req/min per JWT; 1,000 req/min aggregate.
- OpenAPI schema generated and validates against all response models.

---

## Phase 20 — Paper Trading Validation

**Goal:** 30 trading days of paper trading to validate signal quality and system stability.

**Reference docs:** Doc 08 Phase 20.

**Exit criteria for Phase 21 (Live Trading):**

| Metric | Minimum Required |
|--------|-----------------|
| System uptime during market hours | >= 99.5% |
| Zero unhandled exceptions in signal pipeline | Required |
| Signal win rate | >= 45% (> random; no expectation of profitability in paper) |
| Risk engine correctly rejecting signals | 100% of manual test cases pass |
| Kill switch activation + recovery test | Completed successfully |
| Stop-loss orders placed within 2s | >= 99% of fills |
| Paper P&L tracked correctly | Matches manual calculation within 0.1% |
| All 23 architecture documents match implementation | Verified by lead engineer |
| Security checklist (Doc 23 Section 10) | All 14 items checked |

Paper trading runs for a **minimum of 30 trading days**. No exceptions. Live trading is blocked until all exit criteria are met.

---

## Phase 21 — Live Trading

**Reference docs:** Doc 08 Phase 21.

**Go-live prerequisites:**
1. All Phase 20 exit criteria met and documented.
2. Security checklist (Doc 23) complete.
3. Incident response runbook written (who to call, how to manually close positions, broker terminal access confirmed).
4. Risk limits set conservatively for first 5 live days: 50% of configured limits.
5. Dedicated monitoring session by a human operator for the first 5 live trading days.
6. Kill switch tested manually on the live environment (activate → deactivate) before first order.

---

## Development Standards (All Phases)

These rules apply from Phase 1 onward. A phase is **not complete** until all apply:

| Standard | Rule |
|----------|------|
| Type hints | `mypy --strict` passes with zero errors |
| Tests | Every public method has unit tests; 80%+ coverage per module |
| Lint | `ruff check` passes with zero errors |
| No TODOs | Zero `# TODO`, `# FIXME`, `# HACK` in merged code |
| No magic values | Zero numeric or string literals in business logic (all in config) |
| No AI in forbidden services | DI container test verifies IAIProvider not registered in OMS/Risk/Kill Switch |
| Secrets | `git grep -r "password\s*=" src/` returns zero matches |
| Docs match code | Any deviation from architecture docs requires a doc update in the same PR |
| Signal path | Every exception in the signal pipeline is caught, logged, and published to the event bus |

---

*This plan is derived from the post-audit architecture. All conflicts identified in the architecture audit have been resolved in Docs 14, 16, 18, 22, and 23 before this plan was written.*
