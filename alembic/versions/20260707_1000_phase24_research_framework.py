"""phase24_research_framework

Revision ID: 20260707_1000
Revises: 20260702_1600
Create Date: 2026-07-07 10:00:00

Phase 24 — Strategy Research, Optimization & Versioning Framework.
Creates 15 research_* tables for offline strategy simulation,
weight optimization, walk-forward analysis, Monte Carlo simulation,
and promotion workflow. All tables are read-only consumers of
signal_analytics — production scoring is never modified.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260707_1000"
down_revision = "20260702_1600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── research_strategy_versions: version registry ──────────────────────────
    op.create_table(
        "research_strategy_versions",
        sa.Column("id",                    UUID(as_uuid=False), primary_key=True),
        sa.Column("name",                  sa.String(100), nullable=False),
        sa.Column("description",           sa.Text, nullable=True),
        sa.Column("weights_snapshot",      JSONB, nullable=False),
        sa.Column("params_snapshot",       JSONB, nullable=True),
        sa.Column("is_immutable",          sa.Boolean, server_default="false", nullable=False),
        sa.Column("base_version_id",       UUID(as_uuid=False), nullable=True),
        sa.Column("scoring_weights_sha256", sa.String(64), nullable=True),
        sa.Column("created_at",            sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",            sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rsv_name", "research_strategy_versions", ["name"])
    op.create_index("ix_rsv_is_immutable", "research_strategy_versions", ["is_immutable"])

    # ── research_runs: parent run record for any research job ─────────────────
    op.create_table(
        "research_runs",
        sa.Column("id",           UUID(as_uuid=False), primary_key=True),
        sa.Column("version_id",   UUID(as_uuid=False), nullable=True, index=True),
        sa.Column("run_type",     sa.String(30), nullable=False, index=True),
        sa.Column("status",       sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("params",       JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at",   sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at",   sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_research_runs_created_at", "research_runs", ["created_at"])

    # ── research_optimization_runs: grid search metadata ─────────────────────
    op.create_table(
        "research_optimization_runs",
        sa.Column("id",                 UUID(as_uuid=False), primary_key=True),
        sa.Column("run_id",             UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("param_grid",         JSONB, nullable=False),
        sa.Column("metric",             sa.String(30), nullable=False, server_default="sharpe"),
        sa.Column("lookback_days",      sa.Integer, nullable=False, server_default="252"),
        sa.Column("combos_total",       sa.Integer, nullable=True),
        sa.Column("combos_completed",   sa.Integer, server_default="0"),
        sa.Column("best_params",        JSONB, nullable=True),
        sa.Column("best_metric_value",  sa.Float, nullable=True),
        sa.Column("created_at",         sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── research_optimization_results: one row per param combo ───────────────
    op.create_table(
        "research_optimization_results",
        sa.Column("id",               sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id",           UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("params",           JSONB, nullable=False),
        sa.Column("sharpe",           sa.Float, nullable=True),
        sa.Column("sortino",          sa.Float, nullable=True),
        sa.Column("calmar",           sa.Float, nullable=True),
        sa.Column("max_drawdown_pct", sa.Float, nullable=True),
        sa.Column("win_rate",         sa.Float, nullable=True),
        sa.Column("profit_factor",    sa.Float, nullable=True),
        sa.Column("trade_count",      sa.Integer, nullable=True),
        sa.Column("avg_trade_pnl",    sa.Float, nullable=True),
        sa.Column("created_at",       sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ror_sharpe", "research_optimization_results", ["run_id", "sharpe"])

    # ── research_walk_forward_windows: per-window OOS results ────────────────
    op.create_table(
        "research_walk_forward_windows",
        sa.Column("id",              sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id",          UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("window_idx",      sa.Integer, nullable=False),
        sa.Column("train_from",      sa.Date, nullable=True),
        sa.Column("train_to",        sa.Date, nullable=True),
        sa.Column("validate_from",   sa.Date, nullable=True),
        sa.Column("validate_to",     sa.Date, nullable=True),
        sa.Column("test_from",       sa.Date, nullable=True),
        sa.Column("test_to",         sa.Date, nullable=True),
        sa.Column("is_sharpe",       sa.Float, nullable=True),
        sa.Column("oos_sharpe",      sa.Float, nullable=True),
        sa.Column("oos_win_rate",    sa.Float, nullable=True),
        sa.Column("oos_trade_count", sa.Integer, nullable=True),
        sa.Column("oos_pnl",         sa.Float, nullable=True),
        sa.Column("best_params",     JSONB, nullable=True),
        sa.Column("created_at",      sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── research_monte_carlo_runs: MC run metadata ────────────────────────────
    op.create_table(
        "research_monte_carlo_runs",
        sa.Column("id",             UUID(as_uuid=False), primary_key=True),
        sa.Column("run_id",         UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("n_sims",         sa.Integer, nullable=False, server_default="1000"),
        sa.Column("seed",           sa.Integer, nullable=True),
        sa.Column("lookback_days",  sa.Integer, nullable=False, server_default="252"),
        sa.Column("percentile_5",   sa.Float, nullable=True),
        sa.Column("percentile_25",  sa.Float, nullable=True),
        sa.Column("percentile_50",  sa.Float, nullable=True),
        sa.Column("percentile_75",  sa.Float, nullable=True),
        sa.Column("percentile_95",  sa.Float, nullable=True),
        sa.Column("prob_positive",  sa.Float, nullable=True),
        sa.Column("created_at",     sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── research_monte_carlo_results: one row per simulation ─────────────────
    op.create_table(
        "research_monte_carlo_results",
        sa.Column("id",               sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id",           UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("sim_idx",          sa.Integer, nullable=False),
        sa.Column("terminal_pnl",     sa.Float, nullable=True),
        sa.Column("max_drawdown_pct", sa.Float, nullable=True),
        sa.Column("sharpe",           sa.Float, nullable=True),
        sa.Column("win_rate",         sa.Float, nullable=True),
    )
    op.create_index("ix_rmcr_run_id", "research_monte_carlo_results", ["run_id"])

    # ── research_performance_snapshots: aggregated metrics per version ────────
    op.create_table(
        "research_performance_snapshots",
        sa.Column("id",               sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("version_id",       UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("lookback_days",    sa.Integer, nullable=False),
        sa.Column("sharpe",           sa.Float, nullable=True),
        sa.Column("sortino",          sa.Float, nullable=True),
        sa.Column("calmar",           sa.Float, nullable=True),
        sa.Column("max_drawdown_pct", sa.Float, nullable=True),
        sa.Column("win_rate",         sa.Float, nullable=True),
        sa.Column("profit_factor",    sa.Float, nullable=True),
        sa.Column("avg_trade_pnl",    sa.Float, nullable=True),
        sa.Column("trade_count",      sa.Integer, nullable=True),
        sa.Column("computed_at",      sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rps_computed_at", "research_performance_snapshots", ["computed_at"])

    # ── research_component_correlations: pairwise Pearson r ──────────────────
    op.create_table(
        "research_component_correlations",
        sa.Column("id",            sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("lookback_days", sa.Integer, nullable=False),
        sa.Column("component_a",   sa.String(50), nullable=False),
        sa.Column("component_b",   sa.String(50), nullable=False),
        sa.Column("pearson_r",     sa.Float, nullable=True),
        sa.Column("p_value",       sa.Float, nullable=True),
        sa.Column("computed_at",   sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rcc_computed_at", "research_component_correlations", ["computed_at"])

    # ── research_feature_importance: per-component predictive power ───────────
    op.create_table(
        "research_feature_importance",
        sa.Column("id",               sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("lookback_days",    sa.Integer, nullable=False),
        sa.Column("component",        sa.String(50), nullable=False),
        sa.Column("importance_score", sa.Float, nullable=True),
        sa.Column("rank",             sa.Integer, nullable=True),
        sa.Column("computed_at",      sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rfi_computed_at", "research_feature_importance", ["computed_at"])

    # ── research_regime_performance: win rate by regime × direction ───────────
    op.create_table(
        "research_regime_performance",
        sa.Column("id",            sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("version_id",    sa.String(36), nullable=True),
        sa.Column("regime",        sa.String(30), nullable=False, index=True),
        sa.Column("direction",     sa.String(10), nullable=False),
        sa.Column("strategy_type", sa.String(30), nullable=True),
        sa.Column("win_rate",      sa.Float, nullable=True),
        sa.Column("avg_score",     sa.Float, nullable=True),
        sa.Column("avg_pnl",       sa.Float, nullable=True),
        sa.Column("sample_size",   sa.Integer, nullable=True),
        sa.Column("lookback_days", sa.Integer, nullable=False),
        sa.Column("computed_at",   sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rrp_computed_at", "research_regime_performance", ["computed_at"])

    # ── research_symbol_rankings: per-ticker performance ranking ─────────────
    op.create_table(
        "research_symbol_rankings",
        sa.Column("id",                   sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticker",               sa.String(50), nullable=False, index=True),
        sa.Column("signal_count",         sa.Integer, nullable=True),
        sa.Column("win_rate",             sa.Float, nullable=True),
        sa.Column("avg_score",            sa.Float, nullable=True),
        sa.Column("avg_pnl",              sa.Float, nullable=True),
        sa.Column("avg_mfe",              sa.Float, nullable=True),
        sa.Column("composite_rank_score", sa.Float, nullable=True),
        sa.Column("rank",                 sa.Integer, nullable=True),
        sa.Column("lookback_days",        sa.Integer, nullable=False),
        sa.Column("computed_at",          sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rsr_computed_at", "research_symbol_rankings", ["computed_at"])
    op.create_index("ix_rsr_rank", "research_symbol_rankings", ["rank"])

    # ── research_false_positive_analysis: FP/FN by component + score bucket ──
    op.create_table(
        "research_false_positive_analysis",
        sa.Column("id",                  sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("component",           sa.String(50), nullable=False, index=True),
        sa.Column("score_bucket",        sa.String(20), nullable=False),
        sa.Column("false_positive_rate", sa.Float, nullable=True),
        sa.Column("false_negative_rate", sa.Float, nullable=True),
        sa.Column("sample_size",         sa.Integer, nullable=True),
        sa.Column("lookback_days",       sa.Integer, nullable=False),
        sa.Column("computed_at",         sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rfpa_computed_at", "research_false_positive_analysis", ["computed_at"])

    # ── research_promotion_requests: strategy promotion workflow ──────────────
    op.create_table(
        "research_promotion_requests",
        sa.Column("id",                    UUID(as_uuid=False), primary_key=True),
        sa.Column("version_id",            UUID(as_uuid=False), nullable=False, index=True),
        sa.Column("requested_by",          sa.String(100), nullable=True),
        sa.Column("status",                sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("stat_test_passed",      sa.Boolean, nullable=True),
        sa.Column("oos_sharpe",            sa.Float, nullable=True),
        sa.Column("oos_win_rate",          sa.Float, nullable=True),
        sa.Column("walk_forward_windows",  sa.Integer, nullable=True),
        sa.Column("promotion_notes",       sa.Text, nullable=True),
        sa.Column("rejection_reason",      sa.Text, nullable=True),
        sa.Column("reviewed_by",           sa.String(100), nullable=True),
        sa.Column("reviewed_at",           sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at",            sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rpr_status", "research_promotion_requests", ["status"])
    op.create_index("ix_rpr_created_at", "research_promotion_requests", ["created_at"])

    # ── research_threshold_analysis: optimal threshold values ─────────────────
    op.create_table(
        "research_threshold_analysis",
        sa.Column("id",                     sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("version_id",             UUID(as_uuid=False), nullable=True),
        sa.Column("threshold_type",         sa.String(50), nullable=False, index=True),
        sa.Column("current_value",          sa.Float, nullable=True),
        sa.Column("optimal_value",          sa.Float, nullable=True),
        sa.Column("metric_improvement_pct", sa.Float, nullable=True),
        sa.Column("metric_name",            sa.String(30), nullable=True),
        sa.Column("sample_size",            sa.Integer, nullable=True),
        sa.Column("lookback_days",          sa.Integer, nullable=False),
        sa.Column("computed_at",            sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rta_computed_at", "research_threshold_analysis", ["computed_at"])


def downgrade() -> None:
    op.drop_table("research_threshold_analysis")
    op.drop_table("research_promotion_requests")
    op.drop_table("research_false_positive_analysis")
    op.drop_table("research_symbol_rankings")
    op.drop_table("research_regime_performance")
    op.drop_table("research_feature_importance")
    op.drop_table("research_component_correlations")
    op.drop_table("research_performance_snapshots")
    op.drop_table("research_monte_carlo_results")
    op.drop_table("research_monte_carlo_runs")
    op.drop_table("research_walk_forward_windows")
    op.drop_table("research_optimization_results")
    op.drop_table("research_optimization_runs")
    op.drop_table("research_runs")
    op.drop_table("research_strategy_versions")
