"""phase22_scanner_intelligence

Revision ID: 20260702_1200
Revises: 20260702_0900
Create Date: 2026-07-02 12:00:00

Phase 22 — Scanner Intelligence & Execution Optimization.
Adds tables for regime snapshots, scan replay, and extended scan_cycle_metrics columns.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260702_1200"
down_revision = "20260702_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── scanner_regime_snapshots: one row per scan cycle ─────────────────────
    op.create_table(
        "scanner_regime_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("regime", sa.String(30), nullable=False),
        sa.Column("sub_regime", sa.String(30), nullable=True),
        sa.Column("vix_level", sa.Numeric(7, 2), nullable=True),
        sa.Column("vix_regime", sa.String(20), nullable=True),
        sa.Column("nifty_regime", sa.String(20), nullable=True),
        sa.Column("breadth_score", sa.Numeric(7, 2), nullable=True),
        sa.Column("advance_decline_ratio", sa.Numeric(7, 3), nullable=True),
        sa.Column("is_expiry_day", sa.Boolean(), nullable=True, server_default=sa.text("FALSE")),
        sa.Column("gap_pct", sa.Numeric(7, 3), nullable=True),
        sa.Column("indicators", postgresql.JSONB(), nullable=True),
    )
    op.create_index("idx_regime_scanned_at", "scanner_regime_snapshots", ["scanned_at"])

    # ── scanner_replay_snapshots: complete scan state for debugging ───────────
    op.create_table(
        "scanner_replay_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("scan_duration_seconds", sa.Numeric(7, 2), nullable=True),
        sa.Column("total_candidates", sa.Integer(), nullable=True),
        sa.Column("accepted", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("rejected", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("gated", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("market_context", postgresql.JSONB(), nullable=True),
        sa.Column("symbol_results", postgresql.JSONB(), nullable=True),
        sa.Column("top_scores", postgresql.JSONB(), nullable=True),
        sa.Column("gate_summary", postgresql.JSONB(), nullable=True),
        sa.Column("regime_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("stage_timings", postgresql.JSONB(), nullable=True),
    )
    op.create_index("idx_replay_scanned_at", "scanner_replay_snapshots", ["scanned_at"])

    # ── Extend scan_cycle_metrics with Phase 22 fields ────────────────────────
    op.add_column("scan_cycle_metrics",
        sa.Column("stage_timings", postgresql.JSONB(), nullable=True))
    op.add_column("scan_cycle_metrics",
        sa.Column("top_scores", postgresql.JSONB(), nullable=True))
    op.add_column("scan_cycle_metrics",
        sa.Column("symbol_timings", postgresql.JSONB(), nullable=True))
    op.add_column("scan_cycle_metrics",
        sa.Column("p95_symbol_time_ms", sa.Numeric(7, 2), nullable=True))
    op.add_column("scan_cycle_metrics",
        sa.Column("slowest_symbol", sa.String(20), nullable=True))
    op.add_column("scan_cycle_metrics",
        sa.Column("slowest_symbol_ms", sa.Numeric(7, 2), nullable=True))
    op.add_column("scan_cycle_metrics",
        sa.Column("health_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("scan_cycle_metrics",
        sa.Column("regime_snapshot", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    for col in ["stage_timings", "top_scores", "symbol_timings", "p95_symbol_time_ms",
                "slowest_symbol", "slowest_symbol_ms", "health_score", "regime_snapshot"]:
        op.drop_column("scan_cycle_metrics", col)
    op.drop_index("idx_replay_scanned_at", "scanner_replay_snapshots")
    op.drop_table("scanner_replay_snapshots")
    op.drop_index("idx_regime_scanned_at", "scanner_regime_snapshots")
    op.drop_table("scanner_regime_snapshots")
