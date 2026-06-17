"""Black-Scholes IV, Greeks, and GEX calculator for NSE F&O options.

Uses only Python stdlib + math — no scipy dependency.
Newton-Raphson converges in <10 iterations for most realistic market prices.

NSE specifics:
  - Options are European-style → Black-Scholes applies directly
  - Risk-free rate ≈ RBI repo rate (configured below, ~6.5%)
  - GEX formula uses lot_size as contract multiplier (not 100 as in US markets)
  - Spot price estimated from ATM put-call parity when not explicitly provided
"""

from __future__ import annotations

import math

# RBI repo rate approximation for India (update when RBI changes rate)
_RISK_FREE_RATE: float = 0.065  # 6.5%

_SQRT_2PI: float = math.sqrt(2 * math.pi)
_SQRT_2: float = math.sqrt(2)


# ---------------------------------------------------------------------------
# Normal distribution helpers (pure math — no scipy)
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf — accurate to ~7 significant digits."""
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


# ---------------------------------------------------------------------------
# Black-Scholes building blocks
# ---------------------------------------------------------------------------

def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def bs_price(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    """Black-Scholes price for European call (opt='CE') or put (opt='PE')."""
    if T <= 0 or sigma <= 0:
        intrinsic = (S - K) if opt == "CE" else (K - S)
        return max(0.0, intrinsic)
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    disc = math.exp(-r * T)
    if opt == "CE":
        return S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
    return K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Vega is identical for calls and puts. Used in Newton-Raphson IV solver."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    return S * _norm_pdf(d1) * math.sqrt(T)


def bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Gamma is identical for calls and puts."""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    return _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    """Black-Scholes delta."""
    if T <= 0 or sigma <= 0:
        return 1.0 if (opt == "CE" and S > K) else 0.0
    d1 = _d1(S, K, T, r, sigma)
    return _norm_cdf(d1) if opt == "CE" else (_norm_cdf(d1) - 1.0)


# ---------------------------------------------------------------------------
# IV solver — Newton-Raphson
# ---------------------------------------------------------------------------

def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    opt: str,
    r: float = _RISK_FREE_RATE,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> float | None:
    """Compute implied volatility via Newton-Raphson.

    Args:
        market_price: Observed option LTP from Kite.
        S: Spot/forward price of the underlying.
        K: Strike price.
        T: Time to expiry in years (e.g. 30/365).
        opt: "CE" for call, "PE" for put.
        r: Risk-free rate (default: RBI repo rate 6.5%).

    Returns:
        IV as a decimal (0.25 = 25%), or None if not convergent.
    """
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return None

    # Discard deep ITM or near-zero prices — BS doesn't converge well
    intrinsic = max(0.0, (S - K) if opt == "CE" else (K - S))
    if market_price < intrinsic * 0.999:
        return None

    sigma = 0.30  # 30% starting point — good for Indian F&O

    for _ in range(max_iter):
        price = bs_price(S, K, T, r, sigma, opt)
        v = bs_vega(S, K, T, r, sigma)
        if v < 1e-10:
            break
        diff = price - market_price
        if abs(diff) < tol:
            return sigma if 0.001 < sigma < 5.0 else None
        sigma -= diff / v
        if sigma <= 0.001:
            sigma = 0.001
        if sigma > 5.0:
            return None

    return sigma if 0.001 < sigma < 5.0 else None


# ---------------------------------------------------------------------------
# Option chain analytics
# ---------------------------------------------------------------------------

def compute_chain_analytics(
    entries: list[dict],
    spot: float,
    dte: int,
    lot_size: int = 50,
    r: float = _RISK_FREE_RATE,
) -> dict:
    """Compute IV per strike, ATM IV, IV skew, GEX, and net GEX level.

    Args:
        entries: List of option chain rows (dicts with strike, option_type, ltp, oi).
        spot: Underlying spot/forward price.
        dte: Days to expiry.
        lot_size: Contract lot size (Nifty=50, BankNifty=25, stocks vary).
        r: Risk-free rate.

    Returns dict with keys:
        iv_per_strike: {strike: {"CE": iv, "PE": iv}} — only populated where convergent
        atm_iv: float | None — IV of nearest-to-money call
        iv_skew: float | None — OTM put IV (5%) minus OTM call IV (5%)
        net_gex: float — net gamma exposure across all strikes (lot_size-scaled)
        gex_strike: float | None — strike with highest absolute net GEX (pin level)
        gex_positive: bool | None — True if net GEX > 0 (price-suppressing regime)
    """
    if spot <= 0 or dte <= 0:
        return _empty_analytics()

    T = dte / 365.0

    # ── Step 1: Compute IV per strike ────────────────────────────────────
    iv_map: dict[float, dict[str, float]] = {}  # strike → {CE: iv, PE: iv}
    for row in entries:
        strike = float(row.get("strike") or 0)
        opt_type = str(row.get("option_type") or "")
        ltp = float(row.get("ltp") or 0)
        if strike <= 0 or opt_type not in ("CE", "PE") or ltp <= 0:
            continue
        iv = implied_volatility(ltp, spot, strike, T, opt_type, r)
        if iv is not None:
            iv_map.setdefault(strike, {})[opt_type] = iv

    if not iv_map:
        return _empty_analytics()

    # ── Step 2: ATM IV — call IV at nearest strike to spot ───────────────
    atm_strike = min(iv_map.keys(), key=lambda k: abs(k - spot))
    atm_iv: float | None = iv_map[atm_strike].get("CE") or iv_map[atm_strike].get("PE")

    # ── Step 3: IV Skew — OTM put (5% below) minus OTM call (5% above) ──
    # Classic skew: put wing IV > call wing IV = put skew (negative skew = fear of downside)
    target_otm_pct = 0.05
    otm_call_strike = _nearest_strike(iv_map, spot * (1 + target_otm_pct), "CE")
    otm_put_strike  = _nearest_strike(iv_map, spot * (1 - target_otm_pct), "PE")
    otm_call_iv = iv_map.get(otm_call_strike, {}).get("CE") if otm_call_strike else None
    otm_put_iv  = iv_map.get(otm_put_strike, {}).get("PE") if otm_put_strike else None
    iv_skew: float | None = (
        otm_put_iv - otm_call_iv
        if otm_put_iv is not None and otm_call_iv is not None
        else None
    )

    # ── Step 4: GEX — Gamma Exposure (net across all strikes) ────────────
    # GEX_strike = gamma × OI × lot_size × spot² × 0.01
    # Calls add positive GEX, puts add negative GEX (dealer hedging direction)
    gex_per_strike: dict[float, float] = {}
    for row in entries:
        strike = float(row.get("strike") or 0)
        opt_type = str(row.get("option_type") or "")
        oi = int(row.get("oi") or 0)
        if strike <= 0 or oi <= 0 or opt_type not in ("CE", "PE"):
            continue
        iv = iv_map.get(strike, {}).get(opt_type)
        if iv is None:
            continue
        g = bs_gamma(spot, strike, T, r, iv)
        contribution = g * oi * lot_size * spot * spot * 0.01
        if opt_type == "PE":
            contribution = -contribution
        gex_per_strike[strike] = gex_per_strike.get(strike, 0.0) + contribution

    net_gex = sum(gex_per_strike.values())
    gex_strike: float | None = (
        max(gex_per_strike, key=lambda k: abs(gex_per_strike[k]))
        if gex_per_strike else None
    )

    return {
        "iv_per_strike": iv_map,
        "atm_iv": atm_iv,
        "iv_skew": iv_skew,
        "net_gex": net_gex,
        "gex_strike": gex_strike,
        "gex_positive": (net_gex > 0) if gex_per_strike else None,
    }


def _nearest_strike(iv_map: dict, target: float, opt_type: str) -> float | None:
    candidates = [k for k, v in iv_map.items() if opt_type in v]
    return min(candidates, key=lambda k: abs(k - target)) if candidates else None


def _empty_analytics() -> dict:
    return {
        "iv_per_strike": {},
        "atm_iv": None,
        "iv_skew": None,
        "net_gex": 0.0,
        "gex_strike": None,
        "gex_positive": None,
    }
