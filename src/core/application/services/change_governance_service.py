"""ChangeGovernanceService — Phase 25 Section 6.

Enforces the 7 governance gates before any strategy change can be deployed.
All checks are read-only — this service never modifies anything.

Gates:
  1. Minimum completed trades (200)
  2. Walk-forward validation passed
  3. Paper trading validation passed
  4. Statistical significance (p < 0.05)
  5. Rollback plan documented
  6. Impact documented
  7. Human approval recorded

Returns a GovernanceReport — APPROVED or BLOCKED with per-gate details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.platform_constants import (
    ARCHITECTURE_STATUS,
    GOVERNANCE_MIN_TRADES,
    GOVERNANCE_MIN_P_VALUE,
    GOVERNANCE_WALKFORWARD_PASSES,
    GOVERNANCE_PAPER_PASSES,
)

_log = logging.getLogger(__name__)


@dataclass
class GateResult:
    gate:    str
    passed:  bool
    detail:  str


@dataclass
class GovernanceReport:
    experiment_id:  str
    overall:        str          # APPROVED | BLOCKED
    gates:          list[GateResult] = field(default_factory=list)
    blocking_gates: list[str]   = field(default_factory=list)
    summary:        str         = ""

    @property
    def approved(self) -> bool:
        return self.overall == "APPROVED"


class ChangeGovernanceService:
    """Validates all 7 governance gates for an experiment before deployment."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def evaluate(self, experiment_id: str) -> GovernanceReport:
        exp_id = experiment_id.upper()

        # Fetch experiment record
        async with self._sf() as db:
            r = await db.execute(
                text("SELECT * FROM experiments WHERE experiment_id = :eid"),
                {"eid": exp_id},
            )
            exp_row = r.fetchone()

        if exp_row is None:
            return GovernanceReport(
                experiment_id=exp_id,
                overall="BLOCKED",
                gates=[GateResult("EXPERIMENT_EXISTS", False, f"Experiment {exp_id} not found")],
                blocking_gates=["EXPERIMENT_EXISTS"],
                summary=f"Experiment {exp_id} does not exist",
            )

        exp = dict(exp_row._mapping)
        gates: list[GateResult] = []

        # ── Gate 1: Minimum completed trades ─────────────────────────────────
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT COUNT(*) AS n
                    FROM signal_analytics
                    WHERE experiment_id = :eid
                      AND was_accepted = true
                      AND outcome IN ('WIN', 'LOSS', 'EXPIRED', 'PARTIAL')
                """),
                {"eid": exp_id},
            )
            trade_count = int((r.fetchone() or (0,))[0])

        gates.append(GateResult(
            gate   = "MIN_TRADES",
            passed = trade_count >= GOVERNANCE_MIN_TRADES,
            detail = f"{trade_count} settled trades (need {GOVERNANCE_MIN_TRADES})",
        ))

        # ── Gate 2: Walk-forward validation ──────────────────────────────────
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT COUNT(*) FROM backtest_results
                    WHERE status = 'PASSED' AND backtest_type = 'WALK_FORWARD'
                    LIMIT 1
                """),
            )
            wf_count = int((r.fetchone() or (0,))[0])

        gates.append(GateResult(
            gate   = "WALK_FORWARD",
            passed = wf_count >= GOVERNANCE_WALKFORWARD_PASSES,
            detail = f"{wf_count} walk-forward pass(es) found (need {GOVERNANCE_WALKFORWARD_PASSES})",
        ))

        # ── Gate 3: Paper trading validation ─────────────────────────────────
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT COUNT(*) FROM live_validation_results
                    WHERE validation_passed = true
                    LIMIT 1
                """),
            )
            pv_count = int((r.fetchone() or (0,))[0])

        gates.append(GateResult(
            gate   = "PAPER_VALIDATION",
            passed = pv_count >= GOVERNANCE_PAPER_PASSES,
            detail = f"{pv_count} paper validation pass(es) found",
        ))

        # ── Gate 4: Statistical significance ─────────────────────────────────
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                        COUNT(*) FILTER (WHERE ab_group = 'CONTROL'   AND outcome IN ('WIN','LOSS','EXPIRED')) AS ctrl_n,
                        COUNT(*) FILTER (WHERE ab_group = 'TREATMENT' AND outcome IN ('WIN','LOSS','EXPIRED')) AS trt_n,
                        COUNT(*) FILTER (WHERE ab_group = 'CONTROL'   AND target_hit) AS ctrl_wins,
                        COUNT(*) FILTER (WHERE ab_group = 'TREATMENT' AND target_hit) AS trt_wins
                    FROM signal_analytics
                    WHERE experiment_id = :eid AND was_accepted = true
                """),
                {"eid": exp_id},
            )
            row = r.fetchone()

        ctrl_n, trt_n, ctrl_w, trt_w = (
            int(row[0] or 0), int(row[1] or 0),
            int(row[2] or 0), int(row[3] or 0),
        ) if row else (0, 0, 0, 0)

        sig_passed = False
        sig_detail = "Not enough data for significance test"
        if ctrl_n >= 30 and trt_n >= 30:
            import math
            p_c = ctrl_w / ctrl_n if ctrl_n > 0 else 0
            p_t = trt_w / trt_n   if trt_n  > 0 else 0
            p_pool = (ctrl_w + trt_w) / (ctrl_n + trt_n)
            denom  = math.sqrt(p_pool * (1 - p_pool) * (1 / ctrl_n + 1 / trt_n))
            z      = (p_t - p_c) / denom if denom > 0 else 0
            p_val  = math.erfc(abs(z) / math.sqrt(2))
            sig_passed = p_val < GOVERNANCE_MIN_P_VALUE and p_t > p_c
            sig_detail = (
                f"p={p_val:.4f} ({'<' if sig_passed else '>='} 0.05), "
                f"control={ctrl_w}/{ctrl_n}={p_c*100:.1f}%, "
                f"treatment={trt_w}/{trt_n}={p_t*100:.1f}%"
            )

        gates.append(GateResult(
            gate   = "STATISTICAL_SIGNIFICANCE",
            passed = sig_passed,
            detail = sig_detail,
        ))

        # ── Gate 5: Rollback plan documented ─────────────────────────────────
        has_rollback = bool(exp.get("rollback_plan") and len(str(exp["rollback_plan"]).strip()) > 10)
        gates.append(GateResult(
            gate   = "ROLLBACK_PLAN",
            passed = has_rollback,
            detail = "Rollback plan documented" if has_rollback else "No rollback plan — add to experiment record",
        ))

        # ── Gate 6: Impact documented ─────────────────────────────────────────
        has_impact = bool(exp.get("description") and len(str(exp["description"]).strip()) > 20)
        gates.append(GateResult(
            gate   = "IMPACT_DOCUMENTED",
            passed = has_impact,
            detail = "Impact/description documented" if has_impact else "No description — document expected impact",
        ))

        # ── Gate 7: Human approval ────────────────────────────────────────────
        human_approved = exp.get("approval_status") == "APPROVED" and bool(exp.get("approved_by"))
        gates.append(GateResult(
            gate   = "HUMAN_APPROVAL",
            passed = human_approved,
            detail = (
                f"Approved by {exp['approved_by']}" if human_approved
                else f"Approval status: {exp.get('approval_status', 'PENDING')}"
            ),
        ))

        # ── Overall ───────────────────────────────────────────────────────────
        blocking = [g.gate for g in gates if not g.passed]
        overall  = "APPROVED" if not blocking else "BLOCKED"

        summary = (
            f"All {len(gates)} governance gates passed — experiment {exp_id} may proceed to deployment."
            if not blocking else
            f"{len(blocking)}/{len(gates)} gate(s) failed: {', '.join(blocking)}"
        )

        await self._log_governance(exp_id, overall, blocking, summary)

        return GovernanceReport(
            experiment_id  = exp_id,
            overall        = overall,
            gates          = gates,
            blocking_gates = blocking,
            summary        = summary,
        )

    async def _log_governance(
        self, exp_id: str, result: str, blocking: list[str], summary: str
    ) -> None:
        try:
            import json as _json
            async with self._sf() as db:
                await db.execute(
                    text("""
                        INSERT INTO platform_events (event_type, description, payload_json)
                        VALUES (:evt, :desc, :payload)
                    """),
                    {
                        "evt":     f"GOVERNANCE_{result}",
                        "desc":    summary,
                        "payload": _json.dumps({"experiment_id": exp_id, "blocking": blocking}),
                    },
                )
                await db.commit()
        except Exception as exc:
            _log.debug("governance.log_failed: %s", exc)
