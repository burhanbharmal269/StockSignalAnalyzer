"""ValidationReportService — Phase 22 §11.

Aggregates all Phase 22 validation data into a single weekly summary report.
Takes all Phase 22 services as dependencies and composes their outputs.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from core.application.services.bug_detection_service import BugDetectionService
from core.application.services.deployment_readiness_service import DeploymentReadinessService
from core.application.services.go_no_go_service import GoNoGoService
from core.application.services.production_drift_service import ProductionDriftService
from core.application.services.statistical_validation_service import StatisticalValidationService

_log = logging.getLogger(__name__)


class ValidationReportService:
    """Composes all Phase 22 services into a single weekly validation report."""

    def __init__(
        self,
        deployment_readiness_service: DeploymentReadinessService,
        statistical_validation_service: StatisticalValidationService,
        bug_detection_service: BugDetectionService,
        production_drift_service: ProductionDriftService,
        go_no_go_service: GoNoGoService,
    ) -> None:
        self._readiness   = deployment_readiness_service
        self._stats       = statistical_validation_service
        self._bugs        = bug_detection_service
        self._drift       = production_drift_service
        self._go_no_go    = go_no_go_service

    async def get_full_report(self) -> dict[str, Any]:
        """Return a complete validation report — suitable for weekly review."""
        # Fetch all sections concurrently where possible
        readiness_data = await self._readiness.get_readiness_score()
        readiness_score = readiness_data.get("total_score")

        # These can run independently
        try:
            milestones_data = await self._stats.get_validation_milestones()
        except Exception as exc:
            _log.warning("validation_report.milestones failed: %s", exc)
            milestones_data = {"error": str(exc)}

        try:
            ci_data = await self._stats.get_confidence_intervals(lookback_days=90)
        except Exception as exc:
            _log.warning("validation_report.ci failed: %s", exc)
            ci_data = {"error": str(exc)}

        try:
            overlay_val = await self._stats.get_overlay_validation(lookback_days=60)
        except Exception as exc:
            _log.warning("validation_report.overlay_validation failed: %s", exc)
            overlay_val = {"error": str(exc)}

        try:
            component_val = await self._stats.get_component_validation(lookback_days=60)
        except Exception as exc:
            _log.warning("validation_report.component_validation failed: %s", exc)
            component_val = {"error": str(exc)}

        try:
            bugs_data = await self._bugs.run_all_checks()
        except Exception as exc:
            _log.warning("validation_report.bugs failed: %s", exc)
            bugs_data = {"error": str(exc)}

        try:
            drift_data = await self._drift.get_drift_report()
        except Exception as exc:
            _log.warning("validation_report.drift failed: %s", exc)
            drift_data = {"error": str(exc)}

        try:
            go_no_go_data = await self._go_no_go.get_go_no_go(readiness_score=readiness_score)
        except Exception as exc:
            _log.warning("validation_report.go_no_go failed: %s", exc)
            go_no_go_data = {"error": str(exc)}

        # Build health summary
        health = self._build_health_summary(readiness_data, bugs_data, drift_data, go_no_go_data)

        return {
            "report_type":     "FULL_VALIDATION",
            "generated_at":    datetime.now(UTC).isoformat(),
            "health_summary":  health,
            "deployment_readiness": readiness_data,
            "go_no_go":             go_no_go_data,
            "milestones":           milestones_data,
            "confidence_intervals": ci_data,
            "overlay_validation":   overlay_val,
            "component_validation": component_val,
            "bug_detection":        bugs_data,
            "production_drift":     drift_data,
        }

    async def get_summary_report(self) -> dict[str, Any]:
        """Lightweight report — readiness + go/no-go + bug detection only."""
        try:
            readiness_data = await self._readiness.get_readiness_score()
            readiness_score = readiness_data.get("total_score")
        except Exception as exc:
            _log.warning("validation_report.summary.readiness failed: %s", exc)
            readiness_data  = {"error": str(exc)}
            readiness_score = None

        try:
            bugs_data = await self._bugs.run_all_checks(sample_n=50)
        except Exception as exc:
            _log.warning("validation_report.summary.bugs failed: %s", exc)
            bugs_data = {"error": str(exc)}

        try:
            go_no_go_data = await self._go_no_go.get_go_no_go(readiness_score=readiness_score)
        except Exception as exc:
            _log.warning("validation_report.summary.go_no_go failed: %s", exc)
            go_no_go_data = {"error": str(exc)}

        health = self._build_health_summary(readiness_data, bugs_data, {}, go_no_go_data)

        return {
            "report_type":          "SUMMARY",
            "generated_at":         datetime.now(UTC).isoformat(),
            "health_summary":       health,
            "deployment_readiness": readiness_data,
            "go_no_go":             go_no_go_data,
            "bug_detection":        bugs_data,
        }

    # ── Health summary ────────────────────────────────────────────────────────

    def _build_health_summary(
        self,
        readiness: dict[str, Any],
        bugs: dict[str, Any],
        drift: dict[str, Any],
        go_no_go: dict[str, Any],
    ) -> dict[str, Any]:
        issues: list[str] = []
        warnings: list[str] = []

        # Readiness tier
        tier  = readiness.get("tier", "UNKNOWN")
        score = readiness.get("total_score", 0)
        if tier in ("NOT_READY", "UNKNOWN"):
            issues.append(f"Deployment readiness is {tier} (score {score}/100)")
        elif tier == "LIMITED":
            warnings.append(f"Deployment readiness is LIMITED (score {score}/100)")

        # Bug detection — HIGH severity
        if "summary" in bugs:
            high_n = bugs["summary"].get("high_severity", 0)
            total_bugs = bugs["summary"].get("detected", 0)
            if high_n > 0:
                issues.append(f"{high_n} HIGH-severity silent failure(s) detected")
            elif total_bugs > 0:
                warnings.append(f"{total_bugs} silent failure pattern(s) detected")

        # Production drift
        if "summary" in drift:
            drifted = drift["summary"].get("significant_drifts", 0)
            if drifted > 0:
                warnings.append(f"{drifted} statistically significant drift(s) vs prior 30-day baseline")

        # Go/No-Go
        current_gate = go_no_go.get("current_gate")
        if current_gate is None:
            issues.append("No deployment gate has been cleared")
        elif current_gate == "GATE_1":
            warnings.append("Only Gate 1 (paper trading) cleared — not ready for live capital")

        overall = "HEALTHY" if not issues and not warnings else ("NEEDS_ATTENTION" if not issues else "CRITICAL")

        return {
            "overall":    overall,
            "tier":       tier,
            "score":      score,
            "gate":       current_gate,
            "issues":     issues,
            "warnings":   warnings,
            "recommendation": go_no_go.get("recommendation", ""),
        }
