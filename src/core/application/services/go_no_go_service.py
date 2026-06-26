"""GoNoGoService — Phase 22 §10.

Evaluates 4 deployment gates and returns a plain-English recommendation:
  GATE_1 — paper trading      (readiness ≥ 40)
  GATE_2 — 1-lot live trading (readiness ≥ 65, n ≥ 50, profit_factor ≥ 1.1, win_rate ≥ 45%)
  GATE_3 — 2-lot scaling      (readiness ≥ 75, n ≥ 200, profit_factor ≥ 1.3, win_rate ≥ 50%)
  GATE_4 — full scaling       (readiness ≥ 85, n ≥ 500, profit_factor ≥ 1.5, win_rate ≥ 55%)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Gate definitions: (name, label, readiness_min, n_min, pf_min, wr_min_pct)
_GATES = [
    ("GATE_1", "Paper Trading",       40, 0,   0.0,  0.0),
    ("GATE_2", "1-Lot Live Trading",  65, 50,  1.1, 45.0),
    ("GATE_3", "2-Lot Scaling",       75, 200, 1.3, 50.0),
    ("GATE_4", "Full Scaling",        85, 500, 1.5, 55.0),
]


def _gate_result(
    name: str,
    label: str,
    passed: bool,
    criteria: list[dict[str, Any]],
    explanation: str,
) -> dict[str, Any]:
    return {
        "gate":        name,
        "label":       label,
        "passed":      passed,
        "criteria":    criteria,
        "explanation": explanation,
    }


class GoNoGoService:
    """Evaluates deployment readiness gates with human-readable explanations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_go_no_go(self, readiness_score: int | None = None) -> dict[str, Any]:
        """Evaluate all 4 gates. Accepts optional pre-computed readiness_score."""
        trade_stats = await self._fetch_trade_stats()
        gates        = self._evaluate_gates(readiness_score, trade_stats)
        highest_gate = self._highest_passed_gate(gates)

        return {
            "current_gate":   highest_gate,
            "recommendation": self._top_recommendation(highest_gate, gates, trade_stats),
            "gates":          gates,
            "trade_stats":    trade_stats,
            "evaluated_at":   datetime.now(UTC).isoformat(),
        }

    # ── Data fetch ────────────────────────────────────────────────────────────

    async def _fetch_trade_stats(self) -> dict[str, Any]:
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*) AS n,
                        SUM(CASE WHEN target_hit THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN stop_hit THEN 1 ELSE 0 END) AS losses,
                        ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_rate_pct,
                        ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END), 0)
                        , 3) AS profit_factor
                    FROM signal_analytics
                    WHERE was_accepted = true AND outcome IS NOT NULL
                """))
                row = r.fetchone()
        except Exception as exc:
            _log.warning("go_no_go.fetch_trade_stats failed: %s", exc)
            return {"n": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0, "profit_factor": None}

        return {
            "n":              int(row[0] or 0),
            "wins":           int(row[1] or 0),
            "losses":         int(row[2] or 0),
            "win_rate_pct":   float(row[3] or 0),
            "profit_factor":  float(row[4]) if row[4] else None,
        }

    # ── Gate evaluation ───────────────────────────────────────────────────────

    def _evaluate_gates(
        self,
        readiness_score: int | None,
        stats: dict[str, Any],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        n   = stats["n"]
        wr  = stats["win_rate_pct"]
        pf  = stats["profit_factor"] or 0.0
        rs  = readiness_score if readiness_score is not None else -1

        for gate_name, label, rs_min, n_min, pf_min, wr_min in _GATES:
            criteria: list[dict[str, Any]] = []
            all_pass = True

            # Readiness score criterion
            c_rs = {
                "criterion":  "Deployment readiness score",
                "required":   f"≥ {rs_min}",
                "actual":     rs if rs >= 0 else "not computed",
                "passed":     rs >= rs_min,
            }
            criteria.append(c_rs)
            if not c_rs["passed"]:
                all_pass = False

            # Trade count criterion (skip for GATE_1)
            if n_min > 0:
                c_n = {
                    "criterion": "Completed trades",
                    "required":  f"≥ {n_min}",
                    "actual":    n,
                    "passed":    n >= n_min,
                }
                criteria.append(c_n)
                if not c_n["passed"]:
                    all_pass = False

            # Profit factor criterion
            if pf_min > 0:
                c_pf = {
                    "criterion": "Profit factor",
                    "required":  f"≥ {pf_min:.1f}",
                    "actual":    round(pf, 3) if pf else "no data",
                    "passed":    pf >= pf_min if pf else False,
                }
                criteria.append(c_pf)
                if not c_pf["passed"]:
                    all_pass = False

            # Win rate criterion
            if wr_min > 0:
                c_wr = {
                    "criterion": "Win rate",
                    "required":  f"≥ {wr_min:.0f}%",
                    "actual":    f"{round(wr, 1)}%",
                    "passed":    wr >= wr_min if n >= 10 else False,
                }
                criteria.append(c_wr)
                if not c_wr["passed"]:
                    all_pass = False

            explanation = self._explain(gate_name, label, all_pass, criteria, stats, rs)
            results.append(_gate_result(gate_name, label, all_pass, criteria, explanation))

        return results

    def _explain(
        self,
        gate_name: str,
        label: str,
        passed: bool,
        criteria: list[dict[str, Any]],
        stats: dict[str, Any],
        rs: int,
    ) -> str:
        if passed:
            return (
                f"All criteria met for {label}. "
                f"System has {stats['n']} completed trades, "
                f"{stats['win_rate_pct']:.1f}% win rate, "
                f"profit factor {stats['profit_factor']:.2f if stats['profit_factor'] else 'N/A'}, "
                f"readiness score {rs}."
            )

        failures = [c for c in criteria if not c["passed"]]
        parts: list[str] = []
        for f in failures:
            if "readiness" in f["criterion"].lower():
                parts.append(
                    f"deployment readiness is {f['actual']} (need {f['required']}) — "
                    "run the readiness check for category-level breakdown"
                )
            elif "trades" in f["criterion"].lower():
                needed = int(f["required"].lstrip("≥ "))
                remaining = needed - stats["n"]
                parts.append(
                    f"only {stats['n']} completed trades ({remaining} more needed for {f['required']})"
                )
            elif "profit factor" in f["criterion"].lower():
                parts.append(
                    f"profit factor is {f['actual']} (need {f['required']}) — "
                    "strategy edge not yet confirmed by closed trades"
                )
            elif "win rate" in f["criterion"].lower():
                parts.append(
                    f"win rate is {stats['win_rate_pct']:.1f}% (need {f['required']}) — "
                    "more trades needed or strategy filtering should be tightened"
                )

        return f"{label} gate NOT MET: " + "; ".join(parts) + "."

    def _highest_passed_gate(self, gates: list[dict[str, Any]]) -> str | None:
        passed = [g["gate"] for g in gates if g["passed"]]
        return passed[-1] if passed else None

    def _top_recommendation(
        self,
        highest_gate: str | None,
        gates: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> str:
        if highest_gate == "GATE_4":
            return (
                "System is READY FOR FULL SCALING. All four deployment gates have been cleared. "
                "Statistical evidence supports deploying at full position sizing."
            )
        if highest_gate == "GATE_3":
            return (
                "System qualifies for 2-LOT TRADING. Gate 4 (Full Scaling) requires "
                f"≥500 completed trades (currently {stats['n']}), readiness ≥85, "
                "win rate ≥55%, and profit factor ≥1.5. Keep accumulating evidence."
            )
        if highest_gate == "GATE_2":
            return (
                "System qualifies for 1-LOT LIVE TRADING. Gate 3 requires "
                f"≥200 completed trades (currently {stats['n']}), readiness ≥75, "
                "win rate ≥50%, and profit factor ≥1.3."
            )
        if highest_gate == "GATE_1":
            return (
                "System is cleared for PAPER TRADING only. Gate 2 (1-lot live) requires "
                f"≥50 completed trades (currently {stats['n']}), readiness ≥65, "
                "win rate ≥45%, and profit factor ≥1.1. Use paper mode to accumulate evidence."
            )
        # Nothing passed
        failed_rs = next(
            (g for g in gates if g["gate"] == "GATE_1" and not g["passed"]), None
        )
        if failed_rs:
            rs_crit = next((c for c in failed_rs["criteria"] if "readiness" in c["criterion"].lower()), None)
            if rs_crit:
                return (
                    f"NO GATE CLEARED. Deployment readiness score is {rs_crit['actual']} "
                    f"(minimum {rs_crit['required']} even for paper trading). "
                    "Fix infrastructure and data quality issues first — see readiness report."
                )
        return (
            "NO GATE CLEARED. System does not meet minimum criteria for any deployment mode. "
            "Check the readiness report for infrastructure and strategy validation gaps."
        )
