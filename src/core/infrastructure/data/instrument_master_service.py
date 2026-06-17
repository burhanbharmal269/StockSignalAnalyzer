"""InstrumentMasterService — daily refresh, Redis cache, and query operations.

Implements IInstrumentMasterService. Orchestrates:
  1. Download from IDataProvider
  2. Validate (>10,000 rows)
  3. Diff against DB (detect lot size changes)
  4. Upsert instruments; deactivate removed
  5. Rebuild Redis cache
  6. Publish InstrumentMasterRefreshed event
  7. Write to instrument_refresh_log

Reference: docs/13_INSTRUMENT_MASTER.md
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from core.domain.entities.instrument import Instrument
from core.domain.enums.asset_type import AssetType
from core.domain.enums.option_type import OptionType
from core.domain.enums.segment import Segment
from core.domain.events.system_events import InstrumentMasterRefreshed
from core.domain.interfaces.i_instrument_master import IInstrumentMasterService
from core.domain.value_objects.instrument_refresh_result import (
    InstrumentRefreshResult,
    LotSizeChange,
    RefreshStatus,
)
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.data.expiry_calendar import ExpiryCalendar
from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from core.domain.interfaces.i_event_bus import IEventBus
    from core.domain.interfaces.i_instrument_provider import IInstrumentProvider
    from core.domain.interfaces.i_instrument_repository import IInstrumentRepository

logger = get_logger(__name__)

_MIN_INSTRUMENT_COUNT = 10_000
_REDIS_INSTRUMENT_KEY = "instrument:{token}"
_REDIS_SYMBOL_KEY = "instrument:symbol:{exchange}:{tradingsymbol}"
_REDIS_CHAIN_KEY = "instrument:chain:{underlying}:{expiry}"
_REFRESH_SOURCE = "kite_csv"


class InstrumentMasterService(IInstrumentMasterService):
    """Full implementation of IInstrumentMasterService.

    Depends on:
    - IDataProvider   — fetches raw CSV rows
    - IInstrumentRepository — persists instruments
    - redis.asyncio.Redis   — caches instruments for sub-ms access
    - IEventBus             — publishes InstrumentMasterRefreshed
    - async_sessionmaker    — for writing refresh log records
    - ExpiryCalendar        — injected, holiday-aware
    """

    def __init__(
        self,
        data_provider: IInstrumentProvider,
        instrument_repository: IInstrumentRepository,
        redis_client: Redis,  # type: ignore[type-arg]
        event_bus: IEventBus,
        session_factory: async_sessionmaker[AsyncSession],
        expiry_calendar: ExpiryCalendar,
        exchanges: list[str] | None = None,
    ) -> None:
        self._data_provider = data_provider
        self._repo = instrument_repository
        self._redis = redis_client
        self._event_bus = event_bus
        self._session_factory = session_factory
        self._calendar = expiry_calendar
        self._exchanges = exchanges or ["NSE", "NFO", "BSE", "BFO", "MCX", "CDS"]

    # ------------------------------------------------------------------
    # IInstrumentMasterService — query operations
    # ------------------------------------------------------------------

    async def get_by_token(self, token: int) -> Instrument:
        cached = await self._get_from_cache(token)
        if cached is not None:
            return cached
        instrument = await self._repo.get_by_token(token)
        if instrument is None:
            msg = f"Instrument with token {token} not found"
            raise KeyError(msg)
        return instrument

    async def get_by_symbol(self, exchange: str, tradingsymbol: str) -> Instrument:
        symbol = Symbol(tradingsymbol.upper(), exchange.upper())
        instrument = await self._repo.get_by_symbol(symbol)
        if instrument is None:
            msg = f"Instrument {exchange}:{tradingsymbol} not found"
            raise KeyError(msg)
        return instrument

    async def find_option(
        self,
        underlying: str,
        expiry: date,
        strike: Decimal,
        option_type: OptionType,
    ) -> Instrument:
        instruments = await self.get_option_chain(underlying, expiry)
        for inst in instruments:
            if (
                inst.strike is not None
                and inst.strike.value == strike
                and inst.option_type == option_type.value
            ):
                return inst
        msg = f"Option not found: {underlying} {expiry} {strike} {option_type}"
        raise KeyError(msg)

    async def get_option_chain(self, underlying: str, expiry: date) -> list[Instrument]:
        chain_key = _REDIS_CHAIN_KEY.format(
            underlying=underlying.upper(), expiry=expiry.isoformat()
        )
        token_strings: list[str] = await self._redis.zrange(chain_key, 0, -1)
        if token_strings:
            instruments = []
            for token_str in token_strings:
                try:
                    inst = await self.get_by_token(int(token_str))
                    instruments.append(inst)
                except (KeyError, ValueError):
                    logger.warning(
                        "instrument_master.cache.stale_token",
                        token=token_str,
                    )
            return instruments
        # Fallback to DB query
        all_active = await self._repo.get_active_fno()
        return [
            i
            for i in all_active
            if i.underlying_symbol == underlying.upper()
            and i.expiry == expiry
            and i.option_type is not None
        ]

    async def get_all_expiries(self, underlying: str, segment: Segment) -> list[date]:
        instruments = await self._repo.get_active_fno()
        expiries = {
            i.expiry
            for i in instruments
            if i.underlying_symbol == underlying.upper()
            and i.segment == segment.value
            and i.expiry is not None
        }
        return sorted(expiries)

    async def get_next_expiry(self, underlying: str, segment: Segment) -> date:
        today = date.today()
        expiries = await self.get_all_expiries(underlying, segment)
        upcoming = [e for e in expiries if e >= today]
        if not upcoming:
            msg = f"No active expiry for {underlying} in {segment}"
            raise ValueError(msg)
        return upcoming[0]

    async def get_monthly_expiry(
        self, underlying: str, segment: Segment, month: date
    ) -> date:
        all_expiries = await self.get_all_expiries(underlying, segment)
        for expiry in all_expiries:
            if expiry.year == month.year and expiry.month == month.month:
                return expiry
        computed = self._calendar.get_monthly_expiry(
            underlying, month.year, month.month
        )
        return computed

    async def get_lot_size(self, underlying: str, segment: Segment) -> int:
        instruments = await self._repo.get_active_fno()
        for inst in instruments:
            if (
                inst.underlying_symbol == underlying.upper()
                and inst.segment == segment.value
            ):
                return inst.lot_size
        msg = f"Underlying {underlying} not found in {segment}"
        raise KeyError(msg)

    async def get_atm_strike(
        self, underlying: str, expiry: date, ltp: Decimal
    ) -> Decimal:
        chain = await self.get_option_chain(underlying, expiry)
        if not chain:
            msg = f"No option chain for {underlying} {expiry}"
            raise ValueError(msg)
        strikes = sorted(
            {i.strike.value for i in chain if i.strike is not None}
        )
        interval = await self.get_strike_interval(underlying)
        atm = round(ltp / interval) * interval
        # Clamp to available strikes
        if atm < strikes[0]:
            return strikes[0]
        if atm > strikes[-1]:
            return strikes[-1]
        return atm

    async def get_strike_interval(self, underlying: str) -> Decimal:
        instruments = await self._repo.get_active_fno()
        strikes = sorted(
            {i.strike.value for i in instruments
             if i.underlying_symbol == underlying.upper()
             and i.strike is not None}
        )
        if len(strikes) < 2:
            # Default intervals for well-known underlyings
            _known_intervals: dict[str, Decimal] = {
                "NIFTY": Decimal("50"),
                "BANKNIFTY": Decimal("100"),
                "FINNIFTY": Decimal("50"),
                "MIDCPNIFTY": Decimal("25"),
                "SENSEX": Decimal("100"),
            }
            return _known_intervals.get(underlying.upper(), Decimal("50"))
        return strikes[1] - strikes[0]

    def is_trading_day(self, check_date: date) -> bool:
        return self._calendar.is_trading_day(check_date)

    def get_dte(self, instrument: Instrument) -> int:
        if instrument.expiry is None:
            return 0
        return self._calendar.get_dte(instrument.expiry)

    # ------------------------------------------------------------------
    # Refresh lifecycle
    # ------------------------------------------------------------------

    async def refresh(self) -> InstrumentRefreshResult:
        start_ms = int(time.monotonic() * 1000)
        logger.info("instrument_master.refresh.start", exchanges=self._exchanges)

        added = updated = deactivated = 0
        lot_size_changes: list[LotSizeChange] = []

        try:
            raw_rows: list[dict[str, str]] = []
            for exchange in self._exchanges:
                rows = await self._data_provider.download_instruments(exchange)
                raw_rows.extend(rows)

            if len(raw_rows) < _MIN_INSTRUMENT_COUNT:
                error = (
                    f"Refresh aborted: only {len(raw_rows)} instruments returned "
                    f"(minimum {_MIN_INSTRUMENT_COUNT})"
                )
                logger.error("instrument_master.refresh.insufficient_rows", count=len(raw_rows))
                result = InstrumentRefreshResult(
                    status=RefreshStatus.FAILED,
                    instruments_added=0,
                    instruments_updated=0,
                    instruments_deactivated=0,
                    duration_ms=int(time.monotonic() * 1000) - start_ms,
                    error_detail=error,
                )
                await self._log_refresh(result)
                return result

            instruments = [
                _parse_instrument(row) for row in raw_rows if row.get("instrument_token")
            ]
            instruments = [i for i in instruments if i is not None]

            incoming_tokens = {i.token for i in instruments}

            for instrument in instruments:
                existing = await self._repo.get_by_token(instrument.token)
                if existing is None:
                    added += 1
                else:
                    if existing.lot_size != instrument.lot_size:
                        lot_size_changes.append(
                            LotSizeChange(
                                token=instrument.token,
                                tradingsymbol=instrument.symbol.ticker,
                                old_lot_size=existing.lot_size,
                                new_lot_size=instrument.lot_size,
                            )
                        )
                    updated += 1

            if lot_size_changes:
                logger.critical(
                    "instrument_master.lot_size_changes_detected",
                    count=len(lot_size_changes),
                    changes=[
                        {
                            "token": c.token,
                            "symbol": c.tradingsymbol,
                            "old": c.old_lot_size,
                            "new": c.new_lot_size,
                        }
                        for c in lot_size_changes
                    ],
                )

            await self._repo.save_bulk(instruments)

            active_existing = await self._repo.get_active_fno()
            for existing in active_existing:
                if existing.token not in incoming_tokens:
                    existing.deactivate()
                    await self._repo.save(existing)
                    deactivated += 1

            await self._rebuild_cache(instruments)

            status = RefreshStatus.PARTIAL if lot_size_changes else RefreshStatus.SUCCESS
            duration = int(time.monotonic() * 1000) - start_ms

            result = InstrumentRefreshResult(
                status=status,
                instruments_added=added,
                instruments_updated=updated,
                instruments_deactivated=deactivated,
                duration_ms=duration,
                lot_size_changes=lot_size_changes,
            )

            await self._event_bus.publish(
                InstrumentMasterRefreshed(
                    event_id=uuid.uuid4(),
                    status=status,
                    instruments_added=added,
                    instruments_updated=updated,
                    instruments_deactivated=deactivated,
                    duration_ms=duration,
                    lot_size_changes_count=len(lot_size_changes),
                )
            )

        except Exception as exc:
            logger.exception("instrument_master.refresh.failed")
            result = InstrumentRefreshResult(
                status=RefreshStatus.FAILED,
                instruments_added=added,
                instruments_updated=updated,
                instruments_deactivated=deactivated,
                duration_ms=int(time.monotonic() * 1000) - start_ms,
                error_detail=str(exc),
            )

        await self._log_refresh(result)
        logger.info(
            "instrument_master.refresh.complete",
            status=result.status,
            added=result.instruments_added,
            updated=result.instruments_updated,
            deactivated=result.instruments_deactivated,
            duration_ms=result.duration_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_from_cache(self, token: int) -> Instrument | None:
        key = _REDIS_INSTRUMENT_KEY.format(token=token)
        data: dict[str, str] = await self._redis.hgetall(key)
        if not data:
            return None
        try:
            return _instrument_from_cache(data)
        except Exception:
            logger.warning("instrument_master.cache.deserialize_error", token=token)
            return None

    async def _rebuild_cache(self, instruments: list[Instrument]) -> None:
        """Populate Redis hashes and symbol-lookup keys."""
        pipe = self._redis.pipeline()
        for inst in instruments:
            token_key = _REDIS_INSTRUMENT_KEY.format(token=inst.token)
            symbol_key = _REDIS_SYMBOL_KEY.format(
                exchange=inst.exchange.upper(),
                tradingsymbol=inst.symbol.ticker.upper(),
            )
            fields = _instrument_to_cache_fields(inst)
            pipe.hset(token_key, mapping=fields)  # type: ignore[arg-type]
            pipe.set(symbol_key, str(inst.token))

            # Option chain sorted set (score = strike price)
            if inst.underlying_symbol and inst.expiry and inst.option_type:
                chain_key = _REDIS_CHAIN_KEY.format(
                    underlying=inst.underlying_symbol.upper(),
                    expiry=inst.expiry.isoformat(),
                )
                strike_score = float(inst.strike.value) if inst.strike else 0.0
                pipe.zadd(chain_key, {str(inst.token): strike_score})

        await pipe.execute()
        logger.info(
            "instrument_master.cache.rebuilt",
            instrument_count=len(instruments),
        )

    async def _log_refresh(self, result: InstrumentRefreshResult) -> None:
        from core.infrastructure.database.models.instrument_models import (
            InstrumentRefreshLogOrm,
        )

        log_entry = InstrumentRefreshLogOrm(
            refreshed_at=datetime.now(UTC),
            source=_REFRESH_SOURCE,
            instruments_added=result.instruments_added,
            instruments_updated=result.instruments_updated,
            instruments_deactivated=result.instruments_deactivated,
            status=result.status.value,
            error_detail=result.error_detail or None,
            duration_ms=result.duration_ms,
        )
        try:
            async with self._session_factory() as session:
                session.add(log_entry)
                await session.commit()
        except Exception:
            logger.exception("instrument_master.refresh_log.write_failed")


# ---------------------------------------------------------------------------
# CSV row → Instrument mapping
# ---------------------------------------------------------------------------

def _parse_instrument(row: dict[str, str]) -> Instrument | None:
    """Convert a raw Kite CSV row dict into an Instrument domain entity."""
    try:
        token = int(row["instrument_token"])
        ticker = (row.get("tradingsymbol") or "").strip().upper()
        exchange = (row.get("exchange") or "").strip().upper()
        name = (row.get("name") or "").strip()
        lot_size = int(row.get("lot_size") or 1)
        tick_size_str = row.get("tick_size") or "0.05"
        try:
            tick_size = Decimal(tick_size_str)
        except InvalidOperation:
            tick_size = Decimal("0.05")

        expiry: date | None = None
        expiry_str = (row.get("expiry") or "").strip()
        if expiry_str:
            try:
                expiry = date.fromisoformat(expiry_str)
            except ValueError:
                pass

        strike: Decimal | None = None
        strike_str = (row.get("strike") or "").strip()
        if strike_str and strike_str != "0":
            try:
                strike = Decimal(strike_str)
            except InvalidOperation:
                pass

        instrument_type = (row.get("instrument_type") or "").strip().upper()
        segment = (row.get("segment") or "").strip().upper()

        # Determine option_type from instrument_type
        option_type: str | None = None
        if instrument_type in {"CE", "PE"}:
            option_type = instrument_type

        # Map to AssetType
        if instrument_type in {"CE", "PE", "FUT"} or segment in {
            "NSE-FO", "NFO", "BSE-FO", "BFO", "MCX-FO", "CDS-FO", "NFO-FUT",
            "NFO-OPT",
        }:
            asset_type = AssetType.FNO
        elif segment in {"MCX-FO", "MCX_FO"}:
            asset_type = AssetType.COMMODITY
        elif segment in {"CDS-FO", "CDS_FO"}:
            asset_type = AssetType.CURRENCY
        else:
            asset_type = AssetType.EQUITY

        # Normalise segment to our enum values (Kite uses "NSE-FO" vs our "NSE_FO")
        segment = segment.replace("-", "_")

        # underlying_symbol is the root index/stock symbol for derivatives
        underlying_symbol: str | None = None
        if instrument_type in {"CE", "PE", "FUT"} and name:
            underlying_symbol = name.strip().upper()

        symbol = Symbol(ticker, exchange)
        return Instrument.create(
            token=token,
            symbol=symbol,
            name=name,
            asset_type=asset_type,
            exchange=exchange,
            lot_size=lot_size,
            tick_size=tick_size,
            expiry=expiry,
            strike=strike,
            instrument_type=instrument_type,
            segment=segment,
            underlying_symbol=underlying_symbol,
            option_type=option_type,
            isin=row.get("isin") or None,
            display_symbol="",
        )
    except Exception:
        logger.warning("instrument_master.parse.skipped_row", row=row)
        return None


def _instrument_to_cache_fields(inst: Instrument) -> dict[str, str]:
    return {
        "token": str(inst.token),
        "ticker": inst.symbol.ticker,
        "exchange": inst.exchange,
        "name": inst.name,
        "asset_type": inst.asset_type.value,
        "lot_size": str(inst.lot_size),
        "tick_size": str(inst.tick_size.value),
        "is_active": "1" if inst.is_active else "0",
        "expiry": inst.expiry.isoformat() if inst.expiry else "",
        "strike": str(inst.strike.value) if inst.strike else "",
        "instrument_type": inst.instrument_type,
        "segment": inst.segment,
        "underlying_symbol": inst.underlying_symbol or "",
        "option_type": inst.option_type or "",
    }


def _instrument_from_cache(data: dict[str, str]) -> Instrument:
    token = int(data["token"])
    ticker = data["ticker"]
    exchange = data["exchange"]
    name = data.get("name", "")
    asset_type = AssetType(data["asset_type"])
    lot_size = int(data["lot_size"])
    tick_size = Decimal(data["tick_size"])
    is_active = data.get("is_active", "1") == "1"
    expiry_str = data.get("expiry", "")
    expiry = date.fromisoformat(expiry_str) if expiry_str else None
    strike_str = data.get("strike", "")
    strike = Decimal(strike_str) if strike_str else None
    instrument_type = data.get("instrument_type", "")
    segment = data.get("segment", "")
    underlying_symbol = data.get("underlying_symbol") or None
    option_type = data.get("option_type") or None

    return Instrument(
        instrument_id=uuid.uuid4(),
        token=token,
        symbol=Symbol(ticker, exchange),
        name=name,
        asset_type=asset_type,
        exchange=exchange,
        lot_size=lot_size,
        tick_size=Price(tick_size),
        is_active=is_active,
        expiry=expiry,
        strike=Price(strike) if strike else None,
        instrument_type=instrument_type,
        segment=segment,
        underlying_symbol=underlying_symbol,
        option_type=option_type,
    )
