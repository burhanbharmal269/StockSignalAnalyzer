"""Phase 15 — Data Quality, Realized P&L, and Risk Manager columns.

Adds three columns to signal_analytics:

  pnl_pct            — realized P&L % for closed trade
                        WIN  → positive (target return)
                        LOSS → negative (stop loss return)
                        Set by SignalOutcomeTrackerService.update_outcome()

  data_quality_score — 0-100 feed quality score at signal generation time.
                        Monitoring only. Never affects scoring or acceptance.
                        Computed by DataQualityService from option chain age,
                        OI presence, 5m candle presence, VIX, GEX, candle freshness.

  missing_sources    — JSON list of data sources unavailable at signal time.
                        e.g. ["india_vix","gex"] stored as comma-joined string.

All columns are nullable; existing rows receive NULL on upgrade.
Downgrade drops the columns (safe — nullable, no FK constraints).

Revision ID: 20260619_1100
Revises: 20260619_0900
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "20260619_1100"
down_revision = "20260619_0900"
branch_labels = None
depends_on    = None


def _col_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": col},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    for col, typ in [
        ("pnl_pct",            sa.Numeric(8, 4)),
        ("data_quality_score", sa.Integer()),
        ("missing_sources",    sa.String(200)),
    ]:
        if not _col_exists("signal_analytics", col):
            op.add_column("signal_analytics", sa.Column(col, typ, nullable=True))


def downgrade() -> None:
    for col in ["pnl_pct", "data_quality_score", "missing_sources"]:
        if _col_exists("signal_analytics", col):
            op.drop_column("signal_analytics", col)
