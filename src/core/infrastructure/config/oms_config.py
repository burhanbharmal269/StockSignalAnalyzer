"""OmsConfig — Pydantic model for config/oms.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class OmsOrderTypeConfig(BaseModel):
    default: str = "MARKET"
    limit_threshold_premium: int = 500
    limit_buffer_pct: float = Field(default=0.001, ge=0.0, le=0.05)


class OmsStopLossConfig(BaseModel):
    placement_deadline_seconds: int = Field(default=2, ge=1, le=30)


class OmsTargetConfig(BaseModel):
    strategy: str = "PARTIAL_SCALE"
    partial_close_pct: float = Field(default=0.50, ge=0.0, le=1.0)


class OmsReconciliationConfig(BaseModel):
    fill_price_discrepancy_pct: float = Field(default=0.5, ge=0.0)
    schedule_interval_seconds: int = Field(default=300, ge=60)


class OmsPaperConfig(BaseModel):
    market_slippage_pct: float = Field(default=0.05, ge=0.0)
    sl_market_slippage_pct: float = Field(default=0.10, ge=0.0)


class OmsRedisConfig(BaseModel):
    idempotency_key_prefix: str = "oms:idem"
    order_cache_prefix: str = "oms:order"
    position_cache_prefix: str = "oms:position"
    order_cache_ttl_seconds: int = Field(default=900, ge=60)
    position_cache_ttl_seconds: int = Field(default=86400, ge=3600)


class OmsConfig(BaseModel):
    max_orders_per_minute: int = Field(default=10, ge=1, le=100)
    idempotency_ttl_seconds: int = Field(default=300, ge=60)
    order_type: OmsOrderTypeConfig = Field(default_factory=OmsOrderTypeConfig)
    stop_loss: OmsStopLossConfig = Field(default_factory=OmsStopLossConfig)
    target: OmsTargetConfig = Field(default_factory=OmsTargetConfig)
    reconciliation: OmsReconciliationConfig = Field(
        default_factory=OmsReconciliationConfig
    )
    paper: OmsPaperConfig = Field(default_factory=OmsPaperConfig)
    redis: OmsRedisConfig = Field(default_factory=OmsRedisConfig)

    @model_validator(mode="after")
    def _validate_target_strategy(self) -> OmsConfig:
        allowed = {"SINGLE", "PARTIAL_SCALE"}
        if self.target.strategy not in allowed:
            msg = f"target.strategy must be one of {allowed}"
            raise ValueError(msg)
        return self

    def idempotency_key(self, signal_id: str) -> str:
        return f"{self.redis.idempotency_key_prefix}:{signal_id}"

    def order_cache_key(self, order_id: str) -> str:
        return f"{self.redis.order_cache_prefix}:{order_id}"

    def position_cache_key(self, position_id: str) -> str:
        return f"{self.redis.position_cache_prefix}:{position_id}"


def load_oms_config(path: Path | None = None) -> OmsConfig:
    if path is None:
        path = Path(__file__).parents[4] / "config" / "oms.yaml"
    with path.open() as fh:
        raw = yaml.safe_load(fh)
    return OmsConfig(**raw.get("oms", {}))
