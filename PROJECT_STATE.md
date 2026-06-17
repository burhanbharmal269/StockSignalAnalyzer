# Project State

Date reviewed: 2026-06-12

Project: Production-grade Indian Stock Market Trading Platform for NSE FnO trade recommendations.

Primary objective: generate deterministic, explainable, risk-gated FnO recommendations using option chain analysis, OI analysis, trend analysis, volume analysis, market regime detection, and risk management.

## Current Summary

The repository is a backend-first FastAPI application with substantial architecture documentation and a Clean Architecture oriented codebase. The implemented system currently provides the platform foundation, domain model, configuration, database/repository layer, observability primitives, authentication, instrument master infrastructure, broker and WebSocket abstractions, and a market regime engine.

The core trading recommendation pipeline is not yet implemented end to end. Strategy, scoring, confidence, risk, and signal orchestration remain pending. The frontend/dashboard is also not present in the repository.

## Completed Components

### Documentation and Architecture Baseline

- Project constitution and architecture documents exist under `docs/`.
- The authoritative implementation roadmap is captured in `docs/IMPLEMENTATION_PLAN.md`.
- Architecture diagrams exist under `docs/architecture/`.
- Key design documents exist for broker abstraction, event bus, instrument master, risk engine, scoring, strategy framework, market regime engine, OMS, AI provider abstraction, and security baseline.

### Backend Foundation

- FastAPI application factory exists in `src/app.py`.
- Process entry point exists in `src/main.py`.
- Dependency injection container exists in `src/container.py`.
- Project tooling is configured in `pyproject.toml` for Poetry, pytest, ruff, mypy, and coverage.
- Docker and docker-compose files are present.

### Domain Layer

- Domain entities exist for:
  - `Signal`
  - `Order`
  - `Position`
  - `Instrument`
  - `BrokerSession`
  - `User`
- Domain enums exist for asset type, exchange, instrument type, market regime, option type, order state, position state, segment, signal state, signal type, strategy type, subscription mode, and user role.
- Value objects exist for price, score, confidence, symbol, OHLC, market depth, feature snapshots, regime snapshots, instrument health, instrument refresh results, broker DTOs, and signal fingerprints.
- Domain event classes exist for market, order, regime, risk, signal, system, and tick events.
- Domain interfaces exist for broker, data provider, event bus, instrument master, repositories, secrets, market regime engine, and WebSocket manager.

### Configuration and Secrets

- Environment and settings configuration exists.
- Separate typed config loaders exist for:
  - AI
  - Broker
  - Database
  - Redis
  - Regime
  - Risk
  - Scoring
  - Security
  - WebSocket
- Runtime config files exist under `config/`:
  - `risk.yaml`
  - `regime.yaml`
  - `scoring_weights.yaml`
- Environment secrets client exists.
- AWS secrets client stub exists.

### Database Layer

- SQLAlchemy async connection setup exists.
- Alembic migrations exist.
- ORM models exist for users, broker sessions, instruments, market data, signals, regimes, orders, and positions.
- Repository implementations exist for users, broker sessions, instruments, signals, regimes, orders, and positions.
- Repository tests are present.

### Authentication and Authorization

- Password hashing service exists.
- JWT service exists.
- Login rate limiter exists.
- First-run admin credential initializer exists.
- Auth router and auth schemas exist.
- Auth dependency and IP allowlist dependency exist.

### Observability and Middleware

- Structured logging setup exists.
- Request logging middleware exists.
- Error handler middleware exists.
- Prometheus metrics helpers exist.
- Tracing helpers exist.
- `/metrics` endpoint is registered.
- Lightweight `/api/v1/health` endpoint exists.

### Event Infrastructure

- `IEventBus` interface exists.
- In-memory event bus exists for tests.
- Redis Streams event bus exists.
- Message envelope abstraction exists.
- Event bus tests exist for in-memory bus and message envelope.

### Instrument Master and Market Data Infrastructure

- Instrument provider abstraction exists.
- Kite instrument provider exists.
- Instrument master service exists with refresh, validation, diff, cache rebuild, and refresh logging.
- Expiry calendar exists.
- Pre-market scheduler tasks exist.
- Candle aggregator exists.
- Option chain poller exists.
- Instrument API router exists.

### Broker and WebSocket Abstraction

- `IBroker` domain interface exists.
- Kite broker adapter exists.
- Paper broker adapter exists.
- Broker token encryptor exists.
- WebSocket manager interface exists.
- Kite WebSocket manager exists.
- In-memory WebSocket manager exists.
- Subscription manager, reconnect policy, and connection state machine exist.
- Broker and WebSocket tests are present.

### Market Regime Engine

- Regime feature and snapshot value objects exist.
- Trend layer, volatility layer, regime resolver, regime smoother, and confidence calculator exist.
- Regime evaluation use case exists.
- Market regime service exists and implements `IMarketRegimeEngine`.
- Regime repository exists.
- Regime API router exists for latest and history endpoints.
- Regime unit and integration tests are present.

## Pending Components

### Feature Engineering Pipeline

- Full technical indicator pipeline is pending.
- Indicator modules for EMA, ADX, ATR, Supertrend, Bollinger Band width, VWAP, relative volume, OBV, cumulative delta, PCR, max pain, IV rank, IV percentile, and GEX are pending.
- Persistence flow from computed features into `market_features` is not implemented as a complete service.
- Event flow from candle close and option chain update into feature computation is not complete.

### Strategy Framework

- `IScoreComponent` / strategy component contracts are pending.
- Component implementations are pending for:
  - OI build-up
  - Trend following
  - Option chain analysis
  - Volume analysis
  - VWAP analysis
  - IV analysis
  - Sentiment component
- Direction voting and long/short evidence handling are pending.

### Scoring Engine

- Scoring engine service is pending.
- Regime multiplier application is pending.
- Component aggregation and normalization are pending.
- Data completeness checks are pending.
- Score penalty logic is pending.
- Score breakdown audit payload is pending.

### Confidence Engine

- 9-component confidence formula is pending.
- Historical accuracy lookup is pending.
- Calibration logic is pending.
- Confidence breakdown audit payload is pending.
- Signal fingerprint usage in confidence/history lookup is pending beyond the value object.

### Risk Engine

- Risk engine service is pending.
- 15 pre-trade checks from `docs/17_PORTFOLIO_RISK_ENGINE.md` are pending.
- Position sizing is pending.
- Risk decision persistence is pending.
- Portfolio-level Greeks tracking is pending.
- Correlation-aware exposure checks are pending.
- Real-time risk monitor is pending.
- Kill switch integration is pending.

### Signal Engine

- End-to-end orchestration is pending:
  - Strategy
  - Scoring
  - Confidence
  - Risk
  - Signal Engine
  - OMS
- Signal deduplication is pending.
- Signal TTL worker is pending.
- Signal explanation generation is pending.
- Signal outcome recorder is pending.
- Signal performance stats update flow is pending.

### OMS and Order Flow

- OMS service is pending.
- Risk-approved signal to order submission workflow is pending.
- Stop-loss and target order management is pending.
- Partial fill handling across broker/order repositories is pending beyond domain entity capabilities.
- Rogue order reconciliation is pending.
- Idempotent order submission is pending.

### Dashboard and Frontend

- `frontend/` is not present.
- Next.js, TypeScript, Tailwind, shadcn/ui, TanStack Query, WebSocket live feed, and Recharts implementation is pending.
- Dashboard API routers are pending for signals, orders, positions, analytics, market data, detailed health, kill switch, and live feed.
- Detailed health endpoint is pending.

### AI Layer

- AI provider abstraction is documented but not implemented.
- OpenAI/Anthropic/Gemini/Ollama/neutral fallback providers are pending.
- Prompt registry, sentiment cache, cost tracker, provider factory, and response validation are pending.
- AI must remain after deterministic pipeline and paper validation, per project rules.

### Paper Trading and Live Readiness

- Paper trading validation harness is pending.
- 30 trading day validation process is pending.
- Backtesting and replay infrastructure is pending.
- Live trading prerequisites are pending.

## Architecture Compliance Review

### Compliant Areas

- The repository follows a recognizable Clean Architecture layout: `domain`, `application`, `infrastructure`, and `presentation`.
- Domain models are mostly free from FastAPI, SQLAlchemy, Redis, and broker SDK dependencies.
- Broker-specific logic is contained in infrastructure broker/data/websocket adapters.
- API routers are generally thin and delegate to repositories or services.
- Dependency injection is centralized in `src/container.py`.
- Domain and ORM models are separate.
- Repository pattern is used for database access.
- Structured logging and middleware are present.
- The signal domain model enforces a state machine.
- The order domain model enforces a state machine.
- AI is not wired into OMS, risk, position sizing, or order placement.

### Partial Compliance

- Configuration exists, but some operational thresholds and defaults still live in code.
- Event bus abstraction exists, but Redis topic naming currently uses class names rather than the documented domain topic taxonomy.
- Redis event consumption currently reconstructs only a generic `DomainEvent`; typed payload delivery is incomplete.
- Signal entity contains pending event support, but lifecycle methods do not currently emit the documented signal events.
- Health endpoint exists, but detailed dependency health is not implemented.
- Regime engine is implemented, but it depends on upstream feature snapshots that are not yet produced by a full feature engineering pipeline.
- Broker abstraction exists, but full session lifecycle, startup wiring, and production readiness around live Kite usage need further validation.

### Non-Compliant or Not Yet Proven

- Direct executable trade recommendation pipeline is absent.
- No implemented risk gate currently guarantees that every executable signal passes the risk engine.
- No implemented OMS path guarantees that orders cannot bypass risk approval.
- Signal execution thresholds are hardcoded inside `Signal` instead of being supplied by configuration/application orchestration.
- Several source files contain hardcoded market defaults, intervals, stream sizes, and broker mappings. Some are adapter-local and acceptable short term, but they should be reviewed against the "no hardcoded values" rule before production.
- The local test run could not complete because declared dependencies were missing from the active Python environment.

## Technical Debt

### High Priority

- Bootstrap the development environment so test, lint, and type-check commands run reliably.
- Fix Redis event bus typed serialization/deserialization before more event-driven pipeline work.
- Align event topic naming with `docs/11_EVENT_BUS_ARCHITECTURE.md`.
- Move signal execution gate thresholds out of the domain entity and into configuration/application policy.
- Add lifecycle domain event emission to `Signal` and `Order` state transitions where required.
- Create a durable signal audit schema that stores input snapshots, score breakdown, confidence breakdown, penalty log, regime snapshot, and config hash.

### Medium Priority

- Remove or externalize hardcoded market/broker defaults that are not adapter-local constants.
- Add detailed health checks for PostgreSQL, Redis, broker, NSE provider, WebSocket, instrument master, and AI provider status.
- Add dependency-injection tests that prove AI providers cannot be injected into risk, OMS, position sizing, or kill switch services.
- Add architecture tests for forbidden imports from domain to infrastructure/presentation.
- Review repository methods for read/write engine separation before dashboard APIs are added.
- Add event idempotency contracts for side-effecting consumers.

### Low Priority

- Clean generated `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, and coverage artifacts from the working tree if they are not intentionally retained.
- Improve README so it reflects actual setup, current phase, required services, and validation commands.
- Fix mojibake/encoding artifacts visible in several documentation files.
- Add a shorter operator/developer quickstart alongside the large architecture documents.

## Validation Notes

Attempted command:

```powershell
pytest -q
```

Result: test collection failed before executing tests because the active Python environment is missing project dependencies, including `structlog`, `pyyaml`, `argon2-cffi`, `pyjwt`, and `prometheus-client`. Pytest also reported permission warnings writing to `.pytest_cache`.

This means current code quality cannot be confirmed from this environment until dependencies and local cache permissions are fixed.

## Recommended Next Sprint

### Sprint Goal

Stabilize the deterministic foundation required before implementing strategy/scoring/risk features.

### Sprint Scope

1. Environment and quality gate recovery
   - Install or document the correct Python environment workflow.
   - Make `pytest`, `ruff`, and `mypy` runnable locally.
   - Update README with exact setup and validation commands.

2. Event bus hardening
   - Implement typed event round-trip serialization and deserialization.
   - Align Redis stream names with documented topic taxonomy.
   - Add tests for publish, subscribe, replay, DLQ behavior, and typed payload delivery.

3. Signal lifecycle audit correctness
   - Move score/confidence execution thresholds to configuration/application policy.
   - Ensure signal lifecycle methods emit domain events.
   - Ensure signal repository and signal event persistence support append-only audit requirements.

4. Feature engineering vertical slice
   - Implement the first production-grade feature computation path needed by the next strategy work.
   - Recommended first slice: 15-minute trend features for ADX, DI, EMA alignment, Supertrend direction, ATR, and VWAP.
   - Persist computed features and publish the corresponding feature event.

5. Strategy framework contracts
   - Add component contracts and shared input/output DTOs for score components.
   - Implement the first deterministic component after the feature slice, preferably Trend Following.
   - Keep it score-only; do not generate final BUY/SELL recommendations.

### Sprint Exit Criteria

- `pytest` passes in the documented local environment.
- `ruff check` passes.
- `mypy` passes or has an explicit tracked baseline if current code is not yet clean.
- Redis event bus can deliver typed events to typed handlers.
- Signal thresholds are configuration-driven.
- First feature engineering slice is tested and emits usable data for the future strategy component.
- No direct BUY/SELL generation is introduced.
- No broker-specific logic leaks outside adapters.
- AI remains outside the deterministic trading path.

## Recommended Implementation Order After Next Sprint

1. Complete feature engineering service for all core inputs.
2. Implement strategy components as independent score contributors.
3. Implement scoring engine with regime multipliers and penalties.
4. Implement confidence engine.
5. Implement risk engine and risk decision persistence.
6. Implement signal engine orchestration.
7. Implement OMS in paper mode only.
8. Build dashboard API and frontend for operator visibility.
9. Run paper trading validation.
10. Add AI sentiment layer only after deterministic paper validation.

