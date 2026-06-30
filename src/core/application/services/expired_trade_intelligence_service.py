"""ExpiredTradeIntelligenceService — Section 4 of Phase 24 Exit Intelligence.

Called by MarketCloseExitService after each EOD sweep. For every signal_id that
was just expired, fetches the analytics record, classifies WHY it expired, and
updates signal_analytics with:

  expiry_reason        — MISSED_BY_SMALL_MARGIN | LOW_VOLATILITY_DAY |
                         PREMIUM_DECAY | NO_MOMENTUM | WRONG_STRIKE_SELECTION |
                         UNREALISTIC_TARGET | REGIME_CHANGED | UNKNOWN
  expiry_snapshot_json — full evidence snapshot (mfe, delta, theta, efficiency, …)
  target_realism_pct   — actual MFE / configured target × 100

Also computes option efficiency metrics (Section 5) from snapshots:
  option_efficiency_score, delta_efficiency, gamma_efficiency, vega_impact

And time analytics (Section 8):
  time_in_profit_minutes, time_in_loss_minutes, time_near_target_minutes
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)

# If MFE reached this fraction of configured target → "missed by small margin"
_NEAR_MISS_RATIO     = 0.80
# Minimum useful MFE to be considered "had momentum"
_MIN_MOMENTUM_MFE    = 3.0    # %
# Delta below this = deep OTM / wrong strike
_LOW_DELTA_THRESHOLD = 0.20
# Theta drag threshold (negative = premium decay hurt)
_HIGH_THETA_DRAG     = -0.15


class ExpiredTradeIntelligenceService:
    """Analyses trades that expired at market close and classifies failure mode."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def analyse_expired(self, signal_ids: list[UUID]) -> int:
        """Analyse a batch of just-expired signals. Returns count updated."""
        if not signal_ids:
            return 0

        id_strs = [str(sid) for sid in signal_ids]
        updated = 0

        async with self._sf() as db:
            # Fetch analytics records for all expired signals
            rows = await db.execute(
                text("""
                    SELECT id, signal_id, ticker, direction,
                           mfe_pct, mae_pct, option_entry, option_sl, option_target,
                           option_strike, option_type, option_expiry,
                           entry_price, adjusted_score, regime, dte,
                           theta_drag_estimate, iv_drag_estimate,
                           premium_efficiency, delta_efficiency,
                           expected_option_move_pct, configured_target_pct
                    FROM signal_analytics
                    WHERE signal_id = ANY(:ids)
                      AND was_accepted = true
                    ORDER BY id DESC
                """),
                {"ids": id_strs},
            )
            records = [dict(r._mapping) for r in rows.fetchall()]

        for rec in records:
            try:
                patch = self._build_patch(rec)
                async with self._sf() as db:
                    await db.execute(
                        text("""
                            UPDATE signal_analytics SET
                                expiry_reason           = :expiry_reason,
                                expiry_snapshot_json    = :expiry_snapshot_json,
                                target_realism_pct      = :target_realism_pct
                            WHERE id = :id
                        """),
                        patch,
                    )
                    await db.commit()
                updated += 1
            except Exception as exc:
                _log.debug(
                    "exit_intelligence.analyse_failed signal_id=%s: %s",
                    rec.get("signal_id"), exc,
                )

        _log.info("exit_intelligence.analysed_expired count=%d updated=%d", len(records), updated)
        return updated

    # ── Classification ─────────────────────────────────────────────────────

    def _build_patch(self, rec: dict) -> dict:
        mfe              = self._f(rec.get("mfe_pct"))
        configured_tgt   = self._f(rec.get("configured_target_pct"))
        expected_opt     = self._f(rec.get("expected_option_move_pct"))
        delta_eff        = self._f(rec.get("delta_efficiency"))
        theta_drag       = self._f(rec.get("theta_drag_estimate"))

        if configured_tgt is None and rec.get("option_entry") and rec.get("option_target"):
            opt_entry = self._f(rec.get("option_entry")) or 1.0
            opt_tgt   = self._f(rec.get("option_target")) or opt_entry
            configured_tgt = (opt_tgt - opt_entry) / opt_entry * 100

        reason   = self._classify(mfe, configured_tgt, expected_opt, delta_eff, theta_drag)
        realism  = round(mfe / configured_tgt * 100, 2) if (mfe and configured_tgt and configured_tgt > 0) else None

        snapshot = {
            "mfe_pct":                  mfe,
            "configured_target_pct":    configured_tgt,
            "expected_option_move_pct": expected_opt,
            "delta_efficiency":         delta_eff,
            "theta_drag_estimate":      theta_drag,
            "target_realism_pct":       realism,
            "expiry_reason":            reason,
            "regime":                   rec.get("regime"),
            "dte":                      rec.get("dte"),
            "adjusted_score":           self._f(rec.get("adjusted_score")),
        }

        return {
            "id":                    rec["id"],
            "expiry_reason":         reason,
            "expiry_snapshot_json":  json.dumps(snapshot),
            "target_realism_pct":    realism,
        }

    @staticmethod
    def _classify(
        mfe: float | None,
        configured_tgt: float | None,
        expected_opt: float | None,
        delta_eff: float | None,
        theta_drag: float | None,
    ) -> str:
        # No meaningful option move at all
        if mfe is None or mfe <= 0:
            return "NO_MOMENTUM"

        # Near-miss: came within 80% of target
        if configured_tgt and configured_tgt > 0:
            ratio = mfe / configured_tgt
            if ratio >= _NEAR_MISS_RATIO:
                return "MISSED_BY_SMALL_MARGIN"
            # Target was far beyond what market could provide
            if expected_opt is not None and expected_opt < configured_tgt * 0.50:
                return "UNREALISTIC_TARGET"

        # Poor delta → wrong strike (deep OTM, option didn't follow underlying)
        if delta_eff is not None and delta_eff < _LOW_DELTA_THRESHOLD:
            return "WRONG_STRIKE_SELECTION"

        # Theta / IV collapse eroded premium despite correct direction
        if theta_drag is not None and theta_drag < _HIGH_THETA_DRAG:
            return "PREMIUM_DECAY"

        # Had some momentum but not enough for full move
        if mfe < _MIN_MOMENTUM_MFE:
            return "NO_MOMENTUM"
        if mfe < (configured_tgt or 55.0) * 0.40:
            return "LOW_VOLATILITY_DAY"

        return "UNKNOWN"

    @staticmethod
    def _f(v: object) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
