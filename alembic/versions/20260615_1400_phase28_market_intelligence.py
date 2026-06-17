"""Phase 28 — Market Intelligence Platform: all new tables.

Adds: historical_candles, market_universe, option_chain_snapshots,
      news_events, sentiment_scores, market_opportunities,
      backtest_runs, backtest_trades, backtest_metrics,
      paper_trade_journal, market_breadth_snapshots, ai_insights

Revision ID: 010_phase28
Revises: 009_fix_broker_sessions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "010_phase28"
down_revision = "009_fix_broker_sessions"
branch_labels = None
depends_on = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")
_UUID_TYPE = UUID(as_uuid=False).with_variant(sa.String(36), "sqlite")


def _tsdb_hypertable(table: str, time_col: str) -> None:
    """Convert table to TimescaleDB hypertable if TimescaleDB is available.

    Uses a SAVEPOINT so a missing TimescaleDB extension doesn't abort the
    surrounding transaction — plain PostgreSQL just keeps plain tables.
    """
    bind = op.get_bind()
    bind.execute(sa.text("SAVEPOINT tsdb_check"))
    try:
        bind.execute(
            sa.text(
                f"SELECT create_hypertable('{table}', '{time_col}', "
                f"if_not_exists => TRUE, migrate_data => TRUE)"
            )
        )
        bind.execute(sa.text("RELEASE SAVEPOINT tsdb_check"))
    except Exception:
        bind.execute(sa.text("ROLLBACK TO SAVEPOINT tsdb_check"))


def upgrade() -> None:
    # ------------------------------------------------------------------
    # market_universe — canonical symbol registry
    # ------------------------------------------------------------------
    op.create_table(
        "market_universe",
        sa.Column("symbol", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("exchange", sa.String(10), nullable=False, server_default="NSE"),
        sa.Column("segment", sa.String(20), nullable=False, server_default="EQ"),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("is_fo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_index", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("lot_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("instrument_token", sa.BigInteger(), nullable=True),
        sa.Column("isin", sa.String(20), nullable=True),
        sa.Column("meta", _JSON, nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_universe_segment", "market_universe", ["segment"])
    op.create_index("idx_universe_is_fo", "market_universe", ["is_fo"])
    op.create_index("idx_universe_is_active", "market_universe", ["is_active"])

    # ------------------------------------------------------------------
    # historical_candles — OHLCV + OI per symbol + timeframe
    # ------------------------------------------------------------------
    op.create_table(
        "historical_candles",
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("timeframe", sa.String(5), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(18, 4), nullable=False),
        sa.Column("high", sa.Numeric(18, 4), nullable=False),
        sa.Column("low", sa.Numeric(18, 4), nullable=False),
        sa.Column("close", sa.Numeric(18, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("oi", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("symbol", "timeframe", "ts"),
    )
    op.create_index("idx_candles_symbol_tf_ts",
                    "historical_candles", ["symbol", "timeframe", "ts"])
    op.create_index("idx_candles_ts", "historical_candles", ["ts"])
    _tsdb_hypertable("historical_candles", "ts")

    # ------------------------------------------------------------------
    # option_chain_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "option_chain_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("underlying", sa.String(50), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("strike", sa.Numeric(12, 2), nullable=False),
        sa.Column("option_type", sa.String(2), nullable=False),   # CE / PE
        sa.Column("ltp", sa.Numeric(12, 4), nullable=True),
        sa.Column("iv", sa.Numeric(8, 4), nullable=True),
        sa.Column("oi", sa.BigInteger(), nullable=True),
        sa.Column("oi_change", sa.BigInteger(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("delta", sa.Numeric(8, 6), nullable=True),
        sa.Column("gamma", sa.Numeric(10, 8), nullable=True),
        sa.Column("theta", sa.Numeric(10, 6), nullable=True),
        sa.Column("vega", sa.Numeric(10, 6), nullable=True),
        sa.Column("bid", sa.Numeric(12, 4), nullable=True),
        sa.Column("ask", sa.Numeric(12, 4), nullable=True),
        sa.Column("pcr", sa.Numeric(8, 4), nullable=True),
        sa.Column("max_pain", sa.Numeric(12, 2), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_oc_underlying_expiry_ts",
                    "option_chain_snapshots", ["underlying", "expiry", "captured_at"])
    op.create_index("idx_oc_captured_at", "option_chain_snapshots", ["captured_at"])

    # ------------------------------------------------------------------
    # news_events
    # ------------------------------------------------------------------
    op.create_table(
        "news_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("symbols", _JSON, nullable=True),       # list[str]
        sa.Column("categories", _JSON, nullable=True),    # list[str]
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_news_published_at", "news_events", ["published_at"])
    op.create_index("idx_news_source", "news_events", ["source"])
    op.create_index("idx_news_content_hash", "news_events", ["content_hash"], unique=True)

    # ------------------------------------------------------------------
    # sentiment_scores
    # ------------------------------------------------------------------
    op.create_table(
        "sentiment_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),   # -1 to +1
        sa.Column("direction", sa.String(10), nullable=False),   # BULLISH/BEARISH/NEUTRAL
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),  # NEWS/AI/COMBINED
        sa.Column("news_event_id", sa.Integer(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_sentiment_symbol_ts", "sentiment_scores",
                    ["symbol", "calculated_at"])

    # ------------------------------------------------------------------
    # market_breadth_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "market_breadth_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("advances", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("declines", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_highs_52w", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_lows_52w", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("advance_decline_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("breadth_score", sa.Numeric(5, 2), nullable=True),  # -100 to +100
        sa.Column("above_200dma_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("sector_data", _JSON, nullable=True),
    )
    op.create_index("idx_breadth_ts", "market_breadth_snapshots", ["ts"])

    # ------------------------------------------------------------------
    # market_opportunities — scanner results
    # ------------------------------------------------------------------
    op.create_table(
        "market_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("opportunity_type", sa.String(30), nullable=False),
        sa.Column("technical_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("volume_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("sentiment_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("oi_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("regime_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("total_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("direction", sa.String(5), nullable=True),   # LONG / SHORT
        sa.Column("regime", sa.String(20), nullable=True),
        sa.Column("meta", _JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_opp_symbol", "market_opportunities", ["symbol"])
    op.create_index("idx_opp_score", "market_opportunities", ["total_score"])
    op.create_index("idx_opp_created", "market_opportunities", ["created_at"])

    # ------------------------------------------------------------------
    # backtest_runs
    # ------------------------------------------------------------------
    op.create_table(
        "backtest_runs",
        sa.Column("run_id", _UUID_TYPE, primary_key=True),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("params", _JSON, nullable=True),
        sa.Column("symbols", _JSON, nullable=False),   # list[str]
        sa.Column("timeframe", sa.String(5), nullable=False, server_default="15m"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(15), nullable=False, server_default="PENDING"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_bt_strategy", "backtest_runs", ["strategy_name"])
    op.create_index("idx_bt_created", "backtest_runs", ["created_at"])

    # ------------------------------------------------------------------
    # backtest_trades
    # ------------------------------------------------------------------
    op.create_table(
        "backtest_trades",
        sa.Column("trade_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", _UUID_TYPE, nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("direction", sa.String(5), nullable=False),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("stop_loss", sa.Numeric(18, 4), nullable=True),
        sa.Column("target", sa.Numeric(18, 4), nullable=True),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("pnl", sa.Numeric(18, 4), nullable=True),
        sa.Column("pnl_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("exit_reason", sa.String(30), nullable=True),
        sa.Column("strategy_name", sa.String(100), nullable=True),
    )
    op.create_index("idx_bt_trades_run", "backtest_trades", ["run_id"])
    op.create_index("idx_bt_trades_symbol", "backtest_trades", ["symbol"])

    # ------------------------------------------------------------------
    # backtest_metrics
    # ------------------------------------------------------------------
    op.create_table(
        "backtest_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", _UUID_TYPE, nullable=False, unique=True),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winning_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losing_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("total_pnl", sa.Numeric(18, 4), nullable=True),
        sa.Column("avg_profit", sa.Numeric(18, 4), nullable=True),
        sa.Column("avg_loss", sa.Numeric(18, 4), nullable=True),
        sa.Column("profit_factor", sa.Numeric(10, 4), nullable=True),
        sa.Column("expectancy", sa.Numeric(18, 4), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("sortino_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("cagr", sa.Numeric(8, 4), nullable=True),
        sa.Column("avg_trade_duration_mins", sa.Numeric(10, 2), nullable=True),
    )

    # ------------------------------------------------------------------
    # paper_trade_journal — continuous daemon signals
    # ------------------------------------------------------------------
    op.create_table(
        "paper_trade_journal",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(5), nullable=False),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("stop_loss", sa.Numeric(18, 4), nullable=True),
        sa.Column("target", sa.Numeric(18, 4), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("risk_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("pnl", sa.Numeric(18, 4), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.String(30), nullable=True),
        sa.Column("meta", _JSON, nullable=True),
    )
    op.create_index("idx_ptj_session", "paper_trade_journal", ["session_id"])
    op.create_index("idx_ptj_symbol", "paper_trade_journal", ["symbol"])
    op.create_index("idx_ptj_signal_at", "paper_trade_journal", ["signal_at"])

    # ------------------------------------------------------------------
    # ai_insights
    # ------------------------------------------------------------------
    op.create_table(
        "ai_insights",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("insight_type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("symbols", _JSON, nullable=True),
        sa.Column("sentiment", sa.String(10), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("risk_level", sa.String(10), nullable=True),
        sa.Column("source_data", _JSON, nullable=True),
        sa.Column("model_used", sa.String(50), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_insights_type", "ai_insights", ["insight_type"])
    op.create_index("idx_insights_generated", "ai_insights", ["generated_at"])


def downgrade() -> None:
    for tbl in [
        "ai_insights",
        "paper_trade_journal",
        "backtest_metrics",
        "backtest_trades",
        "backtest_runs",
        "market_opportunities",
        "market_breadth_snapshots",
        "sentiment_scores",
        "news_events",
        "option_chain_snapshots",
        "historical_candles",
        "market_universe",
    ]:
        op.drop_table(tbl)
