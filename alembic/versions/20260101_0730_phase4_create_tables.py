"""Phase 4: Create all tables, hypertables, indexes, compression and retention policies.

Revision ID: 001_phase4
Revises:
Create Date: 2026-01-01 07:30:00

TimescaleDB rules followed (docs/18_TIMESCALEDB_ARCHITECTURE.md):
- Extension created first.
- Base table created as regular PostgreSQL table.
- Converted to hypertable via op.execute(create_hypertable(...)).
- Indexes created with timescaledb.transaction_per_chunk where possible.
- Compression and retention policies added last.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_phase4"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timescaledb_available() -> bool:
    """Return True if TimescaleDB extension is available on this server.

    Uses pg_available_extensions to check without attempting installation
    (which would abort the transaction on failure).
    If available, installs it within a SAVEPOINT so a failure can be rolled back.
    """
    conn = op.get_bind()
    # First check if the extension package is present
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM pg_available_extensions WHERE name = 'timescaledb'"
    ))
    if (result.scalar() or 0) == 0:
        return False
    # Extension exists — try to create it, using SAVEPOINT to stay in the transaction
    conn.execute(sa.text("SAVEPOINT tsdb_install"))
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
        conn.execute(sa.text("RELEASE SAVEPOINT tsdb_install"))
        return True
    except Exception:
        conn.execute(sa.text("ROLLBACK TO SAVEPOINT tsdb_install"))
        return False


def _tsdb(sql: str, fallback: str | None = None) -> None:
    """Execute a TimescaleDB-specific SQL statement; skip silently if unavailable."""
    if _TSDB:
        try:
            op.execute(sql)
        except Exception:
            pass
    elif fallback:
        op.execute(fallback)


_TSDB: bool = False  # set at runtime in upgrade()


def upgrade() -> None:
    global _TSDB
    # -------------------------------------------------------------------------
    # TimescaleDB extension (optional — gracefully degrades to plain PostgreSQL)
    # -------------------------------------------------------------------------
    _TSDB = _timescaledb_available()

    # -------------------------------------------------------------------------
    # Relational tables
    # -------------------------------------------------------------------------

    op.create_table(
        "users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "broker_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("broker_name", sa.String(30), nullable=False),
        sa.Column("encrypted_access_token", sa.Text, nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("idx_broker_sessions_user_id", "broker_sessions", ["user_id"])

    op.create_table(
        "instruments",
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token", sa.Integer, nullable=False, unique=True),
        sa.Column("ticker", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("lot_size", sa.Integer, nullable=False),
        sa.Column("tick_size", sa.Numeric(12, 4), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("expiry", sa.Date, nullable=True),
        sa.Column("strike", sa.Numeric(12, 2), nullable=True),
        sa.Column("instrument_type", sa.String(20), nullable=False, server_default="''"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("idx_instruments_token", "instruments", ["token"])
    op.create_index("idx_instruments_asset_type", "instruments", ["asset_type", "is_active"])

    op.create_table(
        "signals",
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("signal_type", sa.String(10), nullable=False),
        sa.Column("strategy_type", sa.String(30), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("regime", sa.String(30), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(50), nullable=False, server_default="''"),
        sa.Column("raw_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("adjusted_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("scoring_weights_sha256", sa.String(64), nullable=False, server_default="''"),
        sa.Column("fingerprint", sa.String(64), nullable=False, server_default="''"),
        sa.Column("risk_rejection_reason", sa.String(255), nullable=False, server_default="''"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("idx_signals_state", "signals", ["state"])
    op.create_index("idx_signals_ticker", "signals", ["ticker"])
    op.create_index("idx_signals_fingerprint", "signals", ["fingerprint"])

    op.create_table(
        "orders",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("limit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("state", sa.String(25), nullable=False),
        sa.Column("broker_order_id", sa.String(50), nullable=False, server_default="''"),
        sa.Column("filled_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("average_fill_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("rejection_reason", sa.String(255), nullable=False, server_default="''"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("idx_orders_signal_id", "orders", ["signal_id"])
    op.create_index("idx_orders_state", "orders", ["state"])
    op.create_index("idx_orders_ticker", "orders", ["ticker"])

    op.create_table(
        "positions",
        sa.Column("position_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("entry_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_positions_state", "positions", ["state"])
    op.create_index("idx_positions_ticker", "positions", ["ticker"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("details", postgresql.JSONB, nullable=True),
    )
    op.create_index("idx_audit_logs_timestamp", "audit_logs", ["timestamp"])

    # signal_performance_stats is created by migration 003_phase12

    # -------------------------------------------------------------------------
    # Hypertables (TimescaleDB)
    # -------------------------------------------------------------------------

    op.create_table(
        "market_data",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument_token", sa.Integer, nullable=False),
        sa.Column("tradingsymbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("open", sa.Numeric(12, 2), nullable=True),
        sa.Column("high", sa.Numeric(12, 2), nullable=True),
        sa.Column("low", sa.Numeric(12, 2), nullable=True),
        sa.Column("close", sa.Numeric(12, 2), nullable=False),
        sa.Column("last_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("volume", sa.BigInteger, nullable=True),
        sa.Column("buy_quantity", sa.BigInteger, nullable=True),
        sa.Column("sell_quantity", sa.BigInteger, nullable=True),
        sa.Column("open_interest", sa.BigInteger, nullable=True),
        sa.Column("change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("data_type", sa.String(10), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.PrimaryKeyConstraint("timestamp", "instrument_token"),
    )
    _tsdb("SELECT create_hypertable('market_data', 'timestamp', chunk_time_interval => INTERVAL '1 day', create_default_indexes => FALSE);")
    _tsdb(
        "CREATE INDEX idx_market_data_instrument_time ON market_data (instrument_token, timestamp DESC) WITH (timescaledb.transaction_per_chunk);",
        "CREATE INDEX idx_market_data_instrument_time ON market_data (instrument_token, timestamp DESC);",
    )
    _tsdb(
        "CREATE INDEX idx_market_data_type_time ON market_data (data_type, timestamp DESC) WITH (timescaledb.transaction_per_chunk);",
        "CREATE INDEX idx_market_data_type_time ON market_data (data_type, timestamp DESC);",
    )
    _tsdb("ALTER TABLE market_data SET (timescaledb.compress, timescaledb.compress_segmentby = 'instrument_token', timescaledb.compress_orderby = 'timestamp DESC');")
    _tsdb("SELECT add_compression_policy('market_data', INTERVAL '7 days');")
    _tsdb("SELECT add_retention_policy('market_data', INTERVAL '90 days');")

    op.create_table(
        "option_chain",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument_token", sa.Integer, nullable=False),
        sa.Column("underlying_symbol", sa.String(30), nullable=False),
        sa.Column("expiry_date", sa.Date, nullable=False),
        sa.Column("strike_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("option_type", sa.String(2), nullable=False),
        sa.Column("last_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("bid_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("ask_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("volume", sa.BigInteger, nullable=True),
        sa.Column("open_interest", sa.BigInteger, nullable=True),
        sa.Column("oi_change", sa.BigInteger, nullable=True),
        sa.Column("iv", sa.Numeric(8, 4), nullable=True),
        sa.Column("delta", sa.Numeric(8, 6), nullable=True),
        sa.Column("gamma", sa.Numeric(10, 8), nullable=True),
        sa.Column("theta", sa.Numeric(8, 6), nullable=True),
        sa.Column("vega", sa.Numeric(8, 6), nullable=True),
        sa.PrimaryKeyConstraint("timestamp", "instrument_token"),
    )
    _tsdb("SELECT create_hypertable('option_chain', 'timestamp', chunk_time_interval => INTERVAL '1 day', create_default_indexes => FALSE);")
    _tsdb(
        "CREATE INDEX idx_option_chain_underlying_expiry ON option_chain (underlying_symbol, expiry_date, strike_price, option_type, timestamp DESC) WITH (timescaledb.transaction_per_chunk);",
        "CREATE INDEX idx_option_chain_underlying_expiry ON option_chain (underlying_symbol, expiry_date, strike_price, option_type, timestamp DESC);",
    )
    _tsdb("ALTER TABLE option_chain SET (timescaledb.compress, timescaledb.compress_segmentby = 'underlying_symbol, expiry_date', timescaledb.compress_orderby = 'timestamp DESC');")
    _tsdb("SELECT add_compression_policy('option_chain', INTERVAL '7 days');")
    _tsdb("SELECT add_retention_policy('option_chain', INTERVAL '90 days');")

    op.create_table(
        "market_features",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument_token", sa.Integer, nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("rsi_14", sa.Numeric(8, 4), nullable=True),
        sa.Column("ema_9", sa.Numeric(12, 2), nullable=True),
        sa.Column("ema_21", sa.Numeric(12, 2), nullable=True),
        sa.Column("ema_50", sa.Numeric(12, 2), nullable=True),
        sa.Column("ema_200", sa.Numeric(12, 2), nullable=True),
        sa.Column("sma_20", sa.Numeric(12, 2), nullable=True),
        sa.Column("vwap", sa.Numeric(12, 2), nullable=True),
        sa.Column("atr_14", sa.Numeric(10, 4), nullable=True),
        sa.Column("macd_line", sa.Numeric(10, 4), nullable=True),
        sa.Column("macd_signal", sa.Numeric(10, 4), nullable=True),
        sa.Column("macd_histogram", sa.Numeric(10, 4), nullable=True),
        sa.Column("adx_14", sa.Numeric(8, 4), nullable=True),
        sa.Column("supertrend", sa.Numeric(12, 2), nullable=True),
        sa.Column("supertrend_dir", sa.SmallInteger, nullable=True),
        sa.Column("bb_upper", sa.Numeric(12, 2), nullable=True),
        sa.Column("bb_lower", sa.Numeric(12, 2), nullable=True),
        sa.Column("bb_width", sa.Numeric(8, 4), nullable=True),
        sa.Column("relative_volume", sa.Numeric(8, 4), nullable=True),
        sa.Column("volume_sma_20", sa.BigInteger, nullable=True),
        sa.Column("pcr", sa.Numeric(8, 4), nullable=True),
        sa.Column("max_pain", sa.Numeric(12, 2), nullable=True),
        sa.Column("iv_rank", sa.Numeric(8, 4), nullable=True),
        sa.Column("iv_percentile", sa.Numeric(8, 4), nullable=True),
        sa.PrimaryKeyConstraint("timestamp", "instrument_token", "timeframe"),
    )
    _tsdb("SELECT create_hypertable('market_features', 'timestamp', chunk_time_interval => INTERVAL '1 day', create_default_indexes => FALSE);")
    _tsdb(
        "CREATE INDEX idx_market_features_instrument_timeframe ON market_features (instrument_token, timeframe, timestamp DESC) WITH (timescaledb.transaction_per_chunk);",
        "CREATE INDEX idx_market_features_instrument_timeframe ON market_features (instrument_token, timeframe, timestamp DESC);",
    )
    _tsdb("ALTER TABLE market_features SET (timescaledb.compress, timescaledb.compress_segmentby = 'instrument_token, timeframe', timescaledb.compress_orderby = 'timestamp DESC');")
    _tsdb("SELECT add_compression_policy('market_features', INTERVAL '7 days');")
    _tsdb("SELECT add_retention_policy('market_features', INTERVAL '90 days');")

    op.create_table(
        "signal_events",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("event_data", postgresql.JSONB, nullable=False),
        sa.Column("correlation_id", sa.String(50), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint("timestamp", "signal_id", "event_type"),
    )
    _tsdb("SELECT create_hypertable('signal_events', 'timestamp', chunk_time_interval => INTERVAL '7 days', create_default_indexes => FALSE);")
    op.execute("CREATE INDEX idx_signal_events_signal_id ON signal_events (signal_id, timestamp ASC);")
    _tsdb("ALTER TABLE signal_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'signal_id', timescaledb.compress_orderby = 'timestamp DESC');")
    _tsdb("SELECT add_compression_policy('signal_events', INTERVAL '30 days');")
    _tsdb("SELECT add_retention_policy('signal_events', INTERVAL '2 years');")

    op.create_table(
        "order_events",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("broker_order_id", sa.String(50), nullable=True),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("event_data", postgresql.JSONB, nullable=False),
        sa.Column("correlation_id", sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint("timestamp", "order_id", "event_type"),
    )
    _tsdb("SELECT create_hypertable('order_events', 'timestamp', chunk_time_interval => INTERVAL '7 days', create_default_indexes => FALSE);")
    op.execute("CREATE INDEX idx_order_events_order_id ON order_events (order_id, timestamp ASC);")
    op.execute("CREATE INDEX idx_order_events_broker_order_id ON order_events (broker_order_id, timestamp ASC) WHERE broker_order_id IS NOT NULL;")
    _tsdb("SELECT add_retention_policy('order_events', INTERVAL '2 years');")

    # -------------------------------------------------------------------------
    # Continuous aggregates (1-minute OHLCV from tick data)
    # TimescaleDB: continuous materialized view. Plain PG: regular view.
    # -------------------------------------------------------------------------
    if _TSDB:
        _tsdb("""
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
        """)
        _tsdb("""
            SELECT add_continuous_aggregate_policy('ohlcv_1min',
                start_offset      => INTERVAL '2 minutes',
                end_offset        => INTERVAL '1 minute',
                schedule_interval => INTERVAL '1 minute');
        """)
        _tsdb("SELECT add_retention_policy('ohlcv_1min', INTERVAL '90 days');")
    else:
        op.execute("""
            CREATE VIEW ohlcv_1min AS
            SELECT
                date_trunc('minute', timestamp)     AS bucket,
                instrument_token,
                MIN(open)                           AS open,
                MAX(high)                           AS high,
                MIN(low)                            AS low,
                MAX(close)                          AS close,
                MAX(last_price)                     AS last_price,
                SUM(volume)                         AS volume,
                MAX(open_interest)                  AS open_interest
            FROM market_data
            WHERE data_type = 'TICK'
            GROUP BY date_trunc('minute', timestamp), instrument_token;
        """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS ohlcv_1min;")
    op.execute("DROP VIEW IF EXISTS ohlcv_1min;")
    op.drop_table("order_events")
    op.drop_table("signal_events")
    op.drop_table("market_features")
    op.drop_table("option_chain")
    op.drop_table("market_data")
    op.drop_table("audit_logs")
    op.drop_table("positions")
    op.drop_table("orders")
    op.drop_table("signals")
    op.drop_table("instruments")
    op.drop_table("broker_sessions")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS timescaledb;")
