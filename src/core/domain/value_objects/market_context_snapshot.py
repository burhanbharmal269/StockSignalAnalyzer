"""MarketContextSnapshot — output of MarketContextEngine (Phase 21.1 §1).

Summarises the current macro / multi-index environment into a single
actionable level.  Consumed by SignalScannerService as a post-engine
confidence and sizing overlay — never by the signal engine itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

# Overlay tables — indexed by level string
CONTEXT_CONFIDENCE_ADJ: dict[str, float] = {
    "NORMAL":    0.0,
    "CAUTION":  -3.0,
    "HIGH_RISK": -7.0,
    "PANIC":    -12.0,
}

CONTEXT_SIZE_MULTIPLIER: dict[str, float] = {
    "NORMAL":    1.00,
    "CAUTION":   0.75,
    "HIGH_RISK": 0.50,
    "PANIC":     0.00,   # 0 = manual-only; scanner stores signal but no auto order
}


@dataclass(frozen=True)
class MarketContextSnapshot:
    """Output of MarketContextEngine.compute()."""

    level: str              # NORMAL | CAUTION | HIGH_RISK | PANIC
    confidence_adj: float   # 0 / -3 / -7 / -12
    size_multiplier: float  # 1.0 / 0.75 / 0.50 / 0.0
    reason: str

    # Inputs recorded for explainability / audit
    nifty_regime: str | None = None
    bnf_regime: str | None = None
    finnifty_regime: str | None = None
    vix: float | None = None
    vix_rising: bool = False
    breadth_score: float | None = None
    advance_decline_ratio: float | None = None
    context_score: int = 0         # raw point total that determined the level

    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        valid_levels = {"NORMAL", "CAUTION", "HIGH_RISK", "PANIC"}
        if self.level not in valid_levels:
            raise ValueError(f"Invalid market context level: {self.level!r}")

    @classmethod
    def normal(cls) -> "MarketContextSnapshot":
        """Return a safe default NORMAL snapshot (used before first cycle completes)."""
        return cls(
            level="NORMAL",
            confidence_adj=0.0,
            size_multiplier=1.00,
            reason="default: awaiting first context cycle",
        )
