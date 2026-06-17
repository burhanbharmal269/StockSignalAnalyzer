"""Pydantic schemas for the Capital Allocation Framework API (Phase 17)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from core.domain.enums.allocation_type import AllocationType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.portfolio_type import PortfolioType
from core.domain.enums.risk_profile_type import RiskProfileType
from core.domain.enums.universe_scope import UniverseScope


# ---------------------------------------------------------------------------
# RiskProfile schemas
# ---------------------------------------------------------------------------


class RiskProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile_id: uuid.UUID
    name: str
    profile_type: RiskProfileType
    universe_scope: UniverseScope
    risk_per_trade_pct: float
    max_open_positions: int
    daily_loss_pct: float
    weekly_loss_pct: float
    drawdown_pct: float
    max_position_size_pct: float
    min_position_size_lots: int
    is_active: bool
    description: str
    created_at: datetime
    updated_at: datetime


class CreateRiskProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    profile_type: RiskProfileType
    universe_scope: UniverseScope = UniverseScope.ALL_FNO
    risk_per_trade_pct: Decimal = Field(gt=Decimal(0), le=Decimal(10))
    max_open_positions: int = Field(gt=0, le=50)
    daily_loss_pct: Decimal = Field(gt=Decimal(0), le=Decimal(20))
    weekly_loss_pct: Decimal = Field(gt=Decimal(0), le=Decimal(30))
    drawdown_pct: Decimal = Field(gt=Decimal(0), le=Decimal(50))
    max_position_size_pct: Decimal = Field(gt=Decimal(0), le=Decimal(100))
    min_position_size_lots: int = Field(default=1, gt=0)
    description: str = ""


class UpdateRiskProfileRequest(BaseModel):
    risk_per_trade_pct: Decimal | None = Field(default=None, gt=Decimal(0), le=Decimal(10))
    max_open_positions: int | None = Field(default=None, gt=0, le=50)
    daily_loss_pct: Decimal | None = Field(default=None, gt=Decimal(0), le=Decimal(20))
    weekly_loss_pct: Decimal | None = Field(default=None, gt=Decimal(0), le=Decimal(30))
    drawdown_pct: Decimal | None = Field(default=None, gt=Decimal(0), le=Decimal(50))
    max_position_size_pct: Decimal | None = Field(default=None, gt=Decimal(0), le=Decimal(100))
    description: str | None = None


class RiskProfileListResponse(BaseModel):
    profiles: list[RiskProfileResponse]
    total: int


# ---------------------------------------------------------------------------
# CapitalAllocation schemas
# ---------------------------------------------------------------------------


class CapitalAllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allocation_id: uuid.UUID
    name: str
    allocation_type: AllocationType
    universe_scope: UniverseScope
    capital_source_mode: CapitalSourceMode
    allocated_capital: float
    allocated_margin: float | None
    strategy_type: str | None
    is_active: bool
    description: str
    created_at: datetime
    updated_at: datetime


class CreateCapitalAllocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    allocation_type: AllocationType
    universe_scope: UniverseScope = UniverseScope.ALL_FNO
    capital_source_mode: CapitalSourceMode = CapitalSourceMode.HYBRID
    allocated_capital: Decimal = Field(ge=Decimal(0))
    allocated_margin: Decimal | None = Field(default=None, ge=Decimal(0))
    strategy_type: str | None = None
    description: str = ""


class UpdateCapitalRequest(BaseModel):
    new_capital: Decimal = Field(ge=Decimal(0))
    new_margin: Decimal | None = Field(default=None, ge=Decimal(0))
    changed_by: str = "operator"
    notes: str = ""


class UpdateModeRequest(BaseModel):
    capital_source_mode: CapitalSourceMode
    changed_by: str = "operator"


class CapitalAllocationListResponse(BaseModel):
    allocations: list[CapitalAllocationResponse]
    total: int


# ---------------------------------------------------------------------------
# Portfolio schemas
# ---------------------------------------------------------------------------


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    portfolio_id: uuid.UUID
    name: str
    portfolio_type: PortfolioType
    risk_profile_id: uuid.UUID | None
    allocation_id: uuid.UUID | None
    owner_user_id: int | None
    is_active: bool
    description: str
    created_at: datetime
    updated_at: datetime


class CreatePortfolioRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    portfolio_type: PortfolioType
    risk_profile_id: uuid.UUID | None = None
    allocation_id: uuid.UUID | None = None
    owner_user_id: int | None = None
    description: str = ""


class PortfolioListResponse(BaseModel):
    portfolios: list[PortfolioResponse]
    total: int


# ---------------------------------------------------------------------------
# EffectiveAccountState schemas
# ---------------------------------------------------------------------------


class EffectiveAccountStateResponse(BaseModel):
    capital_source_mode: CapitalSourceMode
    broker_capital: float
    broker_margin: float
    configured_capital: float
    configured_margin: float | None
    effective_capital: float
    effective_margin: float
    effective_daily_loss_limit: float
    effective_weekly_loss_limit: float
    effective_drawdown_limit: float
    effective_risk_per_trade: float
    effective_max_open_positions: int
    risk_profile_id: uuid.UUID | None
    allocation_id: uuid.UUID | None
    portfolio_id: uuid.UUID | None
    captured_at: datetime
