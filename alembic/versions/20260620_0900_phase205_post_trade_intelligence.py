"""Phase 20.5 — Post-Trade Intelligence columns on signal_analytics.

Adds attribution, quality, journey, premium, and explainability columns
so the PostTradeIntelligenceService can enrich completed trade records
without creating a new table.

All columns are nullable; existing rows receive NULL on upgrade.
No production logic is changed — these are analytics-only fields.

Revision ID: 20260620_0900
Revises: 20260619_1200
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "20260620_0900"
down_revision = "20260619_1200"
branch_labels = None
depends_on    = None

# (column_name, SQLAlchemy type) — all nullable
_NEW_COLS = [
    # ── Section 13 — Failure Attribution ────────────────────────────────
    ("failure_reason",          sa.String(40)),
    ("failure_confidence",      sa.Numeric(4, 3)),
    ("failure_snapshot_json",   sa.Text()),

    # ── Section 14 — Winner Attribution ─────────────────────────────────
    ("success_reason",          sa.String(40)),
    ("success_confidence",      sa.Numeric(4, 3)),
    ("success_snapshot_json",   sa.Text()),

    # ── Section 15 — Trade Journey (times already exist; new ones below) ─
    ("time_to_mfe_minutes",             sa.Integer()),
    ("time_to_mae_minutes",             sa.Integer()),
    ("maximum_favorable_duration_min",  sa.Integer()),
    ("maximum_adverse_duration_min",    sa.Integer()),

    # ── Section 16 — Stop-Loss Intelligence ──────────────────────────────
    ("stop_timing_bucket",      sa.String(15)),   # IMMEDIATE/EARLY/MEDIUM/LATE

    # ── Section 17 — Recovery Analysis ───────────────────────────────────
    ("recovered_after_stop",    sa.Boolean()),
    ("recovery_time_minutes",   sa.Integer()),
    ("future_mfe_pct",          sa.Numeric(8, 4)),

    # ── Section 18 — Signal Quality ──────────────────────────────────────
    ("signal_quality_score",    sa.Numeric(5, 1)),
    ("signal_quality_category", sa.String(12)),   # EXCELLENT/GOOD/ACCEPTABLE/WEAK/FAILED

    # ── Section 20 — Gate Attribution ────────────────────────────────────
    ("gate_snapshot_json",      sa.Text()),
    ("gate_pass_count",         sa.Integer()),
    ("gate_fail_count",         sa.Integer()),

    # ── Section 21 — Premium Decay Intelligence ───────────────────────────
    ("premium_efficiency",      sa.Numeric(7, 4)),
    ("premium_capture_ratio",   sa.Numeric(7, 4)),
    ("theta_drag_estimate",     sa.Numeric(7, 4)),
    ("iv_drag_estimate",        sa.Numeric(7, 4)),

    # ── Section 22 — Model Failure Classification ─────────────────────────
    ("model_failure_class",     sa.String(25)),  # ACCEPTABLE_LOSS/MODEL_FAILURE/EXECUTION_FAILURE/MARKET_ANOMALY

    # ── Section 24 — Operator Explainability ──────────────────────────────
    ("operator_explanation",    sa.Text()),

    # ── Metadata ─────────────────────────────────────────────────────────
    ("attributed_at",           sa.DateTime(timezone=True)),
]


def _col_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    r = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c AND table_schema='public'"
        ),
        {"t": table, "c": col},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    for col, typ in _NEW_COLS:
        if not _col_exists("signal_analytics", col):
            op.add_column("signal_analytics", sa.Column(col, typ, nullable=True))

    # Index attribution fields for fast report queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sa_failure_reason "
        "ON signal_analytics (failure_reason) WHERE failure_reason IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sa_quality_category "
        "ON signal_analytics (signal_quality_category) WHERE signal_quality_category IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sa_model_failure "
        "ON signal_analytics (model_failure_class) WHERE model_failure_class IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sa_attributed "
        "ON signal_analytics (attributed_at) WHERE attributed_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sa_attributed")
    op.execute("DROP INDEX IF EXISTS idx_sa_model_failure")
    op.execute("DROP INDEX IF EXISTS idx_sa_quality_category")
    op.execute("DROP INDEX IF EXISTS idx_sa_failure_reason")

    for col, _ in reversed(_NEW_COLS):
        if _col_exists("signal_analytics", col):
            op.drop_column("signal_analytics", col)
