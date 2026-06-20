"""PortfolioIntelligenceService — Phase 19 portfolio risk monitoring.

Four monitoring sub-systems (read-only, no execution gating):
  Section 1: Correlation Engine — pairwise symbol correlation from P&L returns.
  Section 2: Sector Exposure Control — warning >40%, critical >60% per sector.
  Section 3: Portfolio Heat — active position risk vs daily budget.
  Section 4: Risk of Ruin Monitor — drawdown vs historical average.

All methods are pure analytics. None gate order execution.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Correlation thresholds
_CORR_HIGH   = 0.70    # |r| >= 0.70 → HIGH_CORRELATION
_CORR_MEDIUM = 0.40    # |r| >= 0.40 → MEDIUM_CORRELATION

# Sector exposure limits
_SECTOR_WARNING_PCT  = 40.0
_SECTOR_CRITICAL_PCT = 60.0

# Portfolio heat limits
_HEAT_WARNING_PCT  = 70.0    # >70% of daily risk budget used → WARNING
_HEAT_CRITICAL_PCT = 100.0   # >100% → CRITICAL (budget exceeded)

# Drawdown alert
_DRAWDOWN_ABNORMAL_MULTIPLIER = 1.5   # current drawdown > 1.5× historical avg


class PortfolioIntelligenceService:
    """Portfolio-level risk intelligence — read-only analytics."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        daily_risk_budget_pct: float = 1.0,   # daily max risk as % of capital
        account_capital: float = 200_000.0,
    ) -> None:
        self._sf              = session_factory
        self._daily_budget    = daily_risk_budget_pct
        self._capital         = account_capital

    # ── Section 1: Correlation Engine ─────────────────────────────────────────

    async def get_correlation_report(self, lookback_days: int = 30) -> dict:
        """Compute pairwise signal P&L correlation between active symbols.

        Uses pnl_pct (or current_return_pct) from completed trades.
        Each symbol's returns form a time-series; correlation is Pearson r.
        Flags symbol pairs with |r| >= 0.70 as HIGH_CORRELATION.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          ticker,
                          DATE(created_at AT TIME ZONE 'UTC') AS trade_date,
                          COALESCE(pnl_pct, current_return_pct, 0) AS ret
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        ORDER BY ticker, trade_date
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("portfolio.correlation_error: %s", exc)
            return {"error": str(exc), "pairs": [], "alert": None}

        # Build per-symbol daily return series
        from collections import defaultdict
        symbol_daily: dict[str, dict[str, float]] = defaultdict(dict)
        for ticker, trade_date, ret in rows:
            # Accumulate returns for same symbol+date
            d = str(trade_date)
            symbol_daily[ticker][d] = symbol_daily[ticker].get(d, 0.0) + float(ret or 0)

        symbols = sorted(symbol_daily.keys())
        if len(symbols) < 2:
            return {
                "status":       "INSUFFICIENT_DATA",
                "symbol_count": len(symbols),
                "min_required": 2,
                "pairs":        [],
                "alert":        None,
            }

        # All unique dates across all symbols
        all_dates = sorted({d for s in symbol_daily.values() for d in s})

        # Build vectors (use 0 for missing dates)
        def _vec(sym: str) -> list[float]:
            return [symbol_daily[sym].get(d, 0.0) for d in all_dates]

        # Pearson r for all pairs
        pairs = []
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                s1, s2 = symbols[i], symbols[j]
                v1, v2 = _vec(s1), _vec(s2)
                r_val = _pearson(v1, v2)
                if r_val is None:
                    continue
                level = (
                    "HIGH_CORRELATION"   if abs(r_val) >= _CORR_HIGH   else
                    "MEDIUM_CORRELATION" if abs(r_val) >= _CORR_MEDIUM else
                    "LOW_CORRELATION"
                )
                pairs.append({
                    "symbol_a":    s1,
                    "symbol_b":    s2,
                    "correlation": round(r_val, 4),
                    "level":       level,
                    "direction":   "POSITIVE" if r_val >= 0 else "NEGATIVE",
                })

        high_pairs = [p for p in pairs if p["level"] == "HIGH_CORRELATION"]
        alert = "PORTFOLIO_CORRELATION_RISK" if len(high_pairs) >= 3 else None

        if alert:
            _log.warning(
                "portfolio.PORTFOLIO_CORRELATION_RISK high_pairs=%d",
                len(high_pairs),
            )

        return {
            "lookback_days":  lookback_days,
            "symbol_count":   len(symbols),
            "date_count":     len(all_dates),
            "pairs":          sorted(pairs, key=lambda p: -abs(p["correlation"])),
            "high_pairs":     high_pairs,
            "alert":          alert,
            "thresholds":     {"high": _CORR_HIGH, "medium": _CORR_MEDIUM},
        }

    # ── Section 2: Sector Exposure Control ────────────────────────────────────

    async def get_sector_exposure(self) -> dict:
        """Compute current sector exposure as % of open positions.

        Warning  > 40% in any sector.
        Critical > 60% in any sector.
        """
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT sector, COUNT(*) AS open_count
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NULL
                          AND created_at >= :today
                        GROUP BY sector
                        ORDER BY open_count DESC
                    """),
                    {"today": today_start},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("portfolio.sector_exposure_error: %s", exc)
            return {"error": str(exc), "sectors": [], "alert": None}

        total = sum(int(row[1]) for row in rows) or 1
        sectors = []
        alerts = []

        for row in rows:
            sector_name  = row[0] or "UNKNOWN"
            count        = int(row[1])
            exposure_pct = round(count / total * 100, 2)
            status = (
                "CRITICAL" if exposure_pct > _SECTOR_CRITICAL_PCT else
                "WARNING"  if exposure_pct > _SECTOR_WARNING_PCT  else
                "NORMAL"
            )
            if status in ("WARNING", "CRITICAL"):
                alerts.append({"sector": sector_name, "pct": exposure_pct, "status": status})
            sectors.append({
                "sector":       sector_name,
                "open_signals": count,
                "exposure_pct": exposure_pct,
                "status":       status,
            })

        if alerts:
            _log.warning("portfolio.sector_exposure_alert sectors=%s", alerts)

        return {
            "total_open_signals": total,
            "sectors":            sectors,
            "alerts":             alerts,
            "thresholds":         {"warning_pct": _SECTOR_WARNING_PCT, "critical_pct": _SECTOR_CRITICAL_PCT},
        }

    # ── Section 3: Portfolio Heat ──────────────────────────────────────────────

    async def get_portfolio_heat(self) -> dict:
        """Compute portfolio heat: sum of active position risks vs daily budget.

        Risk per position approximated as effective_risk_pct (0.20% avg proxy).
        WARNING when > 70% of daily budget used.
        CRITICAL when > 100% of daily budget used (budget exceeded).
        """
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT COUNT(*) AS open_positions,
                               SUM(CASE WHEN outcome = 'WIN'  THEN 1 ELSE 0 END) AS wins_today,
                               SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses_today,
                               COUNT(CASE WHEN outcome IS NOT NULL THEN 1 END)    AS closed_today
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND created_at >= :today
                    """),
                    {"today": today_start},
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("portfolio.heat_error: %s", exc)
            return {"error": str(exc)}

        open_positions = int(row[0] or 0)
        # Approximate risk per position: use average 0.20% risk (mid-tier)
        # This is a conservative proxy; actual risk tracked per position when
        # DynamicRiskBudgetService stores risk allocation per signal.
        avg_risk_per_position = 0.20
        used_pct   = open_positions * avg_risk_per_position
        budget_pct = self._daily_budget
        heat_pct   = (used_pct / budget_pct * 100) if budget_pct > 0 else 0.0

        status = (
            "CRITICAL" if heat_pct > _HEAT_CRITICAL_PCT else
            "WARNING"  if heat_pct > _HEAT_WARNING_PCT  else
            "NORMAL"
        )

        if status == "CRITICAL":
            _log.warning(
                "portfolio.CRITICAL_HEAT heat_pct=%.1f%% open=%d",
                heat_pct, open_positions,
            )
        elif status == "WARNING":
            _log.warning(
                "portfolio.WARNING_HEAT heat_pct=%.1f%% open=%d",
                heat_pct, open_positions,
            )

        return {
            "open_positions":       open_positions,
            "used_risk_pct":        round(used_pct, 4),
            "daily_budget_pct":     round(budget_pct, 4),
            "heat_pct":             round(heat_pct, 2),
            "status":               status,
            "wins_today":           int(row[1] or 0),
            "losses_today":         int(row[2] or 0),
            "closed_today":         int(row[3] or 0),
            "thresholds":           {"warning": _HEAT_WARNING_PCT, "critical": _HEAT_CRITICAL_PCT},
        }

    # ── Section 4: Risk of Ruin Monitor ───────────────────────────────────────

    async def get_risk_of_ruin(self, lookback_days: int = 60) -> dict:
        """Monitor drawdown vs historical average.

        ABNORMAL_DRAWDOWN when current rolling 5-day drawdown exceeds
        1.5× the historical average drawdown across the lookback window.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          DATE(created_at AT TIME ZONE 'UTC')  AS trade_date,
                          SUM(COALESCE(pnl_pct, current_return_pct, 0)) AS daily_pnl
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY trade_date
                        ORDER BY trade_date
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("portfolio.ror_error: %s", exc)
            return {"error": str(exc)}

        if len(rows) < 5:
            return {
                "status":      "INSUFFICIENT_DATA",
                "days_needed": 5,
                "days_have":   len(rows),
                "alert":       None,
            }

        # Daily P&L series
        daily_pnl = [float(row[1] or 0) for row in rows]

        # Compute rolling drawdown (5-day window)
        def _rolling_drawdown(pnl_series: list[float], window: int = 5) -> list[float]:
            drawdowns = []
            for i in range(len(pnl_series)):
                start  = max(0, i - window + 1)
                subset = pnl_series[start : i + 1]
                peak   = max(cumsum := _cumulative_sum(subset))
                trough = min(cumsum)
                dd = max(0.0, peak - trough)
                drawdowns.append(dd)
            return drawdowns

        drawdowns = _rolling_drawdown(daily_pnl, window=5)

        avg_drawdown = sum(drawdowns[:-5]) / len(drawdowns[:-5]) if len(drawdowns) > 5 else sum(drawdowns) / len(drawdowns)
        current_drawdown = drawdowns[-1] if drawdowns else 0.0
        threshold = avg_drawdown * _DRAWDOWN_ABNORMAL_MULTIPLIER

        alert = None
        if avg_drawdown > 0 and current_drawdown > threshold:
            alert = "ABNORMAL_DRAWDOWN"
            _log.warning(
                "portfolio.ABNORMAL_DRAWDOWN current=%.4f avg=%.4f threshold=%.4f",
                current_drawdown, avg_drawdown, threshold,
            )

        status = (
            "CRITICAL" if alert == "ABNORMAL_DRAWDOWN" and current_drawdown > avg_drawdown * 2.0 else
            "WARNING"  if alert == "ABNORMAL_DRAWDOWN" else
            "NORMAL"
        )

        return {
            "lookback_days":       lookback_days,
            "days_in_sample":      len(rows),
            "current_drawdown":    round(current_drawdown, 6),
            "avg_historical_drawdown": round(avg_drawdown, 6),
            "abnormal_threshold":  round(threshold, 6),
            "multiplier":          _DRAWDOWN_ABNORMAL_MULTIPLIER,
            "status":              status,
            "alert":               alert,
        }

    # ── Phase 19 Section 8 — Success Criteria ──────────────────────────────────

    async def get_success_criteria_status(self, lookback_days: int = 30) -> dict:
        """Check 11 institutional stability conditions.

        SC1  — Evidence base established (≥100 completed live trades)
        SC2  — System net profitable (overall PF > 1.0)
        SC3  — Minimum directional accuracy (overall win rate ≥ 45%)
        SC4  — Positive expectancy (avg return per trade > 0)
        SC5  — Score monotonicity (high-score bucket WR ≥ low-score bucket WR)
        SC6  — Signal data quality (avg DQ score ≥ 80)
        SC7  — Margin sizing correct (zero INSUFFICIENT_MARGIN in last 30 signals)
        SC8  — Portfolio heat in bounds (not WARNING or CRITICAL)
        SC9  — No abnormal drawdown (current rolling DD ≤ 1.5× historical avg)
        SC10 — Consecutive loss days ≤ 3 within the lookback window
        SC11 — Correlation risk absent (no PORTFOLIO_CORRELATION_RISK alert)

        Returns dict with per-condition pass/fail, overall status, and counts.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

        # ── SC1-SC7 and SC10 from one batch DB query set ───────────────────────
        checks: dict[str, dict] = {}
        try:
            async with self._sf() as db:
                # Overall performance metrics (SC1-SC4, SC6)
                r_perf = await db.execute(
                    text("""
                        SELECT
                          COUNT(*)                                                         AS completed,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 2)  AS win_rate,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit  THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          , 3)                                                             AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct, current_return_pct))*100, 6)       AS expectancy,
                          ROUND(AVG(data_quality_score), 1)                              AS avg_dq
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                    """),
                )
                perf = r_perf.fetchone()

                # Score monotonicity — bucket WR (SC5)
                r_mono = await db.execute(
                    text("""
                        SELECT
                          CASE
                            WHEN adjusted_score >= 70 THEN 'HIGH'
                            WHEN adjusted_score >= 60 THEN 'MED'
                            ELSE 'LOW'
                          END                                                             AS bucket,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 2) AS bucket_wr,
                          COUNT(*)                                                        AS bucket_n
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND adjusted_score IS NOT NULL
                        GROUP BY bucket
                    """),
                )
                mono_rows = {row[0]: {"wr": float(row[1] or 0), "n": int(row[2] or 0)}
                             for row in r_mono.fetchall()}

                # INSUFFICIENT_MARGIN in last 30 signals (SC7)
                r_margin = await db.execute(
                    text("""
                        SELECT COUNT(*)
                        FROM signal_analytics
                        WHERE rejection_code = 'INSUFFICIENT_MARGIN'
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                margin_failures = int((r_margin.fetchone() or [0])[0])

                # Consecutive loss days (SC10)
                r_daily = await db.execute(
                    text("""
                        SELECT
                          DATE(created_at AT TIME ZONE 'UTC') AS trade_date,
                          SUM(CASE WHEN target_hit THEN 1 ELSE 0 END) AS wins,
                          SUM(CASE WHEN stop_hit  THEN 1 ELSE 0 END) AS losses
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY trade_date
                        ORDER BY trade_date
                    """),
                    {"cutoff": cutoff},
                )
                daily_rows = r_daily.fetchall()

        except Exception as exc:
            _log.warning("portfolio.success_criteria_error: %s", exc)
            return {"error": str(exc)}

        # ── SC1: evidence base ─────────────────────────────────────────────────
        completed = int(perf[0] or 0)
        checks["SC1_evidence_base"] = {
            "name":      "Evidence base established",
            "pass":      completed >= 100,
            "value":     completed,
            "threshold": ">= 100 completed live trades",
            "action":    None if completed >= 100 else
                         f"Need {100 - completed} more completed live trades.",
        }

        # ── SC2: net profitable ────────────────────────────────────────────────
        pf = float(perf[2] or 0)
        checks["SC2_net_profitable"] = {
            "name":      "System net profitable (PF > 1.0)",
            "pass":      pf > 1.0,
            "value":     round(pf, 3),
            "threshold": "> 1.0",
            "action":    None if pf > 1.0 else
                         "Profit factor ≤ 1.0. System is not net profitable — do not scale capital.",
        }

        # ── SC3: minimum win rate ──────────────────────────────────────────────
        wr = float(perf[1] or 0)
        checks["SC3_win_rate"] = {
            "name":      "Win rate ≥ 45%",
            "pass":      wr >= 45.0,
            "value":     round(wr, 2),
            "threshold": ">= 45%",
            "action":    None if wr >= 45.0 else
                         f"Win rate {wr:.1f}% below 45%.",
        }

        # ── SC4: positive expectancy ───────────────────────────────────────────
        exp = float(perf[3] or 0)
        checks["SC4_expectancy"] = {
            "name":      "Positive expectancy",
            "pass":      exp > 0,
            "value":     round(exp, 6),
            "threshold": "> 0",
            "action":    None if exp > 0 else
                         "Expectancy ≤ 0. Average trade is a loser.",
        }

        # ── SC5: score monotonicity ────────────────────────────────────────────
        high = mono_rows.get("HIGH", {})
        med  = mono_rows.get("MED",  {})
        mono_ok = (
            high.get("n", 0) >= 10 and med.get("n", 0) >= 10 and
            high["wr"] >= med["wr"] - 2.0  # allow 2pp tolerance
        )
        checks["SC5_score_monotonicity"] = {
            "name":      "Score monotonicity (high-score bucket WR ≥ mid-score bucket WR)",
            "pass":      mono_ok,
            "value": {
                "high_bucket_wr": high.get("wr", "N/A"),
                "med_bucket_wr":  med.get("wr", "N/A"),
                "high_n":         high.get("n", 0),
                "med_n":          med.get("n", 0),
            },
            "threshold": "HIGH bucket WR within 2pp of MED bucket WR or better",
            "action": None if mono_ok else
                      "Score calibration broken: lower-score signals outperforming higher-score signals.",
        }

        # ── SC6: data quality ──────────────────────────────────────────────────
        avg_dq = float(perf[4]) if perf[4] is not None else None
        dq_ok  = avg_dq is not None and avg_dq >= 80.0
        checks["SC6_data_quality"] = {
            "name":      "Average data quality ≥ 80",
            "pass":      dq_ok,
            "value":     avg_dq,
            "threshold": ">= 80",
            "action":    None if dq_ok else
                         (f"Avg DQ {avg_dq:.1f} below 80." if avg_dq is not None else "DQ scores unavailable."),
        }

        # ── SC7: no margin failures ────────────────────────────────────────────
        checks["SC7_no_margin_failures"] = {
            "name":      "No INSUFFICIENT_MARGIN rejections in lookback window",
            "pass":      margin_failures == 0,
            "value":     margin_failures,
            "threshold": "0",
            "action":    None if margin_failures == 0 else
                         f"{margin_failures} INSUFFICIENT_MARGIN rejections. Review margin config or capital allocation.",
        }

        # ── SC8: portfolio heat (live call) ────────────────────────────────────
        heat = await self.get_portfolio_heat()
        heat_ok = heat.get("status") not in ("WARNING", "CRITICAL")
        checks["SC8_portfolio_heat"] = {
            "name":      "Portfolio heat in bounds",
            "pass":      heat_ok,
            "value":     heat.get("status", "UNKNOWN"),
            "threshold": "Not WARNING or CRITICAL",
            "action":    None if heat_ok else
                         f"Portfolio heat is {heat.get('status')}. Reduce open positions.",
        }

        # ── SC9: no abnormal drawdown (live call) ──────────────────────────────
        ror = await self.get_risk_of_ruin(lookback_days=60)
        dd_ok = ror.get("alert") != "ABNORMAL_DRAWDOWN"
        checks["SC9_drawdown"] = {
            "name":      "No abnormal drawdown",
            "pass":      dd_ok,
            "value":     ror.get("status", "UNKNOWN"),
            "threshold": "Current rolling drawdown ≤ 1.5× historical average",
            "action":    None if dd_ok else
                         "ABNORMAL_DRAWDOWN detected. Review recent loss sequence before adding new positions.",
        }

        # ── SC10: consecutive loss days ────────────────────────────────────────
        max_consec = 0
        cur_consec = 0
        for row in daily_rows:
            wins   = int(row[1] or 0)
            losses = int(row[2] or 0)
            if losses > wins:
                cur_consec += 1
                max_consec  = max(max_consec, cur_consec)
            else:
                cur_consec = 0
        consec_ok = max_consec <= 3
        checks["SC10_consecutive_losses"] = {
            "name":      "Max consecutive loss days ≤ 3",
            "pass":      consec_ok,
            "value":     max_consec,
            "threshold": "<= 3",
            "action":    None if consec_ok else
                         f"{max_consec} consecutive loss days detected. Consider pausing until pattern resolves.",
        }

        # ── SC11: correlation risk (live call) ────────────────────────────────
        corr = await self.get_correlation_report(lookback_days=30)
        corr_ok = corr.get("alert") != "PORTFOLIO_CORRELATION_RISK"
        checks["SC11_correlation_risk"] = {
            "name":      "No portfolio correlation risk",
            "pass":      corr_ok,
            "value":     corr.get("alert", "NONE"),
            "threshold": "No PORTFOLIO_CORRELATION_RISK alert",
            "action":    None if corr_ok else
                         "≥3 highly correlated symbol pairs. Positions are clustered — diversify symbol selection.",
        }

        # ── Aggregate ─────────────────────────────────────────────────────────
        passed  = sum(1 for c in checks.values() if c["pass"])
        failed  = len(checks) - passed
        all_ok  = failed == 0
        status  = "INSTITUTIONAL_STABLE" if all_ok else (
            "NEEDS_ATTENTION" if failed <= 3 else "NOT_READY"
        )

        failed_names = [k for k, v in checks.items() if not v["pass"]]
        if not all_ok:
            _log.warning(
                "portfolio.success_criteria failed=%d checks=%s",
                failed, failed_names,
            )

        return {
            "status":          status,
            "passed":          passed,
            "failed":          failed,
            "total":           len(checks),
            "all_conditions_met": all_ok,
            "failed_conditions": failed_names,
            "checks":          checks,
            "evaluated_at":    datetime.now(UTC).isoformat(),
            "interpretation": (
                "All 11 institutional stability conditions met. System is operating at institutional standard."
                if all_ok else
                f"{failed} of 11 conditions not met. Address failed conditions before capital scaling."
            ),
        }

    # ── Combined dashboard ──────────────────────────────────────────────────────

    async def get_portfolio_dashboard(self) -> dict:
        """Single call returning all Phase 19 portfolio intelligence panels."""
        import asyncio
        correlation, sector, heat, ruin, sc = await asyncio.gather(
            self.get_correlation_report(lookback_days=30),
            self.get_sector_exposure(),
            self.get_portfolio_heat(),
            self.get_risk_of_ruin(lookback_days=60),
            self.get_success_criteria_status(lookback_days=30),
            return_exceptions=True,
        )
        # Coerce any exceptions to error dicts
        for name, val in [("correlation", correlation), ("sector", sector),
                           ("heat", heat), ("ruin", ruin), ("sc", sc)]:
            if isinstance(val, Exception):
                _log.warning("portfolio.dashboard_%s_error: %s", name, val)

        correlation = correlation if not isinstance(correlation, Exception) else {"error": str(correlation)}
        sector      = sector      if not isinstance(sector,      Exception) else {"error": str(sector)}
        heat        = heat        if not isinstance(heat,        Exception) else {"error": str(heat)}
        ruin        = ruin        if not isinstance(ruin,        Exception) else {"error": str(ruin)}
        sc          = sc          if not isinstance(sc,          Exception) else {"error": str(sc)}

        # Aggregate alert level
        all_alerts = [
            a for a in [
                correlation.get("alert"),
                heat.get("status") if heat.get("status") in ("WARNING", "CRITICAL") else None,
                ruin.get("alert"),
                "SC_FAILURE" if not sc.get("all_conditions_met") else None,
            ] + [a.get("status") for a in (sector.get("alerts") or [])]
            if a is not None
        ]
        has_critical = any(a == "CRITICAL" for a in all_alerts)
        has_warning  = any(a in ("WARNING", "ABNORMAL_DRAWDOWN", "PORTFOLIO_CORRELATION_RISK",
                                  "SC_FAILURE") for a in all_alerts)

        overall = "CRITICAL" if has_critical else ("WARNING" if has_warning else "HEALTHY")

        return {
            "overall_status":    overall,
            "evaluated_at":      datetime.now(UTC).isoformat(),
            "correlation":       correlation,
            "sector_exposure":   sector,
            "portfolio_heat":    heat,
            "risk_of_ruin":      ruin,
            "success_criteria":  sc,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pearson(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation coefficient. Returns None when std=0."""
    n = len(x)
    if n < 3:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx  = (sum((v - mx) ** 2 for v in x) / n) ** 0.5
    sy  = (sum((v - my) ** 2 for v in y) / n) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return num / (n * sx * sy)


def _cumulative_sum(values: list[float]) -> list[float]:
    """Running sum of a list."""
    result, s = [], 0.0
    for v in values:
        s += v
        result.append(s)
    return result
