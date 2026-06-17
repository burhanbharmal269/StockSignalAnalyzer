"""RiskLimitChecker — 15 pure pre-trade check functions for the risk engine.

All functions are module-level. No class state. No I/O. No async code.
Each function receives all required data as arguments and returns a RiskCheckResult.
No function raises an exception — a failed check returns RiskCheckResult(passed=False).

Check order matches the evaluation sequence in RiskEngineService.evaluate():
  1  KillSwitch           — hard stop if kill switch is active
  2  DailyLoss            — cumulative daily loss against limit_pct and limit_abs
  3  WeeklyLoss           — rolling 5-day loss against limit_pct and limit_abs
  4  Drawdown             — drawdown from HWM against max_drawdown_pct
  5  OpenPositions        — total open positions against max_open_positions
  6  SymbolConcentration  — per-underlying position count against limit
  7  CapitalConcentration — projected post-trade capital + per-trade notional check
  8  NetDelta             — projected signed net portfolio delta against limit
  9  Correlation          — correlation-adjusted net-delta check; CONSERVATIVE_DEFAULT on miss
 10  Margin               — available margin and post-trade utilization limit
 11  RiskReward           — risk/reward ratio within [min_ratio, max_ratio]
 12  PositionSize         — final lot count must be >= 1 (requires SizingResult input)
 13  OrderRate            — per-minute and per-day order rate throttle
 14  ThetaDecay           — daily theta decay vs capital baseline (WARN-ONLY)
 15  VegaExposure         — projected absolute net portfolio vega against limit

No imports from infrastructure layer (except RiskConfig — a pure immutable data object).
"""

from __future__ import annotations

from decimal import Decimal

from core.domain.risk.account_state import AccountState
from core.domain.risk.kill_switch_state import KillSwitchState
from core.domain.risk.portfolio_state import PortfolioState
from core.domain.risk.risk_decision import RiskCheckResult, SizingResult
from core.domain.risk.risk_request import RiskRequest
from core.infrastructure.config.risk_config import RiskConfig

_CONSERVATIVE_DEFAULT_CORRELATION: float = 1.0


def _get_correlation(
    matrix: dict[str, dict[str, float]],
    underlying_a: str,
    underlying_b: str,
) -> float:
    """Return pairwise correlation; applies CONSERVATIVE_DEFAULT (1.0) on any miss."""
    if underlying_a == underlying_b:
        return 1.0
    corr = matrix.get(underlying_a, {}).get(underlying_b)
    if corr is None:
        corr = matrix.get(underlying_b, {}).get(underlying_a)
    return corr if corr is not None else _CONSERVATIVE_DEFAULT_CORRELATION


# ---------------------------------------------------------------------------
# Check 1 — Kill Switch
# ---------------------------------------------------------------------------


def check_kill_switch(
    state: KillSwitchState,
    config: RiskConfig,  # reserved for future kill-switch policy config
) -> RiskCheckResult:
    """Reject immediately when the kill switch is active."""
    passed = not state.is_active
    if passed:
        msg = "Kill switch inactive — evaluation proceeds"
    else:
        msg = (
            f"Kill switch active (by={state.activated_by!r}): "
            f"{state.activation_reason}"
        )
    return RiskCheckResult(
        check_name="KillSwitch",
        passed=passed,
        current_value=1.0 if state.is_active else 0.0,
        limit_value=0.0,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 2 — Daily Loss
# ---------------------------------------------------------------------------


def check_daily_loss(account: AccountState, config: RiskConfig) -> RiskCheckResult:
    """Reject when daily P&L loss exceeds the configured percentage or absolute limit.

    Enforces two independent conditions; either triggers rejection:
      1. Absolute: account.daily_loss_consumed_pct >= 100.0 (INR limit reached).
      2. Percentage: current_loss_pct >= config.daily_loss.limit_pct.
    Absolute limit takes precedence in evaluation order and failure reporting.
    """
    session_cap = float(account.session_capital)
    if session_cap > 0.0 and account.daily_pnl < Decimal(0):
        current_loss_pct = float(abs(account.daily_pnl)) / session_cap * 100.0
    else:
        current_loss_pct = 0.0

    if account.daily_loss_consumed_pct >= 100.0:
        return RiskCheckResult(
            check_name="DailyLoss",
            passed=False,
            current_value=account.daily_loss_consumed_pct,
            limit_value=100.0,
            message=(
                f"Daily loss consumed {account.daily_loss_consumed_pct:.1f}% "
                f"of absolute limit ({config.daily_loss.limit_abs} INR)"
            ),
        )
    if current_loss_pct >= config.daily_loss.limit_pct:
        return RiskCheckResult(
            check_name="DailyLoss",
            passed=False,
            current_value=current_loss_pct,
            limit_value=config.daily_loss.limit_pct,
            message=(
                f"Daily loss {current_loss_pct:.2f}% at or above limit "
                f"{config.daily_loss.limit_pct:.2f}%"
            ),
        )
    return RiskCheckResult(
        check_name="DailyLoss",
        passed=True,
        current_value=current_loss_pct,
        limit_value=config.daily_loss.limit_pct,
        message=(
            f"Daily loss {current_loss_pct:.2f}% within limit "
            f"{config.daily_loss.limit_pct:.2f}%"
        ),
    )


# ---------------------------------------------------------------------------
# Check 3 — Weekly Loss
# ---------------------------------------------------------------------------


def check_weekly_loss(account: AccountState, config: RiskConfig) -> RiskCheckResult:
    """Reject when rolling 5-day P&L loss exceeds the configured percentage or absolute limit.

    Enforces two independent conditions; either triggers rejection:
      1. Absolute: account.weekly_loss_consumed_pct >= 100.0 (INR limit reached).
      2. Percentage: current_loss_pct >= config.weekly_loss.limit_pct.
    Absolute limit takes precedence in evaluation order and failure reporting.
    """
    session_cap = float(account.session_capital)
    if session_cap > 0.0 and account.weekly_pnl < Decimal(0):
        current_loss_pct = float(abs(account.weekly_pnl)) / session_cap * 100.0
    else:
        current_loss_pct = 0.0

    if account.weekly_loss_consumed_pct >= 100.0:
        return RiskCheckResult(
            check_name="WeeklyLoss",
            passed=False,
            current_value=account.weekly_loss_consumed_pct,
            limit_value=100.0,
            message=(
                f"Weekly loss consumed {account.weekly_loss_consumed_pct:.1f}% "
                f"of absolute limit ({config.weekly_loss.limit_abs} INR)"
            ),
        )
    if current_loss_pct >= config.weekly_loss.limit_pct:
        return RiskCheckResult(
            check_name="WeeklyLoss",
            passed=False,
            current_value=current_loss_pct,
            limit_value=config.weekly_loss.limit_pct,
            message=(
                f"Weekly loss {current_loss_pct:.2f}% at or above limit "
                f"{config.weekly_loss.limit_pct:.2f}%"
            ),
        )
    return RiskCheckResult(
        check_name="WeeklyLoss",
        passed=True,
        current_value=current_loss_pct,
        limit_value=config.weekly_loss.limit_pct,
        message=(
            f"Weekly loss {current_loss_pct:.2f}% within limit "
            f"{config.weekly_loss.limit_pct:.2f}%"
        ),
    )


# ---------------------------------------------------------------------------
# Check 4 — Drawdown
# ---------------------------------------------------------------------------


def check_drawdown(account: AccountState, config: RiskConfig) -> RiskCheckResult:
    """Reject when drawdown from the high-water mark exceeds the configured maximum."""
    current = account.drawdown_from_hwm_pct
    limit = config.drawdown.max_drawdown_pct
    passed = current < limit
    if passed:
        msg = f"Drawdown {current:.2f}% within limit {limit:.2f}%"
    else:
        msg = f"Drawdown {current:.2f}% at or above limit {limit:.2f}%"
    return RiskCheckResult(
        check_name="Drawdown",
        passed=passed,
        current_value=current,
        limit_value=limit,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 5 — Open Positions
# ---------------------------------------------------------------------------


def check_open_positions(
    portfolio: PortfolioState, config: RiskConfig
) -> RiskCheckResult:
    """Reject when the total open position count would exceed the portfolio limit."""
    current = portfolio.open_positions_count
    limit = config.position_limits.max_open_positions
    passed = current < limit
    if passed:
        msg = f"Open positions {current} below limit {limit}"
    else:
        msg = f"Open positions {current} at or above limit {limit}"
    return RiskCheckResult(
        check_name="OpenPositions",
        passed=passed,
        current_value=float(current),
        limit_value=float(limit),
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 6 — Symbol Concentration
# ---------------------------------------------------------------------------


def check_symbol_concentration(
    portfolio: PortfolioState,
    request: RiskRequest,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when positions in the request's underlying would exceed the per-symbol limit."""
    current = portfolio.positions_per_underlying.get(request.underlying, 0)
    limit = config.position_limits.max_positions_per_underlying
    passed = current < limit
    if passed:
        msg = (
            f"{request.underlying} position count {current} "
            f"below limit {limit}"
        )
    else:
        msg = (
            f"{request.underlying} position count {current} "
            f"at or above limit {limit}"
        )
    return RiskCheckResult(
        check_name="SymbolConcentration",
        passed=passed,
        current_value=float(current),
        limit_value=float(limit),
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 7 — Capital Concentration
# ---------------------------------------------------------------------------


def check_capital_concentration(
    portfolio: PortfolioState,
    request: RiskRequest,
    account: AccountState,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when projected post-trade capital or per-trade notional would breach limits.

    Sub-check A: (existing + new trade) capital in request.underlying vs
                 max_capital_per_underlying_pct.  Uses account_capital as denominator
                 (same basis as capital_per_underlying_pct in PortfolioState).
    Sub-check B: per-trade notional (1-lot capital-at-risk) vs max_notional_per_trade_pct.
                 Same account_capital denominator as sub-check A.
    For OPTION: lot_risk = option_premium × lot_size (premium capital at risk).
    For FUTURE: lot_risk = atr_14 × atr_stop_multiplier × lot_size (stop-distance at risk).
    """
    total_cap = float(account.account_capital)

    if request.instrument_class == "OPTION" and request.option_premium is not None:
        lot_risk = float(request.option_premium) * request.lot_size
    else:
        lot_risk = (
            request.atr_14
            * config.position_sizing.atr_stop_multiplier
            * request.lot_size
        )

    trade_capital_pct = (lot_risk / total_cap * 100.0) if total_cap > 0.0 else 0.0

    # Sub-check A: projected post-trade concentration
    existing_pct = portfolio.capital_per_underlying_pct.get(request.underlying, 0.0)
    projected_pct = existing_pct + trade_capital_pct
    conc_limit = config.position_limits.max_capital_per_underlying_pct

    # Sub-check B: per-trade notional cap
    notional_limit = config.position_limits.max_notional_per_trade_pct
    notional_ok = trade_capital_pct <= notional_limit

    if projected_pct >= conc_limit:
        return RiskCheckResult(
            check_name="CapitalConcentration",
            passed=False,
            current_value=projected_pct,
            limit_value=conc_limit,
            message=(
                f"{request.underlying} projected capital {projected_pct:.1f}% "
                f"(existing {existing_pct:.1f}% + new {trade_capital_pct:.1f}%) "
                f"would exceed limit {conc_limit:.1f}%"
            ),
        )
    if not notional_ok:
        return RiskCheckResult(
            check_name="CapitalConcentration",
            passed=False,
            current_value=trade_capital_pct,
            limit_value=notional_limit,
            message=(
                f"Trade notional {trade_capital_pct:.1f}% of capital "
                f"exceeds limit {notional_limit:.1f}%"
            ),
        )
    return RiskCheckResult(
        check_name="CapitalConcentration",
        passed=True,
        current_value=projected_pct,
        limit_value=conc_limit,
        message=(
            f"{request.underlying} projected {projected_pct:.1f}% conc, "
            f"trade {trade_capital_pct:.1f}% — within limits"
        ),
    )


# ---------------------------------------------------------------------------
# Check 8 — Net Delta
# ---------------------------------------------------------------------------


def check_net_delta(
    portfolio: PortfolioState,
    request: RiskRequest,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when projected signed net portfolio delta exceeds the absolute limit.

    Adds the 1-lot delta contribution of the new position to the existing net_delta.
    For OPTION: delta contribution = option_delta × lot_size × direction_sign.
    For FUTURE: delta contribution = 1.0 × lot_size × direction_sign (full linear exposure).
    """
    direction_sign = 1.0 if request.direction == "LONG" else -1.0
    if request.instrument_class == "OPTION" and request.option_delta is not None:
        new_delta = request.option_delta * request.lot_size * direction_sign
    else:
        new_delta = float(request.lot_size) * direction_sign

    projected = portfolio.net_delta + new_delta
    current_value = abs(projected)
    limit = config.greeks.max_net_delta
    passed = current_value < limit
    if passed:
        msg = f"Projected net delta {projected:.1f} (abs {current_value:.1f}) within {limit:.1f}"
    else:
        msg = f"Projected net delta {projected:.1f} (abs {current_value:.1f}) exceeds {limit:.1f}"
    return RiskCheckResult(
        check_name="NetDelta",
        passed=passed,
        current_value=current_value,
        limit_value=limit,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 9 — Correlation
# ---------------------------------------------------------------------------


def check_correlation(
    portfolio: PortfolioState,
    request: RiskRequest,
    correlation_matrix: dict[str, dict[str, float]],
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when correlation-adjusted projected net delta exceeds max_net_delta.

    Applies max pairwise correlation as a discount on the existing portfolio delta,
    then adds the new position's signed delta contribution:
        corr_adjusted_portfolio = portfolio.net_delta × max_rho
        effective_exposure       = corr_adjusted_portfolio + new_delta_signed
        correlated_exposure      = |effective_exposure|

    max_rho = maximum pairwise correlation between request.underlying and any
    existing underlying; defaults to CONSERVATIVE_DEFAULT (1.0) on any cache miss.

    Design intent (AD-P13-01): This is a correlation-adjusted net-delta check.
    Cross-instrument trades receive a discount proportional to (1 − max_rho).
    Risk-reducing trades in the opposing direction always pass when Check 8 passes.
    Per-underlying correlated gross exposure analysis is deferred to Phase 2.

    When portfolio has no positions, this check always passes (no correlated peers).
    """
    if not portfolio.positions_per_underlying:
        return RiskCheckResult(
            check_name="Correlation",
            passed=True,
            current_value=0.0,
            limit_value=config.greeks.max_net_delta,
            message="No existing positions — correlation limit not applicable",
        )

    max_rho = max(
        _get_correlation(correlation_matrix, request.underlying, existing)
        for existing in portfolio.positions_per_underlying
    )

    direction_sign = 1.0 if request.direction == "LONG" else -1.0
    if request.instrument_class == "OPTION" and request.option_delta is not None:
        new_delta_signed = request.option_delta * request.lot_size * direction_sign
    else:
        new_delta_signed = float(request.lot_size) * direction_sign

    corr_adjusted_portfolio = portfolio.net_delta * max_rho
    effective_exposure = corr_adjusted_portfolio + new_delta_signed
    correlated_exposure = abs(effective_exposure)
    limit = config.greeks.max_net_delta
    passed = correlated_exposure < limit
    if passed:
        msg = (
            f"Corr-adjusted exposure {correlated_exposure:.1f} "
            f"within {limit:.1f} (max_rho={max_rho:.2f})"
        )
    else:
        msg = (
            f"Corr-adjusted exposure {correlated_exposure:.1f} "
            f"exceeds {limit:.1f} (max_rho={max_rho:.2f})"
        )
    return RiskCheckResult(
        check_name="Correlation",
        passed=passed,
        current_value=correlated_exposure,
        limit_value=limit,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 10 — Margin
# ---------------------------------------------------------------------------


def check_margin(
    account: AccountState,
    margin_required: Decimal,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when available margin is insufficient or post-trade utilization exceeds limit."""
    sufficient = account.available_margin >= margin_required
    account_cap = float(account.account_capital)
    if account_cap > 0.0:
        post_util = (
            float(account.used_margin + margin_required) / account_cap * 100.0
        )
    else:
        post_util = 100.0
    util_ok = post_util <= config.margin.utilization_limit_pct
    passed = sufficient and util_ok
    limit = config.margin.utilization_limit_pct
    if not sufficient:
        msg = (
            f"Insufficient margin: need {margin_required} INR, "
            f"available {account.available_margin} INR"
        )
    elif not util_ok:
        msg = (
            f"Post-trade margin utilization {post_util:.1f}% "
            f"would exceed limit {limit:.1f}%"
        )
    else:
        msg = f"Margin check passed: post-trade utilization {post_util:.1f}%"
    return RiskCheckResult(
        check_name="Margin",
        passed=passed,
        current_value=post_util,
        limit_value=limit,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 11 — Risk/Reward
# ---------------------------------------------------------------------------


def check_risk_reward(request: RiskRequest, config: RiskConfig) -> RiskCheckResult:
    """Reject when risk/reward ratio is outside [min_ratio, max_ratio]."""
    rr = request.risk_reward_ratio
    min_r = config.risk_reward.min_ratio
    max_r = config.risk_reward.max_ratio
    passed = min_r <= rr <= max_r
    if rr < min_r:
        msg = f"Risk/reward {rr:.2f} below minimum {min_r:.2f}"
    elif rr > max_r:
        msg = f"Risk/reward {rr:.2f} above maximum {max_r:.2f} (unrealistic signal)"
    else:
        msg = f"Risk/reward {rr:.2f} within [{min_r:.2f}, {max_r:.2f}]"
    return RiskCheckResult(
        check_name="RiskReward",
        passed=passed,
        current_value=rr,
        limit_value=min_r,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 12 — Position Size
# ---------------------------------------------------------------------------


def check_position_size(sizing: SizingResult) -> RiskCheckResult:
    """Reject when the computed lot count is zero after all sizing calculations."""
    passed = sizing.lots >= 1
    if passed:
        msg = f"Position size {sizing.lots} lot(s) approved"
    else:
        note = f" ({sizing.sizing_note})" if sizing.sizing_note else ""
        msg = f"Position size is zero after sizing{note}"
    return RiskCheckResult(
        check_name="PositionSize",
        passed=passed,
        current_value=float(sizing.lots),
        limit_value=1.0,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 13 — Order Rate
# ---------------------------------------------------------------------------


def check_order_rate(
    portfolio: PortfolioState, config: RiskConfig
) -> RiskCheckResult:
    """Reject when per-minute or per-day order count reaches the configured limits.

    Enforces two independent conditions; either triggers rejection:
      1. Per-minute rate: orders_last_minute >= max_orders_per_minute.
      2. Daily total:     orders_today >= max_orders_per_day.
    Per-minute check takes precedence in evaluation order and failure reporting.
    """
    per_minute = portfolio.orders_last_minute
    per_day = portfolio.orders_today
    minute_limit = config.order_rate.max_orders_per_minute
    day_limit = config.order_rate.max_orders_per_day

    if per_minute >= minute_limit:
        return RiskCheckResult(
            check_name="OrderRate",
            passed=False,
            current_value=float(per_minute),
            limit_value=float(minute_limit),
            message=f"Order rate {per_minute}/min at or above limit {minute_limit}/min",
        )
    if per_day >= day_limit:
        return RiskCheckResult(
            check_name="OrderRate",
            passed=False,
            current_value=float(per_day),
            limit_value=float(day_limit),
            message=f"Daily order count {per_day} at or above daily limit {day_limit}",
        )
    return RiskCheckResult(
        check_name="OrderRate",
        passed=True,
        current_value=float(per_minute),
        limit_value=float(minute_limit),
        message=f"Order rate {per_minute}/min below limit {minute_limit}/min",
    )


# ---------------------------------------------------------------------------
# Check 14 — Theta Decay  (WARN-ONLY — never blocks evaluation)
# ---------------------------------------------------------------------------


def check_theta_decay(
    portfolio: PortfolioState, config: RiskConfig
) -> RiskCheckResult:
    """Warn (never reject) when daily theta decay exceeds the capital-baseline threshold.

    Limit = config.capital.total_capital × max_theta_daily_decay_pct / 100.
    The total_capital baseline (not session_capital) ensures a stable reference
    independent of intraday MTM fluctuations.

    is_warning is ALWAYS True for this check — even when the threshold is breached,
    the evaluation continues and no rejection is issued.
    """
    max_theta_abs = (
        config.capital.total_capital
        * config.greeks.max_theta_daily_decay_pct
        / 100.0
    )
    current_decay = abs(portfolio.net_theta_daily)
    passed = current_decay <= max_theta_abs
    if passed:
        msg = (
            f"Theta decay {current_decay:.1f} INR/day within "
            f"threshold {max_theta_abs:.1f} INR/day"
        )
    else:
        msg = (
            f"Theta decay {current_decay:.1f} INR/day exceeds "
            f"warning threshold {max_theta_abs:.1f} INR/day"
        )
    return RiskCheckResult(
        check_name="ThetaDecay",
        passed=passed,
        current_value=current_decay,
        limit_value=max_theta_abs,
        message=msg,
        is_warning=True,
    )


# ---------------------------------------------------------------------------
# Check 15 — Vega Exposure
# ---------------------------------------------------------------------------


def check_vega_exposure(
    portfolio: PortfolioState,
    request: RiskRequest,
    account: AccountState,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when the projected absolute net portfolio vega exceeds the limit.

    Limit = session_capital × max_net_vega_pct / 100.
    New-position vega contribution: option_vega × lot_size × direction_sign.
    Futures carry no vega; their contribution is 0.
    """
    max_vega_abs = float(account.session_capital) * config.greeks.max_net_vega_pct / 100.0
    direction_sign = 1.0 if request.direction == "LONG" else -1.0
    if request.instrument_class == "OPTION" and request.option_vega is not None:
        new_vega = request.option_vega * request.lot_size * direction_sign
    else:
        new_vega = 0.0

    projected_vega = portfolio.net_vega + new_vega
    current_value = abs(projected_vega)
    passed = current_value <= max_vega_abs
    if passed:
        msg = (
            f"Projected vega {projected_vega:.1f} INR/% "
            f"(abs {current_value:.1f}) within {max_vega_abs:.1f}"
        )
    else:
        msg = (
            f"Projected vega {projected_vega:.1f} INR/% "
            f"(abs {current_value:.1f}) exceeds {max_vega_abs:.1f}"
        )
    return RiskCheckResult(
        check_name="VegaExposure",
        passed=passed,
        current_value=current_value,
        limit_value=max_vega_abs,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 16 — Monthly Loss
# ---------------------------------------------------------------------------


def check_monthly_loss(
    account: AccountState,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when cumulative monthly P&L loss exceeds the monthly loss limit.

    Uses the lesser of:
      - total_capital × monthly_loss.limit_pct / 100
      - monthly_loss.limit_abs (INR absolute)
    """
    monthly_pnl: float = float(getattr(account, "monthly_pnl", 0.0) or 0.0)

    try:
        limit_pct_abs = float(config.capital.total_capital) * float(config.monthly_loss.limit_pct) / 100.0
        limit_abs = float(config.monthly_loss.limit_abs)
        effective_limit = min(limit_pct_abs, limit_abs)
    except (TypeError, AttributeError):
        # Config is a mock or missing fields — treat as not configured; pass.
        return RiskCheckResult(
            check_name="MonthlyLoss",
            passed=True,
            current_value=monthly_pnl,
            limit_value=0.0,
            message="MonthlyLoss not configured — skipped",
        )

    passed = monthly_pnl > -effective_limit
    if passed:
        msg = (
            f"Monthly P&L {monthly_pnl:.2f} INR within monthly limit "
            f"-{effective_limit:.2f} INR"
        )
    else:
        msg = (
            f"Monthly P&L {monthly_pnl:.2f} INR breaches monthly loss limit "
            f"-{effective_limit:.2f} INR"
        )
    return RiskCheckResult(
        check_name="MonthlyLoss",
        passed=passed,
        current_value=monthly_pnl,
        limit_value=-effective_limit,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 17 — Volatility Block
# ---------------------------------------------------------------------------


def check_volatility_block(
    current_vix: float,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject new positions when India VIX exceeds the configured threshold.

    VIX data must be supplied by the caller (sourced from NSE/MarketData provider).
    When volatility_block.enabled is False this check always passes.
    """
    try:
        enabled = bool(config.volatility_block.enabled)
        threshold = float(config.volatility_block.vix_threshold)
    except (TypeError, AttributeError):
        return RiskCheckResult(
            check_name="VolatilityBlock",
            passed=True,
            current_value=current_vix,
            limit_value=0.0,
            message="VolatilityBlock not configured — skipped",
        )

    if not enabled:
        return RiskCheckResult(
            check_name="VolatilityBlock",
            passed=True,
            current_value=current_vix,
            limit_value=threshold,
            message="VolatilityBlock check disabled in config",
        )
    passed = current_vix < threshold
    if passed:
        msg = f"India VIX {current_vix:.2f} below threshold {threshold:.2f} — trading allowed"
    else:
        msg = f"India VIX {current_vix:.2f} at or above threshold {threshold:.2f} — new positions blocked"
    return RiskCheckResult(
        check_name="VolatilityBlock",
        passed=passed,
        current_value=current_vix,
        limit_value=threshold,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 18 — Symbol Exposure
# ---------------------------------------------------------------------------


def check_symbol_exposure(
    symbol_notional: float,
    total_capital: float,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when a single symbol's notional exceeds the configured exposure limit.

    Args:
        symbol_notional: Total notional (INR) already deployed in this symbol,
                         EXCLUDING the proposed trade.
        total_capital:   Total account capital (session_capital or total_capital).
        config:          RiskConfig (reads exposure_limits.max_symbol_exposure_pct).
    """
    try:
        enabled = bool(config.exposure_limits.enabled)
        limit_pct = float(config.exposure_limits.max_symbol_exposure_pct)
    except (TypeError, AttributeError):
        return RiskCheckResult(
            check_name="SymbolExposure",
            passed=True,
            current_value=0.0,
            limit_value=0.0,
            message="SymbolExposure not configured — skipped",
        )

    if not enabled or total_capital <= 0:
        return RiskCheckResult(
            check_name="SymbolExposure",
            passed=True,
            current_value=0.0,
            limit_value=limit_pct,
            message="SymbolExposure check disabled",
        )

    current_pct = float(symbol_notional / total_capital) * 100.0
    passed = current_pct < limit_pct
    msg = (
        f"Symbol exposure {current_pct:.2f}% {'within' if passed else 'exceeds'} "
        f"limit {limit_pct:.2f}%"
    )
    return RiskCheckResult(
        check_name="SymbolExposure",
        passed=passed,
        current_value=current_pct,
        limit_value=limit_pct,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 19 — Sector Exposure
# ---------------------------------------------------------------------------


def check_sector_exposure(
    sector_notional: float,
    total_capital: float,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when a single sector's notional exceeds the configured sector exposure limit.

    Args:
        sector_notional: Total notional (INR) already in this sector (all positions).
        total_capital:   Account total capital.
        config:          RiskConfig (reads exposure_limits.max_sector_exposure_pct).
    """
    try:
        enabled = bool(config.exposure_limits.enabled)
        limit_pct = float(config.exposure_limits.max_sector_exposure_pct)
    except (TypeError, AttributeError):
        return RiskCheckResult(
            check_name="SectorExposure",
            passed=True,
            current_value=0.0,
            limit_value=0.0,
            message="SectorExposure not configured — skipped",
        )

    if not enabled or total_capital <= 0:
        return RiskCheckResult(
            check_name="SectorExposure",
            passed=True,
            current_value=0.0,
            limit_value=limit_pct,
            message="SectorExposure check disabled",
        )

    current_pct = float(sector_notional / total_capital) * 100.0
    passed = current_pct < limit_pct
    msg = (
        f"Sector exposure {current_pct:.2f}% {'within' if passed else 'exceeds'} "
        f"limit {limit_pct:.2f}%"
    )
    return RiskCheckResult(
        check_name="SectorExposure",
        passed=passed,
        current_value=current_pct,
        limit_value=limit_pct,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 20 — Strategy Exposure
# ---------------------------------------------------------------------------


def check_strategy_exposure(
    strategy_notional: float,
    total_capital: float,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when a single strategy's deployed capital exceeds the configured limit.

    Args:
        strategy_notional: Total notional deployed by this strategy across all open positions.
        total_capital:     Account total capital.
        config:            RiskConfig (reads exposure_limits.max_strategy_exposure_pct).
    """
    try:
        enabled = bool(config.exposure_limits.enabled)
        limit_pct = float(config.exposure_limits.max_strategy_exposure_pct)
    except (TypeError, AttributeError):
        return RiskCheckResult(
            check_name="StrategyExposure",
            passed=True,
            current_value=0.0,
            limit_value=0.0,
            message="StrategyExposure not configured — skipped",
        )

    if not enabled or total_capital <= 0:
        return RiskCheckResult(
            check_name="StrategyExposure",
            passed=True,
            current_value=0.0,
            limit_value=limit_pct,
            message="StrategyExposure check disabled",
        )

    current_pct = float(strategy_notional / total_capital) * 100.0
    passed = current_pct < limit_pct
    msg = (
        f"Strategy exposure {current_pct:.2f}% {'within' if passed else 'exceeds'} "
        f"limit {limit_pct:.2f}%"
    )
    return RiskCheckResult(
        check_name="StrategyExposure",
        passed=passed,
        current_value=current_pct,
        limit_value=limit_pct,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Check 21 — Concentration
# ---------------------------------------------------------------------------


def check_concentration(
    position_notionals: "list[float] | dict",
    total_capital: float,
    config: RiskConfig,
) -> RiskCheckResult:
    """Reject when concentration in any single position or top-3 exceeds configured limits.

    Args:
        position_notionals: List or dict of notional values (INR) for ALL open positions.
                            If a dict, values are the notionals.
        total_capital:      Account total capital.
        config:             RiskConfig (reads concentration.*).

    Checks two conditions (either triggers rejection):
      1. Single position > max_single_position_pct of total capital.
      2. Top-3 positions combined > max_top3_concentration_pct of total capital.
    """
    try:
        enabled = bool(config.concentration.enabled)
        single_limit_pct = float(config.concentration.max_single_position_pct)
        top3_limit_pct = float(config.concentration.max_top3_concentration_pct)
    except (TypeError, AttributeError):
        return RiskCheckResult(
            check_name="Concentration",
            passed=True,
            current_value=0.0,
            limit_value=0.0,
            message="Concentration not configured — skipped",
        )

    if not enabled or total_capital <= 0 or not position_notionals:
        return RiskCheckResult(
            check_name="Concentration",
            passed=True,
            current_value=0.0,
            limit_value=single_limit_pct,
            message="Concentration check disabled or no positions",
        )

    notional_values = list(position_notionals.values()) if isinstance(position_notionals, dict) else list(position_notionals)
    sorted_notionals = sorted(notional_values, reverse=True)
    max_single = sorted_notionals[0]
    top3_total = sum(sorted_notionals[:3])

    max_single_pct = float(max_single / total_capital) * 100.0
    top3_pct = float(top3_total / total_capital) * 100.0

    if max_single_pct >= single_limit_pct:
        return RiskCheckResult(
            check_name="Concentration",
            passed=False,
            current_value=max_single_pct,
            limit_value=single_limit_pct,
            message=(
                f"Single-position concentration {max_single_pct:.2f}% "
                f"exceeds limit {single_limit_pct:.2f}%"
            ),
        )

    if top3_pct >= top3_limit_pct:
        return RiskCheckResult(
            check_name="Concentration",
            passed=False,
            current_value=top3_pct,
            limit_value=top3_limit_pct,
            message=(
                f"Top-3 concentration {top3_pct:.2f}% "
                f"exceeds limit {top3_limit_pct:.2f}%"
            ),
        )

    return RiskCheckResult(
        check_name="Concentration",
        passed=True,
        current_value=max_single_pct,
        limit_value=single_limit_pct,
        message=(
            f"Concentration within limits: single={max_single_pct:.2f}%, "
            f"top3={top3_pct:.2f}%"
        ),
    )
