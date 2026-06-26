"""BugDetectionService — Phase 22 §8.

Detects 9 silent-failure patterns in the pipeline:
  1. confidence_identical    — all recent signals have same confidence value
  2. overlay_never_applied   — a registered overlay has 0 applied in last N signals
  3. event_calendar_empty    — event_overlay never fires even during known event windows
  4. mtf_always_neutral      — MTF regime is always "NEUTRAL"
  5. grade_always_d          — execution_grade is always "D" in last N signals
  6. data_quality_never_varies — data_quality_score is constant (no variation)
  7. acceptance_rate_too_low  — fewer than 5% of signals accepted
  8. scanner_idle             — no signals generated in last configurable window
  9. position_size_always_zero — all accepted signals have 0 lots / 0 quantity
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_OVERLAY_NAMES = [
    "market_context",
    "event_overlay",
    "regime_stability",
    "portfolio_heat",
    "portfolio_correlation",
    "sector_exposure",
    "execution_quality",
]

_SAMPLE_WINDOW = 100   # number of recent signals to inspect


def _bug(
    name: str,
    detected: bool,
    severity: str,
    description: str,
    evidence: dict[str, Any],
    recommendation: str,
) -> dict[str, Any]:
    return {
        "pattern":        name,
        "detected":       detected,
        "severity":       severity,
        "description":    description,
        "evidence":       evidence,
        "recommendation": recommendation,
    }


class BugDetectionService:
    """Scans for silent-failure patterns that would produce misleading signals."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def run_all_checks(self, sample_n: int = _SAMPLE_WINDOW) -> dict[str, Any]:
        """Run all 9 silent-failure detectors and return a consolidated report."""
        checks = await self._run_checks(sample_n)
        detected_n = sum(1 for c in checks if c["detected"])
        high_n     = sum(1 for c in checks if c["detected"] and c["severity"] == "HIGH")

        return {
            "summary": {
                "total_checks":    len(checks),
                "detected":        detected_n,
                "high_severity":   high_n,
                "system_healthy":  detected_n == 0,
                "sample_window":   sample_n,
            },
            "checks":       checks,
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    async def _run_checks(self, sample_n: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            results.append(await self._check_confidence_identical(sample_n))
        except Exception as exc:
            _log.warning("bug_detection.confidence_identical failed: %s", exc)
            results.append(_bug("confidence_identical", False, "UNKNOWN", "", {"error": str(exc)}, ""))

        for name in _OVERLAY_NAMES:
            try:
                results.append(await self._check_overlay_never_applied(name, sample_n))
            except Exception as exc:
                _log.warning("bug_detection.overlay_never_applied[%s] failed: %s", name, exc)
                results.append(_bug(f"overlay_never_applied:{name}", False, "UNKNOWN", "", {"error": str(exc)}, ""))

        for check_fn in [
            self._check_event_calendar_empty,
            self._check_mtf_always_neutral,
            self._check_grade_always_d,
            self._check_data_quality_never_varies,
            self._check_acceptance_rate_too_low,
            self._check_scanner_idle,
            self._check_position_size_always_zero,
        ]:
            try:
                results.append(await check_fn(sample_n))
            except Exception as exc:
                _log.warning("bug_detection.%s failed: %s", check_fn.__name__, exc)
                results.append(_bug(check_fn.__name__.lstrip("_check_"), False, "UNKNOWN", "", {"error": str(exc)}, ""))

        return results

    # ── 1. Confidence identical ───────────────────────────────────────────────

    async def _check_confidence_identical(self, sample_n: int) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(text(f"""
                SELECT
                    COUNT(DISTINCT ROUND(COALESCE(confidence, 0)::numeric, 2)) AS distinct_values,
                    MIN(confidence) AS min_conf,
                    MAX(confidence) AS max_conf,
                    COUNT(*) AS total
                FROM (
                    SELECT confidence FROM signal_analytics
                    ORDER BY created_at DESC LIMIT {sample_n}
                ) recent
            """))
            row = r.fetchone()

        distinct = int(row[0] or 0)
        mn       = float(row[1] or 0)
        mx       = float(row[2] or 0)
        total    = int(row[3] or 0)
        detected = total >= 20 and distinct <= 1

        return _bug(
            "confidence_identical",
            detected,
            "HIGH" if detected else "OK",
            "All recent signals share the same confidence value — scoring engine may be frozen or returning a constant.",
            {"distinct_confidence_values": distinct, "min": mn, "max": mx, "sample": total},
            "Check that scoring component results are being fetched fresh per signal. Look for cached/static return values." if detected else "",
        )

    # ── 2. Overlay never applied ──────────────────────────────────────────────

    async def _check_overlay_never_applied(self, overlay_name: str, sample_n: int) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(text(f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN decision_trace_json LIKE :pat THEN 1 ELSE 0 END) AS applied_n
                FROM (
                    SELECT decision_trace_json FROM signal_analytics
                    WHERE decision_trace_json IS NOT NULL
                    ORDER BY created_at DESC LIMIT {sample_n}
                ) recent
            """), {"pat": f'%"name": "{overlay_name}"%"applied": true%'})
            row = r.fetchone()

        total    = int(row[0] or 0)
        applied  = int(row[1] or 0)
        detected = total >= 20 and applied == 0

        return _bug(
            f"overlay_never_applied:{overlay_name}",
            detected,
            "MEDIUM" if detected else "OK",
            f"Overlay '{overlay_name}' has never been applied in the last {sample_n} signals — it may be misconfigured or its trigger condition is never met.",
            {"overlay": overlay_name, "applied_count": applied, "total_with_trace": total},
            f"Review the {overlay_name} overlay configuration. Verify its trigger thresholds are reachable in production data." if detected else "",
        )

    # ── 3. Event calendar empty ───────────────────────────────────────────────

    async def _check_event_calendar_empty(self, sample_n: int) -> dict[str, Any]:
        async with self._sf() as db:
            # Check if event_calendar has any upcoming entries
            r = await db.execute(text("""
                SELECT COUNT(*) FROM event_calendar
                WHERE event_date >= CURRENT_DATE - INTERVAL '7 days'
            """))
            event_count = int((r.fetchone() or (0,))[0])

            r2 = await db.execute(text(f"""
                SELECT SUM(CASE WHEN decision_trace_json LIKE :pat THEN 1 ELSE 0 END) AS fired,
                       COUNT(*) AS total
                FROM (
                    SELECT decision_trace_json FROM signal_analytics
                    WHERE decision_trace_json IS NOT NULL
                    ORDER BY created_at DESC LIMIT {sample_n}
                ) recent
            """), {"pat": '%"name": "event_overlay"%"applied": true%'})
            row2 = r2.fetchone()

        event_overlay_fired = int(row2[0] or 0)
        total               = int(row2[1] or 0)

        # Bug: events exist in calendar but overlay never fires
        detected = event_count >= 3 and total >= 20 and event_overlay_fired == 0

        return _bug(
            "event_calendar_empty",
            detected,
            "MEDIUM" if detected else "OK",
            "Event calendar has entries but event_overlay never fired — event data may not be reaching the overlay pipeline.",
            {"calendar_events_7d": event_count, "overlay_fired": event_overlay_fired, "sample": total},
            "Verify that EventCalendarService is being called in OverlayPipeline and that event dates align with signal timestamps." if detected else "",
        )

    # ── 4. MTF always neutral ─────────────────────────────────────────────────

    async def _check_mtf_always_neutral(self, sample_n: int) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(text(f"""
                SELECT
                    COUNT(DISTINCT regime) AS distinct_regimes,
                    COUNT(*) AS total,
                    SUM(CASE WHEN regime = 'NEUTRAL' OR regime IS NULL THEN 1 ELSE 0 END) AS neutral_n
                FROM (
                    SELECT regime FROM signal_analytics
                    ORDER BY created_at DESC LIMIT {sample_n}
                ) recent
            """))
            row = r.fetchone()

        distinct  = int(row[0] or 0)
        total     = int(row[1] or 0)
        neutral_n = int(row[2] or 0)
        neutral_pct = (neutral_n / total * 100) if total > 0 else 0.0
        detected  = total >= 20 and neutral_pct >= 95.0

        return _bug(
            "mtf_always_neutral",
            detected,
            "MEDIUM" if detected else "OK",
            "MTF regime is NEUTRAL in ≥95% of signals — the multi-timeframe engine may be returning a default without real computation.",
            {"distinct_regimes": distinct, "neutral_pct": round(neutral_pct, 1), "sample": total},
            "Check that MTF analysis is running and that the regime classifier is not short-circuiting to 'NEUTRAL' as default." if detected else "",
        )

    # ── 5. Grade always D ────────────────────────────────────────────────────

    async def _check_grade_always_d(self, sample_n: int) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(text(f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN execution_grade = 'D' THEN 1 ELSE 0 END) AS d_count,
                    COUNT(DISTINCT execution_grade) AS distinct_grades
                FROM (
                    SELECT execution_grade FROM signal_analytics
                    WHERE execution_grade IS NOT NULL
                    ORDER BY created_at DESC LIMIT {sample_n}
                ) recent
            """))
            row = r.fetchone()

        total    = int(row[0] or 0)
        d_count  = int(row[1] or 0)
        distinct = int(row[2] or 0)
        d_pct    = (d_count / total * 100) if total > 0 else 0.0
        detected = total >= 20 and d_pct >= 90.0

        return _bug(
            "grade_always_d",
            detected,
            "HIGH" if detected else "OK",
            "Execution grade is 'D' in ≥90% of signals — the grade assignment logic may be broken or thresholds may be too strict.",
            {"d_pct": round(d_pct, 1), "distinct_grades": distinct, "sample": total},
            "Review execution grade thresholds in OverlayPipeline. Verify that A/B/C grade criteria are reachable with real data." if detected else "",
        )

    # ── 6. Data quality never varies ─────────────────────────────────────────

    async def _check_data_quality_never_varies(self, sample_n: int) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(text(f"""
                SELECT
                    COUNT(DISTINCT ROUND(COALESCE(data_quality_score, 0)::numeric, 3)) AS distinct_values,
                    MIN(data_quality_score) AS min_dq,
                    MAX(data_quality_score) AS max_dq,
                    COUNT(*) AS total
                FROM (
                    SELECT data_quality_score FROM signal_analytics
                    WHERE data_quality_score IS NOT NULL
                    ORDER BY created_at DESC LIMIT {sample_n}
                ) recent
            """))
            row = r.fetchone()

        distinct = int(row[0] or 0)
        mn       = float(row[1] or 0)
        mx       = float(row[2] or 0)
        total    = int(row[3] or 0)
        detected = total >= 20 and distinct <= 1

        return _bug(
            "data_quality_never_varies",
            detected,
            "MEDIUM" if detected else "OK",
            "data_quality_score is constant across all recent signals — the quality check may be returning a hardcoded value.",
            {"distinct_values": distinct, "min": mn, "max": mx, "sample": total},
            "Review data quality scoring logic. Ensure it evaluates each signal's actual data sources, not a global constant." if detected else "",
        )

    # ── 7. Acceptance rate too low ────────────────────────────────────────────

    async def _check_acceptance_rate_too_low(self, sample_n: int) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(text(f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END) AS accepted
                FROM (
                    SELECT was_accepted FROM signal_analytics
                    ORDER BY created_at DESC LIMIT {sample_n}
                ) recent
            """))
            row = r.fetchone()

        total    = int(row[0] or 0)
        accepted = int(row[1] or 0)
        rate     = (accepted / total * 100) if total > 0 else 0.0
        detected = total >= 20 and rate < 5.0

        return _bug(
            "acceptance_rate_too_low",
            detected,
            "HIGH" if detected else "OK",
            "Signal acceptance rate is below 5% — confidence gates or overlay pipeline may be rejecting everything systematically.",
            {"acceptance_rate_pct": round(rate, 2), "accepted": accepted, "total": total},
            "Review confidence gate thresholds and overlay pipeline rejection logic. Check if a recent config change tightened gates too aggressively." if detected else "",
        )

    # ── 8. Scanner idle ───────────────────────────────────────────────────────

    async def _check_scanner_idle(self, _sample_n: int) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT MAX(created_at) AS last_signal FROM signal_analytics
            """))
            row = r.fetchone()

        last_signal = row[0] if row else None
        if last_signal:
            age_min = (datetime.now(UTC) - last_signal.replace(tzinfo=UTC)).total_seconds() / 60
        else:
            age_min = float("inf")

        detected = age_min > 120  # no signal in 2 hours

        return _bug(
            "scanner_idle",
            detected,
            "HIGH" if detected else "OK",
            f"No signals generated in the last {round(age_min)} minutes — scanner may have stopped or crashed.",
            {
                "last_signal_at":   last_signal.isoformat() if last_signal else None,
                "age_minutes":      round(age_min, 1) if age_min != float("inf") else None,
                "threshold_minutes": 120,
            },
            "Check SignalScannerService logs for errors. Verify Celery/APScheduler tasks are running and market data feed is alive." if detected else "",
        )

    # ── 9. Position size always zero ─────────────────────────────────────────

    async def _check_position_size_always_zero(self, sample_n: int) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(text(f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN COALESCE(lot_size, 0) <= 1 THEN 1 ELSE 0 END) AS zero_n
                FROM (
                    SELECT lot_size FROM signal_analytics
                    WHERE was_accepted = true
                    ORDER BY created_at DESC LIMIT {sample_n}
                ) recent
            """))
            row = r.fetchone()

        total  = int(row[0] or 0)
        zero_n = int(row[1] or 0)
        pct    = (zero_n / total * 100) if total > 0 else 0.0
        detected = total >= 10 and pct >= 90.0

        return _bug(
            "position_size_always_zero",
            detected,
            "HIGH" if detected else "OK",
            "Position sizer returns lot_size ≤ 1 for ≥90% of accepted signals — risk engine may have a calculation bug.",
            {"tiny_lot_pct": round(pct, 1), "tiny_n": zero_n, "accepted_sample": total},
            "Review PositionSizer logic. Ensure margin data is loaded, VIX is available, and lot sizes are seeded for F&O symbols." if detected else "",
        )
