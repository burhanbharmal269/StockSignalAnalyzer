# StockSignalAnalyzer — User Guide

**Platform:** Institutional-Grade NSE F&O Trading Platform
**Audience:** Traders who understand markets but not software engineering
**Last Updated:** June 2026

---

## Table of Contents

1. What is StockSignalAnalyzer?
2. Getting Started
3. Paper Trading vs Live Trading
4. How to Connect to Kite
5. Understanding Signals
6. Managing Orders
7. Managing Positions
8. Risk Management
9. Analytics
10. AI Insights
11. News & Sentiment
12. Market Opportunities
13. Backtesting
14. Paper Daemon
15. Kill Switch
16. Daily Routine
17. Troubleshooting

---

## 1. What is StockSignalAnalyzer?

StockSignalAnalyzer is an institutional-grade trading platform built for NSE Futures & Options (F&O) markets. It combines automated signal generation, risk validation, order management, and AI-driven market analysis in a single system.

The platform is designed for traders who want systematic, rule-based decision making rather than purely discretionary trading. At its core, it does the following:

- Scans NSE F&O instruments continuously for trading opportunities
- Applies six distinct strategy models to generate buy and sell signals
- Validates every signal through a risk engine before placing any order
- Routes orders to either a paper (virtual) or live (real money) broker
- Records every execution for performance analysis
- Uses Azure OpenAI to generate market insights from news, price action, and sentiment data

You stay in control. The platform surfaces recommendations and can execute them automatically, but you can stop everything instantly using the Kill Switch.

---

## 2. Getting Started

**First Login**

When you open StockSignalAnalyzer for the first time, you land on the Dashboard. This is your central command view. It shows:

- Current trading mode (Paper or Live) in the top status bar
- Active signals waiting for review or execution
- Open positions and their current profit/loss
- Kill switch status (active or inactive)
- System health indicators

**What You See on the Dashboard**

The top bar shows the platform's operational status. A green indicator means everything is running normally. An amber indicator means something requires your attention (for example, a broker session about to expire). A red indicator means a critical issue exists or the kill switch is active.

The left navigation menu gives you access to all pages:

- Dashboard — summary of everything
- Market Overview — broad market conditions
- Signals — all generated trading signals
- Orders — current and historical orders
- Positions — open trades
- Analytics — performance statistics
- Broker — connection to Kite (Zerodha)
- System Health — platform diagnostics
- Opportunities — scanner output
- AI Insights — Azure OpenAI analysis
- Backtest — historical strategy testing
- Paper Trading — virtual trading management
- Paper Daemon — autonomous paper trading
- Universe — the list of instruments being tracked
- Capital — your capital allocation settings
- Portfolios — grouped position views
- Risk — risk engine configuration
- Settings — platform preferences

**Default Mode**

When you first start, the platform is in Paper Trading mode. No real money is involved. You can safely explore all features without any financial risk.

---

## 3. Paper Trading vs Live Trading

**Paper Trading (Default)**

Paper trading is virtual trading. When the platform generates a signal and places an order in paper mode, no real order reaches any exchange. The system simulates fills based on market prices, tracks virtual positions, and calculates theoretical profit and loss.

Use paper trading to:

- Test strategies before committing real capital
- Understand how the platform works without financial risk
- Evaluate signal quality over time
- Run the Paper Daemon for fully autonomous simulation

Everything in paper mode looks identical to live mode. You will see orders, positions, and PnL — but none of it affects your real account.

**Live Trading**

In live mode, orders are real. They are sent through Kite Connect (Zerodha's broker API) to the NSE exchange. Real money is at risk.

Before switching to live mode, you must:

1. Have a Zerodha trading account
2. Connect your Kite session (see Section 4)
3. Configure your risk limits in the Risk page
4. Confirm your capital allocation in the Capital page

The key difference is order routing: paper orders stay within the platform, live orders go to your Zerodha account.

**Switching Modes**

You can switch between paper and live mode from the Settings page or the Broker page. The platform will ask you to confirm before switching to live mode.

---

## 4. How to Connect to Kite

Kite Connect is Zerodha's trading API. You need this to place real orders. Follow these steps exactly.

**Step 1 — Open the Broker Page**

Click "Broker" in the left navigation menu. You will see your current connection status.

**Step 2 — Initiate Kite Authentication**

Click the "Connect to Kite" button. The platform will open Zerodha's login page in a new browser tab.

**Step 3 — Log In to Zerodha**

Enter your Zerodha Client ID and password. Complete any two-factor authentication (TOTP or PIN) that Zerodha requires.

**Step 4 — Authorize the Application**

After logging in, Zerodha will ask you to authorize StockSignalAnalyzer to access your account. Click "Allow." Zerodha will redirect you back to the platform.

**Step 5 — Confirm the Connection**

Back on the Broker page, you should see your account details: client ID, available margin, and connection timestamp. A green indicator confirms the session is active.

**Session Expiry**

Kite sessions expire daily at 06:00 IST (market open morning). You must reconnect every trading day. The platform's Session Expiry Watcher monitors this and will alert you before expiry and again when reconnection is needed.

If you try to place a live order with an expired session, the order will be rejected and you will see an alert. Reconnect through the Broker page to restore live trading.

---

## 5. Understanding Signals

**What is a Signal?**

A signal is the platform's recommendation to buy or sell a specific F&O instrument. It is generated by one of the six built-in strategies after analyzing market data.

Every signal contains:

- Instrument name (for example, NIFTY26JUN22500CE)
- Direction: LONG (buy) or SHORT (sell)
- Entry price (the recommended price to enter the trade)
- Stop loss (the price at which the trade should be exited to limit loss)
- Target (the price at which the trade should be exited to take profit)
- Confidence score (how strongly the strategy believes in this trade, from 0 to 100)
- Strategy name (which of the six strategies generated it)

**Signal Directions**

LONG — The strategy expects the price to rise. A LONG signal means you should buy the instrument.

SHORT — The strategy expects the price to fall. A SHORT signal means you should sell (short) the instrument.

NEUTRAL — The strategy has no strong directional view. No order is generated for NEUTRAL signals.

**The Six Strategies**

The platform uses six distinct analysis methods, and each can generate signals independently:

- RSI Mean Reversion — Identifies instruments that have been oversold or overbought and are likely to revert to their average price. RSI below 30 often triggers a LONG; above 70 often triggers a SHORT.

- VWAP Momentum — Compares the current price to the Volume Weighted Average Price. Price trading above VWAP with strong volume can trigger a LONG signal.

- Supertrend Crossover — Uses the Supertrend indicator to detect when price crosses above or below a dynamic support/resistance line. A crossover above triggers LONG; below triggers SHORT.

- Bollinger Breakout — Detects when price breaks outside the upper or lower Bollinger Band, signaling a potential strong move. A breakout above the upper band triggers LONG.

- MACD Divergence — Looks for divergences between price movement and the MACD indicator, which can signal a reversal before it happens.

- EMA Crossover — Triggers when a shorter-term Exponential Moving Average crosses a longer-term one. A golden cross (short EMA crosses above long EMA) triggers LONG.

**Where to See Signals**

Go to the Signals page. You will see a list of all generated signals with their details. You can filter by strategy, direction, instrument, or time period. Clicking any signal opens its full detail view, including the risk parameters and execution status.

**Confidence Score**

Each signal carries a confidence score between 0 and 100. A score above 70 is considered high confidence. Signals below a minimum threshold (configured in Settings) may be filtered out before reaching the order stage.

---

## 6. Managing Orders

**What is an Order?**

An order is the instruction sent to a broker (paper or live) to buy or sell an instrument. Orders are created automatically when a signal passes risk validation.

**Order States**

Every order progresses through states:

- PENDING — The order has been created but not yet sent to the broker.
- OPEN — The order has been sent and is waiting to be filled by the market.
- FILLED — The order has been completely executed at the exchange (or simulated in paper mode).
- PARTIALLY FILLED — Some but not all of the order quantity has been executed.
- CANCELLED — The order was cancelled before it was filled.
- REJECTED — The broker or risk engine refused the order.

**Where to See Orders**

Go to the Orders page. You will see all orders with their current state, instrument, quantity, price, and timestamp. You can filter by date range, strategy, or order status.

**Cancelling an Order**

If an order is in PENDING or OPEN state, you can cancel it by clicking the order row and selecting "Cancel Order." Once an order is FILLED, it cannot be cancelled — it has already been executed and a position has been opened.

**Understanding the Correlation ID**

Each order has a Correlation ID — a unique reference code that links the order back to the original signal. If you need to trace why a particular order was placed, note the Correlation ID and look up the corresponding signal on the Signals page.

---

## 7. Managing Positions

**What is a Position?**

A position is an open trade. When an order is filled, it creates or modifies a position. A position remains open until you exit it (by placing an opposing order).

**The Positions Page**

Go to the Positions page to see all your open trades. For each position you will see:

- Instrument name
- Direction (LONG or SHORT)
- Entry price (the price at which you entered)
- Current market price
- Quantity (number of lots)
- Unrealized PnL (profit or loss if you were to close right now)
- Stop loss and target levels

**Unrealized vs Realized PnL**

Unrealized PnL is the profit or loss on a position that is still open. It changes every time the market price moves. It is not actual money until the position is closed.

Realized PnL is the profit or loss locked in after a position has been closed. This is actual money (in live mode) or confirmed virtual profit (in paper mode).

**Closing a Position**

You can manually close a position from the Positions page by clicking the position and selecting "Close Position." The platform will place an exit order at the current market price.

The platform can also close positions automatically when:

- The stop loss price is hit
- The target price is hit
- The kill switch is activated
- The strategy issues an exit signal

---

## 8. Risk Management

**What the Risk Engine Does**

Before any signal becomes an order, the Risk Engine validates it. Think of the Risk Engine as a compliance checkpoint. It checks whether placing this trade is within your configured safety limits.

The Risk Engine validates:

- Position size — Is the order quantity within your maximum allowed lot size?
- Capital utilization — Would this trade push your deployed capital beyond your limit?
- Daily loss limit — Have you already lost more than the maximum allowed amount today?
- Drawdown — Is your portfolio drawdown within acceptable bounds?
- Concentration — Would this trade make you too heavily exposed to one instrument or sector?

If any check fails, the signal is rejected and no order is placed. You will see the rejection reason on the Signals page.

**The Risk Page**

Go to the Risk page to configure your risk parameters. You can set:

- Maximum position size per trade (in lots)
- Maximum capital deployment percentage
- Daily loss limit (in rupees)
- Maximum portfolio drawdown percentage
- Instrument-level exposure limits

Take time to set these carefully before switching to live mode. The defaults are conservative, but you should adjust them to match your actual risk tolerance and capital.

**Risk Profiles**

The platform supports multiple risk profiles (for example, Conservative, Moderate, Aggressive). You can switch between profiles in the Risk page. Each profile has its own set of limits.

---

## 9. Analytics

**What Analytics Shows**

The Analytics page gives you a complete picture of how the platform has performed. It covers every order that has been placed and filled, and calculates key performance metrics.

**Key Metrics Explained**

Win Rate — The percentage of trades that were profitable. A win rate of 55% means 55 out of every 100 completed trades made money.

Average Profit per Winner — How much, on average, a winning trade made.

Average Loss per Loser — How much, on average, a losing trade lost. You want this to be smaller than your average profit.

Sharpe Ratio — A measure of return relative to risk. A Sharpe Ratio above 1.0 is generally considered acceptable; above 2.0 is strong.

Maximum Drawdown — The largest peak-to-trough decline in your portfolio value during the selected period. A 10% drawdown means at some point your portfolio fell 10% from its high before recovering.

Latency — How long it takes from signal generation to order placement. Lower is better. Measured in milliseconds.

Slippage — The difference between the price at which a signal was generated and the price at which the order was actually filled. Some slippage is normal due to market movement between signal generation and execution.

**Filtering Analytics**

You can filter analytics by date range, strategy, instrument, or trading mode (paper or live). This lets you compare, for example, how VWAP Momentum performed in March versus April.

---

## 10. AI Insights

**What AI Insights Does**

The AI Insights page uses Azure OpenAI (Microsoft's enterprise AI service) to generate human-readable market analysis. It processes price data, technical indicators, news sentiment, and market breadth to produce summaries and recommendations.

**What You Will See**

Each insight includes:

- A market summary describing current conditions
- Sentiment score (bullish, neutral, or bearish, on a scale from -1 to +1)
- Key risk factors identified from news and market data
- Instrument-specific commentary where relevant

**How to Interpret AI Insights**

AI insights are informational, not instructions. They summarize what the data is showing, not what you must do. Use them as context when reviewing signals.

A positive sentiment score (closer to +1) means the AI sees mostly bullish signals. A negative score (closer to -1) means bearish conditions are dominant.

Insights are generated periodically throughout the trading day and on demand. You can refresh the insight for any instrument by clicking "Refresh Insight" on that instrument's detail view.

---

## 11. News & Sentiment

**How News Feeds Into the Platform**

StockSignalAnalyzer connects to NewsAPI.ai to pull financial news relevant to the instruments and sectors you are tracking. This news is processed and used to calculate sentiment scores.

Sentiment analysis works by reading the tone of news articles — positive news (earnings beats, regulatory approvals, sector tailwinds) pushes sentiment scores higher; negative news (earnings misses, regulatory actions, macro risks) pushes them lower.

**Where Sentiment Appears**

- On the AI Insights page — as an overall market sentiment score
- On individual instrument pages — as instrument-specific sentiment
- On the Market Overview page — as sector-level sentiment heatmaps

**Using Sentiment Alongside Signals**

News sentiment is one input into the platform's overall analysis, not the only one. A LONG signal in a stock with strongly negative news sentiment deserves extra scrutiny. The strategies themselves do not directly block orders based on sentiment, but the AI Insights summary will flag this kind of conflict.

---

## 12. Market Opportunities

**What the Opportunities Page Shows**

The Opportunities page displays the output of the Market Scanner — the platform's continuous scan of all instruments in your Universe for potential setups that haven't yet become full signals.

Each opportunity has:

- Instrument name
- Opportunity type (for example, RSI Oversold, VWAP Breakout Setup)
- Score (0 to 100 — higher means a stronger setup)
- Market regime (trending, ranging, or volatile)

**How to Use Opportunities**

Opportunities are early-stage findings. They highlight instruments worth watching. Not every opportunity becomes a signal — the strategy engine applies additional filters before issuing a full signal.

Use the Opportunities page to:

- Spot instruments building toward a setup
- Watch for converging indicators across multiple strategies
- Prioritize which instruments to monitor during the session

---

## 13. Backtesting

**What Backtesting Does**

Backtesting runs a strategy against historical market data to show you how it would have performed in the past. It does not predict future performance, but it helps you understand a strategy's characteristics.

**How to Run a Backtest**

1. Go to the Backtest page.
2. Select the strategy you want to test (for example, RSI Mean Reversion).
3. Select the instrument or universe of instruments to test against.
4. Set the date range (start date and end date).
5. Configure any strategy-specific parameters shown on screen.
6. Click "Run Backtest."

The backtest will process historical data and return results within a few seconds to a few minutes depending on the date range and number of instruments.

**Reading Backtest Results**

After the backtest completes, you will see:

- Total trades generated in the period
- Win rate
- Total PnL (in points or rupees depending on settings)
- Maximum drawdown
- Sharpe Ratio
- Average trade duration
- Best and worst individual trades
- Equity curve chart (showing portfolio value over time)

Compare multiple strategies on the same instrument and time period to understand which approach fits that instrument best.

---

## 14. Paper Daemon

**What the Paper Daemon Is**

The Paper Daemon is a fully autonomous paper trading engine. Once activated, it continuously monitors the market, generates signals, passes them through the risk engine, and places paper orders — without any manual intervention from you.

Think of it as a robot trader running entirely in simulation mode. It follows the same rules as manual paper trading but operates 24/7 during market hours.

**How to Start the Paper Daemon**

1. Go to the Paper Daemon page.
2. Review the configuration — which strategies are active, which instruments are in scope, what risk limits apply.
3. Click "Start Daemon."

The daemon status will change to "Running." You can monitor its activity in real time on the same page.

**Monitoring Daemon Activity**

While the daemon runs, you will see:

- Signals generated and their outcomes
- Orders placed and fills simulated
- Current paper positions and PnL
- Any signals rejected by the risk engine

**Stopping the Daemon**

Click "Stop Daemon" on the Paper Daemon page at any time. The daemon will stop generating new signals and orders but will not close existing paper positions automatically. You can close those manually from the Positions page.

---

## 15. Kill Switch

**What the Kill Switch Does**

The Kill Switch is an emergency stop mechanism. When activated, it immediately halts all trading activity:

- No new signals are converted to orders
- All pending and open orders are cancelled
- New order placement is blocked until the kill switch is deactivated

It does not automatically close your existing open positions. You must close those manually after activating the kill switch, or wait until the platform is back in normal operation and use an exit strategy.

**When to Use the Kill Switch**

Use the kill switch when:

- You see abnormal platform behavior (runaway orders, unexpected positions)
- News breaks that makes you want to stop all activity immediately
- You need to step away from the platform urgently during market hours
- Market conditions become extreme (flash crash, circuit breaker events)

**How to Activate**

The Kill Switch button is visible on the Dashboard at all times. Click it once. A confirmation dialog will appear. Confirm, and the kill switch activates immediately.

You will see a red Kill Switch indicator in the top bar while it is active.

**How to Deactivate**

Click the Kill Switch button again. Confirm in the dialog. The platform returns to normal operation. Any signals generated while the kill switch was active will need to be reviewed manually — they were not executed.

**Automatic Kill Switch**

The risk engine can also activate the kill switch automatically if your daily loss limit or maximum drawdown threshold is breached. When this happens, you will receive an alert and the top bar will show a red indicator. You must manually review the situation and deactivate the kill switch when you are ready to resume.

---

## 16. Daily Routine

Here is a recommended workflow for a trading day using StockSignalAnalyzer.

**Before Market Open (Before 09:00 IST)**

1. Open the platform and check the System Health page. Confirm all services show green status.
2. If you are using live trading, go to the Broker page and connect your Kite session. Kite sessions expire daily at 06:00 IST, so you must reconnect every morning.
3. Review the Capital page to confirm your available capital and allocation settings are correct.
4. Check the Risk page to confirm your daily loss limit and other risk parameters are set appropriately for today.
5. Check the AI Insights page for overnight news and sentiment summary.

**Market Open (09:15 IST — 15:30 IST)**

6. Monitor the Dashboard for incoming signals and system status.
7. Review the Opportunities page for early setups as the market opens.
8. Watch the Signals page for new signals from the strategy engine.
9. Review any active positions on the Positions page and monitor unrealized PnL.
10. Check the Analytics page periodically to track today's performance.

**Intraday Monitoring**

11. Watch the Kill Switch status in the top bar. If the system is showing unexpected behavior, activate it immediately.
12. Review AI Insights for midday updates after major market moves.
13. Use the Market Overview page to track market breadth and regime shifts.

**Before Market Close (Before 15:30 IST)**

14. Decide which positions you want to close before end of day. F&O positions that are not closed before 15:30 may face exchange-level square-off.
15. Close positions manually from the Positions page or let exit signals handle it.
16. Review the day's Analytics after market close.

**After Market Close**

17. Check the Orders page to confirm all orders are in a terminal state (FILLED or CANCELLED). No order should be in OPEN or PENDING state after market hours.
18. Review Analytics for the day's PnL, win rate, and slippage.
19. Check the Audit Log in Settings if you need a detailed record of all platform actions.

---

## 17. Troubleshooting

**Kill Switch showing error 429 when I try to activate**

A 429 error means the platform is receiving too many requests in a short period. Wait 30 to 60 seconds and try again. If the error persists, reload the page and attempt again. If you cannot activate the kill switch through the UI, contact your system administrator immediately.

**Kite session has expired — orders are being rejected**

This happens every morning when the Kite session expires at 06:00 IST. Go to the Broker page and click "Connect to Kite." Complete the Zerodha login and authorization. Once reconnected, live trading will resume. Orders that were rejected during the expired session will not be automatically retried — review the Signals page and re-enter any missed setups manually.

**Signals are being generated but no orders are placed**

Check the Signals page for the rejection reason shown next to each signal. Common causes:

- Risk engine rejection: One of your risk limits was breached. Go to the Risk page and review your thresholds.
- Kill switch is active: Deactivate the kill switch from the Dashboard.
- Broker not connected: Go to the Broker page and reconnect to Kite.
- Confidence score too low: The signal's confidence score is below your minimum threshold. Adjust this in Settings if needed.

**Positions show but PnL is not updating**

This usually means the real-time WebSocket connection has been interrupted. Try refreshing the page. If PnL still does not update after refresh, check the System Health page for WebSocket status. A red or amber indicator there confirms the connection is down. Contact your system administrator.

**Paper Daemon stopped unexpectedly**

Go to the Paper Daemon page and check the daemon status log. The most common causes are a risk limit breach (daily loss limit hit in paper mode) or a system resource issue. If the risk limit was hit, review and reset your paper trading risk parameters before restarting.

**Strategy is generating no signals**

Check the Market Overview page to understand the current market regime. Some strategies are designed for trending markets and will generate no signals in a ranging or low-volatility regime. This is expected behavior, not a bug. If you believe signals should be generating, check the System Health page to confirm the strategy engine is running.

**I see duplicate positions for the same instrument**

This can happen if multiple signals fired for the same instrument before the first order was filled. Go to the Positions page and review each position. If positions are genuinely duplicated unintentionally, use the Kill Switch to stop further activity, then close the positions manually. Review your risk engine configuration to add tighter concentration limits to prevent this in future.

**I cannot find a specific order**

Use the filter controls on the Orders page. Orders older than the default date range may be hidden. Expand the date range filter to search further back. You can also search by Correlation ID if you know it from the signal.

---

*For additional support, contact your platform administrator or refer to the TRADING_PLATFORM_GLOSSARY.md for definitions of any unfamiliar terms.*
