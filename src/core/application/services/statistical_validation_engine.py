"""StatisticalValidationEngine — Phase 25 Section 4.

Pure computation. No DB access, no side effects.

Calculates:
  - Wilson confidence interval for each group's win rate
  - Two-proportion Z-test
  - P-value
  - Expected improvement
  - Recommendation: DEPLOY | CONTINUE | REJECT | INSUFFICIENT_DATA
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.application.services.platform_constants import (
    GOVERNANCE_MIN_P_VALUE,
    GOVERNANCE_MIN_TRADES,
    GOVERNANCE_MIN_CONFIDENCE,
)

_Z_95 = 1.96     # 95% CI z-score
_Z_99 = 2.576    # 99% CI z-score


@dataclass(frozen=True)
class GroupStats:
    trades:      int
    wins:        int
    total_pnl:   float = 0.0
    avg_mfe:     float | None = None
    avg_mae:     float | None = None
    avg_holding: float | None = None   # minutes


@dataclass(frozen=True)
class WilsonInterval:
    lower: float
    upper: float
    center: float


@dataclass(frozen=True)
class ValidationResult:
    control_n:               int
    treatment_n:             int
    control_win_rate:        float
    treatment_win_rate:      float
    control_wilson:          WilsonInterval
    treatment_wilson:        WilsonInterval
    improvement_pct:         float          # (treatment - control) / control * 100
    z_score:                 float
    p_value:                 float
    is_significant:          bool
    confidence_level:        float          # 0-1
    recommendation:          str            # DEPLOY|CONTINUE|REJECT|INSUFFICIENT_DATA
    recommendation_reason:   str
    expected_improvement_pct: float
    risk_assessment:         str            # LOW|MEDIUM|HIGH


class StatisticalValidationEngine:
    """Stateless — call validate() per experiment snapshot."""

    def validate(
        self,
        control:   GroupStats,
        treatment: GroupStats,
        minimum_sample_size: int = GOVERNANCE_MIN_TRADES,
    ) -> ValidationResult:

        # ── Insufficient data gate ────────────────────────────────────────────
        if control.trades < minimum_sample_size or treatment.trades < minimum_sample_size:
            missing = max(0, minimum_sample_size - min(control.trades, treatment.trades))
            return self._insufficient(
                control, treatment,
                reason=f"Need {missing} more trades in the smaller group (minimum {minimum_sample_size})"
            )

        ctrl_wr  = control.wins  / control.trades  if control.trades  > 0 else 0.0
        trt_wr   = treatment.wins / treatment.trades if treatment.trades > 0 else 0.0

        ctrl_wi  = self._wilson(control.wins,  control.trades)
        trt_wi   = self._wilson(treatment.wins, treatment.trades)

        z, p     = self._two_proportion_z(
            control.wins,  control.trades,
            treatment.wins, treatment.trades,
        )

        improvement = (trt_wr - ctrl_wr) / ctrl_wr * 100 if ctrl_wr > 0 else 0.0
        significant = p < GOVERNANCE_MIN_P_VALUE
        conf_level  = 1.0 - p if p < 1.0 else 0.0

        recommendation, reason = self._recommend(
            control, treatment, ctrl_wr, trt_wr, z, p, significant, minimum_sample_size
        )

        risk = self._risk_assessment(p, improvement, treatment.trades)

        return ValidationResult(
            control_n               = control.trades,
            treatment_n             = treatment.trades,
            control_win_rate        = round(ctrl_wr * 100, 2),
            treatment_win_rate      = round(trt_wr * 100, 2),
            control_wilson          = ctrl_wi,
            treatment_wilson        = trt_wi,
            improvement_pct         = round(improvement, 2),
            z_score                 = round(z, 4),
            p_value                 = round(p, 6),
            is_significant          = significant,
            confidence_level        = round(conf_level, 4),
            recommendation          = recommendation,
            recommendation_reason   = reason,
            expected_improvement_pct = round(improvement, 2),
            risk_assessment         = risk,
        )

    # ── Wilson confidence interval ────────────────────────────────────────────

    @staticmethod
    def _wilson(wins: int, n: int, z: float = _Z_95) -> WilsonInterval:
        if n == 0:
            return WilsonInterval(lower=0.0, upper=0.0, center=0.0)
        p    = wins / n
        z2   = z * z
        denom = 1 + z2 / n
        center = (p + z2 / (2 * n)) / denom
        half   = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
        return WilsonInterval(
            lower  = round(max(0.0, center - half) * 100, 2),
            upper  = round(min(1.0, center + half) * 100, 2),
            center = round(center * 100, 2),
        )

    # ── Two-proportion Z-test ─────────────────────────────────────────────────

    @staticmethod
    def _two_proportion_z(
        c_wins: int, c_n: int, t_wins: int, t_n: int
    ) -> tuple[float, float]:
        if c_n == 0 or t_n == 0:
            return 0.0, 1.0
        p_c = c_wins / c_n
        p_t = t_wins / t_n
        p_pool = (c_wins + t_wins) / (c_n + t_n)
        denom = math.sqrt(p_pool * (1 - p_pool) * (1 / c_n + 1 / t_n))
        if denom == 0:
            return 0.0, 1.0
        z = (p_t - p_c) / denom
        # Two-tailed p-value approximation via erfc
        p = math.erfc(abs(z) / math.sqrt(2))
        return z, p

    # ── Recommendation logic ──────────────────────────────────────────────────

    @staticmethod
    def _recommend(
        control: GroupStats, treatment: GroupStats,
        ctrl_wr: float, trt_wr: float,
        z: float, p: float,
        significant: bool,
        min_sample: int,
    ) -> tuple[str, str]:
        # Treatment clearly worse
        if trt_wr < ctrl_wr - 0.05:
            return "REJECT", f"Treatment win rate {trt_wr*100:.1f}% is worse than control {ctrl_wr*100:.1f}%"

        if not significant:
            if treatment.trades < min_sample:
                return "INSUFFICIENT_DATA", f"Only {treatment.trades} treatment trades; need {min_sample}"
            return "CONTINUE", f"p={p:.4f} not yet significant at 0.05 — collect more data"

        # Significant but treatment worse
        if trt_wr <= ctrl_wr:
            return "REJECT", f"Significant result but treatment ({trt_wr*100:.1f}%) ≤ control ({ctrl_wr*100:.1f}%)"

        improvement = (trt_wr - ctrl_wr) / ctrl_wr * 100
        if improvement < 3.0:
            return "CONTINUE", f"Improvement {improvement:.1f}% is statistically significant but practically small"

        return "DEPLOY", (
            f"Significant improvement: {improvement:.1f}% win rate gain, "
            f"z={z:.2f}, p={p:.4f} (< 0.05)"
        )

    @staticmethod
    def _risk_assessment(p: float, improvement: float, treatment_n: int) -> str:
        if p > 0.1 or treatment_n < 100:
            return "HIGH"
        if p > 0.05 or improvement < 5.0:
            return "MEDIUM"
        return "LOW"

    # ── Fallback for insufficient data ────────────────────────────────────────

    @staticmethod
    def _insufficient(
        control: GroupStats, treatment: GroupStats, reason: str
    ) -> ValidationResult:
        ctrl_wr = control.wins / control.trades  if control.trades  > 0 else 0.0
        trt_wr  = treatment.wins / treatment.trades if treatment.trades > 0 else 0.0
        return ValidationResult(
            control_n               = control.trades,
            treatment_n             = treatment.trades,
            control_win_rate        = round(ctrl_wr * 100, 2),
            treatment_win_rate      = round(trt_wr * 100, 2),
            control_wilson          = WilsonInterval(0, 0, 0),
            treatment_wilson        = WilsonInterval(0, 0, 0),
            improvement_pct         = 0.0,
            z_score                 = 0.0,
            p_value                 = 1.0,
            is_significant          = False,
            confidence_level        = 0.0,
            recommendation          = "INSUFFICIENT_DATA",
            recommendation_reason   = reason,
            expected_improvement_pct = 0.0,
            risk_assessment         = "HIGH",
        )
