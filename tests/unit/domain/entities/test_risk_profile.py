"""Unit tests — RiskProfile entity."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.domain.entities.risk_profile import RiskProfile
from core.domain.enums.risk_profile_type import RiskProfileType
from core.domain.enums.universe_scope import UniverseScope


def _make_profile(**kwargs: object) -> RiskProfile:
    defaults = dict(
        profile_id=uuid.uuid4(),
        name="Test",
        profile_type=RiskProfileType.MODERATE,
        universe_scope=UniverseScope.ALL_FNO,
        risk_per_trade_pct=Decimal("2.0"),
        max_open_positions=5,
        daily_loss_pct=Decimal("3.0"),
        weekly_loss_pct=Decimal("8.0"),
        drawdown_pct=Decimal("12.0"),
        max_position_size_pct=Decimal("20.0"),
        min_position_size_lots=1,
    )
    defaults.update(kwargs)
    return RiskProfile(**defaults)  # type: ignore[arg-type]


class TestRiskProfilePresets:
    def test_conservative_preset(self) -> None:
        p = RiskProfile.conservative()
        assert p.profile_type == RiskProfileType.CONSERVATIVE
        assert p.risk_per_trade_pct == Decimal("1.0")
        assert p.max_open_positions == 3
        assert p.daily_loss_pct == Decimal("2.0")

    def test_moderate_preset(self) -> None:
        p = RiskProfile.moderate()
        assert p.profile_type == RiskProfileType.MODERATE
        assert p.risk_per_trade_pct == Decimal("2.0")
        assert p.max_open_positions == 5

    def test_aggressive_preset(self) -> None:
        p = RiskProfile.aggressive()
        assert p.profile_type == RiskProfileType.AGGRESSIVE
        assert p.risk_per_trade_pct == Decimal("3.0")
        assert p.max_open_positions == 10

    def test_presets_start_inactive(self) -> None:
        for factory in (RiskProfile.conservative, RiskProfile.moderate, RiskProfile.aggressive):
            assert factory().is_active is False


class TestRiskProfileLifecycle:
    def test_activate(self) -> None:
        p = _make_profile()
        assert p.is_active is False
        p.activate()
        assert p.is_active is True

    def test_deactivate(self) -> None:
        p = _make_profile()
        p.activate()
        p.deactivate()
        assert p.is_active is False

    def test_update_valid_field(self) -> None:
        p = _make_profile()
        p.update(max_open_positions=10)
        assert p.max_open_positions == 10

    def test_update_invalid_field_raises(self) -> None:
        p = _make_profile()
        with pytest.raises(ValueError, match="no field"):
            p.update(nonexistent_field=99)


class TestRiskProfileCreate:
    def test_create_factory(self) -> None:
        p = RiskProfile.create(
            name="Custom",
            profile_type=RiskProfileType.CUSTOM,
            universe_scope=UniverseScope.NIFTY_ONLY,
            risk_per_trade_pct=Decimal("1.5"),
            max_open_positions=4,
            daily_loss_pct=Decimal("2.5"),
            weekly_loss_pct=Decimal("6.0"),
            drawdown_pct=Decimal("10.0"),
            max_position_size_pct=Decimal("15.0"),
        )
        assert p.name == "Custom"
        assert p.profile_type == RiskProfileType.CUSTOM
        assert p.profile_id is not None
        assert p.is_active is False
