"""Tests for ParameterOptimizationService — grid combo builder."""

from __future__ import annotations

import itertools

import pytest

from core.application.services.research.parameter_optimization_service import _build_combos


def _list_combos(grid: dict) -> list[dict]:
    """Consume the generator into a list."""
    return list(_build_combos(grid))


class TestBuildCombos:
    def test_single_param(self) -> None:
        combos = _list_combos({"oi": [20, 25, 30]})
        assert len(combos) == 3
        assert {"oi": 20} in combos

    def test_two_params_cartesian(self) -> None:
        combos = _list_combos({"a": [1, 2], "b": [10, 20]})
        assert len(combos) == 4
        assert {"a": 1, "b": 10} in combos
        assert {"a": 2, "b": 20} in combos

    def test_three_params_cartesian(self) -> None:
        combos = _list_combos({"a": [1, 2], "b": [10, 20], "c": [100, 200]})
        assert len(combos) == 8

    def test_empty_grid_yields_one_empty_dict(self) -> None:
        combos = _list_combos({})
        assert combos == [{}]

    def test_single_value_per_param(self) -> None:
        combos = _list_combos({"x": [5], "y": [10]})
        assert len(combos) == 1
        assert combos[0] == {"x": 5, "y": 10}

    def test_all_combos_are_dicts_with_all_keys(self) -> None:
        combos = _list_combos({"a": [1, 2], "b": [3, 4]})
        for c in combos:
            assert isinstance(c, dict)
            assert "a" in c and "b" in c

    def test_scalar_values_wrapped_in_list(self) -> None:
        combos = _list_combos({"a": 5, "b": [1, 2]})
        assert all(c["a"] == 5 for c in combos)
        assert len(combos) == 2

    def test_large_grid_yields_all_combos(self) -> None:
        grid = {"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8]}
        combos = _list_combos(grid)
        assert len(combos) == 3 * 3 * 2  # 18
