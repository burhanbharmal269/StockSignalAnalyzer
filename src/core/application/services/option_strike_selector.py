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
  Grade A (adjusted_score >= grade_a_min_score): sl=20%, target=35%
  Grade B (adjusted_score < grade_a_min_score or unknown): sl=15%, target=28%
  Thresholds are read from intraday_risk config — not hardcoded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.infrastructure.config.signal_config import IntradayRiskConfig

_log = logging.getLogger(__name__)

# Fallback constants used when no intraday_risk config is supplied
_DEFAULT_GRADE_A_MIN  = 65.0
_DEFAULT_SL_A         = 0.20
_DEFAULT_TARGET_A     = 0.35
_DEFAULT_SL_B         = 0.15
_DEFAULT_TARGET_B     = 0.28

_MIN_LTP              = 3.0    # ignore strikes with LTP below ₹3 (too cheap = noisy, bid-ask is huge % of premium)
_MIN_LTP_PCT          = 0.004  # also reject if premium < 0.4% of underlying (same reason)
_MAX_LTP_PCT          = 0.030  # reject if premium > 3% of underlying (overpaying for IV)
_MIN_OI_FLOOR         = 300    # minimum OI for liquid contract (raised from 100)
_MAX_STRIKE_SPREAD    = 2      # evaluate ATM ± this many strikes for ranking


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

        # Phase 3: rank candidates by OI within ATM ± _MAX_STRIKE_SPREAD
        strike_entry = self._best_contract(expiry_entries, underlying_price)
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
        sl     = round(entry * (1 - sl_pct), 2)
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
    ) -> dict[str, Any] | None:
        """Pick the most liquid contract within ATM ± _MAX_STRIKE_SPREAD strikes.

        Ranking: primary = OI descending (best liquidity proxy available),
        secondary = proximity to ATM (prefer at-the-money for delta).
        Falls back to absolute nearest if no entry meets the OI floor.
        """
        if not entries:
            return None

        strikes = sorted({float(e.get("strike") or 0) for e in entries})
        if not strikes:
            return None

        atm_strike = min(strikes, key=lambda s: abs(s - atm_price))
        atm_idx = strikes.index(atm_strike)
        low_idx  = max(0, atm_idx - _MAX_STRIKE_SPREAD)
        high_idx = min(len(strikes) - 1, atm_idx + _MAX_STRIKE_SPREAD)
        candidate_strikes = set(strikes[low_idx : high_idx + 1])

        candidates = [
            e for e in entries
            if float(e.get("strike") or 0) in candidate_strikes
            and int(e.get("oi") or 0) >= _MIN_OI_FLOOR
        ]

        if not candidates:
            # Fallback: absolute ATM ignoring OI floor
            return min(entries, key=lambda e: abs(float(e.get("strike") or 0) - atm_price))

        # Rank by (OI desc, distance to ATM asc)
        return max(
            candidates,
            key=lambda e: (
                int(e.get("oi") or 0),
                -abs(float(e.get("strike") or 0) - atm_price),
            ),
        )

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
        """Build Kite-style suffix: 26JUN26 + strike + CE/PE."""
        try:
            d = date.fromisoformat(expiry_str)
            month = d.strftime("%b").upper()
            day   = f"{d.day:02d}"
            year  = str(d.year)[2:]
            strike_str = int(strike) if strike == int(strike) else strike
            return f"{day}{month}{year}{strike_str}{opt_type}"
        except Exception:
            return f"{strike}{opt_type}"
