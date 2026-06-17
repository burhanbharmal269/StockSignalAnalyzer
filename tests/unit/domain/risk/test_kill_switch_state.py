"""Unit tests for KillSwitchState domain value object."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from core.domain.exceptions.risk import RiskInvariantError
from core.domain.risk.kill_switch_state import KillSwitchState

_NOW = datetime.now(UTC)


def _make(**overrides: object) -> KillSwitchState:
    defaults: dict[str, object] = {
        "is_active": False,
        "activated_at": None,
        "activated_by": None,
        "activation_reason": None,
        "deactivated_at": None,
        "deactivated_by": None,
        "deactivation_note": None,
    }
    defaults.update(overrides)
    return KillSwitchState(**defaults)  # type: ignore[arg-type]


class TestKillSwitchStateConstruction:
    def test_inactive_default(self) -> None:
        state = _make()
        assert state.is_active is False
        assert state.activated_by is None

    def test_is_frozen(self) -> None:
        state = _make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.is_active = True  # type: ignore[misc]

    def test_active_state_with_metadata(self) -> None:
        state = _make(
            is_active=True,
            activated_at=_NOW,
            activated_by="operator",
            activation_reason="manual test",
        )
        assert state.is_active is True
        assert state.activated_by == "operator"

    def test_invalid_activated_by_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="activated_by"):
            _make(activated_by="unknown_actor")

    def test_valid_activated_by_values(self) -> None:
        for actor in ("operator", "risk_engine", "dead_mans_switch", "system"):
            state = _make(activated_by=actor)
            assert state.activated_by == actor

    def test_none_activated_by_is_valid(self) -> None:
        state = _make(activated_by=None)
        assert state.activated_by is None

    def test_deactivated_state(self) -> None:
        state = _make(
            is_active=False,
            activated_at=_NOW,
            activated_by="risk_engine",
            deactivated_at=_NOW,
            deactivated_by="admin",
            deactivation_note="manual reset",
        )
        assert state.is_active is False
        assert state.deactivated_by == "admin"
