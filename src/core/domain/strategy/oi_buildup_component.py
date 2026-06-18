"""OI Build-up Component — Component 1 (base weight: 25).

Identifies whether fresh directional positions are being built or existing
ones are unwound. Primary conviction signal for Indian FnO.

OI Quadrant Classification:
  Long Build-up:    OI ↑, Price ↑  → most bullish  ★★★★★
  Short Build-up:   OI ↑, Price ↓  → most bearish  ★★★★★
  Short Covering:   OI ↓, Price ↑  → bullish but temporary  ★★★
  Long Unwinding:   OI ↓, Price ↓  → bearish but decelerating  ★★★
  Ambiguous: neither threshold met → noise floor

Source: docs/21_SIGNAL_ENGINE.md Component 1
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.interfaces.i_score_component import IScoreComponent
from core.domain.value_objects.component_output import ComponentOutput

if TYPE_CHECKING:
    from core.domain.value_objects.score_context import ScoreContext
    from core.infrastructure.config.strategy_config import StrategyConfig

_NAME = "OI_BUILDUP"
_MAX_WEIGHT = 25


class OIBuildupComponent(IScoreComponent):
    """OI quadrant + PCR + Max Pain + FII composite scorer. Pure, stateless."""

    def __init__(self, config: StrategyConfig) -> None:
        self._cfg = config.oi_buildup

    @property
    def component_name(self) -> str:
        return _NAME

    @property
    def max_weight(self) -> int:
        return _MAX_WEIGHT

    def evaluate(self, context: ScoreContext) -> ComponentOutput:
        cfg = self._cfg

        if context.oi_change_pct is None or context.price_change_pct is None:
            return ComponentOutput.unavailable(
                _NAME, _MAX_WEIGHT, "oi_change_pct or price_change_pct not available"
            )

        oi_chg = context.oi_change_pct
        price_chg = context.price_change_pct

        # Step 1-2: Determine quadrant and base scores
        quadrant, long_base, short_base = self._classify_quadrant(
            oi_chg, price_chg, cfg
        )

        # Step 3: PCR adjustment (if PCR available)
        long_pcr, short_pcr = self._pcr_adjustment(context.features.pcr, cfg)

        # Step 4: Max pain adjustment
        long_mp, short_mp = self._max_pain_adjustment(
            context.features.close_price,
            context.max_pain_price,
            context.dte,
            cfg,
        )

        # Step 5: FII net position adjustment
        long_fii, short_fii = self._fii_adjustment(context.fii_net_contracts, cfg)

        # Step 6: OFI confluence bonus — both OI quadrant AND PCR confirm direction
        long_ofi, short_ofi = self._ofi_confluence(quadrant, context.features.pcr, cfg)

        long_score = max(
            0.0,
            min(float(_MAX_WEIGHT), long_base + long_pcr + long_mp + long_fii + long_ofi),
        )
        short_score = max(
            0.0,
            min(float(_MAX_WEIGHT), short_base + short_pcr + short_mp + short_fii + short_ofi),
        )

        direction, conviction = _direction_and_conviction(long_score, short_score, _MAX_WEIGHT)

        pcr_val = context.features.pcr
        fii_text = _fii_text(context.fii_net_contracts, cfg.fii_net_threshold_contracts)
        price_dir = "↑" if price_chg >= 0 else "↓"
        oi_dir = "↑" if oi_chg >= 0 else "↓"

        key_finding = (
            f"{quadrant} — OI {oi_dir} {abs(oi_chg):.1f}% with price "
            f"{price_dir} {abs(price_chg):.2f}%. "
            f"PCR: {f'{pcr_val:.2f}' if pcr_val is not None else 'N/A'}. "
            f"FII: {fii_text}."
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
                "quadrant": quadrant,
                "oi_change_pct": oi_chg,
                "price_change_pct": price_chg,
                "long_base": long_base,
                "short_base": short_base,
                "pcr": pcr_val,
                "fii_net_contracts": context.fii_net_contracts,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_quadrant(
        oi_chg: float,
        price_chg: float,
        cfg: object,
    ) -> tuple[str, float, float]:
        """Return (quadrant_name, long_base_score, short_base_score)."""
        strong = cfg.oi_change_strong_pct
        price_min = cfg.price_change_min_pct

        if oi_chg >= strong and price_chg >= price_min:
            score = min(
                cfg.max_strong_score,
                oi_chg * cfg.long_oi_multiplier + price_chg * cfg.long_price_multiplier,
            )
            return "Long Build-up", score, 0.0

        if oi_chg >= strong and price_chg <= -price_min:
            score = min(
                cfg.max_strong_score,
                oi_chg * cfg.long_oi_multiplier + abs(price_chg) * cfg.long_price_multiplier,
            )
            return "Short Build-up", 0.0, score

        if oi_chg <= -strong and price_chg >= price_min:
            score = min(
                cfg.max_weak_score,
                abs(oi_chg) * cfg.covering_oi_multiplier
                + price_chg * cfg.covering_price_multiplier,
            )
            return "Short Covering", score, 0.0

        if oi_chg <= -strong and price_chg <= -price_min:
            score = min(
                cfg.max_weak_score,
                abs(oi_chg) * cfg.covering_oi_multiplier
                + abs(price_chg) * cfg.covering_price_multiplier,
            )
            return "Long Unwinding", 0.0, score

        floor = cfg.ambiguous_floor
        return "Ambiguous", floor / 2, floor / 2

    @staticmethod
    def _pcr_adjustment(
        pcr: float | None, cfg: object
    ) -> tuple[float, float]:
        """Return (long_adj, short_adj). Positive = adds to that direction."""
        if pcr is None:
            return 0.0, 0.0

        if pcr > cfg.pcr_strong_bullish:
            # High PCR = put protection = contrarian bullish for LONG
            return cfg.pcr_adjustment_strong, -cfg.pcr_adjustment_strong

        if pcr >= cfg.pcr_bullish_high:
            # PCR 1.0-1.3 = neutral
            return 0.0, 0.0

        if pcr >= cfg.pcr_bullish_low:
            # PCR 0.7-1.0 = bullish
            return cfg.pcr_adjustment_with, -cfg.pcr_adjustment_with

        # PCR < 0.7 = extreme call demand = contrarian bearish for LONG
        return cfg.pcr_adjustment_against, -cfg.pcr_adjustment_against

    @staticmethod
    def _max_pain_adjustment(
        close_price: float | None,
        max_pain_price: float | None,
        dte: int | None,
        cfg: object,
    ) -> tuple[float, float]:
        if close_price is None or max_pain_price is None or dte is None:
            return 0.0, 0.0

        if max_pain_price <= 0:
            return 0.0, 0.0

        distance_pct = abs(close_price - max_pain_price) / max_pain_price * 100

        if dte <= cfg.dte_max_pain_dominant and distance_pct > cfg.max_pain_distance_pct:
            # Price moving toward max pain on expiry = gravitational pull
            if close_price < max_pain_price:
                # Max pain is above → price needs to go up → bullish
                return cfg.max_pain_adjustment, 0.0
            # Max pain is below → price needs to go down → bearish
            return 0.0, cfg.max_pain_adjustment

        return 0.0, 0.0

    @staticmethod
    def _ofi_confluence(
        quadrant: str, pcr: float | None, cfg: object
    ) -> tuple[float, float]:
        """Return (long_adj, short_adj). Fires only when OI quadrant AND PCR agree."""
        if pcr is None:
            return 0.0, 0.0
        bonus = cfg.ofi_confluence_bonus
        # Long Build-up + PCR indicating put protection = dual institutional bullish
        if quadrant == "Long Build-up" and pcr >= cfg.ofi_bullish_pcr_min:
            return bonus, 0.0
        # Short Build-up + call euphoria (low PCR) = dual institutional bearish
        if quadrant == "Short Build-up" and pcr <= cfg.ofi_bearish_pcr_max:
            return 0.0, bonus
        return 0.0, 0.0

    @staticmethod
    def _fii_adjustment(
        fii_net_contracts: int | None, cfg: object
    ) -> tuple[float, float]:
        if fii_net_contracts is None:
            return 0.0, 0.0

        threshold = cfg.fii_net_threshold_contracts
        adj = cfg.fii_adjustment

        if fii_net_contracts > threshold:
            return adj, 0.0       # FII net long → bullish
        if fii_net_contracts < -threshold:
            return 0.0, adj       # FII net short → bearish
        return 0.0, 0.0


def _direction_and_conviction(
    long_score: float, short_score: float, max_weight: int
) -> tuple[str, float]:
    if long_score > short_score:
        return "LONG", long_score / max_weight
    if short_score > long_score:
        return "SHORT", short_score / max_weight
    return "NEUTRAL", 0.0


def _fii_text(fii_net: int | None, threshold: int) -> str:
    if fii_net is None:
        return "N/A"
    if fii_net > threshold:
        return f"net long +{fii_net:,} contracts"
    if fii_net < -threshold:
        return f"net short {fii_net:,} contracts"
    return f"neutral ({fii_net:,})"
