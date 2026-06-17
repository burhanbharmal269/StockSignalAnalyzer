"""OrderResult — output from OMS after processing a SignalRiskApproved event."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.domain.enums.order_state import OrderState


@dataclass(frozen=True)
class OrderResult:
    """Result of OrderManagementService.process().

    Indicates whether the order was accepted and routed, or rejected.
    """

    accepted: bool
    order_id: uuid.UUID | None
    signal_id: uuid.UUID
    state: OrderState
    rejection_reason: str = ""
    is_duplicate: bool = False
    broker_order_id: str = ""
