"""StatisticalValidationService — Phase 22 §2 §3 §4 §5.

Sections:
  §2  Validation milestones at 50 / 200 / 500 / 1000 completed trades
  §3  95% confidence intervals for win rate, profit factor, expectancy, Sharpe
  §4  Per-overlay validation — trades affected, CI, win rate, PF, EV, KEEP/REDUCE/REMOVE
  §5  Per-component validation — discriminative power, regime stability, recommendation

Rules enforced here:
  - No trading logic changed.
  - No threshold modification.
  - All outputs are measurements, not directives.
  - Recommendations require minimum sample sizes (stated explicitly).
"""

from __future__ import annotations

import math
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_Z95 = 1.96
_MILESTONE_THRESHOLDS = (50, 200, 500, 1000)

_COMPONENTS = [
    ("trend_score",        "Trend"),
    ("volume_score",       "Volume"),
    ("vwap_score",         "VWAP"),
    ("oi_score",           "OI Buildup"),
    ("option_chain_score", "Option Chain"),
    ("sentiment_score",    "Sentiment"),
    ("iv_score",           "IV Analysis"),
]

_OVERLAY_NAMES = [
    "market_context",
    "event_overlay",
    "regime_stability",
    "portfolio_heat",
    "portfolio_correlation",
    "sector_exposure",
    "execution_quality",
]

_OVERLAY_LABELS = {
    "market_context":        "Market Context",
    "event_overlay":         "Event Calendar",
    "regime_stability":      "Regime Stability",
    "portfolio_heat":        "Portfolio Heat",
    "portfolio_correlation": "Correlation",
    "sector_exposure":       "Sector Exposure",
    "execution_quality":     "Execution Quality",
}

_MILESTONE_DESCRIPTIONS = {
    50:   "System sanity — confirm pipeline runs end-to-end without silent errors",
    200:  "Initial calibration — first meaningful overlay effectiveness check",
    500:  "Weight review allowed — component attribution statistically meaningful",
    1000: "Scaling review allowed — full production validation complete",
}


# ─── Statistical helpers ─────────────────────────────────────────────────────


def _wilson_ci(k: int, n: int, z: float = _Z95) -> tuple[float, float]:
    """Wilson score confidence interval for a proportion.

    Returns (lower, upper) as fractions [0, 1].
    Preferred over normal approximation for small n or extreme p.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half_w = z * math.sqrt(max(0.0, p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return (max(0.0, round(center - half_w, 4)), min(1.0, round(center + half_w, 4)))


def _normal_ci(mean: float, std: float, n: int, z: float = _Z95) -> tuple[float, float]:
    """Normal approximation CI for a mean (used for expectancy)."""
    if n < 2:
        return (round(mean, 4), round(mean, 4))
    se = std / math.sqrt(n)
    return (round(mean - z * se, 4), round(mean + z * se, 4))


def _overlay_recommendation(
    fired_n: int, fired_wr: float, base_n: int, base_wr: float,
) -> str:
    """KEEP / REDUCE / REMOVE / UNKNOWN based on win-rate delta and sample size."""
    if fired_n < 20 or base_n < 20:
        return "UNKNOWN"
    delta = fired_wr - base_wr
    if fired_n >= 50 and delta <= -5.0:
        return "REMOVE"
    if delta <= -2.0:
        return "REDUCE"
    return "KEEP"


def _component_recommendation(
    high_wr: float, low_wr: float, high_n: int, low_n: int,
) -> str:
    if high_n < 10 or low_n < 10:
        return "Keep unchanged"
    delta = high_wr - low_wr
    if delta >= 10.0:
        return "Increase weight (future review only — requires ≥500 trades + walk-forward)"
    if delta <= -5.0:
        return "Reduce weight (future review only — requires ≥500 trades + walk-forward)"
    return "Keep unchanged"


# ─── Service ─────────────────────────────────────────────────────────────────


class StatisticalValidationService:
    """Read-only statistical validation for all Phase 22 evidence sections."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── §2 Validation Milestones ──────────────────────────────────────────────

    async def get_validation_milestones(self) -> dict[str, Any]:
        """Milestone tracking at 50 / 200 / 500 / 1000 completed trades.

        Each milestone reports PENDING / PASSED / FAILED / BLOCKED with criteria.
        """
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*)                                             AS n,
                        SUM(CASE WHEN target_hit THEN 1 ELSE 0 END)         AS wins,
                        ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_rate,
                        ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END), 0)
                        , 3)                                                 AS profit_factor,
                        ROUND(AVG(COALESCE(pnl_pct, 0)) * 100, 4)           AS expectancy
                    FROM signal_analytics
                    WHERE was_accepted = true AND outcome IS NOT NULL
                """))
                row = r.fetchone()
        except Exception as exc:
            _log.warning("statistical_validation.milestones_failed: %s", exc)
            return {"error": str(exc)}

        total = int(row[0] or 0)
        wins  = int(row[1] or 0)
        wr    = float(row[2] or 0)
        pf    = float(row[3]) if row[3] else None
        expct = float(row[4] or 0)

        ci_lo, ci_hi = _wilson_ci(wins, total)

        milestones = []
        for threshold in _MILESTONE_THRESHOLDS:
            if total < threshold:
                milestones.append({
                    "threshold":    threshold,
                    "status":       "PENDING",
                    "trades_to_go": threshold - total,
                    "description":  _MILESTONE_DESCRIPTIONS.get(threshold, ""),
                })
                continue

            criteria = {
                "min_trades":           total >= threshold,
                "win_rate_ge_45":       wr >= 45.0,
                "profit_factor_ge_1":   pf is None or pf >= 1.0,
                "positive_expectancy":  expct >= 0,
            }
            blocked = not criteria["win_rate_ge_45"] or (pf is not None and pf < 1.0)
            passed  = all(criteria.values())

            milestones.append({
                "threshold":     threshold,
                "status":        "PASSED" if passed else ("BLOCKED" if blocked else "FAILED"),
                "criteria":      criteria,
                "win_rate":      wr,
                "profit_factor": pf,
                "expectancy":    expct,
                "description":   _MILESTONE_DESCRIPTIONS.get(threshold, ""),
            })

        return {
            "total_completed":    total,
            "wins":               wins,
            "current_win_rate":   wr,
            "current_pf":         pf,
            "current_expectancy": expct,
            "win_rate_ci_95":     {
                "lower": round(ci_lo * 100, 2),
                "upper": round(ci_hi * 100, 2),
            },
            "milestones": milestones,
        }

    # ── §3 Confidence Intervals ───────────────────────────────────────────────

    async def get_confidence_intervals(self, lookback_days: int = 90) -> dict[str, Any]:
        """95% CI for win rate, expectancy, profit factor, and annualised Sharpe ratio."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*)   AS n,
                        SUM(CASE WHEN target_hit THEN 1 ELSE 0 END)                      AS wins,
                        ROUND(AVG(COALESCE(pnl_pct, 0)) * 100, 6)                        AS avg_pnl,
                        ROUND(STDDEV(COALESCE(pnl_pct, 0)) * 100, 6)                     AS std_pnl,
                        ROUND(SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END) * 100, 6) AS gross_profit,
                        ROUND(SUM(CASE WHEN stop_hit  THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END) * 100, 6) AS gross_loss
                    FROM signal_analytics
                    WHERE was_accepted = true AND outcome IS NOT NULL
                      AND created_at >= :cutoff
                """), {"cutoff": cutoff})
                row = r.fetchone()

                r2 = await db.execute(text("""
                    SELECT ROUND(SUM(COALESCE(pnl_pct, 0)) * 100, 6) AS daily_pnl
                    FROM signal_analytics
                    WHERE was_accepted = true AND outcome IS NOT NULL
                      AND created_at >= :cutoff
                    GROUP BY DATE(created_at AT TIME ZONE 'UTC')
                    ORDER BY 1
                """), {"cutoff": cutoff})
                daily_rows = r2.fetchall()
        except Exception as exc:
            _log.warning("statistical_validation.ci_failed: %s", exc)
            return {"error": str(exc)}

        n        = int(row[0] or 0)
        wins     = int(row[1] or 0)
        avg_pnl  = float(row[2] or 0)
        std_pnl  = float(row[3] or 0)
        g_profit = float(row[4] or 0)
        g_loss   = float(row[5] or 0)

        # Win rate + Wilson CI
        wr = (wins / n * 100) if n > 0 else 0.0
        ci_lo, ci_hi = _wilson_ci(wins, n)
        wr_info = {
            "estimate": round(wr, 2),
            "lower":    round(ci_lo * 100, 2),
            "upper":    round(ci_hi * 100, 2),
            "width":    round((ci_hi - ci_lo) * 100, 2),
            "method":   "Wilson score interval",
        }

        # Expectancy + normal CI
        exp_lo, exp_hi = _normal_ci(avg_pnl, std_pnl, n)
        exp_info = {
            "estimate": round(avg_pnl, 4),
            "lower":    exp_lo,
            "upper":    exp_hi,
            "std":      round(std_pnl, 4),
            "method":   "Normal approximation",
        }

        # Profit factor (no closed-form CI)
        pf = g_profit / g_loss if g_loss > 0 else None
        pf_info = {
            "estimate":     round(pf, 3) if pf else None,
            "gross_profit": round(g_profit, 4),
            "gross_loss":   round(g_loss, 4),
            "note":         f"Computed from {n} trades — CI requires bootstrap (not implemented)",
        }

        # Annualised Sharpe from daily PnL series
        daily_pnls = [float(r_[0]) for r_ in daily_rows]
        if len(daily_pnls) >= 5:
            dm   = sum(daily_pnls) / len(daily_pnls)
            dvar = sum((x - dm) ** 2 for x in daily_pnls) / max(1, len(daily_pnls) - 1)
            dstd = math.sqrt(dvar)
            sharpe = round(dm / dstd * math.sqrt(252), 3) if dstd > 0 else None
            sharpe_info = {
                "estimate":         sharpe,
                "trading_days":     len(daily_pnls),
                "daily_mean_pct":   round(dm, 4),
                "daily_std_pct":    round(dstd, 4),
            }
        else:
            sharpe_info = {
                "estimate": None,
                "note":     f"Need ≥5 trading days; have {len(daily_pnls)}",
            }

        return {
            "lookback_days":   lookback_days,
            "sample_size":     n,
            "win_rate":        wr_info,
            "expectancy":      exp_info,
            "profit_factor":   pf_info,
            "sharpe":          sharpe_info,
            "sufficient_data": n >= 30,
            "note": (
                "Confidence intervals are approximate. "
                "Statistical conclusions require ≥200 completed trades."
            ),
        }

    # ── §4 Overlay Validation ─────────────────────────────────────────────────

    async def get_overlay_validation(self, lookback_days: int = 60) -> dict[str, Any]:
        """Per-overlay effectiveness — KEEP / REDUCE / REMOVE / UNKNOWN recommendation.

        Matches on decision_trace_json using LIKE — works with consistent json.dumps output.
        Minimum 20 samples per group required before any recommendation is issued.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        results = []

        for overlay_name in _OVERLAY_NAMES:
            try:
                async with self._sf() as db:
                    r = await db.execute(text("""
                        SELECT
                            CASE WHEN decision_trace_json IS NOT NULL
                                      AND decision_trace_json LIKE :pat
                                 THEN 'fired' ELSE 'baseline' END AS grp,
                            COUNT(*)                               AS n,
                            ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_rate,
                            ROUND(AVG(COALESCE(pnl_pct, current_return_pct, 0)) * 100, 4)   AS avg_pnl,
                            ROUND(
                                SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END) /
                                NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END), 0)
                            , 3)                                   AS pf
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY grp
                    """), {
                        "pat":    f'%"name": "{overlay_name}"%"applied": true%',
                        "cutoff": cutoff,
                    })
                    rows = r.fetchall()
            except Exception as exc:
                _log.warning("overlay_validation.query_failed overlay=%s: %s", overlay_name, exc)
                results.append({
                    "name":  overlay_name,
                    "label": _OVERLAY_LABELS.get(overlay_name, overlay_name),
                    "error": str(exc),
                })
                continue

            groups: dict[str, dict] = {}
            for row in rows:
                groups[row[0]] = {
                    "n":        int(row[1]),
                    "win_rate": float(row[2] or 0),
                    "avg_pnl":  float(row[3] or 0),
                    "pf":       float(row[4]) if row[4] else None,
                }

            fired    = groups.get("fired",    {"n": 0, "win_rate": 0.0, "avg_pnl": 0.0, "pf": None})
            baseline = groups.get("baseline", {"n": 0, "win_rate": 0.0, "avg_pnl": 0.0, "pf": None})

            fn, bn = fired["n"], baseline["n"]
            fwr, bwr = fired["win_rate"], baseline["win_rate"]

            f_lo, f_hi = _wilson_ci(int(fn * fwr / 100), fn)
            b_lo, b_hi = _wilson_ci(int(bn * bwr / 100), bn)

            results.append({
                "name":           overlay_name,
                "label":          _OVERLAY_LABELS.get(overlay_name, overlay_name),
                "fired":          fired,
                "baseline":       baseline,
                "fired_ci_95":    {"lower": round(f_lo * 100, 2), "upper": round(f_hi * 100, 2)},
                "baseline_ci_95": {"lower": round(b_lo * 100, 2), "upper": round(b_hi * 100, 2)},
                "win_rate_delta": round(fwr - bwr, 2),
                "pnl_delta":      round(fired["avg_pnl"] - baseline["avg_pnl"], 4),
                "recommendation": _overlay_recommendation(fn, fwr, bn, bwr),
            })

        return {
            "lookback_days": lookback_days,
            "overlays":      results,
            "note": (
                "UNKNOWN = fewer than 20 trades in at least one group. "
                "REMOVE recommendation requires ≥50 fired trades."
            ),
        }

    # ── §5 Component Validation ───────────────────────────────────────────────

    async def get_component_validation(self, lookback_days: int = 60) -> dict[str, Any]:
        """Per-component discriminative power and regime stability.

        Discriminative power = win_rate(score≥70) − win_rate(score≤30).
        Positive means the component correctly identifies better setups.
        Recommendation changes require ≥500 trades + walk-forward validation.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        results = []

        for col, label in _COMPONENTS:
            try:
                async with self._sf() as db:
                    r = await db.execute(text(f"""
                        SELECT
                            CASE WHEN {col} >= 70 THEN 'HIGH'
                                 WHEN {col} <= 30 THEN 'LOW'
                                 ELSE 'MID' END           AS bucket,
                            COUNT(*)                      AS n,
                            ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_rate,
                            ROUND(AVG(COALESCE(pnl_pct, 0)) * 100, 4)                       AS avg_pnl
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND {col} IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY bucket
                    """), {"cutoff": cutoff})
                    bucket_rows = r.fetchall()

                    r2 = await db.execute(text(f"""
                        SELECT
                            regime,
                            ROUND(AVG({col}), 2)          AS avg_score,
                            ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_rate,
                            COUNT(*)                      AS n
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND {col} IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY regime
                        HAVING COUNT(*) >= 5
                        ORDER BY win_rate DESC
                    """), {"cutoff": cutoff})
                    regime_rows = r2.fetchall()
            except Exception as exc:
                _log.warning("component_validation.query_failed col=%s: %s", col, exc)
                results.append({"name": col, "label": label, "error": str(exc)})
                continue

            buckets: dict[str, dict] = {}
            for row in bucket_rows:
                buckets[row[0]] = {
                    "n":        int(row[1]),
                    "win_rate": float(row[2] or 0),
                    "avg_pnl":  float(row[3] or 0),
                }

            high = buckets.get("HIGH", {"n": 0, "win_rate": 0.0, "avg_pnl": 0.0})
            mid  = buckets.get("MID",  {"n": 0, "win_rate": 0.0, "avg_pnl": 0.0})
            low  = buckets.get("LOW",  {"n": 0, "win_rate": 0.0, "avg_pnl": 0.0})

            disc_power = (
                round(high["win_rate"] - low["win_rate"], 2)
                if high["n"] >= 5 and low["n"] >= 5
                else None
            )
            regime_breakdown = [
                {
                    "regime":    row[0],
                    "avg_score": float(row[1] or 0),
                    "win_rate":  float(row[2] or 0),
                    "n":         int(row[3]),
                }
                for row in regime_rows
            ]

            results.append({
                "name":                  col,
                "label":                 label,
                "high_score_bucket":     high,
                "mid_score_bucket":      mid,
                "low_score_bucket":      low,
                "discriminative_power":  disc_power,
                "regime_breakdown":      regime_breakdown,
                "recommendation":        _component_recommendation(
                    high["win_rate"], low["win_rate"], high["n"], low["n"]
                ),
            })

        return {
            "lookback_days": lookback_days,
            "components":    results,
            "note": (
                "discriminative_power = HIGH win_rate − LOW win_rate. "
                "Weight changes require ≥500 completed trades + walk-forward validation."
            ),
        }
