"""Platform-wide constants for Phase 25 freeze, versioning, and governance.

These are intentionally hard-coded strings — the version manifest is the
source of truth for what logic generated a given signal. Bump them only
when the corresponding engine is materially changed (and only after
satisfying the change governance gates in ChangeGovernanceService).
"""

from __future__ import annotations

# ── Architecture status ────────────────────────────────────────────────────────
# ACTIVE_DEVELOPMENT → FEATURE_COMPLETE → FROZEN → RESEARCH_ONLY
ARCHITECTURE_STATUS: str = "FROZEN"

# ── Version manifest ──────────────────────────────────────────────────────────
# Bump only when corresponding engine changes pass governance gates.
STRATEGY_VERSION:   str = "25.0.0"   # signal scoring + engine bundle
CONFIDENCE_VERSION: str = "25.0.0"   # confidence calculator
OVERLAY_VERSION:    str = "25.0.0"   # overlay pipeline
RISK_VERSION:       str = "25.0.0"   # risk engine + position sizing
TARGET_VERSION:     str = "25.0.0"   # target / stop logic in option strike selector

# ── Governance gate thresholds ─────────────────────────────────────────────────
GOVERNANCE_MIN_TRADES:         int   = 200      # hard minimum to consider deployment
GOVERNANCE_PREFERRED_TRADES:   int   = 500      # preferred sample size
GOVERNANCE_MIN_P_VALUE:        float = 0.05     # p < 0.05 = statistically significant
GOVERNANCE_MIN_CONFIDENCE:     float = 0.95     # 95% confidence interval minimum
GOVERNANCE_WALKFORWARD_PASSES: int   = 1        # must have passed walk-forward
GOVERNANCE_PAPER_PASSES:       int   = 1        # must have passed paper validation

# ── A/B routing defaults ──────────────────────────────────────────────────────
DEFAULT_TREATMENT_ALLOCATION_PCT: float = 10.0  # 10% signals go to treatment group

# ── Prohibited changes while frozen ──────────────────────────────────────────
FROZEN_CHANGE_CATEGORIES: list[str] = [
    "indicators",
    "score_components",
    "score_weights",
    "thresholds",
    "overlays",
    "confidence_logic",
    "target_logic",
    "stop_logic",
    "position_sizing",
    "regime_logic",
    "option_selection",
    "signal_generation",
]
