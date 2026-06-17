"""ScoreBreakdown — per-component weighted contributions to raw_score."""

from __future__ import annotations

from dataclasses import dataclass

_VALID_ALIGNMENTS = frozenset({"ALIGNED", "OPPOSED", "NEUTRAL"})


@dataclass(frozen=True)
class ScoreBreakdown:
    """Weighted contribution of each component to the final raw_score.

    Each field holds how many raw-score points that component contributed
    after regime-multiplier weighting and directional adjustment.
    Opposing components show negative contributions. All contributions
    sum to ``total_before_penalties`` (== raw_score).
    """

    oi_buildup: float
    trend: float
    option_chain: float
    volume: float
    vwap: float
    sentiment: float
    iv_analysis: float
    regime_alignment: str       # "ALIGNED" | "OPPOSED" | "NEUTRAL"
    regime_mismatch: bool
    total_before_penalties: float

    def __post_init__(self) -> None:
        if self.regime_alignment not in _VALID_ALIGNMENTS:
            raise ValueError(f"Invalid regime_alignment: {self.regime_alignment!r}")

    def as_dict(self) -> dict[str, float | str | bool]:
        return {
            "oi_buildup": round(self.oi_buildup, 2),
            "trend": round(self.trend, 2),
            "option_chain": round(self.option_chain, 2),
            "volume": round(self.volume, 2),
            "vwap": round(self.vwap, 2),
            "sentiment": round(self.sentiment, 2),
            "iv_analysis": round(self.iv_analysis, 2),
            "regime_alignment": self.regime_alignment,
            "regime_mismatch": self.regime_mismatch,
            "total_before_penalties": round(self.total_before_penalties, 2),
        }
