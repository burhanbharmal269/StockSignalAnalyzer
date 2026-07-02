"""MarketRegimeSnapshotService — Phase 22 §3.

Classifies the current market regime once per scan cycle using VIX,
market context, breadth data, and gap/expiry detection.

Regimes
-------
STRONG_TRENDING   — ADX-equivalent breadth + VIX moderate + clear direction
TRENDING          — Directional with moderate conviction
RANGE_BOUND       — Low volatility, no clear direction
HIGH_VOLATILITY   — VIX > 20 or extreme breadth divergence
LOW_VOLATILITY    — VIX < 12, compressed range
EXPIRY_BEHAVIOUR  — NIFTY/BANKNIFTY/FINNIFTY expiry day
GAP_DAY           — Open gap > 1% from previous close
EVENT_DRIVEN      — Known macro/earnings event active today

Analytics only — never affects trade filters or execution decisions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, date
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# VIX thresholds (INDIA VIX)
_VIX_LOW       = 12.0
_VIX_HIGH      = 20.0
_VIX_EXTREME   = 30.0

# Gap threshold (% gap from previous close)
_GAP_THRESHOLD = 1.0

# Expiry weekday mappings (0=Mon … 6=Sun)
# NIFTY/MIDCPNIFTY: Thursday weekly; BANKNIFTY: Wednesday monthly;
# FINNIFTY: Tuesday monthly; Stock options: last Thursday of month.
_NIFTY_EXPIRY_WEEKDAY   = 3  # Thursday
_BANKNIFTY_EXPIRY_WEEKDAY = 2  # Wednesday
_FINNIFTY_EXPIRY_WEEKDAY  = 1  # Tuesday


class MarketRegimeSnapshotService:
    """Classifies the overall market regime once per scan cycle."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        self._prev_nifty_close: float | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def classify_and_store(
        self,
        vix: float | None,
        nifty_regime: str | None,
        breadth_score: float | None,
        advance_decline_ratio: float | None,
        nifty_close: float | None = None,
        event_active: bool = False,
    ) -> dict[str, Any]:
        """Classify current market regime and persist to DB. Fail-open."""
        try:
            today = date.today()
            is_expiry = _is_expiry_day(today)
            gap_pct   = _compute_gap_pct(self._prev_nifty_close, nifty_close)

            regime, sub_regime = _classify(
                vix=vix,
                nifty_regime=nifty_regime,
                breadth_score=breadth_score,
                is_expiry=is_expiry,
                gap_pct=gap_pct,
                event_active=event_active,
            )
            vix_regime = _vix_regime_label(vix)

            snapshot: dict[str, Any] = {
                "regime": regime,
                "sub_regime": sub_regime,
                "vix_level": vix,
                "vix_regime": vix_regime,
                "nifty_regime": nifty_regime,
                "breadth_score": breadth_score,
                "advance_decline_ratio": advance_decline_ratio,
                "is_expiry_day": is_expiry,
                "gap_pct": gap_pct,
                "indicators": {
                    "vix": vix,
                    "breadth_score": breadth_score,
                    "ad_ratio": advance_decline_ratio,
                    "gap_pct": gap_pct,
                    "event_active": event_active,
                },
                "scanned_at": datetime.now(UTC).isoformat(),
            }

            await self._persist(snapshot)

            if nifty_close is not None:
                self._prev_nifty_close = nifty_close

            _log.info(
                "market_regime.classified regime=%s sub=%s vix=%.1f gap_pct=%s expiry=%s",
                regime, sub_regime or "-",
                vix or 0,
                f"{gap_pct:.2f}%" if gap_pct is not None else "N/A",
                is_expiry,
            )
            return snapshot
        except Exception as exc:
            _log.warning("market_regime.classify_failed: %s", exc)
            return {"regime": "UNKNOWN", "sub_regime": None}

    async def get_latest(self) -> dict[str, Any] | None:
        """Return the most recent regime snapshot."""
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT id, scanned_at, regime, sub_regime, vix_level, vix_regime,
                       nifty_regime, breadth_score, advance_decline_ratio,
                       is_expiry_day, gap_pct, indicators
                FROM scanner_regime_snapshots
                ORDER BY scanned_at DESC LIMIT 1
            """))
            row = r.mappings().fetchone()
            return dict(row) if row else None

    async def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent regime history."""
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT scanned_at, regime, sub_regime, vix_level, breadth_score, is_expiry_day
                FROM scanner_regime_snapshots
                ORDER BY scanned_at DESC LIMIT :lim
            """), {"lim": limit})
            return [dict(row) for row in r.mappings().fetchall()]

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _persist(self, snap: dict) -> None:
        import json
        async with self._sf() as db:
            await db.execute(text("""
                INSERT INTO scanner_regime_snapshots
                    (scanned_at, regime, sub_regime, vix_level, vix_regime, nifty_regime,
                     breadth_score, advance_decline_ratio, is_expiry_day, gap_pct, indicators)
                VALUES
                    (NOW(), :regime, :sub, :vix, :vix_r, :nifty_r,
                     :breadth, :ad_ratio, :expiry, :gap, :indicators::jsonb)
            """), {
                "regime":    snap["regime"],
                "sub":       snap.get("sub_regime"),
                "vix":       snap.get("vix_level"),
                "vix_r":     snap.get("vix_regime"),
                "nifty_r":   snap.get("nifty_regime"),
                "breadth":   snap.get("breadth_score"),
                "ad_ratio":  snap.get("advance_decline_ratio"),
                "expiry":    snap.get("is_expiry_day", False),
                "gap":       snap.get("gap_pct"),
                "indicators": json.dumps(snap.get("indicators") or {}),
            })
            await db.commit()


# ── Pure classification logic ─────────────────────────────────────────────────

def _classify(
    vix: float | None,
    nifty_regime: str | None,
    breadth_score: float | None,
    is_expiry: bool,
    gap_pct: float | None,
    event_active: bool,
) -> tuple[str, str | None]:
    """Return (regime, sub_regime)."""

    # Priority-ordered classification
    if event_active:
        return "EVENT_DRIVEN", None

    if is_expiry:
        return "EXPIRY_BEHAVIOUR", None

    if gap_pct is not None and abs(gap_pct) >= _GAP_THRESHOLD:
        sub = "GAP_UP" if gap_pct > 0 else "GAP_DOWN"
        return "GAP_DAY", sub

    if vix is not None and vix >= _VIX_EXTREME:
        return "HIGH_VOLATILITY", "EXTREME"

    if vix is not None and vix >= _VIX_HIGH:
        return "HIGH_VOLATILITY", "ELEVATED"

    if vix is not None and vix <= _VIX_LOW:
        return "LOW_VOLATILITY", None

    # Directional regime from nifty context + breadth
    regime_str = str(nifty_regime or "").upper()
    is_directional = regime_str in ("TRENDING_BULLISH", "TRENDING_BEARISH", "TRENDING")
    bs = breadth_score or 0.0

    if is_directional and abs(bs) >= 40:
        return "STRONG_TRENDING", "BULLISH" if bs > 0 else "BEARISH"

    if is_directional or abs(bs) >= 20:
        return "TRENDING", "BULLISH" if bs >= 0 else "BEARISH"

    return "RANGE_BOUND", None


def _is_expiry_day(today: date) -> bool:
    """True on NIFTY (Thu), BANKNIFTY (Wed), or FINNIFTY (Tue) expiry weekdays."""
    return today.weekday() in (
        _NIFTY_EXPIRY_WEEKDAY,
        _BANKNIFTY_EXPIRY_WEEKDAY,
        _FINNIFTY_EXPIRY_WEEKDAY,
    )


def _compute_gap_pct(prev_close: float | None, current: float | None) -> float | None:
    if prev_close is None or current is None or prev_close == 0:
        return None
    return round((current - prev_close) / prev_close * 100, 3)


def _vix_regime_label(vix: float | None) -> str | None:
    if vix is None:
        return None
    if vix >= _VIX_EXTREME:
        return "EXTREME"
    if vix >= _VIX_HIGH:
        return "HIGH"
    if vix <= _VIX_LOW:
        return "LOW"
    return "MODERATE"
