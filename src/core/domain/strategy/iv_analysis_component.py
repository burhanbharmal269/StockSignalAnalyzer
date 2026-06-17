"""IV Analysis Component — Component 7 (base weight: 5).

Assesses whether the current IV environment favours buying or selling
volatility, and whether IV is directionally supportive.

Score formula:
  Step 1: India VIX level context (regime classification)
  Step 2: IV Percentile scoring
          LONG vol (buy premium): low IV is good → iv_pct < 20 → 5 pts
          SHORT vol (sell premium): high IV is good → iv_pct > 70 → 5 pts
  Step 3: HV/IV ratio bonus
          hv_iv > 1.2 → options cheap → +2 to long_score
          hv_iv < 0.8 → options expensive → +2 to short_score
  Step 4: VIX structural penalty on short vol
          India VIX > 20 → -2 from short_score (short vol dangerous in fear zone)

Source: docs/21_SIGNAL_ENGINE.md Component 7
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.interfaces.i_score_component import IScoreComponent
from core.domain.value_objects.component_output import ComponentOutput

if TYPE_CHECKING:
    from core.domain.value_objects.score_context import ScoreContext
    from core.infrastructure.config.strategy_config import StrategyConfig

_NAME = "IV_ANALYSIS"
_MAX_WEIGHT = 5


class IVAnalysisComponent(IScoreComponent):
    """IV regime scorer. Pure, stateless."""

    def __init__(self, config: StrategyConfig) -> None:
        self._cfg = config.iv_analysis

    @property
    def component_name(self) -> str:
        return _NAME

    @property
    def max_weight(self) -> int:
        return _MAX_WEIGHT

    def evaluate(self, context: ScoreContext) -> ComponentOutput:
        cfg = self._cfg
        features = context.features

        iv_pct = features.iv_percentile
        if iv_pct is None:
            return ComponentOutput.unavailable(_NAME, _MAX_WEIGHT, "iv_percentile not available")

        hv_iv = features.hv_iv_ratio
        vix = features.india_vix

        # Step 2: IV percentile scoring
        long_iv = self._long_vol_score(iv_pct, cfg)
        short_iv = self._short_vol_score(iv_pct, cfg)

        # Step 3: HV/IV ratio bonus
        long_hv_bonus = 0.0
        short_hv_bonus = 0.0
        if hv_iv is not None:
            if hv_iv > cfg.hv_iv_ratio_buy_threshold:
                long_hv_bonus = cfg.hv_iv_bonus   # HV > IV = cheap options → buy
            elif hv_iv < cfg.hv_iv_ratio_sell_threshold:
                short_hv_bonus = cfg.hv_iv_bonus  # HV < IV = expensive options → sell

        # Step 4: VIX structural penalty for short vol
        short_vix_penalty = 0.0
        if vix is not None and vix > cfg.vix_high_threshold:
            short_vix_penalty = cfg.vix_short_vol_penalty

        long_raw = long_iv + long_hv_bonus
        short_raw = short_iv + short_hv_bonus - short_vix_penalty

        long_score = max(0.0, min(float(_MAX_WEIGHT), long_raw))
        short_score = max(0.0, min(float(_MAX_WEIGHT), short_raw))

        direction, conviction = _direction_and_conviction(long_score, short_score, _MAX_WEIGHT)

        vix_label = _vix_label(vix)
        hv_iv_text = f"{hv_iv:.2f}" if hv_iv is not None else "N/A"
        vol_bias = "buy vol" if long_score >= short_score else "sell vol"

        key_finding = (
            f"IV Percentile {iv_pct:.0f}%. "
            f"India VIX: {f'{vix:.1f}' if vix is not None else 'N/A'} ({vix_label}). "
            f"HV/IV: {hv_iv_text}. Bias: {vol_bias}."
        )

        return ComponentOutput(
            component_name=_NAME,
            max_weight=_MAX_WEIGHT,
            long_score=long_score,
            short_score=short_score,
            direction=direction,
            conviction=conviction,
            is_available=True,
            data_freshness_seconds=0,
            key_finding=key_finding,
            metadata={
                "iv_percentile": iv_pct,
                "hv_iv_ratio": hv_iv,
                "india_vix": vix,
                "long_iv_score": long_iv,
                "short_iv_score": short_iv,
                "long_hv_bonus": long_hv_bonus,
                "short_hv_bonus": short_hv_bonus,
                "short_vix_penalty": short_vix_penalty,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _long_vol_score(iv_pct: float, cfg: object) -> float:
        """LONG vol signal (buy premium): low IV is structurally advantageous."""
        if iv_pct < cfg.iv_buy_percentile_max:
            return cfg.iv_buy_score_max
        if iv_pct < cfg.iv_buy_percentile_mid:
            return cfg.iv_buy_score_mid
        if iv_pct < cfg.iv_buy_percentile_low:
            return cfg.iv_buy_score_low
        return 0.0

    @staticmethod
    def _short_vol_score(iv_pct: float, cfg: object) -> float:
        """SHORT vol signal (sell premium): high IV is structurally advantageous."""
        if iv_pct >= cfg.iv_sell_percentile_min:
            return cfg.iv_sell_score_max
        if iv_pct >= cfg.iv_sell_percentile_mid:
            return cfg.iv_sell_score_mid
        if iv_pct >= cfg.iv_sell_percentile_low:
            return cfg.iv_sell_score_low
        return 0.0


def _direction_and_conviction(
    long_score: float, short_score: float, max_weight: int
) -> tuple[str, float]:
    if long_score > short_score:
        return "LONG", long_score / max_weight
    if short_score > long_score:
        return "SHORT", short_score / max_weight
    return "NEUTRAL", 0.0


def _vix_label(vix: float | None) -> str:
    if vix is None:
        return "N/A"
    if vix < 11:
        return "extreme complacency"
    if vix < 14:
        return "low fear"
    if vix < 18:
        return "normal"
    if vix < 22:
        return "elevated"
    if vix < 28:
        return "fear zone"
    return "panic"
