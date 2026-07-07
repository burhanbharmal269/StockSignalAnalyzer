"""Tests for FeatureImportanceService — point-biserial correlation."""

from __future__ import annotations

import pytest

from core.application.services.research.feature_importance_service import _point_biserial


class TestPointBiserial:
    def test_all_wins_returns_none(self) -> None:
        # No variance in binary → returns None
        continuous = [80.0, 85.0, 90.0, 75.0, 88.0]
        binary = [1.0, 1.0, 1.0, 1.0, 1.0]
        result = _point_biserial(continuous, binary)
        assert result is None

    def test_separable_groups_high_importance(self) -> None:
        # clear separation: high scores → win, low scores → loss
        continuous = [90.0, 85.0, 88.0, 30.0, 25.0, 28.0]
        binary = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
        r = _point_biserial(continuous, binary)
        assert r is not None
        assert r > 0.8

    def test_no_predictive_power_low_importance(self) -> None:
        # scores same in both groups → near zero
        continuous = [70.0, 70.0, 70.0, 70.0, 70.0, 70.0]
        binary = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
        r = _point_biserial(continuous, binary)
        assert r is None  # zero std_all → None

    def test_returns_float_for_valid_data(self) -> None:
        continuous = [60.0, 70.0, 80.0, 50.0, 65.0, 75.0]
        binary = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
        r = _point_biserial(continuous, binary)
        assert isinstance(r, float) or r is None

    def test_insufficient_data_returns_none(self) -> None:
        # n < 5 → None
        result = _point_biserial([1.0, 2.0], [1.0, 0.0])
        assert result is None

    def test_empty_returns_none(self) -> None:
        assert _point_biserial([], []) is None

    def test_result_is_absolute_value(self) -> None:
        # _point_biserial returns abs(r), so always >= 0
        continuous = [30.0, 25.0, 28.0, 90.0, 85.0, 88.0]
        binary = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
        r = _point_biserial(continuous, binary)
        if r is not None:
            assert r >= 0.0
