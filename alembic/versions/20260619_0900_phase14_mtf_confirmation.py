"""Phase 14 — MTF confirmation attribution columns in signal_analytics.

Adds three columns that store the 5-minute Multi-Timeframe analysis at
signal generation time. These enable post-hoc outcome analysis comparing
MTF-aligned trades vs MTF-conflicted trades (target vs stop win rates).

  mtf_alignment        — 5m candle bias: BULLISH | BEARISH | NEUTRAL
  mtf_score_bonus      — raw score bonus applied by TrendComponent (-4 to +4)
  mtf_confidence_bonus — confidence adjustment via momentum_adj (-5 to +5)

Revision ID: 20260619_0900
Revises: 20260618_1000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260619_0900"
down_revision = "20260618_1000"
branch_labels = None
depends_on = None


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
        ("mtf_alignment",         sa.String(10)),
        ("mtf_score_bonus",       sa.Numeric(4, 1)),
        ("mtf_confidence_bonus",  sa.Numeric(4, 1)),
    ]:
        if not _col_exists("signal_analytics", col):
            op.add_column("signal_analytics", sa.Column(col, typ, nullable=True))


def downgrade() -> None:
    for col in ["mtf_alignment", "mtf_score_bonus", "mtf_confidence_bonus"]:
        if _col_exists("signal_analytics", col):
            op.drop_column("signal_analytics", col)
