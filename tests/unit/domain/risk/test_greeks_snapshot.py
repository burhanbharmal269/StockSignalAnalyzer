"""Unit tests for GreeksSnapshot domain value object."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from core.domain.exceptions.risk import RiskInvariantError
from core.domain.risk.greeks_snapshot import GreeksSnapshot

_NOW = datetime.now(UTC)


def _make(**overrides: object) -> GreeksSnapshot:
    defaults: dict[str, object] = {
        "position_id": "pos_001",
        "delta": 0.45,
        "gamma": 0.02,
        "theta": -15.0,
        "vega": 30.0,
        "computed_at": _NOW,
        "from_fallback": False,
    }
    defaults.update(overrides)
    return GreeksSnapshot(**defaults)  # type: ignore[arg-type]


class TestGreeksSnapshotConstruction:
    def test_valid_construction(self) -> None:
        snap = _make()
        assert snap.position_id == "pos_001"
        assert snap.delta == 0.45
        assert snap.from_fallback is False

    def test_is_frozen(self) -> None:
        snap = _make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.delta = 0.0  # type: ignore[misc]

    def test_empty_position_id_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="position_id"):
            _make(position_id="")

    def test_fallback_flag_true(self) -> None:
        snap = _make(from_fallback=True)
        assert snap.from_fallback is True

    def test_negative_theta_valid(self) -> None:
        snap = _make(theta=-50.0)
        assert snap.theta == -50.0

    def test_negative_vega_valid(self) -> None:
        snap = _make(vega=-10.0)
        assert snap.vega == -10.0
