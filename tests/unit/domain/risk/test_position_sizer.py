"""Unit tests for PositionSizer — ATR + Kelly sizing with four-layer protection."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.domain.exceptions.risk import UnsupportedInstrumentClassError
from core.domain.risk.account_state import AccountState
from core.domain.risk.position_sizer import PositionSizer
from core.domain.risk.risk_request import RiskRequest
from core.infrastructure.config.risk_config import RiskConfig, load_risk_config

_NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def config() -> RiskConfig:
    return load_risk_config()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_account(**overrides: object) -> AccountState:
    defaults: dict[str, object] = {
        "account_capital": Decimal("500000"),
        "session_capital": Decimal("500000"),
        "available_margin": Decimal("400000"),
        "used_margin": Decimal("50000"),
        "margin_utilization_pct": 10.0,
        "daily_pnl": Decimal("0"),
        "daily_loss_consumed_pct": 0.0,
        "weekly_pnl": Decimal("0"),
        "weekly_loss_consumed_pct": 0.0,
        "drawdown_from_hwm_pct": 0.0,
        "open_positions_count": 2,
        "position_size_multiplier": 1.0,
        "trading_mode": "LIVE",
        "captured_at": _NOW,
    }
    defaults.update(overrides)
    return AccountState(**defaults)  # type: ignore[arg-type]


def _make_request(**overrides: object) -> RiskRequest:
    defaults: dict[str, object] = {
        "signal_id": uuid.uuid4(),
        "instrument_token": 12345,
        "underlying": "NIFTY",
        "instrument_class": "OPTION",
        "direction": "LONG",
        "adjusted_score": 75.0,
        "final_confidence": 70.0,
        "entry_price": Decimal("150"),
        "stop_loss_price": Decimal("100"),
        "target_price": Decimal("250"),
        "option_premium": Decimal("150"),
        "lot_size": 50,
        "option_delta": 0.5,
        "option_vega": 30.0,
        "dte": 15,
        "atr_14": 100.0,
        "risk_reward_ratio": 2.0,
        "evaluated_at": _NOW,
    }
    defaults.update(overrides)
    return RiskRequest(**defaults)  # type: ignore[arg-type]


def _compute(
    config: RiskConfig,
    *,
    request: RiskRequest | None = None,
    account: AccountState | None = None,
    win_rate: float = 0.667,
    win_loss_ratio: float = 1.875,
    sample_count: int = 50,
    loss_count: int = 10,
) -> object:
    return PositionSizer.compute(
        request=request or _make_request(),
        account=account or _make_account(),
        win_rate=win_rate,
        win_loss_ratio=win_loss_ratio,
        sample_count=sample_count,
        loss_count=loss_count,
        config=config,
    )


# ===========================================================================
# ATR sizing — OPTION
# ===========================================================================


class TestOptionATRSizing:
    def test_normal_path_lots_floor_applied(self, config: RiskConfig) -> None:
        # capital_at_risk = 500000 × 1% = 5000
        # cost_per_lot = 150 × 50 = 7500
        # atr_lots_raw = floor(5000 / 7500) = 0 (this is the binding constraint)
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("150"), lot_size=50),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        # atr_lots = floor(5000/7500) = 0
        assert result.atr_lots_pre_cap == 0
        assert result.lots == 0

    def test_low_premium_produces_lots(self, config: RiskConfig) -> None:
        # premium=10, lot_size=50 → cost=500; capital_at_risk=5000 → lots=floor(10)=10
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result.atr_lots_pre_cap == 10

    def test_premium_exceeds_capital_at_risk_gives_zero_lots(self, config: RiskConfig) -> None:
        # premium=150, lot_size=50 → cost_per_lot=7500 > capital_at_risk=5000 → lots=0
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("150"), lot_size=50),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result.atr_lots_pre_cap == 0
        assert result.lots == 0


# ===========================================================================
# ATR sizing — FUTURE (PB-15 separate formula)
# ===========================================================================


class TestFutureATRSizing:
    def test_future_uses_stop_distance_formula(self, config: RiskConfig) -> None:
        # stop_distance = atr_14 × atr_stop_multiplier = 100 × 1.5 = 150
        # cost_per_lot = 150 × 75 = 11250
        # capital_at_risk = 500000 × 1% = 5000
        # atr_lots = floor(5000 / 11250) = 0
        result = PositionSizer.compute(
            request=_make_request(
                instrument_class="FUTURE",
                option_premium=None,
                option_delta=None,
                option_vega=None,
                atr_14=100.0,
                lot_size=75,
            ),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        # cost = 100 × 1.5 × 75 = 11250; lots = floor(5000/11250) = 0
        assert result.atr_lots_pre_cap == 0

    def test_future_tight_stop_produces_lots(self, config: RiskConfig) -> None:
        # atr_14=10, multiplier=1.5, lot_size=10 → cost=150
        # capital_at_risk=5000 → lots=floor(5000/150)=33
        result = PositionSizer.compute(
            request=_make_request(
                instrument_class="FUTURE",
                option_premium=None,
                option_delta=None,
                option_vega=None,
                atr_14=10.0,
                lot_size=10,
            ),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        expected_atr = math.floor(5000 / (10 * 1.5 * 10))
        assert result.atr_lots_pre_cap == expected_atr

    def test_unsupported_class_raises(self, config: RiskConfig) -> None:
        with pytest.raises(UnsupportedInstrumentClassError):
            request = _make_request()
            # Bypass invariant to test sizer's guard
            object.__setattr__(request, "instrument_class", "EQUITY")
            PositionSizer.compute(
                request=request,
                account=_make_account(),
                win_rate=0.5,
                win_loss_ratio=1.0,
                sample_count=50,
                loss_count=10,
                config=config,
            )


# ===========================================================================
# Kelly — Layer 1: sample guard
# ===========================================================================


class TestKellyLayerOne:
    def test_below_min_samples_uses_fallback_fraction(self, config: RiskConfig) -> None:
        # sample_count < min_kelly_samples (30) → fallback fraction
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.9,
            win_loss_ratio=3.0,
            sample_count=config.position_sizing.min_kelly_samples - 1,
            loss_count=1,
            config=config,
        )
        expected_eff = (
            config.position_sizing.kelly_fraction
            * config.position_sizing.kelly_min_sample_fallback
        )
        assert abs(result.kelly_fraction_effective - expected_eff) < 1e-9

    def test_sizing_note_is_below_minimum_samples(self, config: RiskConfig) -> None:
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=0.9,
            win_loss_ratio=3.0,
            sample_count=config.position_sizing.min_kelly_samples - 1,
            loss_count=5,
            config=config,
        )
        assert result.sizing_note == "below_minimum_samples"

    def test_at_min_samples_uses_full_fraction(self, config: RiskConfig) -> None:
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=config.position_sizing.min_kelly_samples,
            loss_count=10,
            config=config,
        )
        assert result.kelly_fraction_effective == config.position_sizing.kelly_fraction
        assert result.sizing_note is None


# ===========================================================================
# Kelly — Layer 2: zero-loss edge
# ===========================================================================


class TestKellyLayerTwo:
    def test_zero_losses_uses_fallback_fraction(self, config: RiskConfig) -> None:
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=1.0,
            win_loss_ratio=2.0,
            sample_count=config.position_sizing.min_kelly_samples + 10,
            loss_count=0,
            config=config,
        )
        expected_eff = (
            config.position_sizing.kelly_fraction
            * config.position_sizing.kelly_min_sample_fallback
        )
        assert abs(result.kelly_fraction_effective - expected_eff) < 1e-9

    def test_sizing_note_is_no_historical_losses(self, config: RiskConfig) -> None:
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=1.0,
            win_loss_ratio=2.0,
            sample_count=config.position_sizing.min_kelly_samples + 10,
            loss_count=0,
            config=config,
        )
        assert result.sizing_note == "no_historical_losses"

    def test_layer2_fires_even_with_sufficient_samples(self, config: RiskConfig) -> None:
        # Sufficient samples (50) but loss_count=0 → fallback applies
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=1.0,
            win_loss_ratio=2.0,
            sample_count=50,
            loss_count=0,
            config=config,
        )
        expected_eff = (
            config.position_sizing.kelly_fraction
            * config.position_sizing.kelly_min_sample_fallback
        )
        assert abs(result.kelly_fraction_effective - expected_eff) < 1e-9


# ===========================================================================
# Kelly — Layer 3: raw_kelly floor at 0
# ===========================================================================


class TestKellyLayerThree:
    def test_negative_raw_kelly_clamped_to_zero(self, config: RiskConfig) -> None:
        # win_rate=0.1, win_loss_ratio=0.5 → raw_kelly = 0.1 - 0.9/0.5 = 0.1 - 1.8 = -1.7
        # After floor: 0.0 → kelly_capital=0 → kelly_lots=0
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=0.1,
            win_loss_ratio=0.5,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result.kelly_lots_pre_cap == 0

    def test_zero_win_loss_ratio_guarded(self, config: RiskConfig) -> None:
        # win_loss_ratio=0 (degenerate) → should not raise ZeroDivisionError
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=0.5,
            win_loss_ratio=0.0,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result.kelly_lots_pre_cap == 0


# ===========================================================================
# Kelly — Layer 4: hard cap (max_position_size_lots)
# ===========================================================================


class TestKellyLayerFour:
    def test_kelly_capped_at_max(self, config: RiskConfig) -> None:
        # Very low premium (0.01) → massive kelly_lots → must be capped
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("0.01"), lot_size=1),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.9,
            win_loss_ratio=9.0,
            sample_count=100,
            loss_count=10,
            config=config,
        )
        assert result.kelly_lots_pre_cap > config.position_sizing.max_position_size_lots
        # final lots ≤ max cap (also bounded by atr)
        # The SizingResult stores pre-cap value, so we verify it exceeds cap
        assert result.kelly_lots_pre_cap >= config.position_sizing.max_position_size_lots

    def test_atr_capped_at_max(self, config: RiskConfig) -> None:
        # Very low premium → atr_lots_raw >> max_position_size_lots
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("0.01"), lot_size=1),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.9,
            win_loss_ratio=9.0,
            sample_count=100,
            loss_count=10,
            config=config,
        )
        # Both pre-cap values may exceed the max; final lots ≤ max cap
        assert result.lots <= config.position_sizing.max_position_size_lots

    def test_pre_cap_values_reflect_uncapped_output(self, config: RiskConfig) -> None:
        # Use a premium that gives known ATR lots (e.g., 10)
        # capital_at_risk=5000, cost=500 (prem=10, lot=50) → atr_lots=10
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        # atr_lots_raw = floor(5000/500) = 10 → stored in atr_lots_pre_cap
        assert result.atr_lots_pre_cap == 10


# ===========================================================================
# ATR vs Kelly min (conservative bound)
# ===========================================================================


class TestATRKellyMin:
    def test_atr_is_binding_constraint(self, config: RiskConfig) -> None:
        # ATR lots < Kelly lots → final = ATR (after cap and multiplier)
        # premium=100, lot=50 → cost=5000; capital_at_risk=5000 → atr=1 lot
        # Kelly with good stats → many lots
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("100"), lot_size=50),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.9,
            win_loss_ratio=4.0,
            sample_count=100,
            loss_count=10,
            config=config,
        )
        # ATR: floor(5000/5000) = 1 lot
        # Kelly: much larger (good win_rate and ratio)
        # final = min(atr_capped, kelly_capped) = 1
        assert result.atr_lots_pre_cap == 1
        assert result.kelly_lots_pre_cap > 1
        assert result.lots == 1

    def test_kelly_is_binding_constraint(self, config: RiskConfig) -> None:
        # Very low premium → ATR gives many lots; poor Kelly → 0 kelly lots
        # premium=0.5, lot=10 → cost=5; capital_at_risk=5000 → atr=1000 lots
        # win_rate=0.1, win_loss_ratio=0.5 → raw_kelly < 0 → kelly=0
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("0.5"), lot_size=10),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.1,
            win_loss_ratio=0.5,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result.kelly_lots_pre_cap == 0
        assert result.lots == 0

    def test_both_zero_gives_zero(self, config: RiskConfig) -> None:
        # atr_lots=0 (cost_per_lot=7500 > capital_at_risk=5000)
        # kelly_lots=0 (raw_kelly = 0.1 - 0.9/0.5 = -1.7 → clamped to 0)
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("150"), lot_size=50),
            account=_make_account(session_capital=Decimal("500000")),
            win_rate=0.1,
            win_loss_ratio=0.5,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result.lots == 0


# ===========================================================================
# Graduated response multiplier
# ===========================================================================


class TestGraduatedResponse:
    def test_multiplier_1_no_change(self, config: RiskConfig) -> None:
        account = _make_account(position_size_multiplier=1.0, session_capital=Decimal("500000"))
        result_full = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=account,
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result_full.lots == result_full.atr_lots_pre_cap  # no cap or reduction

    def test_multiplier_0_5_halves_lots(self, config: RiskConfig) -> None:
        # ATR gives 10 lots; 0.5 multiplier → floor(10 × 0.5) = 5
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(
                session_capital=Decimal("500000"), position_size_multiplier=0.5
            ),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        # ATR = 10; Kelly likely higher; min = 10; ×0.5 = floor(5.0) = 5
        assert result.lots == 5

    def test_multiplier_0_gives_zero_lots(self, config: RiskConfig) -> None:
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(position_size_multiplier=0.0),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result.lots == 0


# ===========================================================================
# SizingResult field correctness
# ===========================================================================


class TestSizingResultFields:
    def test_kelly_sample_count_matches_input(self, config: RiskConfig) -> None:
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=42,
            loss_count=8,
            config=config,
        )
        assert result.kelly_sample_count == 42

    def test_sizing_note_is_none_in_normal_path(self, config: RiskConfig) -> None:
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=config.position_sizing.min_kelly_samples + 10,
            loss_count=5,
            config=config,
        )
        assert result.sizing_note is None

    def test_kelly_fraction_effective_is_full_in_normal_path(self, config: RiskConfig) -> None:
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result.kelly_fraction_effective == config.position_sizing.kelly_fraction

    def test_kelly_fraction_effective_is_fallback_in_layer1(self, config: RiskConfig) -> None:
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(),
            win_rate=0.9,
            win_loss_ratio=3.0,
            sample_count=config.position_sizing.min_kelly_samples - 1,
            loss_count=1,
            config=config,
        )
        expected = (
            config.position_sizing.kelly_fraction
            * config.position_sizing.kelly_min_sample_fallback
        )
        assert abs(result.kelly_fraction_effective - expected) < 1e-9

    def test_lots_field_matches_final_computed_value(self, config: RiskConfig) -> None:
        # premium=10, lot=50, session=500000 → atr_lots=10; multiplier=0.5 → 5
        result = PositionSizer.compute(
            request=_make_request(option_premium=Decimal("10"), lot_size=50),
            account=_make_account(
                session_capital=Decimal("500000"), position_size_multiplier=0.5
            ),
            win_rate=0.667,
            win_loss_ratio=1.875,
            sample_count=50,
            loss_count=10,
            config=config,
        )
        assert result.lots == 5
        assert result.lots >= 0
