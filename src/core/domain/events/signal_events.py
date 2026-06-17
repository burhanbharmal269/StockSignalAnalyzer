"""Domain events for the signal lifecycle."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.domain.events.base import DomainEvent


@dataclass(frozen=True, kw_only=True)
class SignalGenerated(DomainEvent):
    signal_id: uuid.UUID
    symbol: str
    signal_type: str
    strategy_type: str
    regime: str


@dataclass(frozen=True, kw_only=True)
class SignalScored(DomainEvent):
    signal_id: uuid.UUID
    raw_score: int | float
    adjusted_score: int | float
    confidence: int | float
    scoring_weights_sha256: str


@dataclass(frozen=True, kw_only=True)
class SignalWeakRejected(DomainEvent):
    """Signal did not pass execution gate (score < 70 OR confidence < 65)."""

    signal_id: uuid.UUID
    score: int | float
    confidence: int | float


@dataclass(frozen=True, kw_only=True)
class SignalRiskApproved(DomainEvent):
    """Emitted by SignalEngineService after risk approval and DB persistence.

    Contains all fields OMS (Phase 15) needs to place and track the order.
    Published ONLY after the signal has been persisted (persistence-first invariant).
    """

    signal_id: uuid.UUID
    instrument_token: int
    underlying: str
    direction: str              # "LONG" | "SHORT"
    adjusted_score: float
    final_confidence: float
    risk_decision_id: int | None  # None when risk engine did not assign a DB id yet
    strategy_type: str
    regime: str
    position_size_lots: int
    valid_until: datetime


@dataclass(frozen=True, kw_only=True)
class SignalRiskRejected(DomainEvent):
    signal_id: uuid.UUID
    reason: str


@dataclass(frozen=True, kw_only=True)
class SignalForwarded(DomainEvent):
    signal_id: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class SignalExecuted(DomainEvent):
    signal_id: uuid.UUID
    order_id: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class SignalExpired(DomainEvent):
    signal_id: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class SignalCancelled(DomainEvent):
    signal_id: uuid.UUID
    reason: str


@dataclass(frozen=True, kw_only=True)
class ScoreCalculated(DomainEvent):
    """Published by ScoringEngineService after every score evaluation.

    Published even when direction is NEUTRAL or is_eligible is False.
    Contains only scalar fields — no nested domain value objects — so the
    event serialises cleanly to the Redis stream.

    ``signal_id`` is None when scoring is invoked outside a Signal entity
    context (e.g., batch calibration, backtesting). The Phase 14 Signal Engine
    populates it via the ScoreContext caller.

    ``breakdown_*`` fields carry the per-component weighted contributions
    from ScoreBreakdown, enabling dashboard consumers to display a score
    breakdown without a separate API call.
    """

    instrument_token: int
    direction: str
    direction_conviction: float
    raw_score: float
    adjusted_score: float
    score_quality: str
    regime: str
    data_completeness_pct: float
    weights_sha256: str
    penalties_count: int
    is_eligible: bool
    # Per-component score breakdown (H-3: dashboard auditability)
    breakdown_oi_buildup: float
    breakdown_trend: float
    breakdown_option_chain: float
    breakdown_volume: float
    breakdown_vwap: float
    breakdown_sentiment: float
    breakdown_iv_analysis: float
    breakdown_regime_alignment: str
    breakdown_regime_mismatch: bool
    breakdown_total: float
    # Signal correlation (H-2: event-sourced auditability)
    signal_id: uuid.UUID | None = None


@dataclass(frozen=True, kw_only=True)
class ConfidenceCalculated(DomainEvent):
    """Published by ConfidenceEngineService after every confidence evaluation.

    Published for all signals that enter the Confidence Engine, including
    those that do not pass the execution gate. Contains only scalar fields
    for clean Redis stream serialisation.
    """

    instrument_token: int
    direction: str
    score_bucket: str
    fingerprint: str
    base_confidence: float
    raw_confidence: float
    calibrated_confidence: float
    final_confidence: float
    passed_gate: bool
    win_rate_adj: float
    regime_alignment_adj: float
    data_quality_adj: float
    momentum_adj: float
    breakout_adj: float
    loss_streak_adj: float
    historical_accuracy_adj: float
    signal_agreement_adj: float
    recent_performance_adj: float
