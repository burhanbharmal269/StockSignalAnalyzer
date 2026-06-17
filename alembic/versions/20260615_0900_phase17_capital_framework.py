"""Phase 17: Capital Allocation Framework.

Revision ID: 006_phase17
Revises: 005_phase15
Create Date: 2026-06-15 09:00:00

Changes:
  NEW TABLES:
    risk_profiles         — named risk parameter bundles
    capital_allocations   — operator-configured capital envelopes
    portfolios            — named position/order groups
    allocation_history    — append-only audit trail (no UPDATE, no DELETE)

  EXISTING TABLES — nullable audit columns added:
    signals       — risk_profile_id, allocation_id, portfolio_id, capital_source_mode
    orders        — risk_profile_id, allocation_id, portfolio_id, capital_source_mode,
                    effective_capital, effective_margin
    positions     — risk_profile_id, allocation_id, portfolio_id, capital_source_mode,
                    effective_capital, effective_margin
    risk_decisions — risk_profile_id, allocation_id, portfolio_id

All new columns in existing tables are nullable so no backfill is required and
existing rows remain valid (backward compatibility invariant).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_phase17"
down_revision: str | None = "005_phase15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # risk_profiles — new table
    # ------------------------------------------------------------------
    op.create_table(
        "risk_profiles",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("profile_type", sa.String(20), nullable=False),
        sa.Column("universe_scope", sa.String(20), nullable=False, server_default="ALL_FNO"),
        sa.Column("risk_per_trade_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("max_open_positions", sa.Integer(), nullable=False),
        sa.Column("daily_loss_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("weekly_loss_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("drawdown_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("max_position_size_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("min_position_size_lots", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("profile_id"),
        sa.UniqueConstraint("name", name="uq_risk_profiles_name"),
    )
    op.create_index("idx_risk_profiles_active", "risk_profiles", ["is_active"])
    op.create_index("idx_risk_profiles_type", "risk_profiles", ["profile_type"])

    # ------------------------------------------------------------------
    # capital_allocations — new table
    # ------------------------------------------------------------------
    op.create_table(
        "capital_allocations",
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("allocation_type", sa.String(20), nullable=False),
        sa.Column("universe_scope", sa.String(20), nullable=False, server_default="ALL_FNO"),
        sa.Column("capital_source_mode", sa.String(15), nullable=False, server_default="HYBRID"),
        sa.Column("allocated_capital", sa.Numeric(16, 2), nullable=False),
        sa.Column("allocated_margin", sa.Numeric(16, 2), nullable=True),
        sa.Column("strategy_type", sa.String(30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("allocation_id"),
        sa.UniqueConstraint("name", name="uq_capital_allocations_name"),
    )
    op.create_index("idx_capital_allocations_active", "capital_allocations", ["is_active"])
    op.create_index("idx_capital_allocations_type", "capital_allocations", ["allocation_type"])

    # ------------------------------------------------------------------
    # portfolios — new table
    # ------------------------------------------------------------------
    op.create_table(
        "portfolios",
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("portfolio_type", sa.String(20), nullable=False),
        sa.Column("risk_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("portfolio_id"),
        sa.UniqueConstraint("name", name="uq_portfolios_name"),
    )
    op.create_index("idx_portfolios_active", "portfolios", ["is_active"])
    op.create_index("idx_portfolios_type", "portfolios", ["portfolio_type"])
    op.create_index("idx_portfolios_owner", "portfolios", ["owner_user_id"])

    # ------------------------------------------------------------------
    # allocation_history — new append-only table
    # ------------------------------------------------------------------
    op.create_table(
        "allocation_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_type", sa.String(30), nullable=False),
        sa.Column("previous_capital", sa.Numeric(16, 2), nullable=True),
        sa.Column("new_capital", sa.Numeric(16, 2), nullable=True),
        sa.Column("previous_margin", sa.Numeric(16, 2), nullable=True),
        sa.Column("new_margin", sa.Numeric(16, 2), nullable=True),
        sa.Column("changed_by", sa.String(50), nullable=False, server_default="system"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_allocation_history_allocation_id",
        "allocation_history",
        ["allocation_id", "changed_at"],
    )

    # ------------------------------------------------------------------
    # signals — add Phase 17 audit columns
    # ------------------------------------------------------------------
    op.add_column("signals", sa.Column("risk_profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("signals", sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("signals", sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("signals", sa.Column("capital_source_mode", sa.String(15), nullable=True))

    # ------------------------------------------------------------------
    # orders — add Phase 17 audit columns
    # ------------------------------------------------------------------
    op.add_column("orders", sa.Column("risk_profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("orders", sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("orders", sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("orders", sa.Column("capital_source_mode", sa.String(15), nullable=True))
    op.add_column("orders", sa.Column("effective_capital", sa.Numeric(16, 2), nullable=True))
    op.add_column("orders", sa.Column("effective_margin", sa.Numeric(16, 2), nullable=True))

    # ------------------------------------------------------------------
    # positions — add Phase 17 audit columns
    # ------------------------------------------------------------------
    op.add_column("positions", sa.Column("risk_profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("positions", sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("positions", sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("positions", sa.Column("capital_source_mode", sa.String(15), nullable=True))
    op.add_column("positions", sa.Column("effective_capital", sa.Numeric(16, 2), nullable=True))
    op.add_column("positions", sa.Column("effective_margin", sa.Numeric(16, 2), nullable=True))

    # ------------------------------------------------------------------
    # risk_decisions — add Phase 17 audit columns
    # ------------------------------------------------------------------
    op.add_column("risk_decisions", sa.Column("risk_profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("risk_decisions", sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("risk_decisions", sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    # risk_decisions
    op.drop_column("risk_decisions", "portfolio_id")
    op.drop_column("risk_decisions", "allocation_id")
    op.drop_column("risk_decisions", "risk_profile_id")

    # positions
    op.drop_column("positions", "effective_margin")
    op.drop_column("positions", "effective_capital")
    op.drop_column("positions", "capital_source_mode")
    op.drop_column("positions", "portfolio_id")
    op.drop_column("positions", "allocation_id")
    op.drop_column("positions", "risk_profile_id")

    # orders
    op.drop_column("orders", "effective_margin")
    op.drop_column("orders", "effective_capital")
    op.drop_column("orders", "capital_source_mode")
    op.drop_column("orders", "portfolio_id")
    op.drop_column("orders", "allocation_id")
    op.drop_column("orders", "risk_profile_id")

    # signals
    op.drop_column("signals", "capital_source_mode")
    op.drop_column("signals", "portfolio_id")
    op.drop_column("signals", "allocation_id")
    op.drop_column("signals", "risk_profile_id")

    # new tables
    op.drop_index("idx_allocation_history_allocation_id", table_name="allocation_history")
    op.drop_table("allocation_history")

    op.drop_index("idx_portfolios_owner", table_name="portfolios")
    op.drop_index("idx_portfolios_type", table_name="portfolios")
    op.drop_index("idx_portfolios_active", table_name="portfolios")
    op.drop_table("portfolios")

    op.drop_index("idx_capital_allocations_type", table_name="capital_allocations")
    op.drop_index("idx_capital_allocations_active", table_name="capital_allocations")
    op.drop_table("capital_allocations")

    op.drop_index("idx_risk_profiles_type", table_name="risk_profiles")
    op.drop_index("idx_risk_profiles_active", table_name="risk_profiles")
    op.drop_table("risk_profiles")
