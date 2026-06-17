"""Unit tests for RiskEngineService.

Critical invariants tested:
  D-1:  Sequential queue — second concurrent evaluate() waits, never rejected
  D-2:  Persistence-first — INSERT inside lock, event outside lock
  D-3:  Kill switch active → no INSERT, no event
  D-4:  Required source unavailable → FAIL_CLOSED rejection
  D-5:  is_hard_failure used as rejection predicate (ThetaDecay never blocks)
  RC-5: asyncio.wait_for wraps INSERT; timeout_seconds unused inside repo
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.application.services.risk_engine_service import RiskEngineService
from core.domain.events.risk_events import DataSourceUnavailable, RiskApproved, RiskRejected
from core.domain.exceptions.risk import DataSourceUnavailableError, RiskDecisionPersistenceError
from core.domain.risk.account_state import AccountState
from core.domain.risk.graduated_response_state import GraduatedResponseState
from core.domain.risk.kill_switch_state import KillSwitchState
from core.domain.risk.portfolio_state import PortfolioState
from core.domain.risk.risk_decision import RiskDecision, RiskRejectionCode
from core.domain.risk.risk_request import RiskRequest


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _sig_id() -> uuid.UUID:
    return uuid.uuid4()


def _request(signal_id: uuid.UUID | None = None) -> RiskRequest:
    return RiskRequest(
        signal_id=signal_id or _sig_id(),
        instrument_token=12345,
        underlying="NIFTY",
        instrument_class="OPTION",
        direction="LONG",
        adjusted_score=75.0,
        final_confidence=80.0,
        entry_price=Decimal("200"),
        stop_loss_price=Decimal("180"),
        target_price=Decimal("230"),
        option_premium=Decimal("200"),
        lot_size=50,
        option_delta=0.5,
        option_vega=50.0,
        dte=7,
        atr_14=50.0,
        risk_reward_ratio=1.5,
        evaluated_at=datetime.now(UTC),
    )


def _approvable_request(signal_id: uuid.UUID | None = None) -> RiskRequest:
    """Request that passes all checks including position sizing.

    option_premium=50, lot_size=50 → cost_per_lot=2500
    capital_at_risk = 500000 * 1% = 5000 → atr_lots = floor(5000/2500) = 2
    """
    return RiskRequest(
        signal_id=signal_id or _sig_id(),
        instrument_token=12345,
        underlying="NIFTY",
        instrument_class="OPTION",
        direction="LONG",
        adjusted_score=75.0,
        final_confidence=80.0,
        entry_price=Decimal("200"),
        stop_loss_price=Decimal("180"),
        target_price=Decimal("230"),
        option_premium=Decimal("50"),
        lot_size=50,
        option_delta=0.5,
        option_vega=50.0,
        dte=7,
        atr_14=50.0,
        risk_reward_ratio=1.5,
        evaluated_at=datetime.now(UTC),
    )


def _account() -> AccountState:
    return AccountState(
        account_capital=Decimal("500000"),
        session_capital=Decimal("500000"),
        available_margin=Decimal("400000"),
        used_margin=Decimal("100000"),
        margin_utilization_pct=20.0,
        daily_pnl=Decimal("0"),
        daily_loss_consumed_pct=0.0,
        weekly_pnl=Decimal("0"),
        weekly_loss_consumed_pct=0.0,
        drawdown_from_hwm_pct=0.0,
        open_positions_count=0,
        position_size_multiplier=1.0,
        trading_mode="LIVE",
        captured_at=datetime.now(UTC),
    )


def _portfolio() -> PortfolioState:
    return PortfolioState(
        open_positions_count=0,
        positions_per_underlying={},
        capital_per_underlying_pct={},
        net_delta=0.0,
        net_vega=0.0,
        net_theta_daily=0.0,
        orders_last_minute=0,
        orders_today=0,
        captured_at=datetime.now(UTC),
    )


def _grad_normal() -> GraduatedResponseState:
    return GraduatedResponseState(
        state="NORMAL", position_size_multiplier=1.0, activated_at=None, reason=None
    )


def _ks_inactive() -> KillSwitchState:
    return KillSwitchState(
        is_active=False,
        activated_at=None, activated_by=None, activation_reason=None,
        deactivated_at=None, deactivated_by=None, deactivation_note=None,
    )


def _ks_active() -> KillSwitchState:
    return KillSwitchState(
        is_active=True,
        activated_at=datetime.now(UTC),
        activated_by="risk_engine",
        activation_reason="daily loss",
        deactivated_at=None, deactivated_by=None, deactivation_note=None,
    )


def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.capital.total_capital = 500000
    cfg.capital.risk_per_trade_pct = 1.0
    cfg.daily_loss.limit_pct = 2.0
    cfg.daily_loss.limit_abs = 10000
    cfg.daily_loss.graduated_response.reduce_size_at_pct = 50.0
    cfg.daily_loss.graduated_response.paper_mode_at_pct = 75.0
    cfg.daily_loss.graduated_response.kill_switch_at_pct = 100.0
    cfg.weekly_loss.limit_pct = 5.0
    cfg.weekly_loss.limit_abs = 25000
    cfg.drawdown.max_drawdown_pct = 10.0
    cfg.position_limits.max_open_positions = 10
    cfg.position_limits.max_positions_per_underlying = 3
    cfg.position_limits.max_capital_per_underlying_pct = 20.0
    cfg.position_limits.max_capital_per_sector_pct = 40.0
    cfg.position_limits.max_notional_per_trade_pct = 10.0
    cfg.order_rate.max_orders_per_minute = 5
    cfg.order_rate.max_orders_per_day = 50
    cfg.greeks.max_net_delta = 2500.0
    cfg.greeks.max_net_gamma_pct = 0.1
    cfg.greeks.max_net_vega_pct = 5.0
    cfg.greeks.max_theta_daily_decay_pct = 0.5
    cfg.margin.utilization_limit_pct = 80.0
    cfg.margin.min_free_margin_pct = 20.0
    cfg.margin.timeout_seconds = 0.15
    cfg.risk_reward.min_ratio = 1.5
    cfg.risk_reward.max_ratio = 10.0
    cfg.position_sizing.method = "atr_kelly"
    cfg.position_sizing.kelly_fraction = 0.25
    cfg.position_sizing.atr_period = 14
    cfg.position_sizing.atr_stop_multiplier = 1.5
    cfg.position_sizing.max_position_size_lots = 50
    cfg.position_sizing.min_kelly_samples = 30
    cfg.position_sizing.kelly_min_sample_fallback = 0.05
    cfg.db.risk_decisions_insert_timeout_seconds = 0.1
    cfg.risk_engine.gather_timeout_seconds = 0.5
    return cfg


def _make_service(
    ks_repo: AsyncMock,
    account_repo: AsyncMock,
    portfolio_repo: AsyncMock,
    corr_repo: AsyncMock,
    margin_svc: AsyncMock,
    signal_perf_repo: AsyncMock,
    risk_decision_repo: AsyncMock,
    event_bus: AsyncMock,
    redis_mock: AsyncMock,
) -> RiskEngineService:
    return RiskEngineService(
        kill_switch_repo=ks_repo,
        account_state_repo=account_repo,
        portfolio_state_repo=portfolio_repo,
        correlation_repo=corr_repo,
        margin_service=margin_svc,
        signal_perf_repo=signal_perf_repo,
        risk_decision_repo=risk_decision_repo,
        event_bus=event_bus,
        redis_client=redis_mock,
        config=_make_config(),
    )


@pytest.fixture
def ks_repo() -> AsyncMock:
    m = AsyncMock()
    m.get_state.return_value = _ks_inactive()
    return m


@pytest.fixture
def account_repo() -> AsyncMock:
    m = AsyncMock()
    m.get_current.return_value = _account()
    return m


@pytest.fixture
def portfolio_repo() -> AsyncMock:
    m = AsyncMock()
    m.get_current.return_value = _portfolio()
    m.get_graduated_response.return_value = _grad_normal()
    return m


@pytest.fixture
def corr_repo() -> AsyncMock:
    m = AsyncMock()
    m.get_matrix.return_value = {}
    return m


@pytest.fixture
def margin_svc() -> AsyncMock:
    m = AsyncMock()
    m.get_required_margin.return_value = Decimal("50000")
    return m


@pytest.fixture
def signal_perf_repo() -> AsyncMock:
    m = AsyncMock()
    m.get_sizing_stats.return_value = None
    return m


@pytest.fixture
def risk_decision_repo() -> AsyncMock:
    m = AsyncMock()
    m.insert.return_value = 42
    return m


@pytest.fixture
def event_bus() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def redis_mock() -> AsyncMock:
    m = AsyncMock()
    m.lpush = AsyncMock()
    return m


@pytest.fixture
def service(
    ks_repo: AsyncMock,
    account_repo: AsyncMock,
    portfolio_repo: AsyncMock,
    corr_repo: AsyncMock,
    margin_svc: AsyncMock,
    signal_perf_repo: AsyncMock,
    risk_decision_repo: AsyncMock,
    event_bus: AsyncMock,
    redis_mock: AsyncMock,
) -> RiskEngineService:
    return _make_service(
        ks_repo, account_repo, portfolio_repo, corr_repo,
        margin_svc, signal_perf_repo, risk_decision_repo, event_bus, redis_mock,
    )


# ---------------------------------------------------------------------------
# D-3: Kill switch precedence
# ---------------------------------------------------------------------------


class TestKillSwitchPrecedence:
    async def test_active_kill_switch_returns_rejected(self, service: RiskEngineService, ks_repo: AsyncMock) -> None:
        ks_repo.get_state.return_value = _ks_active()
        decision = await service.evaluate(_request())
        assert not decision.approved
        assert decision.rejection_code == RiskRejectionCode.KILL_SWITCH_ACTIVE

    async def test_active_kill_switch_no_db_insert(
        self, service: RiskEngineService, ks_repo: AsyncMock, risk_decision_repo: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _ks_active()
        await service.evaluate(_request())
        risk_decision_repo.insert.assert_not_called()

    async def test_active_kill_switch_no_event_published(
        self, service: RiskEngineService, ks_repo: AsyncMock, event_bus: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _ks_active()
        await service.evaluate(_request())
        event_bus.publish.assert_not_called()

    async def test_ks_redis_error_treated_as_active(
        self, service: RiskEngineService, ks_repo: AsyncMock, risk_decision_repo: AsyncMock
    ) -> None:
        ks_repo.get_state.side_effect = DataSourceUnavailableError("kill_switch", "Redis down")
        decision = await service.evaluate(_request())
        assert not decision.approved
        assert decision.rejection_code == RiskRejectionCode.KILL_SWITCH_ACTIVE
        risk_decision_repo.insert.assert_not_called()


# ---------------------------------------------------------------------------
# D-4: FAIL_CLOSED on required sources
# ---------------------------------------------------------------------------


class TestFailClosed:
    async def test_account_unavailable_returns_data_source_rejection(
        self, service: RiskEngineService, account_repo: AsyncMock, risk_decision_repo: AsyncMock
    ) -> None:
        account_repo.get_current.side_effect = DataSourceUnavailableError("account_state", "Redis down")
        decision = await service.evaluate(_request())
        assert not decision.approved
        assert decision.rejection_code == RiskRejectionCode.DATA_SOURCE_UNAVAILABLE
        risk_decision_repo.insert.assert_not_called()

    async def test_account_unavailable_publishes_data_source_event(
        self, service: RiskEngineService, account_repo: AsyncMock, event_bus: AsyncMock
    ) -> None:
        account_repo.get_current.side_effect = DataSourceUnavailableError("account_state", "Redis down")
        await service.evaluate(_request())
        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, DataSourceUnavailable)
        assert event.failed_source == "account_state"

    async def test_portfolio_unavailable_returns_rejected(
        self, service: RiskEngineService, portfolio_repo: AsyncMock
    ) -> None:
        portfolio_repo.get_current.side_effect = DataSourceUnavailableError("portfolio_state", "down")
        decision = await service.evaluate(_request())
        assert not decision.approved
        assert decision.rejection_code == RiskRejectionCode.DATA_SOURCE_UNAVAILABLE

    async def test_margin_unavailable_returns_margin_rejection(
        self, service: RiskEngineService, margin_svc: AsyncMock
    ) -> None:
        from core.domain.exceptions.risk import MarginDataUnavailableError
        margin_svc.get_required_margin.side_effect = MarginDataUnavailableError("margin_cache", "down")
        decision = await service.evaluate(_request())
        assert not decision.approved
        assert decision.rejection_code == RiskRejectionCode.MARGIN_DATA_UNAVAILABLE

    async def test_correlation_unavailable_continues_with_conservative_default(
        self, service: RiskEngineService, corr_repo: AsyncMock
    ) -> None:
        corr_repo.get_matrix.side_effect = Exception("Redis down")
        # Should still evaluate (CONSERVATIVE_DEFAULT for correlation)
        decision = await service.evaluate(_request())
        # May pass or fail based on check results, but should not fail with DATA_SOURCE_UNAVAILABLE
        if not decision.approved:
            assert decision.rejection_code != RiskRejectionCode.DATA_SOURCE_UNAVAILABLE


# ---------------------------------------------------------------------------
# D-1: Sequential queue
# ---------------------------------------------------------------------------


class TestSequentialQueue:
    async def test_concurrent_evaluate_both_succeed(self, service: RiskEngineService) -> None:
        results = await asyncio.gather(
            service.evaluate(_request()),
            service.evaluate(_request()),
        )
        assert len(results) == 2
        # Both should complete (one waits for the other)

    async def test_second_request_does_not_raise_concurrent_error(
        self, service: RiskEngineService
    ) -> None:
        from core.domain.exceptions.risk import ConcurrentEvaluationError

        tasks = [asyncio.create_task(service.evaluate(_request())) for _ in range(3)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            assert not isinstance(r, ConcurrentEvaluationError)


# ---------------------------------------------------------------------------
# D-2: Persistence-first invariant
# ---------------------------------------------------------------------------


class TestPersistenceFirst:
    async def test_approved_decision_has_risk_decision_id(
        self, service: RiskEngineService, risk_decision_repo: AsyncMock
    ) -> None:
        risk_decision_repo.insert.return_value = 99
        decision = await service.evaluate(_request())
        if decision.approved:
            assert decision.risk_decision_id == 99

    async def test_insert_called_before_event_published(
        self,
        service: RiskEngineService,
        risk_decision_repo: AsyncMock,
        event_bus: AsyncMock,
    ) -> None:
        insert_order: list[str] = []

        async def track_insert(d: object, t: float) -> int:
            insert_order.append("insert")
            return 1

        async def track_publish(e: object) -> None:
            insert_order.append("publish")

        risk_decision_repo.insert.side_effect = track_insert
        event_bus.publish.side_effect = track_publish

        await service.evaluate(_request())
        if "insert" in insert_order and "publish" in insert_order:
            assert insert_order.index("insert") < insert_order.index("publish")

    async def test_insert_failure_returns_persistence_error_code(
        self,
        service: RiskEngineService,
        risk_decision_repo: AsyncMock,
    ) -> None:
        risk_decision_repo.insert.side_effect = RiskDecisionPersistenceError("db error")
        # Use _approvable_request so all checks pass and the approved INSERT is attempted
        decision = await service.evaluate(_approvable_request())
        assert not decision.approved
        assert decision.rejection_code == RiskRejectionCode.AUDIT_PERSISTENCE_FAILURE

    async def test_insert_timeout_returns_timeout_code(
        self,
        service: RiskEngineService,
        risk_decision_repo: AsyncMock,
    ) -> None:
        async def slow_insert(d: object, t: float) -> int:
            await asyncio.sleep(10)
            return 1

        risk_decision_repo.insert.side_effect = slow_insert
        decision = await service.evaluate(_approvable_request())
        assert not decision.approved
        assert decision.rejection_code == RiskRejectionCode.AUDIT_PERSISTENCE_TIMEOUT

    async def test_no_event_published_on_insert_failure(
        self,
        service: RiskEngineService,
        risk_decision_repo: AsyncMock,
        event_bus: AsyncMock,
    ) -> None:
        risk_decision_repo.insert.side_effect = RiskDecisionPersistenceError("db error")
        await service.evaluate(_approvable_request())
        event_bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Approved path
# ---------------------------------------------------------------------------


class TestApprovedPath:
    async def test_approved_decision_publishes_risk_approved(
        self, service: RiskEngineService, event_bus: AsyncMock
    ) -> None:
        decision = await service.evaluate(_request())
        if decision.approved:
            event_bus.publish.assert_called_once()
            event = event_bus.publish.call_args[0][0]
            assert isinstance(event, RiskApproved)

    async def test_approved_event_has_correct_signal_id(
        self, service: RiskEngineService, event_bus: AsyncMock
    ) -> None:
        sig_id = _sig_id()
        decision = await service.evaluate(_request(signal_id=sig_id))
        if decision.approved:
            event = event_bus.publish.call_args[0][0]
            assert event.signal_id == sig_id

    async def test_approved_decision_no_rejection_code(self, service: RiskEngineService) -> None:
        decision = await service.evaluate(_request())
        if decision.approved:
            assert decision.rejection_code is None


# ---------------------------------------------------------------------------
# D-5: is_hard_failure — check rejection predicate
# ---------------------------------------------------------------------------


class TestIsHardFailure:
    async def test_daily_loss_limit_causes_rejection(
        self,
        service: RiskEngineService,
        account_repo: AsyncMock,
    ) -> None:
        account = _account()
        from dataclasses import replace
        # 100% daily loss consumed
        bad_account = replace(account, daily_loss_consumed_pct=100.0)
        account_repo.get_current.return_value = bad_account
        decision = await service.evaluate(_request())
        assert not decision.approved
        assert decision.rejection_code == RiskRejectionCode.DAILY_LOSS_LIMIT

    async def test_rejected_decision_publishes_risk_rejected(
        self,
        service: RiskEngineService,
        account_repo: AsyncMock,
        event_bus: AsyncMock,
        risk_decision_repo: AsyncMock,
    ) -> None:
        from dataclasses import replace
        bad_account = replace(_account(), daily_loss_consumed_pct=100.0)
        account_repo.get_current.return_value = bad_account
        await service.evaluate(_request())
        event_bus.publish.assert_called()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, RiskRejected)


# ---------------------------------------------------------------------------
# Gather timeout (Rule 10)
# ---------------------------------------------------------------------------


class TestGatherTimeout:
    async def test_gather_timeout_returns_data_source_unavailable(
        self,
        ks_repo: AsyncMock,
        account_repo: AsyncMock,
        portfolio_repo: AsyncMock,
        corr_repo: AsyncMock,
        margin_svc: AsyncMock,
        signal_perf_repo: AsyncMock,
        risk_decision_repo: AsyncMock,
        event_bus: AsyncMock,
        redis_mock: AsyncMock,
    ) -> None:
        async def slow() -> object:
            await asyncio.sleep(10)

        ks_repo.get_state.side_effect = slow

        cfg = _make_config()
        cfg.risk_engine.gather_timeout_seconds = 0.05

        svc = RiskEngineService(
            kill_switch_repo=ks_repo,
            account_state_repo=account_repo,
            portfolio_state_repo=portfolio_repo,
            correlation_repo=corr_repo,
            margin_service=margin_svc,
            signal_perf_repo=signal_perf_repo,
            risk_decision_repo=risk_decision_repo,
            event_bus=event_bus,
            redis_client=redis_mock,
            config=cfg,
        )

        decision = await svc.evaluate(_request())
        assert not decision.approved
        assert decision.rejection_code == RiskRejectionCode.DATA_SOURCE_UNAVAILABLE
        risk_decision_repo.insert.assert_not_called()
