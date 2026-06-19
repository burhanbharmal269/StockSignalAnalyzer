"""Phase 16-18 — Execution Lifecycle table for slippage, fill quality, and latency.

Creates execution_lifecycle table (Phase 17 Sections D, E, F).

One row per order. Tracks the full lifecycle:
  SIGNAL_GENERATED → ORDER_SUBMITTED → ORDER_FILLED
                   ↘ ORDER_REJECTED
                   ↘ ORDER_CANCELLED

Columns:
  signal_id            — soft reference to signal_analytics.signal_id
  order_id             — broker order ID
  symbol, regime, direction, broker_name
  signal_generated_at, order_submitted_at, order_filled_at, order_rejected_at, order_cancelled_at
  expected_entry_price, actual_entry_price, expected_exit_price, actual_exit_price
  entry_slippage_pct, exit_slippage_pct, total_slippage_pct
  signal_to_order_ms, order_to_fill_ms, signal_to_fill_ms
  rejection_reason, status, created_at, updated_at

Revision ID: 20260619_1200
Revises: 20260619_1100
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "20260619_1200"
down_revision = "20260619_1100"
branch_labels = None
depends_on    = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :t AND table_schema = 'public'"
        ),
        {"t": table},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if _table_exists("execution_lifecycle"):
        return

    op.create_table(
        "execution_lifecycle",
        sa.Column("id",           sa.BigInteger(),     primary_key=True, autoincrement=True),
        sa.Column("signal_id",    sa.String(36),       nullable=True),
        sa.Column("order_id",     sa.String(36),       nullable=True),
        sa.Column("symbol",       sa.String(50),       nullable=False),
        sa.Column("regime",       sa.String(30),       nullable=True),
        sa.Column("direction",    sa.String(10),       nullable=True),
        sa.Column("broker_name",  sa.String(30),       nullable=False, server_default="zerodha"),
        sa.Column("status",       sa.String(20),       nullable=False, server_default="SIGNAL_GENERATED"),

        # Lifecycle timestamps
        sa.Column("signal_generated_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_submitted_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_filled_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_rejected_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_cancelled_at",   sa.DateTime(timezone=True), nullable=True),

        # Price tracking
        sa.Column("expected_entry_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("actual_entry_price",   sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_exit_price",  sa.Numeric(12, 2), nullable=True),
        sa.Column("actual_exit_price",    sa.Numeric(12, 2), nullable=True),

        # Slippage (computed, stored for fast queries)
        sa.Column("entry_slippage_pct",  sa.Numeric(8, 4), nullable=True),
        sa.Column("exit_slippage_pct",   sa.Numeric(8, 4), nullable=True),
        sa.Column("total_slippage_pct",  sa.Numeric(8, 4), nullable=True),

        # Latency in ms (computed, stored for fast queries)
        sa.Column("signal_to_order_ms",  sa.Numeric(10, 2), nullable=True),
        sa.Column("order_to_fill_ms",    sa.Numeric(10, 2), nullable=True),
        sa.Column("signal_to_fill_ms",   sa.Numeric(10, 2), nullable=True),

        sa.Column("rejection_reason",    sa.String(100),  nullable=True),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at",   sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("idx_el_signal_id",      "execution_lifecycle", ["signal_id"])
    op.create_index("idx_el_symbol_created", "execution_lifecycle", ["symbol", "created_at"])
    op.create_index("idx_el_regime_created", "execution_lifecycle", ["regime", "created_at"])
    op.create_index("idx_el_status_created", "execution_lifecycle", ["status", "created_at"])


def downgrade() -> None:
    if _table_exists("execution_lifecycle"):
        op.drop_table("execution_lifecycle")
