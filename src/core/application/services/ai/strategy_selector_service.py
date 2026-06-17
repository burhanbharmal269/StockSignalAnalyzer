"""StrategySelectorService — AI-assisted strategy and parameter selection.

Given a symbol's profile (sector, volatility, liquidity) and current market regime,
recommends which strategy to run and with which parameters.
Falls back to rule-based selection when AI is unavailable.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.strategies.base_strategy import IStrategy
    from core.infrastructure.ai.ai_client import AIClient

_log = logging.getLogger(__name__)

_SYSTEM = """You are an algorithmic trading strategy advisor for NSE/BSE markets.
Given symbol characteristics and market regime, recommend the best strategy and parameters.
Respond ONLY with this JSON:
{
  "strategy": "<strategy_name>",
  "confidence": <float 0-1>,
  "params": {<strategy-specific params>},
  "reasoning": "<1 sentence>"
}
Valid strategies: EMA_TREND, VWAP_PULLBACK, ORB, MOMENTUM, OI_STRATEGY, REGIME_ADAPTIVE"""


class StrategySelectorService:
    def __init__(
        self,
        ai_client: AIClient,
        strategies: list[IStrategy],
    ) -> None:
        self._ai = ai_client
        self._strategy_map = {s.name: s for s in strategies}

    async def select(
        self,
        symbol: str,
        regime: str,
        timeframe: str,
        symbol_meta: dict | None = None,
    ) -> dict:
        """Return selected strategy name + params. Falls back to rule-based."""
        context = {
            "symbol": symbol,
            "regime": regime,
            "timeframe": timeframe,
            "meta": symbol_meta or {},
        }

        raw = await self._ai.complete(_SYSTEM, json.dumps(context))
        if raw:
            try:
                text = raw.strip()
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                result = json.loads(text.strip())
                # Validate strategy name
                if result.get("strategy") in self._strategy_map:
                    return result
            except Exception as exc:
                _log.debug("strategy_selector.parse_error err=%s", exc)

        return self._rule_based_select(regime, timeframe)

    def _rule_based_select(self, regime: str, timeframe: str) -> dict:
        """Deterministic fallback — no AI dependency."""
        if regime in ("TRENDING_UP", "TRENDING_DOWN"):
            if timeframe in ("5m", "15m"):
                return {
                    "strategy": "VWAP_PULLBACK",
                    "confidence": 0.65,
                    "params": {},
                    "reasoning": "Intraday trend; VWAP pullbacks are high-probability entries.",
                }
            return {
                "strategy": "EMA_TREND",
                "confidence": 0.70,
                "params": {"fast": 20, "mid": 50, "slow": 200},
                "reasoning": "Strong trend; ride EMA alignment.",
            }

        if regime == "RANGING":
            return {
                "strategy": "VWAP_PULLBACK",
                "confidence": 0.60,
                "params": {},
                "reasoning": "Range-bound market; mean-reversion to VWAP.",
            }

        if regime == "VOLATILE":
            return {
                "strategy": "MOMENTUM",
                "confidence": 0.55,
                "params": {"rsi_bull": 65, "rsi_bear": 35},
                "reasoning": "High volatility; momentum breakouts more likely.",
            }

        # Opening session — prefer ORB on intraday timeframes
        if timeframe in ("5m", "15m"):
            return {
                "strategy": "ORB",
                "confidence": 0.60,
                "params": {"orb_candles": 6},
                "reasoning": "Unknown regime; ORB is session-start default.",
            }

        return {
            "strategy": "REGIME_ADAPTIVE",
            "confidence": 0.55,
            "params": {},
            "reasoning": "Unknown regime; adaptive strategy auto-detects.",
        }

    async def recommend_for_symbol(
        self,
        symbol: str,
        regime: str,
        timeframe: str = "15m",
        is_index: bool = False,
        is_fo: bool = True,
        sector: str | None = None,
    ) -> dict:
        """High-level recommendation with full context."""
        meta = {
            "is_index": is_index,
            "is_fo": is_fo,
            "sector": sector,
        }
        # OI strategy is best for indices and high-OI F&O stocks
        if is_index:
            meta["note"] = "index — OI strategy applicable"

        result = await self.select(symbol, regime, timeframe, meta)
        result["symbol"] = symbol
        result["regime"] = regime
        result["timeframe"] = timeframe
        return result
