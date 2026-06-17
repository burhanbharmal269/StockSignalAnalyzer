"""BrokerHealthReport — result of a broker health probe."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class BrokerHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


@dataclass(frozen=True)
class BrokerHealthReport:
    broker_name: str
    status: BrokerHealthStatus
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    latency_ms: float = 0.0
    details: dict = field(default_factory=dict)
    error: str | None = None
    authenticated_user: str | None = None
