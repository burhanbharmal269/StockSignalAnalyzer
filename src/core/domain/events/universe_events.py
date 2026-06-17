"""Domain events for the Universe Selection Engine (AD-USE-01).

Single event per evaluation cycle. Published after the 8-stage filter pipeline
completes and before the candidate list is forwarded to Feature Engineering.

Event topic: universe.selected
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.domain.events.base import DomainEvent
from core.domain.universe.selected_instrument import SelectedInstrument


@dataclass(frozen=True, kw_only=True)
class UniverseSelected(DomainEvent):
    """Published once per universe evaluation cycle.

    Downstream consumers (Feature Engineering, observability dashboards) read
    this event to discover which instruments are active for the current cycle.

    Attributes:
        instruments:           Ordered list of selected candidates (rank ascending).
        total_eligible:        Instruments that passed Stage 1 (eligibility).
        total_filtered_out:    Instruments eliminated across Stages 2–7.
        evaluation_cycle_ms:   Wall-clock milliseconds for the full selection pass.
        protected_count:       Instruments included due to active position protection.
        universe_enabled:      False when USE is bypassed (universe.enabled = false).
    """

    instruments: tuple[SelectedInstrument, ...] = field(default_factory=tuple)
    total_eligible: int = 0
    total_filtered_out: int = 0
    evaluation_cycle_ms: int = 0
    protected_count: int = 0
    universe_enabled: bool = True
