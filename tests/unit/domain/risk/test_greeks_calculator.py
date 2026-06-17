"""Unit tests for GreeksAggregate VO and GreeksCalculator service."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from core.domain.exceptions.risk import RiskInvariantError
from core.domain.risk.greeks_aggregate import GreeksAggregate
from core.domain.risk.greeks_calculator import GreeksCalculator
from core.domain.risk.greeks_snapshot import GreeksSnapshot

_NOW = datetime.now(UTC)


def _make_snap(**overrides: object) -> GreeksSnapshot:
    defaults: dict[str, object] = {
        "position_id": "pos_001",
        "delta": 0.5,
        "gamma": 0.02,
        "theta": -15.0,
        "vega": 30.0,
        "computed_at": _NOW,
        "from_fallback": False,
    }
    defaults.update(overrides)
    return GreeksSnapshot(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# GreeksAggregate — domain value object
# ===========================================================================


class TestGreeksAggregate:
    def test_valid_construction(self) -> None:
        agg = GreeksAggregate(
            net_delta=1.0,
            net_gamma=0.05,
            net_theta=-30.0,
            net_vega=60.0,
            any_from_fallback=False,
            snapshot_count=2,
        )
        assert agg.net_delta == 1.0
        assert agg.snapshot_count == 2

    def test_zero_snapshot_count_valid(self) -> None:
        agg = GreeksAggregate(
            net_delta=0.0,
            net_gamma=0.0,
            net_theta=0.0,
            net_vega=0.0,
            any_from_fallback=False,
            snapshot_count=0,
        )
        assert agg.snapshot_count == 0

    def test_negative_snapshot_count_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="snapshot_count"):
            GreeksAggregate(
                net_delta=0.0,
                net_gamma=0.0,
                net_theta=0.0,
                net_vega=0.0,
                any_from_fallback=False,
                snapshot_count=-1,
            )

    def test_is_frozen(self) -> None:
        agg = GreeksAggregate(
            net_delta=1.0,
            net_gamma=0.0,
            net_theta=0.0,
            net_vega=0.0,
            any_from_fallback=False,
            snapshot_count=1,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            agg.net_delta = 99.0  # type: ignore[misc]

    def test_negative_fields_valid(self) -> None:
        agg = GreeksAggregate(
            net_delta=-500.0,
            net_gamma=-0.1,
            net_theta=-2500.0,
            net_vega=-1000.0,
            any_from_fallback=True,
            snapshot_count=10,
        )
        assert agg.net_delta == -500.0
        assert agg.any_from_fallback is True


# ===========================================================================
# GreeksCalculator — empty sequence
# ===========================================================================


class TestGreeksCalculatorEmpty:
    def test_empty_returns_zero_net_delta(self) -> None:
        result = GreeksCalculator.aggregate([])
        assert result.net_delta == 0.0

    def test_empty_returns_all_zeros(self) -> None:
        result = GreeksCalculator.aggregate([])
        assert result.net_delta == 0.0
        assert result.net_gamma == 0.0
        assert result.net_theta == 0.0
        assert result.net_vega == 0.0

    def test_empty_any_from_fallback_false(self) -> None:
        assert GreeksCalculator.aggregate([]).any_from_fallback is False

    def test_empty_snapshot_count_zero(self) -> None:
        assert GreeksCalculator.aggregate([]).snapshot_count == 0

    def test_empty_returns_greeks_aggregate_type(self) -> None:
        result = GreeksCalculator.aggregate([])
        assert isinstance(result, GreeksAggregate)


# ===========================================================================
# GreeksCalculator — single snapshot
# ===========================================================================


class TestGreeksCalculatorSingle:
    def test_single_net_delta_equals_snapshot_delta(self) -> None:
        snap = _make_snap(delta=0.45)
        result = GreeksCalculator.aggregate([snap])
        assert abs(result.net_delta - 0.45) < 1e-9

    def test_single_all_fields_copied(self) -> None:
        snap = _make_snap(delta=0.45, gamma=0.02, theta=-15.0, vega=30.0)
        result = GreeksCalculator.aggregate([snap])
        assert abs(result.net_delta - 0.45) < 1e-9
        assert abs(result.net_gamma - 0.02) < 1e-9
        assert abs(result.net_theta - (-15.0)) < 1e-9
        assert abs(result.net_vega - 30.0) < 1e-9

    def test_single_from_fallback_true_propagates(self) -> None:
        snap = _make_snap(from_fallback=True)
        result = GreeksCalculator.aggregate([snap])
        assert result.any_from_fallback is True

    def test_single_from_fallback_false_stays_false(self) -> None:
        snap = _make_snap(from_fallback=False)
        result = GreeksCalculator.aggregate([snap])
        assert result.any_from_fallback is False

    def test_single_snapshot_count_is_one(self) -> None:
        result = GreeksCalculator.aggregate([_make_snap()])
        assert result.snapshot_count == 1


# ===========================================================================
# GreeksCalculator — multiple snapshots
# ===========================================================================


class TestGreeksCalculatorMultiple:
    def test_net_delta_is_sum(self) -> None:
        snaps = [_make_snap(delta=0.5), _make_snap(delta=0.3, position_id="pos_002")]
        result = GreeksCalculator.aggregate(snaps)
        assert abs(result.net_delta - 0.8) < 1e-9

    def test_all_fields_sum_correctly(self) -> None:
        s1 = _make_snap(delta=0.5, gamma=0.02, theta=-10.0, vega=20.0)
        s2 = _make_snap(delta=0.3, gamma=0.01, theta=-5.0, vega=10.0, position_id="pos_002")
        result = GreeksCalculator.aggregate([s1, s2])
        assert abs(result.net_delta - 0.8) < 1e-9
        assert abs(result.net_gamma - 0.03) < 1e-9
        assert abs(result.net_theta - (-15.0)) < 1e-9
        assert abs(result.net_vega - 30.0) < 1e-9

    def test_any_from_fallback_true_if_any(self) -> None:
        snaps = [
            _make_snap(from_fallback=False),
            _make_snap(from_fallback=True, position_id="pos_002"),
            _make_snap(from_fallback=False, position_id="pos_003"),
        ]
        result = GreeksCalculator.aggregate(snaps)
        assert result.any_from_fallback is True

    def test_any_from_fallback_false_if_none(self) -> None:
        snaps = [
            _make_snap(from_fallback=False),
            _make_snap(from_fallback=False, position_id="pos_002"),
        ]
        result = GreeksCalculator.aggregate(snaps)
        assert result.any_from_fallback is False

    def test_negative_deltas_sum_correctly(self) -> None:
        # Mixed LONG CALL (+delta) and LONG PUT (-delta)
        snaps = [
            _make_snap(delta=0.5, position_id="call_001"),
            _make_snap(delta=-0.5, position_id="put_001"),
        ]
        result = GreeksCalculator.aggregate(snaps)
        assert abs(result.net_delta - 0.0) < 1e-9

    def test_snapshot_count_matches_input_length(self) -> None:
        snaps = [
            _make_snap(position_id=f"pos_{i:03d}") for i in range(7)
        ]
        result = GreeksCalculator.aggregate(snaps)
        assert result.snapshot_count == 7

    def test_large_collection_runs_without_error(self) -> None:
        snaps = [
            _make_snap(position_id=f"pos_{i:04d}", delta=0.01, gamma=0.001)
            for i in range(50)
        ]
        result = GreeksCalculator.aggregate(snaps)
        assert result.snapshot_count == 50
        assert abs(result.net_delta - 0.5) < 1e-6

    def test_result_is_frozen(self) -> None:
        result = GreeksCalculator.aggregate([_make_snap()])
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.net_delta = 0.0  # type: ignore[misc]
