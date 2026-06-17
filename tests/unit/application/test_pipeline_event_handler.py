"""Unit tests — PipelineEventHandler.

Covers:
  - SignalRiskApproved → OMS create + route (happy path)
  - OMS persistence failure → no route attempt
  - OMS kill switch rejection → no route attempt
  - OMS returns not-accepted → no route attempt (duplicate)
  - Order not found after OMS create → no route attempt
  - Route failure → logged, does not propagate
  - OrderFilled (entry) → open position + place SL
  - OrderFilled (exit SL) → handle_stop_loss_fill
  - OrderFilled (exit target) → handle_target_fill
  - OrderFilled for missing order → logged, no crash
  - OrderPartiallyFilled → logged only
  - Wrong event type passed to handler → logged, no crash
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.pipeline_event_handler import PipelineEventHandler
from core.domain.events.order_events import OrderFilled, OrderPartiallyFilled
from core.domain.events.signal_events import SignalGenerated, SignalRiskApproved
from core.domain.exceptions.order import (
    KillSwitchActiveError,
    OrderPersistenceError,
    OrderRateLimitError,
)
from core.domain.value_objects.order_result import OrderResult
from core.domain.enums.order_state import OrderState
from core.domain.value_objects.price import Price


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal_risk_approved(
    signal_id: uuid.UUID | None = None,
) -> SignalRiskApproved:
    return SignalRiskApproved(
        signal_id=signal_id or uuid.uuid4(),
        instrument_token=12345,
        underlying="NIFTY",
        direction="LONG",
        adjusted_score=75.0,
        final_confidence=80.0,
        risk_decision_id=1,
        strategy_type="TREND",
        regime="TRENDING_BULLISH",
        position_size_lots=1,
        valid_until=datetime.now(UTC) + timedelta(minutes=15),
    )


def _make_order_filled(
    order_id: uuid.UUID | None = None,
    signal_id: uuid.UUID | None = None,
    qty: int = 50,
    price: Decimal = Decimal("22000"),
) -> OrderFilled:
    return OrderFilled(
        order_id=order_id or uuid.uuid4(),
        signal_id=signal_id or uuid.uuid4(),
        filled_quantity=qty,
        average_fill_price=price,
        filled_at=datetime.now(UTC),
    )


def _make_position(
    position_id: uuid.UUID | None = None,
    stop_order_id: uuid.UUID | None = None,
) -> MagicMock:
    pos = MagicMock()
    pos.position_id = position_id or uuid.uuid4()
    pos.stop_order_id = stop_order_id
    pos.parent_position_id = None
    return pos


def _make_order(
    order_id: uuid.UUID | None = None,
    parent_position_id: uuid.UUID | None = None,
) -> MagicMock:
    order = MagicMock()
    order.order_id = order_id or uuid.uuid4()
    order.parent_position_id = parent_position_id
    order.broker_order_id = "PAPER-001"
    return order


def _make_accepted_result(order_id: uuid.UUID) -> OrderResult:
    return OrderResult(
        accepted=True,
        order_id=order_id,
        signal_id=uuid.uuid4(),
        state=OrderState.PENDING,
    )


def _make_rejected_result(reason: str = "duplicate") -> OrderResult:
    return OrderResult(
        accepted=False,
        order_id=None,
        signal_id=uuid.uuid4(),
        state=OrderState.PENDING,
        rejection_reason=reason,
        is_duplicate=True,
    )


def _make_handler(
    oms_result: OrderResult | None = None,
    oms_raises: Exception | None = None,
    order_in_repo: MagicMock | None = None,
    route_raises: Exception | None = None,
    position_in_repo: MagicMock | None = None,
    opened_position: MagicMock | None = None,
) -> PipelineEventHandler:
    oms = MagicMock()
    if oms_raises:
        oms.process_signal_risk_approved = AsyncMock(side_effect=oms_raises)
    else:
        oms.process_signal_risk_approved = AsyncMock(
            return_value=oms_result or _make_accepted_result(uuid.uuid4())
        )

    router = MagicMock()
    if route_raises:
        router.route = AsyncMock(side_effect=route_raises)
    else:
        router.route = AsyncMock()

    order_repo = MagicMock()
    order_repo.get_by_id = AsyncMock(return_value=order_in_repo)

    position_mgr = MagicMock()
    position_mgr.open_position = AsyncMock(return_value=opened_position or _make_position())

    exit_mgr = MagicMock()
    exit_mgr.place_stop_loss_order = AsyncMock(return_value=MagicMock(order_id=uuid.uuid4()))
    exit_mgr.handle_stop_loss_fill = AsyncMock()
    exit_mgr.handle_target_fill = AsyncMock()

    position_repo = MagicMock()
    position_repo.get_by_id = AsyncMock(return_value=position_in_repo)

    return PipelineEventHandler(
        order_management_service=oms,
        order_router_service=router,
        order_repository=order_repo,
        position_manager_service=position_mgr,
        exit_manager_service=exit_mgr,
        position_repository=position_repo,
    )


# ---------------------------------------------------------------------------
# SignalRiskApproved handler
# ---------------------------------------------------------------------------


class TestHandleSignalRiskApproved:
    async def test_happy_path_creates_and_routes_order(self) -> None:
        order_id = uuid.uuid4()
        order = _make_order(order_id=order_id)
        result = _make_accepted_result(order_id)

        handler = _make_handler(oms_result=result, order_in_repo=order)
        event = _make_signal_risk_approved()

        await handler.handle_signal_risk_approved(event)

        handler._oms.process_signal_risk_approved.assert_awaited_once_with(event)
        handler._order_repo.get_by_id.assert_awaited_once_with(order_id)
        handler._router.route.assert_awaited_once()

    async def test_oms_persistence_failure_no_route(self) -> None:
        handler = _make_handler(oms_raises=OrderPersistenceError("db down"))
        await handler.handle_signal_risk_approved(_make_signal_risk_approved())
        handler._router.route.assert_not_awaited()

    async def test_oms_kill_switch_rejection_no_route(self) -> None:
        handler = _make_handler(oms_raises=KillSwitchActiveError("kill switch active"))
        await handler.handle_signal_risk_approved(_make_signal_risk_approved())
        handler._router.route.assert_not_awaited()

    async def test_oms_rate_limit_rejection_no_route(self) -> None:
        handler = _make_handler(oms_raises=OrderRateLimitError("rate limit exceeded"))
        await handler.handle_signal_risk_approved(_make_signal_risk_approved())
        handler._router.route.assert_not_awaited()

    async def test_oms_unexpected_exception_no_route(self) -> None:
        handler = _make_handler(oms_raises=RuntimeError("unexpected"))
        await handler.handle_signal_risk_approved(_make_signal_risk_approved())
        handler._router.route.assert_not_awaited()

    async def test_oms_not_accepted_no_route(self) -> None:
        result = _make_rejected_result("duplicate")
        handler = _make_handler(oms_result=result)
        await handler.handle_signal_risk_approved(_make_signal_risk_approved())
        handler._router.route.assert_not_awaited()

    async def test_order_not_found_in_repo_no_route(self) -> None:
        order_id = uuid.uuid4()
        result = _make_accepted_result(order_id)
        handler = _make_handler(oms_result=result, order_in_repo=None)
        await handler.handle_signal_risk_approved(_make_signal_risk_approved())
        handler._router.route.assert_not_awaited()

    async def test_route_failure_does_not_propagate(self) -> None:
        order_id = uuid.uuid4()
        order = _make_order(order_id=order_id)
        result = _make_accepted_result(order_id)
        handler = _make_handler(
            oms_result=result,
            order_in_repo=order,
            route_raises=RuntimeError("broker down"),
        )
        # must not raise
        await handler.handle_signal_risk_approved(_make_signal_risk_approved())

    async def test_wrong_event_type_is_ignored(self) -> None:
        handler = _make_handler()
        wrong_event = SignalGenerated(
            signal_id=uuid.uuid4(),
            symbol="NIFTY",
            signal_type="LONG",
            strategy_type="TREND",
            regime="BULLISH",
        )
        await handler.handle_signal_risk_approved(wrong_event)
        handler._oms.process_signal_risk_approved.assert_not_awaited()


# ---------------------------------------------------------------------------
# OrderFilled handler — entry fill
# ---------------------------------------------------------------------------


class TestHandleOrderFilledEntry:
    async def test_entry_fill_opens_position(self) -> None:
        order_id = uuid.uuid4()
        order = _make_order(order_id=order_id, parent_position_id=None)
        position = _make_position()
        handler = _make_handler(order_in_repo=order, opened_position=position)

        event = _make_order_filled(order_id=order_id)
        await handler.handle_order_filled(event)

        handler._position_mgr.open_position.assert_awaited_once_with(order)

    async def test_entry_fill_places_sl_after_position_open(self) -> None:
        order_id = uuid.uuid4()
        order = _make_order(order_id=order_id, parent_position_id=None)
        position = _make_position()
        handler = _make_handler(order_in_repo=order, opened_position=position)

        await handler.handle_order_filled(_make_order_filled(order_id=order_id))

        handler._exit_mgr.place_stop_loss_order.assert_awaited_once_with(position)

    async def test_entry_fill_position_open_failure_no_sl(self) -> None:
        order_id = uuid.uuid4()
        order = _make_order(order_id=order_id, parent_position_id=None)
        handler = _make_handler(order_in_repo=order)
        handler._position_mgr.open_position = AsyncMock(side_effect=RuntimeError("db fail"))

        await handler.handle_order_filled(_make_order_filled(order_id=order_id))

        handler._exit_mgr.place_stop_loss_order.assert_not_awaited()

    async def test_entry_fill_order_not_found_no_crash(self) -> None:
        handler = _make_handler(order_in_repo=None)
        await handler.handle_order_filled(_make_order_filled())
        handler._position_mgr.open_position.assert_not_awaited()

    async def test_wrong_event_type_is_ignored(self) -> None:
        handler = _make_handler()
        await handler.handle_order_filled(SignalGenerated(
            signal_id=uuid.uuid4(),
            symbol="NIFTY",
            signal_type="LONG",
            strategy_type="TREND",
            regime="BULLISH",
        ))
        handler._position_mgr.open_position.assert_not_awaited()


# ---------------------------------------------------------------------------
# OrderFilled handler — exit fill
# ---------------------------------------------------------------------------


class TestHandleOrderFilledExit:
    async def test_sl_fill_routes_to_handle_stop_loss_fill(self) -> None:
        order_id = uuid.uuid4()
        position_id = uuid.uuid4()

        position = _make_position(position_id=position_id, stop_order_id=order_id)
        order = _make_order(order_id=order_id, parent_position_id=position_id)

        handler = _make_handler(order_in_repo=order, position_in_repo=position)
        event = _make_order_filled(order_id=order_id, price=Decimal("21700"))
        await handler.handle_order_filled(event)

        handler._exit_mgr.handle_stop_loss_fill.assert_awaited_once()
        handler._exit_mgr.handle_target_fill.assert_not_awaited()

    async def test_target_fill_routes_to_handle_target_fill(self) -> None:
        order_id = uuid.uuid4()
        position_id = uuid.uuid4()
        other_sl_order_id = uuid.uuid4()

        position = _make_position(position_id=position_id, stop_order_id=other_sl_order_id)
        order = _make_order(order_id=order_id, parent_position_id=position_id)

        handler = _make_handler(order_in_repo=order, position_in_repo=position)
        event = _make_order_filled(order_id=order_id, price=Decimal("22500"))
        await handler.handle_order_filled(event)

        handler._exit_mgr.handle_target_fill.assert_awaited_once()
        handler._exit_mgr.handle_stop_loss_fill.assert_not_awaited()

    async def test_exit_position_not_found_no_crash(self) -> None:
        order_id = uuid.uuid4()
        position_id = uuid.uuid4()
        order = _make_order(order_id=order_id, parent_position_id=position_id)

        handler = _make_handler(order_in_repo=order, position_in_repo=None)
        await handler.handle_order_filled(_make_order_filled(order_id=order_id))
        handler._exit_mgr.handle_stop_loss_fill.assert_not_awaited()
        handler._exit_mgr.handle_target_fill.assert_not_awaited()

    async def test_exit_handler_failure_does_not_propagate(self) -> None:
        order_id = uuid.uuid4()
        position_id = uuid.uuid4()

        position = _make_position(position_id=position_id, stop_order_id=order_id)
        order = _make_order(order_id=order_id, parent_position_id=position_id)
        handler = _make_handler(order_in_repo=order, position_in_repo=position)
        handler._exit_mgr.handle_stop_loss_fill = AsyncMock(
            side_effect=RuntimeError("exit error")
        )
        # must not raise
        await handler.handle_order_filled(_make_order_filled(order_id=order_id))


# ---------------------------------------------------------------------------
# OrderPartiallyFilled handler
# ---------------------------------------------------------------------------


class TestHandleOrderPartiallyFilled:
    async def test_partial_fill_logs_and_does_not_open_position(self) -> None:
        order_id = uuid.uuid4()
        order = _make_order(order_id=order_id)
        handler = _make_handler(order_in_repo=order)

        event = OrderPartiallyFilled(
            order_id=order_id,
            filled_quantity=25,
            remaining_quantity=25,
            average_fill_price=Decimal("22000"),
        )
        await handler.handle_order_partially_filled(event)
        handler._position_mgr.open_position.assert_not_awaited()

    async def test_partial_fill_wrong_event_type_is_ignored(self) -> None:
        handler = _make_handler()
        await handler.handle_order_partially_filled(
            SignalGenerated(
                signal_id=uuid.uuid4(),
                symbol="NIFTY",
                signal_type="LONG",
                strategy_type="TREND",
                regime="BULLISH",
            )
        )
        handler._position_mgr.open_position.assert_not_awaited()
