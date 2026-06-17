"""Unit tests for InstrumentMasterService — refresh, cache, and query logic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.domain.entities.instrument import Instrument
from core.domain.enums.asset_type import AssetType
from core.domain.enums.option_type import OptionType
from core.domain.enums.segment import Segment
from core.domain.value_objects.instrument_refresh_result import RefreshStatus
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.data.expiry_calendar import ExpiryCalendar
from core.infrastructure.data.instrument_master_service import (
    InstrumentMasterService,
    _parse_instrument,
)


def _make_instrument(
    token: int = 256265,
    ticker: str = "NIFTY",
    exchange: str = "NSE",
    lot_size: int = 50,
    asset_type: AssetType = AssetType.FNO,
    underlying: str | None = "NIFTY",
    option_type: str | None = None,
    expiry: date | None = None,
    strike: Decimal | None = None,
    segment: str = "NSE_FO",
) -> Instrument:
    return Instrument(
        instrument_id=__import__("uuid").uuid4(),
        token=token,
        symbol=Symbol(ticker, exchange),
        name=ticker,
        asset_type=asset_type,
        exchange=exchange,
        lot_size=lot_size,
        tick_size=Price(Decimal("0.05")),
        is_active=True,
        expiry=expiry,
        strike=Price(strike) if strike else None,
        instrument_type=option_type or ("FUT" if not option_type else ""),
        segment=segment,
        underlying_symbol=underlying,
        option_type=option_type,
    )


def _make_redis() -> MagicMock:
    r = MagicMock()
    r.hgetall = AsyncMock(return_value={})
    r.hset = AsyncMock()
    r.set = AsyncMock()
    r.zadd = AsyncMock()
    r.zrange = AsyncMock(return_value=[])
    r.pipeline = MagicMock(return_value=MagicMock(
        hset=MagicMock(),
        set=MagicMock(),
        zadd=MagicMock(),
        execute=AsyncMock(return_value=[]),
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    return r


def _make_repo(instruments: list[Instrument] | None = None) -> MagicMock:
    repo = MagicMock()
    repo.get_by_token = AsyncMock(return_value=None)
    repo.get_by_symbol = AsyncMock(return_value=None)
    repo.get_active_fno = AsyncMock(return_value=instruments or [])
    repo.save = AsyncMock()
    repo.save_bulk = AsyncMock()
    return repo


def _make_service(
    raw_rows: list[dict[str, str]] | None = None,
    db_instruments: list[Instrument] | None = None,
) -> InstrumentMasterService:
    data_provider = MagicMock()
    data_provider.download_instruments = AsyncMock(return_value=raw_rows or [])
    repo = _make_repo(db_instruments)
    redis = _make_redis()
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()
    session_factory = MagicMock()
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session_factory.return_value = session
    calendar = ExpiryCalendar()
    return InstrumentMasterService(
        data_provider=data_provider,
        instrument_repository=repo,
        redis_client=redis,
        event_bus=event_bus,
        session_factory=session_factory,
        expiry_calendar=calendar,
        exchanges=["NSE"],
    )


def _make_csv_rows(count: int = 10001) -> list[dict[str, str]]:
    rows = []
    for i in range(count):
        rows.append({
            "instrument_token": str(i + 1),
            "tradingsymbol": f"SYM{i}",
            "exchange": "NSE",
            "name": f"Stock {i}",
            "lot_size": "1",
            "tick_size": "0.05",
            "expiry": "",
            "strike": "",
            "instrument_type": "EQ",
            "segment": "NSE_EQ",
            "isin": "",
        })
    return rows


class TestParseInstrument:
    def test_parses_equity_row(self) -> None:
        row = {
            "instrument_token": "738561",
            "tradingsymbol": "RELIANCE",
            "exchange": "NSE",
            "name": "Reliance Industries",
            "lot_size": "1",
            "tick_size": "0.05",
            "expiry": "",
            "strike": "",
            "instrument_type": "EQ",
            "segment": "NSE_EQ",
            "isin": "INE002A01018",
        }
        inst = _parse_instrument(row)
        assert inst is not None
        assert inst.token == 738561
        assert inst.symbol.ticker == "RELIANCE"
        assert inst.lot_size == 1
        assert inst.isin == "INE002A01018"

    def test_parses_option_row(self) -> None:
        row = {
            "instrument_token": "12345",
            "tradingsymbol": "NIFTY25JUN23000CE",
            "exchange": "NFO",
            "name": "NIFTY",
            "lot_size": "50",
            "tick_size": "0.05",
            "expiry": "2025-06-26",
            "strike": "23000",
            "instrument_type": "CE",
            "segment": "NFO",
        }
        inst = _parse_instrument(row)
        assert inst is not None
        assert inst.option_type == "CE"
        assert inst.underlying_symbol == "NIFTY"
        assert inst.expiry == date(2025, 6, 26)
        assert inst.strike is not None
        assert inst.strike.value == Decimal("23000")

    def test_returns_none_for_missing_token(self) -> None:
        assert _parse_instrument({"tradingsymbol": "X"}) is None

    def test_invalid_lot_size_defaults_to_one(self) -> None:
        row = {
            "instrument_token": "1",
            "tradingsymbol": "TEST",
            "exchange": "NSE",
            "name": "Test",
            "lot_size": "",
            "tick_size": "0.05",
            "expiry": "",
            "strike": "",
            "instrument_type": "EQ",
            "segment": "NSE_EQ",
        }
        inst = _parse_instrument(row)
        assert inst is not None
        assert inst.lot_size == 1


class TestRefreshValidation:
    async def test_refresh_fails_if_insufficient_rows(self) -> None:
        svc = _make_service(raw_rows=_make_csv_rows(5000))
        result = await svc.refresh()
        assert result.status == RefreshStatus.FAILED

    async def test_refresh_succeeds_with_sufficient_rows(self) -> None:
        svc = _make_service(raw_rows=_make_csv_rows(12000))
        result = await svc.refresh()
        assert result.status == RefreshStatus.SUCCESS

    async def test_refresh_counts_added(self) -> None:
        svc = _make_service(raw_rows=_make_csv_rows(11000))
        result = await svc.refresh()
        assert result.instruments_added > 0

    async def test_refresh_publishes_event(self) -> None:
        svc = _make_service(raw_rows=_make_csv_rows(11000))
        await svc.refresh()
        svc._event_bus.publish.assert_awaited_once()

    async def test_refresh_logs_to_db(self) -> None:
        svc = _make_service(raw_rows=_make_csv_rows(11000))
        await svc.refresh()
        svc._session_factory.return_value.commit.assert_awaited()

    async def test_lot_size_change_makes_status_partial(self) -> None:
        rows = _make_csv_rows(11000)
        # Make the first instrument have lot_size=1 in CSV but 100 in DB
        rows[0]["lot_size"] = "100"
        rows[0]["instrument_token"] = "999999"

        existing = _make_instrument(token=999999, lot_size=50)
        repo = _make_repo(instruments=[existing])
        repo.get_by_token = AsyncMock(side_effect=lambda t: existing if t == 999999 else None)

        data_provider = MagicMock()
        data_provider.download_instruments = AsyncMock(return_value=rows)
        redis = _make_redis()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()
        session = MagicMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session_factory = MagicMock(return_value=session)

        svc = InstrumentMasterService(
            data_provider=data_provider,
            instrument_repository=repo,
            redis_client=redis,
            event_bus=event_bus,
            session_factory=session_factory,
            expiry_calendar=ExpiryCalendar(),
            exchanges=["NSE"],
        )
        result = await svc.refresh()
        assert result.status == RefreshStatus.PARTIAL
        assert result.has_lot_size_changes is True


class TestGetByToken:
    async def test_returns_from_cache_if_available(self) -> None:
        svc = _make_service()
        cache_data = {
            "token": "256265",
            "ticker": "NIFTY",
            "exchange": "NSE",
            "name": "NIFTY 50",
            "asset_type": "FNO",
            "lot_size": "50",
            "tick_size": "0.05",
            "is_active": "1",
            "expiry": "",
            "strike": "",
            "instrument_type": "FUT",
            "segment": "NSE_FO",
            "underlying_symbol": "NIFTY",
            "option_type": "",
        }
        svc._redis.hgetall = AsyncMock(return_value=cache_data)
        inst = await svc.get_by_token(256265)
        assert inst.token == 256265

    async def test_falls_back_to_db_on_cache_miss(self) -> None:
        svc = _make_service()
        db_instrument = _make_instrument(token=256265)
        svc._repo.get_by_token = AsyncMock(return_value=db_instrument)
        inst = await svc.get_by_token(256265)
        assert inst.token == 256265

    async def test_raises_key_error_if_not_found(self) -> None:
        svc = _make_service()
        svc._repo.get_by_token = AsyncMock(return_value=None)
        with pytest.raises(KeyError):
            await svc.get_by_token(999)


class TestGetNextExpiry:
    async def test_returns_nearest_upcoming_expiry(self) -> None:
        today = date.today()
        future_expiry = date(today.year + 1, 1, 31)
        inst = _make_instrument(
            token=1,
            underlying="NIFTY",
            segment="NSE_FO",
            expiry=future_expiry,
        )
        svc = _make_service()
        svc._repo.get_active_fno = AsyncMock(return_value=[inst])
        expiry = await svc.get_next_expiry("NIFTY", Segment.NSE_FO)
        assert expiry == future_expiry

    async def test_raises_when_no_expiry_available(self) -> None:
        svc = _make_service()
        svc._repo.get_active_fno = AsyncMock(return_value=[])
        with pytest.raises(ValueError):
            await svc.get_next_expiry("NIFTY", Segment.NSE_FO)


class TestIsTradingDay:
    def test_delegates_to_calendar(self) -> None:
        svc = _make_service()
        # Monday 2025-06-16
        assert svc.is_trading_day(date(2025, 6, 16)) is True
        assert svc.is_trading_day(date(2025, 6, 14)) is False  # Saturday


class TestGetDte:
    def test_dte_for_future_instrument(self) -> None:
        svc = _make_service()
        expiry = date(2099, 12, 31)
        inst = _make_instrument(expiry=expiry)
        dte = svc.get_dte(inst)
        assert dte > 0

    def test_dte_zero_for_no_expiry(self) -> None:
        svc = _make_service()
        inst = _make_instrument(expiry=None)
        assert svc.get_dte(inst) == 0


class TestFindOption:
    async def test_finds_matching_option(self) -> None:
        expiry = date(2025, 6, 26)
        strike = Decimal("23000")
        inst = _make_instrument(
            token=12345,
            underlying="NIFTY",
            option_type="CE",
            expiry=expiry,
            strike=strike,
        )
        svc = _make_service()
        svc._repo.get_active_fno = AsyncMock(return_value=[inst])
        found = await svc.find_option("NIFTY", expiry, strike, OptionType.CE)
        assert found.token == 12345

    async def test_raises_key_error_if_not_found(self) -> None:
        svc = _make_service()
        svc._repo.get_active_fno = AsyncMock(return_value=[])
        with pytest.raises(KeyError):
            await svc.find_option(
                "NIFTY", date(2025, 6, 26), Decimal("23000"), OptionType.CE
            )
