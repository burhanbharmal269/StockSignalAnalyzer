"""ExperimentService — Phase 25 Section 2+3+4.

Manages A/B experiments:
  - CRUD for experiment registry
  - Signal group assignment (CONTROL | TREATMENT) for active experiments
  - Aggregates per-group outcome stats from signal_analytics
  - Calls StatisticalValidationEngine to produce validation snapshots
  - Logs platform governance events
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.platform_constants import DEFAULT_TREATMENT_ALLOCATION_PCT
from core.application.services.statistical_validation_engine import (
    GroupStats,
    StatisticalValidationEngine,
    ValidationResult,
)

_log = logging.getLogger(__name__)

# Valid experiment statuses
_STATUSES      = {"DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "REJECTED"}
_ACTIVE_STATUSES = {"ACTIVE"}


class ExperimentService:
    """Manages the lifecycle of A/B experiments and their statistical analysis."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf  = session_factory
        self._sve = StatisticalValidationEngine()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def create_experiment(self, payload: dict) -> dict:
        """Create a new experiment in DRAFT status."""
        required = {"experiment_id", "title", "hypothesis", "author"}
        missing = required - set(payload.keys())
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        exp_id = payload["experiment_id"].upper()
        async with self._sf() as db:
            await db.execute(
                text("""
                    INSERT INTO experiments (
                        experiment_id, title, description, hypothesis, author,
                        status, baseline_strategy_version, candidate_strategy_version,
                        minimum_sample_size, preferred_sample_size,
                        primary_kpi, secondary_kpi, expected_improvement_pct,
                        failure_criteria, success_threshold, max_drawdown_allowed,
                        rollback_plan, treatment_allocation_pct, notes
                    ) VALUES (
                        :exp_id, :title, :description, :hypothesis, :author,
                        'DRAFT', :baseline_ver, :candidate_ver,
                        :min_sample, :pref_sample,
                        :primary_kpi, :secondary_kpi, :expected_improvement,
                        :failure_criteria, :success_threshold, :max_dd,
                        :rollback, :treatment_pct, :notes
                    )
                """),
                {
                    "exp_id":             exp_id,
                    "title":              payload["title"],
                    "description":        payload.get("description"),
                    "hypothesis":         payload["hypothesis"],
                    "author":             payload["author"],
                    "baseline_ver":       payload.get("baseline_strategy_version"),
                    "candidate_ver":      payload.get("candidate_strategy_version"),
                    "min_sample":         payload.get("minimum_sample_size", 50),
                    "pref_sample":        payload.get("preferred_sample_size", 200),
                    "primary_kpi":        payload.get("primary_kpi", "win_rate"),
                    "secondary_kpi":      payload.get("secondary_kpi"),
                    "expected_improvement": payload.get("expected_improvement_pct"),
                    "failure_criteria":   payload.get("failure_criteria"),
                    "success_threshold":  payload.get("success_threshold"),
                    "max_dd":             payload.get("max_drawdown_allowed"),
                    "rollback":           payload.get("rollback_plan"),
                    "treatment_pct":      payload.get("treatment_allocation_pct", DEFAULT_TREATMENT_ALLOCATION_PCT),
                    "notes":              payload.get("notes"),
                },
            )
            await db.commit()

        await self._log_event("EXPERIMENT_CREATED", payload["author"],
                              f"Created experiment {exp_id}: {payload['title']}", {"experiment_id": exp_id})
        _log.info("experiment_service.created experiment_id=%s", exp_id)
        return await self.get_experiment(exp_id)  # type: ignore[return-value]

    async def get_experiment(self, experiment_id: str) -> dict | None:
        async with self._sf() as db:
            r = await db.execute(
                text("SELECT * FROM experiments WHERE experiment_id = :eid"),
                {"eid": experiment_id.upper()},
            )
            row = r.fetchone()
        return dict(row._mapping) if row else None

    async def list_experiments(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM experiments"
        params: dict = {}
        if status:
            sql += " WHERE status = :status"
            params["status"] = status.upper()
        sql += " ORDER BY created_at DESC"
        async with self._sf() as db:
            r = await db.execute(text(sql), params)
            return [dict(row._mapping) for row in r.fetchall()]

    async def update_status(
        self, experiment_id: str, new_status: str, actor: str, notes: str | None = None
    ) -> dict | None:
        exp_id = experiment_id.upper()
        new_status = new_status.upper()
        if new_status not in _STATUSES:
            raise ValueError(f"Invalid status {new_status}")

        now = datetime.now(UTC)
        extra_fields = ""
        extra_params: dict = {}
        if new_status == "ACTIVE":
            extra_fields = ", started_at = :started_at"
            extra_params["started_at"] = now
        elif new_status in ("COMPLETED", "REJECTED"):
            extra_fields = ", completed_at = :completed_at"
            extra_params["completed_at"] = now

        async with self._sf() as db:
            await db.execute(
                text(f"UPDATE experiments SET status = :status{extra_fields} WHERE experiment_id = :eid"),
                {"status": new_status, "eid": exp_id, **extra_params},
            )
            if notes:
                await db.execute(
                    text("UPDATE experiments SET notes = COALESCE(notes || E'\\n', '') || :notes WHERE experiment_id = :eid"),
                    {"notes": notes, "eid": exp_id},
                )
            await db.commit()

        await self._log_event(
            f"EXPERIMENT_{new_status}", actor,
            f"Experiment {exp_id} → {new_status}", {"experiment_id": exp_id}
        )
        return await self.get_experiment(exp_id)

    async def approve_experiment(self, experiment_id: str, approved_by: str) -> dict | None:
        exp_id = experiment_id.upper()
        async with self._sf() as db:
            await db.execute(
                text("""
                    UPDATE experiments SET
                        approval_status = 'APPROVED',
                        approved_by = :actor,
                        approved_at = :now
                    WHERE experiment_id = :eid
                """),
                {"actor": approved_by, "now": datetime.now(UTC), "eid": exp_id},
            )
            await db.commit()
        await self._log_event("EXPERIMENT_APPROVED", approved_by, f"Approved {exp_id}", {"experiment_id": exp_id})
        return await self.get_experiment(exp_id)

    async def set_conclusion(self, experiment_id: str, conclusion: str, actor: str) -> None:
        async with self._sf() as db:
            await db.execute(
                text("UPDATE experiments SET conclusion = :c WHERE experiment_id = :eid"),
                {"c": conclusion, "eid": experiment_id.upper()},
            )
            await db.commit()

    # ── A/B signal routing ────────────────────────────────────────────────────

    async def assign_signal(
        self, signal_id: UUID, analytics_id: int | None = None
    ) -> tuple[str, str]:
        """Assign a signal to the active experiment's control/treatment group.

        Returns (experiment_id, group_type) — ("", "NONE") if no active experiment.
        Analytics-only: never changes what signal is generated, only records assignment.
        """
        active = await self._get_active_experiment()
        if active is None:
            return "", "NONE"

        alloc_pct = float(active.get("treatment_allocation_pct") or DEFAULT_TREATMENT_ALLOCATION_PCT)
        group = "TREATMENT" if random.random() * 100 < alloc_pct else "CONTROL"
        exp_id = active["experiment_id"]

        async with self._sf() as db:
            await db.execute(
                text("""
                    INSERT INTO experiment_signals (experiment_id, signal_id, group_type, analytics_id)
                    VALUES (:eid, :sid, :group, :aid)
                """),
                {"eid": exp_id, "sid": str(signal_id), "group": group, "aid": analytics_id},
            )
            await db.commit()

        return exp_id, group

    async def _get_active_experiment(self) -> dict | None:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT * FROM experiments
                    WHERE status = 'ACTIVE' AND approval_status = 'APPROVED'
                    ORDER BY started_at DESC
                    LIMIT 1
                """),
            )
            row = r.fetchone()
        return dict(row._mapping) if row else None

    # ── Statistical analysis ──────────────────────────────────────────────────

    async def compute_validation(self, experiment_id: str) -> dict:
        """Fetch per-group stats from signal_analytics and run statistical tests."""
        exp = await self.get_experiment(experiment_id)
        if exp is None:
            raise ValueError(f"Experiment {experiment_id} not found")

        exp_id = experiment_id.upper()
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                        sa.ab_group,
                        COUNT(*)                                        AS trades,
                        COUNT(*) FILTER (WHERE sa.target_hit)           AS wins,
                        COUNT(*) FILTER (WHERE sa.stop_hit)             AS losses,
                        COUNT(*) FILTER (WHERE sa.outcome = 'EXPIRED')  AS expired,
                        ROUND(AVG(sa.pnl_pct)::numeric, 4)             AS avg_pnl,
                        ROUND(AVG(sa.mfe_pct)::numeric, 4)             AS avg_mfe,
                        ROUND(AVG(sa.mae_pct)::numeric, 4)             AS avg_mae,
                        ROUND(AVG(sa.time_to_target_minutes)::numeric, 1) AS avg_hold_min,
                        ROUND(AVG(sa.target_realism_pct)::numeric, 1)  AS avg_target_realism,
                        ROUND(AVG(sa.option_efficiency_score)::numeric, 4) AS avg_efficiency,
                        SUM(CASE WHEN sa.pnl_pct > 0 THEN sa.pnl_pct ELSE 0 END) AS gross_profit,
                        SUM(CASE WHEN sa.pnl_pct < 0 THEN ABS(sa.pnl_pct) ELSE 0 END) AS gross_loss
                    FROM signal_analytics sa
                    WHERE sa.experiment_id = :eid
                      AND sa.was_accepted = true
                      AND sa.outcome IN ('WIN', 'LOSS', 'EXPIRED', 'PARTIAL')
                      AND sa.ab_group IN ('CONTROL', 'TREATMENT')
                    GROUP BY sa.ab_group
                """),
                {"eid": exp_id},
            )
            rows = {row._mapping["ab_group"]: dict(row._mapping) for row in r.fetchall()}

        ctrl_row = rows.get("CONTROL",   {})
        trt_row  = rows.get("TREATMENT", {})

        def _mk_group(row: dict) -> GroupStats:
            n    = int(row.get("trades") or 0)
            wins = int(row.get("wins")   or 0)
            gp   = float(row.get("gross_profit") or 0)
            gl   = float(row.get("gross_loss")   or 0)
            return GroupStats(
                trades      = n,
                wins        = wins,
                total_pnl   = float(row.get("avg_pnl") or 0) * n,
                avg_mfe     = float(row.get("avg_mfe") or 0) if row.get("avg_mfe") is not None else None,
                avg_mae     = float(row.get("avg_mae") or 0) if row.get("avg_mae") is not None else None,
                avg_holding = float(row.get("avg_hold_min") or 0) if row.get("avg_hold_min") is not None else None,
            )

        ctrl_stats = _mk_group(ctrl_row)
        trt_stats  = _mk_group(trt_row)
        min_sample = int(exp.get("minimum_sample_size") or 50)

        result: ValidationResult = self._sve.validate(ctrl_stats, trt_stats, min_sample)

        def _pf(gp: float, gl: float) -> float | None:
            return round(gp / gl, 3) if gl > 0 else None

        return {
            "experiment_id":    exp_id,
            "experiment_title": exp.get("title"),
            "status":           exp.get("status"),
            "minimum_sample_size": min_sample,
            "control": {
                **ctrl_row,
                "profit_factor": _pf(float(ctrl_row.get("gross_profit") or 0), float(ctrl_row.get("gross_loss") or 0)),
            },
            "treatment": {
                **trt_row,
                "profit_factor": _pf(float(trt_row.get("gross_profit") or 0), float(trt_row.get("gross_loss") or 0)),
            },
            "validation": {
                "control_win_rate":        result.control_win_rate,
                "treatment_win_rate":      result.treatment_win_rate,
                "control_wilson":          asdict(result.control_wilson),
                "treatment_wilson":        asdict(result.treatment_wilson),
                "improvement_pct":         result.improvement_pct,
                "z_score":                 result.z_score,
                "p_value":                 result.p_value,
                "is_significant":          result.is_significant,
                "confidence_level":        result.confidence_level,
                "recommendation":          result.recommendation,
                "recommendation_reason":   result.recommendation_reason,
                "risk_assessment":         result.risk_assessment,
            },
        }

    # ── Governance log ────────────────────────────────────────────────────────

    async def _log_event(
        self, event_type: str, actor: str | None, description: str, payload: dict | None = None
    ) -> None:
        try:
            async with self._sf() as db:
                await db.execute(
                    text("""
                        INSERT INTO platform_events (event_type, actor, description, payload_json)
                        VALUES (:evt, :actor, :desc, :payload)
                    """),
                    {
                        "evt":     event_type,
                        "actor":   actor,
                        "desc":    description,
                        "payload": json.dumps(payload) if payload else None,
                    },
                )
                await db.commit()
        except Exception as exc:
            _log.debug("experiment_service.log_event_failed: %s", exc)

    async def list_platform_events(self, limit: int = 100) -> list[dict]:
        async with self._sf() as db:
            r = await db.execute(
                text("SELECT * FROM platform_events ORDER BY created_at DESC LIMIT :lim"),
                {"lim": limit},
            )
            return [dict(row._mapping) for row in r.fetchall()]
