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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import text

from core.domain.analytics.iv_calculator import compute_chain_analytics

if TYPE_CHECKING:
    from core.application.services.futures_oi_service import FuturesOIService
    from core.application.services.oi_analytics_service import OIAnalyticsService
    from core.domain.interfaces.i_market_data_provider import IMarketDataProvider

_log = logging.getLogger(__name__)

# IV percentile look-back window: 252 trading days ≈ 1 year
_IV_PERCENTILE_LOOKBACK = 252

# Indices with WEEKLY options (NSE, as of Sep 2025)
_WEEKLY_OPTION_SYMBOLS = {"NIFTY"}
# All other indices and stocks use monthly expiry (last Tuesday of month, NSE post-Sep-2025)


def _near_expiry_for(underlying: str) -> date:
    """Return the nearest active option expiry date for a given underlying.

    Rules (NSE effective 1-Sep-2025 SEBI circular):
      - NIFTY: weekly options, expire every Tuesday. Skip today if today IS Tuesday
        (expiry-day options have DTE=0 — too close for meaningful signals).
      - All other symbols: monthly options, expire on the last Tuesday of the month.
        If that expiry has already passed today, return next month's last Tuesday.
    """
    today = datetime.now(UTC).date()

    if underlying in _WEEKLY_OPTION_SYMBOLS:
        # Next Tuesday (never today even if today is Tuesday — avoid DTE=0 options)
        days_ahead = (1 - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return today + timedelta(days=days_ahead)

    # Monthly: last Tuesday of current (or next) month
    for month_offset in range(3):
        year = today.year + (today.month + month_offset - 1) // 12
        month = (today.month + month_offset - 1) % 12 + 1
        # Start from 28th — guaranteed to be in month — then find first Tuesday ≥ 28th
        probe = date(year, month, 28)
        while probe.weekday() != 1:   # 1 = Tuesday
            probe += timedelta(days=1)
        # Advance by weeks while still in same month
        while True:
            nxt = probe + timedelta(days=7)
            if nxt.month != month:
                break
            probe = nxt
        if probe > today:  # strictly after today so we don't trade on the expiry day
            return probe

    return today + timedelta(days=30)


class OptionChainService:
    def __init__(
        self,
        primary_provider: IMarketDataProvider,
        fallback_provider: IMarketDataProvider,
        session_factory,
        futures_oi_service: "FuturesOIService | None" = None,
        oi_analytics_service: "OIAnalyticsService | None" = None,
    ) -> None:
        self._primary = primary_provider
        self._fallback = fallback_provider
        self._sf = session_factory
        self._futures_oi_svc = futures_oi_service
        self._oi_analytics_svc = oi_analytics_service
        # In-memory GEX cache: {underlying: {"net_gex": float, "gex_positive": bool|None}}
        # Populated by fetch_and_store(); read by get_latest() via _latest_net_gex().
        self._gex_cache: dict[str, dict] = {}

    async def fetch_and_store(self, underlying: str, lot_size: int = 50) -> dict:
        """Fetch option chain for the nearest active expiry, compute IV/GEX/skew, store snapshot."""
        expiry = _near_expiry_for(underlying)
        include_futures = (
            self._futures_oi_svc is not None
            and getattr(self._futures_oi_svc, "_cfg", None) is not None
            and self._futures_oi_svc._cfg.oi_poll_enabled
        )
        all_entries = await self._fetch(underlying, expiry=expiry, include_futures=include_futures)
        if not all_entries:
            return {"underlying": underlying, "error": "no data"}

        # Separate FUT entries from CE/PE for FuturesOIService; only CE/PE goes to analysis
        fut_entries = [e for e in all_entries if e.option_type == "FUT"]
        entries = [e for e in all_entries if e.option_type != "FUT"]

        if self._futures_oi_svc is not None:
            if fut_entries:
                for fut in fut_entries:
                    self._futures_oi_svc.update(
                        underlying=underlying,
                        tradingsymbol=fut.tradingsymbol,
                        instrument_token=fut.instrument_token,
                        expiry=fut.expiry,
                        last_price=float(fut.last_price),
                        oi=fut.open_interest,
                        oi_day_high=fut.oi_day_high,
                        oi_day_low=fut.oi_day_low,
                    )
            else:
                self._futures_oi_svc.mark_missing(underlying, "no_fut_contract_in_chain")

            # Phase 21.1 — push latest snapshot into OI analytics (read-only, fail-open)
            if self._oi_analytics_svc is not None:
                snap = self._futures_oi_svc.get_cached(underlying)
                if snap is not None:
                    try:
                        await self._oi_analytics_svc.update_from_snapshot(snap)
                    except Exception as _oa_exc:
                        _log.debug("oi_analytics.update_failed underlying=%s: %s", underlying, _oa_exc)

        if not entries:
            return {"underlying": underlying, "error": "no option entries after filtering FUT"}

        _log.debug(
            "option_chain.fetched underlying=%s expiry=%s ce_pe=%d fut=%d",
            underlying, expiry, len(entries), len(fut_entries),
        )

        # Get spot price from provider — needed for accurate Black-Scholes IV
        spot = await self._get_spot(underlying)

        analysis = await self._analyze(underlying, entries, spot, lot_size)
        # Cache GEX so get_latest() can return it without a schema change
        self._gex_cache[underlying] = {
            "net_gex": analysis.get("net_gex"),
            "gex_positive": analysis.get("gex_positive"),
        }
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
            gex_positive = self.get_cached_gex_positive(underlying)

            return {
                "underlying": underlying,
                "captured_at": str(rows[0]["captured_at"]),
                "pcr": float(rows[0]["pcr"] or 0),
                "max_pain": float(rows[0]["max_pain"] or 0),
                "atm_iv": atm_iv,
                "iv_percentile": iv_pct,
                "iv_skew": iv_skew,
                "net_gex": net_gex,
                "gex_positive": gex_positive,
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

    async def _fetch(
        self,
        underlying: str,
        expiry: date | None = None,
        include_futures: bool = False,
    ) -> list:
        try:
            entries = await self._primary.get_option_chain(
                underlying, expiry=expiry, include_futures=include_futures
            )
            if entries:
                return entries
        except Exception as exc:
            _log.warning("option_chain primary failed %s: %s", underlying, exc)
        try:
            return await self._fallback.get_option_chain(
                underlying, expiry=expiry, include_futures=include_futures
            )
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
        """Rolling IV percentile: rank current ATM IV against last 252 trading days.

        Selects the nearest-to-ATM CE IV per calendar day (using max_pain as the
        underlying price proxy), ordered oldest-first so rows[-1] is today's value.
        """
        result = await db.execute(text("""
            SELECT DISTINCT ON (DATE(captured_at)) iv
            FROM option_chain_snapshots
            WHERE underlying = :und
              AND option_type = 'CE'
              AND iv IS NOT NULL AND iv > 0
            ORDER BY DATE(captured_at) ASC, ABS(strike - max_pain) ASC
            LIMIT :lookback
        """), {"und": underlying, "lookback": _IV_PERCENTILE_LOOKBACK + 1})
        rows = result.fetchall()
        if len(rows) < 5:
            return None
        # rows are date-ascending; last row is the most recent (current) day's ATM IV
        current_iv = float(rows[-1][0])
        if current_iv <= 0:
            return None
        historical_ivs = [float(r[0]) for r in rows[:-1] if r[0] and float(r[0]) > 0]
        if not historical_ivs:
            return None
        rank = sum(1 for v in historical_ivs if v <= current_iv)
        return round(rank / len(historical_ivs) * 100, 1)

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
        """Return GEX from the in-memory cache populated by the most recent fetch_and_store call."""
        cached = self._gex_cache.get(underlying)
        return cached.get("net_gex") if cached else None

    def get_cached_gex_positive(self, underlying: str) -> bool | None:
        """Return gex_positive from the latest fetch_and_store call, or None if not yet fetched."""
        cached = self._gex_cache.get(underlying)
        return cached.get("gex_positive") if cached else None


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
