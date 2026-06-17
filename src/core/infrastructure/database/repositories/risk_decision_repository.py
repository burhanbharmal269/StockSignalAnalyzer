"""SQLAlchemy implementation of IRiskDecisionRepository.

risk_decisions is an append-only TimescaleDB hypertable.  The application DB
user has SELECT + INSERT permissions only (enforced by migration 004_phase13).

RC-5: timeout_seconds is an unused compatibility parameter.  Timeout
enforcement belongs exclusively to the Phase D RiskEngineService caller, which
wraps this call with asyncio.wait_for(timeout=timeout_seconds).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.exceptions.risk import RiskDecisionPersistenceError
from core.domain.interfaces.i_risk_decision_repository import IRiskDecisionRepository
from core.domain.risk.risk_decision import RiskDecision
from core.infrastructure.database.models.risk_models import RiskDecisionModel


def _to_jsonable(v: object) -> object:
    """Recursively convert domain types to JSON-serialisable equivalents.

    Conversion table:
        bool       → bool (must precede int check — bool is a subclass of int)
        Decimal    → str
        datetime   → ISO 8601 str
        uuid.UUID  → str
        Enum       → .value (str for RiskRejectionCode)
        tuple/list → list of recursively converted elements
        dict       → dict of recursively converted values
        dataclass  → dict of field values (computed properties excluded)
        everything else → unchanged
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, tuple | list):
        return [_to_jsonable(item) for item in v]
    if isinstance(v, dict):
        return {k: _to_jsonable(val) for k, val in v.items()}
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {
            f.name: _to_jsonable(getattr(v, f.name))
            for f in dataclasses.fields(v)  # type: ignore[arg-type]
        }
    return v


class SqlAlchemyRiskDecisionRepository(IRiskDecisionRepository):
    """Append-only repository for the risk_decisions TimescaleDB hypertable."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def insert(self, decision: RiskDecision, timeout_seconds: float) -> int:
        """Persist a RiskDecision and return its assigned BIGSERIAL primary key.

        timeout_seconds is accepted for interface compatibility but is not
        enforced internally.  The Phase D RiskEngineService caller owns the
        timeout policy (RC-5).

        Raises:
            RiskDecisionPersistenceError: On OperationalError or IntegrityError.
        """
        orm = RiskDecisionModel(
            signal_id=decision.signal_id,
            approved=decision.approved,
            rejection_code=(
                decision.rejection_code.value if decision.rejection_code is not None else None
            ),
            rejection_reason=decision.rejection_reason,
            position_size_lots=decision.position_size_lots,
            size_reduction_pct=decision.size_reduction_pct,
            checks=[_to_jsonable(c) for c in decision.checks],
            account_snapshot=_to_jsonable(decision.account_snapshot),
            portfolio_snapshot=None,
            sizing_snapshot=_to_jsonable(decision.sizing) if decision.sizing is not None else None,
            failed_data_sources=list(decision.failed_data_sources),
            risk_config_version=None,
            risk_config_sha256=None,
            evaluation_duration_ms=None,
            evaluated_at=decision.evaluated_at,
        )
        try:
            async with self._session_factory() as session:
                session.add(orm)
                await session.flush()
                pk: int = orm.id
                await session.commit()
        except (OperationalError, IntegrityError) as exc:
            raise RiskDecisionPersistenceError(
                f"Failed to persist RiskDecision for signal {decision.signal_id}: {exc}"
            ) from exc
        return pk
