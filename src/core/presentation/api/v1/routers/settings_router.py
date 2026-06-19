"""Settings API — runtime risk & capital configuration.

Endpoints:
  GET   /api/v1/settings/risk-capital   — current system-level risk & capital config
  PATCH /api/v1/settings/risk-capital   — update capital + key risk limits (persists to yaml + Redis)
"""

import logging
from pathlib import Path

import yaml
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from container import ApplicationContainer

_log = logging.getLogger(__name__)
_CONFIG_PATH = Path("/app/config/risk.yaml")

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])


class RiskCapitalSettings(BaseModel):
    total_capital: int = Field(ge=10000, description="Total trading capital in INR")
    risk_per_trade_pct: float = Field(ge=0.1, le=10.0, description="% of capital risked per trade")
    daily_loss_pct: float = Field(ge=0.1, le=20.0, description="Daily loss limit as % of capital")
    daily_loss_abs: int = Field(ge=100, description="Daily loss absolute limit in INR")
    weekly_loss_pct: float = Field(ge=0.1, le=50.0, description="Weekly loss limit as % of capital")
    weekly_loss_abs: int = Field(ge=100, description="Weekly loss absolute limit in INR")
    max_open_positions: int = Field(ge=1, le=50, description="Max concurrent open positions")
    max_capital_per_underlying_pct: float = Field(ge=1.0, le=100.0, description="Max % capital in one underlying")
    vix_threshold: float = Field(ge=10.0, le=100.0, description="India VIX above this blocks new positions")


@router.get("/risk-capital", response_model=RiskCapitalSettings)
@inject
async def get_risk_capital_settings(
    risk_config=Depends(Provide[ApplicationContainer.risk_config]),  # noqa: B008
) -> RiskCapitalSettings:
    """Return current system-level capital and risk limits from risk.yaml."""
    c = risk_config
    return RiskCapitalSettings(
        total_capital=c.capital.total_capital,
        risk_per_trade_pct=c.capital.risk_per_trade_pct,
        daily_loss_pct=c.daily_loss.limit_pct,
        daily_loss_abs=c.daily_loss.limit_abs,
        weekly_loss_pct=c.weekly_loss.limit_pct,
        weekly_loss_abs=c.weekly_loss.limit_abs,
        max_open_positions=c.position_limits.max_open_positions,
        max_capital_per_underlying_pct=c.position_limits.max_capital_per_underlying_pct,
        vix_threshold=c.volatility_block.vix_threshold,
    )


@router.patch("/risk-capital", response_model=RiskCapitalSettings)
@inject
async def update_risk_capital_settings(
    body: RiskCapitalSettings,
    redis_client=Depends(Provide[ApplicationContainer.redis_client]),  # noqa: B008
) -> RiskCapitalSettings:
    """Persist updated capital & risk limits to risk.yaml and re-seed Redis account state."""
    # 1. Load current yaml
    raw: dict = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))

    # 2. Apply user changes
    raw["capital"]["total_capital"] = body.total_capital
    raw["capital"]["risk_per_trade_pct"] = body.risk_per_trade_pct
    raw["daily_loss"]["limit_pct"] = body.daily_loss_pct
    raw["daily_loss"]["limit_abs"] = body.daily_loss_abs
    raw["weekly_loss"]["limit_pct"] = body.weekly_loss_pct
    raw["weekly_loss"]["limit_abs"] = body.weekly_loss_abs
    raw["position_limits"]["max_open_positions"] = body.max_open_positions
    raw["position_limits"]["max_capital_per_underlying_pct"] = body.max_capital_per_underlying_pct
    raw["volatility_block"]["vix_threshold"] = body.vix_threshold

    # 3. Write back to yaml
    _CONFIG_PATH.write_text(yaml.dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _log.info("settings.risk_capital_updated capital=%d", body.total_capital)

    # 4. Update Redis account state so the Risk Engine uses the new capital immediately
    #    (only updates capital fields — preserves live P&L / loss tracking fields)
    try:
        existing = await redis_client.hgetall("risk:account_state")
        if existing:
            new_capital = str(body.total_capital)
            await redis_client.hset("risk:account_state", mapping={
                "account_capital": new_capital,
                "session_capital": new_capital,
                "available_margin": new_capital,
            })
            _log.info("settings.redis_account_state_updated capital=%s", new_capital)
    except Exception as exc:
        _log.warning("settings.redis_update_failed: %s", exc)

    return body
