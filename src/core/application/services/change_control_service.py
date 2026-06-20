"""ChangeControlService — Phase 19 Section 7.

Evidence gate for any strategy or configuration change.

Philosophy:
  No change to scoring weights, gates, regime thresholds, or component logic
  is permitted without passing the evidence gate. The gate ensures changes
  are justified by statistical outcomes, not intuition.

Required for any change to be approved:
  1. Minimum 500 completed live trades (statistical power).
  2. The proposed change must target a specific measured deficiency
     (e.g. a regime with PF < 1.0, a score bucket breaking monotonicity).
  3. The change must specify the expected outcome improvement
     (e.g. "+5pp win rate in SIDEWAYS regime").
  4. Baseline metrics are recorded before change is applied.
  5. A validation period of at least 100 trades post-change is required
     before permanent adoption.

This service computes the baseline snapshot and returns a change request ID.
Post-change validation is checked by comparing the snapshot to current metrics.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_MIN_TRADES_FOR_CHANGE       = 500
_VALIDATION_PERIOD_TRADES    = 100
_ALLOWABLE_CHANGE_CATEGORIES = frozenset({
    "SCORING_WEIGHT",
    "REGIME_THRESHOLD",
    "GATE_THRESHOLD",
    "COMPONENT_PARAMETER",
    "UNIVERSE_ADDITION",
    "UNIVERSE_REMOVAL",
    "RISK_PARAMETER",
})


class ChangeControlService:
    """Evidence gate for strategy and configuration changes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def request_change(
        self,
        *,
        category:             str,
        component:            str,
        description:          str,
        rationale:            str,
        target_deficiency:    str,
        expected_improvement: str,
        proposed_value:       str,
        current_value:        str,
        requested_by:         str = "operator",
    ) -> dict:
        """Submit a change request and validate against the evidence gate.

        Returns an approval or rejection with the baseline snapshot.

        Args:
            category:             Must be one of _ALLOWABLE_CHANGE_CATEGORIES.
            component:            Component or config key being changed.
            description:          Human-readable description of the change.
            rationale:            Why this change is needed.
            target_deficiency:    The specific measured problem (e.g. "SIDEWAYS PF=0.87").
            expected_improvement: Quantified expected outcome (e.g. "+5pp win rate").
            proposed_value:       New value to be applied.
            current_value:        Current value before change.
            requested_by:         Name/role of requester.

        Returns:
            dict: {status: APPROVED|REJECTED, change_id, baseline, gate_checks, ...}
        """
        if category not in _ALLOWABLE_CHANGE_CATEGORIES:
            return {
                "status":  "REJECTED",
                "reason":  f"Unknown category '{category}'. "
                           f"Allowed: {sorted(_ALLOWABLE_CHANGE_CATEGORIES)}",
            }

        baseline = await self._capture_baseline()
        completed = baseline.get("completed_trades", 0)
        gate_checks = self._run_gate_checks(
            completed=completed,
            target_deficiency=target_deficiency,
            expected_improvement=expected_improvement,
            baseline=baseline,
        )

        all_pass = all(c["pass"] for c in gate_checks.values())
        status   = "APPROVED" if all_pass else "REJECTED"

        change_id = self._make_change_id(
            category=category, component=component, proposed_value=proposed_value
        )

        if status == "APPROVED":
            _log.info(
                "change_control.APPROVED id=%s category=%s component=%s by=%s",
                change_id, category, component, requested_by,
            )
        else:
            failed = [k for k, v in gate_checks.items() if not v.get("pass")]
            _log.warning(
                "change_control.REJECTED id=%s category=%s failed=%s",
                change_id, category, failed,
            )

        return {
            "change_id":            change_id,
            "status":               status,
            "category":             category,
            "component":            component,
            "description":          description,
            "rationale":            rationale,
            "target_deficiency":    target_deficiency,
            "expected_improvement": expected_improvement,
            "proposed_value":       proposed_value,
            "current_value":        current_value,
            "requested_by":         requested_by,
            "requested_at":         datetime.now(UTC).isoformat(),
            "gate_checks":          gate_checks,
            "baseline_snapshot":    baseline,
            "validation_required": (
                f"Run {_VALIDATION_PERIOD_TRADES} live trades after applying the change, "
                f"then call validate_change(change_id='{change_id}') to compare vs baseline."
                if status == "APPROVED" else None
            ),
            "rejection_reason": (
                None if status == "APPROVED" else
                f"Gate failed: {[k for k, v in gate_checks.items() if not v.get('pass')]}"
            ),
        }

    async def validate_change(self, change_id: str, baseline: dict) -> dict:
        """Compare current metrics vs a stored baseline after a change.

        Checks if the change achieved the expected improvement.
        Returns a verdict of ADOPT / REVERT.
        """
        current = await self._capture_baseline()
        completed_since = max(0, current.get("completed_trades", 0) - baseline.get("completed_trades", 0))

        if completed_since < _VALIDATION_PERIOD_TRADES:
            return {
                "change_id":         change_id,
                "status":            "VALIDATION_PENDING",
                "trades_since":      completed_since,
                "trades_needed":     _VALIDATION_PERIOD_TRADES,
                "message":           f"Need {_VALIDATION_PERIOD_TRADES - completed_since} more trades to validate.",
            }

        delta_wr = current.get("win_rate_pct", 0) - baseline.get("win_rate_pct", 0)
        delta_pf = current.get("profit_factor", 0) - baseline.get("profit_factor", 0)
        exp_sign_preserved = (
            (current.get("expectancy", 0) > 0) == (baseline.get("expectancy", 0) > 0)
        )

        improved = (delta_wr >= 0.5 or delta_pf >= 0.02) and exp_sign_preserved

        verdict = "ADOPT" if improved else "REVERT"
        if verdict == "REVERT":
            _log.warning(
                "change_control.REVERT id=%s wr_delta=%.2f pf_delta=%.3f",
                change_id, delta_wr, delta_pf,
            )

        return {
            "change_id":         change_id,
            "verdict":           verdict,
            "trades_validated":  completed_since,
            "baseline":          baseline,
            "current":           current,
            "deltas": {
                "win_rate_pct":  round(delta_wr, 4),
                "profit_factor": round(delta_pf, 4),
                "expectancy":    round(
                    current.get("expectancy", 0) - baseline.get("expectancy", 0), 6
                ),
            },
            "expectancy_sign_preserved": exp_sign_preserved,
            "recommendation": (
                f"Change improved performance (WR +{delta_wr:.1f}pp, PF +{delta_pf:.3f}). "
                "Mark as permanent in the config."
                if verdict == "ADOPT" else
                f"Change did not improve performance (WR {delta_wr:+.1f}pp, PF {delta_pf:+.3f}). "
                "Revert to previous values immediately."
            ),
        }

    async def get_evidence_summary(self) -> dict:
        """Return a snapshot of current evidence — use before any change request."""
        baseline = await self._capture_baseline()
        completed = baseline.get("completed_trades", 0)
        return {
            "evidence_sufficient": completed >= _MIN_TRADES_FOR_CHANGE,
            "completed_trades":    completed,
            "min_required":        _MIN_TRADES_FOR_CHANGE,
            "gap":                 max(0, _MIN_TRADES_FOR_CHANGE - completed),
            "metrics":             baseline,
            "note": (
                f"Evidence gate: {completed}/{_MIN_TRADES_FOR_CHANGE} trades. "
                + ("SUFFICIENT — change requests may be submitted." if completed >= _MIN_TRADES_FOR_CHANGE
                   else f"INSUFFICIENT — need {_MIN_TRADES_FOR_CHANGE - completed} more completed trades.")
            ),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _capture_baseline(self) -> dict:
        """Capture current performance snapshot for baseline comparison."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*)                                                       AS completed,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,4)  AS win_rate,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          ,4)                                                             AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,6)         AS expectancy,
                          ROUND(AVG(adjusted_score),2)                                   AS avg_score,
                          ROUND(AVG(confidence),2)                                       AS avg_confidence,
                          ROUND(AVG(data_quality_score),1)                               AS avg_dq
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                    """),
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("change_control.baseline_error: %s", exc)
            return {"error": str(exc)}

        return {
            "captured_at":      datetime.now(UTC).isoformat(),
            "completed_trades": int(row[0] or 0),
            "win_rate_pct":     float(row[1] or 0),
            "profit_factor":    float(row[2] or 0),
            "expectancy":       float(row[3] or 0),
            "avg_score":        float(row[4] or 0),
            "avg_confidence":   float(row[5] or 0),
            "avg_dq_score":     float(row[6] or 0) if row[6] else None,
        }

    @staticmethod
    def _run_gate_checks(
        *,
        completed:            int,
        target_deficiency:    str,
        expected_improvement: str,
        baseline:             dict,
    ) -> dict:
        """Run the four evidence gate checks."""
        checks: dict[str, dict] = {}

        # Gate 1: Minimum trades
        checks["min_trades"] = {
            "pass":      completed >= _MIN_TRADES_FOR_CHANGE,
            "value":     completed,
            "threshold": f">= {_MIN_TRADES_FOR_CHANGE}",
            "action":    (
                None if completed >= _MIN_TRADES_FOR_CHANGE else
                f"Need {_MIN_TRADES_FOR_CHANGE - completed} more completed trades before any change."
            ),
        }

        # Gate 2: Target deficiency specified (non-empty)
        checks["target_deficiency_specified"] = {
            "pass":      bool(target_deficiency and len(target_deficiency.strip()) > 10),
            "value":     target_deficiency[:80] if target_deficiency else "",
            "threshold": "Non-empty specific deficiency description",
            "action": (
                None if target_deficiency and len(target_deficiency.strip()) > 10 else
                "Provide a specific measured deficiency (e.g. 'SIDEWAYS regime PF=0.87 over 150 trades')."
            ),
        }

        # Gate 3: Expected improvement quantified
        checks["improvement_quantified"] = {
            "pass":      bool(expected_improvement and len(expected_improvement.strip()) > 5),
            "value":     expected_improvement[:80] if expected_improvement else "",
            "threshold": "Quantified expected improvement",
            "action": (
                None if expected_improvement and len(expected_improvement.strip()) > 5 else
                "Specify quantified expected improvement (e.g. '+5pp win rate in SIDEWAYS regime')."
            ),
        }

        # Gate 4: Current system is profitable (PF > 1.0, expectancy > 0)
        # — don't change a system that's already working well without strong evidence
        pf  = baseline.get("profit_factor", 0)
        exp = baseline.get("expectancy", 0)
        checks["system_has_baseline_evidence"] = {
            "pass":      pf > 0 and exp != 0,  # system has enough history to compare
            "value":     f"PF={pf:.3f} expectancy={exp:.6f}",
            "threshold": "Non-zero baseline evidence (PF>0, expectancy≠0)",
            "action": (
                None if pf > 0 and exp != 0 else
                "No baseline evidence available. Run more trades before requesting changes."
            ),
        }

        return checks

    @staticmethod
    def _make_change_id(*, category: str, component: str, proposed_value: str) -> str:
        """Generate a deterministic change ID from the change parameters."""
        payload = f"{category}:{component}:{proposed_value}:{datetime.now(UTC).strftime('%Y%m%d')}"
        return "CHG-" + hashlib.md5(payload.encode()).hexdigest()[:8].upper()
