"""Trend Following Component — Component 2 (base weight: 20).

HARD GATE: ADX < gate → long_score = 0, short_score = 0, direction = NEUTRAL.
This gate cannot be overridden by any other condition.

Score formula:
  Step 1: ADX base score (tiers: 20-25, 25-28, 28-32, 32-36, >36)
  Step 2: DI spread score (DI+ vs DI-, 5/10/15 spread thresholds)
  Step 3: EMA alignment (EMA20/50/200 stack on available timeframe)
  Step 4: Supertrend direction confirmation (+3)
  Step 5: Multi-timeframe alignment (approximated from available data)
  Step 6: RSI momentum gate — gradated sweet-spot scoring
  Step 7: Prime time window bonus (+3 in 10:00-11:30 and 13:00-14:00 IST)
  Step 8: ADX Rising bonus (+2 when ADX accelerating)

Source: docs/21_SIGNAL_ENGINE.md Component 2
"""

from __future__ import annotations

from datetime import datetime, time as _dtime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from core.domain.interfaces.i_score_component import IScoreComponent
from core.domain.value_objects.component_output import ComponentOutput

if TYPE_CHECKING:
    from core.domain.value_objects.score_context import ScoreContext
    from core.infrastructure.config.strategy_config import StrategyConfig

_NAME = "TREND"
_MAX_WEIGHT = 20


class TrendComponent(IScoreComponent):
    """Multi-factor trend scorer. Pure, stateless. ADX is the mandatory gate."""

    def __init__(self, config: StrategyConfig) -> None:
        self._cfg = config.trend

    @property
    def component_name(self) -> str:
        return _NAME

    @property
    def max_weight(self) -> int:
        return _MAX_WEIGHT

    def evaluate(self, context: ScoreContext) -> ComponentOutput:
        cfg = self._cfg
        features = context.features

        if features.adx is None:
            return ComponentOutput.unavailable(_NAME, _MAX_WEIGHT, "ADX not available")

        # HARD GATE: ADX < gate threshold
        if features.adx < cfg.adx_gate:
            return ComponentOutput(
                component_name=_NAME,
                max_weight=_MAX_WEIGHT,
                long_score=0.0,
                short_score=0.0,
                direction="NEUTRAL",
                conviction=0.0,
                is_available=True,
                data_freshness_seconds=0,
                key_finding=(
                    f"ADX {features.adx:.1f} < {cfg.adx_gate} gate — "
                    "no trend signal in choppy market"
                ),
                metadata={"adx": features.adx, "gate_triggered": True},
            )

        # Step 1: ADX base score
        adx_base = self._adx_base_score(features.adx, cfg)

        # Step 2: DI spread → direction
        if features.di_plus is None or features.di_minus is None:
            return ComponentOutput.unavailable(_NAME, _MAX_WEIGHT, "DI+/DI- not available")

        di_spread = abs(features.di_plus - features.di_minus)
        long_is_dominant = features.di_plus > features.di_minus
        di_score = self._di_spread_score(di_spread, cfg)

        # Step 3: EMA alignment
        long_ema, short_ema = self._ema_alignment_scores(features, cfg)

        # Step 4: Supertrend
        long_st, short_st = self._supertrend_scores(features.supertrend_direction, cfg)

        # Step 5: MTF (approximated — single TF data contributes 1-TF alignment)
        # Full MTF bonus requires data from multiple timeframes (Phase 14+)
        mtf_score = 0.0  # Conservative: no bonus without cross-TF data

        # Step 6: RSI momentum gate — gradated sweet-spot scoring
        long_rsi, short_rsi = self._rsi_gate(context.rsi_14, cfg)

        # Step 7: Prime time window bonus
        prime = self._prime_time_bonus(cfg)

        # Step 8: ADX Rising bonus — trend accelerating, not exhausting
        adx_bonus = self._adx_rising_bonus(features.adx_rising, features.adx, cfg)

        # Step 9: MACD histogram expansion bonus — momentum strengthening in direction.
        # macd_hist_expanding was already computed in the scanner but never scored.
        # +1 pt when histogram is growing (|current hist| > |previous hist|) — soft bonus
        # only on the dominant direction, never on both, never large enough to swing a trade.
        macd_hist_bonus = 1.0 if features.macd_hist_expanding else 0.0

        # Combine: directional side gets ema + supertrend + rsi + time + adx + macd bonuses
        if long_is_dominant:
            long_raw = adx_base + di_score + long_ema + long_st + mtf_score + long_rsi + prime + adx_bonus + macd_hist_bonus
            short_raw = 0.0
        else:
            long_raw = 0.0
            short_raw = adx_base + di_score + short_ema + short_st + mtf_score + short_rsi + prime + adx_bonus + macd_hist_bonus

        long_score = max(0.0, min(float(_MAX_WEIGHT), long_raw))
        short_score = max(0.0, min(float(_MAX_WEIGHT), short_raw))

        direction = "LONG" if long_is_dominant else "SHORT"
        conviction = max(long_score, short_score) / _MAX_WEIGHT

        dominant_di = "+" if long_is_dominant else "-"
        ema_status = _ema_status_text(features)

        prime_note = f" +{prime:.0f}pt prime-window" if prime > 0 else ""
        adx_note   = f" +{adx_bonus:.0f}pt ADX↑" if adx_bonus > 0 else ""
        key_finding = (
            f"ADX {features.adx:.1f} with DI{dominant_di} leading by "
            f"{di_spread:.1f} pts. EMA: {ema_status}. "
            f"Supertrend: {_supertrend_text(features.supertrend_direction)}."
            f"{prime_note}{adx_note}"
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
                "adx": features.adx,
                "di_plus": features.di_plus,
                "di_minus": features.di_minus,
                "di_spread": di_spread,
                "adx_base": adx_base,
                "di_score": di_score,
                "supertrend": features.supertrend_direction,
                "rsi_14": context.rsi_14,
                "prime_bonus": prime,
                "adx_rising_bonus": adx_bonus,
                "adx_rising": features.adx_rising,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _adx_base_score(adx: float, cfg: object) -> float:
        if adx > cfg.adx_very_strong:
            return cfg.adx_score_very_strong
        if adx > cfg.adx_strong:
            return cfg.adx_score_strong_to_very_strong
        if adx > cfg.adx_moderate:
            return cfg.adx_score_moderate_to_strong
        if adx > cfg.adx_weak:
            return cfg.adx_score_weak_to_moderate
        return cfg.adx_score_gate_to_weak

    @staticmethod
    def _di_spread_score(di_spread: float, cfg: object) -> float:
        if di_spread < cfg.di_spread_no_signal:
            return 0.0
        if di_spread < cfg.di_spread_moderate:
            return cfg.di_spread_score_moderate
        if di_spread < cfg.di_spread_strong:
            return cfg.di_spread_score_strong
        return cfg.di_spread_score_very_strong

    @staticmethod
    def _ema_alignment_scores(features: object, cfg: object) -> tuple[float, float]:
        """Return (long_ema_score, short_ema_score)."""
        e20, e50, e200 = features.ema_20, features.ema_50, features.ema_200

        if e20 is None:
            return 0.0, 0.0

        # Full alignment: 20 > 50 > 200 (bullish) or 20 < 50 < 200 (bearish)
        if e50 is not None and e200 is not None:
            if e20 > e50 > e200:
                return cfg.ema_full_alignment_score, 0.0
            if e20 < e50 < e200:
                return 0.0, cfg.ema_full_alignment_score

        # Partial: 20 vs 50
        if e50 is not None:
            if e20 > e50:
                return cfg.ema_partial_20_50_score, 0.0
            return 0.0, cfg.ema_partial_20_50_score

        # Partial: 20 vs 200
        if e200 is not None:
            if e20 > e200:
                return cfg.ema_partial_20_200_score, 0.0
            return 0.0, cfg.ema_partial_20_200_score

        return 0.0, 0.0

    @staticmethod
    def _supertrend_scores(supertrend_direction: int | None, cfg: object) -> tuple[float, float]:
        if supertrend_direction is None:
            return 0.0, 0.0
        if supertrend_direction == 1:
            return cfg.supertrend_score, 0.0
        if supertrend_direction == -1:
            return 0.0, cfg.supertrend_score
        return 0.0, 0.0

    @staticmethod
    def _rsi_gate(rsi: float | None, cfg: object) -> tuple[float, float]:
        """Gradated RSI scoring: sweet spot > acceptable range > outside = penalty.

        Research (AIMarketAnalyzer): for option buyers the ideal RSI entry zone is
        55-70 (LONG) / 30-45 (SHORT) — momentum is building, not exhausted.
        Buying into RSI 70+ means paying inflated premium at the peak of a move.
        """
        if rsi is None:
            return 0.0, 0.0

        def _score_side(in_sweet: bool, in_range: bool) -> float:
            if in_sweet:
                return cfg.rsi_gate_score + cfg.rsi_sweet_bonus
            if in_range:
                return cfg.rsi_gate_score
            return cfg.rsi_bad_penalty

        long_sweet = cfg.rsi_long_sweet_min <= rsi <= cfg.rsi_long_sweet_max
        long_range = cfg.rsi_long_min <= rsi <= cfg.rsi_long_max
        short_sweet = cfg.rsi_short_sweet_min <= rsi <= cfg.rsi_short_sweet_max
        short_range = cfg.rsi_short_min <= rsi <= cfg.rsi_short_max

        return _score_side(long_sweet, long_range), _score_side(short_sweet, short_range)

    @staticmethod
    def _prime_time_bonus(cfg: object) -> float:
        """Return bonus pts when scanning during high-probability IST windows.

        10:00-11:30: post-open momentum — market settled, directional moves sustained.
        13:00-14:00: post-lunch continuation — breakout window before close volatility.
        Research (AIMarketAnalyzer): these windows have materially higher win rates.
        """
        now = datetime.now(ZoneInfo("Asia/Kolkata")).time()
        if _dtime(10, 0) <= now <= _dtime(11, 30):
            return cfg.prime_time_bonus
        if _dtime(13, 0) <= now <= _dtime(14, 0):
            return cfg.prime_time_bonus
        return 0.0

    @staticmethod
    def _adx_rising_bonus(adx_rising: bool | None, adx: float | None, cfg: object) -> float:
        """Return bonus when ADX is accelerating above the minimum meaningful level.

        Rising ADX means the trend is strengthening — not exhausting — giving
        higher confidence in trend-continuation option setups.
        """
        if adx_rising and adx is not None and adx >= cfg.adx_rising_min:
            return cfg.adx_rising_bonus
        return 0.0


def _ema_status_text(features: object) -> str:
    e20, e50, e200 = features.ema_20, features.ema_50, features.ema_200
    if e20 is None:
        return "N/A"
    if e50 is not None and e200 is not None:
        if e20 > e50 > e200:
            return "full bullish stack (20>50>200)"
        if e20 < e50 < e200:
            return "full bearish stack (20<50<200)"
        return "partial alignment"
    if e50 is not None:
        return f"20{'>' if e20 > e50 else '<'}50"
    return "single EMA"


def _supertrend_text(st: int | None) -> str:
    if st is None:
        return "N/A"
    return "bullish ↑" if st == 1 else "bearish ↓"
