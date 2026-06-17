"""Unit tests — Position entity Phase 15 extensions.

Tests the new fields, MTM P&L tracking, breakeven stop movement,
stop/target detection, and backward compatibility.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.domain.entities.position import Position
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.position_state import PositionState
from core.domain.enums.signal_type import SignalType
from core.domain.enums.trading_mode import TradingMode
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol


def _make_position(
    direction: SignalType = SignalType.LONG,
    quantity: int = 50,
    entry_price: Decimal = Decimal("200"),
    stop_loss_price: Decimal | None = Decimal("180"),
    target_1_price: Decimal | None = Decimal("230"),
    target_2_price: Decimal | None = None,
    **kwargs,
) -> Position:
    return Position.open(
        symbol=Symbol("NIFTY", "NFO"),
        direction=direction,
        quantity=quantity,
        entry_price=Price(entry_price),
        signal_id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        instrument_token=12345,
        lots=1,
        stop_loss_price=Price(stop_loss_price) if stop_loss_price else None,
        target_1_price=Price(target_1_price) if target_1_price else None,
        target_2_price=Price(target_2_price) if target_2_price else None,
        trading_mode=TradingMode.LIVE,
        regime_at_open="Trend",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_minimal_open_factory(self):
        pos = Position.open(
            symbol=Symbol("NIFTY", "NFO"),
            direction=SignalType.LONG,
            quantity=50,
            entry_price=Price(Decimal("200")),
        )
        assert pos.state == PositionState.OPEN
        assert pos.trading_mode == TradingMode.LIVE
        assert pos.instrument_token == 0
        assert pos.lots == 0
        assert pos.stop_loss_price is None
        assert pos.target_1_price is None


# ---------------------------------------------------------------------------
# Phase 15 fields
# ---------------------------------------------------------------------------

class TestPhase15Fields:
    def test_enriched_fields_persisted(self):
        sig_id = uuid.uuid4()
        ord_id = uuid.uuid4()
        pos = Position.open(
            symbol=Symbol("NIFTY", "NFO"),
            direction=SignalType.LONG,
            quantity=50,
            entry_price=Price(Decimal("200")),
            signal_id=sig_id,
            order_id=ord_id,
            instrument_token=12345,
            lots=2,
            stop_loss_price=Price(Decimal("180")),
            target_1_price=Price(Decimal("230")),
            trading_mode=TradingMode.PAPER,
            regime_at_open="Mean_Reversion",
        )
        assert pos.signal_id == sig_id
        assert pos.order_id == ord_id
        assert pos.instrument_token == 12345
        assert pos.lots == 2
        assert pos.stop_loss_price.value == Decimal("180")
        assert pos.target_1_price.value == Decimal("230")
        assert pos.trading_mode == TradingMode.PAPER
        assert pos.regime_at_open == "Mean_Reversion"


# ---------------------------------------------------------------------------
# MTM P&L
# ---------------------------------------------------------------------------

class TestMtmPnl:
    def test_initial_mtm_pnl_is_zero(self):
        pos = _make_position()
        assert pos.current_mtm_pnl.value == Decimal("0")

    def test_long_price_increase_positive_mtm(self):
        pos = _make_position(direction=SignalType.LONG, entry_price=Decimal("200"), quantity=50)
        pos.update_price(Price(Decimal("210")))
        # (210 - 200) * 50 = 500
        assert pos.current_mtm_pnl.value == Decimal("500")

    def test_long_price_decrease_negative_mtm(self):
        pos = _make_position(direction=SignalType.LONG, entry_price=Decimal("200"), quantity=50)
        pos.update_price(Price(Decimal("190")))
        # (190 - 200) * 50 = -500
        assert pos.current_mtm_pnl.value == Decimal("-500")

    def test_short_price_decrease_positive_mtm(self):
        pos = _make_position(direction=SignalType.SHORT, entry_price=Decimal("200"), quantity=50)
        pos.update_price(Price(Decimal("190")))
        # SHORT: -(190 - 200) * 50 = 500
        assert pos.current_mtm_pnl.value == Decimal("500")

    def test_mtm_resets_on_close(self):
        pos = _make_position()
        pos.update_price(Price(Decimal("210")))
        pos.close(Price(Decimal("210")), 50, PositionOutcome.WIN)
        assert pos.current_mtm_pnl.value == Decimal("0")


# ---------------------------------------------------------------------------
# is_stop_hit
# ---------------------------------------------------------------------------

class TestIsStopHit:
    def test_long_stop_hit_when_price_at_stop(self):
        pos = _make_position(direction=SignalType.LONG, stop_loss_price=Decimal("180"))
        pos.update_price(Price(Decimal("180")))
        assert pos.is_stop_hit is True

    def test_long_stop_hit_when_price_below_stop(self):
        pos = _make_position(direction=SignalType.LONG, stop_loss_price=Decimal("180"))
        pos.update_price(Price(Decimal("175")))
        assert pos.is_stop_hit is True

    def test_long_stop_not_hit_when_above(self):
        pos = _make_position(direction=SignalType.LONG, stop_loss_price=Decimal("180"))
        pos.update_price(Price(Decimal("190")))
        assert pos.is_stop_hit is False

    def test_short_stop_hit_when_price_at_stop(self):
        pos = _make_position(direction=SignalType.SHORT, stop_loss_price=Decimal("220"))
        pos.update_price(Price(Decimal("220")))
        assert pos.is_stop_hit is True

    def test_short_stop_not_hit_when_below(self):
        pos = _make_position(direction=SignalType.SHORT, stop_loss_price=Decimal("220"))
        pos.update_price(Price(Decimal("210")))
        assert pos.is_stop_hit is False

    def test_no_stop_price_never_hit(self):
        pos = _make_position(stop_loss_price=None)
        pos.update_price(Price(Decimal("100")))
        assert pos.is_stop_hit is False


# ---------------------------------------------------------------------------
# is_target_hit
# ---------------------------------------------------------------------------

class TestIsTargetHit:
    def test_long_target_hit_when_at_price(self):
        pos = _make_position(direction=SignalType.LONG, target_1_price=Decimal("230"))
        pos.update_price(Price(Decimal("230")))
        assert pos.is_target_hit is True

    def test_long_target_hit_when_above(self):
        pos = _make_position(direction=SignalType.LONG, target_1_price=Decimal("230"))
        pos.update_price(Price(Decimal("235")))
        assert pos.is_target_hit is True

    def test_long_target_not_hit_below(self):
        pos = _make_position(direction=SignalType.LONG, target_1_price=Decimal("230"))
        pos.update_price(Price(Decimal("220")))
        assert pos.is_target_hit is False

    def test_short_target_hit_below(self):
        pos = _make_position(direction=SignalType.SHORT, target_1_price=Decimal("170"))
        pos.update_price(Price(Decimal("170")))
        assert pos.is_target_hit is True

    def test_no_target_never_hit(self):
        pos = _make_position(target_1_price=None)
        pos.update_price(Price(Decimal("999")))
        assert pos.is_target_hit is False


# ---------------------------------------------------------------------------
# move_stop_to_breakeven
# ---------------------------------------------------------------------------

class TestMoveStopToBreakeven:
    def test_stop_moves_to_entry(self):
        pos = _make_position(entry_price=Decimal("200"), stop_loss_price=Decimal("180"))
        pos.move_stop_to_breakeven()
        assert pos.stop_loss_price == pos.entry_price

    def test_stop_is_entry_price_after_move(self):
        pos = _make_position(entry_price=Decimal("200"), stop_loss_price=Decimal("180"))
        pos.move_stop_to_breakeven()
        assert pos.stop_loss_price.value == Decimal("200")


# ---------------------------------------------------------------------------
# assign_stop_order / assign_target_order
# ---------------------------------------------------------------------------

class TestAssignOrders:
    def test_assign_stop_order_id(self):
        pos = _make_position()
        stop_id = uuid.uuid4()
        pos.assign_stop_order(stop_id)
        assert pos.stop_order_id == stop_id

    def test_assign_target_order_id(self):
        pos = _make_position()
        target_id = uuid.uuid4()
        pos.assign_target_order(target_id)
        assert pos.target_order_id == target_id


# ---------------------------------------------------------------------------
# close / partial_close
# ---------------------------------------------------------------------------

class TestClose:
    def test_full_close_sets_outcome(self):
        pos = _make_position()
        pos.close(Price(Decimal("230")), 50, PositionOutcome.WIN)
        assert pos.outcome == PositionOutcome.WIN
        assert pos.state == PositionState.CLOSED

    def test_close_records_realized_pnl_long_win(self):
        pos = _make_position(direction=SignalType.LONG, entry_price=Decimal("200"), quantity=50)
        pos.close(Price(Decimal("230")), 50, PositionOutcome.WIN)
        # (230 - 200) * 50 = 1500
        assert pos.realized_pnl.value == Decimal("1500")

    def test_close_records_realized_pnl_long_loss(self):
        pos = _make_position(direction=SignalType.LONG, entry_price=Decimal("200"), quantity=50)
        pos.close(Price(Decimal("180")), 50, PositionOutcome.LOSS)
        # (180 - 200) * 50 = -1000
        assert pos.realized_pnl.value == Decimal("-1000")

    def test_close_records_realized_pnl_short_win(self):
        pos = _make_position(direction=SignalType.SHORT, entry_price=Decimal("200"), quantity=50)
        pos.close(Price(Decimal("170")), 50, PositionOutcome.WIN)
        # SHORT: -(170 - 200) * 50 = 1500
        assert pos.realized_pnl.value == Decimal("1500")

    def test_partial_close_reduces_quantity(self):
        pos = _make_position(quantity=50)
        pos.partial_close(Price(Decimal("220")), 25)
        assert pos.quantity == 25
        assert pos.state == PositionState.PARTIALLY_CLOSED

    def test_partial_close_quantity_gte_total_raises(self):
        pos = _make_position(quantity=50)
        with pytest.raises(ValueError):
            pos.partial_close(Price(Decimal("220")), 50)

    def test_close_sets_closed_at(self):
        pos = _make_position()
        pos.close(Price(Decimal("220")), 50, PositionOutcome.WIN)
        assert pos.closed_at is not None

    def test_breakeven_outcome(self):
        pos = _make_position(entry_price=Decimal("200"))
        pos.close(Price(Decimal("200")), 50, PositionOutcome.BREAKEVEN)
        assert pos.outcome == PositionOutcome.BREAKEVEN
