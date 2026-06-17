"""SQLAlchemy implementation of IRegimeRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.enums.market_regime import MarketRegime
from core.domain.interfaces.i_regime_repository import IRegimeRepository
from core.domain.value_objects.regime_snapshot import RegimeSnapshot
from core.infrastructure.database.models.regime_models import RegimeSnapshotOrm


def _to_domain(row: RegimeSnapshotOrm) -> RegimeSnapshot:
    evaluated_at = row.evaluated_at
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=UTC)

    explanation_raw = row.explanation or []
    if isinstance(explanation_raw, list):
        explanation = tuple(str(e) for e in explanation_raw)
    else:
        explanation = ()

    return RegimeSnapshot(
        instrument_token=row.instrument_token,
        timeframe=row.timeframe,
        primary_regime=MarketRegime(row.primary_regime),
        secondary_regime=MarketRegime(row.secondary_regime) if row.secondary_regime else None,
        direction_layer=row.direction_layer,
        volatility_layer=row.volatility_layer,
        confidence=row.confidence,
        score=row.score,
        stability_score=row.stability_score,
        regime_duration_bars=row.regime_duration_bars,
        transition_signal=bool(row.transition_signal),
        explanation=explanation,
        evaluated_at=evaluated_at,
    )


class SqlAlchemyRegimeRepository(IRegimeRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, snapshot: RegimeSnapshot) -> None:
        async with self._session_factory() as db:
            db.add(
                RegimeSnapshotOrm(
                    instrument_token=snapshot.instrument_token,
                    timeframe=snapshot.timeframe,
                    primary_regime=snapshot.primary_regime.value,
                    secondary_regime=(
                        snapshot.secondary_regime.value
                        if snapshot.secondary_regime
                        else None
                    ),
                    direction_layer=snapshot.direction_layer,
                    volatility_layer=snapshot.volatility_layer,
                    confidence=snapshot.confidence,
                    score=snapshot.score,
                    stability_score=snapshot.stability_score,
                    regime_duration_bars=snapshot.regime_duration_bars,
                    transition_signal=int(snapshot.transition_signal),
                    explanation=list(snapshot.explanation),
                    evaluated_at=snapshot.evaluated_at,
                )
            )
            await db.commit()

    async def get_latest(
        self,
        instrument_token: int,
        timeframe: str,
    ) -> RegimeSnapshot | None:
        async with self._session_factory() as db:
            result = await db.execute(
                select(RegimeSnapshotOrm)
                .where(
                    RegimeSnapshotOrm.instrument_token == instrument_token,
                    RegimeSnapshotOrm.timeframe == timeframe,
                )
                .order_by(RegimeSnapshotOrm.evaluated_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def get_history(
        self,
        instrument_token: int,
        timeframe: str,
        since: datetime,
    ) -> list[RegimeSnapshot]:
        async with self._session_factory() as db:
            result = await db.execute(
                select(RegimeSnapshotOrm)
                .where(
                    RegimeSnapshotOrm.instrument_token == instrument_token,
                    RegimeSnapshotOrm.timeframe == timeframe,
                    RegimeSnapshotOrm.evaluated_at >= since,
                )
                .order_by(RegimeSnapshotOrm.evaluated_at.asc())
            )
            rows = result.scalars().all()
            return [_to_domain(r) for r in rows]
