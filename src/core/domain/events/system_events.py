"""Domain events for system-level lifecycle changes."""

from __future__ import annotations

from dataclasses import dataclass

from core.domain.events.base import DomainEvent
from core.domain.value_objects.instrument_refresh_result import RefreshStatus


@dataclass(frozen=True, kw_only=True)
class KillSwitchActivated(DomainEvent):
    activated_by: str
    reason: str
    override_loss_check: bool = False


@dataclass(frozen=True, kw_only=True)
class KillSwitchDeactivated(DomainEvent):
    deactivated_by: str
    resume_in_paper_mode: bool


@dataclass(frozen=True, kw_only=True)
class HeartbeatPublished(DomainEvent):
    service_name: str


@dataclass(frozen=True, kw_only=True)
class SystemHealthChanged(DomainEvent):
    component: str
    previous_status: str
    new_status: str
    detail: str = ""


@dataclass(frozen=True, kw_only=True)
class InstrumentMasterRefreshed(DomainEvent):
    """Fired after the daily instrument master refresh completes (07:55 IST).

    Reference: docs/13_INSTRUMENT_MASTER.md §Refresh Lifecycle
    """

    status: RefreshStatus
    instruments_added: int
    instruments_updated: int
    instruments_deactivated: int
    duration_ms: int
    lot_size_changes_count: int = 0
