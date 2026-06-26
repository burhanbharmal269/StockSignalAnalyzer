"""OverlayPipeline — Phase 21.2 §1, §2, §3, §11, §13, §14.

Unified overlay pipeline: applies all context overlays sequentially to an
engine-produced signal, producing a complete decision trace and attribution dict.

Pipeline order (§1):
  1. Market Context   → VIX + regime + breadth
  2. Event            → NSE expiry / macro events
  3. Regime Stability → per-symbol regime change frequency
  4. Portfolio Heat   → daily risk budget consumption (soft overlay only)
  5. Correlation      → pairwise ρ with open positions
  6. Sector Exposure  → sector concentration
  7. Execution Quality → time-of-day, conditions → grade A/B/C/D

Key design rules (§13):
  - Every overlay is individually configurable (enabled / logging_only).
  - Failed overlays are logged and SKIPPED — pipeline always completes.
  - logging_only overlays appear in the trace but do NOT adjust conf/size.

Performance (§14):
  - run() is SYNCHRONOUS — all I/O is pre-fetched by the scanner each cycle.
  - Per-symbol overhead is pure in-memory computation (< 1 ms typical).
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from core.domain.value_objects.overlay_result import (
    OverlayContext,
    OverlayPipelineResult,
    OverlayResult,
)

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)

# Severity mapping for market context levels
_LEVEL_SEVERITY: dict[str, str] = {
    "NORMAL":    "NONE",
    "CAUTION":   "LOW",
    "HIGH_RISK": "HIGH",
    "PANIC":     "CRITICAL",
}

# Severity numeric order for "worst first" comparison
_SEV_ORDER: dict[str, int] = {
    "LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3,
}


def _load_config() -> dict:
    """Load overlay_config.yaml; return defaults on failure."""
    import yaml  # type: ignore[import-untyped]
    paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "config", "overlay_config.yaml"),
        os.path.join(os.path.dirname(__file__), "../../../../config/overlay_config.yaml"),
    ]
    for p in paths:
        p = os.path.normpath(p)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as exc:
                _log.warning("overlay_config.load_failed path=%s: %s", p, exc)
    _log.debug("overlay_config not found — using built-in defaults")
    return {}


def _default_config() -> dict:
    return {
        "decision_version": "21.2",
        "overlay_version":  "1.0",
        "overlays": {
            "market_context":       {"enabled": True,  "logging_only": False},
            "event":                {"enabled": True,  "logging_only": False},
            "regime_stability":     {"enabled": True,  "logging_only": False,
                                     "stable_adj": 0.0, "transition_adj": -3.0, "unstable_adj": -5.0},
            "portfolio_heat":       {"enabled": True,  "logging_only": False,
                                     "warning_threshold_pct": 70.0, "warning_adj": -2.0,
                                     "elevated_threshold_pct": 85.0, "elevated_adj": -5.0},
            "portfolio_correlation":{"enabled": True,  "logging_only": False,
                                     "high_rho_threshold": 0.70,
                                     "adj_per_pair": -3.0, "max_adj": -7.0},
            "sector_exposure":      {"enabled": True,  "logging_only": False,
                                     "warning_threshold_pct": 40.0, "warning_adj": -2.0,
                                     "critical_threshold_pct": 60.0, "critical_adj": -5.0},
            "execution_quality":    {"enabled": True,  "logging_only": False,
                                     "grade_a_min_confidence": 75.0, "grade_d_max_confidence": 55.0,
                                     "grade_a_adj": 2.0, "grade_b_adj": 0.0,
                                     "grade_c_adj": -3.0, "grade_d_adj": -7.0},
        },
    }


class OverlayPipeline:
    """Applies all overlays to a signal, producing a complete decision trace.

    Constructed once at startup (Singleton); run() is called once per accepted
    signal in the scanner's _process_symbol.  All computation is synchronous —
    the scanner pre-fetches all required state before calling run().
    """

    DECISION_VERSION = "21.2"
    OVERLAY_VERSION  = "1.0"

    _SEQUENCE = [
        "market_context",
        "event",
        "regime_stability",
        "portfolio_heat",
        "portfolio_correlation",
        "sector_exposure",
        "execution_quality",
    ]

    def __init__(self, config: dict | None = None) -> None:
        raw = config or _load_config() or _default_config()
        # Merge loaded config with defaults so missing keys fall back
        defaults = _default_config()
        defaults.update(raw)
        for name, default_ov_cfg in defaults.get("overlays", {}).items():
            loaded = raw.get("overlays", {}).get(name, {})
            defaults["overlays"][name] = {**default_ov_cfg, **loaded}
        self._cfg = defaults
        self.DECISION_VERSION = self._cfg.get("decision_version", self.DECISION_VERSION)
        self.OVERLAY_VERSION  = self._cfg.get("overlay_version",  self.OVERLAY_VERSION)
        _log.info(
            "overlay_pipeline.init decision_version=%s overlay_version=%s",
            self.DECISION_VERSION, self.OVERLAY_VERSION,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, ctx: OverlayContext) -> OverlayPipelineResult:
        """Run all overlays and return a complete pipeline result.

        Synchronous — caller must pre-fetch all I/O into ctx before calling.
        Individual overlay failures are caught and skipped (§13 fail-safe).
        """
        conf  = ctx.engine_confidence
        size  = 1.0
        lock  = False
        overlays: list[OverlayResult] = []

        for name in self._SEQUENCE:
            ov_cfg = self._cfg.get("overlays", {}).get(name, {})
            if not ov_cfg.get("enabled", True):
                continue
            try:
                result = self._dispatch(name, ctx, conf, size, ov_cfg)
                overlays.append(result)
                if not ov_cfg.get("logging_only", False):
                    conf = result.confidence_after
                    size = result.size_after
                    if result.execution_lock:
                        lock = True
            except Exception as exc:
                _log.warning(
                    "overlay_pipeline.overlay_failed name=%s symbol=%s: %s",
                    name, ctx.symbol, exc,
                )

        conf  = max(0.0, min(100.0, conf))
        grade = self._execution_grade(overlays)
        trace = [ov.as_trace_step(i + 1) for i, ov in enumerate(overlays)]
        attribution = self._build_attribution(ctx, overlays, conf, size, grade)

        _log.debug(
            "overlay_pipeline.done symbol=%s base=%.1f final=%.1f size=%.2f grade=%s lock=%s",
            ctx.symbol, ctx.engine_confidence, conf, size, grade, lock,
        )

        return OverlayPipelineResult(
            symbol=ctx.symbol,
            base_confidence=ctx.engine_confidence,
            final_confidence=conf,
            final_size_multiplier=size,
            execution_lock=lock,
            execution_grade=grade,
            overlays=tuple(overlays),
            decision_trace=trace,
            attribution=attribution,
            decision_version=self.DECISION_VERSION,
            overlay_version=self.OVERLAY_VERSION,
        )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self, name: str, ctx: OverlayContext, conf: float, size: float, cfg: dict,
    ) -> OverlayResult:
        return {
            "market_context":        self._market_context,
            "event":                 self._event,
            "regime_stability":      self._regime_stability,
            "portfolio_heat":        self._portfolio_heat,
            "portfolio_correlation": self._portfolio_correlation,
            "sector_exposure":       self._sector_exposure,
            "execution_quality":     self._execution_quality,
        }[name](ctx, conf, size, cfg)

    # ------------------------------------------------------------------
    # Individual overlays
    # ------------------------------------------------------------------

    def _market_context(
        self, ctx: OverlayContext, conf: float, size: float, cfg: dict,
    ) -> OverlayResult:
        mc = ctx.market_ctx
        if mc is None or mc.level == "NORMAL":
            return self._no_change(
                "market_context", conf, size,
                reason="NORMAL — no market context penalty",
            )
        adj        = mc.confidence_adj
        s_mult     = mc.size_multiplier
        new_size   = size * s_mult
        execution_lock = (mc.level == "PANIC")
        return OverlayResult(
            name="market_context",
            applied=True,
            confidence_adj=adj,
            size_adj=s_mult,
            execution_lock=execution_lock,
            severity=_LEVEL_SEVERITY.get(mc.level, "HIGH"),
            reason=f"{mc.level}: {mc.reason}",
            details={
                "level":         mc.level,
                "context_score": mc.context_score,
                "vix":           mc.vix,
                "vix_rising":    mc.vix_rising,
                "nifty_regime":  mc.nifty_regime,
                "bnf_regime":    mc.bnf_regime,
            },
            confidence_before=conf,
            confidence_after=conf + adj,
            size_before=size,
            size_after=new_size,
        )

    def _event(
        self, ctx: OverlayContext, conf: float, size: float, cfg: dict,
    ) -> OverlayResult:
        events = (
            ctx.event_cache.get("ALL", []) + ctx.event_cache.get(ctx.symbol, [])
        )
        if not events:
            return self._no_change("event", conf, size, reason="no active events")

        _EV_OVERLAYS: dict[str, dict] = {
            "LOW":      {"adj": 0.0,   "size": 1.00, "lock": False},
            "MEDIUM":   {"adj": -3.0,  "size": 0.85, "lock": False},
            "HIGH":     {"adj": -7.0,  "size": 0.60, "lock": False},
            "CRITICAL": {"adj": -12.0, "size": 0.00, "lock": True},
        }

        worst = max(events, key=lambda e: _SEV_ORDER.get(e.get("severity", "LOW"), 0))
        sev   = worst.get("severity", "LOW")

        if sev == "LOW":
            return self._no_change(
                "event", conf, size,
                reason=f"LOW event: {worst.get('event_name', '')}",
                details={"event_type": worst.get("event_type"), "severity": sev},
            )

        ev_cfg   = _EV_OVERLAYS.get(sev, _EV_OVERLAYS["MEDIUM"])
        new_size = size * ev_cfg["size"]
        return OverlayResult(
            name="event",
            applied=True,
            confidence_adj=ev_cfg["adj"],
            size_adj=ev_cfg["size"],
            execution_lock=ev_cfg["lock"],
            severity=sev,
            reason=worst.get("event_name", "active event"),
            details={
                "worst_event":  worst.get("event_name"),
                "event_type":   worst.get("event_type"),
                "event_count":  len(events),
                "event_types":  list({e.get("event_type") for e in events}),
                "pause_auto":   ev_cfg["lock"],
            },
            confidence_before=conf,
            confidence_after=conf + ev_cfg["adj"],
            size_before=size,
            size_after=new_size,
        )

    def _regime_stability(
        self, ctx: OverlayContext, conf: float, size: float, cfg: dict,
    ) -> OverlayResult:
        past   = ctx.regime_history
        stable_adj     = cfg.get("stable_adj",     0.0)
        transition_adj = cfg.get("transition_adj", -3.0)
        unstable_adj   = cfg.get("unstable_adj",   -5.0)

        if len(past) < 2:
            stability, adj = "STABLE", stable_adj
        elif past[-1] != ctx.regime:
            stability, adj = "TRANSITION", transition_adj
        elif len(past) >= 3 and len(set(past[-3:])) > 1:
            stability, adj = "UNSTABLE", unstable_adj
        else:
            stability, adj = "STABLE", stable_adj

        if adj == 0.0:
            return self._no_change(
                "regime_stability", conf, size,
                reason=f"STABLE: {ctx.regime}",
                details={"stability": stability, "regime": ctx.regime, "history": list(past[-5:])},
            )

        sev = "MEDIUM" if stability == "TRANSITION" else "HIGH"
        return OverlayResult(
            name="regime_stability",
            applied=True,
            confidence_adj=adj,
            size_adj=1.0,
            execution_lock=False,
            severity=sev,
            reason=f"{stability}: {ctx.regime} changed (last 3: {list(past[-3:])})",
            details={"stability": stability, "regime": ctx.regime, "history": list(past[-5:])},
            confidence_before=conf,
            confidence_after=conf + adj,
            size_before=size,
            size_after=size,
        )

    def _portfolio_heat(
        self, ctx: OverlayContext, conf: float, size: float, cfg: dict,
    ) -> OverlayResult:
        heat  = ctx.portfolio.heat_pct
        w_thr = cfg.get("warning_threshold_pct",  70.0)
        e_thr = cfg.get("elevated_threshold_pct", 85.0)
        w_adj = cfg.get("warning_adj",             -2.0)
        e_adj = cfg.get("elevated_adj",            -5.0)

        if heat >= e_thr:
            adj, sev = e_adj, "HIGH"
            reason = f"portfolio heat {heat:.1f}% — elevated risk budget usage"
        elif heat >= w_thr:
            adj, sev = w_adj, "MEDIUM"
            reason = f"portfolio heat {heat:.1f}% — warning threshold breached"
        else:
            return self._no_change(
                "portfolio_heat", conf, size,
                reason=f"heat={heat:.1f}% NORMAL",
                details={"heat_pct": heat},
            )

        return OverlayResult(
            name="portfolio_heat",
            applied=True,
            confidence_adj=adj,
            size_adj=1.0,
            execution_lock=False,   # hard gate is in PipelineEventHandler
            severity=sev,
            reason=reason,
            details={"heat_pct": heat},
            confidence_before=conf,
            confidence_after=conf + adj,
            size_before=size,
            size_after=size,
        )

    def _portfolio_correlation(
        self, ctx: OverlayContext, conf: float, size: float, cfg: dict,
    ) -> OverlayResult:
        corr_matrix  = ctx.portfolio.correlation_matrix
        open_symbols = ctx.portfolio.open_symbols
        high_rho     = cfg.get("high_rho_threshold", 0.70)
        adj_per_pair = cfg.get("adj_per_pair",        -3.0)
        max_adj      = cfg.get("max_adj",             -7.0)

        if not corr_matrix or not open_symbols:
            return self._no_change(
                "portfolio_correlation", conf, size,
                reason="no open positions or correlation data unavailable",
            )

        sym_row = corr_matrix.get(ctx.symbol, {})
        high_pairs: list[dict] = []
        for open_sym in open_symbols:
            if open_sym == ctx.symbol:
                continue
            rho = sym_row.get(open_sym)
            if rho is None:
                rho = corr_matrix.get(open_sym, {}).get(ctx.symbol)
            if rho is not None and abs(float(rho)) >= high_rho:
                high_pairs.append({"symbol": open_sym, "rho": round(float(rho), 4)})

        if not high_pairs:
            return self._no_change(
                "portfolio_correlation", conf, size,
                reason="no high-correlation open positions",
            )

        adj = max(max_adj, adj_per_pair * len(high_pairs))
        sev = "HIGH" if len(high_pairs) > 1 else "MEDIUM"
        return OverlayResult(
            name="portfolio_correlation",
            applied=True,
            confidence_adj=adj,
            size_adj=1.0,
            execution_lock=False,
            severity=sev,
            reason=f"{len(high_pairs)} high-ρ open position(s): {[p['symbol'] for p in high_pairs]}",
            details={"correlated_pairs": high_pairs, "pair_count": len(high_pairs), "rho_threshold": high_rho},
            confidence_before=conf,
            confidence_after=conf + adj,
            size_before=size,
            size_after=size,
        )

    def _sector_exposure(
        self, ctx: OverlayContext, conf: float, size: float, cfg: dict,
    ) -> OverlayResult:
        if not ctx.sector:
            return self._no_change(
                "sector_exposure", conf, size, reason="sector unknown — skipped",
            )
        w_thr = cfg.get("warning_threshold_pct",  40.0)
        c_thr = cfg.get("critical_threshold_pct", 60.0)
        w_adj = cfg.get("warning_adj",             -2.0)
        c_adj = cfg.get("critical_adj",            -5.0)

        pct = ctx.portfolio.sector_exposure.get(ctx.sector, 0.0)

        if pct >= c_thr:
            adj, sev = c_adj, "HIGH"
            reason = f"sector {ctx.sector} CRITICAL: {pct:.1f}% of active positions"
        elif pct >= w_thr:
            adj, sev = w_adj, "MEDIUM"
            reason = f"sector {ctx.sector} WARNING: {pct:.1f}% of active positions"
        else:
            return self._no_change(
                "sector_exposure", conf, size,
                reason=f"sector {ctx.sector}: {pct:.1f}% — NORMAL",
                details={"sector": ctx.sector, "sector_pct": pct},
            )

        return OverlayResult(
            name="sector_exposure",
            applied=True,
            confidence_adj=adj,
            size_adj=1.0,
            execution_lock=False,
            severity=sev,
            reason=reason,
            details={"sector": ctx.sector, "sector_pct": pct},
            confidence_before=conf,
            confidence_after=conf + adj,
            size_before=size,
            size_after=size,
        )

    def _execution_quality(
        self, ctx: OverlayContext, conf: float, size: float, cfg: dict,
    ) -> OverlayResult:
        a_min_conf = cfg.get("grade_a_min_confidence", 75.0)
        d_max_conf = cfg.get("grade_d_max_confidence", 55.0)
        a_adj = cfg.get("grade_a_adj",  2.0)
        b_adj = cfg.get("grade_b_adj",  0.0)
        c_adj = cfg.get("grade_c_adj", -3.0)
        d_adj = cfg.get("grade_d_adj", -7.0)

        mc_level = ctx.market_ctx.level if ctx.market_ctx else "NORMAL"

        all_events  = ctx.event_cache.get("ALL", []) + ctx.event_cache.get(ctx.symbol, [])
        worst_ev_sev = max(
            (_SEV_ORDER.get(e.get("severity", "LOW"), 0) for e in all_events),
            default=0,
        )
        has_event = bool(all_events)

        h = ctx.ist_time.hour
        early  = 9 <= h < 11    # 09:00–10:59 IST
        late   = h >= 14         # 14:00+ IST

        past = ctx.regime_history
        if len(past) < 2:
            stability = "STABLE"
        elif past[-1] != ctx.regime:
            stability = "TRANSITION"
        elif len(past) >= 3 and len(set(past[-3:])) > 1:
            stability = "UNSTABLE"
        else:
            stability = "STABLE"

        # Grade D: worst — PANIC or CRITICAL event or very poor confidence
        if mc_level == "PANIC" or worst_ev_sev >= 3 or conf < d_max_conf:
            grade, adj = "D", d_adj
        # Grade A: premium — high confidence, clean context, early session, stable
        elif (
            conf >= a_min_conf
            and mc_level == "NORMAL"
            and not has_event
            and early
            and stability == "STABLE"
        ):
            grade, adj = "A", a_adj
        # Grade C: degraded — high-risk context, event, unstable regime, late session
        elif mc_level == "HIGH_RISK" or (has_event and worst_ev_sev >= 2) or stability == "UNSTABLE" or late:
            grade, adj = "C", c_adj
        # Grade B: standard
        else:
            grade, adj = "B", b_adj

        session = "early" if early else "late" if late else "mid"
        reason  = (
            f"grade={grade} context={mc_level} event_sev={worst_ev_sev} "
            f"session={session} regime={stability}"
        )
        details = {
            "grade":         grade,
            "mc_level":      mc_level,
            "has_event":     has_event,
            "worst_ev_sev":  worst_ev_sev,
            "session":       session,
            "regime_stab":   stability,
        }

        if adj == 0.0:
            return self._no_change("execution_quality", conf, size, reason=reason, details=details)

        sev_map = {"A": "NONE", "B": "NONE", "C": "MEDIUM", "D": "HIGH"}
        return OverlayResult(
            name="execution_quality",
            applied=(adj != 0.0),
            confidence_adj=adj,
            size_adj=1.0,
            execution_lock=False,
            severity=sev_map.get(grade, "NONE"),
            reason=reason,
            details=details,
            confidence_before=conf,
            confidence_after=conf + adj,
            size_before=size,
            size_after=size,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _no_change(
        name: str, conf: float, size: float,
        reason: str = "", details: dict | None = None,
    ) -> OverlayResult:
        return OverlayResult(
            name=name,
            applied=False,
            confidence_adj=0.0,
            size_adj=1.0,
            execution_lock=False,
            severity="NONE",
            reason=reason,
            details=details or {},
            confidence_before=conf,
            confidence_after=conf,
            size_before=size,
            size_after=size,
        )

    @staticmethod
    def _execution_grade(overlays: list[OverlayResult]) -> str:
        """Extract grade from execution_quality overlay result."""
        for ov in overlays:
            if ov.name == "execution_quality":
                return ov.details.get("grade", "B")
        return "B"

    def _build_attribution(
        self,
        ctx: OverlayContext,
        overlays: list[OverlayResult],
        final_conf: float,
        final_size: float,
        grade: str,
    ) -> dict:
        """Build the flat attribution dict stored in signal_analytics."""
        def _get_ov(name: str) -> OverlayResult | None:
            return next((o for o in overlays if o.name == name), None)

        mc  = _get_ov("market_context")
        ev  = _get_ov("event")
        reg = _get_ov("regime_stability")

        ev_json = json.dumps(ev.details) if ev and ev.applied else None

        portfolio_adj = sum(
            o.confidence_adj for o in overlays
            if o.name in ("portfolio_heat", "portfolio_correlation", "sector_exposure")
        )

        trace_doc = {
            "version":              self.DECISION_VERSION,
            "base_confidence":      ctx.engine_confidence,
            "overlays":             [o.as_trace_step(i + 1) for i, o in enumerate(overlays)],
            "final_confidence":     final_conf,
            "final_size_multiplier": final_size,
            "execution_grade":      grade,
        }

        return {
            "engine_final":             ctx.engine_confidence,
            "market_context":           mc.details.get("level", "NORMAL") if mc else "NORMAL",
            "market_context_adj":       mc.confidence_adj if mc else 0.0,
            "regime_stability":         reg.details.get("stability", "STABLE") if reg else "STABLE",
            "regime_stability_adj":     reg.confidence_adj if reg else 0.0,
            "event_adj":                ev.confidence_adj if ev else 0.0,
            "event_overlay_json":       ev_json,
            "portfolio_adj":            portfolio_adj,
            "overlay_confidence":       final_conf,
            "size_multiplier":          final_size,
            "execution_grade":          grade,
            "decision_trace_json":      json.dumps(trace_doc),
            "decision_version":         self.DECISION_VERSION,
            "overlay_version":          self.OVERLAY_VERSION,
        }
