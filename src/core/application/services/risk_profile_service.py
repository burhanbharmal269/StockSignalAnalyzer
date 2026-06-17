"""RiskProfileService — CRUD and lifecycle for RiskProfile entities."""

from __future__ import annotations

import uuid
from decimal import Decimal

from core.domain.entities.risk_profile import RiskProfile
from core.domain.enums.risk_profile_type import RiskProfileType
from core.domain.enums.universe_scope import UniverseScope
from core.domain.interfaces.i_risk_profile_repository import IRiskProfileRepository
from core.infrastructure.logging.setup import get_logger

_log = get_logger(__name__)


class RiskProfileService:
    def __init__(self, repository: IRiskProfileRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_by_id(self, profile_id: uuid.UUID) -> RiskProfile | None:
        return await self._repo.get_by_id(profile_id)

    async def get_active(self) -> RiskProfile | None:
        return await self._repo.get_active()

    async def list_all(self) -> list[RiskProfile]:
        return await self._repo.list_all()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        profile_type: RiskProfileType,
        universe_scope: UniverseScope,
        risk_per_trade_pct: Decimal,
        max_open_positions: int,
        daily_loss_pct: Decimal,
        weekly_loss_pct: Decimal,
        drawdown_pct: Decimal,
        max_position_size_pct: Decimal,
        min_position_size_lots: int = 1,
        description: str = "",
    ) -> RiskProfile:
        self._validate_limits(
            risk_per_trade_pct=risk_per_trade_pct,
            daily_loss_pct=daily_loss_pct,
            weekly_loss_pct=weekly_loss_pct,
            drawdown_pct=drawdown_pct,
            max_position_size_pct=max_position_size_pct,
            max_open_positions=max_open_positions,
            min_position_size_lots=min_position_size_lots,
        )
        profile = RiskProfile.create(
            name=name,
            profile_type=profile_type,
            universe_scope=universe_scope,
            risk_per_trade_pct=risk_per_trade_pct,
            max_open_positions=max_open_positions,
            daily_loss_pct=daily_loss_pct,
            weekly_loss_pct=weekly_loss_pct,
            drawdown_pct=drawdown_pct,
            max_position_size_pct=max_position_size_pct,
            min_position_size_lots=min_position_size_lots,
            description=description,
        )
        await self._repo.save(profile)
        _log.info("risk_profile.created", profile_id=str(profile.profile_id), name=name)
        return profile

    async def create_from_preset(self, profile_type: RiskProfileType) -> RiskProfile:
        if profile_type == RiskProfileType.CONSERVATIVE:
            profile = RiskProfile.conservative()
        elif profile_type == RiskProfileType.MODERATE:
            profile = RiskProfile.moderate()
        elif profile_type == RiskProfileType.AGGRESSIVE:
            profile = RiskProfile.aggressive()
        else:
            msg = "Use create() for CUSTOM profiles"
            raise ValueError(msg)
        await self._repo.save(profile)
        _log.info(
            "risk_profile.created_from_preset",
            profile_id=str(profile.profile_id),
            profile_type=profile_type.value,
        )
        return profile

    async def activate(self, profile_id: uuid.UUID) -> RiskProfile:
        profile = await self._repo.get_by_id(profile_id)
        if profile is None:
            msg = f"RiskProfile {profile_id} not found"
            raise ValueError(msg)
        await self._repo.deactivate_all()
        profile.activate()
        await self._repo.save(profile)
        _log.info("risk_profile.activated", profile_id=str(profile_id))
        return profile

    async def deactivate(self, profile_id: uuid.UUID) -> RiskProfile:
        profile = await self._repo.get_by_id(profile_id)
        if profile is None:
            msg = f"RiskProfile {profile_id} not found"
            raise ValueError(msg)
        profile.deactivate()
        await self._repo.save(profile)
        _log.info("risk_profile.deactivated", profile_id=str(profile_id))
        return profile

    async def update(self, profile_id: uuid.UUID, **kwargs: object) -> RiskProfile:
        profile = await self._repo.get_by_id(profile_id)
        if profile is None:
            msg = f"RiskProfile {profile_id} not found"
            raise ValueError(msg)
        profile.update(**kwargs)
        await self._repo.save(profile)
        _log.info("risk_profile.updated", profile_id=str(profile_id))
        return profile

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_limits(
        risk_per_trade_pct: Decimal,
        daily_loss_pct: Decimal,
        weekly_loss_pct: Decimal,
        drawdown_pct: Decimal,
        max_position_size_pct: Decimal,
        max_open_positions: int,
        min_position_size_lots: int,
    ) -> None:
        errors: list[str] = []
        if risk_per_trade_pct <= Decimal(0) or risk_per_trade_pct > Decimal(10):
            errors.append("risk_per_trade_pct must be in (0, 10]")
        if daily_loss_pct <= Decimal(0) or daily_loss_pct > Decimal(20):
            errors.append("daily_loss_pct must be in (0, 20]")
        if weekly_loss_pct <= Decimal(0) or weekly_loss_pct > Decimal(30):
            errors.append("weekly_loss_pct must be in (0, 30]")
        if drawdown_pct <= Decimal(0) or drawdown_pct > Decimal(50):
            errors.append("drawdown_pct must be in (0, 50]")
        if max_position_size_pct <= Decimal(0) or max_position_size_pct > Decimal(100):
            errors.append("max_position_size_pct must be in (0, 100]")
        if max_open_positions <= 0:
            errors.append("max_open_positions must be > 0")
        if min_position_size_lots <= 0:
            errors.append("min_position_size_lots must be > 0")
        if errors:
            raise ValueError("; ".join(errors))
