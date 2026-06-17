"""Domain events for the Phase 13 Risk Engine.

Complete 12-event schema (H-6 resolution from PHASE_13_FINAL_READINESS_REVIEW.md).
All events are frozen dataclasses inheriting from DomainEvent.

Event-to-topic mapping (docs/11_EVENT_BUS_ARCHITECTURE.md):
  RiskApproved                → signal.risk.approved
  RiskRejected                → signal.risk.rejected
  DataSourceUnavailable       → signal.risk.rejected
  DailyLossLimitBreached      → risk.limit.breached
  WeeklyLossLimitBreached     → risk.limit.breached
  DrawdownLimitBreached       → risk.drawdown.alert
  GraduatedResponseActivated  → risk.drawdown.alert
  PaperModeActivated          → risk.drawdown.alert
  HighWaterMarkUpdated        → risk.drawdown.alert
  MarginAlertBreached         → risk.margin.alert
  KillSwitchActivated         → system.kill_switch.activated
  KillSwitchDeactivated       → system.kill_switch.deactivated

IMPLEMENTATION NOTE — Constraint 16: All 12 events must be defined BEFORE any
service code is written.  Events cannot be added retroactively to an append-only
Redis Stream without breaking existing consumers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.domain.events.base import DomainEvent

# ---------------------------------------------------------------------------
# Pre-trade evaluation outcomes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class RiskApproved(DomainEvent):
    """Published to signal.risk.approved after a successful risk evaluation.

    Constraints:
    - risk_decision_id must be set (INSERT succeeded before this event fires).
    - Three-tier delivery guarantee applies (Constraint 18).

    Attributes:
        signal_id:               UUID of the approved signal.
        risk_decision_id:        FK → risk_decisions.id (persisted before publish).
        approved_lots:           Final lot count after all sizing caps.
        position_size_multiplier: Graduated-response multiplier applied (1.0 / 0.5).
        kelly_fraction_effective: Actual Kelly fraction used (full or fallback).
        sizing_note:             'below_minimum_samples' | 'no_historical_losses' | None.
    """

    signal_id: uuid.UUID
    risk_decision_id: int
    approved_lots: int
    position_size_multiplier: float
    kelly_fraction_effective: float
    sizing_note: str | None


@dataclass(frozen=True, kw_only=True)
class RiskRejected(DomainEvent):
    """Published to signal.risk.rejected when any pre-trade check fails.

    Attributes:
        signal_id:          UUID of the rejected signal.
        failed_check:       RiskRejectionCode enum value as a string.
        reason:             Human-readable rejection summary.
        checks_passed_count: Number of checks that passed before the failure.
    """

    signal_id: uuid.UUID
    failed_check: str
    reason: str
    checks_passed_count: int


# ---------------------------------------------------------------------------
# Loss / drawdown events (published by PortfolioMonitor)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DailyLossLimitBreached(DomainEvent):
    """Published to risk.limit.breached when daily loss reaches 100%.

    Attributes:
        current_loss_pct: Consumed percentage of the daily loss limit.
        limit_pct:        Configured daily_loss.limit_pct from risk.yaml.
    """

    current_loss_pct: float
    limit_pct: float


@dataclass(frozen=True, kw_only=True)
class WeeklyLossLimitBreached(DomainEvent):
    """Published to risk.limit.breached when the rolling 5-day loss reaches 100%.

    Attributes:
        current_loss_pct: Consumed percentage of the weekly loss limit.
        limit_pct:        Configured weekly_loss.limit_pct from risk.yaml.
        rolling_days:     Always 5 — documents the lookback window.
    """

    current_loss_pct: float
    limit_pct: float
    rolling_days: int


@dataclass(frozen=True, kw_only=True)
class DrawdownLimitBreached(DomainEvent):
    """Published to risk.drawdown.alert when drawdown from HWM hits the configured limit.

    Attributes:
        current_drawdown_pct: Drawdown from the rolling 30-day high-water mark.
        limit_pct:            Configured drawdown.max_drawdown_pct from risk.yaml.
    """

    current_drawdown_pct: float
    limit_pct: float


# ---------------------------------------------------------------------------
# Graduated response state machine (published by PortfolioMonitor)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class GraduatedResponseActivated(DomainEvent):
    """Published to risk.drawdown.alert on every graduated-response tier transition.

    Constraint 17: the 'state' field is mandatory.  Consumers use it to distinguish
    REDUCED (halved sizes) from PAPER (no new positions) from KILLED (kill switch).

    Attributes:
        state:                   New tier: 'REDUCED' | 'PAPER' | 'KILLED'.
        daily_loss_pct:          Daily loss consumed % that triggered the transition.
        position_size_multiplier: Multiplier applied: 0.5 (REDUCED) | 0.0 (PAPER/KILLED).
    """

    state: str
    daily_loss_pct: float
    position_size_multiplier: float


@dataclass(frozen=True, kw_only=True)
class PaperModeActivated(DomainEvent):
    """Published to risk.drawdown.alert when the graduated response reaches PAPER tier.

    This is a dedicated event for consumers that only care about paper-mode entry,
    in addition to the GraduatedResponseActivated(state='PAPER') event that also fires.

    Attributes:
        daily_loss_pct:    Daily loss consumed % at paper-mode activation.
        paper_mode_at_pct: Configured threshold (graduated_response.paper_mode_at_pct).
        activated_at:      UTC timestamp of the tier transition.
    """

    daily_loss_pct: float
    paper_mode_at_pct: float
    activated_at: datetime


@dataclass(frozen=True, kw_only=True)
class HighWaterMarkUpdated(DomainEvent):
    """Published to risk.drawdown.alert when a new portfolio high-water mark is set.

    Attributes:
        previous_hwm: Previous HWM in INR.
        new_hwm:      New (higher) HWM in INR.
        updated_at:   UTC timestamp of the new HWM.
    """

    previous_hwm: float
    new_hwm: float
    updated_at: datetime


# ---------------------------------------------------------------------------
# Margin alert (published by PortfolioMonitor)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class MarginAlertBreached(DomainEvent):
    """Published to risk.margin.alert when margin utilisation exceeds the configured limit.

    This is a WARNING event — it does not block trading but signals the operator
    that margin headroom is critically low.

    Attributes:
        available_margin:  Remaining available margin in INR.
        used_margin:       Margin currently consumed in INR.
        utilization_pct:   Computed utilisation percentage.
        limit_pct:         Configured margin.utilization_limit_pct from risk.yaml.
        instrument_token:  The instrument whose proposed trade triggered the check (if any).
    """

    available_margin: float
    used_margin: float
    utilization_pct: float
    limit_pct: float
    instrument_token: int | None


# ---------------------------------------------------------------------------
# Kill switch lifecycle (published by KillSwitchService)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class KillSwitchActivated(DomainEvent):
    """Published to system.kill_switch.activated as step 2 of the 6-step activation sequence.

    Consumers: OMS (halts order submission), BrokerAdapter (cancels pending), Notification.

    Attributes:
        reason:         Human-readable activation reason.
        activated_by:   'operator' | 'risk_engine' | 'dead_mans_switch' | 'system'.
        trigger_source: Specific trigger condition (e.g. 'daily_loss_100pct').
        activated_at:   UTC timestamp of activation.
    """

    reason: str
    activated_by: str
    trigger_source: str
    activated_at: datetime


@dataclass(frozen=True, kw_only=True)
class KillSwitchDeactivated(DomainEvent):
    """Published to system.kill_switch.deactivated after manual operator deactivation.

    Consumers: OMS (resumes order submission), BrokerAdapter, Notification.

    Attributes:
        deactivated_by:      User ID or process that deactivated the kill switch.
        deactivated_at:      UTC timestamp of deactivation.
        deactivation_note:   Operator note recorded at deactivation.
        override_loss_check: True if the operator bypassed the post-recovery loss check.
    """

    deactivated_by: str
    deactivated_at: datetime
    deactivation_note: str
    override_loss_check: bool


# ---------------------------------------------------------------------------
# Data source failure (published by RiskEngineService)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DataSourceUnavailable(DomainEvent):
    """Published to signal.risk.rejected when a FAIL_CLOSED data source is unavailable.

    Provides an audit trail even when the risk_decisions INSERT itself failed
    (H-7 compensating audit record via event bus when DB is down).

    Attributes:
        signal_id:     UUID of the signal whose evaluation was blocked.
        failed_source: Which data source was unavailable (e.g. 'account_state', 'kill_switch').
        failure_type:  'redis_error' | 'db_timeout' | 'broker_api_timeout'.
        evaluated_at:  UTC timestamp when the evaluation was attempted.
    """

    signal_id: uuid.UUID
    failed_source: str
    failure_type: str
    evaluated_at: datetime
