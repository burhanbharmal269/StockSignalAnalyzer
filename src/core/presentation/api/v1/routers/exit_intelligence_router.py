"""Phase 24 Exit Intelligence analytics endpoints.

GET /api/v1/exit-intelligence/summary           — overall dashboard stats
GET /api/v1/exit-intelligence/target-distribution  — §6 how many trades hit each premium level
GET /api/v1/exit-intelligence/mfe-calibration   — §7 avg/median/P95 MFE by score/regime/symbol/DTE
GET /api/v1/exit-intelligence/expiry-analysis   — §4 distribution of expiry_reason labels
GET /api/v1/exit-intelligence/regime-targets    — §10 avg MFE by market regime
GET /api/v1/exit-intelligence/strike-analysis   — §11 ATM vs OTM option efficiency
GET /api/v1/exit-intelligence/calibration-report — §9 weekly calibration report
"""

from __future__ import annotations

from datetime import date
from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_authenticated
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/exit-intelligence", tags=["Exit Intelligence"])


# ── helpers ────────────────────────────────────────────────────────────────

def _sf() -> async_sessionmaker[AsyncSession]:
    from container import ApplicationContainer as _C
    return _C.db_session_factory()  # type: ignore[return-value]


async def _query(sf: async_sessionmaker[AsyncSession], sql: str, params: dict | None = None) -> list[dict]:
    async with sf() as db:
        result = await db.execute(text(sql), params or {})
        return [dict(r._mapping) for r in result.fetchall()]


# ── §6 Target Distribution ─────────────────────────────────────────────────

@router.get("/target-distribution")
@inject
async def target_distribution(
    days: int = Query(30, ge=1, le=365, description="Look-back window in calendar days"),
    current_user: CurrentUser = Depends(require_authenticated),
    session_factory: async_sessionmaker[AsyncSession] = Depends(
        Provide[ApplicationContainer.db_session_factory]
    ),
) -> dict[str, Any]:
    """How many accepted trades reached each premium gain tier (10/20/30/40/50/55%)."""
    rows = await _query(
        session_factory,
        """
        SELECT
            COUNT(*)                                                      AS total_trades,
            COUNT(*) FILTER (WHERE mfe_pct >= 10)                         AS reached_10,
            COUNT(*) FILTER (WHERE mfe_pct >= 20)                         AS reached_20,
            COUNT(*) FILTER (WHERE mfe_pct >= 30)                         AS reached_30,
            COUNT(*) FILTER (WHERE mfe_pct >= 40)                         AS reached_40,
            COUNT(*) FILTER (WHERE mfe_pct >= 50)                         AS reached_50,
            COUNT(*) FILTER (WHERE mfe_pct >= 55)                         AS reached_55,
            ROUND(AVG(mfe_pct)::numeric, 2)                               AS avg_mfe_pct,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY mfe_pct)::numeric, 2) AS median_mfe_pct,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY mfe_pct)::numeric, 2) AS p95_mfe_pct,
            ROUND(AVG(configured_target_pct)::numeric, 2)                 AS avg_configured_target,
            ROUND(AVG(recommended_target_pct)::numeric, 2)                AS avg_recommended_target
        FROM signal_analytics
        WHERE was_accepted = true
          AND created_at >= NOW() - (:days || ' days')::interval
          AND mfe_pct IS NOT NULL
        """,
        {"days": days},
    )
    row = rows[0] if rows else {}
    total = row.get("total_trades") or 0

    def pct(n: int | None) -> float | None:
        return round(n / total * 100, 1) if total and n else None

    return {
        "total_trades": total,
        "days": days,
        "avg_mfe_pct": row.get("avg_mfe_pct"),
        "median_mfe_pct": row.get("median_mfe_pct"),
        "p95_mfe_pct": row.get("p95_mfe_pct"),
        "avg_configured_target": row.get("avg_configured_target"),
        "avg_recommended_target": row.get("avg_recommended_target"),
        "reach_rates": {
            "10": {"count": row.get("reached_10"), "pct": pct(row.get("reached_10"))},
            "20": {"count": row.get("reached_20"), "pct": pct(row.get("reached_20"))},
            "30": {"count": row.get("reached_30"), "pct": pct(row.get("reached_30"))},
            "40": {"count": row.get("reached_40"), "pct": pct(row.get("reached_40"))},
            "50": {"count": row.get("reached_50"), "pct": pct(row.get("reached_50"))},
            "55": {"count": row.get("reached_55"), "pct": pct(row.get("reached_55"))},
        },
    }


# ── §7 MFE Calibration ────────────────────────────────────────────────────

@router.get("/mfe-calibration")
@inject
async def mfe_calibration(
    days: int = Query(30, ge=1, le=365),
    group_by: str = Query("regime", regex="^(regime|symbol|dte_bucket|score_bucket)$"),
    current_user: CurrentUser = Depends(require_authenticated),
    session_factory: async_sessionmaker[AsyncSession] = Depends(
        Provide[ApplicationContainer.db_session_factory]
    ),
) -> dict[str, Any]:
    """Average, median, and 95th percentile MFE grouped by regime / symbol / DTE / score bucket."""
    group_expr = {
        "regime":       "COALESCE(regime, 'UNKNOWN')",
        "symbol":       "ticker",
        "dte_bucket":   "CASE WHEN dte <= 3 THEN 'weekly' WHEN dte <= 10 THEN '1-10d' WHEN dte <= 20 THEN '11-20d' ELSE '21+d' END",
        "score_bucket": "CASE WHEN adjusted_score >= 8 THEN 'A (8+)' WHEN adjusted_score >= 6 THEN 'B (6-8)' WHEN adjusted_score >= 4 THEN 'C (4-6)' ELSE 'D (<4)' END",
    }[group_by]

    rows = await _query(
        session_factory,
        f"""
        SELECT
            {group_expr}                                                              AS group_label,
            COUNT(*)                                                                  AS trade_count,
            ROUND(AVG(mfe_pct)::numeric, 2)                                          AS avg_mfe,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY mfe_pct)::numeric, 2) AS median_mfe,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY mfe_pct)::numeric, 2) AS p95_mfe,
            ROUND(AVG(target_realism_pct)::numeric, 1)                               AS avg_target_realism,
            ROUND(AVG(option_efficiency_score)::numeric, 3)                          AS avg_efficiency
        FROM signal_analytics
        WHERE was_accepted = true
          AND created_at >= NOW() - (:days || ' days')::interval
          AND mfe_pct IS NOT NULL
        GROUP BY 1
        ORDER BY avg_mfe DESC NULLS LAST
        """,
        {"days": days},
    )
    return {"group_by": group_by, "days": days, "rows": rows}


# ── §4 Expiry Analysis ────────────────────────────────────────────────────

@router.get("/expiry-analysis")
@inject
async def expiry_analysis(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_authenticated),
    session_factory: async_sessionmaker[AsyncSession] = Depends(
        Provide[ApplicationContainer.db_session_factory]
    ),
) -> dict[str, Any]:
    """Distribution of why expired trades didn't hit their target."""
    rows = await _query(
        session_factory,
        """
        SELECT
            COALESCE(expiry_reason, 'NOT_CLASSIFIED')  AS reason,
            COUNT(*)                                    AS count,
            ROUND(AVG(mfe_pct)::numeric, 2)            AS avg_mfe,
            ROUND(AVG(target_realism_pct)::numeric, 1) AS avg_target_realism
        FROM signal_analytics
        WHERE was_accepted = true
          AND created_at >= NOW() - (:days || ' days')::interval
          AND outcome = 'EXPIRED'
        GROUP BY 1
        ORDER BY count DESC
        """,
        {"days": days},
    )
    total = sum(r.get("count") or 0 for r in rows)
    for r in rows:
        r["pct"] = round((r.get("count") or 0) / total * 100, 1) if total else None
    return {"days": days, "total_expired": total, "reasons": rows}


# ── §10 Regime Targets ────────────────────────────────────────────────────

@router.get("/regime-targets")
@inject
async def regime_targets(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_authenticated),
    session_factory: async_sessionmaker[AsyncSession] = Depends(
        Provide[ApplicationContainer.db_session_factory]
    ),
) -> dict[str, Any]:
    """Average MFE and target realism by market regime."""
    rows = await _query(
        session_factory,
        """
        SELECT
            COALESCE(regime, 'UNKNOWN')                 AS regime,
            COUNT(*)                                    AS trade_count,
            ROUND(AVG(mfe_pct)::numeric, 2)            AS avg_mfe,
            ROUND(AVG(configured_target_pct)::numeric, 2) AS avg_configured_target,
            ROUND(AVG(recommended_target_pct)::numeric, 2) AS avg_recommended_target,
            ROUND(AVG(target_realism_pct)::numeric, 1) AS avg_target_realism,
            ROUND(AVG(target_confidence)::numeric, 1)  AS avg_target_confidence,
            COUNT(*) FILTER (WHERE target_hit)         AS target_hit_count,
            COUNT(*) FILTER (WHERE stop_hit)           AS stop_hit_count
        FROM signal_analytics
        WHERE was_accepted = true
          AND created_at >= NOW() - (:days || ' days')::interval
          AND mfe_pct IS NOT NULL
        GROUP BY 1
        ORDER BY trade_count DESC
        """,
        {"days": days},
    )
    for r in rows:
        tc = r.get("trade_count") or 0
        r["target_hit_rate"] = round((r.get("target_hit_count") or 0) / tc * 100, 1) if tc else None
        r["stop_hit_rate"]   = round((r.get("stop_hit_count") or 0) / tc * 100, 1) if tc else None
    return {"days": days, "regimes": rows}


# ── §11 Strike Analysis ───────────────────────────────────────────────────

@router.get("/strike-analysis")
@inject
async def strike_analysis(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_authenticated),
    session_factory: async_sessionmaker[AsyncSession] = Depends(
        Provide[ApplicationContainer.db_session_factory]
    ),
) -> dict[str, Any]:
    """Compare ATM vs OTM option performance based on delta efficiency."""
    rows = await _query(
        session_factory,
        """
        SELECT
            CASE
                WHEN delta_efficiency >= 0.45 THEN 'ATM (Δ≥0.45)'
                WHEN delta_efficiency >= 0.30 THEN 'Mild OTM (0.30-0.45)'
                WHEN delta_efficiency >= 0.20 THEN 'OTM (0.20-0.30)'
                ELSE 'Deep OTM (<0.20)'
            END                                         AS strike_type,
            COUNT(*)                                    AS trade_count,
            ROUND(AVG(mfe_pct)::numeric, 2)            AS avg_mfe,
            ROUND(AVG(option_efficiency_score)::numeric, 3) AS avg_efficiency,
            ROUND(AVG(target_realism_pct)::numeric, 1) AS avg_target_realism,
            ROUND(AVG(time_in_profit_minutes)::numeric, 0) AS avg_time_in_profit_min,
            COUNT(*) FILTER (WHERE expiry_reason = 'WRONG_STRIKE_SELECTION') AS wrong_strike_count
        FROM signal_analytics
        WHERE was_accepted = true
          AND created_at >= NOW() - (:days || ' days')::interval
          AND delta_efficiency IS NOT NULL
        GROUP BY 1
        ORDER BY avg_mfe DESC NULLS LAST
        """,
        {"days": days},
    )
    return {"days": days, "strike_buckets": rows}


# ── §9 Calibration Report ─────────────────────────────────────────────────

@router.get("/calibration-report")
@inject
async def calibration_report(
    days: int = Query(7, ge=1, le=90),
    current_user: CurrentUser = Depends(require_authenticated),
    session_factory: async_sessionmaker[AsyncSession] = Depends(
        Provide[ApplicationContainer.db_session_factory]
    ),
) -> dict[str, Any]:
    """Weekly calibration report: configured vs recommended vs achieved targets."""
    summary = await _query(
        session_factory,
        """
        SELECT
            COUNT(*)                                               AS total_accepted,
            COUNT(*) FILTER (WHERE mfe_pct IS NOT NULL)           AS with_outcome,
            ROUND(AVG(configured_target_pct)::numeric, 2)         AS avg_configured_target,
            ROUND(AVG(recommended_target_pct)::numeric, 2)        AS avg_recommended_target,
            ROUND(AVG(mfe_pct)::numeric, 2)                       AS avg_achieved_mfe,
            ROUND(AVG(target_realism_pct)::numeric, 1)            AS avg_target_realism,
            ROUND(AVG(target_confidence)::numeric, 1)             AS avg_target_confidence,
            COUNT(*) FILTER (WHERE target_hit)                    AS target_hit_count,
            COUNT(*) FILTER (WHERE stop_hit)                      AS stop_hit_count,
            COUNT(*) FILTER (WHERE outcome = 'EXPIRED')           AS expired_count,
            ROUND(AVG(option_efficiency_score)::numeric, 3)       AS avg_option_efficiency,
            ROUND(AVG(time_in_profit_minutes)::numeric, 0)        AS avg_time_in_profit_min,
            ROUND(AVG(time_in_loss_minutes)::numeric, 0)          AS avg_time_in_loss_min
        FROM signal_analytics
        WHERE was_accepted = true
          AND created_at >= NOW() - (:days || ' days')::interval
        """,
        {"days": days},
    )

    expiry_dist = await _query(
        session_factory,
        """
        SELECT COALESCE(expiry_reason, 'NOT_CLASSIFIED') AS reason, COUNT(*) AS count
        FROM signal_analytics
        WHERE was_accepted = true
          AND outcome = 'EXPIRED'
          AND created_at >= NOW() - (:days || ' days')::interval
        GROUP BY 1
        ORDER BY count DESC
        """,
        {"days": days},
    )

    top_symbols = await _query(
        session_factory,
        """
        SELECT ticker, COUNT(*) AS trades, ROUND(AVG(mfe_pct)::numeric, 2) AS avg_mfe
        FROM signal_analytics
        WHERE was_accepted = true
          AND created_at >= NOW() - (:days || ' days')::interval
          AND mfe_pct IS NOT NULL
        GROUP BY ticker
        ORDER BY avg_mfe DESC NULLS LAST
        LIMIT 10
        """,
        {"days": days},
    )

    s = summary[0] if summary else {}
    total = s.get("with_outcome") or 0
    return {
        "report_period_days": days,
        "generated_at": date.today().isoformat(),
        "summary": s,
        "win_rate": round((s.get("target_hit_count") or 0) / total * 100, 1) if total else None,
        "loss_rate": round((s.get("stop_hit_count") or 0) / total * 100, 1) if total else None,
        "expired_rate": round((s.get("expired_count") or 0) / total * 100, 1) if total else None,
        "calibration_gap": (
            round((s.get("avg_configured_target") or 0) - (s.get("avg_achieved_mfe") or 0), 2)
            if s.get("avg_configured_target") and s.get("avg_achieved_mfe") else None
        ),
        "expiry_breakdown": expiry_dist,
        "top_symbols_by_mfe": top_symbols,
    }


# ── Overall summary dashboard ─────────────────────────────────────────────

@router.get("/summary")
@inject
async def summary(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_authenticated),
    session_factory: async_sessionmaker[AsyncSession] = Depends(
        Provide[ApplicationContainer.db_session_factory]
    ),
) -> dict[str, Any]:
    """High-level Phase 24 dashboard: target calibration health at a glance."""
    rows = await _query(
        session_factory,
        """
        SELECT
            COUNT(*)                                                         AS total_accepted,
            COUNT(*) FILTER (WHERE mfe_pct IS NOT NULL)                     AS with_mfe,
            ROUND(AVG(mfe_pct)::numeric, 2)                                 AS avg_mfe,
            ROUND(AVG(configured_target_pct)::numeric, 2)                   AS avg_configured_target,
            ROUND(AVG(recommended_target_pct)::numeric, 2)                  AS avg_recommended_target,
            ROUND(AVG(target_realism_pct)::numeric, 1)                      AS avg_target_realism,
            COUNT(*) FILTER (WHERE target_realism_pct < 50 AND mfe_pct IS NOT NULL) AS unrealistic_target_count,
            COUNT(*) FILTER (WHERE target_hit)                              AS target_hits,
            COUNT(*) FILTER (WHERE stop_hit)                                AS stop_hits,
            COUNT(*) FILTER (WHERE outcome = 'EXPIRED')                     AS expired,
            ROUND(AVG(option_efficiency_score)::numeric, 3)                 AS avg_option_efficiency,
            ROUND(AVG(expected_underlying_move_pct)::numeric, 3)            AS avg_expected_move
        FROM signal_analytics
        WHERE was_accepted = true
          AND created_at >= NOW() - (:days || ' days')::interval
        """,
        {"days": days},
    )
    r = rows[0] if rows else {}
    total = r.get("with_mfe") or 0
    return {
        "days": days,
        "total_accepted": r.get("total_accepted"),
        "with_outcome": total,
        "avg_mfe_pct": r.get("avg_mfe"),
        "avg_configured_target": r.get("avg_configured_target"),
        "avg_recommended_target": r.get("avg_recommended_target"),
        "avg_target_realism_pct": r.get("avg_target_realism"),
        "unrealistic_target_rate": round((r.get("unrealistic_target_count") or 0) / total * 100, 1) if total else None,
        "target_hit_rate": round((r.get("target_hits") or 0) / total * 100, 1) if total else None,
        "stop_hit_rate":   round((r.get("stop_hits") or 0) / total * 100, 1) if total else None,
        "expired_rate":    round((r.get("expired") or 0) / total * 100, 1) if total else None,
        "avg_option_efficiency": r.get("avg_option_efficiency"),
        "avg_expected_move_pct": r.get("avg_expected_move"),
        "calibration_status": (
            "WELL_CALIBRATED" if (r.get("avg_target_realism") or 0) >= 70
            else "SLIGHTLY_AGGRESSIVE" if (r.get("avg_target_realism") or 0) >= 45
            else "AGGRESSIVE"
        ),
    }
