"""ConfidenceResult — output of the Phase 12 Confidence Engine.

Contains the 10-component confidence breakdown, the final calibrated
confidence, an observability dict for dashboards, and a human-readable
explanation produced by ConfidenceExplanationBuilder.

Reference: docs/21_SIGNAL_ENGINE.md §Stage 3 — Confidence Engine
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

_VALID_SCORE_BUCKETS = frozenset({"STRONG", "STANDARD"})


@dataclass(frozen=True)
class ConfidenceResult:
    """Output of ConfidenceEngineService.

    ``confidence_components`` holds all 10 adjustment amounts plus data-quality
    and agreement sub-inputs, keyed by component name. This is the canonical
    breakdown for dashboards and future calibration analytics (AC-13).

    Score Engine produced a ``raw_score`` / ``adjusted_score``; the
    Confidence Engine produces ``final_confidence`` independently.
    """

    # 10-component breakdown (Doc 21 additive formula + signal_agreement + recent_performance)
    base_confidence: float
    win_rate_adj: float
    regime_alignment_adj: float
    data_quality_adj: float          # redesigned: score_quality + completeness + freshness
    momentum_adj: float              # stub: 0
    breakout_adj: float              # stub: 0
    loss_streak_adj: float
    historical_accuracy_adj: float
    signal_agreement_adj: float      # component direction alignment
    recent_performance_adj: float    # instrument-level recent win rate

    # Aggregated confidence values
    raw_confidence: float            # sum of all 10 components, clamped [0, 100]
    calibrated_confidence: float     # raw × calibration_factor, clamped [0, 100]
    final_confidence: float          # after score-band ceiling, clamped [0, 100] (AC-12)

    # Gate and identity
    passed_gate: bool                # final_confidence >= cfg.gate.min_confidence
    score_bucket: str                # "STRONG" | "STANDARD"
    fingerprint: str                 # SHA-256 hex from SignalFingerprint

    # Observability: all adjustments + sub-inputs (AC-13)
    confidence_components: dict[str, float]

    # Human-readable explanation lines (populated by ConfidenceExplanationBuilder)
    explanation: list[str] = field(default_factory=list)

    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for name, val in [
            ("base_confidence", self.base_confidence),
            ("raw_confidence", self.raw_confidence),
            ("calibrated_confidence", self.calibrated_confidence),
            ("final_confidence", self.final_confidence),
        ]:
            if not 0.0 <= val <= 100.0:
                raise ValueError(f"{name} {val} out of [0, 100]")
        if self.score_bucket not in _VALID_SCORE_BUCKETS:
            raise ValueError(f"Invalid score_bucket: {self.score_bucket!r}")
        if len(self.fingerprint) != 64:
            raise ValueError("fingerprint must be a 64-character SHA-256 hex digest")
