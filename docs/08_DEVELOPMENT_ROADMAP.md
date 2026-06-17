Phase 1 — COMPLETE

Architecture Skeleton

Phase 2 — COMPLETE

Configuration Layer

Phase 3 — COMPLETE

Domain Layer

Phase 4 — COMPLETE

Database Layer

Technology:

PostgreSQL + TimescaleDB
SQLAlchemy
Alembic

Phase 5 — COMPLETE

Observability

Structured Logging via structlog

Phase 6 — COMPLETE

Authentication

JWT Authentication
Admin Login — no default credentials; first-run generates random password.

Phase 7 — COMPLETE

Market Data Engine

Instrument Master
Kite WebSocket
Candle Aggregator

Phase 8 — COMPLETE

Broker Abstraction

IBroker
KiteBroker
PaperBrokerAdapter
Token encryption at rest

Phase 9 — COMPLETE

Market Regime Engine

Detect:

TRENDING_BULLISH
TRENDING_BEARISH
SIDEWAYS
HIGH_VOLATILITY
LOW_VOLATILITY

Output:

RegimeSnapshot — primary regime, secondary modifier, confidence, stability score.
Two-layer classification: TrendLayer + VolatilityLayer → 8-rule priority matrix.
α-blending anti-whipsaw smoother.

Phase 10

Strategy Framework

Create:

IStrategy interface

Each strategy returns:

Signal direction
Component score (long + short)
Reason

Implement all scoring components from Doc 19/21:

OI Buildup Component
Trend Component
Option Chain Component
Volume Component
VWAP Component
IV Analysis Component
Momentum Modifier
Breakout Modifier

Strategies must be plug-and-play.
No sentiment. No AI. Deterministic only.

Phase 11

Scoring Engine

Purpose:

Combine component scores into a single 0–100 signal score.

Weights (V1 from Doc 19/21):

Trend = 20
OI = 20
Volume = 15
Price Action = 15
IV = 10
Market Regime = 10
VWAP = 10

Apply regime multipliers from RegimeSnapshot.
Direction voting: weighted bull vs bear component count.
Penalty calculations: staleness, conviction, hours, regime mismatch, expiry.

Output:

0–100 adjusted_score
Direction (LONG / SHORT / NEUTRAL)
direction_conviction (0–1)

Rules:

No direct BUY/SELL decisions.
Score < 70 → WEAK_SIGNAL. Not forwarded to OMS.

Phase 12

Confidence Engine

Inputs:

Historical Win Rate
Strategy Accuracy
Regime Match
Recent Performance (calibration factor)
Signal Fingerprint lookup

Output:

Confidence % (0–100)

Score and Confidence are separate values.
Score answers: "how strong is the signal?"
Confidence answers: "how much should we trust it?"

Phase 13

Risk Engine

Most critical module.

Checks (all 15, in order):

Kill Switch gate
Daily Loss limit
Weekly Loss limit
Drawdown limit
Open Positions count
Symbol Concentration
Capital Concentration
Net Delta exposure
Correlation risk
Margin availability
Risk/Reward ratio
Position Size sanity
Order Rate limit
Theta Decay (warn-only)
Vega Exposure

Rules:

Every signal must pass all 15 checks before OMS receives it.
Risk Engine may reject signals. Rejection is final.
Every RiskDecision written to risk_decisions (append-only).
IAIProvider is FORBIDDEN from being injected into Risk Engine.

Phase 14

Signal Engine

Orchestrates the full pipeline:

Feature Engineering output
→ Market Regime Engine
→ Strategy Framework (all components)
→ Scoring Engine
→ Confidence Engine
→ Risk Engine
→ OMS (paper mode first)

Output per signal:

Symbol
Direction
Entry price
Stop Loss
Targets (T1, T2, T3)
Score (0–100)
Confidence (0–100)
Explanation (template-based, no AI)

Store every signal. Never delete.

Phase 15

Dashboard

Backend API:

All read endpoints on read replica.
WebSocket live feed for signals, positions, regime changes.
Health endpoint covering all 7 system components.

Frontend (Next.js):

Market Overview — regime badge, VIX gauge, top signals, P&L summary
Live Signals — score, confidence, direction, state
Option Chain — live OI, IV, PCR matrix
Trade Journal — orders, positions, closed trades
Analytics — P&L chart, win rate, regime breakdown
Health — component status grid; operator daily check before market open

Phase 16

Paper Trading

Requirements:

Live Market Data
Simulated Orders (PaperBrokerAdapter)
Real P&L Tracking

Minimum Validation:

30 Trading Days — no exceptions.

Exit criteria before live trading:

System uptime >= 99.5% during market hours
Zero unhandled exceptions in signal pipeline
Signal win rate >= 45%
Risk Engine correctly rejecting all manual test cases
Kill switch activation + recovery tested successfully
Stop-loss orders placed within 2s on >= 99% of fills
Paper P&L matches manual calculation within 0.1%

Phase 17

AI Layer

Enabled only after paper trading validation is complete.

Purpose:

News Summarization
Market Sentiment Scoring
News Classification

AI is strictly limited to:

Providing an input to the Sentiment scoring component only.
Returning a structured score (not a trade decision).

AI is FORBIDDEN from:

Direct Buy/Sell decisions
Position Sizing
Risk Management
Order Placement
Stop Loss Calculation
Overriding any deterministic output

IAIProvider must NOT be injectable into:
OMS, RiskEngine, PositionSizer, KillSwitchService

Implement:

IAIProvider interface
OpenAI provider
NeutralSentimentProvider (deterministic fallback — always available)
Prompt registry (versioned YAML)
Redis cache keyed by SHA-256(provider+prompt_version+text)
Daily token budget enforcement

Phase 18

Live Trading

Requirements:

All Phase 16 exit criteria met and documented.
Security checklist (Doc 23) complete.
Incident response runbook written.
Risk limits set to 50% of configured limits for first 5 days.
Human operator monitoring for first 5 live trading days.
Kill switch tested manually on live environment before first order.
