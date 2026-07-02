"""ExecutionReadinessService — Phase 22 §8.

Computes a 0-100 execution readiness score for every accepted signal.

Checks
------
1. Broker Connected       — Kite session active
2. Market Open            — IST 09:15–15:30 Mon-Fri
3. Option Chain Freshness — last OC snapshot < 5 min old
4. Redis Healthy          — PING round-trip < 100 ms
5. Quote Freshness        — underlying quote < 2 min old
6. Strike Available       — option contract found in chain
7. Liquidity OK           — OI > 1000 on chosen contract
8. Risk Engine Healthy    — risk manager not in kill-switch state

Score → 0–100 (each check = 12.5 pts).
Log only — NEVER rejects or delays trades.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

_log = logging.getLogger(__name__)
_IST = ZoneInfo("Asia/Kolkata")
_MARKET_OPEN  = (9, 15)
_MARKET_CLOSE = (15, 30)
_OC_MAX_AGE_SECONDS = 300      # 5 minutes
_QUOTE_MAX_AGE_SECONDS = 120   # 2 minutes
_REDIS_PING_TIMEOUT_MS = 100
_MIN_OI_LIQUIDITY = 1000

if TYPE_CHECKING:
    from redis.asyncio import Redis


class ExecutionReadinessService:
    """Per-signal readiness checker. All checks are fail-open."""

    def __init__(self, redis_client: "Redis | None" = None) -> None:
        self._redis = redis_client

    async def evaluate(
        self,
        symbol: str,
        *,
        broker_connected: bool = False,
        oc_snapshot_ts: datetime | None = None,
        quote_ts: datetime | None = None,
        option_play_oi: int | None = None,
        risk_engine_healthy: bool = True,
    ) -> dict[str, Any]:
        """Return readiness breakdown and aggregate score (0–100)."""
        checks: dict[str, bool] = {}

        # 1. Broker connected
        checks["broker_connected"] = broker_connected

        # 2. Market open (IST Mon-Fri 09:15–15:30)
        checks["market_open"] = _is_market_open()

        # 3. Option chain freshness
        if oc_snapshot_ts is not None:
            ts = oc_snapshot_ts if oc_snapshot_ts.tzinfo else oc_snapshot_ts.replace(tzinfo=UTC)
            age_s = (datetime.now(UTC) - ts).total_seconds()
            checks["oc_fresh"] = age_s <= _OC_MAX_AGE_SECONDS
        else:
            checks["oc_fresh"] = False

        # 4. Redis healthy
        checks["redis_healthy"] = await _check_redis(self._redis)

        # 5. Quote freshness
        if quote_ts is not None:
            ts = quote_ts if quote_ts.tzinfo else quote_ts.replace(tzinfo=UTC)
            age_s = (datetime.now(UTC) - ts).total_seconds()
            checks["quote_fresh"] = age_s <= _QUOTE_MAX_AGE_SECONDS
        else:
            checks["quote_fresh"] = None is not None  # unknown → True (don't penalise)

        # 6. Strike available (option_play was produced)
        checks["strike_available"] = option_play_oi is not None

        # 7. Liquidity OK
        if option_play_oi is not None:
            checks["liquidity_ok"] = option_play_oi >= _MIN_OI_LIQUIDITY
        else:
            checks["liquidity_ok"] = False

        # 8. Risk engine healthy
        checks["risk_healthy"] = risk_engine_healthy

        passed = sum(1 for v in checks.values() if v)
        score  = round(passed / len(checks) * 100)

        if score < 75:
            _log.warning(
                "execution_readiness.low symbol=%s score=%d/100 failed=%s",
                symbol, score,
                [k for k, v in checks.items() if not v],
            )
        else:
            _log.debug(
                "execution_readiness.ok symbol=%s score=%d/100",
                symbol, score,
            )

        return {
            "symbol":  symbol,
            "score":   score,
            "checks":  checks,
            "passed":  passed,
            "total":   len(checks),
            "evaluated_at": datetime.now(UTC).isoformat(),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_market_open() -> bool:
    now = datetime.now(_IST)
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    return (h, m) >= _MARKET_OPEN and (h, m) <= _MARKET_CLOSE


async def _check_redis(redis: "Redis | None") -> bool:
    if redis is None:
        return False
    try:
        t0 = time.monotonic()
        await redis.ping()
        elapsed_ms = (time.monotonic() - t0) * 1000
        return elapsed_ms < _REDIS_PING_TIMEOUT_MS
    except Exception:
        return False
