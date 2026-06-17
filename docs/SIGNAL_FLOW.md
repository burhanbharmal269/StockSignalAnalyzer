# StockSignalAnalyzer — Signal Lifecycle

**Platform:** Institutional-Grade NSE F&O Trading Platform
**Document Purpose:** Complete technical and business walkthrough of a signal's journey from raw market data to analytics
**Last Updated:** June 2026

---

## Overview

Every trade that StockSignalAnalyzer places begins as raw price and volume data from the exchange and ends as a recorded entry in the analytics engine. Between those two points, the signal passes through eight distinct processing stages, each with a specific validation or transformation purpose.

The complete flow is:

```
Market Data (Kite/NSE)
        ↓
  Market Scanner
        ↓
  Strategy Engine
        ↓
 Confidence Scoring
        ↓
   Risk Engine
        ↓
Signal Creation & Storage
        ↓
   OMS Routing
        ↓
Broker Execution (Paper or Live)
        ↓
Order Fill & Position Opening
        ↓
Position Monitoring & PnL
        ↓
  Exit Management
        ↓
 Analytics Recording
        ↓
AI Analysis & Insights
        ↓
Daily Expiry & Session Management
```

The sections below explain each stage in detail: what happens technically, why it matters to you as a trader, where you see it in the platform, and a concrete example.

---

## Stage 1 — Market Data Ingestion

**What happens:**
The platform continuously receives live price and volume data from two sources: the Kite Connect WebSocket feed (streaming tick-by-tick data from Zerodha's infrastructure) and NSE's own data endpoints. This data includes last traded price, bid/ask spread, volume, open interest, and derived values like VWAP. Data arrives in real time during market hours (09:15–15:30 IST) and is stored in the platform's in-memory data store for immediate processing.

The data covers all instruments in your configured Universe — indices like NIFTY and BANKNIFTY, their derivatives (futures and options across strikes and expiries), and stock F&O where configured.

**Why it matters:**
All signal generation, risk calculations, and PnL tracking depend on the accuracy and freshness of this data. Stale or missing data produces bad signals. The platform monitors data feed health and flags gaps.

**Where you see it:**
- Market Overview page — live prices, volume, VWAP, and breadth indicators
- Positions page — live mark-to-market pricing for open positions
- System Health page — data feed status indicator (green = healthy, red = disconnected or delayed)

**Example:**
At 10:23:47 IST, the platform receives a tick for NIFTY26JUN22500CE: Last Price = ₹148.30, Volume = 12,450 contracts, OI = 3,24,000. This tick is immediately used to update the VWAP calculation and re-evaluate the RSI for this instrument.

---

## Stage 2 — Market Scanner

**What happens:**
The Market Scanner continuously processes the incoming data stream across all instruments in the Universe. It calculates broad market indicators and instrument-level metrics:

- Market breadth: How many instruments are advancing vs declining, above their VWAP, above key moving averages
- Market regime detection: Is the market trending, ranging, or in a volatile/chaotic state?
- Opportunity identification: Which instruments are approaching levels that have historically triggered one of the six strategies?

The scanner runs continuously during market hours. It does not generate orders — it surfaces conditions that are worth feeding into the Strategy Engine.

**Why it matters:**
The scanner acts as a filter. Without it, the Strategy Engine would have to evaluate every instrument from scratch on every tick, which is computationally wasteful. The scanner narrows the field to instruments with live, relevant setups. It also provides the regime context that the Strategy Engine uses to weight signal quality.

**Where you see it:**
- Opportunities page — a scored list of setups the scanner has identified, with instrument name, setup type, score, and detected regime
- Market Overview page — breadth indicators, advance/decline ratio, sector heatmaps
- AI Insights page — regime descriptions in market summaries

**Example:**
At 10:45 IST, the scanner detects that BANKNIFTY's RSI has fallen to 28 — below the oversold threshold of 30. It flags this as a potential RSI Mean Reversion opportunity with an opportunity score of 74/100, and queues BANKNIFTY for immediate evaluation by the RSI Mean Reversion strategy. This appears on the Opportunities page within seconds.

---

## Stage 3 — Strategy Engine

**What happens:**
The Strategy Engine receives instruments flagged by the Market Scanner and applies one or more of the six built-in strategies to determine whether a tradeable signal exists.

Each strategy applies its own logic to the price and indicator data:

- RSI Mean Reversion: Checks if RSI is below 30 (oversold, potential LONG) or above 70 (overbought, potential SHORT). Looks for divergence between price and RSI for confirmation.

- VWAP Momentum: Compares current price to intraday VWAP. If price is above VWAP with rising volume, evaluates for a LONG signal. If below VWAP with rising volume on the downside, evaluates for SHORT.

- Supertrend Crossover: Monitors the relationship between price and the Supertrend indicator line. A confirmed cross above the line triggers a LONG evaluation; a cross below triggers a SHORT evaluation.

- Bollinger Breakout: Monitors whether price has breached the upper or lower Bollinger Band. An upper band breach evaluates for LONG momentum; lower band breach evaluates for SHORT.

- MACD Divergence: Detects when price makes a new low but MACD makes a higher low (bullish divergence, potential LONG), or price makes a new high but MACD makes a lower high (bearish divergence, potential SHORT).

- EMA Crossover: Tracks when the 9-period EMA crosses the 21-period EMA. A cross above (golden cross) evaluates for LONG; a cross below (death cross) evaluates for SHORT.

The regime detected by the Market Scanner influences which strategies are most active. Momentum strategies (VWAP, Supertrend, EMA) are prioritized in trending regimes. Mean reversion strategies (RSI, Bollinger) are prioritized in ranging regimes.

**Why it matters:**
This is where analytical judgment is encoded. Each strategy represents a systematic trading thesis, tested and tuned for NSE F&O characteristics. Running six strategies concurrently means the platform can exploit different market conditions simultaneously rather than being dependent on a single approach.

**Where you see it:**
- Signals page — each signal shows which strategy generated it
- Opportunities page — opportunities are tagged with the candidate strategy
- Analytics page — performance can be filtered by strategy to compare effectiveness

**Example:**
The RSI Mean Reversion strategy receives BANKNIFTY at RSI 28. It checks additional conditions: is price near a significant support level? Is volume confirming the oversold reading? Both conditions are met. The strategy outputs a preliminary LONG signal for BANKNIFTY with an entry price of ₹48,240, stop loss at ₹47,900, and target at ₹49,000.

---

## Stage 4 — Confidence Scoring

**What happens:**
Once a strategy has produced a preliminary signal, the Confidence Scoring module assigns a score from 0 to 100 representing how cleanly the signal's conditions are met.

The score is calculated based on factors such as:
- How far the indicator is from its trigger level (RSI at 22 is a stronger setup than RSI at 29)
- Volume confirmation (are more traders participating, confirming the move?)
- Alignment with the detected market regime (a momentum signal in a trending market scores higher than the same signal in a ranging market)
- Historical reliability of this strategy on this instrument in similar conditions
- Sentiment alignment from AI Insights (optional weighting)

Signals that score below your configured minimum threshold (set in Settings) are dropped here and never proceed to the Risk Engine. They appear on the Signals page with a "Below Threshold" status.

**Why it matters:**
Not every technical signal is equally compelling. Confidence scoring ensures that only the clearest setups — where multiple confirming factors align — proceed toward order placement. This reduces the number of low-quality trades and improves the overall win rate.

**Where you see it:**
- Signals page — every signal shows its confidence score (0–100)
- Settings page — minimum confidence threshold setting
- Analytics page — you can filter by confidence score range to see whether high-confidence signals outperformed low-confidence ones

**Example:**
The BANKNIFTY LONG signal from the RSI Mean Reversion strategy scores 82/100. RSI is deeply oversold at 28 (not just marginally below 30), volume is 1.4x the 20-day average, and the regime is "ranging" which suits mean reversion. The minimum threshold is set to 65. The signal passes with a score of 82 and proceeds to the Risk Engine.

---

## Stage 5 — Risk Engine Validation

**What happens:**
The Risk Engine is the final gate before an order is placed. It receives the signal and checks it against every configured risk parameter. If any check fails, the signal is rejected, logged with a reason, and no order is created.

Checks performed:

- Position size: Would the order quantity exceed the maximum lots per trade configured in the Risk page?
- Capital utilization: Would this trade push total deployed capital above the configured maximum percentage?
- Daily loss limit: Has today's realized loss already reached the daily loss limit? If yes, no new orders can be placed.
- Drawdown: Is the portfolio's current drawdown within the configured maximum?
- Concentration: Would this trade create too large an exposure to a single instrument or related instruments?
- Kill switch state: Is the kill switch currently active? If yes, all signals are blocked.

If all checks pass, the Risk Engine approves the signal and forwards it to the OMS.

**Why it matters:**
This is institutional-grade risk management applied at the individual trade level. Without it, a runaway strategy or an unusual market condition could place oversized orders or continue trading through a losing streak far beyond your risk tolerance. The Risk Engine is your systematic protection against these scenarios.

**Where you see it:**
- Signals page — rejected signals show the rejection reason (e.g., "Daily loss limit reached," "Position size exceeds maximum")
- Risk page — current utilization of each risk parameter in real time
- System Health page — risk engine status

**Example:**
The BANKNIFTY LONG signal (confidence 82) reaches the Risk Engine. Checks:
- Position size: 2 lots requested, maximum is 5. Passes.
- Capital utilization: Current deployment is 38%, maximum is 60%. Adding this trade would bring it to 44%. Passes.
- Daily loss limit: Today's realized loss is ₹8,200, limit is ₹25,000. Passes.
- Drawdown: Current drawdown is 1.8%, maximum is 5%. Passes.
- Kill switch: Inactive. Passes.

All checks pass. The signal is approved and forwarded to the OMS.

---

## Stage 6 — Signal Creation & Storage

**What happens:**
Once the Risk Engine approves a signal, the platform creates a formal Signal record and stores it in the database. This record captures:

- Unique Signal ID
- Correlation ID (used to link the signal through every downstream step)
- Instrument, direction (LONG/SHORT), entry price, stop loss, target
- Strategy that generated the signal
- Confidence score
- Timestamp
- Risk Engine approval record
- Current status (PENDING, CONVERTED TO ORDER, REJECTED, EXPIRED)

The signal is now visible on the Signals page and is forwarded to the OMS.

**Why it matters:**
Creating a formal signal record before placing an order ensures full traceability. Every order can be traced back to the signal that created it, and every signal can be traced back to the strategy logic and market conditions at the time of generation. This is critical for performance review, compliance, and debugging.

**Where you see it:**
- Signals page — the signal appears here immediately after creation
- The Correlation ID on this signal will appear on the related Order and Position records
- Audit Log (Settings) — full signal creation log

**Example:**
Signal record created:
- Signal ID: SIG-20260616-00847
- Correlation ID: COR-20260616-00847
- Instrument: BANKNIFTY26JUN48240CE
- Direction: LONG
- Entry: ₹48,240 | Stop Loss: ₹47,900 | Target: ₹49,000
- Strategy: RSI_MEAN_REVERSION
- Confidence: 82
- Status: PENDING

---

## Stage 7 — OMS Routing

**What happens:**
The Order Management System (OMS) receives the approved signal and converts it into an order. The OMS determines:

- Which broker to send the order to (Paper or Live, based on the current Trading Mode)
- Order type (market order for immediate execution, or limit order at the specified entry price)
- Order quantity (calculated from the position size approved by the Risk Engine and the lot size of the instrument)
- Any broker-specific parameters required by Kite Connect

The OMS also begins tracking the order's lifecycle from this point forward, monitoring for fills, partial fills, rejections, or cancellations.

**Why it matters:**
The OMS is the bridge between the platform's internal logic and the external world (the broker). It abstracts the differences between paper and live execution so that the rest of the platform operates identically regardless of trading mode. It also handles the practical complexity of order state management — what to do if an order is partially filled, how to handle a broker rejection, etc.

**Where you see it:**
- Orders page — the order appears here immediately after the OMS creates it, in PENDING state
- The Correlation ID on the order matches the Signal ID
- System Health page — OMS status indicator

**Example:**
The OMS receives SIG-20260616-00847. Trading Mode is Live. It creates Order ORD-20260616-01124:
- Instrument: BANKNIFTY26JUN48240CE
- Direction: BUY (for a LONG)
- Quantity: 1 lot (25 units)
- Order Type: LIMIT at ₹148.30 (the current CE price corresponding to BANKNIFTY at 48,240)
- Routed to: Kite Connect (Live Broker)
- Status: PENDING → OPEN (once confirmed by Kite)

---

## Stage 8 — Broker Execution (Paper vs Live)

**What happens:**

In Live Mode: The OMS sends the order to Kite Connect via Zerodha's API. Kite forwards the order to the NSE exchange. The exchange matches the order against available counterparty orders in the order book. When matched, a fill is confirmed and Kite sends the fill confirmation back to the OMS.

In Paper Mode: The OMS sends the order to the internal paper broker simulation engine. The engine checks if the current market price would have filled the order (for limit orders, is the market price at or better than the limit?). If yes, a simulated fill is created at the current market price with a small simulated slippage applied to reflect realistic conditions. No exchange interaction occurs.

Both paths update the order status and create an execution record.

**Why it matters:**
This stage is where the decision to trade becomes real (in live mode) or realistically simulated (in paper mode). The paper simulation is designed to be honest — it applies realistic slippage and does not assume perfect fills at the exact signal price. This makes paper trading results meaningful when you evaluate strategy performance.

**Where you see it:**
- Orders page — order status changes from OPEN to FILLED (or PARTIALLY FILLED, REJECTED)
- Positions page — a new position appears once the order fills
- In live mode, the same fill will appear in your Zerodha account

**Example:**
The limit order for BANKNIFTY26JUN48240CE at ₹148.30 is submitted to Kite at 10:46:03 IST. At 10:46:11 IST, the market price touches ₹148.30 and the exchange fills the order. Fill confirmation received: 25 units at ₹148.40 (slippage of ₹0.10 from the limit price due to order book dynamics). Order status: FILLED.

---

## Stage 9 — Order Fill & Position Opening

**What happens:**
When a fill confirmation is received from the broker (live or paper), the OMS:

1. Updates the order status to FILLED with the actual fill price and timestamp.
2. Creates or updates a Position record. If no position exists for this instrument, a new LONG or SHORT position is opened. If a position already exists (for example, from a prior partial fill), it is updated with the additional quantity and the average fill price is recalculated.
3. Records the fill in the execution log.
4. Notifies the analytics engine of the new execution event.

The position is now live and its PnL will be tracked in real time against current market prices.

**Why it matters:**
Position creation is when your capital is considered deployed. From this moment, the risk engine monitors the position's unrealized PnL against your stop loss, and the analytics engine begins recording performance data for this trade.

**Where you see it:**
- Positions page — new position with entry price, quantity, direction, and initial PnL (usually near ₹0 immediately after fill)
- Orders page — order shows fill price, fill time, and quantity filled
- Analytics page — a new trade entry is created

**Example:**
Fill at ₹148.40 for 25 units of BANKNIFTY26JUN48240CE creates Position POS-20260616-00512:
- Direction: LONG
- Entry Price: ₹148.40
- Quantity: 25 units (1 lot)
- Stop Loss: ₹47,900 (BANKNIFTY level, translating to approximately ₹120 for the CE option)
- Target: ₹49,000 (BANKNIFTY level)
- Unrealized PnL: ₹0 (at fill)

---

## Stage 10 — Position Monitoring & PnL

**What happens:**
Once a position is open, it is continuously monitored:

- Current market price is fetched from the live data feed on every tick.
- Unrealized PnL is recalculated: for a LONG position, PnL = (Current Price − Entry Price) × Quantity. For a SHORT position, PnL = (Entry Price − Current Price) × Quantity.
- The position's distance from stop loss and target is tracked continuously.
- If the stop loss price is breached, an exit signal is generated automatically.
- If the target price is reached, an exit signal is generated automatically.
- The risk engine continuously rechecks overall portfolio drawdown as PnL changes.

Real-time WebSocket connections push these updates to your browser without requiring page refreshes.

**Why it matters:**
Continuous monitoring ensures that stop losses and targets are respected systematically, without requiring you to watch every position manually. It also gives the risk engine live awareness of portfolio health, enabling automatic responses (like triggering the Kill Switch) if conditions deteriorate.

**Where you see it:**
- Positions page — unrealized PnL updates in real time
- Dashboard — summary PnL across all positions
- Risk page — live capital utilization and drawdown meters

**Example:**
At 11:15 IST, BANKNIFTY rises from 48,240 to 48,650. The BANKNIFTY26JUN48240CE price moves from ₹148.40 to ₹172.80. Unrealized PnL for the position: (₹172.80 − ₹148.40) × 25 = ₹610. The target at ₹49,000 is not yet reached. Monitoring continues.

---

## Stage 11 — Exit Management

**What happens:**
A position can be exited in four ways:

1. Target Hit: The market price reaches the configured target price. The platform generates an automatic exit signal and places a closing order at market.

2. Stop Loss Hit: The market price reaches the configured stop loss price. The platform generates an automatic exit signal and places a closing order at market.

3. Strategy Exit Signal: One of the six strategies issues an explicit exit signal for an instrument (for example, RSI has risen back above 50 for a mean reversion trade, suggesting the setup is complete). The OMS closes the position.

4. Manual Close: You click "Close Position" on the Positions page. The platform places a market order to close immediately.

When the closing order is filled, the position status changes to CLOSED and the PnL is finalized as Realized PnL.

**Why it matters:**
Disciplined exits are as important as disciplined entries. Automatic stop loss and target execution removes the emotional component from exit decisions — a common source of trading losses. The strategy exit signal adds a more nuanced exit mechanism that can close a trade before the stop is hit if the setup is no longer valid.

**Where you see it:**
- Positions page — position status changes to CLOSED
- Orders page — a new exit order appears, linked to the same Correlation ID as the entry
- Analytics page — the trade is recorded with entry, exit, PnL, and duration

**Example:**
At 13:42 IST, BANKNIFTY reaches 49,050 — above the target of 49,000. The platform automatically places a SELL order (to close the LONG) for BANKNIFTY26JUN48240CE at market. Fill at ₹198.60. Position closed.
- Exit Price: ₹198.60
- Entry Price: ₹148.40
- PnL: (₹198.60 − ₹148.40) × 25 = ₹1,255 (Realized)
- Trade Duration: 2 hours 56 minutes

---

## Stage 12 — Analytics Recording

**What happens:**
When a position closes, the analytics engine records a complete trade record including:

- Entry and exit timestamps
- Entry and exit prices
- Realized PnL in rupees and percentage
- Slippage on entry and exit (deviation from signal price to fill price)
- Latency (time from signal generation to order placement)
- Which strategy generated the signal
- Confidence score at the time of the signal
- Risk engine outcome (approved, and with what parameters)
- Trade duration

These records accumulate over time to build a comprehensive performance dataset.

**Why it matters:**
Analytics is how you know whether the platform is working. It answers questions like: Which strategy performs best? Is slippage excessive? Are high-confidence signals actually outperforming low-confidence ones? Is there a time of day when signals are stronger? Without this data, you are flying blind on strategy quality.

**Where you see it:**
- Analytics page — trade-by-trade records, summary statistics, equity curves
- Strategies can be compared side by side
- Date range filtering allows daily, weekly, monthly, or custom period views

**Example:**
Trade record created for the BANKNIFTY position:
- Strategy: RSI_MEAN_REVERSION
- Signal Confidence: 82
- Entry Slippage: ₹0.10 (₹148.30 signal vs ₹148.40 fill)
- Exit Slippage: ₹0.20 (₹198.80 target vs ₹198.60 fill — exit slippage is negative, meaning we filled slightly below the target)
- Latency: 41ms (from signal generation to order placement)
- Realized PnL: ₹1,255
- Trade Duration: 2h 56m
- Outcome: WIN

---

## Stage 13 — AI Analysis & Insights

**What happens:**
Throughout the trading day, Azure OpenAI processes multiple data streams to generate market insights:

- News articles from NewsAPI.ai are analyzed for sentiment, relevance, and potential market impact
- Price action and technical indicator readings across the Universe are summarized
- Strategy performance for the day is incorporated into the context
- Macro and sector signals are evaluated

The output is a natural-language market insight: a structured summary that describes current market conditions, key risks, sentiment score, and any instrument-specific observations.

Insights are generated:
- At market open (initial conditions)
- After significant market moves (triggered by price or breadth thresholds)
- On demand (when you click "Refresh Insight")
- At scheduled intervals throughout the day

**Why it matters:**
AI insights add a layer of context that pure technical analysis cannot provide. A technically strong LONG signal in an instrument facing severe regulatory headwinds (visible in news) is a different risk than the same signal in a calm news environment. The AI insight bridges the gap between the quantitative signals and the qualitative market narrative.

**Where you see it:**
- AI Insights page — full insight text, sentiment score, key risk factors
- Market Overview page — condensed sentiment indicator
- Individual instrument pages — instrument-specific AI commentary

**Example:**
After the BANKNIFTY trade closes profitably, the AI Insights engine notes:
"BANKNIFTY RSI has recovered from oversold levels. Bullish breadth in BFSI sector supports the recovery. RBI policy commentary released at 12:00 IST was neutral-to-positive. Overall sentiment score for BANKNIFTY: +0.42 (mildly bullish). Key risk: global cues remain mixed; US Fed meeting minutes due post-market."

---

## Stage 14 — Daily Expiry & Session Management

**What happens:**
The platform's SessionExpiryWatcher runs as a background process that monitors the Kite session lifecycle. Key events it manages:

- Pre-expiry alert: At approximately 05:30 IST each morning (30 minutes before session expiry), the watcher sends an alert prompting you to prepare for reconnection.
- Session expiry at 06:00 IST: The Kite session expires. The platform switches live order placement to blocked state — no live orders can be placed until reconnection.
- Post-expiry alert: An alert is shown on the Dashboard and Broker page indicating reconnection is required.
- F&O contract expiry: The watcher also monitors for instrument-level expiry (for example, the last Thursday of a monthly F&O series). Positions in expiring contracts are flagged for review well before the expiry close.

After you reconnect through the Broker page each morning, the session watcher validates the new access token and re-enables live trading.

**Why it matters:**
A session expiry during market hours in live trading mode would silently block all order placement, including automatic stop losses. This could result in positions with no protection if a large move occurs. The watcher ensures you are always aware of session state and are prompted to reconnect before market open.

**Where you see it:**
- Broker page — session status, expiry time, and reconnect button
- Dashboard — amber alert when session expiry is approaching, red alert when expired
- System Health page — session status component

**Example:**
At 05:30 IST on June 17, the SessionExpiryWatcher detects that the Kite session will expire in 30 minutes. An amber alert appears on the Dashboard: "Kite session expires at 06:00 IST. Reconnect required before live trading can resume." You dismiss the alert, and at 09:00 IST (before market open), you navigate to the Broker page and complete the Kite reconnection. The new access token is validated, the session status turns green, and live trading is re-enabled for the new trading day.

---

## Summary: Signal Lifecycle at a Glance

| Stage | Input | Output | Where You See It |
|---|---|---|---|
| 1. Market Data | NSE/Kite tick feed | Live prices, volume, OI | Market Overview, Positions |
| 2. Market Scanner | Live data stream | Opportunity list, regime | Opportunities page |
| 3. Strategy Engine | Flagged instruments | Preliminary signals (LONG/SHORT) | Signals page (pending) |
| 4. Confidence Scoring | Preliminary signal | Scored signal (0–100) | Signals page (confidence column) |
| 5. Risk Engine | Scored signal | Approved or rejected signal | Signals page (rejection reason) |
| 6. Signal Storage | Approved signal | Signal record with Correlation ID | Signals page |
| 7. OMS Routing | Approved signal | Order record (PENDING) | Orders page |
| 8. Broker Execution | Order | Fill confirmation | Orders page (FILLED) |
| 9. Position Opening | Fill | Open position record | Positions page |
| 10. PnL Monitoring | Live prices + position | Unrealized PnL | Positions page (live) |
| 11. Exit Management | Target/stop hit or exit signal | Closing order + realized PnL | Orders page, Positions (CLOSED) |
| 12. Analytics | Closed trade record | Performance statistics | Analytics page |
| 13. AI Insights | News + price data | Market insight text, sentiment score | AI Insights page |
| 14. Session Management | Clock + Kite session | Session state alerts, reconnect | Broker page, Dashboard |

---

*For plain-English definitions of every term used in this document, see TRADING_PLATFORM_GLOSSARY.md. For operational instructions, see USER_GUIDE.md.*
