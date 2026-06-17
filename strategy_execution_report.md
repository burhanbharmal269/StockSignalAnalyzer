# Strategy Execution Report — Phase 6

**Date**: 2026-06-16

---

## Scoring Components (Strategy Engine)

The system uses a **component-based scoring framework** (not individual strategy classes). Each component is an `IScoreComponent` evaluated independently.

### Component Status

| Component | Max Weight | Data Source | Status | Produces Signal |
|-----------|-----------|-------------|--------|----------------|
| `OIBuildupComponent` | 25 | OI feed (NSE FO) | ⚠️ Unavailable (no OI feed) | ❌ |
| `TrendComponent` | 20 | OHLCV candles | ✅ Active | ✅ |
| `OptionChainComponent` | 20 | Option chain | ⚠️ Unavailable (no OC feed) | ❌ |
| `VolumeComponent` | 15 | OHLCV candles | ✅ Active | ✅ |
| `VWAPComponent` | 10 | OHLCV candles | ✅ Active | ✅ |
| `SentimentComponent` | 5 | NeutralSentimentProvider | ⚠️ Always NEUTRAL | ⚠️ |
| `IVAnalysisComponent` | 5 | Options IV (NSE) | ⚠️ Unavailable | ❌ |

### TrendComponent — Execution Detail
- **Gate**: ADX < 15 → NEUTRAL (lowered from 20)
- **Score Tiers**: ADX 15–25 = 8 pts, 25–28 = 12 pts, 28–32 = 16 pts, 32–36 = 18 pts, >36 = 20 pts
- **DI Spread**: 5-10 = +3, 10-15 = +5, >15 = +7
- **EMA Alignment**: Full stack (20>50>200) = +5, partial = +2
- **Supertrend**: Now computed (sign of close vs VWAP) = +3
- **RSI Gate**: RSI 45–75 for LONG = +1
- **Produces**: Entry direction (LONG/SHORT), conviction

### VolumeComponent — Execution Detail
- **Score Tiers**: vol_ratio <0.5 = 3 pts, 0.5–1.0 = 6, 1.0–1.5 = 9, 1.5–2.0 = 12, ≥2.0 = 15
- **OBV**: Not computed from OHLCV history → 0 pts
- **Cumulative Delta**: Not computed → 0 pts
- **VPOC**: Not computed → 0 pts
- **Produces**: Direction based on volume with price direction; strength of volume

### VWAPComponent — Execution Detail
- **Mode A** (SIDEWAYS/HIGH_VOL): VWAP mean-reversion — deviation > 1.5σ = 10 pts
- **Mode B** (TRENDING): VWAP pullback — price above/below VWAP = 6 pts, bounce from VWAP = 10 pts
- **Produces**: Direction + conviction from VWAP position

---

## Phase 28 Strategies (PaperTradingDaemon — NOT ACTIVATED)

These 6 strategy classes exist in `core/domain/strategies/` but are **NOT wired into the main signal pipeline**:

| Strategy | File | Actually Called | Notes |
|----------|------|----------------|-------|
| EMATrendStrategy | `ema_trend_strategy.py` | ❌ NOT called | Only by PaperTradingDaemon |
| VWAPPullbackStrategy | `vwap_pullback_strategy.py` | ❌ NOT called | Only by PaperTradingDaemon |
| ORBStrategy | `orb_strategy.py` | ❌ NOT called | Only by PaperTradingDaemon |
| MomentumStrategy | `momentum_strategy.py` | ❌ NOT called | Only by PaperTradingDaemon |
| OIStrategy | `oi_strategy.py` | ❌ NOT called | Only by PaperTradingDaemon |
| AdaptiveStrategy | `adaptive_strategy.py` | ❌ NOT called | Only by PaperTradingDaemon |

**Note**: `PaperTradingDaemon` is instantiated in the container with `strategies=providers.List()` (EMPTY list) and is never started via `background_task_registry`. These strategies produce their own signals independently of the main scoring pipeline — they are PARALLEL systems.

The **main signal pipeline** uses scoring components (not strategy classes). The strategy classes were built for the paper daemon backtester.

### Signal Flow (Main Pipeline):
```
SignalScannerService → SignalEngineService
    → ScoringEngineService (7 components)
    → ConfidenceEngineService
    → RiskEngineService
    → Signal persisted + broadcast
```

### Signal Flow (PaperTradingDaemon — INACTIVE):
```
PaperTradingDaemon → EMATrendStrategy.generate() → Signal
PaperTradingDaemon → VWAPPullbackStrategy.generate() → Signal
... etc
```

Both produce `entry`, `stop_loss`, `target`. The main pipeline is more rigorous (7-component scoring).
