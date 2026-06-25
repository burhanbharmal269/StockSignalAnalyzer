"""PositionSizer — pure domain service for ATR + Kelly position sizing.

Implements two instrument-specific ATR formulas (PB-15):
  OPTION  : capital_at_risk / (option_premium × lot_size)
  FUTURE  : capital_at_risk / (atr_14 × atr_stop_multiplier × lot_size)

Kelly four-layer protection (A-7 / H-5):
  Layer 1 — sample guard     : sample_count < min_kelly_samples → fallback fraction
  Layer 2 — zero-loss edge   : loss_count == 0 → fallback fraction (no loss history)
  Layer 3 — raw_kelly floor  : max(0.0, win_rate − (1−win_rate)/win_loss_ratio)
  Layer 4 — hard cap         : min(lots, max_position_size_lots)

Final lot count = min(atr_lots_capped, kelly_lots_capped) × position_size_multiplier.
ATR is the conservative upper bound; Kelly is the statistical maximum.

No I/O.  No infrastructure imports.  No async code.
"""

from __future__ import annotations

import math

from core.domain.exceptions.risk import UnsupportedInstrumentClassError
from core.domain.risk.account_state import AccountState
from core.domain.risk.risk_decision import SizingResult
from core.domain.risk.risk_request import RiskRequest
from core.infrastructure.config.risk_config import RiskConfig

_SIZING_NOTE_LOW_SAMPLES: str = "below_minimum_samples"
_SIZING_NOTE_NO_LOSSES: str = "no_historical_losses"


class PositionSizer:
    """Stateless position sizing service.  All logic lives in compute()."""

    @staticmethod
    def compute(
        request: RiskRequest,
        account: AccountState,
        win_rate: float,
        win_loss_ratio: float,
        sample_count: int,
        loss_count: int,
        config: RiskConfig,
    ) -> SizingResult:
        """Compute final position size in lots.

        Args:
            request:        Pre-validated risk evaluation input.
            account:        Account snapshot (session_capital, position_size_multiplier).
            win_rate:       Historical win rate in (0, 1).  Used for Kelly formula.
            win_loss_ratio: avg_win / avg_loss.  Must be > 0 when loss_count > 0.
            sample_count:   Total historical trades used for Kelly computation.
            loss_count:     Count of losing trades in the historical sample.
            config:         RiskConfig v2.0; all limits and thresholds come from here.

        Returns:
            SizingResult with final lot count and sizing audit trail.

        Raises:
            UnsupportedInstrumentClassError: when request.instrument_class is not
                'OPTION' or 'FUTURE'.  RiskRequest validates this invariant, so this
                path is a defence-in-depth guard for direct callers.
        """
        session_cap = float(account.session_capital)
        assert session_cap > 0.0, "session_capital must be > 0 for position sizing"

        sizing_cfg = config.position_sizing
        capital_at_risk = session_cap * config.capital.risk_per_trade_pct / 100.0

        # ------------------------------------------------------------------
        # Instrument-specific cost-per-lot (ATR formula, PB-15)
        # ------------------------------------------------------------------
        if request.instrument_class == "OPTION":
            if request.option_premium is None:
                cost_per_lot = 0.0
            else:
                # Risk per lot = loss at stop loss, not full premium.
                # entry_price == option_premium for an option buy; stop_loss_price is the
                # premium stop level. Using SL distance gives correct lot count for
                # capital_at_risk: "how many lots where total SL loss = capital_at_risk."
                sl_distance = float(request.entry_price - request.stop_loss_price)
                cost_per_lot = max(sl_distance, 0.0) * request.lot_size
        elif request.instrument_class == "FUTURE":
            stop_distance = request.atr_14 * sizing_cfg.atr_stop_multiplier
            cost_per_lot = stop_distance * request.lot_size
        else:
            raise UnsupportedInstrumentClassError(
                f"PositionSizer does not support instrument_class={request.instrument_class!r}"
            )

        # ------------------------------------------------------------------
        # ATR lots (before hard cap)
        # ------------------------------------------------------------------
        atr_lots_raw: int = (
            math.floor(capital_at_risk / cost_per_lot)
            if cost_per_lot > 0.0
            else 0
        )

        # ------------------------------------------------------------------
        # Kelly four-layer protection
        # ------------------------------------------------------------------
        use_fallback = (sample_count < sizing_cfg.min_kelly_samples) or (loss_count == 0)

        if use_fallback:
            kelly_fraction_effective = (
                sizing_cfg.kelly_fraction * sizing_cfg.kelly_min_sample_fallback
            )
            sizing_note: str | None = (
                _SIZING_NOTE_LOW_SAMPLES
                if sample_count < sizing_cfg.min_kelly_samples
                else _SIZING_NOTE_NO_LOSSES
            )
            kelly_capital = session_cap * kelly_fraction_effective
        else:
            # Layer 3: raw Kelly formula with floor at 0
            if win_loss_ratio > 0.0:
                raw_kelly = win_rate - (1.0 - win_rate) / win_loss_ratio
            else:
                raw_kelly = 0.0
            raw_kelly = max(0.0, raw_kelly)
            kelly_fraction_effective = sizing_cfg.kelly_fraction
            sizing_note = None
            kelly_capital = session_cap * raw_kelly * kelly_fraction_effective

        kelly_lots_raw: int = (
            math.floor(kelly_capital / cost_per_lot)
            if cost_per_lot > 0.0
            else 0
        )

        # ------------------------------------------------------------------
        # Layer 4: hard cap on both formulas
        # ------------------------------------------------------------------
        atr_lots_pre_cap = atr_lots_raw
        kelly_lots_pre_cap = kelly_lots_raw
        atr_lots_capped = min(atr_lots_raw, sizing_cfg.max_position_size_lots)
        kelly_lots_capped = min(kelly_lots_raw, sizing_cfg.max_position_size_lots)

        # ATR is the conservative upper bound (A-9)
        base_lots = min(atr_lots_capped, kelly_lots_capped)

        # Graduated response multiplier applied last (A-9 / Constraint 13)
        final_lots = math.floor(base_lots * account.position_size_multiplier)

        return SizingResult(
            lots=final_lots,
            atr_lots_pre_cap=atr_lots_pre_cap,
            kelly_lots_pre_cap=kelly_lots_pre_cap,
            kelly_fraction_effective=kelly_fraction_effective,
            kelly_sample_count=sample_count,
            sizing_note=sizing_note,
        )
