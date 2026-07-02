"""OptionChainIntelligenceWorker — Phase 22 §1.

Pre-computes option chain analytics for every active F&O symbol and caches
results in Redis for instant scanner reads (no DB queries during signal generation).

Redis key : oc:intel:{symbol}
TTL       : 300 s (5 minutes — aligns with OptionChainPollerService interval)

Cached per symbol
-----------------
PCR, total CE/PE OI, change in CE/PE OI, max pain, ATM IV, IV skew,
OI buildup patterns, call/put wall, support/resistance strikes,
liquidity score, avg bid-ask spread, top-5 liquid strikes.

The scanner reads from Redis via `get_cached(symbol)` before falling back
to a direct DB query — eliminating per-symbol DB round-trips during scans.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

_log = logging.getLogger(__name__)

_CACHE_TTL = 300   # seconds

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from core.application.services.option_chain_service import OptionChainService
    from core.application.services.market_universe_service import MarketUniverseService


class OptionChainIntelligenceWorker:
    """Computes and caches option chain intelligence for the scanner.

    Called after every OptionChainPollerService cycle.
    """

    def __init__(
        self,
        option_chain_svc: "OptionChainService",
        universe_svc: "MarketUniverseService",
        redis_client: "Redis",
    ) -> None:
        self._oc = option_chain_svc
        self._universe = universe_svc
        self._redis = redis_client

    # ── Public ──────────────────────────────────────────────────────────────

    async def run_cycle(self) -> dict[str, int]:
        """Process all active F&O symbols. Fail-open — never raises."""
        symbols = await self._universe.get_active_symbols(fo_only=True)
        ok = errors = 0
        for sym in symbols:
            try:
                await self._process_symbol(sym.symbol)
                ok += 1
            except Exception as exc:
                errors += 1
                _log.debug("oc_intel.process_failed symbol=%s: %s", sym.symbol, exc)
        _log.info("oc_intel.cycle_done cached=%d errors=%d", ok, errors)
        return {"cached": ok, "errors": errors}

    async def get_cached(self, symbol: str) -> dict[str, Any] | None:
        """Read pre-computed intel from Redis. Returns None on miss or error."""
        try:
            raw = await self._redis.get(f"oc:intel:{symbol}")
            return json.loads(raw) if raw else None
        except Exception as exc:
            _log.debug("oc_intel.get_cached_failed symbol=%s: %s", symbol, exc)
            return None

    async def invalidate(self, symbol: str) -> None:
        """Remove cached intel for a symbol (called after live refresh)."""
        try:
            await self._redis.delete(f"oc:intel:{symbol}")
        except Exception:
            pass

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _process_symbol(self, symbol: str) -> None:
        data = await self._oc.get_latest(symbol)
        if not data:
            return
        intel = _compute_intel(symbol, data)
        raw = json.dumps(intel, default=str)
        await self._redis.setex(f"oc:intel:{symbol}", _CACHE_TTL, raw)

    async def cache_from_data(self, symbol: str, data: dict) -> None:
        """Called directly by OptionChainService after fetch_and_store()."""
        try:
            intel = _compute_intel(symbol, data)
            raw = json.dumps(intel, default=str)
            await self._redis.setex(f"oc:intel:{symbol}", _CACHE_TTL, raw)
        except Exception as exc:
            _log.debug("oc_intel.cache_from_data_failed symbol=%s: %s", symbol, exc)


# ── Pure analytics ────────────────────────────────────────────────────────────

def _compute_intel(symbol: str, data: dict) -> dict[str, Any]:
    """Derive enhanced metrics from a `get_latest()` payload."""
    entries: list[dict] = data.get("entries") or []
    pcr: float = float(data.get("pcr") or 0)
    max_pain: float = float(data.get("max_pain") or 0)
    iv_percentile: float | None = data.get("iv_percentile")
    iv_skew: float | None = data.get("iv_skew")
    gex_positive: bool | None = data.get("gex_positive")

    ce_entries = [e for e in entries if str(e.get("option_type", "")).upper() == "CE"]
    pe_entries = [e for e in entries if str(e.get("option_type", "")).upper() == "PE"]

    total_ce_oi = sum(int(e.get("oi") or 0) for e in ce_entries)
    total_pe_oi = sum(int(e.get("oi") or 0) for e in pe_entries)
    change_ce_oi = sum(int(e.get("change_in_oi") or 0) for e in ce_entries)
    change_pe_oi = sum(int(e.get("change_in_oi") or 0) for e in pe_entries)

    # OI buildup patterns per-entry
    long_buildup = short_buildup = long_unwinding = short_covering = 0
    for e in entries:
        pattern = str(e.get("oi_buildup_pattern") or "")
        if pattern == "LONG_BUILDUP":
            long_buildup += 1
        elif pattern == "SHORT_BUILDUP":
            short_buildup += 1
        elif pattern == "LONG_UNWINDING":
            long_unwinding += 1
        elif pattern == "SHORT_COVERING":
            short_covering += 1

    # Call wall: highest-OI call strike above ATM (use max_pain as proxy for ATM)
    call_wall: float | None = None
    put_wall: float | None = None
    support_strike: float | None = None
    resistance_strike: float | None = None

    ref_price = max_pain or 0.0
    if ref_price > 0 and entries:
        ce_above = [e for e in ce_entries
                    if float(e.get("strike") or 0) > ref_price and int(e.get("oi") or 0) > 0]
        if ce_above:
            top_ce = max(ce_above, key=lambda e: int(e.get("oi") or 0))
            call_wall = float(top_ce["strike"])
            resistance_strike = call_wall

        pe_below = [e for e in pe_entries
                    if float(e.get("strike") or 0) < ref_price and int(e.get("oi") or 0) > 0]
        if pe_below:
            top_pe = max(pe_below, key=lambda e: int(e.get("oi") or 0))
            put_wall = float(top_pe["strike"])
            support_strike = put_wall

    # Top-5 liquid strikes (by OI, any side)
    sorted_by_oi = sorted(entries, key=lambda e: int(e.get("oi") or 0), reverse=True)
    top5 = [
        {
            "strike": float(e.get("strike") or 0),
            "opt_type": str(e.get("option_type") or ""),
            "oi": int(e.get("oi") or 0),
            "ltp": float(e.get("ltp") or 0),
        }
        for e in sorted_by_oi[:5]
    ]

    # Liquidity score 0-100: based on total OI, entry count, and spread quality
    liq_score = _liquidity_score(entries, total_ce_oi + total_pe_oi)

    # Average bid-ask spread proxy: (ltp range / ltp mean) * 100 for liquid strikes
    avg_spread = _avg_spread_proxy(entries)

    snap_ts = data.get("snapshot_ts") or data.get("updated_at")

    return {
        "symbol": symbol,
        "pcr": round(pcr, 4),
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "change_ce_oi": change_ce_oi,
        "change_pe_oi": change_pe_oi,
        "max_pain": max_pain,
        "atm_iv": iv_percentile,
        "iv_skew": iv_skew,
        "gex_positive": gex_positive,
        "long_buildup": long_buildup,
        "short_buildup": short_buildup,
        "long_unwinding": long_unwinding,
        "short_covering": short_covering,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "support_strike": support_strike,
        "resistance_strike": resistance_strike,
        "liquidity_score": liq_score,
        "avg_spread_pct": avg_spread,
        "top5_liquid_strikes": top5,
        "entry_count": len(entries),
        "cached_at": datetime.now(UTC).isoformat(),
        "snapshot_ts": str(snap_ts) if snap_ts else None,
    }


def _liquidity_score(entries: list[dict], total_oi: int) -> int:
    """Score 0-100 based on OI volume and chain depth."""
    if not entries or total_oi == 0:
        return 0
    depth_score  = min(len(entries) / 60 * 40, 40)          # up to 40 pts for chain width
    oi_score     = min(total_oi / 5_000_000 * 40, 40)       # up to 40 pts for OI volume
    active = sum(1 for e in entries if int(e.get("oi") or 0) > 500)
    active_score = min(active / 30 * 20, 20)                 # up to 20 pts for active strikes
    return round(depth_score + oi_score + active_score)


def _avg_spread_proxy(entries: list[dict]) -> float | None:
    """Estimate spread as % of premium for liquid strikes (OI > 1000)."""
    liquid = [e for e in entries if int(e.get("oi") or 0) > 1000 and float(e.get("ltp") or 0) > 4]
    if len(liquid) < 3:
        return None
    spreads = []
    for e in liquid:
        ltp = float(e.get("ltp") or 0)
        if ltp > 0:
            # Estimate: tick size on NSE options = ₹0.05; spread ≈ 1-2 ticks
            spreads.append(round(0.10 / ltp * 100, 3))
    return round(sum(spreads) / len(spreads), 3) if spreads else None
