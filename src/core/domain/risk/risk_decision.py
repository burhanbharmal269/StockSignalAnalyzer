"""RiskDecision — output value objects from RiskEngineService.evaluate().

Contains:
    RiskRejectionCode — exhaustive enum of every rejection reason (20 codes).
    RiskCheckResult   — result of a single pre-trade check (1 of 15).
    SizingResult      — ATR + Kelly sizing breakdown.
    RiskDecision      — complete, immutable risk evaluation record.

All types are frozen.  RiskDecision is persisted to risk_decisions (append-only).
The risk_decision_id field is None before the DB INSERT and populated afterwards
via dataclasses.replace().

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core.domain.exceptions.risk import RiskInvariantError


class RiskRejectionCode(str, Enum):
    """Exhaustive set of rejection codes for a RiskDecision.

    Inherits from str so values serialise to plain strings in JSON/JSONB without
    any custom encoder.  Members are compared by value so
    ``rejection_code == "KILL_SWITCH_ACTIVE"`` works in tests and templates.
    """

    # Infrastructure / data-source failures
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    DATA_SOURCE_UNAVAILABLE = "DATA_SOURCE_UNAVAILABLE"
    AUDIT_PERSISTENCE_FAILURE = "AUDIT_PERSISTENCE_FAILURE"
    AUDIT_PERSISTENCE_TIMEOUT = "AUDIT_PERSISTENCE_TIMEOUT"
    GREEKS_UNAVAILABLE = "GREEKS_UNAVAILABLE"
    MARGIN_DATA_UNAVAILABLE = "MARGIN_DATA_UNAVAILABLE"
    UNSUPPORTED_INSTRUMENT_CLASS = "UNSUPPORTED_INSTRUMENT_CLASS"

    # Loss / drawdown limits (Checks 2–4)
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "WEEKLY_LOSS_LIMIT"
    DRAWDOWN_LIMIT = "DRAWDOWN_LIMIT"

    # Portfolio / concentration limits (Checks 5–7)
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    SYMBOL_CONCENTRATION = "SYMBOL_CONCENTRATION"
    CAPITAL_CONCENTRATION = "CAPITAL_CONCENTRATION"

    # Greek / exposure limits (Checks 8, 9, 15)
    NET_DELTA_LIMIT = "NET_DELTA_LIMIT"
    CORRELATION_LIMIT = "CORRELATION_LIMIT"
    VEGA_LIMIT = "VEGA_LIMIT"

    # Operational limits (Checks 10–11, 13)
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    RISK_REWARD_BELOW_MINIMUM = "RISK_REWARD_BELOW_MINIMUM"
    ORDER_RATE_LIMIT = "ORDER_RATE_LIMIT"

    # Sizing (Check 12)
    POSITION_SIZE_ZERO = "POSITION_SIZE_ZERO"


@dataclass(frozen=True, kw_only=True)
class RiskCheckResult:
    """Result of a single pre-trade check (1 of 15).

    Attributes:
        check_name:    Name of the check (e.g. 'KillSwitch', 'DailyLoss').
        passed:        True if the check passed.
        current_value: Observed metric value (None when not applicable).
        limit_value:   Configured limit value (None when not applicable).
        message:       Human-readable outcome summary.
        is_warning:    True only for ThetaDecay (Check 14 — warn-only, never blocks).
    """

    check_name: str
    passed: bool
    current_value: float | None
    limit_value: float | None
    message: str
    is_warning: bool = False

    def __post_init__(self) -> None:
        if not self.check_name:
            raise RiskInvariantError("check_name must be a non-empty string")

    @property
    def is_hard_failure(self) -> bool:
        """True when this result requires trade rejection.

        Phase D's RiskEngineService.evaluate() MUST use this property as the
        rejection predicate — never ``not result.passed`` directly.
        A result with passed=False and is_warning=True (ThetaDecay, Check 14)
        must not trigger rejection.
        """
        return not self.passed and not self.is_warning


@dataclass(frozen=True, kw_only=True)
class SizingResult:
    """ATR + Kelly position sizing breakdown.

    Attributes:
        lots:                    Final lot count after all caps (may be 0).
        atr_lots_pre_cap:        ATR-formula output before the hard lot cap.
        kelly_lots_pre_cap:      Kelly-formula output before the hard lot cap.
        kelly_fraction_effective: Kelly fraction actually applied (full or fallback).
        kelly_sample_count:      Historical samples used for the Kelly calculation.
        sizing_note:             'below_minimum_samples' | 'no_historical_losses' | None.
    """

    lots: int
    atr_lots_pre_cap: int
    kelly_lots_pre_cap: int
    kelly_fraction_effective: float
    kelly_sample_count: int
    sizing_note: str | None

    def __post_init__(self) -> None:
        if self.lots < 0:
            raise RiskInvariantError(f"lots must be >= 0, got {self.lots}")
        if self.atr_lots_pre_cap < 0:
            raise RiskInvariantError(
                f"atr_lots_pre_cap must be >= 0, got {self.atr_lots_pre_cap}"
            )
        if self.kelly_lots_pre_cap < 0:
            raise RiskInvariantError(
                f"kelly_lots_pre_cap must be >= 0, got {self.kelly_lots_pre_cap}"
            )
        if not (0.0 <= self.kelly_fraction_effective <= 1.0):
            raise RiskInvariantError(
                f"kelly_fraction_effective must be in [0, 1], got {self.kelly_fraction_effective}"
            )
        if self.kelly_sample_count < 0:
            raise RiskInvariantError(
                f"kelly_sample_count must be >= 0, got {self.kelly_sample_count}"
            )


_VALID_SIZE_REDUCTION_PCTS: frozenset[float] = frozenset({0.0, 50.0})


@dataclass(frozen=True, kw_only=True)
class RiskDecision:
    """Complete, immutable risk evaluation record.

    Primary output of RiskEngineService.evaluate().  Persisted to risk_decisions
    (append-only) before any RiskApproved event is published (persistence-first
    invariant, Constraint 4).

    Invariants enforced in __post_init__:
    - approved=True  → rejection_code is None  AND  position_size_lots >= 1
    - approved=False → rejection_code is NOT None
    - size_reduction_pct ∈ {0.0, 50.0}
    - risk_decision_id, when set, must be >= 1

    Attributes:
        signal_id:            UUID of the originating signal.
        approved:             True only when all 15 checks pass and final_lots >= 1.
        rejection_code:       Enum code for the first failed check (None if approved).
        rejection_reason:     Human-readable rejection description (None if approved).
        position_size_lots:   Final approved lot count (None if rejected).
        size_reduction_pct:   Graduated-response reduction: 0.0 (full) or 50.0 (halved).
        checks:               All completed RiskCheckResult entries (tuple for hashability).
        sizing:               Sizing breakdown (None when rejected before the sizing phase).
        account_snapshot:     The AccountState used during this evaluation.
        failed_data_sources:  Data source names that were unavailable (empty tuple on success).
        risk_decision_id:     DB primary key assigned after INSERT; None before persistence.
        evaluated_at:         UTC timestamp when evaluate() began.
    """

    signal_id: uuid.UUID
    approved: bool
    rejection_code: RiskRejectionCode | None
    rejection_reason: str | None
    position_size_lots: int | None
    size_reduction_pct: float
    checks: tuple[RiskCheckResult, ...]
    sizing: SizingResult | None
    account_snapshot: object  # AccountState — typed as object to avoid circular import
    failed_data_sources: tuple[str, ...]
    risk_decision_id: int | None
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if self.approved:
            if self.rejection_code is not None:
                raise RiskInvariantError(
                    "approved RiskDecision must have rejection_code=None, "
                    f"got {self.rejection_code!r}"
                )
            if self.position_size_lots is None:
                raise RiskInvariantError(
                    "approved RiskDecision must have position_size_lots set"
                )
            if self.position_size_lots < 1:
                raise RiskInvariantError(
                    f"approved_lots must be >= 1, got {self.position_size_lots}"
                )
        else:
            if self.rejection_code is None:
                raise RiskInvariantError(
                    "rejected RiskDecision must have a rejection_code"
                )
        if self.size_reduction_pct not in _VALID_SIZE_REDUCTION_PCTS:
            raise RiskInvariantError(
                f"size_reduction_pct must be one of {sorted(_VALID_SIZE_REDUCTION_PCTS)}, "
                f"got {self.size_reduction_pct}"
            )
        if self.risk_decision_id is not None and self.risk_decision_id < 1:
            raise RiskInvariantError(
                f"risk_decision_id must be >= 1 when set, got {self.risk_decision_id}"
            )
