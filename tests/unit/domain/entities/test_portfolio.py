"""Unit tests — Portfolio entity."""

from __future__ import annotations

import uuid

from core.domain.entities.portfolio import Portfolio
from core.domain.enums.portfolio_type import PortfolioType


def _make_portfolio(**kwargs: object) -> Portfolio:
    return Portfolio.create(
        name=kwargs.pop("name", "Test Portfolio"),  # type: ignore[arg-type]
        portfolio_type=kwargs.pop("portfolio_type", PortfolioType.DEFAULT),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


class TestPortfolioCreate:
    def test_create_defaults(self) -> None:
        p = _make_portfolio()
        assert p.is_active is False
        assert p.risk_profile_id is None
        assert p.allocation_id is None
        assert p.owner_user_id is None

    def test_create_with_links(self) -> None:
        rid = uuid.uuid4()
        aid = uuid.uuid4()
        p = _make_portfolio(risk_profile_id=rid, allocation_id=aid)
        assert p.risk_profile_id == rid
        assert p.allocation_id == aid


class TestPortfolioLifecycle:
    def test_activate(self) -> None:
        p = _make_portfolio()
        p.activate()
        assert p.is_active is True

    def test_deactivate(self) -> None:
        p = _make_portfolio()
        p.activate()
        p.deactivate()
        assert p.is_active is False

    def test_assign_risk_profile(self) -> None:
        p = _make_portfolio()
        rid = uuid.uuid4()
        p.assign_risk_profile(rid)
        assert p.risk_profile_id == rid

    def test_assign_allocation(self) -> None:
        p = _make_portfolio()
        aid = uuid.uuid4()
        p.assign_allocation(aid)
        assert p.allocation_id == aid
