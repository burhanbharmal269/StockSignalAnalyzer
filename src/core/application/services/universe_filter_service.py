"""UniverseFilterService — Universe Selection Engine orchestrator (AD-USE-01).

Runs the 8-stage filter pipeline on a caller-supplied list of InstrumentData,
applies active-position protection, emits a UniverseSelected domain event,
and persists the result to Redis via IUniverseRepository.

Pipeline (all stages are pure functions; no I/O):
  Stage 1  EligibilityFilter  — class / DTE / ban check
  Stage 2  LiquidityFilter    — average traded value + active strikes
  Stage 3  VolumeRanker       — volume_ratio threshold + sort
  Stage 4  OIRanker           — near-ATM OI threshold + sort
  Stage 5  SpreadFilter       — bid-ask spread threshold
  Stage 6  IVFilter           — IV% and IVR range (skip if None)
  Stage 7  ATRFilter          — ATR-14% range (exclude if None)
  Stage 8  CandidateRanker    — composite score + sector cap + top-N

Active-position protection (additional requirement):
  Instruments whose underlying is in active_underlyings bypass all filter
  stages and are unconditionally included. They count toward max_candidates.
  Slots remaining = max_candidates - protected_count.

The service is non-blocking for downstream consumers. If universe.enabled is
False the pipeline is bypassed and an empty candidate list is returned.

Architecture constraints:
  - Scoring Engine (Phase 11): UNCHANGED
  - Confidence Engine (Phase 12): UNCHANGED
  - Risk Engine (Phase 13): UNCHANGED
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.domain.events.universe_events import UniverseSelected
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_universe_repository import IUniverseRepository
from core.domain.universe.instrument_data import InstrumentData
from core.domain.universe.selected_instrument import SelectedInstrument
from core.application.services.universe.atr_filter import apply_atr_filter
from core.application.services.universe.candidate_ranker import rank_candidates
from core.application.services.universe.eligibility_filter import apply_eligibility_filter
from core.application.services.universe.iv_filter import apply_iv_filter
from core.application.services.universe.liquidity_filter import apply_liquidity_filter
from core.application.services.universe.oi_ranker import apply_oi_filter
from core.application.services.universe.spread_filter import apply_spread_filter
from core.application.services.universe.volume_ranker import apply_volume_filter
from core.infrastructure.config.universe_config import UniverseConfig

_log = logging.getLogger(__name__)

_RETRY_DELAYS: tuple[float, ...] = (0.0, 0.2, 0.4)


class UniverseFilterService:
    """Universe Selection Engine — pre-pipeline instrument filter.

    Inject once at startup. Call select() on every evaluation cycle.
    """

    def __init__(
        self,
        universe_repo: IUniverseRepository,
        event_bus: IEventBus,
        config: UniverseConfig,
    ) -> None:
        self._repo = universe_repo
        self._event_bus = event_bus
        self._config = config

    async def select(
        self,
        instruments: list[InstrumentData],
        active_underlyings: frozenset[str] | None = None,
    ) -> UniverseSelected:
        """Run the full selection pipeline and return the UniverseSelected event.

        Args:
            instruments:       Full input instrument set (NSE FnO universe snapshot).
            active_underlyings: Underlyings with currently open positions. These
                                instruments bypass all filter stages.

        Returns:
            UniverseSelected domain event (also published via event_bus and
            persisted to Redis).
        """
        start_ns = time.monotonic_ns()
        active = active_underlyings or frozenset()

        if not self._config.enabled:
            event = UniverseSelected(
                instruments=(),
                total_eligible=0,
                total_filtered_out=len(instruments),
                evaluation_cycle_ms=0,
                protected_count=0,
                universe_enabled=False,
            )
            await self._publish_and_cache(event)
            return event

        protected_instruments, candidates = _split_protected(instruments, active)

        if len(protected_instruments) >= self._config.max_candidates:
            _log.warning(
                "universe_protected_count_exceeds_max_candidates "
                "protected=%d max_candidates=%d",
                len(protected_instruments),
                self._config.max_candidates,
            )

        event = self._run_pipeline(
            candidates=candidates,
            protected_instruments=protected_instruments,
            start_ns=start_ns,
        )

        await self._publish_and_cache(event)
        return event

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        candidates: list[InstrumentData],
        protected_instruments: list[InstrumentData],
        start_ns: int,
    ) -> UniverseSelected:
        cfg = self._config
        metadata: dict[int, dict[str, Any]] = {
            inst.instrument_token: {} for inst in candidates
        }

        # Stage 1 — Eligibility
        after_eligibility, excl1 = apply_eligibility_filter(candidates, cfg.eligibility)
        _record_exclusions(metadata, excl1, "stage1_eligibility")
        total_eligible = len(after_eligibility)

        # Stage 2 — Liquidity
        after_liquidity, excl2 = apply_liquidity_filter(after_eligibility, cfg.liquidity)
        _record_exclusions(metadata, excl2, "stage2_liquidity")

        # Stage 3 — Volume
        after_volume, excl3 = apply_volume_filter(after_liquidity, cfg.volume)
        _record_exclusions(metadata, excl3, "stage3_volume")

        # Stage 4 — OI
        after_oi, excl4 = apply_oi_filter(after_volume, cfg.oi)
        _record_exclusions(metadata, excl4, "stage4_oi")

        # Stage 5 — Spread
        after_spread, excl5 = apply_spread_filter(after_oi, cfg.spread)
        _record_exclusions(metadata, excl5, "stage5_spread")

        # Stage 6 — IV (graceful skip when data unavailable)
        after_iv, excl6 = apply_iv_filter(after_spread, cfg.iv)
        _record_exclusions(metadata, excl6, "stage6_iv")

        # Stage 7 — ATR (hard exclusion when data unavailable)
        after_atr, excl7 = apply_atr_filter(after_iv, cfg.atr)
        _record_exclusions(metadata, excl7, "stage7_atr")

        total_filtered_out = len(candidates) - len(after_atr)

        # Stage 8 — Rank + sector cap
        available_slots = max(0, cfg.max_candidates - len(protected_instruments))
        ranked = rank_candidates(
            instruments=after_atr,
            max_slots=available_slots,
            volume_cfg=cfg.volume,
            oi_cfg=cfg.oi,
            spread_cfg=cfg.spread,
            atr_cfg=cfg.atr,
            diversification_cfg=cfg.diversification,
            base_metadata=metadata,
        )

        # Build protected SelectedInstruments (bypass all stages, rank after ranked)
        protected_selected = _build_protected(
            protected_instruments, start_rank=len(ranked) + 1
        )

        all_selected = tuple(ranked) + tuple(protected_selected)

        elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000

        if not all_selected:
            _log.critical(
                "universe_selection_zero_candidates "
                "eligible=%d filtered_out=%d protected=%d",
                total_eligible,
                total_filtered_out,
                len(protected_instruments),
            )

        _log.info(
            "universe_selected candidates=%d protected=%d eligible=%d "
            "filtered_out=%d elapsed_ms=%d",
            len(ranked),
            len(protected_selected),
            total_eligible,
            total_filtered_out,
            elapsed_ms,
        )

        return UniverseSelected(
            instruments=all_selected,
            total_eligible=total_eligible,
            total_filtered_out=total_filtered_out,
            evaluation_cycle_ms=int(elapsed_ms),
            protected_count=len(protected_selected),
            universe_enabled=True,
        )

    # ------------------------------------------------------------------
    # Event publishing + Redis cache
    # ------------------------------------------------------------------

    async def _publish_and_cache(self, event: UniverseSelected) -> None:
        await self._publish_with_retry(event)
        try:
            await self._repo.save_selected(event, self._config.cache_ttl_seconds)
        except Exception:
            _log.warning("universe_cache_write_failed", exc_info=True)

    async def _publish_with_retry(self, event: UniverseSelected) -> None:
        for delay in _RETRY_DELAYS:
            if delay > 0:
                import asyncio
                await asyncio.sleep(delay)
            try:
                await self._event_bus.publish(event)
                return
            except Exception:
                _log.warning(
                    "universe_event_publish_retry event_type=%s", event.event_type,
                    exc_info=True,
                )
        _log.critical(
            "universe_event_publish_failed_all_retries event_id=%s", event.event_id
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_protected(
    instruments: list[InstrumentData],
    active_underlyings: frozenset[str],
) -> tuple[list[InstrumentData], list[InstrumentData]]:
    """Separate instruments into (protected, candidates) based on active underlyings."""
    protected: list[InstrumentData] = []
    candidates: list[InstrumentData] = []
    for inst in instruments:
        if inst.underlying in active_underlyings:
            protected.append(inst)
        else:
            candidates.append(inst)
    return protected, candidates


def _record_exclusions(
    metadata: dict[int, dict[str, Any]],
    exclusions: dict[int, str],
    stage_key: str,
) -> None:
    for token, reason in exclusions.items():
        if token in metadata:
            metadata[token][stage_key] = reason


def _build_protected(
    instruments: list[InstrumentData],
    start_rank: int,
) -> list[SelectedInstrument]:
    selected: list[SelectedInstrument] = []
    for i, inst in enumerate(instruments):
        selected.append(
            SelectedInstrument(
                instrument_token=inst.instrument_token,
                underlying=inst.underlying,
                instrument_class=inst.instrument_class,
                expiry_date=inst.expiry_date,
                sector=inst.sector,
                composite_score=0.0,
                rank=start_rank + i,
                protected=True,
                filter_metadata={"protected": "active_position"},
            )
        )
    return selected
