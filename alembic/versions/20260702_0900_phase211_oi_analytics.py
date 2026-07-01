"""Phase 21.1 — OI Analytics Layer.

Creates:
  - oi_history_snapshots table (Parts 1, 2, 9-12)
  - 8 new Futures OI context columns in signal_analytics (Parts 3, 4, 5)

Revision ID: 20260702_0900
Revises: 20260630_1100
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "20260702_0900"
down_revision = "20260630_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── oi_history_snapshots ──────────────────────────────────────────────────
    op.create_table(
        "oi_history_snapshots",
        sa.Column("id",              sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("snapshot_at",     sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("symbol",          sa.String(50),  nullable=False),
        sa.Column("tradingsymbol",   sa.String(50),  nullable=False),
        sa.Column("expiry",          sa.Date,        nullable=False),
        sa.Column("futures_price",   sa.Numeric(12, 4), nullable=True),
        sa.Column("oi",              sa.BigInteger,  nullable=True),
        sa.Column("previous_oi",     sa.BigInteger,  nullable=True),
        sa.Column("oi_change",       sa.BigInteger,  nullable=True),
        sa.Column("oi_change_pct",   sa.Numeric(8, 4), nullable=True),
        sa.Column("oi_direction",    sa.String(20),  nullable=True),
        sa.Column("oi_regime",       sa.String(30),  nullable=True),
        sa.Column("rolling_avg_5",   sa.Numeric(14, 2), nullable=True),
        sa.Column("rolling_avg_15",  sa.Numeric(14, 2), nullable=True),
        sa.Column("rolling_avg_60",  sa.Numeric(14, 2), nullable=True),
        sa.Column("price_change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("quality_tier",    sa.String(20),  nullable=True),
        sa.Column("quality_score",   sa.Integer,     nullable=True),
        sa.Column("cache_age_seconds", sa.Integer,   nullable=True),
        sa.Column("is_anomaly",      sa.Boolean,     nullable=False, server_default="false"),
        sa.Column("anomaly_type",    sa.String(50),  nullable=True),
        sa.Column("is_contract_roll", sa.Boolean,    nullable=False, server_default="false"),
        sa.Column("created_at",      sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("idx_oi_hist_symbol_at",  "oi_history_snapshots", ["symbol", "snapshot_at"])
    op.create_index("idx_oi_hist_regime",     "oi_history_snapshots", ["oi_regime", "snapshot_at"])
    op.create_index("idx_oi_hist_anomaly",    "oi_history_snapshots", ["is_anomaly", "snapshot_at"])
    op.create_index("idx_oi_hist_snap_at",    "oi_history_snapshots", ["snapshot_at"])

    # ── signal_analytics: 8 Futures OI context columns ───────────────────────
    op.add_column("signal_analytics", sa.Column("futures_oi",              sa.BigInteger,    nullable=True))
    op.add_column("signal_analytics", sa.Column("oi_change",               sa.BigInteger,    nullable=True))
    op.add_column("signal_analytics", sa.Column("oi_change_pct",           sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("oi_direction",            sa.String(20),    nullable=True))
    op.add_column("signal_analytics", sa.Column("oi_regime",               sa.String(30),    nullable=True))
    op.add_column("signal_analytics", sa.Column("futures_contract",        sa.String(50),    nullable=True))
    op.add_column("signal_analytics", sa.Column("oi_quality_score",        sa.String(20),    nullable=True))
    op.add_column("signal_analytics", sa.Column("quote_freshness_seconds", sa.Integer,       nullable=True))

    # Index to support failure attribution and TMI queries by regime
    op.create_index("idx_sa_oi_regime", "signal_analytics", ["oi_regime", "was_accepted"])


def downgrade() -> None:
    op.drop_index("idx_sa_oi_regime", table_name="signal_analytics")
    op.drop_column("signal_analytics", "quote_freshness_seconds")
    op.drop_column("signal_analytics", "oi_quality_score")
    op.drop_column("signal_analytics", "futures_contract")
    op.drop_column("signal_analytics", "oi_regime")
    op.drop_column("signal_analytics", "oi_direction")
    op.drop_column("signal_analytics", "oi_change_pct")
    op.drop_column("signal_analytics", "oi_change")
    op.drop_column("signal_analytics", "futures_oi")
    op.drop_index("idx_oi_hist_snap_at",   table_name="oi_history_snapshots")
    op.drop_index("idx_oi_hist_anomaly",   table_name="oi_history_snapshots")
    op.drop_index("idx_oi_hist_regime",    table_name="oi_history_snapshots")
    op.drop_index("idx_oi_hist_symbol_at", table_name="oi_history_snapshots")
    op.drop_table("oi_history_snapshots")
