"""OptionStrikeSelector — translates an equity signal into a specific option play.

Given:
  - direction:  "LONG" → buy CE  |  "SHORT" → buy PE
  - underlying price (close)
  - option chain entries from option_chain_snapshots
  - nearest expiry in the chain

Selects:
  - ATM strike (closest to current price) for the correct side
  - Falls back to 1-strike OTM if ATM has zero LTP

Produces an OptionPlay with:
  - option_type:   CE or PE
  - option_strike: selected strike price
  - option_expiry: nearest expiry date string (YYYY-MM-DD)
  - option_symbol: Kite trading symbol (e.g. HDFCBANK26JUN1750CE)
  - entry:  option LTP
  - sl:     entry × (1 - SL_PCT)      default 30%
  - target: entry × (1 + TARGET_PCT)  default 60%  → 2:1 R:R

SL / target are expressed in option premium terms.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

_log = logging.getLogger(__name__)

_SL_PCT     = 0.30   # stop-loss  = 30% of option premium
_TARGET_PCT = 0.60   # target     = 60% of option premium (2:1 R:R)
_MIN_LTP    = 1.0    # ignore strikes with LTP below this (illiquid)


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
        min_dte: int = 2,
        max_dte: int = 15,
    ) -> OptionPlay | None:
        """Return the best option play or None if chain is empty / illiquid.

        chain_entries: list of dicts with keys:
            strike, option_type, ltp, oi, expiry (date or str), underlying
        min_dte / max_dte: preferred DTE window. Falls back gracefully so a
            contract is always returned when the chain has any liquid strikes.
        """
        if not chain_entries:
            return None

        opt_type = "CE" if direction == "LONG" else "PE"
        side_entries = [
            e for e in chain_entries
            if str(e.get("option_type", "")).upper() == opt_type
            and float(e.get("ltp") or 0) >= _MIN_LTP
            and int(e.get("oi") or 0) > 0   # exclude ghost/adjusted contracts with zero OI
        ]
        if not side_entries:
            return None

        # Choose preferred expiry within DTE window
        nearest_expiry = self._nearest_expiry(side_entries, min_dte=min_dte, max_dte=max_dte)
        expiry_entries = [
            e for e in side_entries
            if self._expiry_str(e) == nearest_expiry
        ]
        if not expiry_entries:
            return None

        # ATM = strike closest to current price
        strike_entry = min(
            expiry_entries,
            key=lambda e: abs(float(e.get("strike") or 0) - underlying_price),
        )

        entry  = float(strike_entry.get("ltp") or 0)
        strike = float(strike_entry.get("strike") or 0)
        symbol = str(strike_entry.get("underlying", "")) + self._contract_suffix(
            nearest_expiry, strike, opt_type
        )

        if entry < _MIN_LTP:
            return None

        sl     = round(entry * (1 - _SL_PCT), 2)
        target = round(entry * (1 + _TARGET_PCT), 2)

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
        min_dte: int = 2,
        max_dte: int = 15,
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

        # 2. Fall back to nearest with DTE >= min_dte (avoids same/next-day gamma)
        beyond_min = [e for e in expiries if _dte(e) >= min_dte]
        if beyond_min:
            return beyond_min[0]

        # 3. Final fallback: absolute nearest (preserves existing behaviour)
        return expiries[0]

    @staticmethod
    def _contract_suffix(expiry_str: str, strike: float, opt_type: str) -> str:
        """Build the Kite-style suffix: DDMMMYYYY → 26JUN2026 → 26JUN1750CE."""
        try:
            d = date.fromisoformat(expiry_str)
            month = d.strftime("%b").upper()   # JUN
            day   = f"{d.day:02d}"
            year  = str(d.year)[2:]            # last 2 digits
            strike_str = int(strike) if strike == int(strike) else strike
            return f"{day}{month}{year}{strike_str}{opt_type}"
        except Exception:
            return f"{strike}{opt_type}"
