"""Unit tests for PortfolioMonitorService."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.portfolio_monitor_service import PortfolioMonitorService
from core.domain.events.risk_events import (
    DailyLossLimitBreached,
    DrawdownLimitBreached,
    GraduatedResponseActivated,
    HighWaterMarkUpdated,
    PaperModeActivated,
    WeeklyLossLimitBreached,
)
from core.domain.risk.account_state import AccountState
from core.domain.risk.graduated_response_state import GraduatedResponseState


def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.daily_loss.graduated_response.reduce_size_at_pct = 50.0
    cfg.daily_loss.graduated_response.paper_mode_at_pct = 75.0
    cfg.daily_loss.graduated_response.kill_switch_at_pct = 100.0
    cfg.daily_loss.limit_pct = 2.0
    cfg.daily_loss.limit_abs = 10000
    cfg.weekly_loss.limit_pct = 5.0
    cfg.drawdown.max_drawdown_pct = 10.0
    cfg.margin.utilization_limit_pct = 80.0
    return cfg


def _make_account(
    daily_loss_consumed_pct: float = 0.0,
    weekly_loss_consumed_pct: float = 0.0,
    drawdown_from_hwm_pct: float = 0.0,
    margin_utilization_pct: float = 0.0,
    account_capital: float = 500000.0,
) -> AccountState:
    return AccountState(
        account_capital=Decimal(str(account_capital)),
        session_capital=Decimal("500000"),
        available_margin=Decimal("400000"),
        used_margin=Decimal("100000"),
        margin_utilization_pct=margin_utilization_pct,
        daily_pnl=Decimal("0"),
        daily_loss_consumed_pct=daily_loss_consumed_pct,
        weekly_pnl=Decimal("0"),
        weekly_loss_consumed_pct=weekly_loss_consumed_pct,
        drawdown_from_hwm_pct=drawdown_from_hwm_pct,
        open_positions_count=0,
        position_size_multiplier=1.0,
        trading_mode="LIVE",
        captured_at=datetime.now(UTC),
    )


def _normal_grad() -> GraduatedResponseState:
    return GraduatedResponseState(
        state="NORMAL", position_size_multiplier=1.0, activated_at=None, reason=None
    )


@pytest.fixture
def account_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_current.return_value = _make_account()
    return repo


@pytest.fixture
def portfolio_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_graduated_response.return_value = _normal_grad()
    return repo


@pytest.fixture
def ks_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def event_bus() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def redis_mock() -> AsyncMock:
    m = AsyncMock()
    m.get.return_value = None
    return m


@pytest.fixture
def service(
    account_repo: AsyncMock,
    portfolio_repo: AsyncMock,
    ks_service: AsyncMock,
    event_bus: AsyncMock,
    redis_mock: AsyncMock,
) -> PortfolioMonitorService:
    return PortfolioMonitorService(
        account_state_repo=account_repo,
        portfolio_state_repo=portfolio_repo,
        kill_switch_service=ks_service,
        event_bus=event_bus,
        redis_client=redis_mock,
        config=_make_config(),
    )


class TestHWMUpdate:
    async def test_sets_hwm_when_no_prior_hwm(
        self, service: PortfolioMonitorService, redis_mock: AsyncMock
    ) -> None:
        redis_mock.get.return_value = None
        await service._maybe_update_hwm(500000.0)
        redis_mock.set.assert_called_once_with("risk:hwm", "500000.0")

    async def test_updates_hwm_when_new_high(
        self, service: PortfolioMonitorService, redis_mock: AsyncMock, event_bus: AsyncMock
    ) -> None:
        redis_mock.get.return_value = "450000"
        await service._maybe_update_hwm(500000.0)
        redis_mock.set.assert_called_once()
        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, HighWaterMarkUpdated)
        assert event.new_hwm == pytest.approx(500000.0)
        assert event.previous_hwm == pytest.approx(450000.0)

    async def test_does_not_update_hwm_when_lower(
        self, service: PortfolioMonitorService, redis_mock: AsyncMock
    ) -> None:
        redis_mock.get.return_value = "600000"
        await service._maybe_update_hwm(500000.0)
        redis_mock.set.assert_not_called()

    async def test_no_event_on_first_hwm_write(
        self, service: PortfolioMonitorService, redis_mock: AsyncMock, event_bus: AsyncMock
    ) -> None:
        redis_mock.get.return_value = None
        await service._maybe_update_hwm(500000.0)
        event_bus.publish.assert_not_called()


class TestGraduatedResponseTransitions:
    async def test_no_transition_when_normal(
        self,
        service: PortfolioMonitorService,
        portfolio_repo: AsyncMock,
    ) -> None:
        grad = _normal_grad()
        await service._apply_graduated_response(30.0, grad)
        portfolio_repo.set_graduated_response.assert_not_called()

    async def test_transitions_to_reduced_at_50pct(
        self,
        service: PortfolioMonitorService,
        portfolio_repo: AsyncMock,
        event_bus: AsyncMock,
    ) -> None:
        grad = _normal_grad()
        await service._apply_graduated_response(55.0, grad)
        portfolio_repo.set_graduated_response.assert_called_once()
        new_state = portfolio_repo.set_graduated_response.call_args[0][0]
        assert new_state.state == "REDUCED"
        event_bus.publish.assert_called()

    async def test_transitions_to_paper_at_75pct(
        self,
        service: PortfolioMonitorService,
        portfolio_repo: AsyncMock,
        event_bus: AsyncMock,
    ) -> None:
        grad = GraduatedResponseState(
            state="REDUCED", position_size_multiplier=0.5,
            activated_at=datetime.now(UTC), reason="loss"
        )
        await service._apply_graduated_response(80.0, grad)
        new_state = portfolio_repo.set_graduated_response.call_args[0][0]
        assert new_state.state == "PAPER"
        published_types = [type(c[0][0]) for c in event_bus.publish.call_args_list]
        assert GraduatedResponseActivated in published_types
        assert PaperModeActivated in published_types

    async def test_activates_kill_switch_at_100pct(
        self,
        service: PortfolioMonitorService,
        portfolio_repo: AsyncMock,
        ks_service: AsyncMock,
    ) -> None:
        grad = GraduatedResponseState(
            state="PAPER", position_size_multiplier=0.0,
            activated_at=datetime.now(UTC), reason="loss"
        )
        await service._apply_graduated_response(100.0, grad)
        ks_service.activate.assert_called_once()
        call_kwargs = ks_service.activate.call_args[1]
        assert call_kwargs["trigger_source"] == "daily_loss_100pct"

    async def test_no_transition_when_already_at_target(
        self,
        service: PortfolioMonitorService,
        portfolio_repo: AsyncMock,
    ) -> None:
        grad = GraduatedResponseState(
            state="REDUCED", position_size_multiplier=0.5,
            activated_at=datetime.now(UTC), reason="loss"
        )
        await service._apply_graduated_response(55.0, grad)
        portfolio_repo.set_graduated_response.assert_not_called()


class TestRunCycle:
    async def test_cycle_skips_on_account_unavailable(
        self,
        service: PortfolioMonitorService,
        account_repo: AsyncMock,
        event_bus: AsyncMock,
    ) -> None:
        from core.domain.exceptions.risk import DataSourceUnavailableError
        account_repo.get_current.side_effect = DataSourceUnavailableError("account_state", "down")
        await service._run_cycle()
        event_bus.publish.assert_not_called()

    async def test_drawdown_limit_triggers_kill_switch(
        self,
        service: PortfolioMonitorService,
        account_repo: AsyncMock,
        ks_service: AsyncMock,
        event_bus: AsyncMock,
    ) -> None:
        account_repo.get_current.return_value = _make_account(drawdown_from_hwm_pct=12.0)
        await service._run_cycle()
        ks_service.activate.assert_called()
        published_types = [type(c[0][0]) for c in event_bus.publish.call_args_list]
        assert DrawdownLimitBreached in published_types

    async def test_weekly_loss_publishes_event(
        self,
        service: PortfolioMonitorService,
        account_repo: AsyncMock,
        event_bus: AsyncMock,
    ) -> None:
        account_repo.get_current.return_value = _make_account(weekly_loss_consumed_pct=100.5)
        await service._run_cycle()
        published_types = [type(c[0][0]) for c in event_bus.publish.call_args_list]
        assert WeeklyLossLimitBreached in published_types

    async def test_margin_alert_publishes_event(
        self,
        service: PortfolioMonitorService,
        account_repo: AsyncMock,
        event_bus: AsyncMock,
    ) -> None:
        from core.domain.events.risk_events import MarginAlertBreached
        account_repo.get_current.return_value = _make_account(margin_utilization_pct=85.0)
        await service._run_cycle()
        published_types = [type(c[0][0]) for c in event_bus.publish.call_args_list]
        assert MarginAlertBreached in published_types
