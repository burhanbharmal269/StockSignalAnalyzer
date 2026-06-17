"""Stage 8 — Candidate Ranker.

Produces the final ranked candidate list from the instruments that survived
Stages 1–7. Applies weighted composite scoring, sector diversification cap,
and returns exactly max_slots instruments (or fewer if survivors < max_slots).

Composite score formula (AD-USE-01):
  composite_score = (
      w_volume × norm(volume_ratio)
    + w_oi     × norm(atm_oi)
    + w_spread × (1 − norm(spread_pct))   # lower spread = higher score
    + w_atr    × norm(atr_14_pct)
  )

Normalisation: min-max across the survivor set. When all values are equal the
normalised value is 0.0 (avoids zero-division; equal instruments get equal score).

Sector diversification (additional requirement):
  When diversification.enabled and max_per_sector is set, instruments are walked
  in composite_score descending order. An instrument is admitted only when its
  sector count < max_per_sector. This ensures no single sector dominates.
"""

from __future__ import annotations

import logging
from typing import Any

from core.domain.universe.instrument_data import InstrumentData
from core.domain.universe.selected_instrument import SelectedInstrument
from core.infrastructure.config.universe_config import (
    ATRConfig,
    DiversificationConfig,
    OIConfig,
    SpreadConfig,
    VolumeConfig,
)

_log = logging.getLogger(__name__)


def rank_candidates(
    instruments: list[InstrumentData],
    max_slots: int,
    volume_cfg: VolumeConfig,
    oi_cfg: OIConfig,
    spread_cfg: SpreadConfig,
    atr_cfg: ATRConfig,
    diversification_cfg: DiversificationConfig,
    base_metadata: dict[int, dict[str, Any]] | None = None,
) -> list[SelectedInstrument]:
    """Rank survivors and return the top max_slots candidates.

    Args:
        instruments:         Survivors from Stages 1–7.
        max_slots:           Maximum number of candidates to emit.
        volume_cfg:          Volume weight configuration.
        oi_cfg:              OI weight configuration.
        spread_cfg:          Spread weight configuration.
        atr_cfg:             ATR weight configuration.
        diversification_cfg: Sector diversification limits.
        base_metadata:       Per-instrument filter metadata collected in Stages 1–7.

    Returns:
        Ranked list of SelectedInstrument, sorted by composite_score descending.
    """
    if not instruments:
        return []

    base_metadata = base_metadata or {}

    # Compute raw values for all survivors
    volumes = [inst.volume_ratio for inst in instruments]
    ois = [inst.atm_oi for inst in instruments]
    spreads = [inst.spread_pct or 0.0 for inst in instruments]
    atrs = [inst.atr_14_pct or 0.0 for inst in instruments]

    norm_volumes = _minmax_normalise(volumes)
    norm_ois = _minmax_normalise(ois)
    norm_spreads = _minmax_normalise(spreads)
    norm_atrs = _minmax_normalise(atrs)

    w_vol = volume_cfg.weight
    w_oi = oi_cfg.weight
    w_sp = spread_cfg.weight
    w_atr = atr_cfg.weight

    scored: list[tuple[float, InstrumentData]] = []
    for i, inst in enumerate(instruments):
        score = (
            w_vol * norm_volumes[i]
            + w_oi * norm_ois[i]
            + w_sp * (1.0 - norm_spreads[i])
            + w_atr * norm_atrs[i]
        )
        scored.append((score, inst))

    scored.sort(key=lambda t: t[0], reverse=True)

    selected: list[SelectedInstrument] = []
    sector_counts: dict[str, int] = {}
    rank = 1

    for composite_score, inst in scored:
        if len(selected) >= max_slots:
            break

        if diversification_cfg.enabled:
            count = sector_counts.get(inst.sector, 0)
            if count >= diversification_cfg.max_per_sector:
                meta = dict(base_metadata.get(inst.instrument_token, {}))
                meta["stage8_excluded"] = (
                    f"sector_cap: sector={inst.sector!r} "
                    f"count={count} >= max_per_sector={diversification_cfg.max_per_sector}"
                )
                _log.debug(
                    "sector_cap_excluded token=%d underlying=%s sector=%s count=%d",
                    inst.instrument_token,
                    inst.underlying,
                    inst.sector,
                    count,
                )
                continue
            sector_counts[inst.sector] = count + 1

        meta = dict(base_metadata.get(inst.instrument_token, {}))
        meta["stage8_composite_score"] = round(composite_score, 6)
        meta["stage8_rank"] = rank

        selected.append(
            SelectedInstrument(
                instrument_token=inst.instrument_token,
                underlying=inst.underlying,
                instrument_class=inst.instrument_class,
                expiry_date=inst.expiry_date,
                sector=inst.sector,
                composite_score=round(composite_score, 6),
                rank=rank,
                protected=False,
                filter_metadata=meta,
            )
        )
        rank += 1

    return selected


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _minmax_normalise(values: list[float]) -> list[float]:
    """Min-max normalise to [0, 1]. Returns 0.0 for all when range is 0."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span == 0.0:
        return [0.0] * len(values)
    return [(v - lo) / span for v in values]
