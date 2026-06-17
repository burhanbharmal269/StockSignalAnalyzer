"""SQLAlchemy implementation of IKillSwitchEventsRepository.

kill_switch_events is an append-only audit table.  The application DB user has
SELECT + INSERT permissions only (enforced by migration 004_phase13).

created_at is set by the database server via DEFAULT NOW() — the application
never sets this field explicitly.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.exceptions.risk import RiskDecisionPersistenceError
from core.domain.interfaces.i_kill_switch_events_repository import (
    IKillSwitchEventsRepository,
)
from core.infrastructure.database.models.risk_models import KillSwitchEventModel


class SqlAlchemyKillSwitchEventsRepository(IKillSwitchEventsRepository):
    """Append-only repository for the kill_switch_events audit table."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def insert_event(
        self,
        event_type: str,
        triggered_by: str,
        trigger_source: str,
        reason: str,
        metadata: dict[str, object] | None,
        user_id: int | None,
    ) -> None:
        """Append a kill switch lifecycle event to the audit log.

        Raises:
            RiskDecisionPersistenceError: On OperationalError or IntegrityError.
        """
        orm = KillSwitchEventModel(
            event_type=event_type,
            triggered_by=triggered_by,
            trigger_source=trigger_source,
            reason=reason,
            event_metadata=metadata,
            user_id=user_id,
        )
        try:
            async with self._session_factory() as session:
                session.add(orm)
                await session.commit()
        except (OperationalError, IntegrityError) as exc:
            raise RiskDecisionPersistenceError(
                f"Failed to persist kill switch event '{event_type}': {exc}"
            ) from exc
