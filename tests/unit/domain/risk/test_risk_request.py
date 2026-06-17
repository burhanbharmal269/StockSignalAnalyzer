"""Unit tests for RiskRequest domain value object."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.domain.exceptions.risk import RiskInvariantError
from core.domain.risk.risk_request import RiskRequest

_NOW = datetime.now(UTC)
_SIG_ID = uuid.uuid4()


def _make(**overrides: object) -> RiskRequest:
    defaults: dict[str, object] = {
        "signal_id": _SIG_ID,
        "instrument_token": 12345678,
        "underlying": "NIFTY",
        "instrument_class": "OPTION",
        "direction": "LONG",
        "adjusted_score": 75.0,
        "final_confidence": 80.0,
        "entry_price": Decimal("22000"),
        "stop_loss_price": Decimal("21800"),
        "target_price": Decimal("22300"),
        "option_premium": Decimal("150"),
        "lot_size": 50,
        "option_delta": 0.45,
        "option_vega": 30.0,
        "dte": 7,
        "atr_14": 120.5,
        "risk_reward_ratio": 1.5,
        "evaluated_at": _NOW,
    }
    defaults.update(overrides)
    return RiskRequest(**defaults)  # type: ignore[arg-type]


class TestRiskRequestConstruction:
    def test_valid_option_request(self) -> None:
        req = _make()
        assert req.underlying == "NIFTY"
        assert req.instrument_class == "OPTION"
        assert req.direction == "LONG"

    def test_valid_future_request(self) -> None:
        req = _make(
            instrument_class="FUTURE", option_premium=None, option_delta=None, option_vega=None
        )
        assert req.instrument_class == "FUTURE"
        assert req.option_premium is None

    def test_is_frozen(self) -> None:
        req = _make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            req.underlying = "BANKNIFTY"  # type: ignore[misc]

    def test_adjusted_score_below_zero_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="adjusted_score"):
            _make(adjusted_score=-0.1)

    def test_adjusted_score_above_100_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="adjusted_score"):
            _make(adjusted_score=100.1)

    def test_final_confidence_below_zero_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="final_confidence"):
            _make(final_confidence=-1.0)

    def test_final_confidence_above_100_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="final_confidence"):
            _make(final_confidence=101.0)

    def test_invalid_instrument_class_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="instrument_class"):
            _make(instrument_class="EQUITY")

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="direction"):
            _make(direction="BUY")

    def test_zero_entry_price_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="entry_price"):
            _make(entry_price=Decimal("0"))

    def test_negative_entry_price_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="entry_price"):
            _make(entry_price=Decimal("-1"))

    def test_zero_stop_loss_price_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="stop_loss_price"):
            _make(stop_loss_price=Decimal("0"))

    def test_zero_target_price_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="target_price"):
            _make(target_price=Decimal("0"))

    def test_negative_option_premium_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="option_premium"):
            _make(option_premium=Decimal("-1"))

    def test_zero_option_premium_for_option_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="option_premium"):
            _make(instrument_class="OPTION", option_premium=Decimal("0"))

    def test_none_option_premium_for_option_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="option_premium"):
            _make(instrument_class="OPTION", option_premium=None)

    def test_option_premium_required_for_option(self) -> None:
        req = _make(instrument_class="OPTION", option_premium=Decimal("150"))
        assert req.option_premium == Decimal("150")

    def test_none_option_premium_valid_for_future(self) -> None:
        req = _make(
            instrument_class="FUTURE",
            option_premium=None,
            option_delta=None,
            option_vega=None,
        )
        assert req.option_premium is None

    def test_lot_size_below_one_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="lot_size"):
            _make(lot_size=0)

    def test_negative_dte_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="dte"):
            _make(dte=-1)

    def test_zero_dte_is_valid(self) -> None:
        req = _make(dte=0)
        assert req.dte == 0

    def test_zero_atr_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="atr_14"):
            _make(atr_14=0.0)

    def test_zero_risk_reward_ratio_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="risk_reward_ratio"):
            _make(risk_reward_ratio=0.0)

    def test_boundary_score_values(self) -> None:
        req = _make(adjusted_score=0.0, final_confidence=100.0)
        assert req.adjusted_score == 0.0
        assert req.final_confidence == 100.0
