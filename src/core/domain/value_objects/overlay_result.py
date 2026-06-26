"""Phase 21.2 — Overlay pipeline value objects.

All types are frozen dataclasses so they can be safely shared across
threads and stored as immutable snapshots in the decision trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.market_context_snapshot import MarketContextSnapshot


# ---------------------------------------------------------------------------
# Per-overlay result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OverlayResult:
    """Standardised output from one overlay pass.

    Carries both the delta (confidence_adj / size_adj) and the running values
    before/after so the decision trace is self-contained.
    """
    name:              str
    applied:           bool
    confidence_adj:    float   # additive delta (0.0 when not applied)
    size_adj:          float   # multiplicative factor (1.0 = no change)
    execution_lock:    bool    # True → force MANUAL mode for this signal
    severity:          str     # NONE / LOW / MEDIUM / HIGH / CRITICAL
    reason:            str     # human-readable explanation
    details:           dict    # overlay-specific metadata

    # Running values before / after this overlay step
    confidence_before: float
    confidence_after:  float
    size_before:       float
    size_after:        float

    def as_trace_step(self, step: int) -> dict:
        """Serialisable trace entry for decision_trace_json."""
        return {
            "step":        step,
            "name":        self.name,
            "applied":     self.applied,
            "conf_before": round(self.confidence_before, 2),
            "adj":         round(self.confidence_adj, 2),
            "conf_after":  round(self.confidence_after, 2),
            "size_before": round(self.size_before, 4),
            "size_after":  round(self.size_after, 4),
            "severity":    self.severity,
            "reason":      self.reason,
            "lock":        self.execution_lock,
        }


# ---------------------------------------------------------------------------
# Pre-fetched portfolio context (once per scan cycle)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PortfolioContext:
    """Snapshot of portfolio state used by the overlay pipeline.

    Fetched once per scan cycle (not once per symbol) for performance.
    All fields are read-only within the pipeline; the scanner pre-populates them.
    """
    heat_pct:           float
    open_symbols:       frozenset   # ticker strings of open/active signals today
    sector_exposure:    dict        # {sector_name: exposure_pct}
    correlation_matrix: dict        # {sym_a: {sym_b: float}} from Redis (may be empty)

    @classmethod
    def empty(cls) -> "PortfolioContext":
        return cls(
            heat_pct=0.0,
            open_symbols=frozenset(),
            sector_exposure={},
            correlation_matrix={},
        )


# ---------------------------------------------------------------------------
# Per-symbol overlay pipeline input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OverlayContext:
    """All per-symbol inputs the pipeline needs — assembled by the scanner."""
    symbol:            str
    is_index:          bool
    regime:            str
    direction:         str
    engine_confidence: float
    engine_score:      float
    market_ctx:        "MarketContextSnapshot | None"
    event_cache:       dict
    regime_history:    list   # last ≤5 regime strings for this symbol (read-only)
    ist_time:          time
    sector:            str | None
    portfolio:         PortfolioContext


# ---------------------------------------------------------------------------
# Pipeline output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OverlayPipelineResult:
    """Complete output of one overlay pipeline run for a signal."""
    symbol:               str
    base_confidence:      float
    final_confidence:     float
    final_size_multiplier: float
    execution_lock:       bool
    execution_grade:      str          # A / B / C / D
    overlays:             tuple        # tuple[OverlayResult, ...]
    decision_trace:       list         # ordered list of trace step dicts
    attribution:          dict         # flat dict → signal_analytics columns
    decision_version:     str
    overlay_version:      str
