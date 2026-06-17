# UX Review Report
**Project:** StockSignalAnalyzer  
**Date:** 2026-06-16  
**Scope:** All dashboard pages — frontend UX analysis based on component review

---

## Executive Summary

StockSignalAnalyzer's frontend is functionally solid: data tables are consistent, color-coded states are applied throughout, and live WebSocket updates are wired into key pages. However, the platform is primarily data-dense without adequate onboarding support for first-time users. Several pages lack meaningful empty states, error states, or contextual help. The pages most in need of UX attention are System Health, Universe, and the Settings page which is missing critical controls. The strongest UX implementations are found in Market Overview (good empty states with next-step guidance), Broker (clear mode-aware panels with inline workflow instructions), and AI Insights (clean empty state with a clear call-to-action).

---

## Page-by-Page Review

---

### 1. Dashboard

**What it shows:** Trading mode badge, system status, 4 metric tiles (capital, margin, positions, signals), 30-day PnL chart, unrealized PnL panel, recent signals table.

**Good:**
- Trading mode badge (PAPER/LIVE) is prominently placed in the header row.
- System health status indicator is co-located with the mode badge.
- Risk limits (daily loss limit, weekly loss limit, risk per trade, max positions) are displayed inline in the unrealized PnL panel — useful context for active traders.
- Last-updated timestamp is shown from the broker status.

**Missing / Issues:**
- No page-level heading or title. First-time users have no breadcrumb or label telling them they are on "Dashboard."
- When `eas` (effective account state) is null (no capital allocation configured), all 4 metric tiles show "—" with no explanation. A new user would not know why capital data is missing or how to fix it.
- The PnL chart (`PnLChart`) shows 30 days of data but there is no label explaining that the chart is "Daily PnL" until the section header — which is only visible on scroll on smaller viewports.
- No error state if the broker status API call fails — the header row simply renders nothing.
- No "Get started" prompt for first-time users who have zero positions and zero signals.

**Recommendations:**
- Add a first-run banner: "Welcome to StockSignalAnalyzer. Start by configuring a Capital Allocation, then add symbols to your Universe." with links to the respective pages.
- Add an error state for failed broker/health queries (e.g., "Unable to reach the backend. Check your server connection.").
- Show a descriptive empty state when all metrics are "—": "No capital allocation active. Go to Capital to configure one."

---

### 2. Market Overview

**What it shows:** Market breadth metrics (advances, declines, A/D ratio, breadth score, above-200DMA%, 52W highs/lows), market sentiment (direction, avg score, article counts).

**Good:**
- Empty state for breadth: "No breadth data yet. The system collects breadth data during market hours." — clear and informative.
- Empty state for sentiment: "No sentiment data yet. Run 'News Refresh' from the News section to populate." — actionable with next-step instruction.
- Metric tiles use trend arrows (up/down) for A/D ratio.

**Missing / Issues:**
- No error state if the API call itself fails (network error vs. empty data looks the same after the promise resolves to null).
- No last-updated timestamp for breadth or sentiment data. Users cannot tell if data is from today or stale.
- "Above 200 DMA" metric has no tooltip explaining what this means. Non-expert users may not understand it.
- No refresh button — users must navigate away and back to re-fetch.
- Breadth data collection mechanism is not explained (users don't know how or when breadth is calculated).

**Recommendations:**
- Add a `last_updated` timestamp next to both sections.
- Add a "Refresh" button that re-fetches without page navigation.
- Add tooltip or info icon on "Above 200 DMA %", "A/D Ratio", and "Breadth Score" explaining their interpretation.

---

### 3. Signals

**What it shows:** Signals table with filter buttons (PENDING, APPROVED, REJECTED, EXECUTED), Approve/Reject action buttons on pending signals.

**Good:**
- Filter buttons are clearly labeled and toggle-able.
- State colors are semantically appropriate (yellow for pending, green for approved, red for rejected).
- Approve/Reject buttons are only shown on actionable states (RISK_PENDING etc.).
- Empty state via `DataTable(emptyMessage="No signals")`.
- Live updates via `useSignalLiveUpdates()`.

**Missing / Issues:**
- "No signals" is too terse. A first-time user does not know whether the system generates signals automatically or if they need to trigger something.
- `signal_type` column header is "Direction" but values are LONG/SHORT/NEUTRAL — this is accurate but "Direction" might be confused with "Signal Type" (strategy classification).
- "Regime" column has no tooltip explaining what market regime means in this context.
- No bulk-action capability (approve all pending, reject all pending).
- No page title or breadcrumb visible in the view component.
- "Awaiting risk approval" sub-label on dashboard metric tile is helpful — could be echoed on this page.
- No explanation of the signal lifecycle (SCORING → RISK_PENDING → RISK_APPROVED → EXECUTED).

**Recommendations:**
- Change empty state to: "No signals found. The system generates signals automatically based on configured strategies. Check back during market hours."
- Add a signal lifecycle diagram or tooltip on the Status column showing the state machine.
- Add tooltip on "Regime" and "Confidence" column headers.

---

### 4. Orders

**What it shows:** Orders table with filter buttons (OPEN, PENDING, FILLED, CANCELLED), Cancel button on cancellable orders.

**Good:**
- State colors are consistent and semantically correct (green for FILLED, red for REJECTED, muted for cancelled/expired).
- Trading mode badge shown per row (useful when both PAPER and LIVE orders are mixed).
- "MKT" displayed when no limit price is set — correct market order terminology.
- Live updates via `useOrderLiveUpdates()`.
- Empty state: "No orders".

**Missing / Issues:**
- "No orders" is too terse for a first-time user.
- Order ID is truncated (only 8 chars shown) — no way to see or copy the full ID.
- No search or symbol filter — in a live session with many orders, users cannot filter to a specific symbol.
- No date range filter.
- REJECTED_PRE_SUBMIT state is displayed raw — users may not understand what pre-submit rejection means.
- No error state for failed orders query.
- The "Mode" column shows a badge per row; would be cleaner to have a global filter for mode.

**Recommendations:**
- Expand Order ID cell to show full ID on hover (tooltip or click-to-copy).
- Add a symbol search/filter input above the table.
- Rename/tooltip REJECTED_PRE_SUBMIT to "Rejected before broker submission (risk check failed)".
- Change empty state to: "No orders yet. Orders are created when signals pass risk checks."

---

### 5. Positions

**What it shows:** Open positions table with PnL display, close button, total unrealized PnL summary.

**Good:**
- Total unrealized PnL summary is prominently shown in the header row.
- Color-coded LONG/SHORT with profit/loss colors.
- PnLDisplay component shows both unrealized and realized PnL per row.
- Trading mode badge per row.
- Live updates via `usePositionLiveUpdates()`.
- Empty state: "No open positions".

**Missing / Issues:**
- Hardcoded to show only OPEN positions; no way to view CLOSED positions history from this page.
- No position age column (how long the position has been open).
- No stop-loss or target price columns — traders need this context.
- "LTP" column header is not friendly to non-trader users (stands for "Last Traded Price").
- Close button has no confirmation dialog — misclick can close a real position in live mode.
- No error state for failed positions query.

**Recommendations:**
- Add a tab or toggle to show closed positions with realized PnL.
- Add "Opened X hours ago" to the Opened column or as a hover tooltip.
- Rename "LTP" to "Current Price (LTP)" or add a tooltip.
- Add a confirmation dialog before closing a position, especially in LIVE mode: "Are you sure you want to close [SYMBOL] [DIRECTION] [QTY]?"

---

### 6. Analytics

**What it shows:** 4 metric tiles (Total PnL, Win Rate, Avg E2E Latency, Avg Slippage), execution records table.

**Good:**
- Win rate shows trade count sub-label (e.g., "47 trades").
- E2E latency and slippage metrics are operationally useful.
- Empty state: "No execution records yet".

**Missing / Issues:**
- No date range filter — users can only see the most recent 50 records.
- No chart or visualization — PnL over time, win/loss ratio bar chart, or drawdown chart would be far more useful than a raw table.
- Avg slippage in "bps" (basis points) may be unfamiliar to users without a trading background.
- No explanation of what "E2E Latency" measures (signal generation to order fill?).
- No export capability.
- Metric tiles remain "—" when no data is present; no explanatory empty state.

**Recommendations:**
- Add a PnL over time chart (line chart by trade date).
- Add tooltip on "E2E Latency (ms)" explaining it measures signal-to-fill time.
- Add tooltip on "Slippage (bps)" with a plain-English example.
- Add a date range filter to the execution records table.

---

### 7. Broker

**What it shows:** Session status badge, broker status card (capabilities, latency), Kite session panel (LIVE only), paper mode info panel (PAPER only), kill switch controls.

**Good (strongest page in the platform):**
- Mode-aware panels: paper mode shows a green "Paper session ready" indicator; live mode shows the Kite OAuth flow with step-by-step instructions.
- Inline workflow documentation: "Click below to open the Kite OAuth page. After login, Kite will redirect to your callback URL with a request_token. Paste it here to activate the session."
- Kill switch state is clearly shown with activation time and reason.
- Capability status grid (Market Data, Order Placement, Historical Data) with OK/DEGRADED/UNAVAILABLE labels.
- WebSocket-driven updates for broker.status, kill_switch events.

**Missing / Issues:**
- Kill switch activation has no confirmation dialog — a misclick on "Activate Kill Switch" halts all trading immediately.
- No explanation of what "DEGRADED" means for a capability vs. "UNAVAILABLE."
- Session expiry countdown is shown as an absolute datetime — a countdown timer or "expires in X hours" label would be more intuitive.
- In live mode, after pasting the `request_token`, there is no progress indicator between form submission and session confirmation.
- Latency value (e.g., "42.33ms") has no threshold indicator — users don't know if this is good or bad.

**Recommendations:**
- Add a confirmation modal for kill switch activation: "This will halt all order submissions immediately. Are you sure?"
- Show session expiry as "Expires in 4h 22m" (countdown) rather than raw datetime.
- Add a tooltip on DEGRADED/UNAVAILABLE capability status.
- Add a loading spinner in the `KiteTokenInput` form submit button while the callback is being processed.

---

### 8. System Health

**What it shows:** Status indicator (healthy/degraded/unhealthy), app version and environment, static message "Full component health reporting requires backend observability extension."

**Missing / Issues (weakest page):**
- The page essentially shows a single status badge and a static placeholder text. This is a very thin page.
- No component-level breakdown (Database, Redis, broker connectivity, AI provider).
- No historical health data or incident log.
- No actionable guidance when the system is degraded or unhealthy.
- The static message ("requires backend observability extension") is confusing — it implies the feature is permanently unavailable when in fact it likely means it is planned for a future phase.

**Recommendations:**
- Replace the static message with a list of known health components and their last-checked status, even if many are "Unknown."
- Add per-component status: Database (connected/disconnected), Redis (connected/disconnected), Broker (healthy/degraded), AI Provider (enabled/disabled/erroring).
- Remove or rephrase the "requires backend observability extension" message to avoid confusion. If the feature is planned, say "Component-level health monitoring is planned for a future update."

---

### 9. Opportunities

**What it shows:** Opportunities table with symbol, type, direction, scores, a "Run Scan" button.

**Good:**
- Empty state: "No opportunities found. Click 'Run Scan' to scan the market." — actionable.
- Direction coloring (green for LONG, red for SHORT).
- Spinner on scan button during processing.

**Missing / Issues:**
- No explanation of how scores are computed (total_score, technical_score, volume_score, sentiment_score).
- No threshold indicators — is a score of 7.5 good or bad?
- No "type" descriptions — what does opportunity type mean (e.g., breakout, pullback)?
- Created time shows only time (no date) — on next day or after midnight, the date context is lost.
- No auto-refresh — opportunities go stale as the market moves.
- No indication of when the last scan was run.

**Recommendations:**
- Add a "Last scanned: X minutes ago" label.
- Add tooltips on Score, Technical Score, and Volume Score columns.
- Show full datetime for Created (not just time).
- Consider auto-running a scan when the page loads if no opportunities exist (or provide a clear instruction that the user must run a scan first).

---

### 10. AI Insights

**What it shows:** Regime badge with confidence, summary, recommendation, key themes, opportunities, risks, generated timestamp, "Generate New" button.

**Good:**
- Empty state: "No AI insights generated yet. Click 'Generate New' to create one." — clear.
- Regime badge is color-coded by type (green/red/orange/yellow).
- Recommendation is highlighted in a distinct purple card.
- Generating state shows spinner on the button.

**Missing / Issues:**
- Sector outlook data is returned by the AI but not rendered on the page.
- No history view — users cannot compare today's regime to yesterday's.
- No explanation of what "Regime Confidence" means in practical terms.
- If generation fails (network error), the UI silently swallows the error (`catch(e) { console.error(e) }`) — no user-visible error message.
- No indication of whether the displayed insight uses real AI or the rule-based fallback (model_used is not shown).

**Recommendations:**
- Display `sector_outlook` as a small grid of sector badges.
- Add error handling for failed generation with a toast: "Failed to generate insight. Please try again."
- Show the model used (e.g., "Generated by gpt-4.1-mini" or "Generated by rule-based fallback").
- Add a "History" tab showing the last 7 insights.
- Add a tooltip on "Confidence" explaining the interpretation.

---

### 11. Backtest

**What it shows:** Backtest configuration form (strategy, symbol, timeframe, dates, capital), run button, latest result metrics, recent runs table.

**Good:**
- Form is well-structured with clear labels and sensible defaults.
- Recent runs table includes all key metrics (Win%, P&L, Return%, MaxDD%, PF).
- Empty state: "No backtest runs yet." — appropriate.
- Spinner on run button.

**Missing / Issues:**
- Timeframe input is a free-text field (accepts "D, 60m, 15m") — no validation or dropdown; invalid values will silently fail.
- No error message on failed backtest runs (`catch(e) { console.error(e) }` only).
- No progress indicator for long-running backtests — the button just says "Running..." with no ETA or cancellation option.
- Profit Factor (PF) column has no tooltip explaining what a good PF value looks like.
- Max Drawdown is shown as a negative percentage in red but without explicit negative sign (-15.2%).
- "Run ID" is not shown in the recent runs table, making it impossible to reference a specific run.

**Recommendations:**
- Replace timeframe text input with a dropdown (D / 60m / 30m / 15m / 5m).
- Add error toast on failed backtest: "Backtest failed. Check symbol and date range."
- Add tooltip on "PF" (Profit Factor): "A value > 1 means profitable; > 1.5 is generally considered good."
- Show an explicit minus sign or use color alone consistently for drawdown.

---

### 12. Paper Trading

**What it shows:** 4 metric tiles (paper positions, paper orders, active signals, unrealized PnL), open paper positions table.

**Good:**
- PnL display is prominently shown.
- Filtered to PAPER mode only — correctly isolated from live positions.
- Empty state: "No open paper positions" — appropriate.

**Missing / Issues:**
- No paper orders table shown — metric tile shows paper order count but clicking on it does nothing; full paper order list is on the Orders page.
- No paper account starting balance or total return percentage.
- No description of what paper trading mode is — a new user may not understand the concept.
- "Active Signals" metric tile on this page is not filtered to paper mode signals.
- No reset capability (to start a fresh paper trading session with reset PnL).

**Recommendations:**
- Add a brief introductory text: "Paper trading simulates real trading using live market prices. No real money is involved."
- Add a paper trading summary: initial capital, current value, total return %.
- Filter the "Active Signals" metric to paper-mode relevant signals.
- Add a mini paper orders table or a "View Paper Orders" link.

---

### 13. Settings

**What it shows:** Profile tab (username, role), Security tab (change password form with Zod validation).

**Good:**
- Password validation with Zod schema — checks min length and confirmation match.
- Inline validation errors are shown.
- Loading spinner on submit.

**Missing / Issues (significant gap):**
- No application settings (theme, timezone, notification preferences).
- No API key management (for users who need to configure their own Kite keys).
- No session management panel (active sessions, revoke sessions).
- No notification preferences (email, webhook, etc.).
- Profile tab is read-only with only username and role — no way to update email or display name.
- No two-factor authentication controls.
- The settings page has only 2 tabs but the platform has many configurable aspects spread across other pages (Risk, Capital, Universe).

**Recommendations:**
- Add a "Preferences" tab with theme toggle (light/dark), default timeframe, and timezone.
- Add a "Sessions" tab showing active login sessions with revoke buttons.
- Move or link to system-wide configuration (default risk profile, trading universe scope) from Settings.

---

### 14. Universe

**What it shows:** Data table of symbols (symbol, name, sector, F&O eligibility, index flag).

**Good:**
- Uses `DataTable` component with consistent styling.
- F&O column uses `StatusIndicator` (active/inactive) — clear visual.
- Empty state: "No symbols in universe".

**Missing / Issues:**
- No way to add or remove symbols from the UI — the universe appears read-only on the frontend.
- No search or filter by sector, name, or symbol.
- No explanation of what the "Universe" means in context of the trading system.
- "Universe Scope" is referenced in the Capital page but the Universe page doesn't explain how scope selection works.
- No count of F&O-eligible vs. non-F&O symbols.

**Recommendations:**
- Add a search/filter bar for symbol or sector.
- Add a summary row: "47 symbols | 32 F&O eligible | 3 indices."
- Add an "Add Symbol" button (even if it triggers a placeholder API call) so users understand the universe is configurable.
- Add a brief description at the top: "Your trading universe defines which stocks the system analyzes for signals."

---

### 15. Capital

**What it shows:** 4 EAS metric tiles, active allocation detail card, capital allocations table with activate button.

**Good:**
- Active allocation is prominently shown in a dedicated card.
- Multiple allocation support (table with activate buttons for inactive ones).
- Captured timestamp shown for EAS.

**Missing / Issues:**
- No "Create New Allocation" button — allocations appear to be admin-configured only.
- EAS metric tiles are blank with no description when no allocation is active.
- "EAS" acronym (Effective Account State) is not explained anywhere in the UI.
- `capital_source_mode` values (e.g., "BROKER_REPORTED", "CONFIGURED") are raw enum strings with no explanation.
- No explanation of the difference between "Broker Capital" and "Configured Capital" for new users.

**Recommendations:**
- Add a tooltip/info icon on each EAS metric tile explaining the value.
- Replace raw enum strings (`capital_source_mode`, `allocation_type`) with human-readable labels and tooltips.
- Add an empty state when no allocations exist: "No capital allocations configured. Contact your administrator to set up a capital allocation."

---

### 16. Risk

**What it shows:** Active risk profile card, risk profiles table with activate/deactivate buttons, recent risk decisions table.

**Good:**
- Active risk profile summary card with all key parameters.
- Risk decisions table shows rejection reasons — actionable for debugging.
- Empty state for both tables.

**Missing / Issues:**
- No "Create Risk Profile" button — profiles appear to be admin-configured only.
- Risk parameter values (e.g., `risk_per_trade_pct`, `drawdown_pct`) have no tooltips explaining how they are enforced.
- `profile_type` is shown as a raw enum string.
- Decision table signal IDs are truncated to 8 chars — no link to the corresponding signal.
- No visualization of risk utilization (e.g., current daily loss vs. limit).

**Recommendations:**
- Add a daily loss utilization bar: "Daily Loss: ₹4,200 of ₹10,000 limit (42%)."
- Add tooltips on risk parameters explaining their effect (e.g., "Risk per trade: The maximum % of capital risked on a single trade").
- Make signal IDs in the decisions table clickable to navigate to the corresponding signal.

---

## Onboarding Gaps (First-Time User Experience)

The platform has **no guided onboarding flow**. A first-time user who logs in for the first time encounters:

1. **Dashboard** with all metrics showing "—" (no capital allocation).
2. No call-to-action explaining what to do next.
3. No setup wizard or checklist.

**Recommended First-Run Checklist (could be displayed as a collapsible widget on the Dashboard):**

```
Getting Started with StockSignalAnalyzer
[ ] 1. Configure a Capital Allocation (Capital page)
[ ] 2. Set a Risk Profile (Risk page)
[ ] 3. Add symbols to your Universe (Universe page)
[ ] 4. Set Trading Mode (Broker page — currently PAPER)
[ ] 5. Run a News Refresh to populate sentiment (News page or Market Overview)
[ ] 6. Generate an AI Market Insight (AI Insights page)
[ ] 7. Wait for the system to generate your first Signal
```

---

## Overall UX Ratings

| Page | Empty State | Error State | Tooltips | First-Run Support | Overall |
|---|---|---|---|---|---|
| Dashboard | ⚠️ Minimal | ❌ Missing | ❌ None | ❌ None | C |
| Market Overview | ✅ Good | ❌ Missing | ⚠️ Partial | ✅ Actionable | B |
| Signals | ⚠️ Terse | ❌ Missing | ❌ None | ⚠️ Partial | C |
| Orders | ⚠️ Terse | ❌ Missing | ❌ None | ⚠️ Partial | C |
| Positions | ⚠️ Terse | ❌ Missing | ⚠️ Partial | ❌ None | C |
| Analytics | ✅ Good | ❌ Missing | ❌ None | ❌ None | C |
| Broker | ✅ Excellent | ✅ Good | ⚠️ Partial | ✅ Good | A- |
| System Health | ❌ Missing | ✅ Present | ❌ None | ❌ None | D |
| Opportunities | ✅ Actionable | ❌ Missing | ❌ None | ⚠️ Partial | B- |
| AI Insights | ✅ Good | ❌ Silent | ⚠️ Partial | ✅ Good | B |
| Backtest | ✅ Good | ❌ Silent | ❌ None | ⚠️ Partial | B- |
| Paper Trading | ✅ Good | ❌ Missing | ❌ None | ❌ None | C |
| Settings | N/A | ✅ (form) | ❌ None | ❌ None | C |
| Universe | ✅ Good | ❌ Missing | ❌ None | ❌ None | C |
| Capital | ⚠️ Partial | ❌ Missing | ❌ None | ❌ None | C |
| Risk | ✅ Good | ❌ Missing | ❌ None | ❌ None | B- |

---

## Top Priority Recommendations

1. **Add a first-run onboarding checklist** on the Dashboard. This single change would dramatically improve the new user experience.

2. **Add error states** to all pages that make API calls. Currently, network errors or 500 responses silently render empty/blank states, which is indistinguishable from "no data."

3. **Add tooltips** to all technical financial terms (LTP, A/D Ratio, Breadth Score, Basis Points, Regime, Confidence, Profit Factor, E2E Latency). These are essential for operators who are technically skilled but not finance experts.

4. **Add kill switch and close-position confirmation dialogs.** These are high-consequence actions that need a confirmation gate.

5. **Rebuild the System Health page.** The current implementation is essentially a placeholder. Even a basic component checklist (DB, Redis, Broker, AI) would be a major improvement.

6. **Add error handling for async calls that currently use `catch(e) { console.error(e) }`** (AI Insights, Opportunities, Backtest, Market Overview). Replace with user-visible toast notifications.
