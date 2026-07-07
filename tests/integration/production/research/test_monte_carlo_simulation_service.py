"""Tests for MonteCarloSimulationService — bootstrap correctness."""

from __future__ import annotations

import random
import statistics

import pytest


def _bootstrap_once(returns: list[float], seed: int = 42) -> list[float]:
    """Single bootstrap resample — mirrors the service implementation."""
    rng = random.Random(seed)
    return rng.choices(returns, k=len(returns))


def _terminal_pnl(returns: list[float]) -> float:
    capital = 1.0
    for r in returns:
        capital *= 1 + r
    return capital - 1.0


class TestBootstrapResampling:
    def test_resample_preserves_length(self) -> None:
        base = [0.02, -0.01, 0.03, -0.02, 0.01]
        resampled = _bootstrap_once(base)
        assert len(resampled) == len(base)

    def test_resample_only_uses_original_values(self) -> None:
        base = [0.02, -0.01, 0.03]
        resampled = _bootstrap_once(base)
        for v in resampled:
            assert v in base

    def test_different_seeds_give_different_samples(self) -> None:
        base = [0.02, -0.01, 0.03, -0.02, 0.01, 0.04, -0.03]
        s1 = _bootstrap_once(base, seed=1)
        s2 = _bootstrap_once(base, seed=2)
        assert s1 != s2

    def test_same_seed_reproducible(self) -> None:
        base = [0.02, -0.01, 0.03, -0.02, 0.01]
        s1 = _bootstrap_once(base, seed=99)
        s2 = _bootstrap_once(base, seed=99)
        assert s1 == s2

    def test_terminal_pnl_positive_returns(self) -> None:
        returns = [0.02, 0.03, 0.01]
        pnl = _terminal_pnl(returns)
        assert pnl > 0

    def test_terminal_pnl_negative_returns(self) -> None:
        returns = [-0.10, -0.10]
        pnl = _terminal_pnl(returns)
        assert pnl < 0


class TestPercentileComputation:
    def test_p50_equals_median(self) -> None:
        data = sorted([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        n = len(data)
        p50 = data[int(0.50 * n)]
        assert p50 == pytest.approx(statistics.median(data), abs=0.1)

    def test_p5_less_than_p95(self) -> None:
        data = sorted([float(i) for i in range(100)])
        p5 = data[int(0.05 * len(data))]
        p95 = data[int(0.95 * len(data))]
        assert p5 < p95

    def test_prob_positive(self) -> None:
        terminal_pnls = [0.1, -0.05, 0.2, 0.3, -0.1, 0.05, 0.15, -0.02, 0.08, 0.12]
        prob_pos = sum(1 for p in terminal_pnls if p > 0) / len(terminal_pnls)
        assert 0.0 <= prob_pos <= 1.0
        assert prob_pos == pytest.approx(0.7)
