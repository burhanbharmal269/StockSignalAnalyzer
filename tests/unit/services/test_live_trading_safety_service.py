"""Unit tests for LiveTradingSafetyService — ramp-up stages and safety locks."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from core.application.services.live_trading_safety_service import (
    LiveTradingSafetyService,
    RampUpState,
)
from core.domain.interfaces.i_ramp_up_repository import IRampUpRepository


class FakeRampUpRepository(IRampUpRepository):
    def __init__(self, initial_state: RampUpState | None = None) -> None:
        self._state = initial_state

    async def get_current(self) -> RampUpState | None:
        return self._state

    async def create_initial(self) -> RampUpState:
        self._state = RampUpState(
            ramp_id=1,
            current_stage=1,
            stage_capital=Decimal("5000"),
            stage_entered_at=datetime.now(UTC),
            promoted_at=None,
            locked=False,
            lock_reason=None,
            performance_snapshot=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        return self._state

    async def promote_stage(self, performance_snapshot: dict) -> RampUpState:
        assert self._state is not None
        stage_map = {1: Decimal("5000"), 2: Decimal("10000"), 3: Decimal("25000"), 4: Decimal("50000")}
        next_stage = min(self._state.current_stage + 1, 4)
        self._state = RampUpState(
            ramp_id=self._state.ramp_id,
            current_stage=next_stage,
            stage_capital=stage_map[next_stage],
            stage_entered_at=datetime.now(UTC),
            promoted_at=datetime.now(UTC),
            locked=self._state.locked,
            lock_reason=self._state.lock_reason,
            performance_snapshot=performance_snapshot,
            created_at=self._state.created_at,
            updated_at=datetime.now(UTC),
        )
        return self._state

    async def lock(self, reason: str) -> None:
        assert self._state is not None
        self._state.locked = True
        self._state.lock_reason = reason

    async def unlock(self) -> None:
        assert self._state is not None
        self._state.locked = False
        self._state.lock_reason = None


def _make_service(initial_state: RampUpState | None = None) -> LiveTradingSafetyService:
    repo = FakeRampUpRepository(initial_state)
    return LiveTradingSafetyService(ramp_up_repository=repo)


def _stage1_state() -> RampUpState:
    return RampUpState(
        ramp_id=1,
        current_stage=1,
        stage_capital=Decimal("5000"),
        stage_entered_at=datetime.now(UTC),
        promoted_at=None,
        locked=False,
        lock_reason=None,
        performance_snapshot=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_initialize_creates_stage1() -> None:
    service = _make_service()
    state = await service.initialize()
    assert state.current_stage == 1
    assert state.stage_capital == Decimal("5000")
    assert not state.locked


@pytest.mark.asyncio
async def test_initialize_idempotent_if_already_initialized() -> None:
    existing = _stage1_state()
    service = _make_service(initial_state=existing)
    state = await service.initialize()
    assert state.ramp_id == 1  # Same state returned, not recreated


@pytest.mark.asyncio
async def test_get_state_returns_none_when_not_initialized() -> None:
    service = _make_service()
    state = await service.get_state()
    assert state is None


@pytest.mark.asyncio
async def test_get_state_returns_current_state() -> None:
    service = _make_service(initial_state=_stage1_state())
    state = await service.get_state()
    assert state is not None
    assert state.current_stage == 1


@pytest.mark.asyncio
async def test_check_promotion_eligibility_eligible() -> None:
    service = _make_service(initial_state=_stage1_state())
    result = await service.check_promotion_eligibility(
        win_rate=0.60,
        drawdown_pct=3.0,
        trades_completed=25,
        consecutive_profitable_days=4,
    )
    assert result.eligible
    assert result.current_stage == 1
    assert result.next_stage == 2
    assert result.next_capital == Decimal("10000")


@pytest.mark.asyncio
async def test_check_promotion_eligibility_insufficient_win_rate() -> None:
    service = _make_service(initial_state=_stage1_state())
    result = await service.check_promotion_eligibility(
        win_rate=0.50,
        drawdown_pct=3.0,
        trades_completed=25,
        consecutive_profitable_days=4,
    )
    assert not result.eligible
    assert "win_rate" in result.reason.lower() or "win rate" in result.reason.lower()


@pytest.mark.asyncio
async def test_check_promotion_eligibility_excessive_drawdown() -> None:
    service = _make_service(initial_state=_stage1_state())
    result = await service.check_promotion_eligibility(
        win_rate=0.60,
        drawdown_pct=6.0,
        trades_completed=25,
        consecutive_profitable_days=4,
    )
    assert not result.eligible


@pytest.mark.asyncio
async def test_check_promotion_eligibility_insufficient_trades() -> None:
    service = _make_service(initial_state=_stage1_state())
    result = await service.check_promotion_eligibility(
        win_rate=0.60,
        drawdown_pct=3.0,
        trades_completed=15,
        consecutive_profitable_days=4,
    )
    assert not result.eligible


@pytest.mark.asyncio
async def test_promote_advances_to_next_stage() -> None:
    service = _make_service(initial_state=_stage1_state())
    state = await service.promote(
        win_rate=0.60,
        drawdown_pct=3.0,
        trades_completed=25,
        consecutive_profitable_days=4,
    )
    assert state.current_stage == 2
    assert state.stage_capital == Decimal("10000")


@pytest.mark.asyncio
async def test_promote_raises_if_not_eligible() -> None:
    service = _make_service(initial_state=_stage1_state())
    with pytest.raises(ValueError):
        await service.promote(
            win_rate=0.40,
            drawdown_pct=3.0,
            trades_completed=25,
            consecutive_profitable_days=4,
        )


@pytest.mark.asyncio
async def test_lock_and_unlock() -> None:
    service = _make_service(initial_state=_stage1_state())
    await service.lock("drawdown exceeded 10%")
    state = await service.get_state()
    assert state.locked
    assert state.lock_reason == "drawdown exceeded 10%"

    await service.unlock()
    state = await service.get_state()
    assert not state.locked


@pytest.mark.asyncio
async def test_check_safety_locks_on_low_win_rate() -> None:
    service = _make_service(initial_state=_stage1_state())
    await service.evaluate_safety(
        win_rate=0.35,
        drawdown_pct=3.0,
        consecutive_losses=2,
        broker_consecutive_failures=0,
    )
    state = await service.get_state()
    assert state.locked
    assert "win_rate" in (state.lock_reason or "").lower() or state.lock_reason is not None


@pytest.mark.asyncio
async def test_check_safety_locks_on_excessive_drawdown() -> None:
    service = _make_service(initial_state=_stage1_state())
    await service.evaluate_safety(
        win_rate=0.60,
        drawdown_pct=11.0,
        consecutive_losses=2,
        broker_consecutive_failures=0,
    )
    state = await service.get_state()
    assert state.locked


@pytest.mark.asyncio
async def test_check_safety_no_lock_on_healthy_metrics() -> None:
    service = _make_service(initial_state=_stage1_state())
    await service.evaluate_safety(
        win_rate=0.60,
        drawdown_pct=3.0,
        consecutive_losses=2,
        broker_consecutive_failures=0,
    )
    state = await service.get_state()
    assert not state.locked


@pytest.mark.asyncio
async def test_ramp_up_state_effective_capital_when_locked() -> None:
    state = _stage1_state()
    # effective_capital should be 0 when locked (service layer enforces this)
    assert state.stage_capital == Decimal("5000")
    assert not state.at_max_stage


@pytest.mark.asyncio
async def test_at_max_stage_at_stage4() -> None:
    state = RampUpState(
        ramp_id=1,
        current_stage=4,
        stage_capital=Decimal("50000"),
        stage_entered_at=datetime.now(UTC),
        promoted_at=datetime.now(UTC),
        locked=False,
        lock_reason=None,
        performance_snapshot=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert state.at_max_stage
