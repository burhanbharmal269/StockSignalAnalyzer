"""Unit tests for SqlAlchemyInstrumentRepository using SQLite in-memory.

Note: save_bulk() uses PostgreSQL-specific ON CONFLICT syntax and is an
integration-only test. The unit tests cover save(), get_by_token(),
get_by_symbol(), get_active_fno(), count_active(), and get_all_tokens().
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.instrument import Instrument
from core.domain.enums.asset_type import AssetType
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.database.repositories.instrument_repository import (
    SqlAlchemyInstrumentRepository,
)


def _make_instrument(
    token: int = 256265,
    ticker: str = "NIFTY",
    asset_type: AssetType = AssetType.FNO,
) -> Instrument:
    return Instrument.create(
        token=token,
        symbol=Symbol(ticker),
        name=f"{ticker} instrument",
        asset_type=asset_type,
        exchange="NSE",
        lot_size=50,
        tick_size=Decimal("0.05"),
    )


class TestInstrumentRepository:
    async def test_save_and_get_by_token(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        inst = _make_instrument(token=111)
        await repo.save(inst)
        loaded = await repo.get_by_token(111)
        assert loaded is not None
        assert loaded.token == 111
        assert loaded.symbol.ticker == "NIFTY"

    async def test_get_by_token_missing_returns_none(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        assert await repo.get_by_token(99999) is None

    async def test_get_by_symbol(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        inst = _make_instrument(token=222, ticker="BANKNIFTY")
        await repo.save(inst)
        loaded = await repo.get_by_symbol(Symbol("BANKNIFTY"))
        assert loaded is not None
        assert loaded.token == 222

    async def test_get_by_symbol_missing_returns_none(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        assert await repo.get_by_symbol(Symbol("UNKNOWN")) is None

    async def test_get_active_fno_filters_correctly(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        fno = _make_instrument(token=1, ticker="NIFTY", asset_type=AssetType.FNO)
        equity = _make_instrument(token=2, ticker="RELIANCE", asset_type=AssetType.EQUITY)
        inactive_fno = _make_instrument(token=3, ticker="BANKNIFTY", asset_type=AssetType.FNO)
        inactive_fno.deactivate()
        await repo.save(fno)
        await repo.save(equity)
        await repo.save(inactive_fno)
        results = await repo.get_active_fno()
        tokens = {r.token for r in results}
        assert 1 in tokens
        assert 2 not in tokens
        assert 3 not in tokens

    async def test_save_deactivate_updates(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        inst = _make_instrument(token=9)
        await repo.save(inst)
        inst.deactivate()
        await repo.save(inst)
        loaded = await repo.get_by_token(9)
        assert loaded is not None
        assert loaded.is_active is False

    async def test_count_active_returns_zero_when_empty(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        assert await repo.count_active() == 0

    async def test_count_active_counts_only_active(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        active = _make_instrument(token=101)
        inactive = _make_instrument(token=102)
        inactive.deactivate()
        await repo.save(active)
        await repo.save(inactive)
        assert await repo.count_active() == 1

    async def test_count_active_counts_multiple(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        for i in range(5):
            await repo.save(_make_instrument(token=200 + i, ticker=f"SYM{i}"))
        assert await repo.count_active() == 5

    async def test_get_all_tokens_returns_empty_set_when_no_rows(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        tokens = await repo.get_all_tokens()
        assert tokens == set()

    async def test_get_all_tokens_includes_all_saved_tokens(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        for token in (301, 302, 303):
            await repo.save(_make_instrument(token=token, ticker=f"SYM{token}"))
        tokens = await repo.get_all_tokens()
        assert {301, 302, 303}.issubset(tokens)

    async def test_get_all_tokens_includes_inactive_instruments(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = SqlAlchemyInstrumentRepository(session_factory)
        inst = _make_instrument(token=401)
        inst.deactivate()
        await repo.save(inst)
        tokens = await repo.get_all_tokens()
        assert 401 in tokens
