"""Option Chain Analysis Component — Component 3 (base weight: 20).

Reads the options market's collective intelligence: IV levels, GEX
positioning, OI concentration at strikes, PCR trend.

Score formula:
  Step 1: IV Percentile scoring (different tiers for LONG vs SHORT signal)
  Step 2: IV Skew analysis (put_iv - call_iv; confirms directional demand)
  Step 3: GEX (Gamma Exposure) — positive GEX = shock absorber; negative = amplifier
  Step 4: OI wall proximity (nearest CE/PE OI wall distance from current price)
  Step 5: PCR direction trend (RISING/FALLING/STABLE)

Source: docs/21_SIGNAL_ENGINE.md Component 3
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.interfaces.i_score_component import IScoreComponent
from core.domain.value_objects.component_output import ComponentOutput

if TYPE_CHECKING:
    from core.domain.value_objects.option_chain_snapshot import OptionChainSnapshot
    from core.domain.value_objects.score_context import ScoreContext
    from core.infrastructure.config.strategy_config import StrategyConfig

_NAME = "OPTION_CHAIN"
_MAX_WEIGHT = 20


class OptionChainComponent(IScoreComponent):
    """Option chain intelligence scorer. Pure, stateless."""

    def __init__(self, config: StrategyConfig) -> None:
        self._cfg = config.option_chain

    @property
    def component_name(self) -> str:
        return _NAME

    @property
    def max_weight(self) -> int:
        return _MAX_WEIGHT

    def evaluate(self, context: ScoreContext) -> ComponentOutput:
        cfg = self._cfg
        oc = context.option_chain

        # Resolve IV percentile from option chain first, fall back to features
        iv_pct = _resolve_iv_pct(oc, context.features)

        if iv_pct is None:
            return ComponentOutput.unavailable(
                _NAME, _MAX_WEIGHT, "iv_percentile not available"
            )

        # Step 1: IV percentile scoring
        long_iv = self._iv_long_score(iv_pct, cfg)
        short_iv = self._iv_short_score(iv_pct, cfg)

        # Step 2: IV skew
        long_skew, short_skew = self._skew_scores(oc, cfg)

        # Step 3: GEX
        long_gex, short_gex = self._gex_scores(oc, cfg)

        # Step 4: OI wall proximity
        long_wall, short_wall = self._wall_scores(oc, cfg)

        # Step 5: PCR trend
        long_pcr, short_pcr = self._pcr_trend_scores(oc, cfg)

        long_raw = long_iv + long_skew + long_gex + long_wall + long_pcr
        short_raw = short_iv + short_skew + short_gex + short_wall + short_pcr

        long_score = max(0.0, min(float(_MAX_WEIGHT), long_raw))
        short_score = max(0.0, min(float(_MAX_WEIGHT), short_raw))

        direction, conviction = _direction_and_conviction(long_score, short_score, _MAX_WEIGHT)

        iv_skew = oc.iv_skew if oc is not None else None
        skew_text = f"Skew {iv_skew:+.2f}" if iv_skew is not None else "Skew N/A"
        gex_text = _gex_text(oc)
        wall_text = _wall_text(oc)

        key_finding = (
            f"IV Percentile {iv_pct:.0f}%. {skew_text}. "
            f"GEX: {gex_text}. {wall_text}."
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
                "iv_skew": iv_skew,
                "gex_positive": oc.gex_positive if oc else None,
                "nearest_call_wall_pct": oc.nearest_call_wall_distance_pct if oc else None,
                "nearest_put_wall_pct": oc.nearest_put_wall_distance_pct if oc else None,
                "pcr_trend": oc.pcr_trend if oc else None,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _iv_long_score(iv_pct: float, cfg: object) -> float:
        """Lower IV = better for buying options (LONG signal)."""
        if iv_pct < cfg.iv_long_tier_1_max:
            return cfg.iv_long_score_tier_1
        if iv_pct < cfg.iv_long_tier_2_max:
            return cfg.iv_long_score_tier_2
        if iv_pct < cfg.iv_long_tier_3_max:
            return cfg.iv_long_score_tier_3
        if iv_pct < cfg.iv_long_tier_4_max:
            return cfg.iv_long_score_tier_4
        return cfg.iv_long_score_tier_5

    @staticmethod
    def _iv_short_score(iv_pct: float, cfg: object) -> float:
        """Higher IV = better for selling options or bear spreads (SHORT signal)."""
        if iv_pct > cfg.iv_short_tier_3_max:
            return cfg.iv_short_score_tier_4
        if iv_pct > cfg.iv_short_tier_2_max:
            return cfg.iv_short_score_tier_3
        if iv_pct > cfg.iv_short_tier_1_max:
            return cfg.iv_short_score_tier_2
        return cfg.iv_short_score_tier_1

    @staticmethod
    def _skew_scores(
        oc: OptionChainSnapshot | None, cfg: object
    ) -> tuple[float, float]:
        if oc is None or oc.iv_skew is None:
            return 0.0, 0.0
        # skew = put_iv - call_iv
        # Negative skew (calls more expensive than puts) = bullish demand → LONG
        # Positive skew (puts more expensive) = bearish protection demand → SHORT
        if oc.iv_skew < -cfg.iv_skew_threshold:
            return cfg.iv_skew_score, 0.0
        if oc.iv_skew > cfg.iv_skew_threshold:
            return 0.0, cfg.iv_skew_score
        return 0.0, 0.0

    @staticmethod
    def _gex_scores(
        oc: OptionChainSnapshot | None, cfg: object
    ) -> tuple[float, float]:
        if oc is None or oc.gex_positive is None:
            return 0.0, 0.0

        if oc.gex_positive:
            # Positive GEX: market makers net long gamma, act as shock absorbers.
            # They pin price toward the GEX concentration strike.
            if oc.gex_strike is not None:
                # If GEX strike is above price it pulls price up → helps LONG
                # We can't compute this without close_price in oc, so give neutral bonus
                return cfg.gex_aligned_score, cfg.gex_aligned_score
            return 0.0, 0.0

        # Negative GEX: market makers net short gamma, amplify moves.
        # Amplification helps whichever direction the market is already going.
        # Give the squeeze bonus to both since we don't know the recent direction here.
        return cfg.gex_squeeze_score, cfg.gex_squeeze_score

    @staticmethod
    def _wall_scores(
        oc: OptionChainSnapshot | None, cfg: object
    ) -> tuple[float, float]:
        """OI wall proximity — call wall for LONG, put wall for SHORT."""
        if oc is None:
            return 0.0, 0.0

        long_wall = _single_wall_score(oc.nearest_call_wall_distance_pct, cfg)
        short_wall = _single_wall_score(oc.nearest_put_wall_distance_pct, cfg)
        return long_wall, short_wall

    @staticmethod
    def _pcr_trend_scores(
        oc: OptionChainSnapshot | None, cfg: object
    ) -> tuple[float, float]:
        if oc is None or oc.pcr_trend is None:
            return 0.0, 0.0

        if oc.pcr_trend == "RISING":
            # Rising PCR = more put buying / put OI building = bullish for underlying
            return cfg.pcr_trend_confirms_score, cfg.pcr_trend_against_score
        if oc.pcr_trend == "FALLING":
            # Falling PCR = call OI building faster = bearish (calls being written)
            return cfg.pcr_trend_against_score, cfg.pcr_trend_confirms_score
        return 0.0, 0.0  # STABLE


def _single_wall_score(distance_pct: float | None, cfg: object) -> float:
    if distance_pct is None:
        return 0.0
    if distance_pct < cfg.oi_wall_close_pct:
        return cfg.oi_wall_close_score        # Immediate wall — blocks move
    if distance_pct < cfg.oi_wall_medium_pct:
        return cfg.oi_wall_medium_score       # Neutral
    if distance_pct < cfg.oi_wall_far_pct:
        return cfg.oi_wall_far_score          # Clear room
    return cfg.oi_wall_very_far_score         # Significant room


def _resolve_iv_pct(
    oc: OptionChainSnapshot | None,
    features: object,
) -> float | None:
    """Prefer option chain IV percentile, fall back to features.iv_percentile."""
    if oc is not None and oc.iv_percentile is not None:
        return oc.iv_percentile
    return features.iv_percentile


def _direction_and_conviction(
    long_score: float, short_score: float, max_weight: int
) -> tuple[str, float]:
    if long_score > short_score:
        return "LONG", long_score / max_weight
    if short_score > long_score:
        return "SHORT", short_score / max_weight
    return "NEUTRAL", 0.0


def _gex_text(oc: OptionChainSnapshot | None) -> str:
    if oc is None or oc.gex_positive is None:
        return "N/A"
    kind = "positive (shock absorber)" if oc.gex_positive else "negative (amplifier)"
    strike = f" at {oc.gex_strike:.0f}" if oc.gex_strike is not None else ""
    return f"{kind}{strike}"


def _wall_text(oc: OptionChainSnapshot | None) -> str:
    if oc is None:
        return "No OI wall data"
    parts = []
    if oc.nearest_call_wall_distance_pct is not None:
        parts.append(f"CE wall {oc.nearest_call_wall_distance_pct:.1f}% above")
    if oc.nearest_put_wall_distance_pct is not None:
        parts.append(f"PE wall {oc.nearest_put_wall_distance_pct:.1f}% below")
    return "; ".join(parts) if parts else "No wall data"
