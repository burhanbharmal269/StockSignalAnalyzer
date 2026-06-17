"""PortfolioService — CRUD and lifecycle for Portfolio entities."""

from __future__ import annotations

import uuid

from core.domain.entities.portfolio import Portfolio
from core.domain.enums.portfolio_type import PortfolioType
from core.domain.interfaces.i_portfolio_repository import IPortfolioRepository
from core.infrastructure.logging.setup import get_logger

_log = get_logger(__name__)


class PortfolioService:
    def __init__(self, repository: IPortfolioRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_by_id(self, portfolio_id: uuid.UUID) -> Portfolio | None:
        return await self._repo.get_by_id(portfolio_id)

    async def get_active(self) -> Portfolio | None:
        return await self._repo.get_active()

    async def get_active_by_type(self, portfolio_type: PortfolioType) -> Portfolio | None:
        return await self._repo.get_active_by_type(portfolio_type)

    async def list_all(self) -> list[Portfolio]:
        return await self._repo.list_all()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        portfolio_type: PortfolioType,
        *,
        risk_profile_id: uuid.UUID | None = None,
        allocation_id: uuid.UUID | None = None,
        owner_user_id: int | None = None,
        description: str = "",
    ) -> Portfolio:
        portfolio = Portfolio.create(
            name=name,
            portfolio_type=portfolio_type,
            risk_profile_id=risk_profile_id,
            allocation_id=allocation_id,
            owner_user_id=owner_user_id,
            description=description,
        )
        await self._repo.save(portfolio)
        _log.info(
            "portfolio.created",
            portfolio_id=str(portfolio.portfolio_id),
            name=name,
            portfolio_type=portfolio_type.value,
        )
        return portfolio

    async def activate(self, portfolio_id: uuid.UUID) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            msg = f"Portfolio {portfolio_id} not found"
            raise ValueError(msg)
        await self._repo.deactivate_all()
        portfolio.activate()
        await self._repo.save(portfolio)
        _log.info("portfolio.activated", portfolio_id=str(portfolio_id))
        return portfolio

    async def deactivate(self, portfolio_id: uuid.UUID) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            msg = f"Portfolio {portfolio_id} not found"
            raise ValueError(msg)
        portfolio.deactivate()
        await self._repo.save(portfolio)
        _log.info("portfolio.deactivated", portfolio_id=str(portfolio_id))
        return portfolio

    async def assign_risk_profile(
        self, portfolio_id: uuid.UUID, risk_profile_id: uuid.UUID
    ) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            msg = f"Portfolio {portfolio_id} not found"
            raise ValueError(msg)
        portfolio.assign_risk_profile(risk_profile_id)
        await self._repo.save(portfolio)
        return portfolio

    async def assign_allocation(
        self, portfolio_id: uuid.UUID, allocation_id: uuid.UUID
    ) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            msg = f"Portfolio {portfolio_id} not found"
            raise ValueError(msg)
        portfolio.assign_allocation(allocation_id)
        await self._repo.save(portfolio)
        return portfolio
