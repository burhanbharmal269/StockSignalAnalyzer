"""MarketContextEngine — Phase 21.1 §1.

Synthesises multi-index regime, India VIX, and market breadth into a single
NORMAL / CAUTION / HIGH_RISK / PANIC level.

The output is a MarketContextSnapshot consumed by SignalScannerService as a
POST-ENGINE overlay.  It never touches the scoring engine, strategy logic, or
signal generation — it only adjusts confidence and (later) position sizing.

Point scoring:
  VIX contributions    (highest threshold wins, not cumulative):
    < 16              → 0 pts
    ≥ 16              → +1 pt
    ≥ 20              → +2 pts
    ≥ 25              → +4 pts
  VIX rising            → +1 pt (extra)

  Regime contributions:
    NIFTY HIGH_VOL        → +1 pt
    NIFTY TRENDING_BEARISH → +2 pts
    BNF  HIGH_VOL or BEARISH → +1 pt
    FINNIFTY HIGH_VOL or BEARISH → +1 pt (if available)
    All 3 indices volatile simultaneously → +1 extra pt

  Breadth contributions (highest tier wins):
    ADR < 0.90 → +1 pt
    ADR < 0.70 → +2 pts
    ADR < 0.50 → +3 pts

Thresholds:
  0 pts   → NORMAL
  1-2 pts → CAUTION   (confidence -3, size 75%)
  3-4 pts → HIGH_RISK (confidence -7, size 50%)
  5+ pts  → PANIC     (confidence -12, size manual/0)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

from core.domain.value_objects.market_context_snapshot import (
    CONTEXT_CONFIDENCE_ADJ,
    CONTEXT_SIZE_MULTIPLIER,
    MarketContextSnapshot,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Regime strings that count as "bearish or highly volatile"
_BEARISH_REGIMES  = {"TRENDING_BEARISH"}
_VOLATILE_REGIMES = {"HIGH_VOLATILITY"}
_RISK_REGIMES     = _BEARISH_REGIMES | _VOLATILE_REGIMES


class MarketContextEngine:
    """Stateless computation + DB persistence of scan-cycle market context."""

    def __init__(
        self,
        session_factory: "async_sessionmaker[AsyncSession]",
    ) -> None:
        self._sf = session_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compute(
        self,
        index_regimes: dict[str, str],
        vix: float | None,
        vix_rising: bool,
        breadth: dict | None,
    ) -> MarketContextSnapshot:
        """Compute MarketContextSnapshot from current macro inputs.

        index_regimes: {symbol: regime_string}, e.g. {"NIFTY": "HIGH_VOLATILITY"}
        vix:           India VIX last reading (None if unavailable)
        vix_rising:    True when VIX latest > recent rolling average
        breadth:       dict from MarketBreadthService.get_latest() or None
        """
        score, reasons = self._score(index_regimes, vix, vix_rising, breadth)
        level          = self._level_from_score(score)

        conf_adj  = CONTEXT_CONFIDENCE_ADJ[level]
        size_mult = CONTEXT_SIZE_MULTIPLIER[level]
        reason    = "; ".join(reasons) if reasons else "all indicators normal"

        adr = float(breadth.get("advance_decline_ratio", 0)) if breadth else None
        bs  = float(breadth.get("breadth_score",         0)) if breadth else None

        snap = MarketContextSnapshot(
            level              = level,
            confidence_adj     = conf_adj,
            size_multiplier    = size_mult,
            reason             = reason,
            nifty_regime       = index_regimes.get("NIFTY"),
            bnf_regime         = index_regimes.get("BANKNIFTY"),
            finnifty_regime    = index_regimes.get("FINNIFTY"),
            vix                = vix,
            vix_rising         = vix_rising,
            breadth_score      = bs,
            advance_decline_ratio = adr,
            context_score      = score,
        )

        _log.info(
            "market_context level=%s score=%d vix=%s vix_rising=%s "
            "nifty=%s bnf=%s adr=%s reason=%s",
            level, score,
            f"{vix:.1f}" if vix is not None else "N/A",
            vix_rising,
            index_regimes.get("NIFTY", "N/A"),
            index_regimes.get("BANKNIFTY", "N/A"),
            f"{adr:.2f}" if adr is not None else "N/A",
            reason,
        )

        await self._persist(snap)
        return snap

    # ------------------------------------------------------------------
    # Private — scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _score(
        index_regimes: dict[str, str],
        vix: float | None,
        vix_rising: bool,
        breadth: dict | None,
    ) -> tuple[int, list[str]]:
        """Return (total_score, [reason_strings])."""
        pts: int = 0
        reasons: list[str] = []

        # ── VIX contribution ────────────────────────────────────────
        if vix is not None:
            if vix >= 25.0:
                pts += 4
                reasons.append(f"VIX={vix:.1f}≥25 (+4)")
            elif vix >= 20.0:
                pts += 2
                reasons.append(f"VIX={vix:.1f}≥20 (+2)")
            elif vix >= 16.0:
                pts += 1
                reasons.append(f"VIX={vix:.1f}≥16 (+1)")

            if vix_rising:
                pts += 1
                reasons.append("VIX rising (+1)")

        # ── Regime contributions ─────────────────────────────────────
        nifty_reg = index_regimes.get("NIFTY", "")
        bnf_reg   = index_regimes.get("BANKNIFTY", "")
        fin_reg   = index_regimes.get("FINNIFTY", "")

        if nifty_reg in _BEARISH_REGIMES:
            pts += 2
            reasons.append(f"NIFTY={nifty_reg} (+2)")
        elif nifty_reg in _VOLATILE_REGIMES:
            pts += 1
            reasons.append(f"NIFTY={nifty_reg} (+1)")

        if bnf_reg in _RISK_REGIMES:
            pts += 1
            reasons.append(f"BNF={bnf_reg} (+1)")

        if fin_reg in _RISK_REGIMES:
            pts += 1
            reasons.append(f"FINNIFTY={fin_reg} (+1)")

        # Extra point if all 3 major indices are simultaneously in risk regimes
        if (nifty_reg in _RISK_REGIMES and bnf_reg in _RISK_REGIMES
                and fin_reg and fin_reg in _RISK_REGIMES):
            pts += 1
            reasons.append("all 3 indices volatile (+1)")

        # ── Breadth contribution ─────────────────────────────────────
        if breadth:
            adr = breadth.get("advance_decline_ratio")
            if adr is not None:
                adr = float(adr)
                if adr < 0.50:
                    pts += 3
                    reasons.append(f"ADR={adr:.2f}<0.50 (+3)")
                elif adr < 0.70:
                    pts += 2
                    reasons.append(f"ADR={adr:.2f}<0.70 (+2)")
                elif adr < 0.90:
                    pts += 1
                    reasons.append(f"ADR={adr:.2f}<0.90 (+1)")

        return pts, reasons

    @staticmethod
    def _level_from_score(score: int) -> str:
        if score >= 5:
            return "PANIC"
        if score >= 3:
            return "HIGH_RISK"
        if score >= 1:
            return "CAUTION"
        return "NORMAL"

    # ------------------------------------------------------------------
    # Private — persistence
    # ------------------------------------------------------------------

    async def _persist(self, snap: MarketContextSnapshot) -> None:
        try:
            async with self._sf() as db:
                await db.execute(
                    text("""
                        INSERT INTO market_context_snapshots
                            (level, confidence_adj, size_multiplier, reason, context_score,
                             nifty_regime, bnf_regime, finnifty_regime,
                             vix, vix_rising, breadth_score, advance_decline_ratio, computed_at)
                        VALUES
                            (:level, :conf_adj, :size_mult, :reason, :score,
                             :nifty, :bnf, :fin,
                             :vix, :vix_rising, :breadth_score, :adr, :computed_at)
                    """),
                    {
                        "level":        snap.level,
                        "conf_adj":     snap.confidence_adj,
                        "size_mult":    snap.size_multiplier,
                        "reason":       snap.reason,
                        "score":        snap.context_score,
                        "nifty":        snap.nifty_regime,
                        "bnf":          snap.bnf_regime,
                        "fin":          snap.finnifty_regime,
                        "vix":          snap.vix,
                        "vix_rising":   snap.vix_rising,
                        "breadth_score": snap.breadth_score,
                        "adr":          snap.advance_decline_ratio,
                        "computed_at":  snap.computed_at,
                    },
                )
                await db.commit()
        except Exception as exc:
            # ERROR not WARNING: stale DB means PipelineEventHandler reads wrong size_multiplier
            _log.error("market_context.persist_failed — size_multiplier in DB is stale: %s", exc)
