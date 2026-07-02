"""phase23_execution_intelligence

Revision ID: 20260702_1600
Revises: 20260702_1200
Create Date: 2026-07-02 16:00:00

Phase 23 — Execution Intelligence & Broker Quality.
Creates tables for execution timeline, latency, slippage, retries,
rejections, broker health, and execution quality metrics.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260702_1600"
down_revision = "20260702_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── execution_events: complete per-signal execution timeline ──────────────
    op.create_table(
        "execution_events",
        sa.Column("id",           sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("signal_id",    UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("order_id",     UUID(as_uuid=False), nullable=True, index=True),
        sa.Column("position_id",  UUID(as_uuid=False), nullable=True),
        sa.Column("symbol",       sa.String(30), nullable=True),
        sa.Column("broker",       sa.String(30), server_default="kite"),
        sa.Column("direction",    sa.String(10), nullable=True),
        sa.Column("regime",       sa.String(30), nullable=True),
        sa.Column("is_index",     sa.Boolean, server_default="false"),
        # Stage timestamps (UTC)
        sa.Column("signal_generated_at",   sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("risk_approved_at",      sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("strike_selected_at",    sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("order_submitted_at",    sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("broker_received_at",    sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("broker_accepted_at",    sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("exchange_accepted_at",  sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("order_filled_at",       sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("position_opened_at",    sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("position_closed_at",    sa.TIMESTAMP(timezone=True), nullable=True),
        # Duration between consecutive stages (milliseconds)
        sa.Column("signal_to_risk_ms",     sa.Float, nullable=True),
        sa.Column("risk_to_strike_ms",     sa.Float, nullable=True),
        sa.Column("strike_to_order_ms",    sa.Float, nullable=True),
        sa.Column("order_to_broker_ms",    sa.Float, nullable=True),
        sa.Column("broker_to_exchange_ms", sa.Float, nullable=True),
        sa.Column("exchange_to_fill_ms",   sa.Float, nullable=True),
        sa.Column("fill_to_position_ms",   sa.Float, nullable=True),
        sa.Column("total_execution_ms",    sa.Float, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_execution_events_signal_id", "execution_events", ["signal_id"])
    op.create_index("ix_execution_events_created_at", "execution_events", ["created_at"])

    # ── execution_latency: per-stage latency records ───────────────────────────
    op.create_table(
        "execution_latency",
        sa.Column("id",          sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("signal_id",   UUID(as_uuid=False), nullable=True, index=True),
        sa.Column("order_id",    UUID(as_uuid=False), nullable=True),
        sa.Column("symbol",      sa.String(30), nullable=True),
        sa.Column("broker",      sa.String(30), server_default="kite"),
        sa.Column("stage",       sa.String(50), nullable=False),
        sa.Column("duration_ms", sa.Float, nullable=False),
        sa.Column("time_of_day", sa.Time, nullable=True),
        sa.Column("regime",      sa.String(30), nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_execution_latency_stage", "execution_latency", ["stage"])
    op.create_index("ix_execution_latency_broker", "execution_latency", ["broker"])
    op.create_index("ix_execution_latency_recorded_at", "execution_latency", ["recorded_at"])

    # ── execution_slippage: entry/exit slippage per order ─────────────────────
    op.create_table(
        "execution_slippage",
        sa.Column("id",                     sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("signal_id",              UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("order_id",               UUID(as_uuid=False), nullable=True),
        sa.Column("symbol",                 sa.String(30), nullable=True),
        sa.Column("broker",                 sa.String(30), server_default="kite"),
        sa.Column("direction",              sa.String(10), nullable=True),
        sa.Column("expected_entry",         sa.Numeric(14, 4), nullable=True),
        sa.Column("actual_entry",           sa.Numeric(14, 4), nullable=True),
        sa.Column("entry_slippage_points",  sa.Numeric(14, 4), nullable=True),
        sa.Column("entry_slippage_pct",     sa.Numeric(10, 6), nullable=True),
        sa.Column("entry_slippage_rupees",  sa.Numeric(14, 4), nullable=True),
        sa.Column("expected_exit",          sa.Numeric(14, 4), nullable=True),
        sa.Column("actual_exit",            sa.Numeric(14, 4), nullable=True),
        sa.Column("exit_slippage_points",   sa.Numeric(14, 4), nullable=True),
        sa.Column("exit_slippage_pct",      sa.Numeric(10, 6), nullable=True),
        sa.Column("exit_slippage_rupees",   sa.Numeric(14, 4), nullable=True),
        sa.Column("total_slippage_points",  sa.Numeric(14, 4), nullable=True),
        sa.Column("total_slippage_pct",     sa.Numeric(10, 6), nullable=True),
        sa.Column("total_slippage_rupees",  sa.Numeric(14, 4), nullable=True),
        sa.Column("lot_size",               sa.Integer, nullable=True),
        sa.Column("lots",                   sa.Integer, nullable=True),
        # Liquidity context at execution time (§8)
        sa.Column("bid",                    sa.Numeric(14, 4), nullable=True),
        sa.Column("ask",                    sa.Numeric(14, 4), nullable=True),
        sa.Column("spread",                 sa.Numeric(14, 4), nullable=True),
        sa.Column("spread_pct",             sa.Float, nullable=True),
        sa.Column("available_qty",          sa.Integer, nullable=True),
        sa.Column("liquidity_score",        sa.Float, nullable=True),
        sa.Column("recorded_at",            sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_execution_slippage_recorded_at", "execution_slippage", ["recorded_at"])

    # ── execution_retries: retry tracking per order ────────────────────────────
    op.create_table(
        "execution_retries",
        sa.Column("id",             sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("signal_id",      UUID(as_uuid=False), nullable=True, index=True),
        sa.Column("order_id",       UUID(as_uuid=False), nullable=True, index=True),
        sa.Column("symbol",         sa.String(30), nullable=True),
        sa.Column("broker",         sa.String(30), server_default="kite"),
        sa.Column("attempt_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("retry_reason",   sa.String(200), nullable=True),
        sa.Column("delay_ms",       sa.Integer, nullable=True),
        sa.Column("succeeded",      sa.Boolean, nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("timeout_type",   sa.String(30), nullable=True),
        sa.Column("recorded_at",    sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── execution_rejections: rejection categorization ─────────────────────────
    op.create_table(
        "execution_rejections",
        sa.Column("id",          sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("signal_id",   UUID(as_uuid=False), nullable=True, index=True),
        sa.Column("order_id",    UUID(as_uuid=False), nullable=True),
        sa.Column("symbol",      sa.String(30), nullable=True),
        sa.Column("broker",      sa.String(30), server_default="kite"),
        sa.Column("rejected_by", sa.String(20), nullable=True),
        sa.Column("category",    sa.String(50), nullable=True, index=True),
        sa.Column("raw_reason",  sa.String(500), nullable=True),
        sa.Column("regime",      sa.String(30), nullable=True),
        sa.Column("time_of_day", sa.Time, nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_execution_rejections_recorded_at", "execution_rejections", ["recorded_at"])

    # ── broker_health_history: broker health snapshots ────────────────────────
    op.create_table(
        "broker_health_history",
        sa.Column("id",               sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("broker",           sa.String(30), server_default="kite", index=True),
        sa.Column("health_score",     sa.Float, nullable=True),
        sa.Column("api_latency_ms",   sa.Float, nullable=True),
        sa.Column("ws_latency_ms",    sa.Float, nullable=True),
        sa.Column("order_latency_ms", sa.Float, nullable=True),
        sa.Column("failure_rate_pct", sa.Float, nullable=True),
        sa.Column("reconnect_count",  sa.Integer, server_default="0"),
        sa.Column("is_connected",     sa.Boolean, nullable=True),
        sa.Column("downtime_seconds", sa.Float, server_default="0"),
        sa.Column("events_json",      JSONB, nullable=True),
        sa.Column("recorded_at",      sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_broker_health_history_recorded_at", "broker_health_history", ["recorded_at"])

    # ── execution_metrics: per-order fill quality (§4) ────────────────────────
    op.create_table(
        "execution_metrics",
        sa.Column("id",                      sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("signal_id",               UUID(as_uuid=False), nullable=True, index=True),
        sa.Column("order_id",                UUID(as_uuid=False), nullable=True, index=True),
        sa.Column("symbol",                  sa.String(30), nullable=True),
        sa.Column("broker",                  sa.String(30), server_default="kite"),
        sa.Column("fill_pct",                sa.Float, nullable=True),
        sa.Column("partial_fills",           sa.Integer, server_default="0"),
        sa.Column("num_fills",               sa.Integer, server_default="0"),
        sa.Column("avg_fill_price",          sa.Numeric(14, 4), nullable=True),
        sa.Column("best_fill_price",         sa.Numeric(14, 4), nullable=True),
        sa.Column("worst_fill_price",        sa.Numeric(14, 4), nullable=True),
        sa.Column("execution_quality_score", sa.Float, nullable=True),
        sa.Column("recorded_at",             sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_execution_metrics_recorded_at", "execution_metrics", ["recorded_at"])


def downgrade() -> None:
    op.drop_table("execution_metrics")
    op.drop_table("broker_health_history")
    op.drop_table("execution_rejections")
    op.drop_table("execution_retries")
    op.drop_table("execution_slippage")
    op.drop_table("execution_latency")
    op.drop_table("execution_events")
