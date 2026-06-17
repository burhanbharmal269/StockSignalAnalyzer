"""UniverseConfig — typed representation of config/universe.yaml v1.0.

Loaded once at startup; injected via ApplicationContainer.universe_config.
All values are validated by Pydantic on load.

Reference: docs/architecture_decisions/AD-USE-01.md (Configuration Schema)
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

_CONFIG_PATH = Path(__file__).parents[4] / "config" / "universe.yaml"

_WEIGHT_TOLERANCE = 1e-6


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class EligibilityConfig(BaseModel):
    allowed_instrument_classes: list[str] = Field(min_length=1)
    max_dte_days: int = Field(ge=1)
    exclude_banned: bool = True


class LiquidityConfig(BaseModel):
    min_liquidity_crores: float = Field(ge=0.0)
    min_active_strikes: int = Field(ge=0)


class VolumeConfig(BaseModel):
    min_volume_ratio: float = Field(ge=0.0)
    weight: float = Field(ge=0.0, le=1.0)


class OIConfig(BaseModel):
    min_oi_lots: float = Field(ge=0.0)
    atm_oi_band_pct: float = Field(ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)


class SpreadConfig(BaseModel):
    max_spread_pct: float = Field(ge=0.0)
    weight: float = Field(ge=0.0, le=1.0)


class IVConfig(BaseModel):
    min_iv_pct: float = Field(ge=0.0)
    max_iv_pct: float = Field(ge=0.0)
    min_ivr: float = Field(ge=0.0, le=100.0)
    max_ivr: float = Field(ge=0.0, le=100.0)

    @field_validator("max_iv_pct")
    @classmethod
    def max_must_exceed_min(cls, v: float, info: object) -> float:
        data = getattr(info, "data", {})
        if v <= data.get("min_iv_pct", 0.0):
            raise ValueError(f"iv.max_iv_pct ({v}) must be > iv.min_iv_pct")
        return v


class ATRConfig(BaseModel):
    min_atr_pct: float = Field(ge=0.0)
    max_atr_pct: float = Field(ge=0.0)
    weight: float = Field(ge=0.0, le=1.0)

    @field_validator("max_atr_pct")
    @classmethod
    def max_must_exceed_min(cls, v: float, info: object) -> float:
        data = getattr(info, "data", {})
        if v <= data.get("min_atr_pct", 0.0):
            raise ValueError(f"atr.max_atr_pct ({v}) must be > atr.min_atr_pct")
        return v


class DiversificationConfig(BaseModel):
    enabled: bool = True
    max_per_sector: int = Field(ge=1)


class UniverseConfig(BaseModel):
    enabled: bool = True
    evaluation_interval_seconds: int = Field(ge=1)
    max_candidates: int = Field(ge=1)
    stale_universe_max_age_seconds: int = Field(ge=1)
    eligibility: EligibilityConfig
    liquidity: LiquidityConfig
    volume: VolumeConfig
    oi: OIConfig
    spread: SpreadConfig
    iv: IVConfig
    atr: ATRConfig
    diversification: DiversificationConfig

    @model_validator(mode="after")
    def weights_must_sum_to_one(self) -> UniverseConfig:
        total = self.volume.weight + self.oi.weight + self.spread.weight + self.atr.weight
        if abs(total - 1.0) > _WEIGHT_TOLERANCE:
            raise ValueError(
                f"universe ranking weights must sum to 1.0, got {total:.6f}. "
                f"Weights: volume={self.volume.weight}, oi={self.oi.weight}, "
                f"spread={self.spread.weight}, atr={self.atr.weight}"
            )
        return self

    @property
    def cache_ttl_seconds(self) -> int:
        """TTL for Redis universe:selected key (interval + 60s buffer)."""
        return self.evaluation_interval_seconds + 60


# ---------------------------------------------------------------------------
# Root wrapper (mirrors YAML top-level structure)
# ---------------------------------------------------------------------------


class _UniverseYaml(BaseModel):
    version: str
    universe: UniverseConfig

    @field_validator("version")
    @classmethod
    def version_must_be_v1(cls, v: str) -> str:
        if v != "1.0":
            raise ValueError(f"universe.yaml version must be '1.0', got {v!r}")
        return v


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_universe_config(path: Path = _CONFIG_PATH) -> UniverseConfig:
    """Load and validate config/universe.yaml, returning an immutable UniverseConfig."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    wrapper = _UniverseYaml.model_validate(raw)
    return wrapper.universe
