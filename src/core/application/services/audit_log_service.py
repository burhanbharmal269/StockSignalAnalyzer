"""AuditLogService — structured audit trail for all auditable platform actions.

Auditable actions:
  USER_LOGIN, USER_LOGOUT
  SIGNAL_APPROVED, SIGNAL_REJECTED
  ORDER_PLACED, ORDER_CANCELLED, ORDER_FILLED
  POSITION_OPENED, POSITION_CLOSED
  KILL_SWITCH_ACTIVATED, KILL_SWITCH_DEACTIVATED
  RISK_VIOLATION
  BROKER_FAILURE
  CAPITAL_UPDATED
  RISK_PROFILE_CHANGED

All methods are fire-and-forget safe — errors are logged but never propagated.
"""

from __future__ import annotations

import logging
from uuid import UUID

from core.domain.interfaces.i_audit_log_repository import AuditLogEntry, IAuditLogRepository

log = logging.getLogger(__name__)


class AuditLogService:
    def __init__(self, repository: IAuditLogRepository) -> None:
        self._repo = repository

    async def _log(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        user_id: UUID | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        try:
            await self._repo.append(
                AuditLogEntry(
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    user_id=user_id,
                    old_value=old_value,
                    new_value=new_value,
                    metadata=metadata,
                    ip_address=ip_address,
                )
            )
        except Exception:  # noqa: BLE001
            log.exception("audit_log.write_failed", extra={"action": action, "entity_id": entity_id})

    # -------------------------------------------------------------------------
    # Auth
    # -------------------------------------------------------------------------

    async def log_user_login(self, user_id: UUID, username: str, ip_address: str | None) -> None:
        await self._log("USER_LOGIN", "user", str(user_id), user_id=user_id, metadata={"username": username}, ip_address=ip_address)

    async def log_user_logout(self, user_id: UUID, username: str) -> None:
        await self._log("USER_LOGOUT", "user", str(user_id), user_id=user_id, metadata={"username": username})

    # -------------------------------------------------------------------------
    # Signals
    # -------------------------------------------------------------------------

    async def log_signal_approved(self, signal_id: str, user_id: UUID | None, metadata: dict | None = None) -> None:
        await self._log("SIGNAL_APPROVED", "signal", signal_id, user_id=user_id, metadata=metadata)

    async def log_signal_rejected(self, signal_id: str, user_id: UUID | None, reason: str) -> None:
        await self._log("SIGNAL_REJECTED", "signal", signal_id, user_id=user_id, metadata={"reason": reason})

    # -------------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------------

    async def log_order_placed(self, order_id: str, broker_order_id: str | None, symbol: str, quantity: int, user_id: UUID | None = None) -> None:
        await self._log(
            "ORDER_PLACED",
            "order",
            order_id,
            user_id=user_id,
            new_value={"broker_order_id": broker_order_id, "symbol": symbol, "quantity": quantity},
        )

    async def log_order_cancelled(self, order_id: str, reason: str, user_id: UUID | None = None) -> None:
        await self._log("ORDER_CANCELLED", "order", order_id, user_id=user_id, metadata={"reason": reason})

    async def log_order_filled(self, order_id: str, broker_order_id: str, fill_price: float, filled_qty: int) -> None:
        await self._log(
            "ORDER_FILLED",
            "order",
            order_id,
            new_value={"broker_order_id": broker_order_id, "fill_price": fill_price, "filled_qty": filled_qty},
        )

    # -------------------------------------------------------------------------
    # Positions
    # -------------------------------------------------------------------------

    async def log_position_opened(self, position_id: str, symbol: str, direction: str, quantity: int, entry_price: float) -> None:
        await self._log(
            "POSITION_OPENED",
            "position",
            position_id,
            new_value={"symbol": symbol, "direction": direction, "quantity": quantity, "entry_price": entry_price},
        )

    async def log_position_closed(self, position_id: str, symbol: str, exit_price: float, pnl: float, user_id: UUID | None = None) -> None:
        await self._log(
            "POSITION_CLOSED",
            "position",
            position_id,
            user_id=user_id,
            new_value={"exit_price": exit_price, "pnl": pnl, "symbol": symbol},
        )

    # -------------------------------------------------------------------------
    # Kill Switch
    # -------------------------------------------------------------------------

    async def log_kill_switch_activated(self, reason: str, activated_by: str, source: str) -> None:
        await self._log(
            "KILL_SWITCH_ACTIVATED",
            "kill_switch",
            "global",
            metadata={"reason": reason, "activated_by": activated_by, "source": source},
        )

    async def log_kill_switch_deactivated(self, deactivated_by: str, note: str | None) -> None:
        await self._log(
            "KILL_SWITCH_DEACTIVATED",
            "kill_switch",
            "global",
            metadata={"deactivated_by": deactivated_by, "note": note},
        )

    # -------------------------------------------------------------------------
    # Risk
    # -------------------------------------------------------------------------

    async def log_risk_violation(self, signal_id: str, rejection_code: str, reason: str) -> None:
        await self._log(
            "RISK_VIOLATION",
            "signal",
            signal_id,
            metadata={"code": rejection_code, "reason": reason},
        )

    # -------------------------------------------------------------------------
    # Broker
    # -------------------------------------------------------------------------

    async def log_broker_failure(self, order_id: str, broker: str, error: str, attempt_count: int) -> None:
        await self._log(
            "BROKER_FAILURE",
            "order",
            order_id,
            metadata={"broker": broker, "error": error, "attempt_count": attempt_count},
        )

    # -------------------------------------------------------------------------
    # Capital / Profile
    # -------------------------------------------------------------------------

    async def log_capital_updated(self, user_id: UUID, old_capital: float, new_capital: float) -> None:
        await self._log(
            "CAPITAL_UPDATED",
            "capital",
            str(user_id),
            user_id=user_id,
            old_value={"capital": old_capital},
            new_value={"capital": new_capital},
        )

    async def log_risk_profile_changed(self, profile_id: str, user_id: UUID, old_value: dict | None, new_value: dict | None) -> None:
        await self._log(
            "RISK_PROFILE_CHANGED",
            "risk_profile",
            profile_id,
            user_id=user_id,
            old_value=old_value,
            new_value=new_value,
        )
