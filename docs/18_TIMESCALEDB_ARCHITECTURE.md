# 18 — TimescaleDB Architecture

## Purpose

Define the time-series data storage strategy for all market data, features, and event logs. This document specifies which tables use TimescaleDB hypertables, the chunk interval and compression policy for each, continuous aggregates for OHLCV rollups, the data retention tier model, index design, connection pool configuration, and the Alembic migration strategy.

---

## Why TimescaleDB

TimescaleDB is the PostgreSQL extension for time-series workloads. Chosen over alternatives for the following reasons:

| Factor | TimescaleDB | QuestDB | InfluxDB |
|---|---|---|---|
| SQL compatibility | Full PostgreSQL | Limited | Flux only |
| JOIN with relational tables | Yes (same DB) | No | No |
| Existing SQLAlchemy stack | Direct reuse | Separate driver | Separate driver |
| Alembic migrations | Supported | Not applicable | Not applicable |
| Compression ratio | 90–97% | ~90% | 85–95% |
| Continuous aggregates | Yes (materialized) | Limited | Yes |
| Operational complexity | Low (Postgres extension) | Moderate | Moderate |
| License | Apache 2.0 (community) | Apache 2.0 | MIT |

The community (free) edition of TimescaleDB supports all features in this design. No paid features are required.

---

## Hypertable Definitions

A hypertable is a PostgreSQL table managed by TimescaleDB with automatic time-based partitioning. To application code and SQLAlchemy ORM, it behaves exactly like a regular PostgreSQL table.

### `market_data` Hypertable

Stores raw tick data and OHLCV candles from broker WebSocket and REST API.

```
market_data
─────────────────────────────────────────────────────────
timestamp           TIMESTAMPTZ     NOT NULL     ← partition key
instrument_token    INTEGER         NOT NULL
tradingsymbol       VARCHAR(50)     NOT NULL
exchange            VARCHAR(10)     NOT NULL
open                NUMERIC(12,2)
high                NUMERIC(12,2)
low                 NUMERIC(12,2)
close               NUMERIC(12,2)   NOT NULL
last_price          NUMERIC(12,2)
volume              BIGINT
buy_quantity        BIGINT
sell_quantity       BIGINT
open_interest       BIGINT
change_pct          NUMERIC(8,4)
data_type           VARCHAR(10)     NOT NULL     (TICK, 1MIN, 5MIN, 15MIN, 1H, 1D)
source              VARCHAR(20)     NOT NULL     (WEBSOCKET, REST, HISTORICAL)

PRIMARY KEY (timestamp, instrument_token)
```

```sql
SELECT create_hypertable('market_data', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    create_default_indexes => FALSE
);
```

### `option_chain` Hypertable

Stores full option chain snapshots.

```
option_chain
─────────────────────────────────────────────────────────
timestamp               TIMESTAMPTZ     NOT NULL
instrument_token        INTEGER         NOT NULL
underlying_symbol       VARCHAR(30)     NOT NULL
expiry_date             DATE            NOT NULL
strike_price            NUMERIC(12,2)   NOT NULL
option_type             VARCHAR(2)      NOT NULL
last_price              NUMERIC(12,2)   NOT NULL
bid_price               NUMERIC(12,2)
ask_price               NUMERIC(12,2)
volume                  BIGINT
open_interest           BIGINT
oi_change               BIGINT
iv                      NUMERIC(8,4)
delta                   NUMERIC(8,6)
gamma                   NUMERIC(10,8)
theta                   NUMERIC(8,6)
vega                    NUMERIC(8,6)

PRIMARY KEY (timestamp, instrument_token)
```

```sql
SELECT create_hypertable('option_chain', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    create_default_indexes => FALSE
);
```

### `market_features` Hypertable

Stores computed technical indicators and derived features.

```
market_features
─────────────────────────────────────────────────────────
timestamp           TIMESTAMPTZ     NOT NULL
instrument_token    INTEGER         NOT NULL
timeframe           VARCHAR(10)     NOT NULL     (1MIN, 5MIN, 15MIN, 1H, 1D)
rsi_14              NUMERIC(8,4)
ema_9               NUMERIC(12,2)
ema_21              NUMERIC(12,2)
ema_50              NUMERIC(12,2)
ema_200             NUMERIC(12,2)
sma_20              NUMERIC(12,2)
vwap                NUMERIC(12,2)
atr_14              NUMERIC(10,4)
macd_line           NUMERIC(10,4)
macd_signal         NUMERIC(10,4)
macd_histogram      NUMERIC(10,4)
adx_14              NUMERIC(8,4)
supertrend          NUMERIC(12,2)
supertrend_dir      SMALLINT             (1=bullish, -1=bearish)
bb_upper            NUMERIC(12,2)
bb_lower            NUMERIC(12,2)
bb_width            NUMERIC(8,4)
relative_volume     NUMERIC(8,4)
volume_sma_20       BIGINT
pcr                 NUMERIC(8,4)
max_pain            NUMERIC(12,2)
iv_rank             NUMERIC(8,4)
iv_percentile       NUMERIC(8,4)
extended_features   JSONB                (overflow for less-common indicators)

PRIMARY KEY (timestamp, instrument_token, timeframe)
```

```sql
SELECT create_hypertable('market_features', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    create_default_indexes => FALSE
);
```

### `signal_events` Hypertable

Immutable event log for every signal state transition.

```
signal_events
─────────────────────────────────────────────────────────
timestamp           TIMESTAMPTZ     NOT NULL
signal_id           UUID            NOT NULL
event_type          VARCHAR(30)     NOT NULL
event_data          JSONB           NOT NULL
correlation_id      VARCHAR(50)
source              VARCHAR(50)

PRIMARY KEY (timestamp, signal_id, event_type)
```

```sql
SELECT create_hypertable('signal_events', 'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    create_default_indexes => FALSE
);
```

### `order_events` Hypertable

Immutable event log for every order state transition.

```
order_events
─────────────────────────────────────────────────────────
timestamp           TIMESTAMPTZ     NOT NULL
order_id            UUID            NOT NULL
broker_order_id     VARCHAR(50)
event_type          VARCHAR(30)     NOT NULL
event_data          JSONB           NOT NULL
correlation_id      VARCHAR(50)

PRIMARY KEY (timestamp, order_id, event_type)
```

```sql
SELECT create_hypertable('order_events', 'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    create_default_indexes => FALSE
);
```

### `signal_performance_stats` Table

Stores per-signal outcome records used by the Confidence Engine for historical accuracy lookup, calibration, and win rate computation. This is a regular relational table (not a hypertable) — it is queried by fingerprint and regime, not by time range.

```
signal_performance_stats
─────────────────────────────────────────────────────────
id                       BIGSERIAL        PRIMARY KEY
fingerprint              VARCHAR(64)      NOT NULL        SHA-256 of (regime+score_bucket+direction+top2_components+vix_bucket)
signal_id                UUID             NOT NULL        FK → signals
instrument               VARCHAR(30)      NOT NULL
instrument_class         VARCHAR(20)      NOT NULL        (INDEX_OPTION, INDEX_FUTURE, STOCK_OPTION, STOCK_FUTURE)
direction                VARCHAR(5)       NOT NULL        (LONG, SHORT)
regime_at_signal         VARCHAR(30)      NOT NULL
score_bucket             VARCHAR(10)      NOT NULL        (STRONG: >=85, STANDARD: 70-84)
vix_bucket               VARCHAR(10)      NOT NULL        (<14, 14-18, 18-22, >22)
top_2_components         VARCHAR(50)[]    NOT NULL        sorted by effective contribution
score                    NUMERIC(5,2)     NOT NULL
confidence               NUMERIC(5,2)     NOT NULL
outcome                  VARCHAR(15)      NOT NULL        (WIN, LOSS, TIME_EXIT)
entry_price              NUMERIC(12,2)    NOT NULL
exit_price               NUMERIC(12,2)    NOT NULL
pnl_bps                  INTEGER          NOT NULL        basis points (currency-independent)
hold_duration_minutes    INTEGER          NOT NULL
dte_at_signal            INTEGER          NOT NULL
confidence_calibration_error NUMERIC(6,3)                predicted_confidence − (actual win flag × 100)
recorded_at              TIMESTAMPTZ      NOT NULL DEFAULT NOW()

INDEXES:
  idx_spstats_fingerprint         ON (fingerprint, recorded_at DESC)
  idx_spstats_regime_direction    ON (regime_at_signal, direction, instrument_class, recorded_at DESC)
  idx_spstats_instrument          ON (instrument, recorded_at DESC)
  idx_spstats_outcome             ON (outcome, regime_at_signal)
```

**Read pattern:** Confidence Engine queries `WHERE fingerprint = ? ORDER BY recorded_at DESC LIMIT 200` for accuracy lookup.  
**Write pattern:** Append-only on position close. No updates. No deletes.  
**Retention:** No automated deletion — this is the historical calibration source. Archive to cold storage after 2 years.

---

## Chunk Interval Summary

| Table | Chunk Interval | Reason |
|---|---|---|
| `market_data` | 1 day | High write volume; 1 chunk = 1 trading day |
| `option_chain` | 1 day | High volume; compress after day close |
| `market_features` | 1 day | Aligned with market_data chunks |
| `signal_events` | 7 days | Lower volume; week-scale queries common |
| `order_events` | 7 days | Same rationale |

---

## Compression Policy

Compression is applied automatically after a chunk is older than the `compress_after` threshold. TimescaleDB's columnar compression achieves 90–97% size reduction on numeric time-series data.

```sql
-- market_data
ALTER TABLE market_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'instrument_token',
    timescaledb.compress_orderby   = 'timestamp DESC'
);
SELECT add_compression_policy('market_data', INTERVAL '7 days');

-- option_chain
ALTER TABLE option_chain SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'underlying_symbol, expiry_date',
    timescaledb.compress_orderby   = 'timestamp DESC'
);
SELECT add_compression_policy('option_chain', INTERVAL '7 days');

-- market_features
ALTER TABLE market_features SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'instrument_token, timeframe',
    timescaledb.compress_orderby   = 'timestamp DESC'
);
SELECT add_compression_policy('market_features', INTERVAL '7 days');

-- signal_events
ALTER TABLE signal_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'signal_id',
    timescaledb.compress_orderby   = 'timestamp DESC'
);
SELECT add_compression_policy('signal_events', INTERVAL '30 days');
```

`compress_segmentby` groups rows of the same `instrument_token` together within a compressed chunk. This dramatically improves query speed when filtering by instrument — the most common access pattern.

---

## Continuous Aggregates

Continuous aggregates are materialized views that TimescaleDB keeps up-to-date as new data arrives. They eliminate the need to scan raw ticks for OHLCV queries.

### 1-Minute OHLCV (from raw ticks)

```sql
CREATE MATERIALIZED VIEW ohlcv_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', timestamp)  AS bucket,
    instrument_token,
    first(open, timestamp)              AS open,
    max(high)                           AS high,
    min(low)                            AS low,
    last(close, timestamp)              AS close,
    last(last_price, timestamp)         AS last_price,
    sum(volume)                         AS volume,
    last(open_interest, timestamp)      AS open_interest
FROM market_data
WHERE data_type = 'TICK'
GROUP BY bucket, instrument_token
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_1min',
    start_offset      => INTERVAL '2 minutes',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute'
);
```

### Cascading Aggregates (5m → 15m → 1h → 1d)

Higher timeframes are derived from the 1-minute aggregate, not re-scanned from raw ticks. This is dramatically more efficient.

```sql
-- 5-minute from 1-minute
CREATE MATERIALIZED VIEW ohlcv_5min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', bucket)  AS bucket,
    instrument_token,
    first(open, bucket)               AS open,
    max(high)                         AS high,
    min(low)                          AS low,
    last(close, bucket)               AS close,
    sum(volume)                       AS volume,
    last(open_interest, bucket)       AS open_interest
FROM ohlcv_1min
GROUP BY time_bucket('5 minutes', bucket), instrument_token
WITH NO DATA;
```

15-minute, 1-hour, and 1-day aggregates follow the same pattern, cascading from `ohlcv_5min`.

### Option Chain Hourly Aggregate

```sql
CREATE MATERIALIZED VIEW option_chain_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp)  AS bucket,
    underlying_symbol,
    expiry_date,
    strike_price,
    option_type,
    last(last_price, timestamp)       AS last_price,
    last(open_interest, timestamp)    AS open_interest,
    sum(volume)                       AS volume,
    last(iv, timestamp)               AS iv,
    last(delta, timestamp)            AS delta,
    last(theta, timestamp)            AS theta
FROM option_chain
GROUP BY bucket, underlying_symbol, expiry_date, strike_price, option_type
WITH NO DATA;
```

---

## Index Design

TimescaleDB creates the primary key index automatically. Additional indexes are created with `timescaledb.transaction_per_chunk` to apply them only to new chunks without locking existing data.

### `market_data` Indexes

```sql
-- For candle queries by instrument + time range (most common query)
CREATE INDEX idx_market_data_instrument_time
    ON market_data (instrument_token, timestamp DESC)
    WITH (timescaledb.transaction_per_chunk);

-- For data type filtering
CREATE INDEX idx_market_data_type_time
    ON market_data (data_type, timestamp DESC)
    WITH (timescaledb.transaction_per_chunk);
```

### `option_chain` Indexes

```sql
CREATE INDEX idx_option_chain_underlying_expiry
    ON option_chain (underlying_symbol, expiry_date, strike_price, option_type, timestamp DESC)
    WITH (timescaledb.transaction_per_chunk);
```

### `market_features` Indexes

```sql
CREATE INDEX idx_market_features_instrument_timeframe
    ON market_features (instrument_token, timeframe, timestamp DESC)
    WITH (timescaledb.transaction_per_chunk);
```

### `signal_events` and `order_events` Indexes

```sql
CREATE INDEX idx_signal_events_signal_id
    ON signal_events (signal_id, timestamp ASC);

CREATE INDEX idx_order_events_order_id
    ON order_events (order_id, timestamp ASC);

CREATE INDEX idx_order_events_broker_order_id
    ON order_events (broker_order_id, timestamp ASC)
    WHERE broker_order_id IS NOT NULL;
```

---

## Data Retention Tiers

| Tier | Storage | Retention Period | Access Pattern |
|---|---|---|---|
| Hot | TimescaleDB (uncompressed) | 7 days | Read/write; < 10ms |
| Warm | TimescaleDB (compressed) | 90 days | Read-mostly; 50–100ms acceptable |
| Cold | Object Storage (S3/GCS Parquet) | 2 years (SEBI order records requirement) | Batch; restore on demand |
| Archive | Glacier-class storage | 5 years | Compliance only |

### Retention Policies

```sql
SELECT add_retention_policy('market_data',       INTERVAL '90 days');
SELECT add_retention_policy('option_chain',       INTERVAL '90 days');
SELECT add_retention_policy('market_features',    INTERVAL '90 days');

SELECT add_retention_policy('ohlcv_1min',  INTERVAL '90 days');
SELECT add_retention_policy('ohlcv_5min',  INTERVAL '180 days');
SELECT add_retention_policy('ohlcv_1h',    INTERVAL '5 years');
SELECT add_retention_policy('ohlcv_1d',    INTERVAL '10 years');

SELECT add_retention_policy('signal_events', INTERVAL '2 years');
SELECT add_retention_policy('order_events',  INTERVAL '2 years');
```

### Cold Archive Process

Before TimescaleDB drops a chunk, the `DataArchiveService` exports it and uploads to object storage:

1. `pre_drop_chunk_hook` triggers before each drop.
2. Serialize chunk to Parquet format (columnar, Snappy compressed).
3. Upload to `s3://bucket/market_data/{year}/{month}/{date}/{instrument_token}.parquet`.
4. Verify checksum.
5. Allow chunk drop.
6. Log archive to `data_archive_log` table.

**Restoration:** download Parquet from S3, bulk-load into a temporary hypertable, query via standard SQL.

---

## Connection Pool Configuration

### PgBouncer

All application connections pass through PgBouncer in transaction-mode pooling. Direct PostgreSQL connections are prohibited except for schema migrations.

```ini
[databases]
trading = host=127.0.0.1 port=5432 dbname=trading

[pgbouncer]
pool_mode           = transaction
max_client_conn     = 500
default_pool_size   = 20
min_pool_size       = 5
reserve_pool_size   = 5
server_reset_query  = DISCARD ALL
```

### SQLAlchemy Pool Configuration per Service

| Service | pool_size | max_overflow | pool_timeout |
|---|---|---|---|
| API handlers | 10 | 20 | 30s |
| Market data writer | 5 | 10 | 10s |
| OMS | 5 | 10 | 5s |
| Analytics queries | 5 | 10 | 60s |
| Background tasks | 3 | 5 | 30s |

### PostgreSQL Configuration Tuning

```
# Memory
shared_buffers                  = 25% of RAM
effective_cache_size            = 75% of RAM
work_mem                        = 64MB
maintenance_work_mem            = 512MB

# Parallelism
max_parallel_workers_per_gather = 4
max_parallel_workers            = 8

# Write Performance
checkpoint_completion_target    = 0.9
wal_buffers                     = 64MB
max_wal_size                    = 4GB

# Autovacuum (tuned for append-heavy hypertables)
autovacuum_vacuum_scale_factor  = 0.01
autovacuum_analyze_scale_factor = 0.005
autovacuum_vacuum_cost_delay    = 2ms

# Slow Query Logging
log_min_duration_statement      = 100   # log queries > 100ms
log_autovacuum_min_duration     = 1000  # log autovacuums > 1s
```

---

## Read/Write Separation

### Write Path (Primary)
All writes go to the primary PostgreSQL instance:
- Market data writer (tick ingestion)
- OMS (order events)
- Risk engine (risk decisions)
- Feature engineering service (computed features)

### Read Path (Replica)
Analytical and dashboard queries use a read replica:
- Dashboard queries (P&L, signal history)
- Backtesting engine
- Report generation
- All continuous aggregate queries

SQLAlchemy session factory is configured with two engines:
- `write_engine` → primary
- `read_engine` → replica

The repository's `get_session(read_only: bool)` method routes to the appropriate engine.

---

## Alembic Migration Strategy

### TimescaleDB-Aware Migration Rules

1. Create the extension before any hypertable:
   ```sql
   CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
   ```

2. Create the base table as a regular PostgreSQL table first.

3. Then convert to hypertable using `create_hypertable()` in the same migration.

4. `create_hypertable()` calls must be written as raw SQL in `op.execute()` — Alembic cannot auto-generate them.

5. Continuous aggregates must be dropped before modifying the underlying hypertable. Each migration that alters a hypertable must drop dependent aggregates and recreate them.

6. Never rename hypertable columns in a single migration. Use: add new column → backfill → drop old column in three separate migrations to avoid table locks.

### Migration Naming Convention

```
YYYYMMDD_HHMM_phaseN_description.py
Example: 20260101_0730_phase4_create_market_data_hypertable.py
```

### Phase 4 Migration Checklist

- [ ] Create `timescaledb` extension
- [ ] Create all relational tables (users, instruments, signals, orders, trades, positions, etc.)
- [ ] Create hypertables (market_data, option_chain, market_features, signal_events, order_events)
- [ ] Create indexes for all hypertables
- [ ] Create compression policies
- [ ] Create continuous aggregates (ohlcv_1min through ohlcv_1d)
- [ ] Create retention policies
- [ ] Verify: `SELECT * FROM timescaledb_information.hypertables;`
- [ ] Verify: `SELECT * FROM timescaledb_information.continuous_aggregates;`
- [ ] Verify: `SELECT * FROM timescaledb_information.compression_settings;`

---

## Observability

| Metric | Type | Description |
|---|---|---|
| `timescaledb_chunk_count` | Gauge | Per hypertable chunk count |
| `timescaledb_compressed_chunks` | Gauge | Compressed chunk count per table |
| `timescaledb_uncompressed_size_bytes` | Gauge | Uncompressed hypertable size |
| `timescaledb_compressed_size_bytes` | Gauge | Post-compression size |
| `timescaledb_compression_ratio` | Gauge | Size reduction ratio |
| `db_write_latency_seconds` | Histogram | Per-table write latency |
| `db_query_latency_seconds` | Histogram | Per-query-type read latency |
| `db_connection_pool_size` | Gauge | Current active connections |
| `db_slow_queries_total` | Counter | Queries exceeding 100ms |
| `continuous_aggregate_lag_seconds` | Gauge | Per-aggregate refresh lag |

**Alert:** if `continuous_aggregate_lag_seconds > 120` for `ohlcv_1min`, the feature engineering service is reading stale data. Investigate immediately.
