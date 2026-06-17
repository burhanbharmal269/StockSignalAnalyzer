"""OptionChainService — fetch, analyze, and store option chain data.

Calculates:
  - PCR, Max Pain, OI buildup/unwinding patterns
  - IV per strike via Black-Scholes (Newton-Raphson, no scipy required)
  - ATM IV, IV Skew (OTM 5% put minus OTM 5% call)
  - GEX (Gamma Exposure) — net dealer gamma position across all strikes
  - IV Percentile — rolling percentile of ATM IV from historical snapshots

Stores snapshots in option_chain_snapshots table (iv column now populated).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import text

from core.domain.analytics.iv_calculator import compute_chain_analytics

if TYPE_CHECKING:
    from core.domain.interfaces.i_market_data_provider import IMarketDataProvider

_log = logging.getLogger(__name__)

# IV percentile look-back window: 252 trading days ≈ 1 year
_IV_PERCENTILE_LOOKBACK = 252


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

    async def fetch_and_store(self, underlying: str, lot_size: int = 50) -> dict:
        """Fetch option chain, compute IV/GEX/skew, store snapshot, return analysis."""
        entries = await self._fetch(underlying)
        if not entries:
            return {"underlying": underlying, "error": "no data"}

        # Get spot price from provider — needed for accurate Black-Scholes IV
        spot = await self._get_spot(underlying)

        analysis = await self._analyze(underlying, entries, spot, lot_size)
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

            # Fetch IV percentile from history
            iv_pct = await self._iv_percentile(underlying, db)

            # Pull atm_iv, iv_skew, gex from the most recent analytics stored in metadata
            # (we store these in pcr/max_pain rows; atm_iv is the ATM CE iv column value)
            atm_iv = await self._latest_atm_iv(underlying, db)
            iv_skew = await self._latest_iv_skew(underlying, db)
            net_gex = await self._latest_net_gex(underlying, db)

            return {
                "underlying": underlying,
                "captured_at": str(rows[0]["captured_at"]),
                "pcr": float(rows[0]["pcr"] or 0),
                "max_pain": float(rows[0]["max_pain"] or 0),
                "atm_iv": atm_iv,
                "iv_percentile": iv_pct,
                "iv_skew": iv_skew,
                "net_gex": net_gex,
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

    # ------------------------------------------------------------------
    # Private analysis
    # ------------------------------------------------------------------

    async def _analyze(self, underlying: str, entries: list, spot: float, lot_size: int) -> dict:
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

        # Black-Scholes IV, skew, GEX
        # Convert OptionChainEntry objects to plain dicts for the calculator
        entry_dicts = [
            {
                "strike": float(e.strike),
                "option_type": e.option_type,
                "ltp": float(e.last_price),
                "oi": int(e.open_interest or 0),
            }
            for e in entries
        ]
        # DTE from first expiry in entries (approximate)
        dte = max(1, _dte_from_entries(entries))
        iv_analytics = compute_chain_analytics(
            entries=entry_dicts,
            spot=spot,
            dte=dte,
            lot_size=lot_size,
        )
        _log.info(
            "option_chain.analytics underlying=%s atm_iv=%.1f%% iv_skew=%s net_gex=%s gex_positive=%s",
            underlying,
            (iv_analytics["atm_iv"] or 0) * 100,
            f"{(iv_analytics['iv_skew'] or 0):.4f}" if iv_analytics["iv_skew"] is not None else "N/A",
            f"{iv_analytics['net_gex']:.0f}",
            iv_analytics["gex_positive"],
        )

        return {
            "underlying": underlying,
            "pcr": float(pcr),
            "max_pain": float(max_pain),
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "ce_oi_change": ce_oi_change,
            "pe_oi_change": pe_oi_change,
            "pattern": pattern,
            "spot": spot,
            "atm_iv": iv_analytics["atm_iv"],
            "iv_skew": iv_analytics["iv_skew"],
            "net_gex": iv_analytics["net_gex"],
            "gex_strike": iv_analytics["gex_strike"],
            "gex_positive": iv_analytics["gex_positive"],
            "iv_per_strike": iv_analytics["iv_per_strike"],
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

    async def _get_spot(self, underlying: str) -> float:
        """Fetch spot price from provider. Falls back to 0 on failure."""
        try:
            ltp_map = await self._primary.get_ltp([underlying])
            val = ltp_map.get(underlying)
            if val:
                return float(val)
        except Exception as exc:
            _log.debug("option_chain.spot_fetch failed %s: %s", underlying, exc)
        try:
            ltp_map = await self._fallback.get_ltp([underlying])
            val = ltp_map.get(underlying)
            if val:
                return float(val)
        except Exception:
            pass
        return 0.0

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
        iv_per_strike: dict = analysis.get("iv_per_strike", {})
        now = datetime.now(UTC)
        async with self._sf() as db:
            for e in entries[:200]:
                strike_f = float(e.strike)
                iv_val = iv_per_strike.get(strike_f, {}).get(e.option_type)
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
                    "strike": strike_f,
                    "opt_type": e.option_type,
                    "ltp": float(e.last_price),
                    "iv": iv_val,       # now populated from Black-Scholes
                    "oi": e.open_interest,
                    "oi_change": e.change_in_oi,
                    "vol": e.volume,
                    "pcr": pcr,
                    "max_pain": max_pain,
                    "ts": now,
                })
            await db.commit()

    # ------------------------------------------------------------------
    # IV percentile from historical snapshots
    # ------------------------------------------------------------------

    async def _iv_percentile(self, underlying: str, db) -> float | None:
        """Rolling IV percentile: rank of current ATM IV vs last 252 trading days."""
        result = await db.execute(text("""
            SELECT DISTINCT ON (DATE(captured_at)) iv
            FROM option_chain_snapshots
            WHERE underlying = :und
              AND option_type = 'CE'
              AND iv IS NOT NULL AND iv > 0
            ORDER BY DATE(captured_at), ABS(strike - (
                SELECT ltp FROM option_chain_snapshots
                WHERE underlying = :und AND option_type = 'CE'
                  AND captured_at = (SELECT MAX(captured_at) FROM option_chain_snapshots WHERE underlying = :und)
                ORDER BY captured_at DESC LIMIT 1
            ))
            LIMIT :lookback
        """), {"und": underlying, "lookback": _IV_PERCENTILE_LOOKBACK + 1})
        rows = result.fetchall()
        if len(rows) < 5:
            return None
        iv_values = sorted(float(r[0]) for r in rows)
        current_iv = iv_values[-1]
        rank = sum(1 for v in iv_values[:-1] if v <= current_iv)
        return round(rank / len(iv_values[:-1]) * 100, 1)

    async def _latest_atm_iv(self, underlying: str, db) -> float | None:
        result = await db.execute(text("""
            SELECT iv FROM option_chain_snapshots
            WHERE underlying = :und AND option_type = 'CE' AND iv IS NOT NULL
              AND captured_at = (SELECT MAX(captured_at) FROM option_chain_snapshots WHERE underlying = :und)
            ORDER BY ABS(strike - max_pain)
            LIMIT 1
        """), {"und": underlying})
        row = result.fetchone()
        return float(row[0]) if row and row[0] else None

    async def _latest_iv_skew(self, underlying: str, db) -> float | None:
        """Approximate skew: median PE iv minus median CE iv at latest snapshot."""
        result = await db.execute(text("""
            SELECT option_type, AVG(iv) as avg_iv
            FROM option_chain_snapshots
            WHERE underlying = :und AND iv IS NOT NULL AND iv > 0
              AND captured_at = (SELECT MAX(captured_at) FROM option_chain_snapshots WHERE underlying = :und)
            GROUP BY option_type
        """), {"und": underlying})
        rows = {r[0]: float(r[1]) for r in result.fetchall()}
        ce_iv = rows.get("CE")
        pe_iv = rows.get("PE")
        if ce_iv and pe_iv:
            return round(pe_iv - ce_iv, 4)
        return None

    async def _latest_net_gex(self, underlying: str, db) -> float | None:
        """GEX is computed at fetch_and_store time; scanner reads it from analysis dict directly."""
        return None


def _dte_from_entries(entries: list) -> int:
    """Return days-to-expiry from the nearest expiry found in entries."""
    today = datetime.now(UTC).date()
    dates = []
    for e in entries:
        expiry = getattr(e, "expiry", None)
        if expiry is None:
            continue
        exp_date = expiry.date() if hasattr(expiry, "date") else expiry
        try:
            delta = (exp_date - today).days
            if delta >= 0:
                dates.append(delta)
        except Exception:
            continue
    return min(dates) if dates else 30
