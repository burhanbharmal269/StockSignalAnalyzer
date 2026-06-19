"""ScalingRulesService — Phase 18J capital scaling validation.

All 10 conditions must pass before scaling capital from small to full deployment.
Any single failure blocks scaling. No partial override allowed.

Conditions (Section J):
  SC-J1  Profit Factor > 1.30
  SC-J2  Win Rate > 45%
  SC-J3  Expectancy > 0
  SC-J4  Max Drawdown within configured limit
  SC-J5  500+ completed live trades
  SC-J6  Risk Manager healthy (no current lock)
  SC-J7  Data Quality Score average > 85
  SC-J8  Execution Quality Score > 85 (from ExecutionLifecycleService)
  SC-J9  MTF validation complete (AC-5 passes: conflict underperforms baseline)
  SC-J10 Score bucket monotonicity confirmed (no SCORE_CALIBRATION_REQUIRED flag)

When all pass:
  Returns SCALING_APPROVED with a written plan.

When any fail:
  Returns SCALING_BLOCKED with per-condition details and corrective actions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from core.application.services.execution_lifecycle_service import ExecutionLifecycleService
    from core.application.services.risk_manager_service import RiskManagerService
    from core.application.services.signal_intelligence_service import SignalIntelligenceService

_log = logging.getLogger(__name__)

# Thresholds
_MIN_PROFIT_FACTOR   = 1.30
_MIN_WIN_RATE        = 45.0
_MIN_COMPLETED_TRADES = 500
_MAX_DRAWDOWN_PCT    = 20.0    # max acceptable peak-to-trough drawdown %
_MIN_DQ_SCORE        = 85.0
_MIN_EQ_SCORE        = 85.0


class ScalingRulesService:
    """Evaluates all 10 scaling conditions and returns structured verdict."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        risk_manager: "RiskManagerService | None" = None,
        execution_svc: "ExecutionLifecycleService | None" = None,
        intelligence_svc: "SignalIntelligenceService | None" = None,
    ) -> None:
        self._sf       = session_factory
        self._risk_mgr = risk_manager
        self._exec_svc = execution_svc
        self._intel    = intelligence_svc

    async def evaluate(self, lookback_days: int = 90) -> dict:
        """Evaluate all 10 scaling conditions.

        Returns verdict: SCALING_APPROVED or SCALING_BLOCKED.
        All conditions are evaluated even when early ones fail (no short-circuit)
        so the operator sees the full picture.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        conditions: dict[str, dict] = {}

        # ── Fetch core metrics from signal_analytics ──
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*)                                                       AS completed,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,2)  AS win_rate,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          ,3)                                                            AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)        AS expectancy,
                          ROUND(AVG(data_quality_score),1)                              AS avg_dq,
                          ROUND(MAX(mae_pct)*100,2)                                    AS max_drawdown
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("scaling_rules.db_error: %s", exc)
            return {"verdict": "SCALING_BLOCKED", "error": str(exc), "conditions": {}}

        completed    = int(row[0] or 0)
        win_rate     = float(row[1] or 0)
        pf           = float(row[2] or 0)
        expectancy   = float(row[3] or 0)
        avg_dq       = float(row[4] or 0) if row[4] else 0.0
        max_drawdown = float(row[5] or 0)

        # SC-J1: Profit Factor > 1.30
        conditions["SC_J1_profit_factor"] = {
            "pass":      pf > _MIN_PROFIT_FACTOR,
            "value":     round(pf, 3),
            "threshold": f"> {_MIN_PROFIT_FACTOR}",
            "action":    None if pf > _MIN_PROFIT_FACTOR else
                         "Profit factor below threshold. Allow 100 more trades before re-evaluation.",
        }

        # SC-J2: Win Rate > 45%
        conditions["SC_J2_win_rate"] = {
            "pass":      win_rate > _MIN_WIN_RATE,
            "value":     round(win_rate, 2),
            "threshold": f"> {_MIN_WIN_RATE}%",
            "action":    None if win_rate > _MIN_WIN_RATE else
                         "Win rate below 45%. Review UNDERPERFORMING_REGIME report and consider regime-specific floor adjustments.",
        }

        # SC-J3: Expectancy > 0
        conditions["SC_J3_expectancy"] = {
            "pass":      expectancy > 0,
            "value":     round(expectancy, 6),
            "threshold": "> 0",
            "action":    None if expectancy > 0 else
                         "Expectancy is zero or negative. Do not scale. Investigate with MTF and regime breakdown.",
        }

        # SC-J4: Drawdown within limit
        conditions["SC_J4_drawdown"] = {
            "pass":      max_drawdown <= _MAX_DRAWDOWN_PCT,
            "value":     round(max_drawdown, 2),
            "threshold": f"<= {_MAX_DRAWDOWN_PCT}%",
            "action":    None if max_drawdown <= _MAX_DRAWDOWN_PCT else
                         f"Max adverse excursion {max_drawdown:.1f}% exceeds limit. Review exit timing and SL calibration.",
        }

        # SC-J5: 500+ completed trades
        conditions["SC_J5_completed_trades"] = {
            "pass":      completed >= _MIN_COMPLETED_TRADES,
            "value":     completed,
            "threshold": f">= {_MIN_COMPLETED_TRADES}",
            "action":    None if completed >= _MIN_COMPLETED_TRADES else
                         f"Need {_MIN_COMPLETED_TRADES - completed} more completed trades. Continue shadow/small-capital phase.",
        }

        # SC-J6: Risk Manager healthy (no current lock)
        if self._risk_mgr is not None:
            try:
                risk_status = await self._risk_mgr.get_status()
                risk_locked = bool(risk_status.get("risk_locked", False))
            except Exception:
                risk_locked = False
        else:
            risk_locked = False

        conditions["SC_J6_risk_manager_healthy"] = {
            "pass":      not risk_locked,
            "value":     "LOCKED" if risk_locked else "HEALTHY",
            "threshold": "HEALTHY",
            "action":    None if not risk_locked else
                         "Risk manager is currently locked. Resolve the lock condition before evaluating scaling.",
        }

        # SC-J7: Data Quality Score > 85
        conditions["SC_J7_data_quality"] = {
            "pass":      avg_dq >= _MIN_DQ_SCORE,
            "value":     round(avg_dq, 1),
            "threshold": f">= {_MIN_DQ_SCORE}",
            "action":    None if avg_dq >= _MIN_DQ_SCORE else
                         "Average data quality below 85. Investigate feed reliability for option chain, VIX, and 5m candles.",
        }

        # SC-J8: Execution Quality Score > 85
        if self._exec_svc is not None:
            try:
                eq_report = await self._exec_svc.get_fill_quality_report(lookback_days=lookback_days)
                eq_score  = eq_report.get("execution_quality_score")
            except Exception:
                eq_score = None
        else:
            eq_score = None

        if eq_score is None:
            conditions["SC_J8_execution_quality"] = {
                "pass":   None,
                "value":  "NO_DATA",
                "threshold": f">= {_MIN_EQ_SCORE}",
                "action": "No execution data yet (system in shadow mode). This condition will auto-evaluate when live orders are placed.",
            }
        else:
            conditions["SC_J8_execution_quality"] = {
                "pass":      eq_score >= _MIN_EQ_SCORE,
                "value":     eq_score,
                "threshold": f">= {_MIN_EQ_SCORE}",
                "action":    None if eq_score >= _MIN_EQ_SCORE else
                             "Execution quality below 85. Check slippage, fill rate, and latency reports.",
            }

        # SC-J9: MTF validation complete (AC-5 passes)
        if self._intel is not None:
            try:
                mtf = await self._intel.get_mtf_retention_analysis(lookback_days=lookback_days)
                ac5 = mtf.get("criteria", {}).get("ac5_conflict_underperforms")
                mtf_ok = bool(ac5) if ac5 is not None else None
            except Exception:
                mtf_ok = None
        else:
            mtf_ok = None

        conditions["SC_J9_mtf_validated"] = {
            "pass":      mtf_ok,
            "value":     "AC5_PASS" if mtf_ok else ("INSUFFICIENT_DATA" if mtf_ok is None else "AC5_FAIL"),
            "threshold": "AC-5 passes (conflict signals underperform baseline)",
            "action":    None if mtf_ok else
                         ("Run MTF retention analysis after 200+ completed trades." if mtf_ok is None else
                          "AC-5 fails: conflict signals do not underperform baseline. Remove MTF or reduce its weight before scaling."),
        }

        # SC-J10: Score bucket monotonicity
        if self._intel is not None:
            try:
                buckets = await self._intel.get_score_bucket_performance(lookback_days=lookback_days)
                # monotonic if all calibration_ok flags are True (requires enough data)
                has_data = len(buckets) >= 3
                mono     = all(b.get("calibration_ok", False) for b in buckets) if has_data else None
            except Exception:
                mono = None
        else:
            mono = None

        conditions["SC_J10_score_monotonic"] = {
            "pass":      mono,
            "value":     "MONOTONIC" if mono else ("INSUFFICIENT_DATA" if mono is None else "NON_MONOTONIC"),
            "threshold": "Score buckets show monotonically improving performance",
            "action":    None if mono else
                         ("Need 3+ score buckets with sufficient data." if mono is None else
                          "Non-monotonic score buckets detected. Run SCORE_CALIBRATION_REQUIRED report and identify which bucket boundary breaks."),
        }

        # ── Verdict ──
        # Conditions where pass=None (insufficient data) are treated as blocking for scaling
        all_passed = all(
            c.get("pass") is True
            for c in conditions.values()
            if c.get("pass") is not None   # skip truly unevaluable (no data)
        )
        has_none   = any(c.get("pass") is None for c in conditions.values())
        blocked_conditions = [k for k, v in conditions.items() if v.get("pass") is not True]

        if all_passed and not has_none:
            verdict = "SCALING_APPROVED"
            plan = (
                "All 10 conditions passed. Recommended scaling plan: "
                "(1) Increase to 2 lots for 50 trades. (2) Verify PF and win rate hold. "
                "(3) Increase to 3 lots if no degradation. (4) Reassess every 100 trades. "
                "(5) Never exceed 1% daily portfolio risk per DynamicRiskBudgetService."
            )
        else:
            verdict = "SCALING_BLOCKED"
            plan = (
                f"SCALING BLOCKED: {len(blocked_conditions)} condition(s) not satisfied. "
                f"Failed: {', '.join(blocked_conditions)}. "
                "Resolve all conditions before re-evaluation. "
                "Re-evaluate after next 100 completed trades."
            )

        _log.info(
            "scaling_rules.verdict=%s passed=%d/%d blocked=%s",
            verdict, sum(1 for c in conditions.values() if c.get("pass") is True),
            len(conditions), blocked_conditions,
        )

        return {
            "evaluated_at":         datetime.now(UTC).isoformat(),
            "lookback_days":        lookback_days,
            "verdict":              verdict,
            "conditions":           conditions,
            "blocked_conditions":   blocked_conditions,
            "scaling_plan":         plan,
            "metrics_summary": {
                "completed_trades": completed,
                "win_rate_pct":     win_rate,
                "profit_factor":    pf,
                "expectancy":       expectancy,
                "max_drawdown_pct": max_drawdown,
                "avg_dq_score":     avg_dq,
            },
        }
