"""Phase TMI — Trade Management Intelligence analytics columns.

Revision ID: 20260630_1100
Revises: 20260630_1000
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "20260630_1100"
down_revision = "20260630_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── signal_analytics: TMI columns ─────────────────────────────────────────
    op.add_column("signal_analytics", sa.Column("capture_ratio",        sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("opportunity_lost_pct", sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("profit_surrender_pct", sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("trade_classification", sa.String(50),    nullable=True))
    # Position outcome (separate from signal outcome — set when trader manually closes)
    op.add_column("signal_analytics", sa.Column("position_exit_price",  sa.Numeric(12, 2), nullable=True))
    op.add_column("signal_analytics", sa.Column("position_closed_at",   sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("signal_analytics", sa.Column("position_return_pct",  sa.Numeric(8, 4), nullable=True))

    # ── tmi_weekly_reports ────────────────────────────────────────────────────
    op.create_table(
        "tmi_weekly_reports",
        sa.Column("id",              sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("week_ending",     sa.Date,       nullable=False),
        sa.Column("lookback_days",   sa.Integer,    nullable=False, server_default="7"),
        sa.Column("total_signals",   sa.Integer,    nullable=True),
        sa.Column("positive_mfe",    sa.Integer,    nullable=True),
        sa.Column("avg_mfe_pct",     sa.Numeric(8, 4), nullable=True),
        sa.Column("avg_capture_ratio",      sa.Numeric(8, 4), nullable=True),
        sa.Column("avg_profit_surrendered", sa.Numeric(8, 4), nullable=True),
        sa.Column("tier_10pct",  sa.Integer, nullable=True),
        sa.Column("tier_20pct",  sa.Integer, nullable=True),
        sa.Column("tier_30pct",  sa.Integer, nullable=True),
        sa.Column("tier_40pct",  sa.Integer, nullable=True),
        sa.Column("tier_50pct",  sa.Integer, nullable=True),
        sa.Column("classifications_json", sa.Text, nullable=True),
        sa.Column("regime_analysis_json", sa.Text, nullable=True),
        sa.Column("full_report_json",     sa.Text, nullable=True),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_tmi_weekly_reports_week_ending", "tmi_weekly_reports", ["week_ending"])


def downgrade() -> None:
    op.drop_table("tmi_weekly_reports")
    for col in [
        "capture_ratio", "opportunity_lost_pct", "profit_surrender_pct",
        "trade_classification", "position_exit_price", "position_closed_at",
        "position_return_pct",
    ]:
        op.drop_column("signal_analytics", col)
