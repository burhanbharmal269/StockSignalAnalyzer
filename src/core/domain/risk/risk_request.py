"""RiskRequest — frozen input value object to RiskEngineService.evaluate().

Carries everything needed to run all 15 risk checks without additional I/O inside
the check logic.  Constructed by the event consumer from signal.confidence.computed
payload and instrument master data before the evaluation lock is acquired.

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.domain.exceptions.risk import RiskInvariantError

_VALID_INSTRUMENT_CLASSES: frozenset[str] = frozenset({"OPTION", "FUTURE"})
_VALID_DIRECTIONS: frozenset[str] = frozenset({"LONG", "SHORT"})


@dataclass(frozen=True, kw_only=True)
class RiskRequest:
    """All inputs required for one pre-trade risk evaluation.

    Attributes:
        signal_id:          UUID of the originating signal (from signal.confidence.computed).
        instrument_token:   Broker instrument token.
        underlying:         Underlying index/stock name (e.g. 'NIFTY', 'BANKNIFTY').
        instrument_class:   'OPTION' or 'FUTURE'.
        direction:          'LONG' (buy) or 'SHORT' (sell).
        adjusted_score:     Scoring engine output, clamped to [0, 100].
        final_confidence:   Confidence engine output, clamped to [0, 100].
        entry_price:        Proposed entry price (> 0).
        stop_loss_price:    Proposed stop-loss price (> 0).
        target_price:       Proposed target price (> 0).
        option_premium:     Option premium per unit (> 0, required for OPTION; None for FUTURE).
        lot_size:           Exchange-defined lot size (>= 1).
        option_delta:       Delta of the proposed new option position (None for futures).
        option_vega:        Vega of the proposed new option position (None for futures).
        dte:                Days to expiry at evaluation time (>= 0).
        atr_14:             14-period ATR from the feature snapshot (> 0).
        risk_reward_ratio:  Pre-computed (target − entry) / (entry − stop) (> 0).
        evaluated_at:       UTC timestamp when the evaluation was initiated.
    """

    signal_id: uuid.UUID
    instrument_token: int
    underlying: str
    instrument_class: str
    direction: str
    adjusted_score: float
    final_confidence: float
    entry_price: Decimal
    stop_loss_price: Decimal
    target_price: Decimal
    option_premium: Decimal | None
    lot_size: int
    option_delta: float | None
    option_vega: float | None
    dte: int
    atr_14: float
    risk_reward_ratio: float
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if not (0.0 <= self.adjusted_score <= 100.0):
            raise RiskInvariantError(
                f"adjusted_score must be in [0, 100], got {self.adjusted_score}"
            )
        if not (0.0 <= self.final_confidence <= 100.0):
            raise RiskInvariantError(
                f"final_confidence must be in [0, 100], got {self.final_confidence}"
            )
        if self.instrument_class not in _VALID_INSTRUMENT_CLASSES:
            raise RiskInvariantError(
                f"instrument_class must be one of {sorted(_VALID_INSTRUMENT_CLASSES)!r}, "
                f"got {self.instrument_class!r}"
            )
        if self.direction not in _VALID_DIRECTIONS:
            raise RiskInvariantError(
                f"direction must be one of {sorted(_VALID_DIRECTIONS)!r}, "
                f"got {self.direction!r}"
            )
        if self.entry_price <= Decimal(0):
            raise RiskInvariantError(
                f"entry_price must be > 0, got {self.entry_price}"
            )
        if self.stop_loss_price <= Decimal(0):
            raise RiskInvariantError(
                f"stop_loss_price must be > 0, got {self.stop_loss_price}"
            )
        if self.target_price <= Decimal(0):
            raise RiskInvariantError(
                f"target_price must be > 0, got {self.target_price}"
            )
        if self.instrument_class == "OPTION":
            if self.option_premium is None:
                raise RiskInvariantError(
                    "option_premium is required for OPTION instruments"
                )
            if self.option_premium <= Decimal(0):
                raise RiskInvariantError(
                    f"option_premium must be > 0 for OPTION instruments, got {self.option_premium}"
                )
        elif self.option_premium is not None and self.option_premium < Decimal(0):
            raise RiskInvariantError(
                f"option_premium must be >= 0 when provided, got {self.option_premium}"
            )
        if self.lot_size < 1:
            raise RiskInvariantError(
                f"lot_size must be >= 1, got {self.lot_size}"
            )
        if self.dte < 0:
            raise RiskInvariantError(
                f"dte must be >= 0, got {self.dte}"
            )
        if self.atr_14 <= 0.0:
            raise RiskInvariantError(
                f"atr_14 must be > 0, got {self.atr_14}"
            )
        if self.risk_reward_ratio <= 0.0:
            raise RiskInvariantError(
                f"risk_reward_ratio must be > 0, got {self.risk_reward_ratio}"
            )
