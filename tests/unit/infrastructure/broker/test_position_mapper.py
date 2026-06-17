"""Unit tests for PositionMapper."""

from __future__ import annotations

from decimal import Decimal

from core.domain.value_objects.broker_dtos import BrokerPosition
from core.infrastructure.broker.position_mapper import PositionMapper


def _broker_pos(qty: int = 50, net_qty: int | None = None) -> BrokerPosition:
    return BrokerPosition(
        symbol="NIFTY",
        exchange="NFO",
        product="INTRADAY",
        quantity=qty,
        average_price=Decimal("22000"),
        last_price=Decimal("22100"),
        pnl=Decimal("5000"),
        net_quantity=net_qty if net_qty is not None else qty,
    )


class TestPositionMapper:
    def test_to_snapshot_copies_symbol(self) -> None:
        snap = PositionMapper.to_snapshot(_broker_pos())
        assert snap.symbol == "NIFTY"
        assert snap.exchange == "NFO"

    def test_to_snapshot_copies_quantity(self) -> None:
        snap = PositionMapper.to_snapshot(_broker_pos(qty=75))
        assert snap.quantity == 75

    def test_to_snapshot_long_position_is_long(self) -> None:
        snap = PositionMapper.to_snapshot(_broker_pos(qty=50, net_qty=50))
        assert snap.is_long is True

    def test_to_snapshot_negative_net_qty_is_not_long(self) -> None:
        snap = PositionMapper.to_snapshot(_broker_pos(qty=50, net_qty=-50))
        assert snap.is_long is False

    def test_to_snapshot_fallback_when_no_net_quantity(self) -> None:
        pos = BrokerPosition(
            symbol="NIFTY",
            exchange="NFO",
            product="INTRADAY",
            quantity=30,
            average_price=Decimal("22000"),
            last_price=Decimal("22000"),
            pnl=Decimal("0"),
            net_quantity=None,
        )
        snap = PositionMapper.to_snapshot(pos)
        assert snap.net_quantity == 30  # fallback to quantity

    def test_to_snapshots_batch(self) -> None:
        positions = [_broker_pos(50), _broker_pos(100)]
        snaps = PositionMapper.to_snapshots(positions)
        assert len(snaps) == 2
        assert snaps[0].quantity == 50
        assert snaps[1].quantity == 100

    def test_to_snapshots_empty_list(self) -> None:
        snaps = PositionMapper.to_snapshots([])
        assert snaps == []
