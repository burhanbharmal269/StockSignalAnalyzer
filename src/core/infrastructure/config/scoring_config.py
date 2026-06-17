"""ScoringConfig — typed representation of config/scoring_weights.yaml.

SHA-256 of the file is stored with every generated signal for audit
traceability. Validates that component weights sum to total_max_score.

Reference: docs/19_STRATEGY_FRAMEWORK.md, docs/21_SIGNAL_ENGINE.md
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

_CONFIG_PATH = Path(__file__).parents[4] / "config" / "scoring_weights.yaml"


class ComponentWeight(BaseModel):
    max_score: int = Field(ge=0)
    description: str = ""


class TrendComponentWeight(ComponentWeight):
    hard_gate: dict[str, object] | None = None


class ExecutionGate(BaseModel):
    min_score: int = Field(ge=0, le=100)
    min_confidence: int = Field(ge=0, le=100)


class Thresholds(BaseModel):
    strong: int = Field(ge=0, le=100)
    standard: int = Field(ge=0, le=100)
    neutral: int = Field(ge=0, le=100)
    weak: int = Field(ge=0, le=100)


class ScoringComponents(BaseModel):
    oi_buildup: ComponentWeight
    trend: TrendComponentWeight
    option_chain: ComponentWeight
    volume: ComponentWeight
    vwap: ComponentWeight
    sentiment: ComponentWeight
    iv_analysis: ComponentWeight


class PenaltiesConfig(BaseModel):
    data_staleness_per_component: int = Field(ge=0)
    data_staleness_cap: int = Field(ge=0)
    staleness_threshold_seconds: int = Field(ge=0)
    low_conviction_moderate: int = Field(ge=0)
    low_conviction_severe: int = Field(ge=0)
    market_hours_opening: int = Field(ge=0)
    market_hours_closing: int = Field(ge=0)
    regime_mismatch: int = Field(ge=0)
    expiry_dte_zero: int = Field(ge=0)
    expiry_dte_one: int = Field(ge=0)


class DataFreshnessConfig(BaseModel):
    tick_data_max_age: int = Field(ge=1)
    option_chain_max_age: int = Field(ge=1)
    news_max_age: int = Field(ge=1)


class DataQualityConfig(BaseModel):
    data_completeness_min_pct: float = Field(ge=0.0, le=100.0)
    score_quality_high_min_conviction: float = Field(ge=0.0, le=1.0)
    score_quality_medium_min_conviction: float = Field(ge=0.0, le=1.0)
    score_quality_high_min_completeness_pct: float = Field(ge=0.0, le=100.0)
    score_quality_medium_max_staleness_points: int = Field(ge=0)


class ScoringConfig(BaseModel):
    """Typed scoring weights loaded from config/scoring_weights.yaml.

    The sha256 field is the hex digest of the raw YAML file content and
    is injected into every Signal entity at creation time.
    """

    version: str
    components: ScoringComponents
    total_max_score: int = Field(ge=1)
    execution_gate: ExecutionGate
    thresholds: Thresholds
    penalties: PenaltiesConfig
    data_freshness: DataFreshnessConfig
    data_quality: DataQualityConfig
    sha256: str = ""

    @model_validator(mode="after")
    def weights_must_sum_to_total(self) -> ScoringConfig:
        components_sum = (
            self.components.oi_buildup.max_score
            + self.components.trend.max_score
            + self.components.option_chain.max_score
            + self.components.volume.max_score
            + self.components.vwap.max_score
            + self.components.sentiment.max_score
            + self.components.iv_analysis.max_score
        )
        if components_sum != self.total_max_score:
            msg = (
                f"Component weights sum to {components_sum}, "
                f"expected {self.total_max_score}"
            )
            raise ValueError(msg)
        return self


def load_scoring_config(path: Path = _CONFIG_PATH) -> ScoringConfig:
    """Load config/scoring_weights.yaml and embed the file's SHA-256 hash."""
    content = path.read_bytes()
    file_hash = hashlib.sha256(content).hexdigest()
    raw: dict[str, object] = yaml.safe_load(content)
    raw["sha256"] = file_hash
    return ScoringConfig.model_validate(raw)
