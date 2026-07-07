"""Tests for ComponentCorrelationService — Pearson r computation."""

from __future__ import annotations

import math

import pytest

from core.application.services.research.component_correlation_service import _pearson


class TestPearsonCorrelation:
    def test_perfect_positive_correlation(self) -> None:
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        r, p = _pearson(x, y)
        assert math.isclose(r, 1.0, abs_tol=1e-4)

    def test_perfect_negative_correlation(self) -> None:
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 4.0, 3.0, 2.0, 1.0]
        r, p = _pearson(x, y)
        assert math.isclose(r, -1.0, abs_tol=1e-4)

    def test_constant_x_returns_none(self) -> None:
        x = [3.0, 3.0, 3.0, 3.0]
        y = [1.0, 2.0, 3.0, 4.0]
        r, p = _pearson(x, y)
        assert r is None

    def test_constant_y_returns_none(self) -> None:
        x = [1.0, 2.0, 3.0, 4.0]
        y = [7.0, 7.0, 7.0, 7.0]
        r, p = _pearson(x, y)
        assert r is None

    def test_p_value_between_0_and_1(self) -> None:
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.1, 3.9, 6.2, 7.8, 10.3]
        r, p = _pearson(x, y)
        assert r is not None
        assert 0.0 <= p <= 1.0

    def test_insufficient_data_returns_none(self) -> None:
        r, p = _pearson([1.0], [2.0])
        assert r is None
        assert p is None

    def test_empty_returns_none(self) -> None:
        r, p = _pearson([], [])
        assert r is None

    def test_known_correlation(self) -> None:
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        y = [10.0, 8.0, 6.0, 4.0, 2.0, 0.0]
        r, _ = _pearson(x, y)
        assert r is not None
        assert r < -0.99
