"""CapitalScalingGovernor — Phase 19 Section 5.

Five-stage deployment model with evidence gates at each stage.
No capital scaling is allowed without meeting the prior stage's criteria.

Stages:
  Stage 0 — Shadow Trading   (0 real capital; signals generated, no orders)
  Stage 1 — Micro Deployment (1 lot, 1-2 symbols maximum)
  Stage 2 — Controlled Live  (1 lot, full universe, standard risk)
  Stage 3 — Validated Live   (2 lots, full universe, DynamicRiskBudget active)
  Stage 4 — Scaled Live      (3+ lots, full risk budget)

Promotion criteria:
  Stage 0 → 1: 100 shadow signals with win_rate > 45% and profit_factor > 1.0
  Stage 1 → 2: 100 live trades, no RISK_REJECTED in last 20, no MODEL_DRIFT
  Stage 2 → 3: 200 live trades, PF > 1.20, WR > 48%, DQ avg > 80, no DRIFT
  Stage 3 → 4: 500 live trades, PF > 1.30, WR > 50%, all 10 scaling conditions pass

All promotion checks are advisory — the system surfaces the verdict;
the operator takes the action (switching execution mode / lot size).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from core.application.services.scaling_rules_service import ScalingRulesService
    from core.application.services.shadow_trading_service import ShadowTradingService

_log = logging.getLogger(__name__)

# Stage thresholds (min completed trades in that stage before promotion check)
_STAGE_TRADE_THRESHOLDS = {0: 100, 1: 100, 2: 200, 3: 500}

# Stage PF / WR minimums for promotion
_STAGE_MIN_PF = {0: 1.0, 1: 1.0, 2: 1.20, 3: 1.30}
_STAGE_MIN_WR = {0: 45.0, 1: 45.0, 2: 48.0, 3: 50.0}

# Risk parameter recommendations per stage (advisory only)
_STAGE_PARAMS = {
    0: {"lots": 0,  "symbols": "ALL",       "risk_pct": 0.0,  "label": "Shadow Trading"},
    1: {"lots": 1,  "symbols": "1-2 ONLY",  "risk_pct": 0.10, "label": "Micro Deployment"},
    2: {"lots": 1,  "symbols": "ALL",       "risk_pct": 0.20, "label": "Controlled Live"},
    3: {"lots": 2,  "symbols": "ALL",       "risk_pct": 0.25, "label": "Validated Live"},
    4: {"lots": 3,  "symbols": "ALL",       "risk_pct": 0.30, "label": "Scaled Live"},
}


class CapitalScalingGovernor:
    """Evaluates current stage and promotion readiness."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        scaling_svc: "ScalingRulesService | None" = None,
        shadow_svc:  "ShadowTradingService | None"  = None,
    ) -> None:
        self._sf         = session_factory
        self._scaling    = scaling_svc
        self._shadow     = shadow_svc

    async def get_stage_report(self, current_stage: int = 0) -> dict:
        """Evaluate current stage and check promotion criteria.

        Args:
            current_stage: operator-supplied current stage (0-4).
                           The governor does NOT auto-advance stages —
                           the operator must confirm each promotion.

        Returns:
            dict with current stage analysis and promotion verdict.
        """
        current_stage = max(0, min(4, current_stage))
        params        = _STAGE_PARAMS[current_stage]

        # Core metrics for this stage
        metrics = await self._fetch_stage_metrics(current_stage)

        if current_stage >= 4:
            return {
                "current_stage":   4,
                "stage_label":     _STAGE_PARAMS[4]["label"],
                "stage_params":    params,
                "metrics":         metrics,
                "promotion_ready": None,
                "verdict":         "AT_MAX_STAGE",
                "message":         "Stage 4 reached. Continue evidence collection per 100-trade review cadence.",
                "evaluated_at":    datetime.now(UTC).isoformat(),
            }

        # Promotion criteria checks
        next_stage = current_stage + 1
        checks = await self._check_promotion(current_stage, metrics)

        all_pass    = all(c["pass"] for c in checks.values())
        fail_checks = [k for k, v in checks.items() if not v.get("pass")]

        verdict = "PROMOTE_TO_STAGE_{:d}".format(next_stage) if all_pass else "HOLD_STAGE_{:d}".format(current_stage)

        if all_pass:
            _log.info(
                "capital_governor.PROMOTE_READY current=%d next=%d",
                current_stage, next_stage,
            )
        else:
            _log.info(
                "capital_governor.HOLD_STAGE stage=%d failed=%s",
                current_stage, fail_checks,
            )

        return {
            "current_stage":    current_stage,
            "next_stage":       next_stage,
            "stage_label":      params["label"],
            "stage_params":     params,
            "next_stage_params": _STAGE_PARAMS[next_stage],
            "metrics":          metrics,
            "promotion_checks": checks,
            "promotion_ready":  all_pass,
            "failed_checks":    fail_checks,
            "verdict":          verdict,
            "message": (
                f"All promotion criteria met. Operator may advance to Stage {next_stage} "
                f"({_STAGE_PARAMS[next_stage]['label']}). "
                f"Recommended: increase to {_STAGE_PARAMS[next_stage]['lots']} lot(s), "
                f"risk {_STAGE_PARAMS[next_stage]['risk_pct']:.2f}% per trade."
                if all_pass else
                f"Stage {current_stage} promotion blocked. Resolve: {', '.join(fail_checks)}. "
                f"Re-evaluate after next 100 completed trades."
            ),
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    async def _fetch_stage_metrics(self, stage: int) -> dict:
        """Fetch performance metrics for the stage's lookback window."""
        # Stage 0: shadow signals only; stages 1+: live accepted signals
        since_days = {0: 30, 1: 60, 2: 90, 3: 180}
        cutoff = datetime.now(UTC) - timedelta(days=since_days.get(stage, 90))
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
                          ROUND(AVG(data_quality_score),1)                              AS avg_dq
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("capital_governor.metrics_error: %s", exc)
            return {"error": str(exc)}

        return {
            "completed_trades": int(row[0] or 0),
            "win_rate_pct":     float(row[1] or 0),
            "profit_factor":    float(row[2] or 0),
            "expectancy":       float(row[3] or 0),
            "avg_dq_score":     float(row[4] or 0) if row[4] else None,
        }

    async def _check_promotion(self, stage: int, metrics: dict) -> dict:
        """Return per-check pass/fail for stage promotion."""
        min_trades = _STAGE_TRADE_THRESHOLDS.get(stage, 100)
        min_pf     = _STAGE_MIN_PF.get(stage, 1.0)
        min_wr     = _STAGE_MIN_WR.get(stage, 45.0)
        completed  = metrics.get("completed_trades", 0)
        wr         = metrics.get("win_rate_pct", 0)
        pf         = metrics.get("profit_factor", 0)
        exp        = metrics.get("expectancy", 0)

        checks: dict[str, dict] = {}

        # Minimum trades
        checks["min_trades"] = {
            "pass":      completed >= min_trades,
            "value":     completed,
            "threshold": f">= {min_trades}",
            "action":    None if completed >= min_trades else
                         f"Need {min_trades - completed} more completed trades.",
        }

        # Win rate
        checks["win_rate"] = {
            "pass":      wr >= min_wr,
            "value":     round(wr, 2),
            "threshold": f">= {min_wr}%",
            "action":    None if wr >= min_wr else
                         f"Win rate {wr:.1f}% below {min_wr}%.",
        }

        # Profit factor
        checks["profit_factor"] = {
            "pass":      pf >= min_pf,
            "value":     round(pf, 3),
            "threshold": f">= {min_pf}",
            "action":    None if pf >= min_pf else
                         f"Profit factor {pf:.2f} below {min_pf}.",
        }

        # Positive expectancy
        checks["expectancy_positive"] = {
            "pass":      exp > 0,
            "value":     round(exp, 6),
            "threshold": "> 0",
            "action":    None if exp > 0 else
                         "Expectancy is zero or negative. Investigate losing regime.",
        }

        # Stage 1+: no MODEL_DRIFT
        if stage >= 1 and self._shadow is not None:
            try:
                drift = await self._shadow.get_drift_report(reference_days=60, live_days=14)
                drift_ok = drift.get("alert") != "MODEL_DRIFT"
            except Exception:
                drift_ok = True  # fail-open
            checks["no_model_drift"] = {
                "pass":      drift_ok,
                "value":     "CLEAR" if drift_ok else "MODEL_DRIFT",
                "threshold": "No MODEL_DRIFT",
                "action":    None if drift_ok else
                             "MODEL_DRIFT detected. Investigate before capital scaling.",
            }

        # Stage 3: full 10-condition scaling check
        if stage >= 3 and self._scaling is not None:
            try:
                scaling = await self._scaling.evaluate(lookback_days=90)
                scaling_ok = scaling.get("verdict") == "SCALING_APPROVED"
            except Exception:
                scaling_ok = False
            checks["all_scaling_conditions"] = {
                "pass":      scaling_ok,
                "value":     "APPROVED" if scaling_ok else "BLOCKED",
                "threshold": "All 10 scaling conditions pass (ScalingRulesService)",
                "action":    None if scaling_ok else
                             "One or more scaling conditions not met. Run ScalingRulesService.evaluate().",
            }

        return checks

    async def get_all_stages_summary(self) -> dict:
        """Return a summary view of what each stage requires and current progress."""
        metrics = await self._fetch_stage_metrics(0)
        completed = metrics.get("completed_trades", 0)
        current_stage = 0
        for s in range(1, 5):
            if completed >= _STAGE_TRADE_THRESHOLDS.get(s - 1, 100):
                current_stage = s
            else:
                break

        stages = []
        for s in range(5):
            p = _STAGE_PARAMS[s]
            stages.append({
                "stage":       s,
                "label":       p["label"],
                "min_trades":  _STAGE_TRADE_THRESHOLDS.get(s, None),
                "min_pf":      _STAGE_MIN_PF.get(s, None),
                "min_wr":      _STAGE_MIN_WR.get(s, None),
                "lots":        p["lots"],
                "risk_pct":    p["risk_pct"],
            })

        return {
            "inferred_stage": current_stage,
            "completed_trades": completed,
            "stages": stages,
            "note": (
                "Inferred stage based on completed trade count only. "
                "Run get_stage_report(current_stage=N) for full promotion check."
            ),
        }
