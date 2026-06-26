# Strategy Weights & Thresholds Reference

**Version:** strategy.yaml v1.2  
**Last updated:** 2026-06-18  
**Purpose:** Single truth document for every weight, threshold, gate, and research basis in the scoring system.

---

## 1. Component Base Weights (total = 100)

| Component | Max Pts | Rationale |
|-----------|---------|-----------|
| OI_BUILDUP | **25** | Primary signal: institutional positioning via price+OI quadrant. Change-in-OI PCR is the sharpest intraday institutional flow indicator for NSE F&O. |
| TREND | **20** | ADX + EMA + Supertrend + DI spread confirms directional momentum. Pure trend-follow is the #1 alpha source in intraday options. |
| OPTION_CHAIN | **20** | IV percentile, GEX, OI walls, PCR direction trend — options market microstructure. Max pain gravity, skew, and wall proximity define strike-level risk. |
| VOLUME | **15** | Volume ratio, OBV, cumulative delta, VPOC. Volume confirms price moves; divergence is an early reversal warning. |
| VWAP | **10** | Research: VWAP is #1 intraday institutional anchor (Sharpe 2.1 in trend-follow setups). Price vs VWAP defines buy/sell bias. |
| SENTIMENT | **5** | Currently wired to NeutralSentimentProvider (always 50) — regime multipliers reduce to ≈2 pts effective. Placeholder for real NLP integration. |
| IV_ANALYSIS | **5** | HV/IV ratio and VIX penalty. Determines whether buying or selling premium is appropriate; penalizes short-vol in fear zones. |
| **Total** | **100** | |

---

## 2. Regime Multipliers

Effective weight = base × multiplier. Applied before score aggregation so the system emphasizes the right signals per market condition.

| Component | TRENDING_BULL | TRENDING_BEAR | SIDEWAYS | HIGH_VOL | LOW_VOL |
|-----------|:---:|:---:|:---:|:---:|:---:|
| OI_BUILDUP | 1.15 | 1.15 | 1.10 | 0.70 | 1.00 |
| TREND | **1.40** | **1.40** | 0.25 | 0.50 | 0.60 |
| OPTION_CHAIN | 0.85 | 0.95 | **1.60** | 1.50 | 1.45 |
| VOLUME | 1.25 | 1.25 | 1.00 | 1.20 | 1.00 |
| VWAP | **1.50** | **1.50** | 1.55 | 0.55 | 1.30 |
| SENTIMENT | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 |
| IV_ANALYSIS | 0.45 | 0.50 | 1.65 | **1.90** | **1.80** |

**Key regime logic:**
- **Trending**: TREND (1.40) and VWAP (1.50) dominate. VWAP position is the most reliable trend-follow signal per research.
- **Sideways**: OPTION_CHAIN (1.60) and IV_ANALYSIS (1.65) dominate. OI walls and IV regime define the range.
- **High Volatility**: IV_ANALYSIS (1.90) is highest. VWAP (0.55) disabled — price gaps past it in panic. OI_BUILDUP (0.70) unreliable during panic gaps.
- **Low Volatility**: IV_ANALYSIS (1.80) and OPTION_CHAIN (1.45) dominate. Premium-selling territory.

---

## 3. Signal Execution Gates

These are score-level gates applied *after* all components score:

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| `min_score_to_execute` | **70** | Research: only top-decile signals (score ≥70/100) have statistically significant win rates in F&O intraday. Below 70 = WEAK_SIGNAL. |
| `min_confidence_to_execute` | **65** | Confidence = directional conviction across components. <65 = mixed signals. |
| `data_completeness_min_pct` | **60%** | At least 5 of 7 components must have data. OI_BUILDUP and OPTION_CHAIN unavailable outside market hours. |
| `direction_conviction_min` | **0.50** | max(long,short) / max_weight ≥ 0.50 for dominant direction. Prevents execution on coin-flip signals. |

---

## 4. Pre-Scoring Hard Gates (Scanner Level)

These gates fire **before** any component scoring. A triggered gate returns immediately with no score — signal is dropped.

| Gate | Condition | Reason |
|------|-----------|--------|
| **Opening Volatility** | IST time 09:15–09:30 | First 15 min = price discovery chaos; IV dislocated; options gapping. No reliable entry. |
| **Closing Volatility** | IST time ≥ 15:00 | Last 20 min before MarketCloseExitService (15:20 expiry). No hold window remaining. |
| **VIX Hard Gate** | India VIX ≥ 22.0 | Fear zone: option premiums severely dislocated. Research: VIX >20 = high vol warning; 22+ = confirmed fear. Buying options in fear = overpaying IV. |
| **RSI Extreme Gate** | RSI > 80 (LONG) or RSI < 20 (SHORT) | Overbought/oversold exhaustion at entry; option premium already peak. |
| **MACD Direction Gate** | MACD line vs signal mismatch with trade direction | Momentum not confirmed. LONG requires MACD > signal; SHORT requires MACD < signal. Research: MACD+RSI combo achieves 73% win rate when filters align. |
| **Expiry Day Gamma Gate** | 0-DTE after 11:00 IST | Gamma accelerates exponentially near expiry; long options destroyed by theta in final hours. Safe window only 09:30–11:00 on expiry day. |

---

## 5. Component 1 — OI Build-up (max 25 pts)

### OI Quadrant Classification

| Quadrant | OI Change | Price Change | Interpretation |
|----------|-----------|--------------|----------------|
| Long Build-up | ↑ ≥ 1.8% | ↑ ≥ 0.25% | Institutions entering long — bullish |
| Short Build-up | ↑ ≥ 1.8% | ↓ ≥ 0.25% | Institutions entering short — bearish |
| Short Covering | ↓ | ↑ | Shorts unwinding — mild bullish |
| Long Unwinding | ↓ | ↓ | Longs exiting — mild bearish |
| Ambiguous | Mixed/small | Mixed/small | Floor score only: 3 pts |

**Thresholds:**
- `oi_change_strong_pct`: **1.8%** — OI change must be ≥1.8% to classify as meaningful (lowered from 2.0 to catch early accumulation; research: 1%+ = meaningful signal)
- `price_change_min_pct`: **0.25%** — Minimum price confirmation (lowered from 0.3; research: 0.25% filters noise without missing moves)

### Score Formula

| Quadrant | Score Formula |
|----------|---------------|
| Long Build-up | `OI_change × 1.8 + price_change × 2.0`, capped at 25 |
| Short Covering | `OI_change × 1.0 + price_change × 1.5`, capped at 15 |
| Ambiguous | Floor 3.0 pts |

### PCR Adjustments (on top of quadrant score)

| PCR Range | Adjustment |
|-----------|------------|
| PCR < 0.7 | –2.0 pts (call euphoria / bearish tilt) |
| PCR 0.7–1.0 | neutral |
| PCR 1.0–1.3 | +2.0 pts (bullish institutional positioning) |
| PCR > 1.3 | +3.0 pts (strong bullish) |

**Research basis**: NSE NIFTY PCR oscillates 0.8–1.3 normally. <0.7 = bearish tilt confirmed by call buying; 1.0–1.3 = neutral-to-bullish; >1.3 = strong institutional long bias. >1.8 = exhaustion reversal risk (not scored separately).

### OFI Confluence Bonus

When **both** OI quadrant AND PCR confirm the same direction simultaneously:
- Long Build-up + PCR ≥ 1.0 → **+3 pts** (institutions stacking price AND options flow)
- Short Build-up + PCR ≤ 0.9 → **+3 pts** (call writers and short OI aligned)

### FII & Max Pain Adjustments

| Factor | Threshold | Adjustment |
|--------|-----------|------------|
| FII net | ≥5,000 contracts net long/short | +2.0 pts toward FII direction |
| Max pain proximity | within 1.0% of max pain | +2.0 pts (gravitational pull on DTE ≤3) |

---

## 6. Component 2 — Trend Following (max 20 pts)

### Step 1: ADX Base Score

| ADX Range | Score |
|-----------|-------|
| < **20.0** | **0** — HARD GATE: no trend signal (was 15; raised per research: ADX<20 = weak/absent trend) |
| 20–25 | 8 pts (weakest acceptable) |
| 25–28 | 12 pts (moderate) |
| 28–32 | 16 pts (strong) |
| 32–36 | 18 pts (very strong) |
| > 36 | 20 pts (maximum) |

**Research**: "Stop generating signals when ADX below 20 — reduces drawdown by 18% in backtests." For intraday 5-min charts, ADX 20 is the minimum meaningful threshold.

### Step 2: DI Spread Score

| DI Spread (DI+ − DI−) | Score |
|------------------------|-------|
| < 5 | 0 pts |
| 5–10 | 3 pts |
| 10–15 | 5 pts |
| > 15 | 7 pts |

Direction determined by: DI+ > DI− → LONG dominant; DI− > DI+ → SHORT dominant.

### Step 3: EMA Alignment Score

| Alignment | Score (to dominant direction) |
|-----------|-------------------------------|
| Full stack (20>50>200 bull or 20<50<200 bear) | 5 pts |
| Partial 20 vs 50 only | 2 pts |
| Partial 20 vs 200 only | 1 pt |
| EMA20 unavailable | 0 pts |

### Step 4: Supertrend

| Direction | Score |
|-----------|-------|
| Confirms dominant direction | +3 pts |
| Against dominant direction | 0 pts |

### Step 5: Multi-Timeframe Alignment (placeholder)

Currently 0 pts — Phase 14+ will add cross-TF data. Conservative default.

### Step 6: RSI Gate (gradated)

| RSI Zone | Score |
|----------|-------|
| LONG sweet spot (55–70) | **3 pts** (rsi_gate_score 1 + sweet_bonus 2) |
| LONG acceptable range (45–75) | 1 pt |
| LONG outside range | –1 pt |
| SHORT sweet spot (30–45) | **3 pts** |
| SHORT acceptable range (25–55) | 1 pt |
| SHORT outside range | –1 pt |

**Research**: RSI 55–70 for LONG = momentum building, not exhausted. Buying at RSI >75 = paying peak premium into exhaustion. RSI <60 at entry + MACD confirmation = 73% win rate combo.

### Step 7: Prime Time Window Bonus

| IST Window | Bonus |
|------------|-------|
| 10:00–11:30 | +3 pts |
| 13:00–14:00 | +3 pts |
| All other times | 0 pts |

**Research**: Post-open momentum window (10–11:30) is when price discovery is complete and institutional directional flow is strongest. Post-lunch (13–14) is the breakout continuation window before closing volatility. Both windows verified by AIMarketAnalyzer strategy research.

### Step 8: ADX Rising Bonus

| Condition | Bonus |
|-----------|-------|
| ADX is rising (current > 3-bars-ago) AND ADX ≥ 20 | +2 pts |
| Otherwise | 0 pts |

**Research**: Rising ADX = trend accelerating, not exhausting. Gives higher confidence in trend-continuation option setups.

### Maximum Possible Score (Component 2)

All bonuses stacked: 20 (ADX very strong) + 7 (DI spread) + 5 (EMA full) + 3 (Supertrend) + 3 (RSI sweet) + 3 (prime time) + 2 (ADX rising) = **43 raw**, capped at **20 pts**.

---

## 7. Component 3 — Option Chain Analysis (max 20 pts)

### Step 1: IV Percentile Scoring

**LONG signals** (buying calls/puts — want low IV so premium is cheap):

| IV Percentile | Score |
|---------------|-------|
| 0–20% | 6 pts (cheapest — best time to buy vol) |
| 20–40% | 4 pts |
| 40–60% | 3 pts |
| 60–75% | 1 pt |
| > 75% | 0 pts (expensive premium — avoid buying) |

**SHORT signals** (selling premium — want high IV so premium is rich):

| IV Percentile | Score |
|---------------|-------|
| 0–30% | 2 pts |
| 30–55% | 4 pts |
| 55–70% | 6 pts |
| > 70% | 8 pts (richest premium — best time to sell) |

### Step 2: IV Skew

If put IV ≠ call IV by ≥1.0%: **+2 pts** to the side the skew confirms.

### Step 3: GEX (Gamma Exposure)

| GEX Position | Score |
|--------------|-------|
| Aligned with trade direction | +2 pts |
| Against trade direction | –1 pt |
| Gamma squeeze setup | +2 pts |

### Step 4: OI Wall Proximity

| Distance to OI Wall | Score |
|--------------------|-------|
| < 0.5% away (wall blocks price) | –3 pts |
| 0.5–1.0% | 0 pts |
| 1.0–2.0% | +2 pts |
| > 2.0% (room to run) | +3 pts |

### Step 5: PCR Direction Trend

| PCR vs Trend | Score |
|--------------|-------|
| PCR confirms trade direction | +2 pts |
| PCR against trade direction | –1 pt |

---

## 8. Component 4 — Volume Analysis (max 15 pts)

### Step 1: Volume Ratio (current / 20-bar average)

| Volume Ratio | Score |
|--------------|-------|
| < 0.5× | 3 pts (thin volume — low conviction) |
| 0.5–1.0× | 6 pts |
| 1.0–1.5× | 9 pts (average-to-above) |
| 1.5–2.0× | 12 pts |
| > 2.0× | 15 pts (volume surge — institutional flow) |

**Research (OFI)**: Order Flow Imbalance with 2×+ volume = strongest confirmation of directional move. Reduces false breakout entries.

### Step 2: Volume Divergence Penalty

Price moves against volume direction: **–5 pts** (warns of potential reversal).

### Step 3: OBV Confirmation

| OBV | Score |
|-----|-------|
| OBV trend confirms direction | +2 pts |
| OBV diverges from direction | –2 pts |

### Step 4: Cumulative Delta

| Delta | Score |
|-------|-------|
| Confirms direction | +2 pts |
| Against direction | –2 pts |

### Step 5: VPOC Proximity

Within 0.2% of Volume Point of Control: **+1 pt** (key level of interest).

---

## 9. Component 5 — VWAP Analysis (max 10 pts)

### Mode A (Sideways / High Volatility regime — mean reversion)

Price must be extended from VWAP and RSI must confirm exhaustion:

| VWAP Distance | Score | Volume Req | RSI Gate (LONG entry) |
|---------------|-------|------------|----------------------|
| > 1.5σ from VWAP | 10 pts | ≥ 1.5× avg | RSI ≤ 35 |
| > 1.0σ from VWAP | 7 pts | ≥ 1.2× avg | RSI ≤ 45 |
| > 0.5σ from VWAP | 4 pts | any | RSI ≤ 50 |

**VWAP touch count degradation** (each revisit weakens bounce reliability):

| Touch Count | Multiplier |
|-------------|------------|
| 0 (first approach) | 1.00 |
| 1 previous touch | 0.88 |
| 2 previous touches | 0.70 |
| 3+ previous touches | 0.50 |

### Mode B (Trending regime — trend follow)

| VWAP Position | Score |
|---------------|-------|
| Bouncing off VWAP in trend direction | 10 pts (highest confidence) |
| Price above VWAP (LONG) without bounce | 7 pts |
| Price on wrong side of VWAP | 2 pts (caution) |

"Near VWAP" bounce defined as within **0.35σ** of VWAP.

**Research**: VWAP is the #1 intraday signal (Sharpe ratio 2.1 in trend-following setups). Best entry window is 9:30–11:30 which overlaps with prime time bonus. Minimum 1:2 RR when using VWAP entry.

---

## 10. Component 6 — Sentiment Analysis (max 5 pts)

Currently a pass-through: `NeutralSentimentProvider` always returns score 50, giving both LONG and SHORT 2.5 pts. Regime multipliers reduce this to **≈1 effective pt** in all regimes (multiplier: 0.40 everywhere).

**Real-world impact:** Near-zero. Placeholder for future NLP/news sentiment integration.

| Sentiment Level | Long Score | Short Score |
|-----------------|------------|-------------|
| Strongly Bullish (≥80) | 5.0 | 0.0 |
| Bullish (60–80) | 4.0 | 1.0 |
| Neutral (40–60) | 2.5 | 2.5 |
| Bearish (20–40) | 1.0 | 4.0 |
| Strongly Bearish (<20) | 0.0 | 5.0 |

---

## 11. Component 7 — IV Analysis (max 5 pts)

### LONG Vol (buying options — want low IV)

| IV Percentile | Score |
|---------------|-------|
| ≤ 20% | 5 pts (cheapest — strong buy-vol signal) |
| 20–35% | 3 pts |
| 35–50% | 1 pt |
| > 50% | 0 pts |

### SHORT Vol (selling premium — want high IV)

| IV Percentile | Score |
|---------------|-------|
| ≥ 70% | 5 pts (richest premium) |
| 55–70% | 3 pts |
| 40–55% | 1 pt |
| < 40% | 0 pts |

### HV/IV Ratio Bonus

| HV/IV Ratio | Interpretation | Bonus |
|-------------|----------------|-------|
| ≥ 1.10 | HV > IV by 10%+ → options measurably cheap → buy vol | +2 pts |
| ≤ 0.80 | HV < IV → options expensive → sell vol | +2 pts |

### VIX Short-Vol Penalty

| India VIX | Penalty |
|-----------|---------|
| ≥ 20 | –2 pts against short-vol signals |

**Note**: VIX ≥ 22 also triggers the scanner-level hard gate that drops the signal entirely before scoring. The VIX 20 threshold here is a softer deterrent for the 20–22 zone.

---

## 12. Grade A / B Signal Sizing

Applied after a signal scores ≥70 and passes all gates:

| Grade | Min Score | SL | Target | R:R Ratio |
|-------|-----------|----|--------|-----------|
| **Grade A** | 65 | 20% | 35% | 1.75:1 |
| **Grade B** | 40 | 15% | 28% | 1.87:1 |

**Research**: Professional intraday traders target 2.5:1–3:1 R:R. Grade A at 1.75:1 is the minimum for positive expectancy at a 40% win rate. Tighter gates (score ≥70 to execute) raise win rate toward 55–65%, making 1.75:1 solidly profitable.

---

## 13. DTE-Aware IV Hard Gates

Applied inside the scanner after option selection, before scoring:

| DTE | Max IV Allowed |
|-----|----------------|
| 0 (expiry day) | 95% |
| 1 | 88% |
| 2–3 | 80% |
| 4+ | 75% |

Rationale: Near-expiry options have extreme theta decay; high IV on top of that destroys long-option edge. Tighter IV limit for longer DTE because there's no urgency premium justification.

---

## 14. Research Basis Summary

| Decision | Research Finding | Source |
|----------|-----------------|--------|
| ADX gate = 20 (was 15) | ADX < 20 = weak/absent trend; filtering drawdown –18% | StatOasis backtests |
| RSI sweet spot 55–70 LONG | Momentum building not exhausted; best premium entry | AIMarketAnalyzer gates |
| MACD gate required | MACD+RSI combo achieves 73% win rate | Trading research |
| PCR 1.0–1.3 = bullish | NSE NIFTY oscillates 0.8–1.3; >1.3 = institutional long | NSE options data |
| VIX ≥ 22 hard gate | Options buyers severely overpay IV in fear zone | India VIX research |
| VWAP Sharpe 2.1 | Best intraday signal; 1.50 regime multiplier in trending | Quant research |
| Prime time 10–11:30 | Post-open momentum = directional institutional flow | AIMarketAnalyzer |
| OFI confluence +3 | Dual confirmation (OI + PCR) materially improves win rate | NSE F&O studies |
| Score gate 70 | Top-decile signals have statistically significant edge | SEBI/options research |
| Grade A RR 1.75:1 | Minimum for positive expectancy at 40% win rate | Risk management |
| Opening vol gate 09:15–09:30 | Price discovery chaos, IV dislocated | Practitioner knowledge |
| Expiry gamma gate 0-DTE after 11:00 | Gamma destroys long options in final hours | Options Greeks research |

---

## 15. Effective Score Contribution at Maximum (Trending Bullish Regime)

| Component | Max Raw | Multiplier | Max Effective | % of Total |
|-----------|---------|------------|---------------|------------|
| OI_BUILDUP | 25 | 1.15 | 28.75 | 26% |
| TREND | 20 | 1.40 | 28.00 | 25% |
| OPTION_CHAIN | 20 | 0.85 | 17.00 | 15% |
| VOLUME | 15 | 1.25 | 18.75 | 17% |
| VWAP | 10 | 1.50 | 15.00 | 13% |
| SENTIMENT | 5 | 0.40 | 2.00 | 2% |
| IV_ANALYSIS | 5 | 0.45 | 2.25 | 2% |
| **Total** | **100** | — | **111.75** | **100%** |

Scores are normalized to 0–100 before gate comparison. In TRENDING_BULLISH regime, **OI_BUILDUP + TREND + VOLUME together represent 68% of the effective score** — confirming institutional flow is the dominant filter.

---

*This file is auto-maintained alongside strategy.yaml. Update both when thresholds change.*
