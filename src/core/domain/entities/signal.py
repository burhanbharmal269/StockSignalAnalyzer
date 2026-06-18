"""Signal entity — full lifecycle from generation to execution.

State machine (unified from docs/16, docs/21, docs/22):

  PENDING → SCORING → SCORED → RISK_PENDING → RISK_APPROVED → FORWARDED → EXECUTED
                             → WEAK_SIGNAL (terminal)
                    → RISK_REJECTED (terminal)
  Any non-terminal state → CANCELLED | FAILED

See signal_state.py for the complete valid-transition map.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.domain.enums.asset_type import AssetType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.market_regime import MarketRegime
from core.domain.enums.signal_state import VALID_SIGNAL_TRANSITIONS, SignalState
from core.domain.enums.signal_type import SignalType
from core.domain.enums.strategy_type import StrategyType
from core.domain.events.signal_events import (
    SignalScored,
    SignalWeakRejected,
)
from core.domain.exceptions.signal import SignalStateError
from core.domain.value_objects.confidence import Confidence
from core.domain.value_objects.score import Score
from core.domain.value_objects.symbol import Symbol


@dataclass
class Signal:
    """A trading signal through its full lifecycle.

    Created in PENDING state. Transitions are strictly enforced by
    _transition_to(). Attempting an invalid transition raises SignalStateError.

    Domain events are accumulated in _pending_events and pulled by the
    application layer after each operation.
    """

    signal_id: uuid.UUID
    symbol: Symbol
    signal_type: SignalType
    strategy_type: StrategyType
    asset_type: AssetType
    regime: MarketRegime
    valid_until: datetime
    correlation_id: str
    state: SignalState = field(default=SignalState.PENDING)
    raw_score: Score | None = field(default=None)
    adjusted_score: Score | None = field(default=None)
    confidence: Confidence | None = field(default=None)
    scoring_weights_sha256: str = field(default="")
    fingerprint: str = field(default="")
    risk_rejection_reason: str = field(default="")

    # Phase 17 audit fields — nullable for backward compat
    risk_profile_id: uuid.UUID | None = field(default=None)
    allocation_id: uuid.UUID | None = field(default=None)
    portfolio_id: uuid.UUID | None = field(default=None)
    capital_source_mode: CapitalSourceMode | None = field(default=None)

    # Price levels — populated from signal_analytics join (display only)
    entry_price: float | None = field(default=None)
    stop_loss_price: float | None = field(default=None)
    target_price: float | None = field(default=None)

    # Option contract recommendation — populated from signal_analytics join
    option_type: str | None = field(default=None)    # "CE" or "PE"
    option_strike: float | None = field(default=None)
    option_expiry: str | None = field(default=None)  # ISO date string
    option_symbol: str | None = field(default=None)  # e.g. HDFCBANK26JUN1750CE
    option_entry: float | None = field(default=None)
    option_sl: float | None = field(default=None)
    option_target: float | None = field(default=None)

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    _pending_events: list[object] = field(
        default_factory=list, init=False, repr=False
    )

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _transition_to(self, new_state: SignalState) -> None:
        allowed = VALID_SIGNAL_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise SignalStateError(self.state, new_state)
        self.state = new_state

    # ------------------------------------------------------------------
    # Lifecycle methods
    # ------------------------------------------------------------------

    def start_scoring(self) -> None:
        """Move from PENDING → SCORING."""
        self._transition_to(SignalState.SCORING)

    def complete_scoring(
        self,
        raw_score: Score,
        adjusted_score: Score,
        confidence: Confidence,
        scoring_weights_sha256: str,
        fingerprint: str = "",
    ) -> None:
        """Move from SCORING → SCORED (always).

        Gate check happens separately via submit_to_risk(), which transitions
        SCORED → RISK_PENDING (passes) or SCORED → WEAK_SIGNAL (fails).
        """
        self.raw_score = raw_score
        self.adjusted_score = adjusted_score
        self.confidence = confidence
        self.scoring_weights_sha256 = scoring_weights_sha256
        self.fingerprint = fingerprint
        self._transition_to(SignalState.SCORED)
        self._pending_events.append(
            SignalScored(
                signal_id=self.signal_id,
                raw_score=raw_score.value,
                adjusted_score=adjusted_score.value,
                confidence=confidence.value,
                scoring_weights_sha256=scoring_weights_sha256,
                correlation_id=self.correlation_id,
            )
        )

    def submit_to_risk(self, min_score: int, min_confidence: int) -> None:
        """Move from SCORED → RISK_PENDING or SCORED → WEAK_SIGNAL.

        Applies the execution gate (score >= 70 AND confidence >= 65).
        """
        if self.adjusted_score is None or self.confidence is None:
            self._transition_to(SignalState.WEAK_SIGNAL)
            return
        passes_gate = (
            self.adjusted_score.passes_execution_gate(min_score)
            and self.confidence.passes_execution_gate(min_confidence)
        )
        if passes_gate:
            self._transition_to(SignalState.RISK_PENDING)
        else:
            self._transition_to(SignalState.WEAK_SIGNAL)
            self._pending_events.append(
                SignalWeakRejected(
                    signal_id=self.signal_id,
                    score=self.adjusted_score.value,
                    confidence=self.confidence.value,
                    correlation_id=self.correlation_id,
                )
            )

    def approve_risk(self) -> None:
        """Move from RISK_PENDING → RISK_APPROVED."""
        self._transition_to(SignalState.RISK_APPROVED)

    def reject_risk(self, reason: str) -> None:
        """Move from RISK_PENDING → RISK_REJECTED."""
        self.risk_rejection_reason = reason
        self._transition_to(SignalState.RISK_REJECTED)

    def forward_to_oms(self) -> None:
        """Move from RISK_APPROVED → FORWARDED."""
        self._transition_to(SignalState.FORWARDED)

    def mark_executed(self) -> None:
        """Move from FORWARDED → EXECUTED."""
        self._transition_to(SignalState.EXECUTED)

    def expire(self) -> None:
        """Move from FORWARDED → EXPIRED."""
        self._transition_to(SignalState.EXPIRED)

    def cancel(self, reason: str = "") -> None:
        """Cancel from any non-terminal state."""
        self._transition_to(SignalState.CANCELLED)

    def fail(self, reason: str = "") -> None:
        """Mark as FAILED from any non-terminal state."""
        self._transition_to(SignalState.FAILED)

    # ------------------------------------------------------------------
    # Domain events
    # ------------------------------------------------------------------

    def pull_events(self) -> list[object]:
        """Drain and return accumulated domain events."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def is_expired_by_ttl(self) -> bool:
        return datetime.now(UTC) >= self.valid_until

    def passed_execution_gate(self, min_score: int, min_confidence: int) -> bool:
        if self.adjusted_score is None or self.confidence is None:
            return False
        return (
            self.adjusted_score.passes_execution_gate(min_score)
            and self.confidence.passes_execution_gate(min_confidence)
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        symbol: Symbol,
        signal_type: SignalType,
        strategy_type: StrategyType,
        asset_type: AssetType,
        regime: MarketRegime,
        valid_until: datetime,
        correlation_id: str = "",
    ) -> Signal:
        return cls(
            signal_id=uuid.uuid4(),
            symbol=symbol,
            signal_type=signal_type,
            strategy_type=strategy_type,
            asset_type=asset_type,
            regime=regime,
            valid_until=valid_until,
            correlation_id=correlation_id,
        )
