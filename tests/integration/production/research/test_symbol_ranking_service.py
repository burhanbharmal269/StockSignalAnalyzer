"""Tests for SymbolRankingService — composite rank score and normalisation."""

from __future__ import annotations

import pytest

from core.application.services.research.symbol_ranking_service import _normalise


class TestNormalise:
    def test_uniform_returns_midpoint(self) -> None:
        result = _normalise([5.0, 5.0, 5.0])
        assert result == [0.5, 0.5, 0.5]

    def test_min_max_bounds(self) -> None:
        result = _normalise([0.0, 5.0, 10.0])
        assert result[0] == pytest.approx(0.0)
        assert result[-1] == pytest.approx(1.0)

    def test_intermediate_value(self) -> None:
        result = _normalise([0.0, 5.0, 10.0])
        assert result[1] == pytest.approx(0.5)

    def test_single_element_returns_midpoint(self) -> None:
        result = _normalise([7.0])
        assert result == [0.5]

    def test_empty_list_returns_empty(self) -> None:
        result = _normalise([])
        assert result == []

    def test_negative_values(self) -> None:
        result = _normalise([-10.0, 0.0, 10.0])
        assert result[0] == pytest.approx(0.0)
        assert result[-1] == pytest.approx(1.0)

    def test_preserves_order(self) -> None:
        values = [3.0, 1.0, 4.0, 1.0, 5.0]
        result = _normalise(values)
        # max (5.0) should map to 1.0
        assert result[4] == pytest.approx(1.0)
        # min (1.0) should map to 0.0
        assert result[1] == pytest.approx(0.0)

    def test_two_elements(self) -> None:
        result = _normalise([0.0, 10.0])
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(1.0)
