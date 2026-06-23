"""RiskEngineService — full 15-check pre-trade risk evaluation.

Architecture rules (all mandatory):

D-1 (sequential queue): asyncio.Lock queues concurrent evaluate() calls.
     Second request waits; it is NEVER rejected with ConcurrentEvaluationError.

D-2 (persistence-first): RiskDecision INSERT is inside the lock. Event
     publication is OUTSIDE the lock (after async with exits).

D-3 (kill switch precedence): kill switch active → immediate return with no
     INSERT and no event publication.

D-4 (fail closed): required sources (kill_switch, account, portfolio,
     graduated_response, margin) raise DataSourceUnavailableError → rejection,
     no INSERT when account_snapshot is unavailable (NOT NULL constraint).

D-5 (is_hard_failure): rejection predicate is result.is_hard_failure, not
     ``not result.passed``. ThetaDecay (Check 14) has is_hard_failure=False.

RC-5: asyncio.wait_for wraps the INSERT; timeout_seconds param unused inside
      the repository itself.

3-tier event delivery: direct publish → 3 retries → LPUSH pending queue → CRITICAL log.

Rule 10 (gather timeout): asyncio.wait_for wraps the parallel gather.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from decimal import Decimal

from core.domain.events.base import DomainEvent
from core.domain.events.risk_events import (
    DataSourceUnavailable,
    RiskApproved,
    RiskRejected,
)
from core.domain.exceptions.risk import (
    RiskDecisionPersistenceError,
)
from core.domain.interfaces.i_account_state_repository import IAccountStateRepository
from core.domain.interfaces.i_correlation_repository import ICorrelationRepository
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_kill_switch_repository import IKillSwitchRepository
from core.domain.interfaces.i_margin_service import IMarginService
from core.domain.interfaces.i_portfolio_state_repository import IPortfolioStateRepository
from core.domain.interfaces.i_risk_decision_repository import IRiskDecisionRepository
from core.domain.interfaces.i_signal_performance_repository import ISignalPerformanceRepository
from core.domain.risk.position_sizer import PositionSizer
from core.domain.risk.risk_decision import (
    RiskCheckResult,
    RiskDecision,
    RiskRejectionCode,
    SizingResult,
)
from core.domain.risk.risk_limit_checker import (
    check_capital_concentration,
    check_concentration,
    check_correlation,
    check_daily_loss,
    check_drawdown,
    check_kill_switch,
    check_margin,
    check_monthly_loss,
    check_net_delta,
    check_open_positions,
    check_order_rate,
    check_position_size,
    check_risk_reward,
    check_sector_exposure,
    check_strategy_exposure,
    check_symbol_concentration,
    check_symbol_exposure,
    check_theta_decay,
    check_vega_exposure,
    check_volatility_block,
    check_weekly_loss,
)
from core.domain.risk.risk_request import RiskRequest
from core.infrastructure.config.risk_config import RiskConfig

_log = logging.getLogger(__name__)

_RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.0, 0.2, 0.4)
_PENDING_DELIVERY_KEY = "risk:approvals_pending_delivery"

_CHECK_TO_REJECTION_CODE: dict[str, RiskRejectionCode] = {
    "KillSwitch": RiskRejectionCode.KILL_SWITCH_ACTIVE,
    "DailyLoss": RiskRejectionCode.DAILY_LOSS_LIMIT,
    "WeeklyLoss": RiskRejectionCode.WEEKLY_LOSS_LIMIT,
    "Drawdown": RiskRejectionCode.DRAWDOWN_LIMIT,
    "OpenPositions": RiskRejectionCode.MAX_OPEN_POSITIONS,
    "SymbolConcentration": RiskRejectionCode.SYMBOL_CONCENTRATION,
    "CapitalConcentration": RiskRejectionCode.CAPITAL_CONCENTRATION,
    "NetDelta": RiskRejectionCode.NET_DELTA_LIMIT,
    "Correlation": RiskRejectionCode.CORRELATION_LIMIT,
    "Margin": RiskRejectionCode.INSUFFICIENT_MARGIN,
    "RiskReward": RiskRejectionCode.RISK_REWARD_BELOW_MINIMUM,
    "PositionSize": RiskRejectionCode.POSITION_SIZE_ZERO,
    "OrderRate": RiskRejectionCode.ORDER_RATE_LIMIT,
    "VegaExposure": RiskRejectionCode.VEGA_LIMIT,
    "MonthlyLoss": RiskRejectionCode.WEEKLY_LOSS_LIMIT,
    "VolatilityBlock": RiskRejectionCode.DRAWDOWN_LIMIT,
    "SymbolExposure": RiskRejectionCode.SYMBOL_CONCENTRATION,
    "SectorExposure": RiskRejectionCode.SYMBOL_CONCENTRATION,
    "StrategyExposure": RiskRejectionCode.CAPITAL_CONCENTRATION,
    "Concentration": RiskRejectionCode.CAPITAL_CONCENTRATION,
}


class RiskEngineService:

    def __init__(
        self,
        kill_switch_repo: IKillSwitchRepository,
        account_state_repo: IAccountStateRepository,
        portfolio_state_repo: IPortfolioStateRepository,
        correlation_repo: ICorrelationRepository,
        margin_service: IMarginService,
        signal_perf_repo: ISignalPerformanceRepository,
        risk_decision_repo: IRiskDecisionRepository,
        event_bus: IEventBus,
        redis_client: object,  # Redis — used for 3-tier delivery fallback queue
        config: RiskConfig,
    ) -> None:
        self._ks_repo = kill_switch_repo
        self._account_repo = account_state_repo
        self._portfolio_repo = portfolio_state_repo
        self._corr_repo = correlation_repo
        self._margin_service = margin_service
        self._signal_perf_repo = signal_perf_repo
        self._risk_decision_repo = risk_decision_repo
        self._event_bus = event_bus
        self._redis = redis_client
        self._config = config
        self._evaluation_lock = asyncio.Lock()

    async def evaluate(self, request: RiskRequest) -> RiskDecision:
        """Evaluate a single pre-trade risk request.

        Concurrent calls are queued (D-1). Each call runs to completion; the
        second caller waits until the first releases the lock.
        """
        deferred_events: list[DomainEvent] = []

        async with self._evaluation_lock:  # D-1: queue, never reject
            decision, deferred_events = await self._evaluate_locked(request)
        # Lock released (D-2): persist already done inside _evaluate_locked

        for event in deferred_events:  # D-3: events outside lock
            await self._publish_with_retry(event)

        return decision

    async def _evaluate_locked(
        self, request: RiskRequest
    ) -> tuple[RiskDecision, list[DomainEvent]]:
        """Run full evaluation inside the lock.  Returns (decision, events_to_publish)."""
        start_ns = time.monotonic_ns()

        # ----------------------------------------------------------------
        # Rule 10: gather all dependencies in parallel with total timeout
        # ----------------------------------------------------------------
        gather_timeout = self._config.risk_engine.gather_timeout_seconds
        margin_timeout = self._config.margin.timeout_seconds

        try:
            gather_results = await asyncio.wait_for(
                asyncio.gather(
                    self._ks_repo.get_state(),
                    self._account_repo.get_current(),
                    self._portfolio_repo.get_current(),
                    self._portfolio_repo.get_graduated_response(),
                    self._corr_repo.get_matrix(),
                    self._margin_service.get_required_margin(
                        request.instrument_token,
                        1,  # check affordability for 1 lot; position sizer determines final count
                        margin_timeout,
                    ),
                    self._signal_perf_repo.get_sizing_stats(
                        instrument=request.underlying,
                        instrument_class=request.instrument_class,
                        lookback_days=90,
                        min_samples=self._config.position_sizing.min_kelly_samples,
                    ),
                    return_exceptions=True,
                ),
                timeout=gather_timeout,
            )
        except TimeoutError:
            elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.DATA_SOURCE_UNAVAILABLE,
                reason=f"Dependency gather timed out after {gather_timeout:.2f}s",
                checks=(),
                sizing=None,
                account_snapshot=None,
                failed_sources=("gather_timeout",),
                elapsed_ms=elapsed_ms,
            )
            return decision, []

        (
            ks_result,
            acct_result,
            port_result,
            grad_result,
            corr_result,
            margin_result,
            stats_result,
        ) = gather_results

        elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000

        # ----------------------------------------------------------------
        # D-3: Kill switch — first check, no INSERT, no event
        # ----------------------------------------------------------------
        if isinstance(ks_result, Exception):
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.KILL_SWITCH_ACTIVE,
                reason=f"Kill switch state unavailable (FAIL_CLOSED): {ks_result}",
                checks=(),
                sizing=None,
                account_snapshot=None,
                failed_sources=("kill_switch",),
                elapsed_ms=elapsed_ms,
            )
            return decision, []

        ks_check = check_kill_switch(ks_result, self._config)
        if ks_result.is_active:
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.KILL_SWITCH_ACTIVE,
                reason=ks_check.message,
                checks=(ks_check,),
                sizing=None,
                account_snapshot=None,
                failed_sources=(),
                elapsed_ms=elapsed_ms,
            )
            return decision, []

        checks: list[RiskCheckResult] = [ks_check]
        failed_sources: list[str] = []

        # ----------------------------------------------------------------
        # D-4: Required data sources — FAIL_CLOSED; no INSERT without account
        # ----------------------------------------------------------------
        if isinstance(acct_result, Exception):
            failed_sources.append("account_state")
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.DATA_SOURCE_UNAVAILABLE,
                reason=f"Account state unavailable: {acct_result}",
                checks=tuple(checks),
                sizing=None,
                account_snapshot=None,
                failed_sources=tuple(failed_sources),
                elapsed_ms=elapsed_ms,
            )
            return decision, [
                DataSourceUnavailable(
                    signal_id=request.signal_id,
                    failed_source="account_state",
                    failure_type="redis_error",
                    evaluated_at=request.evaluated_at,
                )
            ]

        if isinstance(port_result, Exception):
            failed_sources.append("portfolio_state")
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.DATA_SOURCE_UNAVAILABLE,
                reason=f"Portfolio state unavailable: {port_result}",
                checks=tuple(checks),
                sizing=None,
                account_snapshot=acct_result,
                failed_sources=tuple(failed_sources),
                elapsed_ms=elapsed_ms,
            )
            return decision, [
                DataSourceUnavailable(
                    signal_id=request.signal_id,
                    failed_source="portfolio_state",
                    failure_type="redis_error",
                    evaluated_at=request.evaluated_at,
                )
            ]

        if isinstance(grad_result, Exception):
            failed_sources.append("graduated_response_state")
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.DATA_SOURCE_UNAVAILABLE,
                reason=f"Graduated response state unavailable: {grad_result}",
                checks=tuple(checks),
                sizing=None,
                account_snapshot=acct_result,
                failed_sources=tuple(failed_sources),
                elapsed_ms=elapsed_ms,
            )
            return decision, [
                DataSourceUnavailable(
                    signal_id=request.signal_id,
                    failed_source="graduated_response_state",
                    failure_type="redis_error",
                    evaluated_at=request.evaluated_at,
                )
            ]

        if isinstance(margin_result, Exception):
            failed_sources.append("margin_service")
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.MARGIN_DATA_UNAVAILABLE,
                reason=f"Margin service unavailable: {margin_result}",
                checks=tuple(checks),
                sizing=None,
                account_snapshot=acct_result,
                failed_sources=tuple(failed_sources),
                elapsed_ms=elapsed_ms,
            )
            return decision, [
                DataSourceUnavailable(
                    signal_id=request.signal_id,
                    failed_source="margin_service",
                    failure_type="redis_error",
                    evaluated_at=request.evaluated_at,
                )
            ]

        # Correlation: CONSERVATIVE_DEFAULT (empty dict → ρ=1.0 in check)
        corr_matrix: dict[str, dict[str, float]] = (
            {} if isinstance(corr_result, Exception) else corr_result
        )

        # Signal stats: graceful fallback (None → PositionSizer uses fallback fraction)
        from core.domain.interfaces.i_signal_performance_repository import KellySizingStats
        stats: KellySizingStats | None = (
            None if isinstance(stats_result, Exception) else stats_result
        )

        account = acct_result
        portfolio = port_result
        grad = grad_result
        margin_required: Decimal = margin_result

        # ----------------------------------------------------------------
        # Checks 2–17 (existing) + 18-21 (Phase 22: exposure/concentration)
        # ----------------------------------------------------------------
        current_vix: float = getattr(account, "current_vix", 0.0)
        total_capital_f = float(account.session_capital)

        # Compute symbol/sector/strategy notionals from portfolio positions for checks 18-21
        symbol_notional: float = 0.0
        sector_notional: float = 0.0
        strategy_notional: float = 0.0
        position_notionals: list[float] = []
        try:
            for pos in getattr(portfolio, "positions", []):
                n = float(getattr(pos, "notional", 0.0))
                position_notionals.append(n)
                if str(getattr(pos, "underlying", "")) == str(request.underlying):
                    symbol_notional += n
                if str(getattr(pos, "sector", "")) == str(getattr(request, "sector", "")):
                    sector_notional += n
                if str(getattr(pos, "strategy_type", "")) == str(getattr(request, "strategy_type", "")):
                    strategy_notional += n
        except Exception:
            pass

        check_results_2_11 = [
            check_daily_loss(account, self._config),
            check_weekly_loss(account, self._config),
            check_monthly_loss(account, self._config),
            check_volatility_block(current_vix, self._config),
            check_drawdown(account, self._config),
            check_open_positions(portfolio, self._config),
            check_symbol_concentration(portfolio, request, self._config),
            check_capital_concentration(portfolio, request, account, self._config),
            check_net_delta(portfolio, request, self._config),
            check_correlation(portfolio, request, corr_matrix, self._config),
            check_margin(account, margin_required, self._config),
            check_risk_reward(request, self._config),
            # Phase 22 — Advanced Exposure & Concentration
            check_symbol_exposure(symbol_notional, total_capital_f, self._config),
            check_sector_exposure(sector_notional, total_capital_f, self._config),
            check_strategy_exposure(strategy_notional, total_capital_f, self._config),
            check_concentration(position_notionals, total_capital_f, self._config),
        ]

        for result in check_results_2_11:
            checks.append(result)
            if result.is_hard_failure:  # D-5
                code = _CHECK_TO_REJECTION_CODE.get(
                    result.check_name, RiskRejectionCode.DATA_SOURCE_UNAVAILABLE
                )
                decision = _build_rejected_decision(
                    request=request,
                    code=code,
                    reason=result.message,
                    checks=tuple(checks),
                    sizing=None,
                    account_snapshot=account,
                    failed_sources=tuple(failed_sources),
                    elapsed_ms=elapsed_ms,
                )
                decision = await self._try_insert(decision)
                return decision, [
                    RiskRejected(
                        signal_id=request.signal_id,
                        failed_check=code.value,
                        reason=result.message,
                        checks_passed_count=sum(1 for c in checks if c.passed),
                    )
                ]

        # ----------------------------------------------------------------
        # Check 12 — Position size (requires SizingResult)
        # ----------------------------------------------------------------
        win_rate, win_loss_ratio, sample_count, loss_count = _extract_kelly_params(
            stats, self._config
        )
        sizing = PositionSizer.compute(
            request=request,
            account=account,
            win_rate=win_rate,
            win_loss_ratio=win_loss_ratio,
            sample_count=sample_count,
            loss_count=loss_count,
            config=self._config,
        )

        size_check = check_position_size(sizing)
        checks.append(size_check)
        if size_check.is_hard_failure:
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.POSITION_SIZE_ZERO,
                reason=size_check.message,
                checks=tuple(checks),
                sizing=sizing,
                account_snapshot=account,
                failed_sources=tuple(failed_sources),
                elapsed_ms=elapsed_ms,
            )
            decision = await self._try_insert(decision)
            return decision, [
                RiskRejected(
                    signal_id=request.signal_id,
                    failed_check=RiskRejectionCode.POSITION_SIZE_ZERO.value,
                    reason=size_check.message,
                    checks_passed_count=sum(1 for c in checks if c.passed),
                )
            ]

        # ----------------------------------------------------------------
        # Checks 13–15 (OrderRate, ThetaDecay warn-only, VegaExposure)
        # ----------------------------------------------------------------
        checks_13_15 = [
            check_order_rate(portfolio, self._config),
            check_theta_decay(portfolio, self._config),  # is_warning=True always
            check_vega_exposure(portfolio, request, account, self._config),
        ]

        for result in checks_13_15:
            checks.append(result)
            if result.is_hard_failure:  # D-5: theta_decay never triggers
                code = _CHECK_TO_REJECTION_CODE.get(
                    result.check_name, RiskRejectionCode.DATA_SOURCE_UNAVAILABLE
                )
                decision = _build_rejected_decision(
                    request=request,
                    code=code,
                    reason=result.message,
                    checks=tuple(checks),
                    sizing=sizing,
                    account_snapshot=account,
                    failed_sources=tuple(failed_sources),
                    elapsed_ms=elapsed_ms,
                )
                decision = await self._try_insert(decision)
                return decision, [
                    RiskRejected(
                        signal_id=request.signal_id,
                        failed_check=code.value,
                        reason=result.message,
                        checks_passed_count=sum(1 for c in checks if c.passed),
                    )
                ]

        # ----------------------------------------------------------------
        # All checks passed — build approved decision
        # ----------------------------------------------------------------
        size_reduction_pct = 50.0 if grad.position_size_multiplier == 0.5 else 0.0

        decision = RiskDecision(
            signal_id=request.signal_id,
            approved=True,
            rejection_code=None,
            rejection_reason=None,
            position_size_lots=sizing.lots,
            size_reduction_pct=size_reduction_pct,
            checks=tuple(checks),
            sizing=sizing,
            account_snapshot=account,
            failed_data_sources=tuple(failed_sources),
            risk_decision_id=None,
            evaluated_at=request.evaluated_at,
        )

        # D-2: INSERT inside lock before returning
        insert_timeout = self._config.db.risk_decisions_insert_timeout_seconds
        try:
            pk = await asyncio.wait_for(
                self._risk_decision_repo.insert(decision, insert_timeout),
                timeout=insert_timeout,
            )
            decision = dataclasses.replace(decision, risk_decision_id=pk)
        except TimeoutError:
            _log.critical(
                "risk_decision_insert_timeout signal_id=%s", request.signal_id
            )
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.AUDIT_PERSISTENCE_TIMEOUT,
                reason=(
                    "Risk decision INSERT timed out — "
                    "persistence-first invariant prevents approval"
                ),
                checks=tuple(checks),
                sizing=sizing,
                account_snapshot=account,
                failed_sources=tuple(failed_sources),
                elapsed_ms=elapsed_ms,
            )
            return decision, []
        except RiskDecisionPersistenceError:
            _log.critical(
                "risk_decision_insert_failed signal_id=%s", request.signal_id, exc_info=True
            )
            decision = _build_rejected_decision(
                request=request,
                code=RiskRejectionCode.AUDIT_PERSISTENCE_FAILURE,
                reason=(
                    "Risk decision INSERT failed — "
                    "persistence-first invariant prevents approval"
                ),
                checks=tuple(checks),
                sizing=sizing,
                account_snapshot=account,
                failed_sources=tuple(failed_sources),
                elapsed_ms=elapsed_ms,
            )
            return decision, []

        approved_event = RiskApproved(
            signal_id=request.signal_id,
            risk_decision_id=pk,
            approved_lots=sizing.lots,
            position_size_multiplier=grad.position_size_multiplier,
            kelly_fraction_effective=sizing.kelly_fraction_effective,
            sizing_note=sizing.sizing_note,
        )
        return decision, [approved_event]

    async def _try_insert(self, decision: RiskDecision) -> RiskDecision:
        """Try to INSERT a rejected decision (best-effort). Returns unchanged on failure."""
        if decision.account_snapshot is None:
            return decision  # NOT NULL constraint — cannot insert without account data

        insert_timeout = self._config.db.risk_decisions_insert_timeout_seconds
        try:
            pk = await asyncio.wait_for(
                self._risk_decision_repo.insert(decision, insert_timeout),
                timeout=insert_timeout,
            )
            return dataclasses.replace(decision, risk_decision_id=pk)
        except Exception:
            _log.warning(
                "rejected_decision_insert_failed signal_id=%s", decision.signal_id, exc_info=True
            )
            return decision

    async def _publish_with_retry(self, event: DomainEvent) -> None:
        """3-tier delivery: direct → 3 retries → LPUSH pending queue → CRITICAL log."""
        for delay in _RETRY_DELAYS_SECONDS:
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                await self._event_bus.publish(event)
                return
            except Exception:
                _log.warning("event_publish_retry event_type=%s", event.event_type, exc_info=True)

        # Tier 3: push to Redis pending delivery queue
        try:
            import json as _json

            payload = _json.dumps(
                {
                    "event_type": event.event_type,
                    "event_id": str(event.event_id),
                    "occurred_at": event.occurred_at.isoformat(),
                }
            )
            await self._redis.lpush(_PENDING_DELIVERY_KEY, payload)  # type: ignore[attr-defined]
        except Exception:
            _log.debug("redis_lpush_failed event_type=%s", event.event_type)

        _log.critical(
            "event_publish_failed_all_retries event_type=%s event_id=%s",
            event.event_type,
            event.event_id,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_rejected_decision(
    *,
    request: RiskRequest,
    code: RiskRejectionCode,
    reason: str,
    checks: tuple[RiskCheckResult, ...],
    sizing: SizingResult | None,
    account_snapshot: object,
    failed_sources: tuple[str, ...],
    elapsed_ms: int,  # noqa: ARG001 — reserved for future evaluation_duration_ms field
) -> RiskDecision:
    return RiskDecision(
        signal_id=request.signal_id,
        approved=False,
        rejection_code=code,
        rejection_reason=reason,
        position_size_lots=None,
        size_reduction_pct=0.0,
        checks=checks,
        sizing=sizing,
        account_snapshot=account_snapshot,
        failed_data_sources=failed_sources,
        risk_decision_id=None,
        evaluated_at=request.evaluated_at,
    )


def _extract_kelly_params(
    stats: object,  # KellySizingStats | None
    config: RiskConfig,
) -> tuple[float, float, int, int]:
    """Extract (win_rate, win_loss_ratio, sample_count, loss_count) from stats.

    Returns conservative fallback values when stats is None or win_loss_ratio is None.
    """
    from core.domain.interfaces.i_signal_performance_repository import KellySizingStats

    if stats is None or not isinstance(stats, KellySizingStats):
        return (0.5, 1.0, 0, 0)

    win_rate = stats.win_rate
    win_loss_ratio = stats.win_loss_ratio if stats.win_loss_ratio is not None else 1.0
    return (win_rate, win_loss_ratio, stats.sample_count, stats.loss_count)
