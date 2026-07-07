"""OptionStrikeSelector — translates an equity signal into a specific option play.

Given:
  - direction:  "LONG" → buy CE  |  "SHORT" → buy PE
  - underlying price (close)
  - option chain entries from option_chain_snapshots
  - nearest expiry in the chain

Selects:
  - Best liquid contract near ATM for the correct side
  - Ranks candidates (ATM ± 1 strike) by OI — highest liquidity wins
  - Falls back to absolute ATM if no candidate meets the OI floor

Produces an OptionPlay with:
  - option_type:   CE or PE
  - option_strike: selected strike price
  - option_expiry: nearest expiry date string (YYYY-MM-DD)
  - option_symbol: Kite trading symbol (e.g. HDFCBANK26JUN1750CE)
  - entry:  option LTP
  - sl:     entry × (1 - sl_pct)
  - target: entry × (1 + target_pct)

SL / target sizing:
  Grade A (adjusted_score >= grade_a_min_score): sl=25%, target=55%  (2.2:1 R:R)
  Grade B (adjusted_score < grade_a_min_score or unknown): sl=20%, target=42%  (2.1:1 R:R)
  After 13:30 IST: target capped at 35% regardless of grade (time constraint).
  Thresholds are read from intraday_risk config — not hardcoded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time as _dtime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from core.infrastructure.config.signal_config import IntradayRiskConfig

_log = logging.getLogger(__name__)


# ── Phase 22 §2 — Strike Quality Score ───────────────────────────────────────

@dataclass
class StrikeScore:
    """Weighted quality score (0–100) for a single option contract."""
    strike: float
    opt_type: str
    ltp: float
    oi: int
    total: float = 0.0
    components: dict[str, float] = field(default_factory=dict)

    def log_selection(self, symbol: str, underlying_price: float) -> None:
        dist_pct = abs(self.strike - underlying_price) / underlying_price * 100
        _log.info(
            "strike_ranking.selected symbol=%s %s strike=%.0f ltp=%.2f oi=%d "
            "score=%.1f/100 dist=%.1f%% components=%s",
            symbol, self.opt_type, self.strike, self.ltp, self.oi,
            self.total, dist_pct,
            " ".join(f"{k}={v:.1f}" for k, v in self.components.items()),
        )


def _score_strike(
    entry: dict[str, Any],
    atm_price: float,
    all_entries: list[dict[str, Any]],
    opt_type: str,
) -> StrikeScore:
    """Compute weighted Strike Quality Score (0–100) for one contract."""
    strike = float(entry.get("strike") or 0)
    ltp    = float(entry.get("ltp") or 0)
    oi     = int(entry.get("oi") or 0)
    volume = int(entry.get("volume") or 0)

    # Max OI and volume in the same-side chain (for normalisation)
    side = [e for e in all_entries if str(e.get("option_type", "")).upper() == opt_type]
    max_oi  = max((int(e.get("oi") or 0) for e in side), default=1) or 1
    max_vol = max((int(e.get("volume") or 0) for e in side), default=1) or 1

    # 1. OI Score (0–25): liquidity proxy
    oi_score = min(oi / max_oi * 25, 25)

    # 2. Volume Score (0–15)
    vol_score = min(volume / max_vol * 15, 15) if max_vol > 0 else 0

    # 3. Distance from ATM (0–20): closer = better
    dist_pct = abs(strike - atm_price) / atm_price * 100 if atm_price > 0 else 100
    dist_score = max(0, 20 - dist_pct * 4)

    # 4. Premium suitability (0–15): sweet spot ₹10–₹150
    if 10 <= ltp <= 150:
        prem_score = 15.0
    elif 4 <= ltp < 10 or 150 < ltp <= 300:
        prem_score = 8.0
    else:
        prem_score = 2.0

    # 5. Delta suitability (0–15): 0.25–0.45 is ideal for directional options
    if atm_price > 0:
        moneyness = (strike - atm_price) / atm_price
        if opt_type == "PE":
            moneyness = -moneyness
        # Rough delta estimate: ATM ≈ 0.50, each 1% OTM ≈ -0.05 delta
        approx_delta = max(0.05, min(0.95, 0.50 - moneyness * 5))
        if 0.25 <= approx_delta <= 0.45:
            delta_score = 15.0
        elif 0.20 <= approx_delta < 0.25 or 0.45 < approx_delta <= 0.55:
            delta_score = 10.0
        else:
            delta_score = 4.0
    else:
        delta_score = 7.5

    # 6. Slippage estimate (0–10): low slippage = high OI (inverse)
    slip_score = min(oi / 5000 * 10, 10)

    total = oi_score + vol_score + dist_score + prem_score + delta_score + slip_score
    return StrikeScore(
        strike=strike,
        opt_type=opt_type,
        ltp=ltp,
        oi=oi,
        total=round(total, 2),
        components={
            "oi": round(oi_score, 1),
            "vol": round(vol_score, 1),
            "dist": round(dist_score, 1),
            "prem": round(prem_score, 1),
            "delta": round(delta_score, 1),
            "slip": round(slip_score, 1),
        },
    )

# Fallback constants used when no intraday_risk config is supplied
_DEFAULT_GRADE_A_MIN  = 65.0
_DEFAULT_SL_A         = 0.20
_DEFAULT_TARGET_A     = 0.35
_DEFAULT_SL_B         = 0.15
_DEFAULT_TARGET_B     = 0.28

_MIN_LTP              = 4.0    # ignore strikes below ₹4: ATM 8-DTE options trade at ~2-3% of underlying, so ₹200+ stocks can have ~₹4-6 ATM premiums
_MIN_LTP_PCT          = 0.004  # also reject if premium < 0.4% of underlying (catches very low-priced stocks)
_MAX_LTP_PCT          = 0.060  # reject if premium > 6% of underlying; 3% was incorrectly
                                # filtering ATM options for mid/high-priced stocks at 29 DTE
                                # (e.g. FORCEMOT ₹17986 ATM PE = ₹450-600 = 2.5-3.3% → filtered,
                                # forcing PE 17000 at 5.5% OTM). IV overpayment is already gated
                                # upstream by the iv_percentile scanner gate.
_MIN_OI_FLOOR         = 500    # raised 300→500: tighter liquidity gate; sub-500 OI = wide spreads, poor fills
_MAX_STRIKE_SPREAD    = 2      # evaluate ATM ± this many strikes for ranking
_MIN_SL_BUFFER        = 1.0    # minimum ₹ gap between entry and SL; 25% of ₹4 option = ₹1.00 buffer — adequate for NSE tick size
_LATE_SESSION_START   = _dtime(13, 30)   # after this, reduce target to 35% — < 2 hours to close
_LATE_TARGET_CAP      = 0.35             # cap on target_pct after 13:30 IST
_LATE_SL_CAP          = 0.17            # matching SL cap: 35% target / 17% SL ≈ 2.1:1 R:R (maintains design minimum)


@dataclass(frozen=True)
class OptionPlay:
    option_type:   str           # "CE" or "PE"
    option_strike: float
    option_expiry: str           # "YYYY-MM-DD"
    option_symbol: str           # e.g. HDFCBANK26JUN1750CE
    entry:         float
    sl:            float
    target:        float


class OptionStrikeSelector:
    """Stateless service — call select() per signal."""

    def select(
        self,
        direction: str,
        underlying_price: float,
        chain_entries: list[dict[str, Any]],
        min_dte: int = 0,
        max_dte: int = 3,
        adjusted_score: float | None = None,
        intraday_risk_cfg: "IntradayRiskConfig | None" = None,
    ) -> OptionPlay | None:
        """Return the best option play or None if chain is empty / illiquid.

        chain_entries: list of dicts with keys:
            strike, option_type, ltp, oi, expiry (date or str), underlying
        min_dte / max_dte: preferred DTE window. Falls back gracefully so a
            contract is always returned when the chain has any liquid strikes.
        adjusted_score: engine score used to determine Grade A/B sizing.
        intraday_risk_cfg: risk config from signal.yaml intraday_risk section.
        """
        if not chain_entries:
            return None

        opt_type = "CE" if direction == "LONG" else "PE"
        # Premium quality filter: reject options that are too cheap (noisy, wide spread)
        # or too expensive (overpaying for IV). Both checks protect option buyers.
        _min_premium = max(_MIN_LTP, underlying_price * _MIN_LTP_PCT)
        _max_premium = underlying_price * _MAX_LTP_PCT if underlying_price > 0 else float("inf")
        side_entries = [
            e for e in chain_entries
            if str(e.get("option_type", "")).upper() == opt_type
            and float(e.get("ltp") or 0) >= _min_premium
            and float(e.get("ltp") or 0) <= _max_premium
            and int(e.get("oi") or 0) > 0
        ]
        if not side_entries:
            return None

        nearest_expiry = self._nearest_expiry(side_entries, min_dte=min_dte, max_dte=max_dte)
        expiry_entries = [
            e for e in side_entries
            if self._expiry_str(e) == nearest_expiry
        ]
        if not expiry_entries:
            return None

        # Phase 22 §2: rank by Strike Quality Score within ATM ± _MAX_STRIKE_SPREAD
        underlying = str(expiry_entries[0].get("underlying", "?")) if expiry_entries else "?"
        strike_entry = self._best_contract(expiry_entries, underlying_price, symbol=underlying)
        if strike_entry is None:
            return None

        entry  = float(strike_entry.get("ltp") or 0)
        strike = float(strike_entry.get("strike") or 0)
        symbol = str(strike_entry.get("underlying", "")) + self._contract_suffix(
            nearest_expiry, strike, opt_type
        )

        if entry < _MIN_LTP:
            return None

        # Grade A/B sizing from config (Phase 5)
        sl_pct, target_pct = self._grade_sizing(adjusted_score, intraday_risk_cfg)

        # Time-based target + SL cap: signals after 13:30 IST have < 2 hours to
        # market close. Cap target at 35% AND tighten SL to maintain ≥2:1 R:R.
        # Without the SL cap, Grade A gives 35%/25% = 1.4:1 R:R — below design floor.
        # 35% target / 17% SL ≈ 2.1:1 — preserves minimum design R:R in late session.
        _now_ist = datetime.now(ZoneInfo("Asia/Kolkata")).time()
        if _now_ist >= _LATE_SESSION_START and target_pct > _LATE_TARGET_CAP:
            target_pct = _LATE_TARGET_CAP
            if sl_pct > _LATE_SL_CAP:
                sl_pct = _LATE_SL_CAP

        sl = round(entry * (1 - sl_pct), 2)

        # Reject contracts where SL absolute buffer is too tight: the bid-ask spread
        # on a ₹4 option can be ₹0.25-0.50; a 17-25% SL on a ₹4 option = ₹0.68-1.00
        # — market makers will trigger it without any real adverse move.
        if (entry - sl) < _MIN_SL_BUFFER:
            _log.debug(
                "option_selector.sl_too_tight symbol=%s entry=%.2f sl=%.2f buffer=%.2f min=%.2f",
                strike_entry.get("underlying", "?"), entry, sl, entry - sl, _MIN_SL_BUFFER,
            )
            return None

        target = round(entry * (1 + target_pct), 2)

        return OptionPlay(
            option_type=opt_type,
            option_strike=strike,
            option_expiry=nearest_expiry,
            option_symbol=symbol,
            entry=round(entry, 2),
            sl=max(sl, 0.05),
            target=target,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _grade_sizing(
        score: float | None,
        cfg: "IntradayRiskConfig | None",
    ) -> tuple[float, float]:
        """Return (sl_pct, target_pct) based on signal grade."""
        if cfg is not None:
            grade_a = score is not None and score >= cfg.grade_a_min_score
            sl     = cfg.grade_a_sl_pct     if grade_a else cfg.grade_b_sl_pct
            target = cfg.grade_a_target_pct if grade_a else cfg.grade_b_target_pct
        else:
            grade_a = score is not None and score >= _DEFAULT_GRADE_A_MIN
            sl     = _DEFAULT_SL_A     if grade_a else _DEFAULT_SL_B
            target = _DEFAULT_TARGET_A if grade_a else _DEFAULT_TARGET_B
        return sl, target

    @staticmethod
    def _best_contract(
        entries: list[dict[str, Any]],
        atm_price: float,
        symbol: str = "?",
    ) -> dict[str, Any] | None:
        """Phase 22 §2: Pick highest Strike Quality Score within ATM ± spread.

        Uses weighted ranking (OI, volume, distance, premium, delta, slippage)
        instead of simple OI-descending sort. Logs selection reasoning.
        Falls back to absolute ATM if no candidate meets the OI floor.
        """
        if not entries:
            return None

        strikes = sorted({float(e.get("strike") or 0) for e in entries})
        if not strikes:
            return None

        atm_strike = min(strikes, key=lambda s: abs(s - atm_price))
        atm_idx    = strikes.index(atm_strike)
        low_idx    = max(0, atm_idx - _MAX_STRIKE_SPREAD)
        high_idx   = min(len(strikes) - 1, atm_idx + _MAX_STRIKE_SPREAD)
        candidate_strikes = set(strikes[low_idx : high_idx + 1])

        candidates = [
            e for e in entries
            if float(e.get("strike") or 0) in candidate_strikes
            and int(e.get("oi") or 0) >= _MIN_OI_FLOOR
        ]

        if not candidates:
            # Fallback: absolute ATM ignoring OI floor
            best = min(entries, key=lambda e: abs(float(e.get("strike") or 0) - atm_price))
            _log.debug(
                "strike_ranking.fallback_atm symbol=%s strike=%.0f oi=%d (no candidates met OI floor)",
                symbol, float(best.get("strike") or 0), int(best.get("oi") or 0),
            )
            return best

        # Phase 22 §2: compute Strike Quality Score for each candidate
        opt_type = str(candidates[0].get("option_type", "CE")).upper()
        scored = [_score_strike(e, atm_price, entries, opt_type) for e in candidates]
        best_score = max(scored, key=lambda s: s.total)

        # Find the matching entry
        best_entry = next(
            (e for e in candidates if float(e.get("strike") or 0) == best_score.strike),
            candidates[0],
        )
        best_score.log_selection(symbol, atm_price)
        return best_entry

    @staticmethod
    def _expiry_str(entry: dict[str, Any]) -> str:
        raw = entry.get("expiry")
        if isinstance(raw, date):
            return raw.isoformat()
        if isinstance(raw, str):
            return raw[:10]
        return ""

    def _nearest_expiry(
        self,
        entries: list[dict[str, Any]],
        min_dte: int = 0,
        max_dte: int = 3,
    ) -> str:
        today = datetime.utcnow().date()
        expiries = sorted(
            {self._expiry_str(e) for e in entries if self._expiry_str(e) >= today.isoformat()}
        )
        if not expiries:
            return ""

        def _dte(exp_str: str) -> int:
            return (date.fromisoformat(exp_str) - today).days

        # 1. Prefer expiries inside the [min_dte, max_dte] window
        in_window = [e for e in expiries if min_dte <= _dte(e) <= max_dte]
        if in_window:
            return in_window[0]

        # 2. Fall back to nearest with DTE >= min_dte
        beyond_min = [e for e in expiries if _dte(e) >= min_dte]
        if beyond_min:
            return beyond_min[0]

        # 3. Final fallback: absolute nearest
        return expiries[0]

    @staticmethod
    def _contract_suffix(expiry_str: str, strike: float, opt_type: str) -> str:
        """Build Kite-style suffix: YYMONSTRIKE + CE/PE (e.g. 26JUL1750CE)."""
        try:
            d = date.fromisoformat(expiry_str)
            month = d.strftime("%b").upper()
            year  = str(d.year)[2:]
            strike_str = int(strike) if strike == int(strike) else strike
            return f"{year}{month}{strike_str}{opt_type}"
        except Exception:
            return f"{strike}{opt_type}"
