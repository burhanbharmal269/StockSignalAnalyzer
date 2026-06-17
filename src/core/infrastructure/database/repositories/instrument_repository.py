"""SQLAlchemy implementation of IInstrumentRepository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.instrument import Instrument
from core.domain.enums.asset_type import AssetType
from core.domain.interfaces.i_instrument_repository import IInstrumentRepository
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.database.models.instrument_models import InstrumentOrm


def _to_orm(instrument: Instrument) -> InstrumentOrm:
    return InstrumentOrm(
        instrument_id=instrument.instrument_id,
        token=instrument.token,
        ticker=instrument.symbol.ticker,
        exchange=instrument.symbol.exchange,
        name=instrument.name,
        asset_type=instrument.asset_type.value,
        lot_size=instrument.lot_size,
        tick_size=instrument.tick_size.value,
        is_active=instrument.is_active,
        expiry=instrument.expiry,
        strike=instrument.strike.value if instrument.strike else None,
        instrument_type=instrument.instrument_type,
        segment=instrument.segment,
        underlying_symbol=instrument.underlying_symbol,
        option_type=instrument.option_type,
        isin=instrument.isin,
        display_symbol=instrument.display_symbol,
    )


def _to_domain(row: InstrumentOrm) -> Instrument:
    return Instrument(
        instrument_id=row.instrument_id,
        token=row.token,
        symbol=Symbol(row.ticker, row.exchange),
        name=row.name,
        asset_type=AssetType(row.asset_type),
        exchange=row.exchange,
        lot_size=row.lot_size,
        tick_size=Price(row.tick_size),
        is_active=row.is_active,
        expiry=row.expiry,
        strike=Price(row.strike) if row.strike is not None else None,
        instrument_type=row.instrument_type,
        segment=row.segment,
        underlying_symbol=row.underlying_symbol,
        option_type=row.option_type,
        isin=row.isin,
        display_symbol=row.display_symbol,
    )


class SqlAlchemyInstrumentRepository(IInstrumentRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, instrument: Instrument) -> None:
        async with self._session_factory() as session:
            existing = await session.get(InstrumentOrm, instrument.instrument_id)
            if existing is None:
                session.add(_to_orm(instrument))
            else:
                orm = _to_orm(instrument)
                existing.lot_size = orm.lot_size
                existing.tick_size = orm.tick_size
                existing.is_active = orm.is_active
                existing.expiry = orm.expiry
                existing.strike = orm.strike
                existing.instrument_type = orm.instrument_type
                existing.updated_at = datetime.now()  # noqa: DTZ005
            await session.commit()

    async def save_bulk(self, instruments: list[Instrument]) -> None:
        """Upsert a batch. Uses PostgreSQL ON CONFLICT for atomic refresh."""
        if not instruments:
            return
        async with self._session_factory() as session:
            for instrument in instruments:
                stmt = (
                    pg_insert(InstrumentOrm)
                    .values(
                        instrument_id=instrument.instrument_id,
                        token=instrument.token,
                        ticker=instrument.symbol.ticker,
                        exchange=instrument.symbol.exchange,
                        name=instrument.name,
                        asset_type=instrument.asset_type.value,
                        lot_size=instrument.lot_size,
                        tick_size=instrument.tick_size.value,
                        is_active=instrument.is_active,
                        expiry=instrument.expiry,
                        strike=instrument.strike.value if instrument.strike else None,
                        instrument_type=instrument.instrument_type,
                        segment=instrument.segment,
                        underlying_symbol=instrument.underlying_symbol,
                        option_type=instrument.option_type,
                        isin=instrument.isin,
                        display_symbol=instrument.display_symbol,
                    )
                    .on_conflict_do_update(
                        index_elements=["token"],
                        set_={
                            "lot_size": instrument.lot_size,
                            "tick_size": instrument.tick_size.value,
                            "is_active": instrument.is_active,
                            "expiry": instrument.expiry,
                            "strike": instrument.strike.value if instrument.strike else None,
                            "instrument_type": instrument.instrument_type,
                            "segment": instrument.segment,
                            "underlying_symbol": instrument.underlying_symbol,
                            "option_type": instrument.option_type,
                            "isin": instrument.isin,
                            "display_symbol": instrument.display_symbol,
                        },
                    )
                )
                await session.execute(stmt)
            await session.commit()

    async def get_by_token(self, token: int) -> Instrument | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(InstrumentOrm).where(InstrumentOrm.token == token)
            )
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def get_by_symbol(self, symbol: Symbol) -> Instrument | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(InstrumentOrm).where(
                    InstrumentOrm.ticker == symbol.ticker,
                    InstrumentOrm.exchange == symbol.exchange,
                )
            )
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def get_active_fno(self) -> list[Instrument]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(InstrumentOrm).where(
                    InstrumentOrm.is_active.is_(True),
                    InstrumentOrm.asset_type == AssetType.FNO.value,
                )
            )
            return [_to_domain(r) for r in result.scalars()]

    async def count_active(self) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count()).where(InstrumentOrm.is_active.is_(True))
            )
            return result.scalar_one()

    async def get_all_tokens(self) -> set[int]:
        async with self._session_factory() as session:
            result = await session.execute(select(InstrumentOrm.token))
            return set(result.scalars())
