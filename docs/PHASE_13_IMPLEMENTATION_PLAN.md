# Phase 13 Risk Engine — Implementation Plan

**Date:** 2026-06-13  
**Status:** APPROVED FOR IMPLEMENTATION — Readiness Score 93/100  
**Source:** PHASE_13_FINAL_READINESS_REVIEW.md (Section 9: 20 mandatory constraints)  
**Constraint reference:** All code generated under this plan must satisfy Constraints 1–20.

---

## Constraint Validation Checklist

Before any file is generated, confirm all mandatory constraints from the Final Readiness Review are addressed in this plan.

| # | Constraint | Addressed By |
|---|-----------|-------------|
| 1 | asyncio.Lock in RiskEngineService.evaluate() | `risk_engine_service.py` — lock field + context manager |
| 2 | risk-engine consumer group parallelism = 1 | `container.py` Phase 13 section + implementation notes |
| 3 | evaluate() not called concurrently | Lock raises `ConcurrentEvaluationError` if contested |
| 4 | Persistence-first: INSERT before publish | `risk_engine_service.py` — INSERT before event publish |
| 5 | risk_decisions append-only | DB permissions in migration; no UPDATE/DELETE in repo |
| 6 | kill_switch_events INSERT-only | DB permissions in migration |
| 7 | All limits from risk.yaml v2.0 | `risk_config.py` rewrite + `config/risk.yaml` update |
| 8 | RiskRejectionCode enum | `risk_decision.py` — RiskRejectionCode enum |
| 9 | Kill switch: system:kill_switch Hash, no TTL | `kill_switch_repository.py` — Hash operations only |
| 10 | KillSwitchService is sole writer | `kill_switch_service.py` — only writer to Hash |
| 11 | Greeks two-tier cache write | `greeks_repository.py` — atomic Tier 1 + Tier 2 write |
| 12 | IAIProvider forbidden | No IAIProvider import in any Phase 13 service or domain |
| 13 | session_capital for sizing | `position_sizer.py` — uses account_state.session_capital |
| 14 | Kelly four-layer protection | `position_sizer.py` — all four layers |
| 15 | POSITION_SIZE_ZERO rejection | `risk_engine_service.py` — zero-lot check |
| 16 | All 12 events implemented | `risk_events.py` — complete schema |
| 17 | GraduatedResponseActivated.state | `risk_events.py` — state field present |
| 18 | Three-tier event delivery | `risk_engine_service.py` — retry + pending list |
| 19 | FAIL_CLOSED per C-2 table | `risk_engine_service.py` — gather exception handler |
| 20 | Startup kill switch check | `kill_switch_service.py` + `main.py` startup hook |

---

## Section 1 — Files To Create

### 1.1 Domain Layer — `src/core/domain/risk/`

New package. Pure domain: no I/O, no external dependencies, fully synchronous.

---

#### `src/core/domain/risk/__init__.py`
Empty package marker.

---

#### `src/core/domain/risk/account_state.py`

**Purpose:** Frozen value object representing the account state snapshot at evaluation time.

```
AccountState (frozen dataclass):
    account_capital: Decimal          — total account capital (session-anchored)
    session_capital: Decimal          — capital frozen at 09:15 IST (used for sizing)
    available_margin: Decimal         — live margin available
    used_margin: Decimal              — margin currently in use
    margin_utilization_pct: float     — used_margin / account_capital × 100
    daily_pnl: Decimal                — realized + MTM P&L for the day
    daily_loss_consumed_pct: float    — abs(daily_pnl) / daily_loss_limit_abs × 100 (only when negative)
    weekly_pnl: Decimal               — rolling 5-day P&L
    weekly_loss_consumed_pct: float   — abs(weekly_pnl) / weekly_loss_limit_abs × 100
    drawdown_from_hwm_pct: float      — (HWM - current_value) / HWM × 100
    open_positions_count: int
    position_size_multiplier: float   — 1.0 | 0.5 | 0.0
    trading_mode: str                 — LIVE | PAPER | BLOCKED
    captured_at: datetime
```

**Constraint:** No methods. No I/O. Pure data.

---

#### `src/core/domain/risk/portfolio_state.py`

**Purpose:** Frozen value object for portfolio-level risk metrics.

```
PortfolioState (frozen dataclass):
    open_positions_count: int
    positions_per_underlying: dict[str, int]       — {underlying: count}
    capital_per_underlying_pct: dict[str, float]   — {underlying: pct_of_total}
    net_delta: float                               — INR per 1-point move
    net_vega: float                                — INR per 1% IV change
    net_theta_daily: float                         — INR per calendar day
    orders_last_minute: int
    captured_at: datetime
```

**Constraint:** dict fields are frozen-compatible (frozen dataclass with dict fields is not directly hashable; do not hash PortfolioState — it is not an event field).

---

#### `src/core/domain/risk/greeks_snapshot.py`

**Purpose:** Greeks for a single position, read from the two-tier cache.

```
GreeksSnapshot (frozen dataclass):
    position_id: str
    delta: float
    gamma: float
    theta: float                     — daily decay in INR (negative for long positions)
    vega: float                      — INR per 1% IV change
    computed_at: datetime
    from_fallback: bool              — True if Tier 2 was used
```

---

#### `src/core/domain/risk/risk_request.py`

**Purpose:** Input value object to the risk engine. Carries everything needed to run all 15 checks without additional I/O inside the checks.

```
RiskRequest (frozen dataclass):
    signal_id: uuid.UUID
    instrument_token: int
    underlying: str                  — e.g., "NIFTY", "BANKNIFTY"
    instrument_class: str            — "OPTION" | "FUTURE"
    direction: str                   — "LONG" | "SHORT"
    adjusted_score: float
    final_confidence: float
    entry_price: Decimal
    stop_loss_price: Decimal
    target_price: Decimal
    option_premium: Decimal | None   — None for futures
    lot_size: int
    option_delta: float | None       — delta of the proposed new position
    option_vega: float | None
    dte: int                         — days to expiry
    atr_14: float                    — from FeatureSnapshot
    risk_reward_ratio: float         — pre-computed: (target - entry) / (entry - stop)
    evaluated_at: datetime
```

**Constraint:** No business logic. Fields only.

---

#### `src/core/domain/risk/risk_decision.py`

**Purpose:** Output value object from the risk engine. Complete audit record.

```
RiskRejectionCode (str enum):
    KILL_SWITCH_ACTIVE
    DAILY_LOSS_LIMIT
    WEEKLY_LOSS_LIMIT
    DRAWDOWN_LIMIT
    MAX_OPEN_POSITIONS
    SYMBOL_CONCENTRATION
    CAPITAL_CONCENTRATION
    NET_DELTA_LIMIT
    CORRELATION_LIMIT
    INSUFFICIENT_MARGIN
    RISK_REWARD_BELOW_MINIMUM
    POSITION_SIZE_ZERO
    ORDER_RATE_LIMIT
    VEGA_LIMIT
    AUDIT_PERSISTENCE_FAILURE
    AUDIT_PERSISTENCE_TIMEOUT
    DATA_SOURCE_UNAVAILABLE
    GREEKS_UNAVAILABLE
    MARGIN_DATA_UNAVAILABLE
    UNSUPPORTED_INSTRUMENT_CLASS

RiskCheckResult (frozen dataclass):
    check_name: str
    passed: bool
    current_value: float | None
    limit_value: float | None
    message: str
    is_warning: bool = False        — True for ThetaDecay (warn-only)

SizingResult (frozen dataclass):
    lots: int
    atr_lots_pre_cap: int
    kelly_lots_pre_cap: int
    kelly_fraction_effective: float
    kelly_sample_count: int
    sizing_note: str | None

RiskDecision (frozen dataclass):
    signal_id: uuid.UUID
    approved: bool
    rejection_code: RiskRejectionCode | None
    rejection_reason: str | None
    position_size_lots: int | None
    size_reduction_pct: float            — 0 | 50 (graduated response)
    checks: tuple[RiskCheckResult, ...]  — all 15 check results (tuple for hashability)
    sizing: SizingResult | None
    account_snapshot: AccountState
    failed_data_sources: tuple[str, ...]
    risk_decision_id: int | None         — populated after DB INSERT; None before
    evaluated_at: datetime
```

---

#### `src/core/domain/risk/risk_limit_checker.py`

**Purpose:** Pure domain service containing all 15 check functions. No I/O. Receives all data as arguments. Returns `RiskCheckResult`.

**Structure:** One function per check. All functions are `@staticmethod` or module-level functions. No class state.

**Constraint enforcement:**
- No database calls
- No Redis calls
- No broker API calls
- No async operations
- No imports from infrastructure layer

**15 check signatures (to be implemented):**

```
check_kill_switch(state: KillSwitchState, config: RiskConfig) -> RiskCheckResult
check_daily_loss(account: AccountState, config: RiskConfig) -> RiskCheckResult
check_weekly_loss(account: AccountState, config: RiskConfig) -> RiskCheckResult
check_drawdown(account: AccountState, config: RiskConfig) -> RiskCheckResult
check_open_positions(portfolio: PortfolioState, config: RiskConfig) -> RiskCheckResult
check_symbol_concentration(portfolio: PortfolioState, request: RiskRequest, config: RiskConfig) -> RiskCheckResult
check_capital_concentration(portfolio: PortfolioState, request: RiskRequest, account: AccountState, config: RiskConfig) -> RiskCheckResult
check_net_delta(portfolio: PortfolioState, request: RiskRequest, config: RiskConfig) -> RiskCheckResult
check_correlation(portfolio: PortfolioState, request: RiskRequest, correlation_matrix: dict[str, dict[str, float]], config: RiskConfig) -> RiskCheckResult
check_margin(account: AccountState, margin_required: Decimal, config: RiskConfig) -> RiskCheckResult
check_risk_reward(request: RiskRequest, config: RiskConfig) -> RiskCheckResult
check_position_size(sizing: SizingResult) -> RiskCheckResult
check_order_rate(portfolio: PortfolioState, config: RiskConfig) -> RiskCheckResult
check_theta_decay(portfolio: PortfolioState, config: RiskConfig) -> RiskCheckResult  ← warn-only
check_vega_exposure(portfolio: PortfolioState, request: RiskRequest, account: AccountState, config: RiskConfig) -> RiskCheckResult
```

---

#### `src/core/domain/risk/position_sizer.py`

**Purpose:** Pure domain service. Implements ATR + Kelly sizing with all four protection layers.

**Constraint:** No I/O. All data passed as arguments.

```
PositionSizer.compute(
    request: RiskRequest,
    account: AccountState,
    win_rate: float,
    win_loss_ratio: float,
    sample_count: int,
    loss_count: int,
    config: RiskConfig,
) -> SizingResult
```

**Internal logic:**
1. Layer 1 — sample guard: `sample_count < config.position_sizing.min_kelly_samples` → use fallback fraction
2. Layer 2 — zero-loss edge: `loss_count == 0` → use fallback fraction
3. Layer 3 — raw_kelly floor: `raw_kelly = max(0.0, win_rate - (1-win_rate) / win_loss_ratio)`
4. Layer 4 — absolute cap: `min(computed_lots, config.position_sizing.max_position_size_lots)`
5. Graduated response multiplier applied after caps

---

#### `src/core/domain/risk/kill_switch_state.py`

**Purpose:** Frozen value object for the kill switch state read from Redis.

```
KillSwitchState (frozen dataclass):
    is_active: bool
    activated_at: datetime | None
    activated_by: str | None
    activation_reason: str | None
    deactivated_at: datetime | None
    deactivated_by: str | None
    deactivation_note: str | None
```

---

### 1.2 Domain Interfaces — `src/core/domain/interfaces/`

---

#### `src/core/domain/interfaces/i_risk_engine.py`

```
IRiskEngine (ABC):
    @abstractmethod
    async def evaluate(self, request: RiskRequest) -> RiskDecision: ...
```

---

#### `src/core/domain/interfaces/i_risk_decision_repository.py`

```
IRiskDecisionRepository (ABC):
    @abstractmethod
    async def insert(self, decision: RiskDecision, timeout_seconds: float) -> int: ...
    # Returns the assigned risk_decision_id (BIGSERIAL)
    # Raises: RiskDecisionPersistenceError | asyncio.TimeoutError
```

---

#### `src/core/domain/interfaces/i_account_state_repository.py`

```
IAccountStateRepository (ABC):
    @abstractmethod
    async def get_current(self) -> AccountState: ...
    # Raises: DataSourceUnavailableError if Redis read fails
```

---

#### `src/core/domain/interfaces/i_portfolio_state_repository.py`

```
IPortfolioStateRepository (ABC):
    @abstractmethod
    async def get_current(self) -> PortfolioState: ...
    @abstractmethod
    async def get_graduated_response(self) -> GraduatedResponseState: ...
    # Both raise: DataSourceUnavailableError if Redis read fails
```

---

#### `src/core/domain/interfaces/i_greeks_repository.py`

```
IGreeksRepository (ABC):
    @abstractmethod
    async def get_portfolio_greeks(
        self,
        position_ids: list[str],
        max_age_seconds: int,
        new_position_grace_seconds: int,
    ) -> dict[str, GreeksSnapshot | None]: ...
    # None for a position_id means FAIL_CLOSED should be applied by caller
    
    @abstractmethod
    async def write_greeks(self, position_id: str, snapshot: GreeksSnapshot) -> None: ...
    # Writes both Tier 1 (TTL 60s) and Tier 2 (TTL 300s) atomically
```

---

#### `src/core/domain/interfaces/i_correlation_repository.py`

```
ICorrelationRepository (ABC):
    @abstractmethod
    async def get_matrix(self) -> dict[str, dict[str, float]]: ...
    # Returns empty dict on miss (caller applies CONSERVATIVE_DEFAULT: ρ=1.0)
```

---

#### `src/core/domain/interfaces/i_margin_service.py`

```
IMarginService (ABC):
    @abstractmethod
    async def get_required_margin(
        self,
        instrument_token: int,
        lots: int,
        timeout_seconds: float,
    ) -> Decimal: ...
    # Raises: MarginDataUnavailableError on API timeout or broker error
```

---

#### `src/core/domain/interfaces/i_kill_switch_repository.py`

```
IKillSwitchRepository (ABC):
    @abstractmethod
    async def get_state(self) -> KillSwitchState: ...
    # FAIL_CLOSED: raises DataSourceUnavailableError if Redis unavailable
    # Caller treats unavailability as is_active=True (checked in RiskEngineService)
    
    @abstractmethod
    async def activate(
        self,
        reason: str,
        activated_by: str,
        trigger_source: str,
    ) -> None: ...
    
    @abstractmethod
    async def deactivate(
        self,
        deactivated_by: str,
        note: str,
        override_loss_check: bool = False,
    ) -> None: ...
```

---

### 1.3 Domain Exceptions — `src/core/domain/exceptions/`

#### `src/core/domain/exceptions/risk.py`

```
RiskDecisionPersistenceError(Exception)
DataSourceUnavailableError(Exception)
    source: str   — which data source failed
MarginDataUnavailableError(DataSourceUnavailableError)
GreeksUnavailableError(DataSourceUnavailableError)
ConcurrentEvaluationError(Exception)   — raised if evaluate() is called while lock is held
UnsupportedInstrumentClassError(Exception)
```

---

### 1.4 Application Layer — `src/core/application/services/`

---

#### `src/core/application/services/risk_engine_service.py`

**Purpose:** Orchestrates the full pre-trade evaluation flow.

**Dependencies (injected):**
- `account_state_repository: IAccountStateRepository`
- `portfolio_state_repository: IPortfolioStateRepository`
- `greeks_repository: IGreeksRepository`
- `correlation_repository: ICorrelationRepository`
- `margin_service: IMarginService`
- `kill_switch_repository: IKillSwitchRepository`
- `risk_decision_repository: IRiskDecisionRepository`
- `signal_performance_repository: ISignalPerformanceRepository`
- `limit_checker: RiskLimitChecker`
- `position_sizer: PositionSizer`
- `event_bus: IEventBus`
- `config: RiskConfig`

**IAIProvider: FORBIDDEN.**

**Evaluation flow (matches PHASE_13_REMEDIATION_PLAN.md Section 2):**
1. Acquire `self._evaluation_lock` (asyncio.Lock)
2. Validate instrument class — raise `UnsupportedInstrumentClassError` for non-FnO
3. `asyncio.gather(..., return_exceptions=True)` for all 7 data sources
4. Inspect gather results; apply FAIL_CLOSED policies; return REJECTED if any reject-policy source failed
5. Run 15 checks sequentially using `RiskLimitChecker`
6. Run `PositionSizer.compute()` on success
7. Build `RiskDecision` object
8. INSERT to `risk_decisions` via `asyncio.wait_for(..., timeout=0.1)` — REJECTED on failure or timeout
9. Populate `risk_decision.risk_decision_id` from INSERT result
10. Publish event (3 retries → pending list → alternative alert)
11. Release lock; return decision

---

#### `src/core/application/services/portfolio_monitor.py`

**Purpose:** Background 30-second loop. Computes MTM P&L, updates graduated response state, updates HWM, triggers kill switch if limits breached.

**Dependencies (injected):**
- `account_state_repository: IAccountStateRepository`
- `portfolio_state_repository: IPortfolioStateRepository`
- `kill_switch_repository: IKillSwitchRepository`
- `kill_switch_service: KillSwitchService`
- `event_bus: IEventBus`
- `config: RiskConfig`
- `redis_client: Redis`

**Loop body:**
1. Fetch account state
2. Check daily loss → update graduated response → publish `GraduatedResponseActivated` if changed
3. Check weekly loss → publish `WeeklyLossLimitBreached` if breached
4. Check drawdown → update HWM → publish `HighWaterMarkUpdated` if HWM increased
5. Check margin utilization → publish `MarginAlertBreached` if > `margin.utilization_limit_pct`
6. If daily loss at 100% OR drawdown at 100%: activate kill switch

---

#### `src/core/application/services/kill_switch_service.py`

**Purpose:** Wraps the kill switch lifecycle. Sole writer to `system:kill_switch`.

**Dependencies:**
- `kill_switch_repository: IKillSwitchRepository`
- `kill_switch_events_repository: IKillSwitchEventsRepository`
- `event_bus: IEventBus`

**IAIProvider: FORBIDDEN.**

**Public methods:**
```
async def activate(reason: str, activated_by: str, trigger_source: str) -> None
async def deactivate(deactivated_by: str, note: str, override_loss_check: bool = False) -> None
async def get_state() -> KillSwitchState
async def startup_check() -> bool   — reads state; returns is_active
```

**Activation sequence (6 steps per Doc 14):**
1. `HSET system:kill_switch` (atomic Redis write)
2. Publish `KillSwitchActivated` event
3. Set in-memory flag (if OMS is in-process)
4. Cancel all open orders (async, 15s timeout)
5. `INSERT INTO kill_switch_events`
6. Send alert

---

### 1.5 Infrastructure Layer

---

#### `src/core/infrastructure/database/models/risk_models.py`

**Purpose:** SQLAlchemy ORM model for `risk_decisions`. Append-only.

```
RiskDecisionModel:
    id: BigInteger PRIMARY KEY AUTOINCREMENT
    signal_id: UUID NOT NULL
    approved: Boolean NOT NULL
    rejection_code: String(50)
    rejection_reason: Text
    position_size_lots: Integer
    size_reduction_pct: Numeric(5,2)
    checks: JSONB NOT NULL
    account_snapshot: JSONB NOT NULL
    sizing_snapshot: JSONB
    failed_data_sources: JSONB
    evaluated_at: DateTime(timezone=True) NOT NULL DEFAULT NOW()
    risk_decision_id: BigInteger  ← same as id; alias for API clarity
```

**Note:** `kill_switch_events` is already defined in Doc 14. Its ORM model is in `risk_models.py` as a second model in the same file.

```
KillSwitchEventModel:
    id: BigInteger PRIMARY KEY AUTOINCREMENT
    event_type: String(20) NOT NULL  — ACTIVATED | DEACTIVATED
    triggered_by: String(50) NOT NULL
    trigger_source: String(30) NOT NULL
    reason: Text NOT NULL
    metadata: JSONB
    created_at: DateTime(timezone=True) NOT NULL DEFAULT NOW()
    user_id: Integer FK → users (nullable)
```

---

#### `src/core/infrastructure/database/repositories/risk_decision_repository.py`

**Purpose:** Implements `IRiskDecisionRepository`. Inserts only; no reads for Phase 13.

**Key constraint:** `async def insert(...)` raises `RiskDecisionPersistenceError` on DB error. The caller wraps with `asyncio.wait_for(timeout=0.1)`.

---

#### `src/core/infrastructure/cache/kill_switch_repository.py`

**Purpose:** Implements `IKillSwitchRepository`. All operations target `system:kill_switch` Hash with no TTL.

**Key operations:**
- `HGETALL system:kill_switch` — for `get_state()`
- `HSET system:kill_switch field1 val1 field2 val2 ...` — for `activate()` and `deactivate()`
- Never calls `EXPIRE` or `PEXPIRE` on this key
- On `ConnectionError`: `get_state()` raises `DataSourceUnavailableError` (caller applies FAIL_CLOSED)

---

#### `src/core/infrastructure/cache/account_state_repository.py`

**Purpose:** Implements `IAccountStateRepository`. Reads `risk:account_state` Hash from Redis.

**Key constraint:** On `ConnectionError` or missing key: raises `DataSourceUnavailableError`.

---

#### `src/core/infrastructure/cache/portfolio_state_repository.py`

**Purpose:** Implements `IPortfolioStateRepository`. Reads `risk:portfolio_state` and `risk:graduated_response` Hashes.

**Key constraint:** Same FAIL_CLOSED on connection error.

---

#### `src/core/infrastructure/cache/greeks_repository.py`

**Purpose:** Implements `IGreeksRepository`. Two-tier cache.

**Write contract:**
```
async def write_greeks(position_id, snapshot):
    pipe = redis.pipeline()
    pipe.hset(f"risk:greeks:{position_id}", mapping=fields)
    pipe.expire(f"risk:greeks:{position_id}", 60)
    pipe.hset(f"risk:greeks:fallback:{position_id}", mapping=fields)
    pipe.expire(f"risk:greeks:fallback:{position_id}", 300)
    await pipe.execute()   ← atomic pipeline
```

**Read contract:**
```
async def get_portfolio_greeks(position_ids, max_age_seconds, new_position_grace_seconds):
    For each position_id:
        Try Tier 1 (risk:greeks:{id}): check computed_at age ≤ max_age_seconds
        If stale or miss: try Tier 2 (risk:greeks:fallback:{id})
        If both miss: return None for this position_id (caller applies FAIL_CLOSED)
```

---

#### `src/core/infrastructure/cache/correlation_repository.py`

**Purpose:** Implements `ICorrelationRepository`. Reads `risk:correlation_matrix` JSON string.

**Miss behavior:** Returns `{}` (empty dict). Caller applies CONSERVATIVE_DEFAULT (ρ=1.0 for any missing pair).

---

#### `src/core/infrastructure/broker/margin_service.py`

**Purpose:** Implements `IMarginService`. Calls broker API for margin requirement.

**Key constraint:** Wrapped in `asyncio.wait_for(timeout=0.15)` inside the service. Raises `MarginDataUnavailableError` on timeout or broker error.

---

#### `src/core/infrastructure/database/repositories/kill_switch_events_repository.py`

**Purpose:** INSERT-only repository for `kill_switch_events`. The application DB user has INSERT permission only.

```
IKillSwitchEventsRepository (ABC):
    async def insert_event(
        event_type: str,
        triggered_by: str,
        trigger_source: str,
        reason: str,
        metadata: dict | None,
        user_id: int | None,
    ) -> None
```

---

### 1.6 Configuration

#### `src/core/infrastructure/config/risk_config.py` (REWRITE — see Section 2)

---

### 1.7 Test Files To Create

See Section 8 (Testing Strategy) for the complete test matrix.

---

## Section 2 — Files To Modify

### 2.1 `config/risk.yaml` — Update to version 2.0

Replace the current file entirely with the schema defined in PHASE_13_REMEDIATION_PLAN.md Section 3. Key changes:
- Version: "1.0" → "2.0"
- `capital.capital_at_risk_pct` → `capital.risk_per_trade_pct`
- `daily_loss.graduated_response_pct` → `daily_loss.graduated_response.reduce_size_at_pct` + add `paper_mode_at_pct` and `kill_switch_at_pct`
- Add `daily_loss.limit_abs: 10000`
- Add `weekly_loss.limit_abs: 25000`
- `position_limits.max_open_positions`: 5 → 10
- `position_limits.max_positions_per_symbol: 1` → `max_positions_per_underlying: 3`
- `position_limits.max_capital_per_symbol_pct` → `max_capital_per_underlying_pct`
- Add `position_limits.max_notional_per_trade_pct: 10`
- `order_rate.max_orders_per_minute`: 10 → 5
- Add `order_rate.max_orders_per_day: 50`
- `greeks.max_net_delta`: 500.0 → 2500 (unit: INR/point)
- Add `greeks.max_net_gamma_pct: 0.1`
- `greeks.max_vega_exposure: 10000.0` → `max_net_vega_pct: 5.0`
- Add `greeks.max_theta_daily_decay_pct: 0.5`
- Add `greeks.max_age_seconds: 120`
- Add `greeks.new_position_grace_seconds: 90`
- Add `greeks.fallback_ttl_seconds: 300`
- Add `margin.utilization_limit_pct: 80`
- Add `margin.min_free_margin_pct: 20`
- `risk_reward.minimum_ratio` → `min_ratio`; add `max_ratio: 10.0`
- `position_sizing.atr_stop_multiplier`: 2.0 → 1.5
- Add `position_sizing.max_position_size_lots: 50`
- Add `position_sizing.min_kelly_samples: 30`
- Add `position_sizing.kelly_min_sample_fallback: 0.05`
- Add `db.risk_decisions_insert_timeout_ms: 100`
- Add `redis_fail_safe` section (7 entries)

---

### 2.2 `src/core/infrastructure/config/risk_config.py` — Rewrite for v2.0

**Current schema** (13 Pydantic fields across 9 sub-models) is incompatible with v2.0. Full rewrite required.

**New sub-models to define:**

```python
class GraduatedResponseConfig(BaseModel):
    reduce_size_at_pct: float
    paper_mode_at_pct: float
    kill_switch_at_pct: float

class DailyLossConfig(BaseModel):
    limit_pct: float
    limit_abs: int
    graduated_response: GraduatedResponseConfig

class WeeklyLossConfig(BaseModel):
    limit_pct: float
    limit_abs: int

class PositionLimitsConfig(BaseModel):
    max_open_positions: int
    max_positions_per_underlying: int
    max_capital_per_underlying_pct: float
    max_capital_per_sector_pct: float
    max_notional_per_trade_pct: float

class OrderRateConfig(BaseModel):
    max_orders_per_minute: int
    max_orders_per_day: int

class GreeksConfig(BaseModel):
    max_net_delta: float           # INR/point
    max_net_gamma_pct: float
    max_net_vega_pct: float
    max_theta_daily_decay_pct: float
    max_age_seconds: int
    new_position_grace_seconds: int
    fallback_ttl_seconds: int

class MarginConfig(BaseModel):
    utilization_limit_pct: float
    min_free_margin_pct: float

class RiskRewardConfig(BaseModel):
    min_ratio: float
    max_ratio: float

class PositionSizingConfig(BaseModel):
    method: str
    kelly_fraction: float
    atr_period: int
    atr_stop_multiplier: float
    max_position_size_lots: int
    min_kelly_samples: int
    kelly_min_sample_fallback: float

class RedisFailSafeConfig(BaseModel):
    account_state: str             # "FAIL_CLOSED"
    portfolio_state: str
    graduated_response_state: str
    greeks_cache: GreeksCacheFailSafeConfig
    correlation_matrix: CorrelationFailSafeConfig
    margin_required: str

class DbConfig(BaseModel):
    risk_decisions_insert_timeout_ms: int

class RiskConfig(BaseModel):
    version: str
    capital: CapitalConfig
    daily_loss: DailyLossConfig
    weekly_loss: WeeklyLossConfig
    drawdown: DrawdownConfig
    position_limits: PositionLimitsConfig
    order_rate: OrderRateConfig
    greeks: GreeksConfig
    margin: MarginConfig
    risk_reward: RiskRewardConfig
    position_sizing: PositionSizingConfig
    redis_fail_safe: RedisFailSafeConfig
    db: DbConfig
```

**Impact:** `RiskConfig` is already registered in `container.py` as a singleton. The container registration does not change — only the schema changes. Existing tests that use `load_risk_config()` must be updated after the yaml is updated.

---

### 2.3 `src/core/domain/events/risk_events.py` — Complete 12-Event Schema

Replace the current 5-event file with the complete 12-event schema defined in PHASE_13_FINAL_READINESS_REVIEW.md H-6 resolution.

**Events to add (7 new):**
- `WeeklyLossLimitBreached`
- `KillSwitchActivated`
- `KillSwitchDeactivated`
- `HighWaterMarkUpdated`
- `PaperModeActivated`
- `MarginAlertBreached`
- `DataSourceUnavailable`

**Events to update (3 existing):**
- `RiskApproved` — add `risk_decision_id: int`, `kelly_fraction_effective: float`, `sizing_note: str | None`
- `RiskRejected` — add `checks_passed_count: int`
- `GraduatedResponseActivated` — add `state: str` field

---

### 2.4 `src/container.py` — Phase 13 Provider Block

Add a Phase 13 section after the Phase 12 block. Providers to register:

```python
# -------------------------------------------------------------------------
# Phase 13 — Risk Engine
# -------------------------------------------------------------------------

risk_decision_repository = providers.Singleton(
    SqlAlchemyRiskDecisionRepository,
    session_factory=db_session_factory,
)

kill_switch_events_repository = providers.Singleton(
    SqlAlchemyKillSwitchEventsRepository,
    session_factory=db_session_factory,
)

kill_switch_repository = providers.Singleton(
    RedisKillSwitchRepository,
    redis_client=redis_client,
)

account_state_repository = providers.Singleton(
    RedisAccountStateRepository,
    redis_client=redis_client,
)

portfolio_state_repository = providers.Singleton(
    RedisPortfolioStateRepository,
    redis_client=redis_client,
)

greeks_repository = providers.Singleton(
    RedisGreeksRepository,
    redis_client=redis_client,
    config=risk_config,
)

correlation_repository = providers.Singleton(
    RedisCorrelationRepository,
    redis_client=redis_client,
)

margin_service = providers.Singleton(
    KiteMarginService,
    broker=kite_broker,
    config=risk_config,
)

risk_limit_checker = providers.Singleton(RiskLimitChecker)

position_sizer = providers.Singleton(PositionSizer)

kill_switch_service = providers.Singleton(
    KillSwitchService,
    kill_switch_repository=kill_switch_repository,
    kill_switch_events_repository=kill_switch_events_repository,
    event_bus=event_bus,
)

risk_engine_service = providers.Singleton(
    RiskEngineService,
    account_state_repository=account_state_repository,
    portfolio_state_repository=portfolio_state_repository,
    greeks_repository=greeks_repository,
    correlation_repository=correlation_repository,
    margin_service=margin_service,
    kill_switch_repository=kill_switch_repository,
    risk_decision_repository=risk_decision_repository,
    signal_performance_repository=signal_performance_repository,
    limit_checker=risk_limit_checker,
    position_sizer=position_sizer,
    event_bus=event_bus,
    config=risk_config,
)

portfolio_monitor = providers.Singleton(
    PortfolioMonitor,
    account_state_repository=account_state_repository,
    portfolio_state_repository=portfolio_state_repository,
    kill_switch_service=kill_switch_service,
    event_bus=event_bus,
    config=risk_config,
    redis_client=redis_client,
)
```

**Note the comment in the existing container:**
```
# Phase 14 — Risk Engine          (populated in Phase 14)
```
This comment is now Phase 13. Update accordingly.

---

### 2.5 `src/core/infrastructure/database/models/__init__.py`

Add `from core.infrastructure.database.models.risk_models import RiskDecisionModel, KillSwitchEventModel`.

---

### 2.6 `src/main.py`

Add startup kill switch check (Constraint 20):

```python
@app.on_event("startup")
async def startup_risk_checks():
    container = ApplicationContainer()
    kill_switch_svc = container.kill_switch_service()
    is_active = await kill_switch_svc.startup_check()
    if is_active:
        logger.critical("kill_switch_active_at_startup — trading components initialized in BLOCKED state")
    
    portfolio_monitor = container.portfolio_monitor()
    asyncio.create_task(portfolio_monitor.start())
```

---

## Section 3 — Database Migration Plan

### Migration: `004_phase13_risk_engine`

**File:** `alembic/versions/20260613_1000_phase13_risk_engine.py`  
**Revision:** `004_phase13`  
**Revises:** `003_phase12`

**`upgrade()` steps:**

1. Create `risk_decisions` table:
```sql
CREATE TABLE risk_decisions (
    id                  BIGSERIAL PRIMARY KEY,
    signal_id           UUID NOT NULL,
    approved            BOOLEAN NOT NULL,
    rejection_code      VARCHAR(50),
    rejection_reason    TEXT,
    position_size_lots  INTEGER,
    size_reduction_pct  NUMERIC(5,2),
    checks              JSONB NOT NULL,
    account_snapshot    JSONB NOT NULL,
    sizing_snapshot     JSONB,
    failed_data_sources JSONB,
    evaluated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

2. Create indexes on `risk_decisions`:
```sql
CREATE INDEX idx_risk_decisions_signal_id ON risk_decisions (signal_id);
CREATE INDEX idx_risk_decisions_approved ON risk_decisions (approved, evaluated_at DESC);
CREATE INDEX idx_risk_decisions_evaluated_at ON risk_decisions (evaluated_at DESC);
CREATE INDEX idx_risk_decisions_rejection_code ON risk_decisions (rejection_code) WHERE rejection_code IS NOT NULL;
```

3. Create `kill_switch_events` table:
```sql
CREATE TABLE kill_switch_events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      VARCHAR(20) NOT NULL,
    triggered_by    VARCHAR(50) NOT NULL,
    trigger_source  VARCHAR(30) NOT NULL,
    reason          TEXT NOT NULL,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id         INTEGER REFERENCES users(id)
);
```

4. Create index on `kill_switch_events`:
```sql
CREATE INDEX idx_kill_switch_events_created_at ON kill_switch_events (created_at DESC);
CREATE INDEX idx_kill_switch_events_event_type ON kill_switch_events (event_type, created_at DESC);
```

5. Apply DB-level permissions (app user = `app_user`):
```sql
REVOKE UPDATE, DELETE ON kill_switch_events FROM app_user;
REVOKE UPDATE, DELETE ON risk_decisions FROM app_user;
-- Note: These are defense-in-depth; primary protection is no UPDATE/DELETE in repo code.
```

6. Convert `risk_decisions` to TimescaleDB hypertable (partitioned by `evaluated_at`):
```sql
SELECT create_hypertable('risk_decisions', 'evaluated_at', chunk_time_interval => INTERVAL '1 day');
```

**`downgrade()` steps:**
```sql
DROP TABLE IF EXISTS kill_switch_events;
DROP TABLE IF EXISTS risk_decisions;
```

**Pre-migration check:** Assert chain is `003_phase12` → `004_phase13`. Migration must not run if `risk_decisions` already exists (idempotency guard in upgrade).

---

## Section 4 — Redis Key Usage Plan

All Phase 13 Redis keys follow the convention `{namespace}:{scope}:{identifier}`.

| Key | Type | TTL | Writer | Readers | FAIL_CLOSED? |
|-----|------|-----|--------|---------|--------------|
| `system:kill_switch` | Hash | None | `KillSwitchService` only | `KillSwitchRepository`, OMS | Yes — treat as active if unavailable |
| `risk:account_state` | Hash | 30s | `AccountStatePoller` (Phase 16) | `RiskEngineService`, `PortfolioMonitor` | Yes — REJECTED |
| `risk:portfolio_state` | Hash | 60s | `PortfolioMonitor` | `RiskEngineService` | Yes — REJECTED |
| `risk:graduated_response` | Hash | None | `PortfolioMonitor` | `RiskEngineService` | Yes — multiplier=0.0 |
| `risk:greeks:{position_id}` | Hash | 60s | `GreeksComputeService` | `RiskEngineService` | Tier 2 fallback first |
| `risk:greeks:fallback:{position_id}` | Hash | 300s | `GreeksComputeService` | `RiskEngineService` | Yes — REJECTED if both miss |
| `risk:correlation_matrix` | String (JSON) | 24h | `CorrelationService` (Phase 16) | `RiskEngineService` | Conservative default: ρ=1.0 |
| `risk:hwm:{yyyy-mm-dd}` | String | 35d | `PortfolioMonitor` | `PortfolioMonitor` | N/A — computed from DB on miss |
| `risk:approvals_pending_delivery` | List | None | `RiskEngineService` | `DeliveryReconciler` (Phase 15+) | N/A — this IS the fallback |

### `system:kill_switch` Hash Field Specification

```
is_active:           "true" | "false"
activated_at:        ISO 8601 UTC | ""
activated_by:        "operator" | "risk_engine" | "dead_mans_switch" | "system" | ""
activation_reason:   str | ""
deactivated_at:      ISO 8601 UTC | ""
deactivated_by:      str | ""
deactivation_note:   str | ""
```

**Phase 13 initialization:** On first startup with no existing key: `HSET system:kill_switch is_active false`. Treat missing key as inactive (not as FAIL_CLOSED — a missing key at first-ever startup is not an outage).

### `risk:graduated_response` Hash Field Specification

```
state:                     "NORMAL" | "REDUCED" | "PAPER" | "KILLED"
position_size_multiplier:  "1.0" | "0.5" | "0.0"
activated_at:              ISO 8601 | ""
reason:                    str | ""
```

Initial value (written at market open by PortfolioMonitor): `state=NORMAL, position_size_multiplier=1.0`.

---

## Section 5 — Event Schema Implementation Plan

### Implementation Order

Events must be defined in `risk_events.py` **before** any service code is written. All 12 events are in the same file.

### Implementation Sequence

1. Update existing `RiskApproved` — add 3 fields (backward-compatible: no consumer exists yet)
2. Update existing `RiskRejected` — add 1 field
3. Update existing `GraduatedResponseActivated` — add `state: str` field (CRITICAL — without this field, consumers cannot identify the graduated tier)
4. Add `WeeklyLossLimitBreached`
5. Add `KillSwitchActivated`
6. Add `KillSwitchDeactivated`
7. Add `HighWaterMarkUpdated`
8. Add `PaperModeActivated`
9. Add `MarginAlertBreached`
10. Add `DataSourceUnavailable`

### Event-to-Publisher Mapping

| Event | Publisher | Trigger |
|-------|-----------|---------|
| `RiskApproved` | `RiskEngineService` | After successful DB INSERT and event publish |
| `RiskRejected` | `RiskEngineService` | Any check failure or data source failure |
| `DailyLossLimitBreached` | `PortfolioMonitor` | Daily loss consumed = 100% |
| `WeeklyLossLimitBreached` | `PortfolioMonitor` | Weekly loss consumed = 100% |
| `DrawdownLimitBreached` | `PortfolioMonitor` | Drawdown ≥ max_drawdown_pct |
| `GraduatedResponseActivated` | `PortfolioMonitor` | Any graduated response state transition |
| `PaperModeActivated` | `PortfolioMonitor` | State transitions to PAPER |
| `KillSwitchActivated` | `KillSwitchService` | Activation (Step 2 in Doc 14 sequence) |
| `KillSwitchDeactivated` | `KillSwitchService` | Deactivation |
| `HighWaterMarkUpdated` | `PortfolioMonitor` | New HWM established |
| `MarginAlertBreached` | `PortfolioMonitor` | Margin utilization > limit_pct |
| `DataSourceUnavailable` | `RiskEngineService` | Data source FAIL_CLOSED triggered |

### Event Topics (from Doc 11)

| Event | Topic |
|-------|-------|
| `RiskApproved` | `signal.risk.approved` |
| `RiskRejected`, `DataSourceUnavailable` | `signal.risk.rejected` |
| `DailyLossLimitBreached`, `WeeklyLossLimitBreached` | `risk.limit.breached` |
| `DrawdownLimitBreached`, `GraduatedResponseActivated`, `PaperModeActivated`, `HighWaterMarkUpdated` | `risk.drawdown.alert` |
| `MarginAlertBreached` | `risk.margin.alert` |
| `KillSwitchActivated` | `system.kill_switch.activated` |
| `KillSwitchDeactivated` | `system.kill_switch.deactivated` |

---

## Section 6 — Dependency Injection Registration Plan

### Dependency Graph (Phase 13 additions only)

```
redis_client ──────────────────────┐
                                   ▼
                   RedisKillSwitchRepository ──► KillSwitchService ──► RiskEngineService
                                                         │
                                   ┌─────────────────────┘
                                   ▼
                   SqlAlchemyKillSwitchEventsRepository

redis_client ──► RedisAccountStateRepository ──┐
redis_client ──► RedisPortfolioStateRepository ─┼─► RiskEngineService
redis_client ──► RedisGreeksRepository ─────────┤
redis_client ──► RedisCorrelationRepository ────┤
                                                │
kite_broker ───► KiteMarginService ─────────────┤
                                                │
db_session_factory ──► SqlAlchemyRiskDecisionRepository ──► RiskEngineService
db_session_factory ──► SqlAlchemySignalPerformanceRepository (reused from Phase 12)
                                                │
risk_config ────────────────────────────────────┤
event_bus ──────────────────────────────────────┘
                                                │
                   RiskLimitChecker (stateless) ─┤
                   PositionSizer    (stateless) ──┘

PortfolioMonitor:
    RedisAccountStateRepository
    RedisPortfolioStateRepository
    KillSwitchService
    event_bus
    risk_config
    redis_client
```

### Provider Registration Order in container.py

Providers must be declared in dependency order (dependencies before dependents):

1. `risk_decision_repository`
2. `kill_switch_events_repository`
3. `kill_switch_repository`
4. `account_state_repository`
5. `portfolio_state_repository`
6. `greeks_repository`
7. `correlation_repository`
8. `margin_service`
9. `risk_limit_checker`
10. `position_sizer`
11. `kill_switch_service` (depends on 2, 3, event_bus)
12. `risk_engine_service` (depends on 1, 4–10, 11, event_bus, risk_config, signal_performance_repository)
13. `portfolio_monitor` (depends on 4, 5, 11, event_bus, risk_config, redis_client)

---

## Section 7 — Configuration Implementation Plan

### Step 1: Update `config/risk.yaml`

Replace with v2.0 schema from PHASE_13_REMEDIATION_PLAN.md Section 3. File must be committed before any code that reads it is written.

### Step 2: Rewrite `risk_config.py`

Replace all Pydantic models to match v2.0 schema. The `load_risk_config()` function signature does not change — only the returned `RiskConfig` type changes.

### Step 3: Update existing risk_config tests

`tests/unit/infrastructure/config/test_risk_config.py` must be updated to test against the new schema fields. All existing field tests must be adapted or replaced.

### Configuration Access Pattern

All Phase 13 services access config through the injected `RiskConfig` singleton:

```python
# In RiskEngineService:
max_positions = self._config.position_limits.max_open_positions
timeout_ms = self._config.db.risk_decisions_insert_timeout_ms / 1000  # convert to seconds

# In PositionSizer:
min_samples = config.position_sizing.min_kelly_samples
max_lots = config.position_sizing.max_position_size_lots
fallback = config.position_sizing.kelly_min_sample_fallback

# In RiskLimitChecker:
delta_limit = config.greeks.max_net_delta   # INR/point
vega_limit = config.greeks.max_net_vega_pct  # % of capital
```

**Zero hardcoded values.** No magic numbers anywhere in Phase 13 code.

---

## Section 8 — Testing Strategy

### Test Matrix

| Test File | Type | Tests | Coverage Target |
|-----------|------|-------|----------------|
| `tests/unit/domain/risk/test_account_state.py` | Unit | ~8 | AccountState construction, immutability |
| `tests/unit/domain/risk/test_portfolio_state.py` | Unit | ~6 | PortfolioState construction |
| `tests/unit/domain/risk/test_risk_request.py` | Unit | ~8 | RiskRequest field validation |
| `tests/unit/domain/risk/test_risk_decision.py` | Unit | ~12 | RiskDecision construction, RiskRejectionCode enum, all codes |
| `tests/unit/domain/risk/test_risk_limit_checker.py` | Unit | ~60 | Each of 15 checks: pass + fail case; boundary values; ThetaDecay warn-only |
| `tests/unit/domain/risk/test_position_sizer.py` | Unit | ~20 | ATR lots, Kelly lots, four layers (sample guard, zero-loss, negative kelly, hard cap), graduated response, POSITION_SIZE_ZERO |
| `tests/unit/domain/risk/test_kill_switch_state.py` | Unit | ~6 | KillSwitchState construction |
| `tests/unit/domain/events/test_risk_events.py` | Unit | ~24 | All 12 events: construction, frozen, all fields |
| `tests/unit/application/services/test_risk_engine_service.py` | Unit | ~50 | Full evaluation flow, FAIL_CLOSED per source, persistence-first, three-tier delivery, lock contention |
| `tests/unit/application/services/test_portfolio_monitor.py` | Unit | ~20 | 30s loop, graduated response transitions, kill switch trigger, HWM update, margin alert |
| `tests/unit/application/services/test_kill_switch_service.py` | Unit | ~15 | Activation sequence, startup check, deactivation, idempotency |
| `tests/unit/infrastructure/cache/test_kill_switch_repository.py` | Unit | ~12 | HGETALL, HSET, no TTL set, FAIL_CLOSED on connection error |
| `tests/unit/infrastructure/cache/test_account_state_repository.py` | Unit | ~8 | Hash read, field parsing, FAIL_CLOSED |
| `tests/unit/infrastructure/cache/test_portfolio_state_repository.py` | Unit | ~10 | Hash read, graduated_response read, FAIL_CLOSED |
| `tests/unit/infrastructure/cache/test_greeks_repository.py` | Unit | ~16 | Two-tier write (atomic), two-tier read priority, age check, new-position grace, both-miss |
| `tests/unit/infrastructure/cache/test_correlation_repository.py` | Unit | ~6 | JSON read, miss returns empty dict |
| `tests/unit/infrastructure/config/test_risk_config.py` | Unit | ~20 | All v2.0 fields, invalid values, missing required fields |
| `tests/unit/infrastructure/database/test_risk_decision_repository.py` | Unit | ~10 | INSERT returns ID, no UPDATE/DELETE methods exist |
| `tests/integration/test_risk_engine_integration.py` | Integration | ~15 | Full evaluation → DB INSERT → event publish, real Redis + TimescaleDB |

**Estimated total new tests: ~290**  
**Estimated post-Phase-13 test count: 1172 + 290 = ~1462 tests**

### Key Unit Test Scenarios

**RiskEngineService — must test:**

1. `test_evaluation_acquires_and_releases_lock` — verify lock is acquired and released normally
2. `test_concurrent_call_raises_concurrent_evaluation_error` — verify second call while lock held raises
3. `test_kill_switch_active_returns_rejected` — Check 1 fires immediately
4. `test_all_15_checks_run_on_pass` — verify checks list has 15 entries on approval
5. `test_first_failure_stops_checks` — verify subsequent checks are skipped after first failure
6. `test_account_state_unavailable_returns_rejected` — FAIL_CLOSED for account_state
7. `test_portfolio_state_unavailable_returns_rejected` — FAIL_CLOSED
8. `test_greeks_tier2_used_when_tier1_miss` — fallback key used
9. `test_both_greeks_tiers_miss_returns_rejected` — FAIL_CLOSED
10. `test_correlation_matrix_miss_uses_conservative_default` — ρ=1.0 used
11. `test_db_insert_failure_returns_rejected` — persistence-first invariant
12. `test_db_insert_timeout_returns_rejected` — 100ms timeout
13. `test_event_publish_retries_on_failure` — 3 retries
14. `test_event_publish_exhausted_writes_to_pending_list` — pending delivery fallback
15. `test_no_ai_provider_in_dependencies` — assert no IAIProvider in injection chain
16. `test_position_size_zero_returns_rejected` — POSITION_SIZE_ZERO code
17. `test_approved_decision_has_risk_decision_id_populated` — DB ID flows back
18. `test_risk_approved_event_contains_risk_decision_id` — event carries DB ID

**PositionSizer — must test:**

1. `test_kelly_below_minimum_samples_uses_fallback_fraction`
2. `test_kelly_zero_losses_uses_fallback_fraction`
3. `test_kelly_negative_expected_value_returns_zero_lots`
4. `test_kelly_hard_cap_limits_lots`
5. `test_graduated_response_multiplier_applied`
6. `test_session_capital_used_not_live_capital`
7. `test_atr_option_sizing_formula`
8. `test_atr_futures_sizing_formula`
9. `test_min_of_atr_and_kelly_taken`

**RiskLimitChecker — must test (1 pass + 1 fail per check = 30 minimum):**

- `check_kill_switch`: active=True → fail; active=False → pass
- `check_daily_loss`: consumed=100 → fail; consumed=99 → pass
- `check_weekly_loss`: similar
- `check_drawdown`: similar
- `check_open_positions`: at limit → fail; below → pass
- `check_symbol_concentration`: at per-underlying limit → fail
- `check_capital_concentration`: would exceed 20% → fail
- `check_net_delta`: portfolio delta + proposed > limit → fail
- `check_correlation`: effective_concentration > limit → fail
- `check_margin`: available < required → fail
- `check_risk_reward`: R:R < minimum → fail; also R:R > maximum → fail (data error)
- `check_position_size`: lots=0 → fail; lots=1 → pass
- `check_order_rate`: rate exceeded → fail
- `check_theta_decay`: always passes but sets `is_warning=True` when threshold breached
- `check_vega_exposure`: net_vega% > limit → fail

**KillSwitchRepository — must test:**

1. `test_get_state_reads_hash_not_string_key` — verify HGETALL, not GET
2. `test_activate_never_sets_ttl` — verify no EXPIRE call in pipeline
3. `test_unavailable_redis_raises_data_source_unavailable_error`
4. `test_deactivate_sets_is_active_false`

### Test Infrastructure

**Mock pattern:** Use `AsyncMock` for all async repository/service dependencies. Use `MagicMock` for synchronous domain service inputs.

**No real Redis or DB in unit tests.** Unit tests mock all I/O. Integration tests use real infrastructure via test fixtures.

**Fixtures needed:**
- `make_risk_request()` — factory for valid `RiskRequest` with sensible defaults
- `make_account_state()` — factory for `AccountState` with all limits safely below thresholds
- `make_portfolio_state()` — factory for `PortfolioState` with zero positions
- `make_kill_switch_state(is_active=False)` — factory for `KillSwitchState`
- `make_risk_config()` — returns `RiskConfig` loaded from a test-specific yaml fixture

---

## Section 9 — Rollback Strategy

### Pre-Implementation Rollback Point

The `config/risk.yaml` and `src/core/domain/events/risk_events.py` are the first files modified. Both have a clear rollback:

- `config/risk.yaml`: Git revert to v1.0 (current file). `risk_config.py` remains at old schema.
- `risk_events.py`: Git revert to 5-event schema. No downstream consumers exist yet.

### Database Rollback

Migration `004_phase13` has a full `downgrade()` that drops both `risk_decisions` and `kill_switch_events`. Rolling back requires:

```bash
poetry run alembic downgrade 003_phase12
```

This is safe — no other table has a FK referencing these tables yet (the `orders.risk_decision_id FK` is Phase 15 work).

### Redis Rollback

All Phase 13 Redis keys are new keys not used by any existing Phase 1–12 service. Removing them requires no coordination:

```bash
redis-cli DEL system:kill_switch risk:account_state risk:portfolio_state risk:graduated_response
redis-cli DEL risk:correlation_matrix risk:approvals_pending_delivery
# Greeks keys: pattern delete (requires SCAN)
```

### Service Rollback

The `container.py` Phase 13 block is self-contained. Rolling back Phase 13 means removing the block. The Phase 12 confidence engine and all earlier phases are unaffected — no Phase 13 service is injected into any Phase 1–12 service.

### Rollback Trigger Conditions

Rollback is required if any of the following occur during implementation:

1. Test suite fails below 1462 expected tests (regressions in Phase 1–12 tests)
2. `ruff` reports violations in modified files
3. Import of `IAIProvider` found anywhere in Phase 13 code
4. `system:kill_switch` key written with a TTL
5. `risk_decisions` contains an UPDATE or DELETE operation in any repository
6. Any hardcoded numeric risk limit value found outside `risk.yaml` or config tests

---

## Section 10 — Deployment Considerations

### Deployment Order

Phase 13 must be deployed in strict order:

```
Step 1: Update config/risk.yaml to v2.0
         ↓ Validate: load_risk_config() succeeds; all new fields parse

Step 2: Run Alembic migration 004_phase13
         ↓ Validate: risk_decisions and kill_switch_events tables exist
         ↓ Validate: app_user has no UPDATE/DELETE on these tables

Step 3: Deploy application code (all Phase 13 files)
         ↓ Validate: startup kill switch check runs without error
         ↓ Validate: system:kill_switch Hash is initialized (is_active=false)
         ↓ Validate: portfolio_monitor starts its 30s loop

Step 4: Smoke test pre-trade evaluation
         ↓ Submit a test signal with known inputs
         ↓ Verify risk_decisions INSERT occurs
         ↓ Verify signal.risk.approved or signal.risk.rejected event published
         ↓ Verify kill switch check 1 fires first

Step 5: Verify kill switch integration
         ↓ Manually activate kill switch via API
         ↓ Verify system:kill_switch is_active = "true"
         ↓ Verify new evaluation returns REJECTED (KILL_SWITCH_ACTIVE)
         ↓ Deactivate; verify evaluation resumes
```

### Pre-Deployment Checklist

- [ ] `poetry run pytest` passes all 1462 tests (no regressions)
- [ ] `poetry run ruff check .` reports zero violations
- [ ] `config/risk.yaml` version field is "2.0"
- [ ] `system:kill_switch` Redis Hash exists with `is_active = "false"`
- [ ] `risk_decisions` table exists and is a TimescaleDB hypertable
- [ ] `kill_switch_events` table exists with INSERT-only permissions
- [ ] All 12 risk domain events are importable from `risk_events.py`
- [ ] No `IAIProvider` import anywhere in Phase 13 files (`grep -r IAIProvider src/core/domain/risk src/core/application/services/risk*.py src/core/application/services/kill*.py src/core/application/services/portfolio*.py` returns empty)
- [ ] `RiskConfig.version` loads as "2.0" from the container

### Non-Functional Requirements

| Metric | SLO | Validation |
|--------|-----|-----------|
| Pre-trade evaluation latency | P99 < 200ms | Prometheus histogram `risk_engine_check_duration_seconds` |
| `risk_decisions` INSERT latency | P99 < 50ms | Prometheus histogram |
| Kill switch activation latency | P99 < 200ms (Redis write + event publish) | Prometheus histogram |
| Greeks cache hit rate | > 95% during market hours | Counter: hits / (hits + misses) |
| Evaluation lock contention | = 0 (Phase 1) | Counter: `risk_engine_lock_contention_total` |
| `risk:approvals_pending_delivery` depth | = 0 during market hours | Gauge |

---

## Event Flow Diagram

```
signal.confidence.computed
    │
    ▼
RiskEngineService.evaluate(RiskRequest)
    │
    ├── [LOCK acquired]
    │
    ├── asyncio.gather() ──────────────────────────────────────────────────────┐
    │       fetch: kill_switch_state                                           │
    │       fetch: account_state                                               │
    │       fetch: portfolio_state                                             │
    │       fetch: graduated_response_state                                    │
    │       fetch: greeks_cache (Tier1 → Tier2 → None)                        │
    │       fetch: correlation_matrix (miss → ρ=1.0)                          │
    │       fetch: margin_required (broker API, 150ms timeout)                 │
    │                                                                          │
    │   ◄───────────────────────────────────────────────────────────────────────┘
    │
    ├── Exception inspection (C-2 fail-safe policies)
    │       FAIL_CLOSED source failed? ──YES──► RiskDecision(REJECTED)
    │                                           Publish DataSourceUnavailable
    │                                           [LOCK released]
    │                                           return
    │
    ├── 15 Pure Checks (RiskLimitChecker) ─ sequential ─────────────────────
    │       Check 1: KillSwitch
    │       Check 2: DailyLoss
    │       ...
    │       Check 15: VegaExposure
    │           │
    │   First failure ──────────────────────────────────────────────────────►
    │       RiskDecision(approved=False, rejection_code=X)                   │
    │       Publish RiskRejected                                             │
    │       [LOCK released]                                                  │
    │       return                                                           │
    │                                                                        │
    ├── PositionSizer.compute() ◄───────────────────────────────────────────-┘
    │       Layer 1: sample guard
    │       Layer 2: zero-loss edge
    │       Layer 3: raw_kelly floor
    │       Layer 4: hard cap (max_position_size_lots)
    │       × graduated_response.position_size_multiplier
    │           │
    │   final_lots == 0 ──► RiskDecision(POSITION_SIZE_ZERO) ──► return
    │
    ├── DB INSERT ─────────────────────────────────────────────────────────
    │   asyncio.wait_for(
    │       risk_decision_repository.insert(decision),
    │       timeout=0.1
    │   )
    │       OperationalError or TimeoutError ──►
    │           RiskDecision(AUDIT_PERSISTENCE_FAILURE)
    │           [LOCK released]
    │           return
    │
    ├── Publish signal.risk.approved (3-tier delivery) ───────────────────
    │       Attempt 1 ──────────────────────────────────► SUCCESS ──► done
    │       Attempt 2 (200ms later) ───────────────────► SUCCESS ──► done
    │       Attempt 3 (400ms later) ───────────────────► SUCCESS ──► done
    │       All fail ──► LPUSH risk:approvals_pending_delivery
    │                    Pub/Sub alert + file log
    │
    └── [LOCK released]
        return RiskDecision(approved=True, ...)
```

---

## Dependency Diagram

```
                      [Domain Layer — no I/O, no external deps]

  RiskRequest ──────────────────────────────────────────────────┐
  RiskDecision (+ RiskRejectionCode, RiskCheckResult, SizingResult) │
  AccountState                                                  │
  PortfolioState                                                │
  GreeksSnapshot                                                │
  KillSwitchState                                               │
                                                                │
  RiskLimitChecker (pure functions, synchronous) ───────────────┤
  PositionSizer (pure functions, synchronous) ──────────────────┤
                                                                │
  IRiskEngine ──────────────────────────────────────────────────┤
  IRiskDecisionRepository                                       │
  IAccountStateRepository                                       │
  IPortfolioStateRepository                                     │
  IGreeksRepository                                             │
  ICorrelationRepository                                        │
  IMarginService                                                │
  IKillSwitchRepository                                         │
                                                                ▼
                   [Application Layer — async, orchestration only]
                   
  RiskEngineService ──────────────────────────────────────────────
      implements: IRiskEngine
      depends on: ALL interfaces above + IEventBus + ISignalPerformanceRepository
      
  KillSwitchService ──────────────────────────────────────────────
      depends on: IKillSwitchRepository + IKillSwitchEventsRepository + IEventBus
      
  PortfolioMonitor ───────────────────────────────────────────────
      depends on: IAccountStateRepository + IPortfolioStateRepository
                + KillSwitchService + IEventBus + redis_client
      
                   [Infrastructure Layer — concrete implementations]

  RedisKillSwitchRepository ──────── implements IKillSwitchRepository
  RedisAccountStateRepository ─────── implements IAccountStateRepository
  RedisPortfolioStateRepository ────── implements IPortfolioStateRepository
  RedisGreeksRepository ───────────── implements IGreeksRepository
  RedisCorrelationRepository ──────── implements ICorrelationRepository
  KiteMarginService ───────────────── implements IMarginService
  SqlAlchemyRiskDecisionRepository ── implements IRiskDecisionRepository
  SqlAlchemyKillSwitchEventsRepository (INSERT-only)
```

---

## Risk Evaluation Sequence Diagram

```
signal.confidence.computed arrives
      │
      ▼
[RiskEngine Consumer] ──asyncio.Lock──► [RiskEngineService]
                                                │
                              ┌─────────────────┘
                              ▼
                    [asyncio.gather]
                    ┌───────────────────────────────────┐
                    │ RedisKillSwitchRepo.get_state()   │
                    │ RedisAccountStateRepo.get()       │
                    │ RedisPortfolioStateRepo.get()     │
                    │ RedisPortfolioStateRepo.get_grad()│
                    │ RedisGreeksRepo.get_portfolio()   │
                    │ RedisCorrelationRepo.get_matrix() │
                    │ KiteMarginService.get_margin()    │
                    └───────────────────────────────────┘
                              │
                    [Exception inspection + fail-safe]
                              │
                    [RiskLimitChecker] ──15 checks──►
                              │
                    [PositionSizer.compute()]
                              │
                    [asyncio.wait_for 100ms]
                    SqlAlchemyRiskDecisionRepository.insert()
                              │ returns risk_decision_id
                              │
                    [IEventBus.publish(RiskApproved)]
                    [retry × 3 on failure]
                    [LPUSH pending_delivery on exhaustion]
                              │
                    [asyncio.Lock released]
                              │
                    return RiskDecision ──► [Consumer ACK to Redis Stream]
```

---

## Acceptance Criteria

All of the following must be true before Phase 13 is considered complete.

### Functional Acceptance Criteria

- [ ] **AC-1:** A signal that passes all 15 checks results in a `risk_decisions` INSERT and a `signal.risk.approved` event published to Redis Streams.

- [ ] **AC-2:** A signal that fails Check 1 (KillSwitch) results in `rejection_code=KILL_SWITCH_ACTIVE` and no DB INSERT (Kill switch check must come first).

- [ ] **AC-3:** Manually activating the kill switch via API causes all subsequent evaluations to return `rejection_code=KILL_SWITCH_ACTIVE`.

- [ ] **AC-4:** With Redis unavailable (simulated by stopping Redis): all evaluations return `rejection_code=DATA_SOURCE_UNAVAILABLE`. No approvals are published.

- [ ] **AC-5:** With `risk_decisions` INSERT failing (simulated by dropping write permissions): evaluations return `rejection_code=AUDIT_PERSISTENCE_FAILURE`. No `signal.risk.approved` event is published.

- [ ] **AC-6:** Two simultaneous calls to `evaluate()` result in the second call blocking until the first completes (verified by asyncio lock test), not both running concurrently.

- [ ] **AC-7:** When the Greeks Tier 1 cache misses but Tier 2 has data: evaluation succeeds with `from_fallback=True` in the GreeksSnapshot. A WARNING is logged.

- [ ] **AC-8:** When both Greeks tiers miss for a non-grace position: evaluation returns `rejection_code=GREEKS_UNAVAILABLE`.

- [ ] **AC-9:** When a position is < `greeks.new_position_grace_seconds` old: Greeks checks are skipped for that position. Evaluation proceeds.

- [ ] **AC-10:** Kelly sizing with < 30 samples uses the fallback fraction (0.05 × kelly_fraction). The `SizingResult.sizing_note` is `"below_minimum_samples"`.

- [ ] **AC-11:** Kelly sizing with 0 historical losses uses the fallback fraction. The `SizingResult.sizing_note` is `"no_historical_losses"`.

- [ ] **AC-12:** Kelly sizing that would produce > 50 lots is capped at 50. (max_position_size_lots hard cap).

- [ ] **AC-13:** Graduated response at REDUCED (multiplier=0.5): approved lots = floor(normal_lots × 0.5).

- [ ] **AC-14:** Graduated response at PAPER (multiplier=0.0): `final_lots=0` → `rejection_code=POSITION_SIZE_ZERO`.

- [ ] **AC-15:** `GraduatedResponseActivated` event always contains the `state` field (REDUCED, PAPER, or KILLED).

- [ ] **AC-16:** `system:kill_switch` Redis key is a Hash type with no TTL. Verified: `TTL system:kill_switch` returns -1 (no TTL set).

- [ ] **AC-17:** On process restart with `system:kill_switch is_active = "true"`: the application initializes in BLOCKED state without any signals being processed.

- [ ] **AC-18:** `grep -r "IAIProvider" src/core/domain/risk src/core/application/services/risk_engine_service.py src/core/application/services/kill_switch_service.py src/core/application/services/portfolio_monitor.py` returns empty.

- [ ] **AC-19:** No hardcoded numeric risk limit in any Phase 13 file. All limits read from `config.` paths.

- [ ] **AC-20:** `risk_decisions` repository has no `update` or `delete` method. `kill_switch_events` repository has no `update`, `delete`, or `update_many` method.

### Non-Functional Acceptance Criteria

- [ ] **AC-21:** `poetry run pytest` passes ≥ 1462 tests, 0 failures.
- [ ] **AC-22:** `poetry run ruff check .` reports 0 violations.
- [ ] **AC-23:** Pre-trade evaluation latency P99 < 200ms in load test (10 evaluations/second for 60 seconds).
- [ ] **AC-24:** `risk_decisions` INSERT latency P99 < 50ms verified by Prometheus histogram.

---

*Implementation plan approved for Phase 13 code generation. All 24 acceptance criteria must pass before Phase 14 design begins.*  
*Source documents: PHASE_13_FINAL_READINESS_REVIEW.md (20 constraints) · PHASE_13_REMEDIATION_PLAN.md · PHASE_13_RISK_ENGINE_ARCHITECTURE_AUDIT.md*  
*Date: 2026-06-13*
