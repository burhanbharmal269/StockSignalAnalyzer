"""ExpectedMoveEngine — estimates realistic intraday option movement pre-trade.

Section 1 + 2 of Phase 24 Exit Intelligence.

Pure computation — no DB access, no side effects. Called by the scanner
immediately after a signal is accepted and an option play is found.

Outputs stored in signal_analytics (analytics only, never drives execution):
  expected_underlying_move_pct  — 1-sigma expected underlying move today
  expected_option_move_pct      — corresponding option premium move %
  expected_holding_minutes      — estimated time for move to materialize
  reach_prob_json               — P(reach 10/20/30/40/50/55% premium gain)
  recommended_target_pct        — evidence-based target suggestion (% of premium)
  recommended_stop_pct          — matching stop to maintain ≥2:1 R:R
  recommended_holding_minutes   — suggested hold duration
  target_confidence             — confidence score 0-100 in the recommendation
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
_MARKET_OPEN_HOUR   = 9
_MARKET_OPEN_MINUTE = 15
_SESSION_MINUTES    = 375   # 09:15 → 15:30

# Reach-probability levels (% option premium gain)
_REACH_LEVELS = [10, 20, 30, 40, 50, 55]

# Regime-specific multipliers for expected move and recommended target
_REGIME_MOVE_MULT: dict[str, float] = {
    "TRENDING_BULLISH":  1.25,
    "TRENDING_BEARISH":  1.25,
    "HIGH_VOLATILITY":   1.50,
    "SIDEWAYS":          0.65,
    "RANGING":           0.70,
    "LOW_VOLATILITY":    0.60,
}
_REGIME_HOLD_MINUTES: dict[str, int] = {
    "TRENDING_BULLISH":  45,
    "TRENDING_BEARISH":  45,
    "HIGH_VOLATILITY":   35,
    "SIDEWAYS":          120,
    "RANGING":           110,
    "LOW_VOLATILITY":    150,
}


@dataclass(frozen=True)
class ExpectedMoveResult:
    expected_underlying_move_pct: float
    expected_option_move_pct:     float
    expected_holding_minutes:     int
    reach_prob_json:              str           # JSON string {"10": p, "20": p, …}
    recommended_target_pct:       float         # 0-100 scale (e.g. 28.5)
    recommended_stop_pct:         float         # 0-100 scale (e.g. 13.0)
    recommended_holding_minutes:  int
    target_confidence:            float         # 0-100


class ExpectedMoveEngine:
    """Stateless service — call compute() per accepted signal."""

    def compute(
        self,
        atr_pct:         float,            # ATR as % of underlying price
        india_vix:       float | None,     # India VIX (annualised %)
        iv_percentile:   float | None,     # IV percentile 0-100
        delta:           float | None,     # absolute option delta (estimated)
        gamma:           float | None,     # option gamma (per ₹1 move)
        dte:             int | None,
        underlying_price: float,
        option_entry:    float,
        configured_target_pct: float,      # e.g. 0.55 → 55%
        configured_sl_pct:     float,      # e.g. 0.25 → 25%
        regime:          str | None = None,
        atr_ratio:       float = 1.0,      # current ATR / average ATR (expansion)
    ) -> ExpectedMoveResult:

        # ── 1. Expected underlying 1-sigma daily move ──────────────────────
        underlying_move = self._expected_underlying_move(
            atr_pct, india_vix, iv_percentile, atr_ratio
        )

        # ── 2. Map to option premium move via delta + gamma ────────────────
        d = abs(delta) if delta is not None else self._estimate_delta(atr_pct, dte)
        g = abs(gamma) if gamma is not None else self._estimate_gamma(d, underlying_price, option_entry, dte)
        entry = max(option_entry, 1.0)

        underlying_rupee_move = underlying_price * underlying_move / 100
        option_rupee_move = (d * underlying_rupee_move
                             + 0.5 * g * underlying_rupee_move ** 2)
        expected_option_move = max(0.1, option_rupee_move / entry * 100)

        # ── 3. Regime adjustment ───────────────────────────────────────────
        regime_key = (regime or "").upper().replace(" ", "_")
        mult = _REGIME_MOVE_MULT.get(regime_key, 1.0)
        underlying_move   *= mult
        expected_option_move *= mult

        # ── 4. Probability of reaching each premium level ─────────────────
        reach_probs = self._reach_probabilities(expected_option_move)

        # ── 5. Recommended target / stop ──────────────────────────────────
        rec_target = self._recommended_target(
            expected_option_move,
            configured_target_pct * 100,
            regime_key,
        )
        rec_stop = self._recommended_stop(rec_target, configured_sl_pct * 100)

        # ── 6. Holding time ────────────────────────────────────────────────
        now_ist         = datetime.now(_IST)
        tod_minutes     = (now_ist.hour - _MARKET_OPEN_HOUR) * 60 + (now_ist.minute - _MARKET_OPEN_MINUTE)
        hold_minutes    = self._expected_holding_minutes(dte, regime_key, tod_minutes, expected_option_move)

        # ── 7. Confidence score ───────────────────────────────────────────
        confidence = self._target_confidence(
            d, india_vix, iv_percentile, atr_pct,
            expected_option_move, configured_target_pct * 100,
        )

        return ExpectedMoveResult(
            expected_underlying_move_pct = round(underlying_move, 4),
            expected_option_move_pct     = round(expected_option_move, 4),
            expected_holding_minutes     = hold_minutes,
            reach_prob_json              = json.dumps(reach_probs),
            recommended_target_pct       = round(rec_target, 4),
            recommended_stop_pct         = round(rec_stop, 4),
            recommended_holding_minutes  = hold_minutes,
            target_confidence            = round(confidence, 2),
        )

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _expected_underlying_move(
        atr_pct: float,
        vix: float | None,
        iv_pct: float | None,
        atr_ratio: float,
    ) -> float:
        """Blend ATR%, VIX daily implied move, and IV percentile adjustment."""
        components, weights = [atr_pct * min(atr_ratio, 2.0)], [0.50]

        if vix and vix > 0:
            components.append(vix / math.sqrt(252))
            weights.append(0.35)

        if iv_pct is not None:
            # High IV percentile means unusually elevated volatility → amplify
            iv_factor  = 0.70 + (iv_pct / 100) * 0.80   # 0.70×–1.50×
            components.append(atr_pct * iv_factor)
            weights.append(0.15)

        total = sum(weights)
        return max(0.20, sum(c * w for c, w in zip(components, weights)) / total)

    @staticmethod
    def _estimate_delta(atr_pct: float, dte: int | None) -> float:
        """Heuristic delta when not available from option chain.
        ATM ~0.47, declining for OTM. For 29 DTE near-ATM, use 0.45."""
        if dte is not None and dte <= 3:
            return 0.45      # near expiry: selected strikes should be ATM
        return 0.42          # monthly expiry ATM estimate

    @staticmethod
    def _estimate_gamma(
        delta: float, underlying: float, entry: float, dte: int | None
    ) -> float:
        """Heuristic gamma. Increases near expiry and near ATM."""
        base_gamma = delta * (1 - delta) / max(entry, 1.0)
        if dte is not None and dte <= 7:
            base_gamma *= 2.0
        return max(0.001, base_gamma)

    @staticmethod
    def _reach_probabilities(expected_option_pct: float) -> dict:
        """P(option premium reaches level%) using half-normal approximation.

        Assumes premium move is approximately normally distributed with
        sigma = expected_option_pct. We want P(X >= level) for X ~ N(0, sigma).
        """
        sigma = max(expected_option_pct, 0.5)
        result = {}
        for level in _REACH_LEVELS:
            z    = level / (math.sqrt(2) * sigma)
            prob = 0.5 * math.erfc(z)          # P(X > level) one-sided
            result[str(level)] = round(min(0.95, max(0.01, prob)), 4)
        return result

    @staticmethod
    def _recommended_target(
        expected_pct: float,
        configured_pct: float,   # already in 0-100 scale
        regime_key: str,
    ) -> float:
        """Suggest a realistic target.

        Calibration: use 70% of 1-sigma expected move as target. If expected
        exceeds configured, cap at configured (never recommend overshooting intent).
        Floor: 10% (minimum meaningful intraday premium gain).
        """
        base = expected_pct * 0.70
        floor, cap = 10.0, configured_pct
        return max(floor, min(cap, base))

    @staticmethod
    def _recommended_stop(rec_target: float, configured_sl_pct: float) -> float:
        """Maintain ≥2:1 R:R on recommended target. Never below 8% (option noise)."""
        rr_stop = rec_target / 2.2      # 2.2:1 R:R
        return max(8.0, min(configured_sl_pct, rr_stop))

    @staticmethod
    def _expected_holding_minutes(
        dte: int | None,
        regime_key: str,
        tod_minutes: int,
        expected_option_pct: float,
    ) -> int:
        """Estimate minutes needed for the expected move to materialise."""
        base = _REGIME_HOLD_MINUTES.get(regime_key, 75)

        # Near expiry: higher gamma → faster realisation
        if dte is not None and dte <= 3:
            base = int(base * 0.65)

        # Don't recommend holding longer than remaining session
        remaining = max(30, _SESSION_MINUTES - max(0, tod_minutes))
        hold = min(base, int(remaining * 0.70))

        # If expected move is large, we can afford a shorter hold
        if expected_option_pct >= 40:
            hold = int(hold * 0.75)

        return max(20, hold)

    @staticmethod
    def _target_confidence(
        delta: float,
        vix: float | None,
        iv_pct: float | None,
        atr_pct: float,
        expected_option_pct: float,
        configured_target_pct: float,   # 0-100
    ) -> float:
        """Confidence that the recommended target is realistic (0-100)."""
        score = 50.0

        # Delta: closer to ATM = more responsive
        if delta >= 0.45:
            score += 15
        elif delta >= 0.30:
            score += 5
        else:
            score -= 20    # deep OTM: poor efficiency

        # ATR volatility support
        if atr_pct >= 2.0:
            score += 10
        elif atr_pct >= 1.0:
            score += 5
        elif atr_pct < 0.5:
            score -= 10

        # Expected vs configured target ratio
        ratio = expected_option_pct / max(configured_target_pct, 1.0)
        if ratio >= 1.0:
            score += 20
        elif ratio >= 0.70:
            score += 10
        elif ratio >= 0.50:
            score -= 5
        else:
            score -= 20

        # VIX context
        if vix is not None:
            if vix >= 20:
                score += 12
            elif vix >= 16:
                score += 6
            elif vix <= 13:
                score -= 10

        return max(5.0, min(95.0, score))
