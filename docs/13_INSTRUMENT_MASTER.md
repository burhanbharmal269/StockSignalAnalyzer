# 13 — Instrument Master

## Purpose

Define the authoritative registry for all tradable instruments across all segments. The Instrument Master is the foundation of the entire platform. Every component that references a symbol, lot size, expiry date, or strike price must source that information from the Instrument Master — never from hardcoded values, environment variables, or in-memory constants.

---

## Design Principles

- Single source of truth for all instrument metadata.
- Refreshed daily from the broker before market open.
- Versioned: every refresh creates a log record, enabling historical reconstruction.
- Cached in Redis for sub-millisecond access during the trading session.
- The domain layer works with `Instrument` value objects; it never reads the DB directly.
- All symbol lookups are case-insensitive and normalize to a canonical form.

---

## Core Domain Model

### Instrument Entity

```
Instrument:
    instrument_token:     int              — broker-assigned unique token (Kite integer ID)
    tradingsymbol:        str              — broker-facing symbol (e.g., NIFTY24JUN23000CE)
    display_symbol:       str              — human-readable (e.g., NIFTY 23000 CE Jun24)
    exchange:             Exchange
    segment:              Segment
    instrument_type:      InstrumentType
    underlying_symbol:    str | None       — e.g., NIFTY for options/futures; None for equity
    isin:                 str | None       — ISIN for equity; None for derivatives
    lot_size:             int              — 1 for equity; SEBI-mandated for FnO
    tick_size:            Decimal          — minimum price movement (e.g., 0.05)
    strike_price:         Decimal | None   — for options only
    option_type:          OptionType | None — CE or PE
    expiry_date:          date | None      — for derivatives only
    is_active:            bool
    last_updated_at:      datetime
```

### Enumerations

```
Exchange:
    NSE
    BSE
    NFO       — NSE FnO segment
    BFO       — BSE FnO segment
    MCX       — Multi Commodity Exchange
    CDS       — Currency Derivatives Segment

Segment:
    NSE_EQ    — NSE equities
    BSE_EQ    — BSE equities
    NSE_FO    — NSE Futures and Options
    BSE_FO    — BSE FnO
    MCX_FO    — MCX commodity derivatives
    CDS_FO    — Currency derivatives

InstrumentType:
    EQ        — equity
    FUT       — futures
    CE        — call option
    PE        — put option
    INDEX     — index (non-tradable; used for regime and scoring reference)

OptionType:
    CE
    PE
```

---

## Database Schema

### `instruments` Table

```
instruments
─────────────────────────────────────────────────────────
instrument_token     INTEGER          PRIMARY KEY
tradingsymbol        VARCHAR(50)      NOT NULL
display_symbol       VARCHAR(100)
exchange             VARCHAR(10)      NOT NULL
segment              VARCHAR(20)      NOT NULL
instrument_type      VARCHAR(10)      NOT NULL
underlying_symbol    VARCHAR(30)
isin                 VARCHAR(12)
lot_size             INTEGER          NOT NULL DEFAULT 1
tick_size            NUMERIC(10,4)    NOT NULL
strike_price         NUMERIC(12,2)
option_type          VARCHAR(2)
expiry_date          DATE
is_active            BOOLEAN          NOT NULL DEFAULT TRUE
last_updated_at      TIMESTAMPTZ      NOT NULL

INDEXES:
  idx_instruments_symbol      ON (tradingsymbol, exchange)
  idx_instruments_underlying  ON (underlying_symbol, expiry_date, strike_price, option_type)
  idx_instruments_expiry      ON (expiry_date, segment)
  idx_instruments_active      ON (is_active, segment)
```

### `instrument_refresh_log` Table

```
instrument_refresh_log
─────────────────────────────────────────────────────────
id                       BIGSERIAL        PRIMARY KEY
refreshed_at             TIMESTAMPTZ      NOT NULL
source                   VARCHAR(50)      NOT NULL  (e.g., 'kite_csv')
instruments_added        INTEGER          NOT NULL
instruments_updated      INTEGER          NOT NULL
instruments_deactivated  INTEGER          NOT NULL
status                   VARCHAR(20)      NOT NULL  (SUCCESS, FAILED, PARTIAL)
error_detail             TEXT
duration_ms              INTEGER
```

### `expiry_calendar` Table

```
expiry_calendar
─────────────────────────────────────────────────────────
id                       BIGSERIAL        PRIMARY KEY
underlying_symbol        VARCHAR(30)      NOT NULL
segment                  VARCHAR(20)      NOT NULL
expiry_date              DATE             NOT NULL
expiry_type              VARCHAR(20)      NOT NULL  (WEEKLY, MONTHLY)
series                   VARCHAR(10)                (e.g., 'JUN24', 'W1')
is_holiday_adjusted      BOOLEAN          NOT NULL DEFAULT FALSE
original_expiry_date     DATE                       (if holiday-adjusted)

UNIQUE: (underlying_symbol, segment, expiry_date)
INDEX:  (underlying_symbol, expiry_date)
```

### `instrument_broker_tokens` Table

Different brokers assign different integer tokens to the same instrument. This table maps canonical symbols to per-broker tokens.

```
instrument_broker_tokens
─────────────────────────────────────────────────────────
id               BIGSERIAL
tradingsymbol    VARCHAR(50)      NOT NULL
exchange         VARCHAR(10)      NOT NULL
broker           VARCHAR(30)      NOT NULL    (e.g., 'kite', 'dhan', 'angel')
broker_token     VARCHAR(50)      NOT NULL
last_updated_at  TIMESTAMPTZ

UNIQUE: (tradingsymbol, exchange, broker)
```

---

## Refresh Lifecycle

### Daily Refresh Schedule

| Time (IST) | Action |
|---|---|
| 07:30 | Download full instrument master CSV from Kite |
| 07:35 | Validate CSV: row count, required columns, sample price checks |
| 07:40 | Diff against existing DB records |
| 07:45 | Apply upserts, mark newly inactive instruments |
| 07:50 | Rebuild Redis cache |
| 07:55 | Publish `system.instrument_master.refreshed` event |
| 08:00 | Readiness check: platform will not start trading without a successful refresh |

### Refresh Validation Rules

- A refresh is FAILED if fewer than 10,000 instruments are returned (NSE alone has 40,000+ FnO rows).
- A refresh is PARTIAL if lot size changes are detected: alert operator before applying, as lot size changes affect position sizing calculations for open positions.
- Instruments present in the DB but absent from the new CSV are marked `is_active = FALSE`, not deleted. Historical trades referencing them remain valid.
- Lot size changes from SEBI circulars take effect from the next expiry series. The system tracks `lot_size_effective_from` date alongside each lot size change.

---

## Expiry Calendar Management

### NSE FnO Expiry Rules

| Product | Standard Expiry Day | Holiday Rule |
|---|---|---|
| NIFTY Weekly | Thursday | If Thursday holiday → Wednesday |
| BANKNIFTY Weekly | Wednesday | If Wednesday holiday → Tuesday |
| FINNIFTY Weekly | Tuesday | If Tuesday holiday → Monday |
| MIDCPNIFTY Weekly | Monday | If Monday holiday → previous Friday |
| Monthly (all) | Last Thursday of month | If holiday → prior Wednesday |
| USDINR Currency | Last business day of month | Per RBI schedule |

### Holiday Adjustment

On a match between an expiry day and a market holiday:
1. Move the expiry to the previous business day.
2. Flag `is_holiday_adjusted = TRUE` and record `original_expiry_date`.
3. Alert operator for manual confirmation if the adjustment is applied mid-session.

Holiday calendar is seeded at system initialization and updated annually when NSE announces changes.

---

## Strike Range Management

For option chain queries and signal generation, the system defines the active strike range for each underlying and expiry.

```
StrikeRange:
    underlying:        str
    expiry_date:       date
    atm_strike:        Decimal     (nearest round lot to current LTP)
    range_itm:         int         (number of ITM strikes to include, default 20)
    range_otm:         int         (number of OTM strikes to include, default 20)
    strike_interval:   Decimal     (e.g., 50 for NIFTY, 100 for BANKNIFTY)
```

ATM strike is recalculated every time LTP crosses a strike boundary. Strike interval is derived from the instrument master (minimum strike gap for the underlying).

---

## Roll-Over Logic

### Definition

Roll-over is the process of closing a near-expiry position and opening the equivalent position in the next expiry. The platform generates roll-over signals but requires operator confirmation before execution in live trading.

### Roll-Over Trigger

| Condition | Action |
|---|---|
| `DTE <= roll_over_warning_dte` (default 3) | Emit roll-over warning notification |
| `DTE <= roll_over_execute_dte` (default 1) AND `position_size > 0` | Generate roll-over signal (pending confirmation) |

### Roll-Over Instrument Selection

Given a position in `NIFTY24JUN23000CE`:
1. Find the active position's expiry date.
2. Query expiry calendar for the next available monthly expiry.
3. Find the equivalent strike in the next expiry (same strike price).
4. If the same strike is not available, select the nearest available active strike.
5. Verify the target strike has minimum liquidity (OI > 500 lots).
6. Create a two-legged signal: SELL current instrument, BUY next expiry instrument.

---

## Caching Architecture

### Redis Data Model

```
Key pattern:   instrument:{instrument_token}
Value:         HSET with all instrument fields
TTL:           Set daily at 07:55 IST, no TTL (manually invalidated on refresh)

Key pattern:   instrument:symbol:{exchange}:{tradingsymbol}
Value:         instrument_token (integer, for reverse lookup)
TTL:           Same as above

Key pattern:   instrument:chain:{underlying}:{expiry_date}
Value:         ZSET where score=strike_price, member=instrument_token (all CE+PE for that expiry)
TTL:           Same as above

Key pattern:   expiry:next:{underlying}:{segment}
Value:         nearest expiry date string
TTL:           Until market close (15:30 IST)
```

A cache miss during live market hours is logged as WARNING — it should not occur if the daily refresh completed successfully.

---

## Instrument Master Service Interface

```
IInstrumentMasterService:
    get_by_token(token: int) -> Instrument
    get_by_symbol(exchange: Exchange, tradingsymbol: str) -> Instrument
    find_option(underlying: str, expiry: date, strike: Decimal, option_type: OptionType) -> Instrument
    get_option_chain(underlying: str, expiry: date) -> list[Instrument]
    get_all_expiries(underlying: str, segment: Segment) -> list[date]
    get_next_expiry(underlying: str, segment: Segment) -> date
    get_monthly_expiry(underlying: str, segment: Segment, month: date) -> date
    get_lot_size(underlying: str, segment: Segment) -> int
    get_atm_strike(underlying: str, expiry: date, ltp: Decimal) -> Decimal
    get_strike_interval(underlying: str) -> Decimal
    is_trading_day(date: date) -> bool
    get_dte(instrument: Instrument) -> int
    refresh() -> InstrumentRefreshResult
```

---

## Lot Size Change Handling

SEBI revises lot sizes periodically (typically every 6 months). Lot size changes affect:
- Position sizing calculations (new lot size ≠ old lot size)
- Historical backtest comparability
- Risk calculations for open positions straddling the change date

**Handling protocol:**
1. The instrument master stores `lot_size_effective_from` alongside `lot_size`.
2. On refresh, if a lot size change is detected, a CRITICAL alert is sent to the operator.
3. Historical positions use the lot size active at trade time, sourced from `trades.lot_size_at_execution`.
4. The backtesting engine applies lot sizes temporally: it uses the correct lot size for each historical date.

---

## Observability

| Metric | Type | Description |
|---|---|---|
| `instrument_master_refresh_duration_seconds` | Histogram | End-to-end refresh time |
| `instrument_master_instruments_total` | Gauge | Total active instruments by segment |
| `instrument_master_lot_size_changes_total` | Counter | Lot size changes detected in current refresh |
| `instrument_master_cache_hit_ratio` | Gauge | Redis cache hit rate |
| `instrument_master_last_refresh_age_seconds` | Gauge | Seconds since last successful refresh |

**Alert:** if `instrument_master_last_refresh_age_seconds > 86400` (24 hours), block trading and notify operator.
