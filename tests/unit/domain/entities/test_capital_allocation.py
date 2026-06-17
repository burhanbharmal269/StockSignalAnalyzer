"""Unit tests — CapitalAllocation entity."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.domain.entities.capital_allocation import CapitalAllocation
from core.domain.enums.allocation_type import AllocationType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.universe_scope import UniverseScope


def _make_allocation(**kwargs: object) -> CapitalAllocation:
    return CapitalAllocation.create(
        name=kwargs.pop("name", "Test"),  # type: ignore[arg-type]
        allocation_type=kwargs.pop("allocation_type", AllocationType.GLOBAL),  # type: ignore[arg-type]
        universe_scope=kwargs.pop("universe_scope", UniverseScope.ALL_FNO),  # type: ignore[arg-type]
        allocated_capital=kwargs.pop("allocated_capital", Decimal("1000000")),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


class TestCapitalAllocationCreate:
    def test_create_with_defaults(self) -> None:
        a = _make_allocation()
        assert a.capital_source_mode == CapitalSourceMode.HYBRID
        assert a.is_active is False
        assert a.allocated_margin is None

    def test_negative_capital_raises(self) -> None:
        with pytest.raises(ValueError, match="allocated_capital"):
            _make_allocation(allocated_capital=Decimal("-1"))

    def test_negative_margin_raises(self) -> None:
        with pytest.raises(ValueError, match="allocated_capital"):
            CapitalAllocation.create(
                name="X",
                allocation_type=AllocationType.GLOBAL,
                universe_scope=UniverseScope.ALL_FNO,
                allocated_capital=Decimal("-100"),
            )


class TestCapitalAllocationLifecycle:
    def test_activate(self) -> None:
        a = _make_allocation()
        a.activate()
        assert a.is_active is True

    def test_deactivate(self) -> None:
        a = _make_allocation()
        a.activate()
        a.deactivate()
        assert a.is_active is False

    def test_update_capital(self) -> None:
        a = _make_allocation()
        a.update_capital(Decimal("2000000"), Decimal("500000"))
        assert a.allocated_capital == Decimal("2000000")
        assert a.allocated_margin == Decimal("500000")

    def test_update_capital_negative_raises(self) -> None:
        a = _make_allocation()
        with pytest.raises(ValueError):
            a.update_capital(Decimal("-1"))

    def test_update_mode(self) -> None:
        a = _make_allocation()
        a.update_mode(CapitalSourceMode.ACCOUNT)
        assert a.capital_source_mode == CapitalSourceMode.ACCOUNT
