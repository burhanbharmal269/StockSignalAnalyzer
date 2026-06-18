"""RiskConfig — typed representation of config/risk.yaml v2.0.

Loaded once at startup; injected via ApplicationContainer.risk_config.
All values are validated by Pydantic on load.

Reference: docs/17_PORTFOLIO_RISK_ENGINE.md
           docs/PHASE_13_REMEDIATION_PLAN.md Section 3 (authoritative schema)
           docs/PHASE_13_IMPLEMENTATION_PLAN.md Section 2.2
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

_CONFIG_PATH = Path(__file__).parents[4] / "config" / "risk.yaml"

_VALID_SIZING_METHODS: frozenset[str] = frozenset(
    {"atr_kelly", "fixed_fractional", "fixed_lots"}
)
_VALID_FAIL_SAFE_POLICIES: frozenset[str] = frozenset(
    {"FAIL_CLOSED", "CONSERVATIVE_DEFAULT"}
)


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class CapitalConfig(BaseModel):
    total_capital: int = Field(ge=1)
    risk_per_trade_pct: float = Field(ge=0.0, le=100.0)


class GraduatedResponseConfig(BaseModel):
    reduce_size_at_pct: float = Field(ge=0.0, le=100.0)
    paper_mode_at_pct: float = Field(ge=0.0, le=100.0)
    kill_switch_at_pct: float = Field(ge=0.0, le=100.0)


class DailyLossConfig(BaseModel):
    limit_pct: float = Field(ge=0.0, le=100.0)
    limit_abs: int = Field(ge=0)
    graduated_response: GraduatedResponseConfig


class WeeklyLossConfig(BaseModel):
    limit_pct: float = Field(ge=0.0, le=100.0)
    limit_abs: int = Field(ge=0)


class MonthlyLossConfig(BaseModel):
    limit_pct: float = Field(default=15.0, ge=0.0, le=100.0)
    limit_abs: int = Field(default=75000, ge=0)


class ExposureLimitsConfig(BaseModel):
    max_symbol_exposure_pct: float = Field(default=20.0, ge=0.0, le=100.0,
        description="Max % of total capital in a single symbol.")
    max_sector_exposure_pct: float = Field(default=40.0, ge=0.0, le=100.0,
        description="Max % of total capital in a single sector.")
    max_strategy_exposure_pct: float = Field(default=50.0, ge=0.0, le=100.0,
        description="Max % of total capital deployed by one strategy.")
    enabled: bool = Field(default=True)


class ConcentrationConfig(BaseModel):
    max_single_position_pct: float = Field(default=15.0, ge=0.0, le=100.0,
        description="Max % of total capital in any one position (by notional).")
    max_top3_concentration_pct: float = Field(default=50.0, ge=0.0, le=100.0,
        description="Max combined % of top-3 positions by notional value.")
    enabled: bool = Field(default=True)


class VolatilityBlockConfig(BaseModel):
    vix_threshold: float = Field(default=30.0, ge=0.0, description="India VIX above this → block new positions.")
    enabled: bool = Field(default=True)


class DrawdownConfig(BaseModel):
    max_drawdown_pct: float = Field(ge=0.0, le=100.0)


class PositionLimitsConfig(BaseModel):
    max_open_positions: int = Field(ge=1)
    max_positions_per_underlying: int = Field(ge=1)
    max_capital_per_underlying_pct: float = Field(ge=0.0, le=100.0)
    max_capital_per_sector_pct: float = Field(ge=0.0, le=100.0)
    max_notional_per_trade_pct: float = Field(ge=0.0, le=100.0)


class OrderRateConfig(BaseModel):
    max_orders_per_minute: int = Field(ge=1, le=1000)
    max_orders_per_day: int = Field(ge=1)


class GreeksConfig(BaseModel):
    max_net_delta: float = Field(ge=0.0)
    max_net_gamma_pct: float = Field(ge=0.0)
    max_net_vega_pct: float = Field(ge=0.0)
    max_theta_daily_decay_pct: float = Field(ge=0.0)
    max_age_seconds: int = Field(ge=1)
    new_position_grace_seconds: int = Field(ge=0)
    fallback_ttl_seconds: int = Field(ge=1)


class MarginConfig(BaseModel):
    utilization_limit_pct: float = Field(ge=0.0, le=100.0)
    min_free_margin_pct: float = Field(ge=0.0, le=100.0)
    timeout_ms: int = Field(ge=1)
    fallback_margin_per_lot_inr: float = Field(default=50000.0, ge=0.0)

    @property
    def timeout_seconds(self) -> float:
        return self.timeout_ms / 1000.0


class RiskRewardConfig(BaseModel):
    min_ratio: float = Field(ge=0.0)
    max_ratio: float = Field(ge=0.0)


class PositionSizingConfig(BaseModel):
    method: str
    kelly_fraction: float = Field(ge=0.0, le=1.0)
    atr_period: int = Field(ge=1)
    atr_stop_multiplier: float = Field(ge=0.1)
    max_position_size_lots: int = Field(ge=1)
    min_kelly_samples: int = Field(ge=1)
    kelly_min_sample_fallback: float = Field(ge=0.0, le=1.0)

    @field_validator("method")
    @classmethod
    def method_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_SIZING_METHODS:
            msg = f"position_sizing.method must be one of {_VALID_SIZING_METHODS}, got {v!r}"
            raise ValueError(msg)
        return v


class DbConfig(BaseModel):
    risk_decisions_insert_timeout_ms: int = Field(ge=1)

    @property
    def risk_decisions_insert_timeout_seconds(self) -> float:
        return self.risk_decisions_insert_timeout_ms / 1000.0


class GreeksCacheFailSafeConfig(BaseModel):
    policy: str = Field(default="FAIL_CLOSED")
    fallback_ttl_seconds: int = Field(ge=1)

    @field_validator("policy")
    @classmethod
    def policy_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_FAIL_SAFE_POLICIES:
            msg = (
                f"redis_fail_safe.greeks_cache.policy must be one of "
                f"{_VALID_FAIL_SAFE_POLICIES!r}, got {v!r}"
            )
            raise ValueError(msg)
        return v


class CorrelationFailSafeConfig(BaseModel):
    policy: str = Field(default="CONSERVATIVE_DEFAULT")
    default_correlation: float = Field(ge=0.0, le=1.0)

    @field_validator("policy")
    @classmethod
    def policy_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_FAIL_SAFE_POLICIES:
            msg = (
                f"redis_fail_safe.correlation_matrix.policy must be one of "
                f"{_VALID_FAIL_SAFE_POLICIES!r}, got {v!r}"
            )
            raise ValueError(msg)
        return v


class RiskEngineConfig(BaseModel):
    gather_timeout_ms: int = Field(ge=1)

    @property
    def gather_timeout_seconds(self) -> float:
        return self.gather_timeout_ms / 1000.0


class DeadMansSwitchConfig(BaseModel):
    redis_check_interval_seconds: int = Field(ge=1)
    redis_failure_threshold: int = Field(ge=1)
    db_check_interval_seconds: int = Field(ge=1)
    db_failure_threshold: int = Field(ge=1)


class RedisFailSafeConfig(BaseModel):
    account_state: str
    portfolio_state: str
    graduated_response_state: str
    greeks_cache: GreeksCacheFailSafeConfig
    correlation_matrix: CorrelationFailSafeConfig
    margin_required: str

    @field_validator(
        "account_state", "portfolio_state", "graduated_response_state", "margin_required"
    )
    @classmethod
    def scalar_policy_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_FAIL_SAFE_POLICIES:
            msg = f"redis_fail_safe policy must be one of {_VALID_FAIL_SAFE_POLICIES}, got {v!r}"
            raise ValueError(msg)
        return v


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------


class RiskConfig(BaseModel):
    """Typed risk limits loaded from config/risk.yaml v2.0.

    Immutable after load. All Phase 13 services read limits through this object.
    No hardcoded numeric limits anywhere in Phase 13 code — all values come from here.

    Version: 2.0
    """

    version: str
    capital: CapitalConfig
    daily_loss: DailyLossConfig
    weekly_loss: WeeklyLossConfig
    monthly_loss: MonthlyLossConfig = Field(default_factory=MonthlyLossConfig)
    volatility_block: VolatilityBlockConfig = Field(default_factory=VolatilityBlockConfig)
    exposure_limits: ExposureLimitsConfig = Field(default_factory=ExposureLimitsConfig)
    concentration: ConcentrationConfig = Field(default_factory=ConcentrationConfig)
    drawdown: DrawdownConfig
    position_limits: PositionLimitsConfig
    order_rate: OrderRateConfig
    greeks: GreeksConfig
    margin: MarginConfig
    risk_reward: RiskRewardConfig
    position_sizing: PositionSizingConfig
    db: DbConfig
    redis_fail_safe: RedisFailSafeConfig
    risk_engine: RiskEngineConfig
    dead_mans_switch: DeadMansSwitchConfig

    @field_validator("version")
    @classmethod
    def version_must_be_v2(cls, v: str) -> str:
        if v != "2.0":
            msg = f"risk.yaml version must be '2.0', got {v!r}. Run the Phase 13 config migration."
            raise ValueError(msg)
        return v


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_risk_config(path: Path = _CONFIG_PATH) -> RiskConfig:
    """Load and validate config/risk.yaml, returning an immutable RiskConfig."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return RiskConfig.model_validate(raw)
