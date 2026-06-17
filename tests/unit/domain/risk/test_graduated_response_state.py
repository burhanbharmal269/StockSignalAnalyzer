"""Unit tests for GraduatedResponseState domain value object."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from core.domain.exceptions.risk import RiskInvariantError
from core.domain.risk.graduated_response_state import GraduatedResponseState

_NOW = datetime.now(UTC)


def _make(**overrides: object) -> GraduatedResponseState:
    defaults: dict[str, object] = {
        "state": "NORMAL",
        "position_size_multiplier": 1.0,
        "activated_at": None,
        "reason": None,
    }
    defaults.update(overrides)
    return GraduatedResponseState(**defaults)  # type: ignore[arg-type]


class TestGraduatedResponseStateConstruction:
    def test_normal_state(self) -> None:
        state = _make()
        assert state.state == "NORMAL"
        assert state.position_size_multiplier == 1.0

    def test_reduced_state(self) -> None:
        state = _make(
            state="REDUCED", position_size_multiplier=0.5,
            activated_at=_NOW, reason="50% daily loss consumed",
        )
        assert state.state == "REDUCED"
        assert state.position_size_multiplier == 0.5

    def test_paper_state(self) -> None:
        state = _make(
            state="PAPER", position_size_multiplier=0.0,
            activated_at=_NOW, reason="75% daily loss consumed",
        )
        assert state.state == "PAPER"
        assert state.position_size_multiplier == 0.0

    def test_killed_state(self) -> None:
        state = _make(
            state="KILLED", position_size_multiplier=0.0,
            activated_at=_NOW, reason="100% daily loss consumed",
        )
        assert state.state == "KILLED"
        assert state.position_size_multiplier == 0.0

    def test_is_frozen(self) -> None:
        state = _make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.state = "PAPER"  # type: ignore[misc]

    def test_invalid_state_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="state"):
            _make(state="UNKNOWN", position_size_multiplier=1.0)

    def test_multiplier_mismatch_normal_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="position_size_multiplier"):
            _make(state="NORMAL", position_size_multiplier=0.5)

    def test_multiplier_mismatch_reduced_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="position_size_multiplier"):
            _make(state="REDUCED", position_size_multiplier=1.0)

    def test_multiplier_mismatch_paper_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="position_size_multiplier"):
            _make(state="PAPER", position_size_multiplier=0.5)
