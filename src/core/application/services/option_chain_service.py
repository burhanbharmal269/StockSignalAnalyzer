"""OptionChainService — fetch, analyze, and store option chain data.

Calculates: PCR, Max Pain, OI buildup/unwinding patterns.
Stores snapshots in option_chain_snapshots table.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from core.domain.interfaces.i_market_data_provider import IMarketDataProvider
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

_log = logging.getLogger(__name__)


class OptionChainService:
    def __init__(
        self,
        primary_provider: IMarketDataProvider,
        fallback_provider: IMarketDataProvider,
        session_factory,
    ) -> None:
        self._primary = primary_provider
        self._fallback = fallback_provider
        self._sf = session_factory

    async def fetch_and_store(self, underlying: str) -> dict:
        """Fetch option chain, store snapshot, return analysis."""
        entries = await self._fetch(underlying)
        if not entries:
            return {"underlying": underlying, "error": "no data"}

        analysis = self._analyze(underlying, entries)
        await self._persist(underlying, entries, analysis)
        return analysis

    async def get_latest(self, underlying: str) -> dict | None:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT underlying, expiry, strike, option_type, ltp, iv, oi,
                       oi_change, volume, delta, gamma, theta, vega, pcr, max_pain,
                       captured_at
                FROM option_chain_snapshots
                WHERE underlying = :und
                  AND captured_at = (
                      SELECT MAX(captured_at) FROM option_chain_snapshots
                      WHERE underlying = :und
                  )
                ORDER BY expiry, strike, option_type
            """), {"und": underlying})
            rows = result.mappings().fetchall()
            if not rows:
                return None
            return {
                "underlying": underlying,
                "captured_at": str(rows[0]["captured_at"]),
                "pcr": float(rows[0]["pcr"] or 0),
                "max_pain": float(rows[0]["max_pain"] or 0),
                "entries": [dict(r) for r in rows],
            }

    async def get_pcr_history(self, underlying: str, limit: int = 20) -> list[dict]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT captured_at, pcr
                FROM option_chain_snapshots
                WHERE underlying=:und AND option_type='CE'
                GROUP BY captured_at, pcr
                ORDER BY captured_at DESC
                LIMIT :lim
            """), {"und": underlying, "lim": limit})
            return [{"ts": str(r[0]), "pcr": float(r[1] or 0)} for r in result.fetchall()]

    def _analyze(self, underlying: str, entries: list) -> dict:
        ce_entries = [e for e in entries if e.option_type == "CE"]
        pe_entries = [e for e in entries if e.option_type == "PE"]

        total_ce_oi = sum(e.open_interest or 0 for e in ce_entries)
        total_pe_oi = sum(e.open_interest or 0 for e in pe_entries)
        pcr = (total_pe_oi / total_ce_oi) if total_ce_oi > 0 else Decimal(1)

        max_pain = self._calculate_max_pain(entries)

        # OI buildup patterns
        ce_oi_change = sum(e.change_in_oi or 0 for e in ce_entries)
        pe_oi_change = sum(e.change_in_oi or 0 for e in pe_entries)

        if ce_oi_change > 0 and pe_oi_change < 0:
            pattern = "SHORT_BUILDUP"
        elif pe_oi_change > 0 and ce_oi_change < 0:
            pattern = "LONG_BUILDUP"
        elif ce_oi_change < 0 and pe_oi_change < 0:
            pattern = "SHORT_COVERING"
        elif ce_oi_change > 0 and pe_oi_change > 0:
            pattern = "LONG_UNWINDING"
        else:
            pattern = "NEUTRAL"

        return {
            "underlying": underlying,
            "pcr": float(pcr),
            "max_pain": float(max_pain),
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "ce_oi_change": ce_oi_change,
            "pe_oi_change": pe_oi_change,
            "pattern": pattern,
            "captured_at": datetime.now(UTC).isoformat(),
        }

    def _calculate_max_pain(self, entries: list) -> Decimal:
        """Max pain = strike where total option seller loss is minimum."""
        strikes = set(e.strike for e in entries)
        if not strikes:
            return Decimal(0)

        min_loss = None
        max_pain_strike = Decimal(0)

        for test_strike in sorted(strikes):
            loss = Decimal(0)
            for e in entries:
                intrinsic = Decimal(0)
                if e.option_type == "CE" and test_strike > e.strike:
                    intrinsic = test_strike - e.strike
                elif e.option_type == "PE" and test_strike < e.strike:
                    intrinsic = e.strike - test_strike
                loss += intrinsic * (e.open_interest or 0)

            if min_loss is None or loss < min_loss:
                min_loss = loss
                max_pain_strike = test_strike

        return max_pain_strike

    async def _fetch(self, underlying: str) -> list:
        try:
            entries = await self._primary.get_option_chain(underlying)
            if entries:
                return entries
        except Exception as exc:
            _log.warning("option_chain primary failed %s: %s", underlying, exc)

        try:
            return await self._fallback.get_option_chain(underlying)
        except Exception as exc:
            _log.warning("option_chain fallback failed %s: %s", underlying, exc)
            return []

    async def _persist(self, underlying: str, entries: list, analysis: dict) -> None:
        if not entries:
            return
        pcr = analysis.get("pcr", 0)
        max_pain = analysis.get("max_pain", 0)
        now = datetime.now(UTC)
        async with self._sf() as db:
            for e in entries[:200]:   # cap to avoid huge inserts
                await db.execute(text("""
                    INSERT INTO option_chain_snapshots
                        (underlying, expiry, strike, option_type, ltp, iv, oi,
                         oi_change, volume, pcr, max_pain, captured_at)
                    VALUES
                        (:und, :expiry, :strike, :opt_type, :ltp, :iv, :oi,
                         :oi_change, :vol, :pcr, :max_pain, :ts)
                """), {
                    "und": underlying,
                    "expiry": e.expiry,
                    "strike": float(e.strike),
                    "opt_type": e.option_type,
                    "ltp": float(e.last_price),
                    "iv": None,
                    "oi": e.open_interest,
                    "oi_change": e.change_in_oi,
                    "vol": e.volume,
                    "pcr": pcr,
                    "max_pain": max_pain,
                    "ts": now,
                })
            await db.commit()
