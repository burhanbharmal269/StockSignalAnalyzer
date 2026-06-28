"""MarketUniverseService — manages the full tradeable universe (500+ symbols).

Seeds the database with standard NSE indices and F&O stocks.
Syncs instrument list from Kite when available.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.domain.entities.market_symbol import MarketSymbol

if TYPE_CHECKING:
    from core.domain.interfaces.i_market_data_provider import IMarketDataProvider
    from core.infrastructure.database.repositories.market_universe_repository import (
        SqlAlchemyMarketUniverseRepository,
    )

_log = logging.getLogger(__name__)

# Core indices — is_fo=True means they trade as futures (scannable)
_INDICES = [
    # Tradeable index futures
    ("NIFTY 50",          "NIFTY",         True),
    ("NIFTY BANK",        "BANKNIFTY",     True),
    ("NIFTY FIN SERVICE", "FINNIFTY",      True),
    ("NIFTY MIDCAP SELECT","MIDCPNIFTY",   True),
    # Reference indices (no futures)
    ("NIFTY NEXT 50",     "NIFTYNXT50",    False),
    ("INDIA VIX",         "INDIAVIX",      False),
    ("NIFTY 100",         "NIFTY100",      False),
    ("NIFTY 200",         "NIFTY200",      False),
    ("NIFTY 500",         "NIFTY500",      False),
    ("NIFTY AUTO",        "NIFTYAUTO",     False),
    ("NIFTY FMCG",        "NIFTYFMCG",     False),
    ("NIFTY IT",          "NIFTYIT",       False),
    ("NIFTY MEDIA",       "NIFTYMEDIA",    False),
    ("NIFTY METAL",       "NIFTYMETAL",    False),
    ("NIFTY PHARMA",      "NIFTYPHARMA",   False),
    ("NIFTY PSU BANK",    "NIFTYPSUBANK",  False),
    ("NIFTY REALTY",      "NIFTYREALTY",   False),
]

# NIFTY 50 constituent F&O stocks
_NIFTY50_SYMBOLS = [
    "RELIANCE",   "TCS",        "HDFCBANK",   "INFY",       "ICICIBANK",
    "HINDUNILVR", "ITC",        "SBIN",       "BHARTIARTL", "KOTAKBANK",
    "LT",         "AXISBANK",   "ASIANPAINT", "MARUTI",     "BAJFINANCE",
    "WIPRO",      "HCLTECH",    "TECHM",      "ULTRACEMCO", "NESTLEIND",
    "TITAN",      "BAJAJFINSV", "SUNPHARMA",  "TATAMOTORS", "POWERGRID",
    "NTPC",       "ONGC",       "COALINDIA",  "TATASTEEL",  "JSWSTEEL",
    "M&M",        "INDUSINDBK", "DIVISLAB",   "CIPLA",      "DRREDDY",
    "ADANIENT",   "ADANIPORTS", "GRASIM",     "EICHERMOT",  "BPCL",
    "HEROMOTOCO", "BRITANNIA",  "APOLLOHOSP", "TATACONSUM", "HINDALCO",
    "BAJAJ-AUTO", "LTIM",       "SBILIFE",    "HDFCLIFE",   "UPL",
]

# NIFTY NEXT 50 additions
_NIFTY_NEXT50 = [
    "DMART",       "SIEMENS",    "ABB",         "PIDILITIND",  "GODREJCP",
    "MARICO",      "DABUR",      "COLPAL",      "MUTHOOTFIN",  "PAGEIND",
    "HDFCAMC",     "ICICIGI",    "ICICIPRULI",  "SBICARD",     "CHOLAFIN",
    "SHREECEM",    "AMBUJACEM",  "ACCGRI",      "JKCEMENT",    "RAMCOCEM",
    "TATACOMM",    "MCDOWELL-N", "UNITDSPR",    "RADICO",      "GLOBALVEND",
]

# Defence & PSU (high-momentum sector — frequently in F&O)
_DEFENCE_PSU = [
    "BEL",        "HAL",        "BDL",         "BHEL",        "RVNL",
    "IRCON",      "RAILTEL",    "IRFC",        "RECLTD",      "PFC",
    "NHPC",       "SJVN",       "NTPC",        "POWERGRID",   "CONCOR",
    "IRCTC",      "COALINDIA",  "NMDC",        "SAIL",        "NATIONALUM",
    "HUDCO",      "MAZAGON",    "COCHINSHIP",  "GRSE",        "MIDHANI",
]

# Banking & Financial services
_BANKING_FINANCE = [
    "BANKBARODA", "CANBK",      "PNB",         "FEDERALBNK",  "IDFCFIRSTB",
    "BANDHANBNK", "RBLBANK",    "AUBANK",      "UJJIVANSFB",  "EQUITASBNK",
    "FINBL",      "CREDITACC",  "MANAPPURAM",  "BAJAJHFL",    "LICHOUSFIN",
    "PNBHOUSING", "CANFINHOME",
]

# IT & Technology
_IT_TECH = [
    "PERSISTENT", "MPHASIS",    "COFORGE",     "LTTS",        "KPITTECH",
    "RATEGAIN",   "NEWGEN",     "TANLA",       "HAPPSTMNDS",  "MASTEK",
    "TATAELXSI",  "CYIENT",     "ZENSAR",      "HEXAWARE",    "NIITTECH",
]

# Capital goods & Infrastructure
_CAPGOODS_INFRA = [
    "HAVELLS",    "POLYCAB",    "CROMPTON",    "VOLTAS",      "WHIRLPOOL",
    "ASTRAL",     "SUPREMEIND", "CUMMINSIND",  "THERMAX",     "ABB",
    "SIEMENS",    "KECINTL",    "KALPATPOWR",  "BEML",        "TIINDIA",
]

# Consumer & Retail
_CONSUMER_RETAIL = [
    "TRENT",      "NYKAA",      "ZOMATO",      "DELHIVERY",   "PAYTM",
    "PVR",        "JUBLFOOD",   "DEVYANI",     "WESTLIFE",    "SAPPHIRE",
    "BATAINDIA",  "ABFRL",      "VMART",       "MANYAVAR",    "CAMPUS",
]

# Chemicals & Speciality
_CHEMICALS = [
    "DEEPAKNTR",  "GHCL",       "GNFC",        "AARTIIND",    "SRF",
    "ALKYLAMINE", "TATACHEM",   "COROMANDEL",  "CHAMBLFERT",  "FACT",
    "RAIN",       "HINDZINC",   "VEDL",        "JINDALSTEL",  "NATIONALUM",
]

# Oil & Gas / Energy (upstream)
_ENERGY = [
    "GAIL",       "MGL",        "GSPL",        "PETRONET",
    "IOC",        "HINDPETRO",  "MRPL",        "CPCL",        "CHENNPETRO",
    "OIL",        "ATGL",
]

# Pharma & Healthcare
_PHARMA = [
    "IPCALAB",    "LAURUSLABS", "GRANULES",    "AUROPHARMA",  "TORNTPHARM",
    "ALKEM",      "NATCOPHARM", "JBCHEPHARM",  "AJANTPHARM",  "ABBOTINDIA",
    "PFIZER",     "GLAXO",      "SANOFI",      "ERIS",        "GLENMARK",
    "LUPIN",      "BIOCON",     "ZYDUSLIFE",   "MAXHEALTH",   "MANKIND",
    "FORTIS",     "NAVINFLUOR",
]

# Auto & Auto Ancillaries
_AUTO_ANCILLARY = [
    "TVSMOTOR",   "ASHOKLEY",   "ESCORTS",     "BALKRISIND",  "MOTHERSON",
    "MRF",        "EXIDEIND",   "BHARATFORG",  "SONACOMS",    "UNOMINDA",
    "BOSCHLTD",   "FORCEMOT",   "HYUNDAI",
]

# Real Estate & Hospitality
_REAL_ESTATE = [
    "DLF",        "GODREJPROP", "PRESTIGE",    "OBEROIRLTY",  "LODHA",
    "PHOENIXLTD", "INDHOTEL",   "INDIGO",
]

# New Energy — power generation, renewables, clean tech
_NEW_ENERGY = [
    "TATAPOWER",  "ADANIGREEN", "ADANIPOWER",  "ADANIENSOL",  "JSWENERGY",
    "TORNTPOWER", "SUZLON",     "NLCINDIA",    "INOXWIND",    "IREDA",
    "WAAREEENER", "PREMIERENE", "IEX",
]

# Capital Markets & Asset Management
_CAPITAL_MARKETS = [
    "MCX",        "BSE",        "CDSL",        "ABCAPITAL",   "ANGELONE",
    "POLICYBZR",  "MOTILALOFS", "NAUKRI",      "CAMS",        "KFINTECH",
    "NUVAMA",     "NAM-INDIA",  "MFSL",        "JIOFIN",      "LTF",
    "SHRIRAMFIN", "SAMMAANCAP", "LICI",        "LICHSGFIN",
]

# Capital Goods & Electronics (additional)
_CAPGOODS_EXTRA = [
    "CGPOWER",    "DIXON",      "KAYNES",      "KEI",         "PIIND",
    "SOLARINDS",  "PGEL",       "APLAPOLLO",   "AMBER",       "POWERINDIA",
]

# Consumer, FMCG & New-age (additional)
_CONSUMER_EXTRA = [
    "DALBHARAT",  "EMAMILTD",   "KALYANKJIL",  "PATANJALI",   "BLUESTARCO",
    "VBL",        "SWIGGY",     "ETERNAL",     "GODFRYPHLP",
]

# PSU Banking & Telecom (additional)
_PSU_BANKS2 = [
    "UNIONBANK",  "INDIANB",    "YESBANK",     "IDEA",
]

# Infrastructure & Conglomerates (additional)
_INFRA_MISC = [
    "GMRAIRPORT", "INDUSTOWER", "NBCC",        "MAZDOCK",     "BAJAJHLDNG",
    "OFSS",
]

# All additional F&O — deduplicated at seed time
_FO_EXTRA = list({
    s for group in [
        _NIFTY_NEXT50, _DEFENCE_PSU, _BANKING_FINANCE,
        _IT_TECH, _CAPGOODS_INFRA, _CONSUMER_RETAIL,
        _CHEMICALS, _ENERGY, _PHARMA,
        _AUTO_ANCILLARY, _REAL_ESTATE, _NEW_ENERGY,
        _CAPITAL_MARKETS, _CAPGOODS_EXTRA, _CONSUMER_EXTRA,
        _PSU_BANKS2, _INFRA_MISC,
    ]
    for s in group
})


_KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"


class MarketUniverseService:
    def __init__(
        self,
        repository: SqlAlchemyMarketUniverseRepository,
        kite_provider: IMarketDataProvider,
    ) -> None:
        self._repo = repository
        self._kite = kite_provider

    async def get_active_symbols(
        self,
        segment: str | None = None,
        fo_only: bool = False,
    ) -> list[MarketSymbol]:
        return await self._repo.get_active(segment=segment, fo_only=fo_only)

    async def get_symbol(self, symbol: str) -> MarketSymbol | None:
        return await self._repo.get(symbol)

    async def count(self) -> int:
        return await self._repo.count()

    # Index future lot sizes — rebased by NSE effective January 2026 contracts.
    # NIFTY: 75→65, BANKNIFTY: 35→30, FINNIFTY: 65→60, MIDCPNIFTY: 140→120.
    # Source: NSE circular FAOP70616 / bigul.co January 2026 lot size revision.
    # Kite CSV sync will override with live values; these are the static fallbacks.
    _INDEX_LOT_SIZES: dict[str, int] = {
        "NIFTY":      65,
        "BANKNIFTY":  30,
        "FINNIFTY":   60,
        "MIDCPNIFTY": 120,
    }

    # Static lot size overrides for symbols absent or misnamed in Kite's instrument CSV.
    # These are NSE-authoritative values — update when SEBI revises F&O lot sizes.
    # NOTE: Kite's public instruments CSV is regenerated after each expiry; these fallbacks
    # ensure correct sizing on expiry days before the CSV is refreshed.
    _LOT_SIZE_OVERRIDES: dict[str, int] = {
        # ── Existing overrides ──────────────────────────────────────────
        "TATAMOTORS":  550,
        "AARTIIND":    600,
        "BEML":        375,
        "CANFINHOME": 1000,
        "COROMANDEL":  400,
        "CYIENT":      500,
        "DEEPAKNTR":   150,
        "GRANULES":   1500,
        "GSPL":       1500,
        "HAPPSTMNDS": 2000,
        "HEXAWARE":    700,
        "HUDCO":      4000,
        "IPCALAB":     400,
        "IRCON":      2750,
        "IRCTC":       375,
        "JKCEMENT":    200,
        "KALPATPOWR":  600,
        "KECINTL":     750,
        "LTIM":         75,
        "LTTS":         75,
        "MASTEK":      400,
        "MAZAGON":     170,
        "MGL":         220,
        "NEWGEN":      700,
        "PVR":         600,
        "RAILTEL":    4000,
        "RAMCOCEM":    500,
        "RATEGAIN":   1400,
        "SJVN":       5000,
        "TANLA":       600,
        "TATACHEM":    500,
        "TATACOMM":    375,
        "THERMAX":     200,
        "UJJIVANSFB": 5000,
        "ZENSAR":      800,
        "ZOMATO":     1500,
        # ── Auto & Auto Ancillaries ─────────────────────────────────────
        "TVSMOTOR":    350,
        "ASHOKLEY":   2750,
        "ESCORTS":     375,
        "BALKRISIND":  250,
        "MOTHERSON":  3500,
        "MRF":          10,
        "EXIDEIND":   2250,
        "BHARATFORG": 1000,
        "SONACOMS":   2000,
        "UNOMINDA":   1000,
        "BOSCHLTD":     50,
        "FORCEMOT":    125,
        "HYUNDAI":     375,
        # ── Real Estate & Hospitality ───────────────────────────────────
        "DLF":        1250,
        "GODREJPROP":  300,
        "PRESTIGE":    300,
        "OBEROIRLTY":  300,
        "LODHA":       750,
        "PHOENIXLTD":  400,
        "INDHOTEL":    750,
        "INDIGO":      300,
        # ── New Energy / Renewables ─────────────────────────────────────
        "TATAPOWER":  2925,
        "ADANIGREEN":  500,
        "ADANIPOWER": 1875,
        "ADANIENSOL": 1250,
        "ATGL":        800,
        "JSWENERGY":   750,
        "TORNTPOWER":  375,
        "SUZLON":     5000,
        "NLCINDIA":   5000,
        "INOXWIND":   3000,
        "IREDA":      7500,
        "WAAREEENER":  500,
        "PREMIERENE": 1500,
        "IEX":        2500,
        # ── Capital Markets & Asset Management ─────────────────────────
        "MCX":         200,
        "BSE":         500,
        "CDSL":        600,
        "ABCAPITAL":  2000,
        "ANGELONE":    400,
        "POLICYBZR":  1000,
        "MOTILALOFS":  300,
        "NAUKRI":      300,
        "CAMS":        300,
        "KFINTECH":   1500,
        "NUVAMA":      250,
        "NAM-INDIA":   600,
        "MFSL":        500,
        "JIOFIN":     2625,
        "LTF":        3500,
        "SHRIRAMFIN":  375,
        "SAMMAANCAP": 4000,
        "LICI":        700,
        "LICHSGFIN":   500,
        # ── Pharma / Healthcare (additional) ───────────────────────────
        "LUPIN":       500,
        "BIOCON":     2000,
        "ZYDUSLIFE":  1000,
        "MAXHEALTH":   700,
        "MANKIND":     500,
        "FORTIS":     2500,
        "NAVINFLUOR":  250,
        # ── PSU Banking & Telecom ───────────────────────────────────────
        "UNIONBANK":  5000,
        "INDIANB":    3000,
        "YESBANK":   25000,
        "IDEA":      25000,
        # ── Capital Goods / Electronics (additional) ────────────────────
        "CGPOWER":    1500,
        "DIXON":       200,
        "KAYNES":      250,
        "KEI":         500,
        "PIIND":       300,
        "SOLARINDS":   250,
        "PGEL":        750,
        "APLAPOLLO":   500,
        "AMBER":       250,
        "POWERINDIA": 1000,
        # ── Consumer / FMCG (additional) ────────────────────────────────
        "DALBHARAT":   300,
        "EMAMILTD":    800,
        "KALYANKJIL": 2500,
        "PATANJALI":   750,
        "BLUESTARCO":  300,
        "VBL":        1250,
        "SWIGGY":     1750,
        "ETERNAL":     500,
        "GODFRYPHLP":  300,
        # ── Infrastructure / Misc ───────────────────────────────────────
        "GMRAIRPORT": 8000,
        "INDUSTOWER": 1900,
        "NBCC":       5000,
        "MAZDOCK":     170,
        "OIL":        1900,
        "BAJAJHLDNG":   75,
        "OFSS":        200,
    }

    # Every symbol seeded as F&O that Kite's NFO CSV might miss on expiry-day transitions.
    # The CSV is regenerated after each expiry and can temporarily show < 300 instruments
    # (vs the normal 4000+), causing valid F&O stocks to be incorrectly demoted.
    # sync_fo_from_kite_instruments skips demotion when the CSV is clearly partial,
    # but this set provides a hard guarantee for any stock that Kite names differently.
    _FO_ALWAYS: frozenset[str] = frozenset({
        # Originals
        "TATAMOTORS",  "LTIM",        "ZOMATO",      "IRCTC",       "DEEPAKNTR",
        "TATACOMM",    "TATACHEM",    "MGL",         "GRANULES",    "GSPL",
        "SJVN",        "HUDCO",       "RAILTEL",     "MAZAGON",     "IRCON",
        "IPCALAB",     "JKCEMENT",    "CANFINHOME",  "LTTS",        "HEXAWARE",
        "TANLA",       "HAPPSTMNDS",  "NEWGEN",      "ZENSAR",      "MASTEK",
        "RATEGAIN",    "THERMAX",     "KECINTL",     "KALPATPOWR",  "BEML",
        "CYIENT",      "COROMANDEL",  "RAMCOCEM",    "UJJIVANSFB",  "AARTIIND",
        "PVR",
        # Auto & Auto Ancillaries
        "TVSMOTOR",    "ASHOKLEY",    "ESCORTS",     "BALKRISIND",  "MOTHERSON",
        "MRF",         "EXIDEIND",    "BHARATFORG",  "SONACOMS",    "UNOMINDA",
        "BOSCHLTD",    "FORCEMOT",    "HYUNDAI",
        # Real Estate & Hospitality
        "DLF",         "GODREJPROP",  "PRESTIGE",    "OBEROIRLTY",  "LODHA",
        "PHOENIXLTD",  "INDHOTEL",    "INDIGO",
        # New Energy
        "TATAPOWER",   "ADANIGREEN",  "ADANIPOWER",  "ADANIENSOL",  "ATGL",
        "JSWENERGY",   "TORNTPOWER",  "SUZLON",      "NLCINDIA",    "INOXWIND",
        "IREDA",       "WAAREEENER",  "PREMIERENE",  "IEX",
        # Capital Markets
        "MCX",         "BSE",         "CDSL",        "ABCAPITAL",   "ANGELONE",
        "POLICYBZR",   "MOTILALOFS",  "NAUKRI",      "CAMS",        "KFINTECH",
        "NUVAMA",      "NAM-INDIA",   "MFSL",        "JIOFIN",      "LTF",
        "SHRIRAMFIN",  "SAMMAANCAP",  "LICI",        "LICHSGFIN",
        # Pharma / Healthcare
        "LUPIN",       "BIOCON",      "ZYDUSLIFE",   "MAXHEALTH",   "MANKIND",
        "FORTIS",      "NAVINFLUOR",
        # PSU Banking & Telecom
        "UNIONBANK",   "INDIANB",     "YESBANK",     "IDEA",
        # Capital Goods / Electronics
        "CGPOWER",     "DIXON",       "KAYNES",      "KEI",         "PIIND",
        "SOLARINDS",   "PGEL",        "APLAPOLLO",   "AMBER",       "POWERINDIA",
        # Consumer / FMCG
        "DALBHARAT",   "EMAMILTD",    "KALYANKJIL",  "PATANJALI",   "BLUESTARCO",
        "VBL",         "SWIGGY",      "ETERNAL",     "GODFRYPHLP",
        # Infrastructure / Misc
        "GMRAIRPORT",  "INDUSTOWER",  "NBCC",        "MAZDOCK",     "OIL",
        "BAJAJHLDNG",  "OFSS",
        # Energy (oil & gas)
        "ATGL",        "OIL",
    })

    async def seed_default_universe(self, force: bool = False) -> int:
        """Seed the database with standard NSE + F&O symbols. Idempotent.

        Args:
            force: When True, upsert all symbols even if the table is already populated.
                   Use after adding new symbols to the static lists.
        """
        count = await self._repo.count()
        if count > 0 and not force:
            _log.info("universe.seed skipped — %d symbols already loaded", count)
            return count

        symbols: list[MarketSymbol] = []
        seen: set[str] = set()

        def _add(sym: MarketSymbol) -> None:
            if sym.symbol not in seen:
                seen.add(sym.symbol)
                symbols.append(sym)

        # Indices (is_fo=True → tradeable as futures)
        for name, sym, is_fo in _INDICES:
            lot = self._INDEX_LOT_SIZES.get(sym, 1)
            _add(MarketSymbol(
                symbol=sym, name=name, exchange="NSE",
                segment="IDX", is_index=True, is_fo=is_fo, is_active=True,
                lot_size=lot,
                meta={"index_future": is_fo},
            ))

        # NIFTY 50 constituents
        for sym in _NIFTY50_SYMBOLS:
            lot = self._LOT_SIZE_OVERRIDES.get(sym, 1)
            _add(MarketSymbol(
                symbol=sym, name=sym, exchange="NSE",
                segment="EQ", is_fo=True, is_active=True, lot_size=lot,
            ))

        # All additional F&O sectors
        for sym in _FO_EXTRA:
            lot = self._LOT_SIZE_OVERRIDES.get(sym, 1)
            _add(MarketSymbol(
                symbol=sym, name=sym, exchange="NSE",
                segment="EQ", is_fo=True, is_active=True, lot_size=lot,
            ))

        stored = await self._repo.upsert_many(symbols)
        _log.info(
            "universe.seed completed total=%d indices=%d fo_stocks=%d",
            stored,
            sum(1 for s in symbols if s.is_index),
            sum(1 for s in symbols if not s.is_index),
        )
        return stored

    async def sync_from_kite(
        self,
        api_key: str,
        access_token: str,
    ) -> int:
        """Pull full NSE instrument list from Kite and update sector/token metadata."""
        try:
            from kiteconnect import KiteConnect  # type: ignore[import-untyped]
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            loop = asyncio.get_event_loop()
            instruments: list[dict] = await loop.run_in_executor(
                None, lambda: kite.instruments("NSE")
            )
            _log.info("universe.sync_from_kite: fetched %d NSE instruments", len(instruments))

            # Build lookup by tradingsymbol
            kite_map: dict[str, dict] = {
                i["tradingsymbol"]: i for i in instruments
            }

            existing = await self._repo.get_active()
            updated = 0
            for sym in existing:
                info = kite_map.get(sym.symbol)
                if not info:
                    continue
                sym.name = info.get("name") or sym.name
                sym.instrument_token = info.get("instrument_token")
                sym.lot_size = int(info.get("lot_size") or 1)
                sym.sector = info.get("segment") or sym.sector
                sym.isin = info.get("isin")
                updated += 1
            await self._repo.upsert_many(existing)
            _log.info("universe.sync_from_kite: updated metadata for %d symbols", updated)
            return updated
        except Exception as exc:
            _log.warning("universe.sync_from_kite failed: %s", exc)
            return 0

    async def sync_fo_from_kite_instruments(self) -> dict[str, int]:
        """Cross-reference our universe against Kite's public instrument master.

        Downloads https://api.kite.trade/instruments (no API key needed, updated
        daily by Kite), filters to segment=NFO-FUT to get the authoritative list
        of stocks with active F&O contracts, then:
          - marks symbols in our universe that ARE in NFO-FUT as is_fo=True
          - marks symbols that are NOT in NFO-FUT as is_fo=False (cash-only)

        Returns {"promoted": N, "demoted": N, "unchanged": N}.
        """
        try:
            import io
            import csv
            import asyncio
            import urllib.request

            loop = asyncio.get_event_loop()

            def _fetch_csv() -> tuple[set[str], dict[str, int]]:
                with urllib.request.urlopen(_KITE_INSTRUMENTS_URL, timeout=30) as resp:
                    text = resp.read().decode("utf-8")
                reader = csv.DictReader(io.StringIO(text))
                active_fo_names: set[str] = set()
                lot_sizes: dict[str, int] = {}
                for row in reader:
                    # NFO-FUT: stocks + indices with futures (implies options too)
                    # NFO-OPT: stocks that may have lost futures but still have options
                    if row.get("segment") in ("NFO-FUT", "NFO-OPT"):
                        name = row.get("name", "").strip().strip('"')
                        # Extract symbol prefix from tradingsymbol: stop at first digit
                        # e.g. "TATAMOTORS26JUNFUT" → "TATAMOTORS", "BAJAJ-AUTO26JUNFUT" → "BAJAJ-AUTO"
                        # (old approach kept "JUN"/"FUT" alpha chars, giving wrong keys like "TATAMOTORSJUNFUT")
                        tsym = row.get("tradingsymbol", "").strip()
                        tsym_prefix = ""
                        for _c in tsym:
                            if _c.isdigit():
                                break
                            tsym_prefix += _c
                        try:
                            ls = int(row.get("lot_size") or 0)
                        except (ValueError, TypeError):
                            ls = 0
                        for key in (name, tsym_prefix):
                            if key:
                                active_fo_names.add(key)
                                if ls > 0 and key not in lot_sizes:
                                    lot_sizes[key] = ls
                return active_fo_names, lot_sizes

            nfo_fut, fo_lot_sizes = await loop.run_in_executor(None, _fetch_csv)
            _log.info("universe.kite_instruments_fetched nfo_active_count=%d", len(nfo_fut))

            # Kite's CSV is regenerated after each expiry. During the transition window
            # it contains < 500 entries (vs the normal 4000+). A partial CSV must never
            # demote stocks — only promote and update lot sizes.
            csv_is_partial = len(nfo_fut) < 500
            if csv_is_partial:
                _log.info(
                    "universe.kite_csv_partial nfo_count=%d — demotion suppressed (expiry-day transition)",
                    len(nfo_fut),
                )

        except Exception as exc:
            _log.warning("universe.kite_instruments_fetch_failed: %s — skipping F&O sync", exc)
            return {"promoted": 0, "demoted": 0, "unchanged": 0}

        all_symbols = await self._repo.get_active()
        promoted = demoted = unchanged = 0

        lot_size_updated = 0
        for sym in all_symbols:
            if sym.is_index:
                # Indices are always kept as is_fo=True regardless of NFO-FUT list
                continue
            in_nfo = sym.symbol in nfo_fut or sym.symbol in self._FO_ALWAYS
            if in_nfo and not sym.is_fo:
                sym.is_fo = True
                promoted += 1
            elif not in_nfo and sym.is_fo and not csv_is_partial:
                # Only demote when the CSV is a full list — never on expiry-day transitions
                sym.is_fo = False
                demoted += 1
            else:
                unchanged += 1
            # Update lot size: Kite CSV first, static overrides as fallback
            kite_lot = fo_lot_sizes.get(sym.symbol) or self._LOT_SIZE_OVERRIDES.get(sym.symbol)
            if kite_lot and sym.lot_size != kite_lot:
                sym.lot_size = kite_lot
                lot_size_updated += 1

        if promoted + demoted + lot_size_updated > 0:
            await self._repo.upsert_many(all_symbols)
        _log.info("universe.lot_sizes_synced updated=%d", lot_size_updated)

        _log.info(
            "universe.fo_sync_done promoted=%d demoted=%d unchanged=%d",
            promoted, demoted, unchanged,
        )
        return {"promoted": promoted, "demoted": demoted, "unchanged": unchanged}

    async def get_fo_symbols(self) -> list[str]:
        syms = await self._repo.get_active(fo_only=True)
        return [s.symbol for s in syms]

    async def get_index_symbols(self) -> list[str]:
        syms = await self._repo.get_active(index_only=True)
        return [s.symbol for s in syms]

    async def get_scannable_symbols(self) -> list["MarketSymbol"]:
        """All symbols eligible for signal scanning: F&O stocks + index futures."""
        return await self._repo.get_active(fo_only=True)
