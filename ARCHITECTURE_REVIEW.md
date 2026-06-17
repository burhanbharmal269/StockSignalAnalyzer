# Architecture Review — StockSignalAnalyzer

**Reviewer Role:** Principal Software Architect / Quant Developer / Trading Systems Engineer  
**Review Date:** 2026-06-11  
**Scope:** All documents under `/docs` (00–10)  
**Platform Target:** Institutional-grade Indian FnO Trading Platform (NSE)

---

## Executive Summary

The documentation establishes a well-intentioned layered architecture with sound principles (Clean Architecture, DDD, SOLID, event-driven design). The phased roadmap is logical and the forbidden-practices list prevents the most common anti-patterns. However, the design exists almost entirely at the conceptual level. At current documentation depth, critical production concerns — streaming data, time-series storage, real-time risk, broker WebSocket lifecycle, and observability infrastructure — are either absent or underspecified to the point of being unimplementable without significant rework decisions later. The findings below address each requested dimension in priority order.

---

## 1. Missing Components

### 1.1 Event Bus
The system declares "Event Driven Design" as a core principle (00, 09) but specifies no event bus. The pipeline in `02_SYSTEM_FLOW.md` is a linear, implicitly synchronous chain. Without an event bus, every stage is tightly coupled via direct function calls, making independent scaling, replay, and fan-out impossible.

**Required Decision:** Choose and document one: Redis Streams, RabbitMQ, Kafka, or an in-process `asyncio.Queue` bus for Phase 1 with an upgrade path.

### 1.2 WebSocket / Streaming Data Manager
F&O trading requires tick-level data from the Kite WebSocket (KiteTicker). There is no specification for:
- WebSocket connection lifecycle (connect, subscribe, reconnect, heartbeat)
- Tick message normalization and fan-out to consumers
- Backpressure handling when consumers are slower than the data feed
- Reconnection strategy with exponential backoff

This is one of the highest-risk missing components. Kite's WebSocket disconnects frequently under poor network conditions.

### 1.3 Expiry Calendar and Instrument Master
There is no `instrument_master` table or `expiry_calendar` component. For FnO:
- Lot sizes change with SEBI circulars
- Expiry dates (weekly, monthly) drive strike selection and position management
- Roll-over logic requires knowing current vs next expiry
- Max Pain and PCR calculations require the full option chain for the correct expiry

Without this, the Feature Engineering phase (Phase 9) and Signal Engine (Phase 16) cannot function correctly.

### 1.4 Kill Switch / Emergency Stop
Mentioned in Phase 21 requirements but never architecturally defined. This is non-negotiable for live trading. It must be:
- Accessible via a single endpoint or hotkey
- Cancel all open orders at broker level immediately
- Block all new order submissions system-wide
- Persist its state so a process restart does not re-enable trading
- Trigger automatically when daily/weekly loss limits are breached

### 1.5 Async Task Queue
No background task infrastructure is specified. The following work **must not** run in the request or tick-handler path:
- OpenAI API calls (500ms–2s latency)
- Feature engineering over long lookback windows
- End-of-day report generation
- Backtesting runs

**Required:** Celery + Redis, or `asyncio`-native task queues with worker pools. Specify which.

### 1.6 Alert and Notification Subsystem
Live trading (Phase 21) lists "Alerts" but no specification exists. A trading platform needs:
- Signal fired alert (Telegram/WhatsApp Business API preferred for Indian traders)
- Order filled / rejected / cancelled alert
- Risk limit breached alert
- System health degradation alert
- Daily P&L summary push

This must be an `INotifier` interface with at minimum a Telegram adapter.

### 1.7 Position Reconciliation Service
After a broker WebSocket disconnect or process restart, the OMS internal state and the broker's actual positions may diverge. A reconciliation service must:
- Fetch positions from broker on startup and after reconnect
- Diff against OMS state
- Reconcile or alert on discrepancies
- Never allow the risk engine to operate on stale position data

### 1.8 Rate Limiter for External APIs
Kite Connect has explicit rate limits (3 req/s for historical data, 10 req/s for orders). OpenAI has RPM/TPM limits. No rate limiter is specified anywhere in the architecture. Without it, the system will receive `429` errors under normal operation.

### 1.9 Secret Management
`.env` files are listed as the secrets mechanism. For a trading platform where broker tokens and API keys are stored, this is insufficient. A secret manager (HashiCorp Vault, AWS Secrets Manager, or at minimum `python-dotenv` with an encrypted secrets file) must be specified with a rotation strategy.

### 1.10 Options Strike and Expiry Selector
After the signal engine generates a directional view (BUY/SELL on underlying), there is no component that decides:
- Which expiry to trade (nearest, next, or specific DTE)
- Which strike (ATM, ITM delta-targeting, or OTM)
- CE vs PE selection
- Spread construction (naked vs defined-risk)

This is a major functional gap for an FnO platform.

---

## 2. Scalability Concerns

### 2.1 Synchronous Linear Pipeline
The pipeline in `02_SYSTEM_FLOW.md` lists 14 sequential stages. At tick frequency (every 200ms for Kite), each pipeline execution must complete in under 200ms or ticks will queue up and latency will compound. Stages like News Sentiment (AI call) and Market Regime (multi-indicator computation) cannot meet this budget synchronously.

**Required Architecture:** Decouple time-sensitive stages (tick ingestion, LTP update, OMS) from slower analytical stages (AI sentiment, regime detection, feature engineering) using the event bus. Define latency budgets per stage.

### 2.2 PostgreSQL for Time-Series Workloads
`market_data`, `option_chain`, and `market_features` are time-series tables. A liquid FnO instrument like Nifty50 generates ~1,500 ticks/day on Kite. Across 50 instruments, that is 75,000 rows/day in `market_data` alone. Over one year that is ~19 million rows. Range queries (`WHERE timestamp BETWEEN ...`) on a vanilla PostgreSQL table without partitioning will degrade significantly past 50 million rows.

**Required:** Either enable TimescaleDB extension (hypertables with automatic time-based chunks) or adopt a purpose-built time-series store (QuestDB for extreme write throughput, InfluxDB for ecosystem). This decision must be made before Phase 4.

### 2.3 No Read/Write Separation
All OLTP (order writes, signal writes) and OLAP (backtesting queries, analytics, P&L aggregation) go to the same PostgreSQL instance. Analytical queries with large scans will contend with low-latency order writes.

**Required:** Define a read replica strategy or a separate analytics schema with materialized views refreshed on a schedule.

### 2.4 No Horizontal Scaling Path for Signal Generation
The strategy framework (Phase 12) requires evaluating 5+ strategies per symbol. If coverage expands to 50 FnO instruments, that is 250+ strategy evaluations per tick cycle. There is no specification for parallelizing strategy evaluation (multi-process pool, worker partitioning by symbol).

### 2.5 AI Call in Critical Path
`02_SYSTEM_FLOW.md` places News Sentiment between Feature Engineering and Market Regime — both of which feed the Strategy Engine. If OpenAI is slow or unavailable, the entire pipeline stalls. AI calls must be decoupled from the synchronous signal path and run asynchronously with cached results.

### 2.6 Option Chain Volume
A full NSE option chain snapshot for a single expiry of Nifty50 contains approximately 500 strike-option records. Storing full snapshots every minute across multiple instruments and expiries generates tens of thousands of rows per minute. No compression, columnar storage, or summarization strategy is defined.

---

## 3. Security Concerns

### 3.1 Default Admin Credentials (Critical)
`Phase 6` specifies `admin/admin` as default credentials. This is a P0 security vulnerability. Any deployment accessible on a network is immediately compromised. At minimum:
- Force password change on first login
- Generate a random credential at install time
- Enforce password complexity requirements

This must be fixed before any non-localhost deployment.

### 3.2 Broker Token Exposure
Broker session tokens (Kite access tokens) are stored in the `broker_sessions` table. If the database is compromised, all broker tokens are immediately usable for fund withdrawals and trade manipulation. Tokens must be:
- Encrypted at rest using a key stored outside the database (application-level encryption)
- Short-lived with automatic revocation on logout
- Audited on every use

### 3.3 No Token Revocation / Refresh Strategy
JWT is specified but no refresh token rotation, token revocation list (Redis-backed), or short expiry policy is defined. A compromised JWT remains valid until expiry. For a trading platform, token lifetime should be ≤15 minutes with silent refresh.

### 3.4 RBAC Deferred Without Interim ACL
RBAC is listed as "future" while the current design grants all authenticated users identical access. Even in Phase 1, a minimum two-role model (admin, read-only viewer) is required to safely share dashboard access.

### 3.5 Audit Log Integrity
`audit_logs` is a regular writable table accessible via the application DB user. An attacker who compromises the application can delete audit evidence. Audit logs should be:
- Written via a write-only DB role that cannot `UPDATE` or `DELETE`
- Ideally append-only (PostgreSQL's `pg_audit` extension or a separate immutable log store)

### 3.6 No Transport Security Specification
No TLS/HTTPS requirement is stated. The dashboard and API must enforce HTTPS. Broker WebSocket connections must use `wss://`. HTTP-only deployments of a trading platform are unacceptable.

### 3.7 Input Validation Gap
Pydantic models are implied for request validation, but no explicit validation boundary is documented. Injection vectors (symbol name injection, SQL via ORM misuse, path traversal in log file references) are not addressed.

### 3.8 CORS Policy Absent
The dashboard API has no CORS policy specification. An open CORS policy on a trading API allows cross-site request forgery from any malicious page the user visits.

---

## 4. Performance Bottlenecks

### 4.1 Feature Engineering Recomputation
Technical indicators (RSI, EMA, MACD, ATR, etc.) are recalculated from scratch on every signal cycle. For a 200-period EMA, this means summing 200 candles every tick. Incremental computation (store last EMA value + apply new candle formula) reduces this to O(1) per tick. This design decision must be explicit in the Feature Engineering specification.

### 4.2 Database Connection Pool Undersized
No connection pool configuration is specified. SQLAlchemy's default pool size of 5 is insufficient for a system that has concurrent strategy evaluators, OMS writers, market data writers, and API handlers all needing DB access simultaneously. Define pool size, max overflow, and timeout for each service context.

### 4.3 N+1 Query Risk in Repository Layer
The Repository Pattern is mandated but no eager loading strategy is defined. Loading a `Signal` entity that joins to `Strategy`, `MarketSnapshot`, and `RiskDecision` via lazy loading produces N+1 queries. Every repository method that returns collections must document its join/prefetch strategy.

### 4.4 No Query Explain Budget
No policy exists for maximum acceptable query execution time. Slow query logging should be enabled in PostgreSQL (`log_min_duration_statement`) with a 100ms threshold, and a process for reviewing and adding indexes must be defined.

### 4.5 No Table Partitioning
`market_data`, `option_chain`, and `signals` will grow unboundedly. Without range partitioning by date, maintenance operations (VACUUM, index rebuilds) will lock the entire table. Partition-by-month is the minimum requirement.

### 4.6 Synchronous Broker Order Placement
If `place_order()` is called synchronously in the OMS → Broker path, and the broker API takes 200–500ms to respond, the OMS is blocked for that duration. Order submission must be async with callback/webhook or polling for fill status.

### 4.7 No Caching Layer Design
Redis is referenced in health checks but its usage is not designed. The following data should be cached in Redis with explicit TTLs:
- Option chain snapshots (TTL: 30 seconds for live, 0 for backtesting)
- LTP per instrument (TTL: tick interval)
- AI sentiment results keyed by news hash (TTL: 1 hour)
- Broker session tokens (TTL: token expiry)
- Computed market features (TTL: candle interval)

---

## 5. Database Improvements

### 5.1 Missing Tables

| Table | Purpose |
|---|---|
| `instruments` | Symbol master: lot size, tick size, expiry, segment, ISIN |
| `expiry_calendar` | NSE expiry dates by series (weekly/monthly) |
| `strategies` | Strategy registry with version, weights, enabled flag |
| `strategy_performance` | Historical win rate, accuracy, sharpe per strategy per regime |
| `risk_parameters` | Configurable risk limits (daily loss, max positions, sizing) per user |
| `backtest_runs` | Backtesting session metadata (parameters, date range, result summary) |
| `backtest_trades` | Simulated trades from backtest runs |
| `alerts` | Alert configurations and delivery history |
| `notifications` | Notification log (channel, recipient, content, delivery status) |
| `paper_trades` | Simulated orders and fills for paper trading |
| `signal_events` | Immutable event log for every state transition of a signal |
| `order_events` | Immutable event log for every order state transition |

### 5.2 TimescaleDB Adoption
`market_data`, `option_chain`, and `market_features` must be TimescaleDB hypertables. This provides:
- Automatic time-based chunking
- Chunk-level compression (up to 95% space reduction for tick data)
- Continuous aggregates for OHLCV rollups without scanning raw ticks
- Automatic data retention policies

This decision should be made in Phase 4 before any migration is written.

### 5.3 Indexing Strategy (Currently Absent)
Minimum required indexes:
- `market_data(instrument_id, timestamp DESC)` — composite, for candle queries
- `signals(symbol, created_at DESC, status)` — composite, for dashboard and dedup
- `orders(status, created_at)` — for OMS queue polling
- `option_chain(instrument_id, expiry, strike, option_type, timestamp)` — for chain reconstruction
- `news(published_at DESC, source)` — for sentiment pipeline
- `sentiments(news_id, symbol)` — for signal scoring lookup

### 5.4 Referential Integrity Not Specified
No FK relationships between `signals → orders → trades → positions` are documented. Without FK constraints, orphaned orders and position leaks are inevitable. Define the full entity relationship diagram before Phase 4.

### 5.5 Data Retention Policy
Tick data older than 90 days is rarely needed for live operation. Define:
- Retention tiers (hot: 7 days in TimescaleDB, warm: 90 days compressed, cold: S3/GCS archive)
- Automated pg_partman or TimescaleDB retention policy
- Minimum retention for regulatory audit (2 years for order/trade records per SEBI requirements)

### 5.6 JSONB for Flexible Metadata
Signal metadata (strategy contributions, weight breakdown, rejection reason) should be stored as JSONB with GIN indexes. This avoids premature schema normalization while retaining queryability.

---

## 6. Broker Abstraction Improvements

### 6.1 Missing Methods on IBroker

The current interface covers basic order management but is incomplete for production FnO trading:

| Missing Method | Reason Required |
|---|---|
| `subscribe_ticks(instruments)` | Live market data via broker WebSocket |
| `unsubscribe_ticks(instruments)` | Resource cleanup |
| `get_funds()` | Real-time margin/cash available for position sizing |
| `get_margin_required(order)` | Pre-trade margin check without placing order |
| `get_instrument_master()` | Download full symbol/lot-size/expiry list |
| `get_historical_candles(instrument, from, to, interval)` | Backtesting data |
| `place_gtt_order()` | Good-Till-Triggered orders for automated stop management |
| `get_quote(instruments)` | Full quote (OHLCV + depth) vs just LTP |

### 6.2 Order Type and Product Type Abstraction
The interface has `place_order()` but no domain model for order parameters. Required domain enums (not broker-specific):
- `OrderType`: MARKET, LIMIT, SL, SL_MARKET
- `ProductType`: INTRADAY, DELIVERY, OVERNIGHT (maps to MIS/CNC/NRML per broker)
- `Validity`: DAY, IOC, TTL
- `Exchange`: NSE, BSE, NFO, MCX

Each broker maps these differently (Kite uses "MIS", Dhan uses "INTRADAY"). Normalization must happen inside the adapter, not in the application layer.

### 6.3 No WebSocket Event Model
The `IBroker` interface must define the event model for streaming data. Recommended approach: a callback/handler pattern where the broker adapter emits normalized `TickEvent`, `OrderUpdateEvent`, and `PositionUpdateEvent` domain events onto the internal event bus. The adapter owns the WebSocket lifecycle; the rest of the system is unaware of it.

### 6.4 Broker Capability Matrix
Not all brokers support all features. A `BrokerCapabilities` object should declare per-broker:
- Supports WebSocket streaming: yes/no
- Supports GTT orders: yes/no
- Supports options: yes/no
- Supports historical data API: yes/no
- Supports basket orders: yes/no

The application layer queries capabilities before attempting unsupported operations.

### 6.5 Order State Machine
Order lifecycle is listed (`PENDING → OPEN → FILLED/CANCELLED/REJECTED`) but not formalized as a state machine. Illegal transitions (e.g., `FILLED → CANCELLED`) must raise domain exceptions, not silently corrupt state. Use a formal FSM with allowed transitions enumerated.

### 6.6 Session Refresh
Kite access tokens expire daily at 6:00 AM IST. The `broker_sessions` table exists but no session refresh flow is specified. The system must:
- Detect token expiry proactively
- Block order submission while re-authenticating
- Queue or reject in-flight orders during the re-auth window
- Alert the operator if re-authentication requires manual intervention

---

## 7. Signal Engine Improvements

### 7.1 Static Weights Are a Systemic Weakness
Scoring weights (Trend=20, OI=20, etc.) are documented as fixed constants. This is dangerous because:
- Weights appropriate for a trending market hurt performance in a sideways market
- No mechanism exists to improve weights from backtesting results
- Different asset classes (equity vs FnO) likely need different weights

**Required:** Weights must be regime-conditional, strategy-specific, and stored in the `strategies` table. The Confidence Engine should adjust effective weights based on recent strategy performance.

### 7.2 Signal Deduplication Not Specified
If the pipeline runs every 5 minutes and conditions have not changed, the system will generate duplicate signals for the same symbol + direction. Without deduplication logic, the OMS will receive duplicate orders. Define: a signal is a duplicate if `(symbol, direction, strategy_version)` already has an OPEN signal within the last N minutes.

### 7.3 Signal TTL / Expiry
Signals have no expiry. An FnO signal generated at 9:30 AM may be irrelevant by 10:30 AM if the underlying has moved significantly. Every signal must carry:
- `valid_until` timestamp
- Invalidation trigger (e.g., if underlying moves beyond ATR band from signal time)

### 7.4 Multi-Timeframe Confirmation Missing
All analysis implicitly operates on a single timeframe. Institutional FnO trading requires multi-timeframe alignment:
- Daily/Weekly for bias (market regime)
- 1-hour for trend confirmation
- 15-minute for entry timing

The Feature Engineering phase should produce features for multiple timeframes, and the Scoring Engine should require alignment across timeframes above a configurable threshold.

### 7.5 Strike and Expiry Selection Gap
The Signal Engine outputs `symbol`, `entry`, `stop_loss`, and `targets` — but for FnO these values apply to the underlying. There is no component that translates the underlying signal into:
- Specific option instrument (e.g., `NIFTY24JUN23000CE`)
- Expiry selection (nearest vs weekly vs monthly)
- Strike selection methodology (delta-based, ATM, risk-reward optimized)
- Quantity calculation respecting lot size

### 7.6 Portfolio Correlation Check
Two simultaneous BUY signals on NIFTY CE and BANKNIFTY CE are highly correlated. The signal engine emitting both doubles effective market exposure without the risk engine being aware. A portfolio-level correlation check must sit between signal generation and risk engine evaluation.

### 7.7 Score Explainability
Each signal's score must record the individual component contributions (Trend=18, OI=17, Volume=12...) not just the aggregate. This is required for:
- Debugging signal quality
- Backtesting weight optimization
- Regulatory audit ("why did the system recommend this trade?")

---

## 8. Risk Engine Improvements

### 8.1 No Real-Time Position MTM
The Risk Engine checks limits at signal generation time but has no continuous monitoring of open positions. If a position moves against the trader after entry, the daily loss limit check at signal time is irrelevant. Required: a continuous loop (every tick or every minute) that revalues all open positions and triggers the kill switch if limits are breached.

### 8.2 No Portfolio Greeks
For an FnO platform, the Risk Engine must track portfolio-level Greeks:
- **Net Delta** — directional exposure to underlying moves
- **Net Gamma** — rate of delta change (tail risk)
- **Net Theta** — daily time decay (always negative for long options)
- **Net Vega** — sensitivity to IV changes

Position sizing and exposure limits that ignore Greeks will produce portfolios with uncontrolled tail risk.

### 8.3 No Volatility-Adjusted Position Sizing
Position size is specified as a risk engine check but the sizing formula is not defined. Best practice for FnO: `position_size = (account_risk_per_trade / ATR) / lot_size`. Without ATR-based sizing, the system will over-risk in low-volatility periods and under-risk in high-volatility periods.

### 8.4 Missing Hard Limits
The following limits are absent from the specification:
- Maximum number of concurrent open positions
- Maximum capital allocated to a single underlying
- Maximum number of orders per minute (rate limiting at OMS level)
- Maximum notional value per trade

### 8.5 Risk Engine Auditability
Every risk decision (approve or reject) must be persisted with:
- Signal ID evaluated
- Each check performed and its result
- Final decision and reason code
- Timestamp

The current `signals` table does not capture risk rejection reasons. This is a regulatory and debugging requirement.

### 8.6 Intraday Loss Cliff vs Gradual Scaling
Daily loss limits are binary (stop trading at breach). A more robust approach uses graduated responses:
- At 50% of daily loss limit: reduce position size by 50%
- At 75%: move to paper trading mode
- At 100%: kill switch

### 8.7 No Counterparty / Settlement Risk
For delivery trades (Phase 2/3), settlement failure risk (T+1 funds, T+2 delivery) is unspecified. Even in Phase 1, a failed margin call can result in broker auto-squareoff at unfavorable prices.

---

## 9. AI Integration Improvements

### 9.1 IAIProvider Abstraction is Missing
OpenAI is hardcoded as the AI provider across all documentation. The system must define an `IAIProvider` interface before any AI integration code is written:
```
IAIProvider:
    summarize_news(text) -> str
    analyze_sentiment(text) -> SentimentResult
    generate_market_commentary(context) -> str
    explain_trade(signal, context) -> str
```
This allows substitution with Anthropic Claude, Google Gemini, local Ollama models, or mock providers for testing — without changing any application logic.

### 9.2 Prompt Versioning
AI output quality is determined by prompt quality, and prompts change over time. Without versioning:
- Historical sentiment scores are incomparable across prompt versions
- A/B testing prompt improvements is impossible
- Debugging unexpected sentiment output has no baseline

Prompts must be stored in configuration (not hardcoded), versioned, and recorded alongside each AI response.

### 9.3 Structured Output Enforcement
All AI calls must use structured output (OpenAI's `response_format: { type: "json_object" }` or function calling). Free-form text responses for sentiment analysis will fail to parse intermittently and are impossible to validate.

### 9.4 AI Fallback Strategy
If the AI provider is unavailable, the sentiment component must return a neutral score (0) rather than blocking the pipeline. The `Sentiment Score` weight (10 points) is small enough that neutral fallback is acceptable. This must be explicit in the Confidence Engine: when AI is unavailable, confidence is reduced by the sentiment weight contribution.

### 9.5 AI Response Caching
The same news article should not be sent to the AI API multiple times. Cache AI responses in Redis keyed by a hash of the input text. Estimated cost savings: 80–90% on duplicate news items from the same source.

### 9.6 Cost and Token Budget Controls
OpenAI API costs scale with usage. Define:
- Maximum tokens per request type
- Daily/monthly spend budget with hard stops
- Per-request cost logging in structured logs
- Alert when budget is 80% consumed

### 9.7 Entity-Level Sentiment
Current design outputs a single sentiment score. For multi-instrument coverage, sentiment should be entity-tagged: a news article mentioning both Reliance and Nifty should produce separate sentiment signals for each. This requires named entity recognition (NER) before sentiment scoring.

### 9.8 AI Should Not Block Signal Generation
News sentiment is listed between Feature Engineering and Market Regime in `02_SYSTEM_FLOW.md`. This means the entire signal pipeline waits for the AI call. Architecture must be changed: run AI sentiment asynchronously on news ingestion, cache results, and have the scoring engine read from cache. If cache is empty for a symbol, use neutral score.

---

## 10. Monitoring Improvements

### 10.1 No Metrics Framework Specified
"Observability" is listed as a non-functional requirement but no metrics instrumentation library is specified. Required:
- **Prometheus** (via `prometheus-client`) for metrics collection
- **Grafana** for dashboards
- Define key metrics at each pipeline stage (see §10.6)

### 10.2 No Distributed Tracing
A signal traverses 10+ components from market data ingestion to order placement. When a signal behaves unexpectedly, there is no way to trace its path. Implement OpenTelemetry tracing with a span for each pipeline stage. This is especially valuable for debugging latency regressions.

### 10.3 No Alerting Rules Defined
Health checks expose status but no alerting thresholds are defined. Required:
- PagerDuty/OpsGenie integration or a Telegram alert channel for on-call
- Alert on: broker disconnect, DB connection failure, signal pipeline stall > 60s, kill switch trigger, daily loss limit approach

### 10.4 No SLOs/SLIs
Define measurable service level objectives:
- Signal generation latency P99 < 5 seconds from tick ingestion to signal record
- Order submission latency P99 < 500ms from signal approval to broker confirmation
- Dashboard data freshness < 30 seconds
- System uptime during market hours > 99.5%

### 10.5 Log Aggregation Not Specified
`structlog` is specified for structured logging but no log shipping target is defined. Logs written only to stdout/file are lost on process restart and unsearchable at scale. Required: ship to a central store (ELK stack, Grafana Loki, or a managed service like Datadog) with retention policy and full-text search.

### 10.6 Business KPI Metrics
The health check dashboard covers infrastructure (Kite, NSE, OpenAI, PostgreSQL, Redis) but no business metrics. Required metrics:
- `signals_generated_total` — counter by symbol, direction, strategy
- `signals_rejected_by_risk_total` — counter by rejection reason
- `orders_placed_total` / `orders_filled_total` / `orders_rejected_total`
- `order_fill_rate` — ratio of filled to placed
- `average_slippage_bps` — filled price vs signal price
- `daily_pnl` — running MTM P&L gauge
- `signal_pipeline_duration_seconds` — histogram per pipeline stage
- `ai_api_latency_seconds` — histogram for AI calls
- `broker_api_latency_seconds` — histogram by method

### 10.7 WebSocket Monitoring
Broker WebSocket connections are the system's most fragile component. Monitor:
- `websocket_connected` — boolean gauge
- `websocket_reconnect_total` — counter
- `last_tick_received_seconds` — gauge; alert if > 10 seconds during market hours
- `websocket_message_lag_seconds` — time between market event and processing

### 10.8 Dead Man's Switch
For fully automated live trading, implement a dead man's switch: if the monitoring heartbeat has not been updated for > 2 minutes during market hours, auto-trigger the kill switch. This protects against silent process hangs where no new signals are generated but open positions remain unmonitored.

### 10.9 Dashboard Gap: No P&L Attribution
The dashboard pages listed (Market Overview, Signals, Option Chain, Trades, Sentiment, Health, Analytics) have no P&L attribution page. Operators need to see:
- P&L by strategy
- P&L by instrument
- P&L by market regime
- Realized vs unrealized P&L
- Slippage and brokerage cost breakdown

---

## Summary Priority Matrix

| # | Finding | Severity | Phase Impact |
|---|---|---|---|
| 1.1 | No event bus defined | High | Before Phase 7 |
| 1.2 | No WebSocket manager | Critical | Before Phase 7 |
| 1.3 | No instrument master | High | Before Phase 9 |
| 1.4 | No kill switch design | Critical | Before Phase 21 |
| 3.1 | Default admin/admin credentials | Critical | Phase 6 |
| 3.2 | Broker token unencrypted | High | Phase 8 |
| 5.2 | No TimescaleDB decision | High | Phase 4 |
| 5.4 | No FK/ER diagram | High | Phase 4 |
| 6.1 | IBroker missing methods | High | Phase 8 |
| 6.3 | No WebSocket event model | Critical | Phase 8 |
| 7.5 | No strike/expiry selector | High | Phase 16 |
| 8.1 | No real-time position MTM | Critical | Phase 21 |
| 8.2 | No portfolio Greeks | High | Phase 15 |
| 9.1 | No IAIProvider interface | Medium | Phase 10 |
| 9.8 | AI in synchronous signal path | High | Phase 10 |
| 10.1 | No metrics framework | High | Phase 5 |
| 10.8 | No dead man's switch | High | Phase 21 |

---

## Recommended Immediate Documentation Additions

Before writing any production code, these documents should be added to `/docs`:

1. **`11_EVENT_BUS_DESIGN.md`** — Event taxonomy, topic names, consumer groups, message schemas
2. **`12_WEBSOCKET_MANAGER.md`** — Broker WebSocket lifecycle, reconnect policy, tick fan-out
3. **`13_INSTRUMENT_MASTER.md`** — Instrument model, expiry calendar, lot size management
4. **`14_DATA_RETENTION.md`** — Retention tiers, partitioning strategy, archival policy
5. **`15_OBSERVABILITY_STACK.md`** — Prometheus metrics list, Grafana dashboard spec, alerting rules
6. **`16_SECURITY_MODEL.md`** — Auth flow, token lifecycle, secret management, CORS policy
7. **`17_KILL_SWITCH.md`** — Trigger conditions, behavior, recovery flow
8. **`18_STRIKE_SELECTOR.md`** — Strike/expiry selection methodology for FnO signals

---

*This review covers architectural intent only. No code was generated or modified.*
