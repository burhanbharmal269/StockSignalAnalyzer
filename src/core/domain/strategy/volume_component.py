"""Volume Analysis Component — Component 4 (base weight: 15).

Confirms that price movements are backed by institutional participation.
Volume is the engine; price without volume is noise.

Score formula:
  Step 1: Volume ratio (current bar / 20-bar average) — tiered 3→15 pts
  Step 2: Volume divergence penalty (-5 if price making new high on declining volume)
  Step 3: OBV (On-Balance Volume) trend confirmation (+/-2)
  Step 4: Cumulative delta — buy vs sell pressure (+/-2)
  Step 5: VPOC proximity — within 0.2% of today's volume POC (+1)

Final = clamp(sum of above, 0, 15)

Source: docs/21_SIGNAL_ENGINE.md Component 4
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.interfaces.i_score_component import IScoreComponent
from core.domain.value_objects.component_output import ComponentOutput

if TYPE_CHECKING:
    from core.domain.value_objects.score_context import ScoreContext
    from core.infrastructure.config.strategy_config import StrategyConfig

_NAME = "VOLUME"
_MAX_WEIGHT = 15


class VolumeComponent(IScoreComponent):
    """Volume confirmation scorer. Pure, stateless."""

    def __init__(self, config: StrategyConfig) -> None:
        self._cfg = config.volume

    @property
    def component_name(self) -> str:
        return _NAME

    @property
    def max_weight(self) -> int:
        return _MAX_WEIGHT

    def evaluate(self, context: ScoreContext) -> ComponentOutput:
        cfg = self._cfg

        if context.volume_ratio is None:
            return ComponentOutput.unavailable(_NAME, _MAX_WEIGHT, "volume_ratio not available")

        vr = context.volume_ratio

        # Step 1: Volume ratio base score
        vol_base = self._volume_ratio_score(vr, cfg)

        # Step 2: Divergence penalty (price up on falling volume = suspect)
        div_penalty = self._divergence_penalty(
            context.price_change_pct,
            vr,
            cfg,
        )

        # Step 3: OBV confirmation
        long_obv, short_obv = self._obv_scores(context.obv_trend, cfg)

        # Step 4: Cumulative delta
        long_delta, short_delta = self._delta_scores(context.cumulative_delta, cfg)

        # Step 5: VPOC proximity
        vpoc_bonus = self._vpoc_bonus(context.vpoc_distance_pct, cfg)

        # Both directions share the same volume base and divergence signals.
        # The delta and OBV provide directional differentiation.
        long_raw = vol_base - div_penalty + long_obv + long_delta + vpoc_bonus
        short_raw = vol_base - div_penalty + short_obv + short_delta + vpoc_bonus

        long_score = max(0.0, min(float(_MAX_WEIGHT), long_raw))
        short_score = max(0.0, min(float(_MAX_WEIGHT), short_raw))

        direction, conviction = _direction_and_conviction(long_score, short_score, _MAX_WEIGHT)

        div_text = f"−{div_penalty:.0f}pt divergence" if div_penalty > 0 else "no divergence"
        obv_text = context.obv_trend or "N/A"
        delta = context.cumulative_delta
        delta_text = (
            f"delta {'↑' if delta >= 0 else '↓'} {abs(delta):.0f}"
            if delta is not None
            else "delta N/A"
        )

        key_finding = (
            f"Volume {vr:.1f}× average. {div_text}. OBV: {obv_text}. "
            f"Cumulative {delta_text}. VPOC: {_vpoc_text(context.vpoc_distance_pct, cfg)}."
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
                "volume_ratio": vr,
                "vol_base_score": vol_base,
                "divergence_penalty": div_penalty,
                "obv_trend": context.obv_trend,
                "cumulative_delta": context.cumulative_delta,
                "vpoc_distance_pct": context.vpoc_distance_pct,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _volume_ratio_score(vr: float, cfg: object) -> float:
        if vr >= cfg.volume_ratio_tier_4:
            return cfg.volume_ratio_score_5
        if vr >= cfg.volume_ratio_tier_3:
            return cfg.volume_ratio_score_4
        if vr >= cfg.volume_ratio_tier_2:
            return cfg.volume_ratio_score_3
        if vr >= cfg.volume_ratio_tier_1:
            return cfg.volume_ratio_score_2
        return cfg.volume_ratio_score_1

    @staticmethod
    def _divergence_penalty(
        price_change_pct: float | None,
        volume_ratio: float,
        cfg: object,
    ) -> float:
        """Return penalty when price is rising/falling but volume is declining."""
        if price_change_pct is None:
            return 0.0
        if abs(price_change_pct) > 0 and volume_ratio < 1.0:
            return cfg.divergence_penalty
        return 0.0

    @staticmethod
    def _obv_scores(obv_trend: str | None, cfg: object) -> tuple[float, float]:
        if obv_trend == "UP":
            return cfg.obv_confirms_score, cfg.obv_against_score
        if obv_trend == "DOWN":
            return cfg.obv_against_score, cfg.obv_confirms_score
        return 0.0, 0.0  # FLAT or None

    @staticmethod
    def _delta_scores(
        cumulative_delta: float | None, cfg: object
    ) -> tuple[float, float]:
        if cumulative_delta is None:
            return 0.0, 0.0
        if cumulative_delta > 0:
            return cfg.delta_confirms_score, cfg.delta_against_score
        if cumulative_delta < 0:
            return cfg.delta_against_score, cfg.delta_confirms_score
        return 0.0, 0.0

    @staticmethod
    def _vpoc_bonus(vpoc_distance_pct: float | None, cfg: object) -> float:
        if vpoc_distance_pct is None:
            return 0.0
        if abs(vpoc_distance_pct) <= cfg.vpoc_threshold_pct:
            return cfg.vpoc_bonus
        return 0.0


def _direction_and_conviction(
    long_score: float, short_score: float, max_weight: int
) -> tuple[str, float]:
    if long_score > short_score:
        return "LONG", long_score / max_weight
    if short_score > long_score:
        return "SHORT", short_score / max_weight
    return "NEUTRAL", 0.0


def _vpoc_text(vpoc_distance_pct: float | None, cfg: object) -> str:
    if vpoc_distance_pct is None:
        return "N/A"
    if abs(vpoc_distance_pct) <= cfg.vpoc_threshold_pct:
        return f"at VPOC ({vpoc_distance_pct:+.2f}%)"
    return f"{abs(vpoc_distance_pct):.2f}% from VPOC"
