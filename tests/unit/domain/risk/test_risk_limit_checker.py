"""Unit tests for all 15 pure pre-trade check functions in RiskLimitChecker."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.domain.risk.account_state import AccountState
from core.domain.risk.kill_switch_state import KillSwitchState
from core.domain.risk.portfolio_state import PortfolioState
from core.domain.risk.risk_decision import SizingResult
from core.domain.risk.risk_limit_checker import (
    check_capital_concentration,
    check_correlation,
    check_daily_loss,
    check_drawdown,
    check_kill_switch,
    check_margin,
    check_net_delta,
    check_open_positions,
    check_order_rate,
    check_position_size,
    check_risk_reward,
    check_symbol_concentration,
    check_theta_decay,
    check_vega_exposure,
    check_weekly_loss,
)
from core.domain.risk.risk_request import RiskRequest
from core.infrastructure.config.risk_config import RiskConfig, load_risk_config

_NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def config() -> RiskConfig:
    return load_risk_config()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_kill_switch(**overrides: object) -> KillSwitchState:
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
        "open_positions_count": 0,
        "position_size_multiplier": 1.0,
        "trading_mode": "LIVE",
        "captured_at": _NOW,
    }
    defaults.update(overrides)
    return AccountState(**defaults)  # type: ignore[arg-type]


def _make_portfolio(**overrides: object) -> PortfolioState:
    defaults: dict[str, object] = {
        "open_positions_count": 0,
        "positions_per_underlying": {},
        "capital_per_underlying_pct": {},
        "net_delta": 0.0,
        "net_vega": 0.0,
        "net_theta_daily": 0.0,
        "orders_last_minute": 0,
        "orders_today": 0,
        "captured_at": _NOW,
    }
    defaults.update(overrides)
    return PortfolioState(**defaults)  # type: ignore[arg-type]


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


def _make_sizing(**overrides: object) -> SizingResult:
    defaults: dict[str, object] = {
        "lots": 2,
        "atr_lots_pre_cap": 2,
        "kelly_lots_pre_cap": 5,
        "kelly_fraction_effective": 0.25,
        "kelly_sample_count": 50,
        "sizing_note": None,
    }
    defaults.update(overrides)
    return SizingResult(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# Check 1 — Kill Switch
# ===========================================================================


class TestCheckKillSwitch:
    def test_inactive_passes(self, config: RiskConfig) -> None:
        state = _make_kill_switch(is_active=False)
        result = check_kill_switch(state, config)
        assert result.passed is True

    def test_active_fails(self, config: RiskConfig) -> None:
        state = _make_kill_switch(
            is_active=True,
            activated_by="operator",
            activation_reason="manual stop",
        )
        result = check_kill_switch(state, config)
        assert result.passed is False

    def test_check_name(self, config: RiskConfig) -> None:
        result = check_kill_switch(_make_kill_switch(), config)
        assert result.check_name == "KillSwitch"

    def test_current_value_when_active(self, config: RiskConfig) -> None:
        state = _make_kill_switch(is_active=True, activated_by="operator")
        result = check_kill_switch(state, config)
        assert result.current_value == 1.0

    def test_current_value_when_inactive(self, config: RiskConfig) -> None:
        result = check_kill_switch(_make_kill_switch(is_active=False), config)
        assert result.current_value == 0.0

    def test_is_not_warning(self, config: RiskConfig) -> None:
        result = check_kill_switch(_make_kill_switch(is_active=True, activated_by="system"), config)
        assert result.is_warning is False


# ===========================================================================
# Check 2 — Daily Loss
# ===========================================================================


class TestCheckDailyLoss:
    def test_no_loss_passes(self, config: RiskConfig) -> None:
        account = _make_account(daily_pnl=Decimal("0"))
        assert check_daily_loss(account, config).passed is True

    def test_positive_pnl_passes(self, config: RiskConfig) -> None:
        account = _make_account(daily_pnl=Decimal("5000"))
        assert check_daily_loss(account, config).passed is True

    def test_loss_below_limit_passes(self, config: RiskConfig) -> None:
        session_cap = Decimal("500000")
        # 1% loss — below 2% limit
        loss = session_cap * Decimal("1") / Decimal("100")
        account = _make_account(session_capital=session_cap, daily_pnl=-loss)
        assert check_daily_loss(account, config).passed is True

    def test_loss_at_limit_fails(self, config: RiskConfig) -> None:
        session_cap = Decimal("500000")
        # Exactly at daily_loss.limit_pct
        loss = session_cap * Decimal(str(config.daily_loss.limit_pct)) / Decimal("100")
        account = _make_account(session_capital=session_cap, daily_pnl=-loss)
        result = check_daily_loss(account, config)
        assert result.passed is False

    def test_loss_above_limit_fails(self, config: RiskConfig) -> None:
        session_cap = Decimal("500000")
        # 3% loss — above 2% limit
        loss = session_cap * Decimal("3") / Decimal("100")
        account = _make_account(session_capital=session_cap, daily_pnl=-loss)
        assert check_daily_loss(account, config).passed is False

    def test_current_value_populated(self, config: RiskConfig) -> None:
        session_cap = Decimal("500000")
        loss = session_cap * Decimal("1") / Decimal("100")
        account = _make_account(session_capital=session_cap, daily_pnl=-loss)
        result = check_daily_loss(account, config)
        assert abs(result.current_value - 1.0) < 0.001  # ~1%

    def test_abs_limit_fires_with_large_capital(self, config: RiskConfig) -> None:
        # 1M capital: 1.5% loss = 15K < 2% pct threshold, but 15K > 10K abs limit
        account = _make_account(
            session_capital=Decimal("1000000"),
            daily_pnl=Decimal("-15000"),
            daily_loss_consumed_pct=150.0,
        )
        result = check_daily_loss(account, config)
        assert result.passed is False
        assert result.current_value == 150.0
        assert result.limit_value == 100.0

    def test_abs_limit_at_100_pct_fails(self, config: RiskConfig) -> None:
        account = _make_account(daily_loss_consumed_pct=100.0)
        assert check_daily_loss(account, config).passed is False

    def test_abs_limit_below_100_passes_when_pct_ok(self, config: RiskConfig) -> None:
        account = _make_account(
            session_capital=Decimal("500000"),
            daily_pnl=Decimal("-4500"),
            daily_loss_consumed_pct=45.0,
        )
        assert check_daily_loss(account, config).passed is True

    def test_current_value_is_consumed_pct_when_abs_binds(self, config: RiskConfig) -> None:
        account = _make_account(daily_loss_consumed_pct=120.0)
        result = check_daily_loss(account, config)
        assert result.passed is False
        assert result.current_value == 120.0
        assert result.limit_value == 100.0


# ===========================================================================
# Check 3 — Weekly Loss
# ===========================================================================


class TestCheckWeeklyLoss:
    def test_no_loss_passes(self, config: RiskConfig) -> None:
        account = _make_account(weekly_pnl=Decimal("0"))
        assert check_weekly_loss(account, config).passed is True

    def test_loss_below_limit_passes(self, config: RiskConfig) -> None:
        session_cap = Decimal("500000")
        loss = session_cap * Decimal("2") / Decimal("100")  # 2% < 5% limit
        account = _make_account(session_capital=session_cap, weekly_pnl=-loss)
        assert check_weekly_loss(account, config).passed is True

    def test_loss_at_limit_fails(self, config: RiskConfig) -> None:
        session_cap = Decimal("500000")
        loss = session_cap * Decimal(str(config.weekly_loss.limit_pct)) / Decimal("100")
        account = _make_account(session_capital=session_cap, weekly_pnl=-loss)
        assert check_weekly_loss(account, config).passed is False

    def test_loss_above_limit_fails(self, config: RiskConfig) -> None:
        session_cap = Decimal("500000")
        loss = session_cap * Decimal("6") / Decimal("100")  # 6% > 5% limit
        account = _make_account(session_capital=session_cap, weekly_pnl=-loss)
        assert check_weekly_loss(account, config).passed is False

    def test_check_name(self, config: RiskConfig) -> None:
        assert check_weekly_loss(_make_account(), config).check_name == "WeeklyLoss"

    def test_weekly_abs_limit_fires_with_large_capital(self, config: RiskConfig) -> None:
        # 1M capital: 3% loss = 30K < 5% pct threshold, but 30K > 25K abs limit
        account = _make_account(
            session_capital=Decimal("1000000"),
            weekly_pnl=Decimal("-30000"),
            weekly_loss_consumed_pct=120.0,
        )
        result = check_weekly_loss(account, config)
        assert result.passed is False
        assert result.current_value == 120.0
        assert result.limit_value == 100.0

    def test_weekly_abs_limit_at_100_pct_fails(self, config: RiskConfig) -> None:
        account = _make_account(weekly_loss_consumed_pct=100.0)
        assert check_weekly_loss(account, config).passed is False


# ===========================================================================
# Check 4 — Drawdown
# ===========================================================================


class TestCheckDrawdown:
    def test_zero_drawdown_passes(self, config: RiskConfig) -> None:
        account = _make_account(drawdown_from_hwm_pct=0.0)
        assert check_drawdown(account, config).passed is True

    def test_drawdown_below_limit_passes(self, config: RiskConfig) -> None:
        account = _make_account(drawdown_from_hwm_pct=config.drawdown.max_drawdown_pct - 0.1)
        assert check_drawdown(account, config).passed is True

    def test_drawdown_at_limit_fails(self, config: RiskConfig) -> None:
        account = _make_account(drawdown_from_hwm_pct=config.drawdown.max_drawdown_pct)
        assert check_drawdown(account, config).passed is False

    def test_drawdown_above_limit_fails(self, config: RiskConfig) -> None:
        account = _make_account(drawdown_from_hwm_pct=config.drawdown.max_drawdown_pct + 1.0)
        assert check_drawdown(account, config).passed is False

    def test_current_value_matches_input(self, config: RiskConfig) -> None:
        account = _make_account(drawdown_from_hwm_pct=5.5)
        result = check_drawdown(account, config)
        assert result.current_value == 5.5


# ===========================================================================
# Check 5 — Open Positions
# ===========================================================================


class TestCheckOpenPositions:
    def test_zero_positions_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(open_positions_count=0)
        assert check_open_positions(portfolio, config).passed is True

    def test_below_max_passes(self, config: RiskConfig) -> None:
        count = config.position_limits.max_open_positions - 2
        portfolio = _make_portfolio(open_positions_count=count)
        assert check_open_positions(portfolio, config).passed is True

    def test_max_minus_one_passes(self, config: RiskConfig) -> None:
        count = config.position_limits.max_open_positions - 1
        portfolio = _make_portfolio(open_positions_count=count)
        assert check_open_positions(portfolio, config).passed is True

    def test_at_max_fails(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(open_positions_count=config.position_limits.max_open_positions)
        assert check_open_positions(portfolio, config).passed is False

    def test_above_max_fails(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(
            open_positions_count=config.position_limits.max_open_positions + 5
        )
        assert check_open_positions(portfolio, config).passed is False


# ===========================================================================
# Check 6 — Symbol Concentration
# ===========================================================================


class TestCheckSymbolConcentration:
    def test_no_existing_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(positions_per_underlying={})
        request = _make_request(underlying="NIFTY")
        assert check_symbol_concentration(portfolio, request, config).passed is True

    def test_underlying_not_in_dict_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(positions_per_underlying={"BANKNIFTY": 2})
        request = _make_request(underlying="NIFTY")
        assert check_symbol_concentration(portfolio, request, config).passed is True

    def test_below_limit_passes(self, config: RiskConfig) -> None:
        limit = config.position_limits.max_positions_per_underlying
        portfolio = _make_portfolio(positions_per_underlying={"NIFTY": limit - 1})
        request = _make_request(underlying="NIFTY")
        assert check_symbol_concentration(portfolio, request, config).passed is True

    def test_at_limit_fails(self, config: RiskConfig) -> None:
        limit = config.position_limits.max_positions_per_underlying
        portfolio = _make_portfolio(positions_per_underlying={"NIFTY": limit})
        request = _make_request(underlying="NIFTY")
        assert check_symbol_concentration(portfolio, request, config).passed is False

    def test_check_name(self, config: RiskConfig) -> None:
        result = check_symbol_concentration(_make_portfolio(), _make_request(), config)
        assert result.check_name == "SymbolConcentration"


# ===========================================================================
# Check 7 — Capital Concentration
# ===========================================================================


class TestCheckCapitalConcentration:
    def test_no_existing_concentration_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(capital_per_underlying_pct={})
        request = _make_request(underlying="NIFTY", option_premium=Decimal("50"))
        account = _make_account()
        assert check_capital_concentration(portfolio, request, account, config).passed is True

    def test_below_conc_limit_passes(self, config: RiskConfig) -> None:
        limit = config.position_limits.max_capital_per_underlying_pct
        portfolio = _make_portfolio(capital_per_underlying_pct={"NIFTY": limit - 1.0})
        request = _make_request(underlying="NIFTY", option_premium=Decimal("50"))
        account = _make_account()
        assert check_capital_concentration(portfolio, request, account, config).passed is True

    def test_at_conc_limit_fails(self, config: RiskConfig) -> None:
        limit = config.position_limits.max_capital_per_underlying_pct
        portfolio = _make_portfolio(capital_per_underlying_pct={"NIFTY": limit})
        request = _make_request(underlying="NIFTY")
        account = _make_account()
        assert check_capital_concentration(portfolio, request, account, config).passed is False

    def test_notional_above_limit_fails(self, config: RiskConfig) -> None:
        # Option premium × lot_size / session_capital > max_notional_per_trade_pct
        # With session_cap=500000, limit=10%: max_lot_cost = 50000
        # premium=1100, lot_size=50 → cost = 55000 → 11% > 10% → FAIL
        portfolio = _make_portfolio()
        request = _make_request(
            underlying="NIFTY",
            option_premium=Decimal("1100"),
            lot_size=50,
        )
        account = _make_account(session_capital=Decimal("500000"))
        result = check_capital_concentration(portfolio, request, account, config)
        assert result.passed is False

    def test_notional_at_limit_passes(self, config: RiskConfig) -> None:
        # premium=1000, lot_size=50 → cost=50000 → 10% == limit → should pass (<=)
        portfolio = _make_portfolio()
        request = _make_request(
            underlying="NIFTY",
            option_premium=Decimal("1000"),
            lot_size=50,
        )
        account = _make_account(session_capital=Decimal("500000"))
        result = check_capital_concentration(portfolio, request, account, config)
        assert result.passed is True

    def test_future_uses_atr_stop_notional(self, config: RiskConfig) -> None:
        # FUTURE: lot_risk = atr_14 × atr_stop_multiplier × lot_size
        # atr_14=100, multiplier=1.5, lot_size=75 → risk=11250 → 2.25% of 500000 → passes
        portfolio = _make_portfolio()
        request = _make_request(
            underlying="NIFTY",
            instrument_class="FUTURE",
            option_premium=None,
            option_delta=None,
            option_vega=None,
            atr_14=100.0,
            lot_size=75,
        )
        account = _make_account(session_capital=Decimal("500000"))
        result = check_capital_concentration(portfolio, request, account, config)
        assert result.passed is True

    def test_projection_pushes_above_limit_fails(self, config: RiskConfig) -> None:
        # existing=19%, new trade=2% → projected=21% > 20% limit → FAIL
        # option_premium=200, lot_size=50 → lot_risk=10000 → 10000/500000*100=2%
        limit = config.position_limits.max_capital_per_underlying_pct
        portfolio = _make_portfolio(capital_per_underlying_pct={"NIFTY": limit - 1.0})
        request = _make_request(
            underlying="NIFTY", option_premium=Decimal("200"), lot_size=50
        )
        account = _make_account()
        result = check_capital_concentration(portfolio, request, account, config)
        assert result.passed is False

    def test_projection_stays_below_limit_passes(self, config: RiskConfig) -> None:
        # existing=17%, new trade=2% → projected=19% < 20% limit → PASS
        limit = config.position_limits.max_capital_per_underlying_pct
        portfolio = _make_portfolio(capital_per_underlying_pct={"NIFTY": limit - 3.0})
        request = _make_request(
            underlying="NIFTY", option_premium=Decimal("200"), lot_size=50
        )
        account = _make_account()
        result = check_capital_concentration(portfolio, request, account, config)
        assert result.passed is True

    def test_current_value_is_projected_not_existing(self, config: RiskConfig) -> None:
        # existing=10%, trade=5% (500*50=25000, 25000/500000*100=5%) → projected=15%
        portfolio = _make_portfolio(capital_per_underlying_pct={"NIFTY": 10.0})
        request = _make_request(
            underlying="NIFTY", option_premium=Decimal("500"), lot_size=50
        )
        account = _make_account()
        result = check_capital_concentration(portfolio, request, account, config)
        assert result.passed is True
        assert abs(result.current_value - 15.0) < 0.01  # projected, not existing (10.0)

    def test_failure_message_shows_existing_and_new_pct(self, config: RiskConfig) -> None:
        # existing=19%, new trade=2% → FAIL; message must name both components
        limit = config.position_limits.max_capital_per_underlying_pct
        portfolio = _make_portfolio(capital_per_underlying_pct={"NIFTY": limit - 1.0})
        request = _make_request(
            underlying="NIFTY", option_premium=Decimal("200"), lot_size=50
        )
        account = _make_account()
        result = check_capital_concentration(portfolio, request, account, config)
        assert result.passed is False
        assert "existing" in result.message


# ===========================================================================
# Check 8 — Net Delta
# ===========================================================================


class TestCheckNetDelta:
    def test_zero_portfolio_delta_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(net_delta=0.0)
        request = _make_request(option_delta=0.1, lot_size=50, direction="LONG")
        assert check_net_delta(portfolio, request, config).passed is True

    def test_projected_below_limit_passes(self, config: RiskConfig) -> None:
        # existing=2000, new LONG call delta=0.5×50=25 → projected=2025 < 2500
        portfolio = _make_portfolio(net_delta=2000.0)
        request = _make_request(option_delta=0.5, lot_size=50, direction="LONG")
        assert check_net_delta(portfolio, request, config).passed is True

    def test_projected_at_limit_fails(self, config: RiskConfig) -> None:
        limit = config.greeks.max_net_delta
        # Position net_delta so that adding 1 lot hits the limit
        # option_delta=0.5, lot_size=50 → contribution=25
        # existing = limit - 25 + 25 = limit → projected = limit
        portfolio = _make_portfolio(net_delta=limit - 25.0)
        request = _make_request(option_delta=0.5, lot_size=50, direction="LONG")
        result = check_net_delta(portfolio, request, config)
        assert result.passed is False

    def test_negative_delta_portfolio_abs_applied(self, config: RiskConfig) -> None:
        # Large short delta: -(limit-25). Adding LONG put (delta=-0.5) pushes further negative.
        limit = config.greeks.max_net_delta
        portfolio = _make_portfolio(net_delta=-(limit - 25.0))
        # LONG PUT: delta=-0.5, direction_sign=+1 → contribution=-25 → projected=-(limit)
        request = _make_request(option_delta=-0.5, lot_size=50, direction="LONG")
        result = check_net_delta(portfolio, request, config)
        # |projected| = limit → fails
        assert result.passed is False

    def test_long_call_adds_delta(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(net_delta=100.0)
        request = _make_request(option_delta=0.5, lot_size=50, direction="LONG")
        result = check_net_delta(portfolio, request, config)
        # Projected = 100 + 0.5×50×1 = 125 — well below limit
        assert result.passed is True
        assert abs(result.current_value - 125.0) < 0.01

    def test_short_call_subtracts_delta(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(net_delta=100.0)
        request = _make_request(option_delta=0.5, lot_size=50, direction="SHORT")
        result = check_net_delta(portfolio, request, config)
        # Projected = 100 + 0.5×50×(-1) = 75
        assert result.passed is True
        assert abs(result.current_value - 75.0) < 0.01

    def test_long_put_subtracts_delta(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(net_delta=100.0)
        # LONG PUT: delta=-0.5, direction_sign=+1 → contribution=-25 → projected=75
        request = _make_request(option_delta=-0.5, lot_size=50, direction="LONG")
        result = check_net_delta(portfolio, request, config)
        assert result.passed is True
        assert abs(result.current_value - 75.0) < 0.01

    def test_future_uses_full_lot_size(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(net_delta=0.0)
        request = _make_request(
            instrument_class="FUTURE",
            option_delta=None,
            option_vega=None,
            option_premium=None,
            lot_size=75,
            direction="LONG",
        )
        result = check_net_delta(portfolio, request, config)
        # FUTURE LONG: contribution = 1.0 × 75 = 75
        assert abs(result.current_value - 75.0) < 0.01


# ===========================================================================
# Check 9 — Correlation
# ===========================================================================


class TestCheckCorrelation:
    def test_empty_portfolio_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(positions_per_underlying={})
        request = _make_request(underlying="NIFTY", option_delta=0.5, lot_size=50)
        result = check_correlation(portfolio, request, {}, config)
        assert result.passed is True

    def test_same_underlying_rho_1(self, config: RiskConfig) -> None:
        # NIFTY in portfolio, request also NIFTY → ρ=1.0 (same underlying)
        portfolio = _make_portfolio(
            open_positions_count=1,
            positions_per_underlying={"NIFTY": 1},
            net_delta=100.0,
        )
        request = _make_request(underlying="NIFTY", option_delta=0.5, lot_size=50)
        result = check_correlation(portfolio, request, {}, config)
        # corr_adj=100×1.0=100; new_delta_signed=0.5×50×1=25; effective=125 → passes
        assert result.passed is True
        assert abs(result.current_value - 125.0) < 0.01

    def test_empty_matrix_uses_conservative_default(self, config: RiskConfig) -> None:
        # Empty matrix → ρ=1.0 (conservative default); risk-increasing same-direction FAILS
        limit = config.greeks.max_net_delta
        portfolio = _make_portfolio(
            open_positions_count=1,
            positions_per_underlying={"BANKNIFTY": 1},
            net_delta=limit - 20.0,  # positive portfolio, just below limit
        )
        # LONG CALL adds positive delta: corr_adj=(limit-20)×1.0; eff=(limit-20)+25=limit+5 → FAIL
        request = _make_request(underlying="NIFTY", option_delta=0.5, lot_size=50)
        result = check_correlation(portfolio, request, {}, config)
        assert result.passed is False

    def test_low_correlation_applies_discount_to_portfolio_delta(
        self, config: RiskConfig
    ) -> None:
        # With ρ=0.2: corr_adj=-(limit-20)×0.2=-496; effective=-496+25=-471 → PASS
        limit = config.greeks.max_net_delta
        portfolio = _make_portfolio(
            open_positions_count=1,
            positions_per_underlying={"BANKNIFTY": 1},
            net_delta=-(limit - 20.0),
        )
        request = _make_request(underlying="FINNIFTY", option_delta=0.5, lot_size=50)
        matrix = {"FINNIFTY": {"BANKNIFTY": 0.2}}
        result = check_correlation(portfolio, request, matrix, config)
        assert result.passed is True

    def test_missing_pair_uses_conservative_default(self, config: RiskConfig) -> None:
        # Matrix doesn't have the NIFTY/BANKNIFTY entry → ρ=1.0
        portfolio = _make_portfolio(
            open_positions_count=1,
            positions_per_underlying={"BANKNIFTY": 1},
            net_delta=100.0,
        )
        request = _make_request(underlying="NIFTY", option_delta=0.5, lot_size=50)
        result = check_correlation(portfolio, request, {}, config)
        # ρ defaults to 1.0: corr_adj=100; new_delta_signed=25; effective=125 → passes
        assert result.passed is True
        assert abs(result.current_value - 125.0) < 0.01

    def test_corr_allows_risk_reducing_opposing_direction(self, config: RiskConfig) -> None:
        # SHORT portfolio near limit; LONG CALL reduces risk → PASS (H1 fix)
        limit = config.greeks.max_net_delta
        portfolio = _make_portfolio(
            open_positions_count=1,
            positions_per_underlying={"NIFTY": 1},
            net_delta=-(limit - 20.0),  # just inside limit, negative direction
        )
        # LONG CALL: new_delta_signed=+25; corr_adj=-(limit-20)×1.0; eff=-(2455) → |2455|<2500
        request = _make_request(underlying="NIFTY", option_delta=0.5, lot_size=50)
        result = check_correlation(portfolio, request, {}, config)
        assert result.passed is True

    def test_corr_blocks_risk_increasing_near_limit(self, config: RiskConfig) -> None:
        # LONG portfolio near limit; additional LONG CALL pushes over → FAIL
        limit = config.greeks.max_net_delta
        portfolio = _make_portfolio(
            open_positions_count=1,
            positions_per_underlying={"NIFTY": 1},
            net_delta=limit - 20.0,  # positive, just inside limit
        )
        # LONG CALL: new_delta_signed=+25; effective=(limit-20)+25=limit+5 → FAIL
        request = _make_request(underlying="NIFTY", option_delta=0.5, lot_size=50)
        result = check_correlation(portfolio, request, {}, config)
        assert result.passed is False

    def test_corr_cross_instrument_rho_discount_reduces_exposure(
        self, config: RiskConfig
    ) -> None:
        # net_delta=+2480 (BANKNIFTY). New NIFTY LONG at rho=0.85:
        # corr_adj=2480×0.85=2108; eff=2108+25=2133 < 2500 → PASS
        portfolio = _make_portfolio(
            open_positions_count=1,
            positions_per_underlying={"BANKNIFTY": 1},
            net_delta=2480.0,
        )
        request = _make_request(underlying="NIFTY", option_delta=0.5, lot_size=50)
        matrix = {"NIFTY": {"BANKNIFTY": 0.85}}
        result = check_correlation(portfolio, request, matrix, config)
        assert result.passed is True
        assert abs(result.current_value - 2133.0) < 0.5


# ===========================================================================
# Check 10 — Margin
# ===========================================================================


class TestCheckMargin:
    def test_sufficient_margin_passes(self, config: RiskConfig) -> None:
        account = _make_account(
            available_margin=Decimal("100000"),
            used_margin=Decimal("50000"),
            account_capital=Decimal("500000"),
        )
        result = check_margin(account, Decimal("50000"), config)
        assert result.passed is True

    def test_insufficient_margin_fails(self, config: RiskConfig) -> None:
        account = _make_account(available_margin=Decimal("1000"))
        result = check_margin(account, Decimal("50000"), config)
        assert result.passed is False

    def test_utilization_at_limit_fails(self, config: RiskConfig) -> None:
        # used=350000, account_cap=500000. After adding 50000: util=(400000/500000)*100=80%
        # utilization_limit_pct = 80% → post_util == limit → passes (<=)
        # To FAIL: make post_util > 80%
        account = _make_account(
            available_margin=Decimal("200000"),
            used_margin=Decimal("350000"),
            account_capital=Decimal("500000"),
        )
        # margin_required=51000 → (350000+51000)/500000*100 = 80.2% > 80% → FAIL
        result = check_margin(account, Decimal("51000"), config)
        assert result.passed is False

    def test_zero_account_capital_treated_as_100_pct(self, config: RiskConfig) -> None:
        account = _make_account(
            account_capital=Decimal("0"),
            session_capital=Decimal("0"),
            available_margin=Decimal("0"),
            used_margin=Decimal("0"),
        )
        result = check_margin(account, Decimal("1"), config)
        # available (0) < required (1) → fails on sufficiency
        assert result.passed is False

    def test_check_name(self, config: RiskConfig) -> None:
        account = _make_account()
        result = check_margin(account, Decimal("1000"), config)
        assert result.check_name == "Margin"


# ===========================================================================
# Check 11 — Risk/Reward
# ===========================================================================


class TestCheckRiskReward:
    def test_at_min_ratio_passes(self, config: RiskConfig) -> None:
        request = _make_request(risk_reward_ratio=config.risk_reward.min_ratio)
        assert check_risk_reward(request, config).passed is True

    def test_above_min_ratio_passes(self, config: RiskConfig) -> None:
        request = _make_request(risk_reward_ratio=config.risk_reward.min_ratio + 0.5)
        assert check_risk_reward(request, config).passed is True

    def test_below_min_ratio_fails(self, config: RiskConfig) -> None:
        request = _make_request(risk_reward_ratio=config.risk_reward.min_ratio - 0.1)
        assert check_risk_reward(request, config).passed is False

    def test_at_max_ratio_passes(self, config: RiskConfig) -> None:
        request = _make_request(risk_reward_ratio=config.risk_reward.max_ratio)
        assert check_risk_reward(request, config).passed is True

    def test_above_max_ratio_fails(self, config: RiskConfig) -> None:
        request = _make_request(risk_reward_ratio=config.risk_reward.max_ratio + 0.1)
        assert check_risk_reward(request, config).passed is False

    def test_check_name(self, config: RiskConfig) -> None:
        assert check_risk_reward(_make_request(), config).check_name == "RiskReward"


# ===========================================================================
# Check 12 — Position Size
# ===========================================================================


class TestCheckPositionSize:
    def test_zero_lots_fails(self) -> None:
        sizing = _make_sizing(lots=0)
        result = check_position_size(sizing)
        assert result.passed is False

    def test_one_lot_passes(self) -> None:
        sizing = _make_sizing(lots=1)
        assert check_position_size(sizing).passed is True

    def test_many_lots_passes(self) -> None:
        sizing = _make_sizing(lots=50)
        assert check_position_size(sizing).passed is True

    def test_is_not_warning(self) -> None:
        result = check_position_size(_make_sizing(lots=0))
        assert result.is_warning is False

    def test_check_name(self) -> None:
        assert check_position_size(_make_sizing()).check_name == "PositionSize"

    def test_sizing_note_appears_in_message(self) -> None:
        sizing = _make_sizing(lots=0, sizing_note="below_minimum_samples")
        result = check_position_size(sizing)
        assert "below_minimum_samples" in result.message


# ===========================================================================
# Check 13 — Order Rate
# ===========================================================================


class TestCheckOrderRate:
    def test_zero_orders_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(orders_last_minute=0)
        assert check_order_rate(portfolio, config).passed is True

    def test_below_limit_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(orders_last_minute=config.order_rate.max_orders_per_minute - 2)
        assert check_order_rate(portfolio, config).passed is True

    def test_max_minus_one_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(orders_last_minute=config.order_rate.max_orders_per_minute - 1)
        assert check_order_rate(portfolio, config).passed is True

    def test_at_limit_fails(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(orders_last_minute=config.order_rate.max_orders_per_minute)
        assert check_order_rate(portfolio, config).passed is False

    def test_above_limit_fails(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(
            orders_last_minute=config.order_rate.max_orders_per_minute + 3
        )
        assert check_order_rate(portfolio, config).passed is False

    def test_daily_limit_at_cap_fails(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(orders_today=config.order_rate.max_orders_per_day)
        assert check_order_rate(portfolio, config).passed is False

    def test_daily_limit_above_cap_fails(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(orders_today=config.order_rate.max_orders_per_day + 5)
        assert check_order_rate(portfolio, config).passed is False

    def test_daily_limit_below_cap_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(orders_today=config.order_rate.max_orders_per_day - 1)
        assert check_order_rate(portfolio, config).passed is True

    def test_rate_ok_daily_limit_exceeded_fails(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(
            orders_last_minute=0,
            orders_today=config.order_rate.max_orders_per_day,
        )
        result = check_order_rate(portfolio, config)
        assert result.passed is False
        assert result.current_value == float(config.order_rate.max_orders_per_day)
        assert result.limit_value == float(config.order_rate.max_orders_per_day)

    def test_rate_exceeded_daily_ok_fails(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(
            orders_last_minute=config.order_rate.max_orders_per_minute,
            orders_today=0,
        )
        assert check_order_rate(portfolio, config).passed is False

    def test_both_within_limits_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(orders_last_minute=0, orders_today=0)
        assert check_order_rate(portfolio, config).passed is True


# ===========================================================================
# Check 14 — Theta Decay (warn-only)
# ===========================================================================


class TestCheckThetaDecay:
    def test_zero_theta_is_warning_and_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(net_theta_daily=0.0)
        result = check_theta_decay(portfolio, config)
        assert result.passed is True
        assert result.is_warning is True

    def test_theta_below_threshold_is_warning_and_passes(self, config: RiskConfig) -> None:
        max_abs = (
            config.capital.total_capital * config.greeks.max_theta_daily_decay_pct / 100.0
        )
        portfolio = _make_portfolio(net_theta_daily=-(max_abs - 1.0))
        result = check_theta_decay(portfolio, config)
        assert result.passed is True
        assert result.is_warning is True

    def test_theta_at_threshold_is_warning_and_passes(self, config: RiskConfig) -> None:
        max_abs = (
            config.capital.total_capital * config.greeks.max_theta_daily_decay_pct / 100.0
        )
        portfolio = _make_portfolio(net_theta_daily=-max_abs)
        result = check_theta_decay(portfolio, config)
        # current_decay == max_abs → passed (<=)
        assert result.passed is True
        assert result.is_warning is True

    def test_theta_above_threshold_is_warning_and_fails(self, config: RiskConfig) -> None:
        max_abs = (
            config.capital.total_capital * config.greeks.max_theta_daily_decay_pct / 100.0
        )
        portfolio = _make_portfolio(net_theta_daily=-(max_abs + 1.0))
        result = check_theta_decay(portfolio, config)
        assert result.passed is False
        assert result.is_warning is True

    def test_is_warning_always_true(self, config: RiskConfig) -> None:
        for theta in [0.0, -100.0, -99999.0]:
            result = check_theta_decay(_make_portfolio(net_theta_daily=theta), config)
            assert result.is_warning is True, f"is_warning must be True for theta={theta}"

    def test_negative_theta_uses_abs(self, config: RiskConfig) -> None:
        max_abs = (
            config.capital.total_capital * config.greeks.max_theta_daily_decay_pct / 100.0
        )
        portfolio = _make_portfolio(net_theta_daily=-(max_abs + 10.0))
        result = check_theta_decay(portfolio, config)
        assert abs(result.current_value - (max_abs + 10.0)) < 0.01


# ===========================================================================
# Check 15 — Vega Exposure
# ===========================================================================


class TestCheckVegaExposure:
    def test_zero_portfolio_vega_passes(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(net_vega=0.0)
        request = _make_request(option_vega=10.0, lot_size=50, direction="LONG")
        account = _make_account(session_capital=Decimal("500000"))
        assert check_vega_exposure(portfolio, request, account, config).passed is True

    def test_below_limit_passes(self, config: RiskConfig) -> None:
        # max_vega = 500000 × 5% = 25000; projected = 0 + 30×50 = 1500 → passes
        portfolio = _make_portfolio(net_vega=0.0)
        request = _make_request(option_vega=30.0, lot_size=50, direction="LONG")
        account = _make_account(session_capital=Decimal("500000"))
        assert check_vega_exposure(portfolio, request, account, config).passed is True

    def test_at_limit_passes(self, config: RiskConfig) -> None:
        # projected == max_vega → passes (<=)
        max_vega = float(Decimal("500000")) * config.greeks.max_net_vega_pct / 100.0
        portfolio = _make_portfolio(net_vega=max_vega - 30.0 * 50.0)
        request = _make_request(option_vega=30.0, lot_size=50, direction="LONG")
        account = _make_account(session_capital=Decimal("500000"))
        result = check_vega_exposure(portfolio, request, account, config)
        assert result.passed is True

    def test_above_limit_fails(self, config: RiskConfig) -> None:
        max_vega = 500000.0 * config.greeks.max_net_vega_pct / 100.0
        # Set existing vega just above limit already
        portfolio = _make_portfolio(net_vega=max_vega + 100.0)
        request = _make_request(option_vega=30.0, lot_size=50, direction="LONG")
        account = _make_account(session_capital=Decimal("500000"))
        assert check_vega_exposure(portfolio, request, account, config).passed is False

    def test_short_direction_subtracts_vega(self, config: RiskConfig) -> None:
        # SHORT call: vega contribution is negative (reducing existing long vega)
        portfolio = _make_portfolio(net_vega=1000.0)
        request = _make_request(option_vega=30.0, lot_size=50, direction="SHORT")
        account = _make_account(session_capital=Decimal("500000"))
        result = check_vega_exposure(portfolio, request, account, config)
        # projected = 1000 - 30×50 = 1000 - 1500 = -500; |−500| = 500 → passes
        assert result.passed is True
        assert abs(result.current_value - 500.0) < 0.01

    def test_future_has_no_vega_contribution(self, config: RiskConfig) -> None:
        portfolio = _make_portfolio(net_vega=0.0)
        request = _make_request(
            instrument_class="FUTURE",
            option_premium=None,
            option_delta=None,
            option_vega=None,
        )
        account = _make_account(session_capital=Decimal("500000"))
        result = check_vega_exposure(portfolio, request, account, config)
        assert result.current_value == 0.0
        assert result.passed is True
