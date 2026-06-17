"""SQLAlchemy repository for market_universe."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.market_symbol import MarketSymbol


class SqlAlchemyMarketUniverseRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def upsert(self, symbol: MarketSymbol) -> None:
        async with self._sf() as db:
            await db.execute(text("""
                INSERT INTO market_universe
                    (symbol, name, exchange, segment, sector, industry,
                     is_fo, is_index, is_active, lot_size, instrument_token, isin, meta)
                VALUES
                    (:symbol, :name, :exchange, :segment, :sector, :industry,
                     :is_fo, :is_index, :is_active, :lot_size, :instrument_token, :isin,
                     CAST(:meta AS jsonb))
                ON CONFLICT (symbol) DO UPDATE SET
                    name=EXCLUDED.name, sector=EXCLUDED.sector,
                    industry=EXCLUDED.industry, is_fo=EXCLUDED.is_fo,
                    is_active=EXCLUDED.is_active, lot_size=EXCLUDED.lot_size,
                    instrument_token=EXCLUDED.instrument_token, isin=EXCLUDED.isin,
                    meta=EXCLUDED.meta, updated_at=now()
            """), {
                "symbol": symbol.symbol, "name": symbol.name,
                "exchange": symbol.exchange, "segment": symbol.segment,
                "sector": symbol.sector, "industry": symbol.industry,
                "is_fo": symbol.is_fo, "is_index": symbol.is_index,
                "is_active": symbol.is_active, "lot_size": symbol.lot_size,
                "instrument_token": symbol.instrument_token,
                "isin": symbol.isin,
                "meta": __import__("json").dumps(symbol.meta),
            })
            await db.commit()

    async def upsert_many(self, symbols: list[MarketSymbol]) -> int:
        for s in symbols:
            await self.upsert(s)
        return len(symbols)

    async def get_active(
        self,
        segment: str | None = None,
        fo_only: bool = False,
        index_only: bool = False,
    ) -> list[MarketSymbol]:
        conditions = ["is_active = true"]
        params: dict = {}
        if segment:
            conditions.append("segment = :segment")
            params["segment"] = segment
        if fo_only:
            conditions.append("is_fo = true")
        if index_only:
            conditions.append("is_index = true")
        where = " AND ".join(conditions)
        async with self._sf() as db:
            result = await db.execute(
                text(f"SELECT * FROM market_universe WHERE {where} ORDER BY symbol"),
                params,
            )
            return [_row_to_symbol(r) for r in result.mappings().fetchall()]

    async def get(self, symbol: str) -> MarketSymbol | None:
        async with self._sf() as db:
            result = await db.execute(
                text("SELECT * FROM market_universe WHERE symbol=:sym"),
                {"sym": symbol},
            )
            row = result.mappings().fetchone()
            return _row_to_symbol(row) if row else None

    async def count(self) -> int:
        async with self._sf() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM market_universe WHERE is_active=true"))
            return int(result.scalar() or 0)


def _row_to_symbol(r) -> MarketSymbol:
    import json
    meta = r.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return MarketSymbol(
        symbol=r["symbol"],
        name=r["name"],
        exchange=r["exchange"],
        segment=r["segment"],
        sector=r.get("sector"),
        industry=r.get("industry"),
        is_fo=bool(r["is_fo"]),
        is_index=bool(r["is_index"]),
        is_active=bool(r["is_active"]),
        lot_size=int(r["lot_size"]),
        instrument_token=r.get("instrument_token"),
        isin=r.get("isin"),
        meta=meta,
        added_at=r.get("added_at"),
        updated_at=r.get("updated_at"),
    )
