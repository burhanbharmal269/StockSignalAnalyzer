"""Phase 15: OMS — extend orders/positions, create executions table.

Revision ID: 005_phase15
Revises: 004_phase13
Create Date: 2026-06-14 11:00:00

Changes:
  orders     — add Phase 15 columns (instrument_token, tradingsymbol, transaction_type,
               order_type, product, lots, trigger_price, validity, risk_decision_id,
               trading_mode, parent_position_id, submitted_at, filled_at, cancelled_at,
               underlying, indexes)
  positions  — add Phase 15 columns (signal_id, order_id, instrument_token, tradingsymbol,
               lots, stop_loss_price, target_1_price, target_2_price, current_mtm_pnl,
               outcome, trading_mode, regime_at_open, stop_order_id, target_order_id,
               underlying, indexes)
  executions — new append-only fills table

All new columns in existing tables are nullable or have server defaults so no
backfill is required and existing rows remain valid.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_phase15"
down_revision: str | None = "004_phase13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # orders — add Phase 15 columns
    # ------------------------------------------------------------------
    op.add_column("orders", sa.Column("instrument_token", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("tradingsymbol", sa.String(50), nullable=False, server_default=""))
    op.add_column("orders", sa.Column("underlying", sa.String(20), nullable=False, server_default=""))
    op.add_column("orders", sa.Column("transaction_type", sa.String(4), nullable=False, server_default="BUY"))
    op.add_column("orders", sa.Column("order_type", sa.String(15), nullable=False, server_default="MARKET"))
    op.add_column("orders", sa.Column("product", sa.String(10), nullable=False, server_default="MIS"))
    op.add_column("orders", sa.Column("lots", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("trigger_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("orders", sa.Column("validity", sa.String(5), nullable=False, server_default="DAY"))
    op.add_column("orders", sa.Column("risk_decision_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("trading_mode", sa.String(10), nullable=False, server_default="LIVE"))
    op.add_column("orders", sa.Column("parent_position_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("orders", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))

    # Orders indexes
    op.create_index("idx_orders_state_created", "orders", ["state", "created_at"])
    op.create_index(
        "idx_orders_broker_order_id_nonempty",
        "orders",
        ["broker_order_id"],
        postgresql_where=sa.text("broker_order_id != ''"),
    )

    # ------------------------------------------------------------------
    # positions — add Phase 15 columns
    # ------------------------------------------------------------------
    op.add_column("positions", sa.Column(
        "signal_id", postgresql.UUID(as_uuid=True), nullable=True
    ))
    op.add_column("positions", sa.Column(
        "order_id", postgresql.UUID(as_uuid=True), nullable=True
    ))
    op.add_column("positions", sa.Column("instrument_token", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("tradingsymbol", sa.String(50), nullable=False, server_default=""))
    op.add_column("positions", sa.Column("underlying", sa.String(20), nullable=False, server_default=""))
    op.add_column("positions", sa.Column("lots", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("stop_loss_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("positions", sa.Column("target_1_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("positions", sa.Column("target_2_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("positions", sa.Column(
        "current_mtm_pnl", sa.Numeric(14, 2), nullable=False, server_default="0"
    ))
    op.add_column("positions", sa.Column("outcome", sa.String(15), nullable=True))
    op.add_column("positions", sa.Column("trading_mode", sa.String(10), nullable=False, server_default="LIVE"))
    op.add_column("positions", sa.Column("regime_at_open", sa.String(30), nullable=False, server_default=""))
    op.add_column("positions", sa.Column(
        "stop_order_id", postgresql.UUID(as_uuid=True), nullable=True
    ))
    op.add_column("positions", sa.Column(
        "target_order_id", postgresql.UUID(as_uuid=True), nullable=True
    ))

    # Positions indexes (idx_positions_state already created in 001_phase4)
    op.create_index("idx_positions_signal_id", "positions", ["signal_id"])

    # ------------------------------------------------------------------
    # executions — new append-only fills table
    # ------------------------------------------------------------------
    op.create_table(
        "executions",
        sa.Column("fill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("broker_order_id", sa.String(50), nullable=False),
        sa.Column("exchange_trade_id", sa.String(50), nullable=False, server_default=""),
        sa.Column("filled_quantity", sa.Integer(), nullable=False),
        sa.Column("fill_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("fill_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trading_mode", sa.String(10), nullable=False, server_default="LIVE"),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_executions_order_id_fill_time",
        "executions",
        ["order_id", "fill_time"],
    )
    op.create_foreign_key(
        "fk_executions_order_id",
        "executions",
        "orders",
        ["order_id"],
        ["order_id"],
    )

    # DB user permissions: executions is append-only (no UPDATE/DELETE)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trading_app') THEN
                GRANT SELECT, INSERT ON TABLE executions TO trading_app;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # Reverse executions
    op.drop_constraint("fk_executions_order_id", "executions", type_="foreignkey")
    op.drop_index("idx_executions_order_id_fill_time")
    op.drop_table("executions")

    # Reverse positions columns
    for col in [
        "signal_id", "order_id", "instrument_token", "tradingsymbol", "underlying",
        "lots", "stop_loss_price", "target_1_price", "target_2_price",
        "current_mtm_pnl", "outcome", "trading_mode", "regime_at_open",
        "stop_order_id", "target_order_id",
    ]:
        op.drop_column("positions", col)
    op.drop_index("idx_positions_signal_id")

    # Reverse orders columns
    for col in [
        "instrument_token", "tradingsymbol", "underlying", "transaction_type",
        "order_type", "product", "lots", "trigger_price", "validity",
        "risk_decision_id", "trading_mode", "parent_position_id",
        "submitted_at", "filled_at", "cancelled_at",
    ]:
        op.drop_column("orders", col)
    op.drop_index("idx_orders_state_created")
    op.drop_index("idx_orders_broker_order_id_nonempty")
