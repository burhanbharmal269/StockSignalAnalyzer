"""Tests for PerformanceMetricsService — Sharpe/Sortino/Calmar/max-drawdown formulas."""

from __future__ import annotations

import math

import pytest

from core.application.services.research.performance_metrics_service import compute_metrics


class TestComputeMetrics:
    def test_empty_returns_none_metrics(self) -> None:
        m = compute_metrics([])
        assert m["sharpe"] is None
        assert m["win_rate"] is None
        assert m["trade_count"] == 0

    def test_all_wins_profit_factor_is_none(self) -> None:
        # No losses → profit_factor is None (gross_loss == 0)
        returns = [0.02, 0.03, 0.015, 0.025]
        m = compute_metrics(returns)
        assert m["win_rate"] == 100.0  # win_rate is in % (0-100)
        assert m["profit_factor"] is None

    def test_all_losses(self) -> None:
        returns = [-0.02, -0.03]
        m = compute_metrics(returns)
        assert m["win_rate"] == 0.0
        assert m["sharpe"] is not None
        assert m["sharpe"] < 0
        assert m["profit_factor"] is None  # no gains

    def test_mixed_returns_win_rate_percent(self) -> None:
        returns = [0.05, -0.02, 0.03, -0.01, 0.04]
        m = compute_metrics(returns)
        # 3 wins out of 5 → 60%
        assert m["win_rate"] == pytest.approx(60.0)
        assert m["trade_count"] == 5

    def test_mixed_returns_profit_factor_positive(self) -> None:
        returns = [0.05, -0.02, 0.03, -0.01, 0.04]
        m = compute_metrics(returns)
        assert m["profit_factor"] is not None
        assert m["profit_factor"] > 0

    def test_max_drawdown_monotone_decline(self) -> None:
        returns = [-5.0, -5.0, -5.0]
        m = compute_metrics(returns)
        assert m["max_drawdown_pct"] is not None
        assert m["max_drawdown_pct"] > 0

    def test_sortino_returns_none_for_all_positive(self) -> None:
        # No negative returns → sortino is None
        all_positive = [0.02, 0.03, 0.01, 0.04, 0.02]
        m = compute_metrics(all_positive)
        assert m["sortino"] is None

    def test_sortino_computed_for_mixed(self) -> None:
        returns = [0.03, -0.01, 0.02, -0.005, 0.025]
        m = compute_metrics(returns)
        assert m["sortino"] is not None

    def test_calmar_present(self) -> None:
        returns = [3.0, -1.0, 2.0, -0.5, 2.5]
        m = compute_metrics(returns)
        assert "calmar" in m

    def test_single_trade(self) -> None:
        m = compute_metrics([5.0])
        assert m["trade_count"] == 1
        assert m["win_rate"] == 100.0
        # sharpe requires n >= 2
        assert m["sharpe"] is None

    def test_avg_trade_pnl(self) -> None:
        returns = [1.0, 2.0, 3.0]
        m = compute_metrics(returns)
        assert m["avg_trade_pnl"] == pytest.approx(2.0, abs=1e-3)
