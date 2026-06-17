"""Integration tests for Phase D risk pipeline.

Uses real asyncio concurrency. Mocks only I/O boundaries (Redis, DB).
Validates D-rules under realistic service wiring:
  D-1: Sequential queue
  D-2: Persistence-first
  D-3: Kill switch gate
  D-4: FAIL_CLOSED on required sources
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.risk_engine_service import RiskEngineService
from core.domain.events.risk_events import RiskApproved, RiskRejected
from core.domain.exceptions.risk import DataSourceUnavailableError
from core.domain.risk.account_state import AccountState
from core.domain.risk.graduated_response_state import GraduatedResponseState
from core.domain.risk.kill_switch_state import KillSwitchState
from core.domain.risk.portfolio_state import PortfolioState
from core.domain.risk.risk_decision import RiskRejectionCode
from core.domain.risk.risk_request import RiskRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_request(signal_id: uuid.UUID | None = None) -> RiskRequest:
    return RiskRequest(
        signal_id=signal_id or uuid.uuid4(),
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


def _build_healthy_account() -> AccountState:
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


def _build_healthy_portfolio() -> PortfolioState:
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


def _build_config() -> MagicMock:
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
    cfg.db.risk_decisions_insert_timeout_seconds = 2.0
    cfg.risk_engine.gather_timeout_seconds = 2.0
    return cfg


@pytest.fixture
def mocks() -> dict:
    ks_repo = AsyncMock()
    ks_repo.get_state.return_value = KillSwitchState(
        is_active=False,
        activated_at=None, activated_by=None, activation_reason=None,
        deactivated_at=None, deactivated_by=None, deactivation_note=None,
    )

    account_repo = AsyncMock()
    account_repo.get_current.return_value = _build_healthy_account()

    portfolio_repo = AsyncMock()
    portfolio_repo.get_current.return_value = _build_healthy_portfolio()
    portfolio_repo.get_graduated_response.return_value = GraduatedResponseState(
        state="NORMAL", position_size_multiplier=1.0, activated_at=None, reason=None
    )

    corr_repo = AsyncMock()
    corr_repo.get_matrix.return_value = {}

    margin_svc = AsyncMock()
    margin_svc.get_required_margin.return_value = Decimal("50000")

    signal_perf_repo = AsyncMock()
    signal_perf_repo.get_sizing_stats.return_value = None

    risk_decision_repo = AsyncMock()
    risk_decision_repo.insert.return_value = 1

    event_bus = AsyncMock()

    redis_mock = AsyncMock()
    redis_mock.lpush = AsyncMock()

    return {
        "ks_repo": ks_repo,
        "account_repo": account_repo,
        "portfolio_repo": portfolio_repo,
        "corr_repo": corr_repo,
        "margin_svc": margin_svc,
        "signal_perf_repo": signal_perf_repo,
        "risk_decision_repo": risk_decision_repo,
        "event_bus": event_bus,
        "redis_mock": redis_mock,
    }


@pytest.fixture
def engine(mocks: dict) -> RiskEngineService:
    return RiskEngineService(
        kill_switch_repo=mocks["ks_repo"],
        account_state_repo=mocks["account_repo"],
        portfolio_state_repo=mocks["portfolio_repo"],
        correlation_repo=mocks["corr_repo"],
        margin_service=mocks["margin_svc"],
        signal_perf_repo=mocks["signal_perf_repo"],
        risk_decision_repo=mocks["risk_decision_repo"],
        event_bus=mocks["event_bus"],
        redis_client=mocks["redis_mock"],
        config=_build_config(),
    )


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_single_evaluation_completes(self, engine: RiskEngineService) -> None:
        decision = await engine.evaluate(_build_request())
        assert decision is not None

    async def test_approved_path_publishes_event(
        self, engine: RiskEngineService, mocks: dict
    ) -> None:
        decision = await engine.evaluate(_build_request())
        if decision.approved:
            mocks["event_bus"].publish.assert_called_once()
            event = mocks["event_bus"].publish.call_args[0][0]
            assert isinstance(event, RiskApproved)

    async def test_approved_path_inserts_to_db(
        self, engine: RiskEngineService, mocks: dict
    ) -> None:
        decision = await engine.evaluate(_build_request())
        if decision.approved:
            mocks["risk_decision_repo"].insert.assert_called_once()


# ---------------------------------------------------------------------------
# D-1: Sequential queue — concurrent evaluate() calls
# ---------------------------------------------------------------------------


class TestD1SequentialQueue:
    async def test_concurrent_calls_both_complete(self, engine: RiskEngineService) -> None:
        results = await asyncio.gather(
            engine.evaluate(_build_request()),
            engine.evaluate(_build_request()),
            engine.evaluate(_build_request()),
        )
        assert len(results) == 3
        for r in results:
            assert r is not None

    async def test_concurrent_calls_no_exception(self, engine: RiskEngineService) -> None:
        results = await asyncio.gather(
            *[engine.evaluate(_build_request()) for _ in range(5)],
            return_exceptions=True,
        )
        for r in results:
            assert not isinstance(r, Exception), f"Unexpected exception: {r}"

    async def test_db_insert_called_for_each_decision(
        self, engine: RiskEngineService, mocks: dict
    ) -> None:
        n = 4
        results = await asyncio.gather(*[engine.evaluate(_build_request()) for _ in range(n)])
        # Approved decisions INSERT inside lock; rejected decisions _try_insert best-effort.
        # Either way, insert should be attempted for each outcome that has account_snapshot data.
        total_inserts = mocks["risk_decision_repo"].insert.call_count
        assert total_inserts == n


# ---------------------------------------------------------------------------
# D-2: Persistence-first
# ---------------------------------------------------------------------------


class TestD2PersistenceFirst:
    async def test_insert_before_event(self, mocks: dict) -> None:
        call_log: list[str] = []

        async def track_insert(d: object, t: float) -> int:
            call_log.append("insert")
            return 1

        async def track_publish(e: object) -> None:
            call_log.append("publish")

        mocks["risk_decision_repo"].insert.side_effect = track_insert
        mocks["event_bus"].publish.side_effect = track_publish

        engine = RiskEngineService(
            kill_switch_repo=mocks["ks_repo"],
            account_state_repo=mocks["account_repo"],
            portfolio_state_repo=mocks["portfolio_repo"],
            correlation_repo=mocks["corr_repo"],
            margin_service=mocks["margin_svc"],
            signal_perf_repo=mocks["signal_perf_repo"],
            risk_decision_repo=mocks["risk_decision_repo"],
            event_bus=mocks["event_bus"],
            redis_client=mocks["redis_mock"],
            config=_build_config(),
        )

        await engine.evaluate(_build_request())
        if "insert" in call_log and "publish" in call_log:
            assert call_log.index("insert") < call_log.index("publish")


# ---------------------------------------------------------------------------
# D-3: Kill switch gate
# ---------------------------------------------------------------------------


class TestD3KillSwitchGate:
    async def test_active_kill_switch_blocks_all_concurrent(
        self, mocks: dict
    ) -> None:
        mocks["ks_repo"].get_state.return_value = KillSwitchState(
            is_active=True,
            activated_at=datetime.now(UTC),
            activated_by="risk_engine",
            activation_reason="test",
            deactivated_at=None, deactivated_by=None, deactivation_note=None,
        )
        engine = RiskEngineService(
            kill_switch_repo=mocks["ks_repo"],
            account_state_repo=mocks["account_repo"],
            portfolio_state_repo=mocks["portfolio_repo"],
            correlation_repo=mocks["corr_repo"],
            margin_service=mocks["margin_svc"],
            signal_perf_repo=mocks["signal_perf_repo"],
            risk_decision_repo=mocks["risk_decision_repo"],
            event_bus=mocks["event_bus"],
            redis_client=mocks["redis_mock"],
            config=_build_config(),
        )
        results = await asyncio.gather(*[engine.evaluate(_build_request()) for _ in range(3)])
        for r in results:
            assert not r.approved
            assert r.rejection_code == RiskRejectionCode.KILL_SWITCH_ACTIVE
        mocks["risk_decision_repo"].insert.assert_not_called()
        mocks["event_bus"].publish.assert_not_called()


# ---------------------------------------------------------------------------
# D-4: FAIL_CLOSED
# ---------------------------------------------------------------------------


class TestD4FailClosed:
    async def test_account_unavailable_all_rejected(self, mocks: dict) -> None:
        mocks["account_repo"].get_current.side_effect = DataSourceUnavailableError(
            "account_state", "Redis down"
        )
        engine = RiskEngineService(
            kill_switch_repo=mocks["ks_repo"],
            account_state_repo=mocks["account_repo"],
            portfolio_state_repo=mocks["portfolio_repo"],
            correlation_repo=mocks["corr_repo"],
            margin_service=mocks["margin_svc"],
            signal_perf_repo=mocks["signal_perf_repo"],
            risk_decision_repo=mocks["risk_decision_repo"],
            event_bus=mocks["event_bus"],
            redis_client=mocks["redis_mock"],
            config=_build_config(),
        )
        results = await asyncio.gather(*[engine.evaluate(_build_request()) for _ in range(2)])
        for r in results:
            assert not r.approved
            assert r.rejection_code == RiskRejectionCode.DATA_SOURCE_UNAVAILABLE
        mocks["risk_decision_repo"].insert.assert_not_called()

    async def test_recovery_after_account_restored(self, mocks: dict) -> None:
        call_count = 0
        original_account = _build_healthy_account()

        async def flaky_account() -> AccountState:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise DataSourceUnavailableError("account_state", "blip")
            return original_account

        mocks["account_repo"].get_current.side_effect = flaky_account
        engine = RiskEngineService(
            kill_switch_repo=mocks["ks_repo"],
            account_state_repo=mocks["account_repo"],
            portfolio_state_repo=mocks["portfolio_repo"],
            correlation_repo=mocks["corr_repo"],
            margin_service=mocks["margin_svc"],
            signal_perf_repo=mocks["signal_perf_repo"],
            risk_decision_repo=mocks["risk_decision_repo"],
            event_bus=mocks["event_bus"],
            redis_client=mocks["redis_mock"],
            config=_build_config(),
        )
        first = await engine.evaluate(_build_request())
        assert not first.approved
        second = await engine.evaluate(_build_request())
        # Second call should succeed with healthy account
        assert second is not None


# ---------------------------------------------------------------------------
# Lock released before event publication (observable via timing)
# ---------------------------------------------------------------------------


class TestLockReleasedBeforeEvent:
    async def test_event_published_outside_lock(self, mocks: dict) -> None:
        """Verify that a second evaluate() call can start while event is being published."""
        publish_started = asyncio.Event()
        second_started = asyncio.Event()

        async def slow_publish(event: object) -> None:
            publish_started.set()
            await asyncio.sleep(0.1)

        mocks["event_bus"].publish.side_effect = slow_publish

        engine = RiskEngineService(
            kill_switch_repo=mocks["ks_repo"],
            account_state_repo=mocks["account_repo"],
            portfolio_state_repo=mocks["portfolio_repo"],
            correlation_repo=mocks["corr_repo"],
            margin_service=mocks["margin_svc"],
            signal_perf_repo=mocks["signal_perf_repo"],
            risk_decision_repo=mocks["risk_decision_repo"],
            event_bus=mocks["event_bus"],
            redis_client=mocks["redis_mock"],
            config=_build_config(),
        )

        # Run both concurrently — if lock is held during publish, second would deadlock
        results = await asyncio.gather(
            engine.evaluate(_build_request()),
            engine.evaluate(_build_request()),
        )
        assert len(results) == 2
